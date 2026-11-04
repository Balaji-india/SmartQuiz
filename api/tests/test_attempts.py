"""P06: quiz_hash, on-chain commit before ready, timed attempts, scoring and fact coverage."""
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from eth_utils import keccak
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.chain import quizhash
from app.chain.service import chain_id_of
from app.config import get_settings
from app.models import Fact, FactCoverage, Question, Quiz
from tests.quiz_helpers import make_quiz, ready_document


def _questions(test_engine, quiz_id):
    with Session(test_engine) as db:
        return db.scalars(select(Question).where(Question.quiz_id == uuid.UUID(quiz_id)).order_by(Question.position)).all()


def _answer_key(test_engine, quiz_id):
    return [q.answer_index for q in _questions(test_engine, quiz_id)]


# --- quiz_hash -----------------------------------------------------------------------------


def test_quiz_hash_matches_the_spec_format():
    q = {"position": 1, "stem": "Stem é", "options": ["a", "b", "c", "d"], "answer_index": 2, "fact_idxs": [3, 7],
         "gate_results": {"gate1": {"verdict": "SUPPORTED", "reason": "r"}}}
    expected = (
        '{"questions":[{"answer_index":2,"fact_idxs":[3,7],"gate_results":{"gate1":{"reason":"r","verdict":"SUPPORTED"}},'
        '"options":["a","b","c","d"],"stem":"Stem é"}],"salt":"00ff"}'
    )
    assert quizhash.canonical_json([q], "00ff") == expected.encode("utf-8")
    assert quizhash.quiz_hash([q], "00ff") == "0x" + keccak(expected.encode("utf-8")).hex()


def test_quiz_hash_follows_position_order_and_every_hashed_field():
    a = {"position": 1, "stem": "A", "options": ["1", "2", "3", "4"], "answer_index": 0, "fact_idxs": [1], "gate_results": {}}
    b = {**a, "position": 2, "stem": "B"}
    base = quizhash.quiz_hash([a, b], "aa")
    assert quizhash.quiz_hash([b, a], "aa") == base  # input order does not matter, position does
    assert quizhash.quiz_hash([{**a, "position": 3}, b], "aa") != base
    for field, value in [("stem", "A!"), ("options", ["1", "2", "3", "5"]), ("answer_index", 1), ("fact_idxs", [2]),
                         ("gate_results", {"gate4": {"confidence": 1}})]:
        assert quizhash.quiz_hash([{**a, field: value}, b], "aa") != base, field
    assert quizhash.quiz_hash([a, b], "ab") != base
    # Not hashed: bloom level, dependence, flags, target.
    assert quizhash.quiz_hash([{**a, "bloom_level": "understand", "target_fact_idx": 9}, b], "aa") == base


def test_salt_is_32_lowercase_hex():
    salt = quizhash.new_salt()
    assert len(salt) == 32 and salt == salt.lower() and int(salt, 16) >= 0


def test_stored_quiz_hash_recomputes_and_changes_after_tampering(client, test_engine):
    headers, doc_id = ready_document(client)
    quiz_id = make_quiz(client, headers, doc_id)["id"]
    with Session(test_engine) as db:
        quiz = db.get(Quiz, uuid.UUID(quiz_id))
    questions = _questions(test_engine, quiz_id)
    assert len(quiz.salt) == 32
    assert quizhash.quiz_hash(questions, quiz.salt) == quiz.quiz_hash
    with test_engine.begin() as conn:
        conn.execute(text("UPDATE questions SET stem = stem || ' ' WHERE quiz_id = :q AND position = 2"), {"q": quiz_id})
    assert quizhash.quiz_hash(_questions(test_engine, quiz_id), quiz.salt) != quiz.quiz_hash


# --- chain commit --------------------------------------------------------------------------


def test_quiz_is_committed_on_chain_before_ready(client, local_chain, test_engine):
    headers, doc_id = ready_document(client)
    quiz_id = make_quiz(client, headers, doc_id)["id"]
    quiz = client.get(f"/quizzes/{quiz_id}", headers=headers).json()
    assert quiz["status"] == "ready" and quiz["chain_status"] == "confirmed"
    assert quiz["commit_tx"].startswith("0x") and quiz["explorer_url"] is None  # local chain
    doc_on_chain, hash_on_chain, at = local_chain.get_quiz(quiz_id)
    assert doc_on_chain == chain_id_of(doc_id) and hash_on_chain == quiz["quiz_hash"] and at > 0


def test_required_chain_down_fails_the_quiz(client, chain_down, monkeypatch):
    headers, doc_id = ready_document(client)
    monkeypatch.setattr(get_settings(), "chain_optional", False)
    quiz_id = make_quiz(client, headers, doc_id)["id"]
    quiz = client.get(f"/quizzes/{quiz_id}", headers=headers).json()
    assert quiz["status"] == "failed"
    assert client.post(f"/quizzes/{quiz_id}/start", headers=headers).status_code == 409


def test_optional_chain_down_is_ready_and_offline(client, chain_down):
    headers, doc_id = ready_document(client)
    quiz = client.get(f"/quizzes/{make_quiz(client, headers, doc_id)['id']}", headers=headers).json()
    assert quiz["status"] == "ready" and quiz["chain_status"] == "offline" and quiz["commit_tx"] is None
    assert quiz["quiz_hash"].startswith("0x")


def test_uncommitted_quiz_refuses_attempts_when_chain_is_required(client, monkeypatch):
    headers, doc_id = ready_document(client)
    quiz_id = make_quiz(client, headers, doc_id)["id"]  # chain optional and unconfigured → offline
    client.post(f"/quizzes/{quiz_id}/start", headers=headers)
    monkeypatch.setattr(get_settings(), "chain_optional", False)
    response = client.post(f"/quizzes/{quiz_id}/attempts", json={"answers": [0] * 5, "time_taken_sec": 5}, headers=headers)
    assert response.status_code == 409 and "committed" in response.json()["detail"]


# --- attempts ------------------------------------------------------------------------------


def test_attempt_before_start_is_refused(client):
    headers, doc_id = ready_document(client)
    quiz_id = make_quiz(client, headers, doc_id)["id"]
    response = client.post(f"/quizzes/{quiz_id}/attempts", json={"answers": [0] * 5, "time_taken_sec": 1}, headers=headers)
    assert response.status_code == 409


def test_generation_and_reading_before_start_do_not_count(client, test_engine):
    headers, doc_id = ready_document(client)
    quiz_id = make_quiz(client, headers, doc_id, time_limit_sec=60)["id"]
    # The quiz was created 10 minutes ago and read since, but only started now.
    with test_engine.begin() as conn:
        conn.execute(text("UPDATE quizzes SET created_at = now() - interval '10 minutes' WHERE id = :q"), {"q": quiz_id})
    client.get(f"/quizzes/{quiz_id}", headers=headers)
    client.post(f"/quizzes/{quiz_id}/start", headers=headers)
    key = _answer_key(test_engine, quiz_id)
    response = client.post(f"/quizzes/{quiz_id}/attempts", json={"answers": key, "time_taken_sec": 30}, headers=headers)
    assert response.status_code == 200 and response.json()["score"] == 5


def test_attempt_after_time_limit_plus_grace_is_refused(client, test_engine):
    headers, doc_id = ready_document(client)
    quiz_id = make_quiz(client, headers, doc_id, time_limit_sec=60)["id"]
    client.post(f"/quizzes/{quiz_id}/start", headers=headers)
    with test_engine.begin() as conn:
        conn.execute(text("UPDATE quizzes SET started_at = now() - interval '91 seconds' WHERE id = :q"), {"q": quiz_id})
    response = client.post(f"/quizzes/{quiz_id}/attempts", json={"answers": [0] * 5, "time_taken_sec": 60}, headers=headers)
    assert response.status_code == 409 and "Time limit" in response.json()["detail"]


def test_scoring_sources_weak_concepts_and_coverage(client, test_engine):
    headers, doc_id = ready_document(client)
    quiz_id = make_quiz(client, headers, doc_id)["id"]
    client.post(f"/quizzes/{quiz_id}/start", headers=headers)
    questions = _questions(test_engine, quiz_id)
    key = [q.answer_index for q in questions]
    answers = [key[0], (key[1] + 1) % 4, None, key[3], key[4]]
    result = client.post(f"/quizzes/{quiz_id}/attempts", json={"answers": answers, "time_taken_sec": 42}, headers=headers).json()

    assert (result["score"], result["total"]) == (3, 5)
    assert [r["correct"] for r in result["results"]] == [True, False, False, True, True]
    assert [r["correct_index"] for r in result["results"]] == key
    assert result["results"][2]["chosen"] is None
    for r, q in zip(result["results"], questions):
        assert [s["idx"] for s in r["sources"]] == sorted(q.fact_idxs)
        assert all(s["text"] and s["page"] >= 1 and s["section"] for s in r["sources"])
    weak_idxs = sorted(i for w in result["weak_concepts"] for i in w["facts"])
    assert weak_idxs == sorted([questions[1].target_fact_idx, questions[2].target_fact_idx])

    with Session(test_engine) as db:
        rows = db.execute(
            select(Fact.idx, FactCoverage.times_tested, FactCoverage.last_correct, FactCoverage.last_bloom).join(
                Fact, Fact.id == FactCoverage.fact_id
            )
        ).all()
    coverage = {r.idx: r for r in rows}
    assert set(coverage) == {q.target_fact_idx for q in questions}  # target facts only
    for q, correct in zip(questions, [True, False, False, True, True]):
        row = coverage[q.target_fact_idx]
        assert (row.times_tested, row.last_correct, row.last_bloom) == (1, correct, q.bloom_level)


def test_context_facts_get_no_coverage_row(client, test_engine, monkeypatch):
    headers, doc_id = ready_document(client)
    quiz_id = make_quiz(client, headers, doc_id)["id"]
    with test_engine.begin() as conn:  # give question 1 a context fact
        conn.execute(text("UPDATE questions SET fact_idxs = array[target_fact_idx, 23] WHERE quiz_id = :q AND position = 1 AND target_fact_idx <> 23"), {"q": quiz_id})
    client.post(f"/quizzes/{quiz_id}/start", headers=headers)
    client.post(f"/quizzes/{quiz_id}/attempts", json={"answers": [0] * 5, "time_taken_sec": 5}, headers=headers)
    with Session(test_engine) as db:
        tested = set(db.scalars(select(Fact.idx).join(FactCoverage, Fact.id == FactCoverage.fact_id)).all())
        targets = set(db.scalars(select(Question.target_fact_idx).where(Question.quiz_id == uuid.UUID(quiz_id))).all())
    assert tested == targets


def test_fact_idxs_hidden_before_attempt_and_shown_after(client, test_engine):
    headers, doc_id = ready_document(client)
    quiz_id = make_quiz(client, headers, doc_id)["id"]
    started = client.post(f"/quizzes/{quiz_id}/start", headers=headers).json()
    assert all(q["fact_idxs"] is None for q in started["questions"]) and started["submitted"] is False
    client.post(f"/quizzes/{quiz_id}/attempts", json={"answers": [0] * 5, "time_taken_sec": 5}, headers=headers)
    after = client.get(f"/quizzes/{quiz_id}", headers=headers).json()
    assert after["submitted"] is True
    stored = {str(q.id): sorted(q.fact_idxs) for q in _questions(test_engine, quiz_id)}
    assert all(q["fact_idxs"] == stored[q["id"]] for q in after["questions"])
    assert "answer_index" not in json.dumps(after)


def test_one_attempt_per_quiz_and_answer_count_checked(client):
    headers, doc_id = ready_document(client)
    quiz_id = make_quiz(client, headers, doc_id)["id"]
    client.post(f"/quizzes/{quiz_id}/start", headers=headers)
    bad = client.post(f"/quizzes/{quiz_id}/attempts", json={"answers": [0] * 4, "time_taken_sec": 5}, headers=headers)
    assert bad.status_code == 422
    out_of_range = client.post(f"/quizzes/{quiz_id}/attempts", json={"answers": [0, 0, 0, 0, 4], "time_taken_sec": 5}, headers=headers)
    assert out_of_range.status_code == 422
    assert client.post(f"/quizzes/{quiz_id}/attempts", json={"answers": [0] * 5, "time_taken_sec": 5}, headers=headers).status_code == 200
    assert client.post(f"/quizzes/{quiz_id}/attempts", json={"answers": [0] * 5, "time_taken_sec": 5}, headers=headers).status_code == 409


def test_once_unused_facts_run_out_wrong_answers_come_first(client, test_engine):
    headers, doc_id = ready_document(client)
    wrong_targets: set[int] = set()
    # 24 facts, 8 per quiz: three quizzes use every fact once. Answer question 1 of each wrong.
    for _ in range(3):
        quiz_id = make_quiz(client, headers, doc_id, n=8)["id"]
        client.post(f"/quizzes/{quiz_id}/start", headers=headers)
        questions = _questions(test_engine, quiz_id)
        answers = [q.answer_index for q in questions]
        answers[0] = (answers[0] + 1) % 4
        wrong_targets.add(questions[0].target_fact_idx)
        client.post(f"/quizzes/{quiz_id}/attempts", json={"answers": answers, "time_taken_sec": 5}, headers=headers)
    # FAKE stems for a retest repeat the first stem, so the cosine check would drop them;
    # this test is about selection, so ask the selector directly.
    from app.quiz.select import select_targets

    with Session(test_engine) as db:
        user_id = db.scalar(text("SELECT id FROM users"))
        bloom = dict(db.execute(select(Question.target_fact_idx, Question.bloom_level)).all())
        targets = select_targets(db, user_id, uuid.UUID(doc_id), 3, "seed")
    assert {t.fact.idx for t in targets} == wrong_targets
    assert all(t.tier == 2 and t.bloom_level != bloom[t.fact.idx] for t in targets)
