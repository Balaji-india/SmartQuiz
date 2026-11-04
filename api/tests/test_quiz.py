"""P05: selection, generation, gates, duplicates, the request budget, QuizOut hiding, progress and metrics (FAKE LLM)."""
import json
import uuid

import numpy as np
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.llm import provider
from app.models import Fact, GenerationLog, Question, Quiz
from app.quiz import job
from app.quiz.dedup import DuplicateChecker, fingerprint
from app.quiz.generate import validate
from app.quiz.select import Target, select_targets
from tests.quiz_helpers import make_quiz, ready_document

FORBIDDEN_KEYS = {"answer_index", "target_fact_idx", "correct_index"}


@pytest.fixture
def calls(monkeypatch):
    """Records every LLM call (role, task, attempt) and lets a test rewrite FAKE replies."""
    real = provider.generate_json
    log: list[tuple[str, str, int]] = []
    rewrites = []

    def spy(role, system, user, attempt=0):
        task = system.split("]", 1)[0] + "]"
        reply = real(role, system, user, attempt)
        if task in (provider.TASK_EXTRACT_FACTS, provider.TASK_CHECK_FAITHFULNESS):
            return reply  # ingestion, not part of the quiz budget
        log.append((role, task, attempt))
        for rewrite in rewrites:
            reply = rewrite(task, json.loads(user), attempt, reply)
        return reply

    for module in ("app.quiz.generate", "app.quiz.gates"):
        monkeypatch.setattr(f"{module}.provider.generate_json", spy)
    spy.log, spy.rewrites = log, rewrites
    return spy


def _keys(obj) -> set:
    if isinstance(obj, dict):
        return set(obj) | {k for v in obj.values() for k in _keys(v)}
    if isinstance(obj, list):
        return {k for v in obj for k in _keys(v)}
    return set()


def _targets(test_engine, quiz_id) -> list[int]:
    with Session(test_engine) as db:
        return db.scalars(select(Question.target_fact_idx).where(Question.quiz_id == uuid.UUID(quiz_id))).all()


# --- endpoints -----------------------------------------------------------------------------


def test_post_returns_generating_immediately_then_becomes_ready(client):
    headers, doc_id = ready_document(client)
    created = make_quiz(client, headers, doc_id)
    assert created["status"] == "generating"
    assert created["questions"] == [] and created["generation"] is None
    assert created["quiz_hash"] is None and created["commit_tx"] is None and created["chain_status"] == "pending"

    quiz = client.get(f"/quizzes/{created['id']}", headers=headers).json()
    assert quiz["status"] == "ready"
    assert quiz["questions"] == []  # not started yet
    assert quiz["generation"]["accepted"] == 5
    assert quiz["quiz_hash"].startswith("0x") and quiz["chain_status"] == "offline"


def test_progress_shape(client):
    headers, doc_id = ready_document(client)
    quiz_id = make_quiz(client, headers, doc_id)["id"]
    progress = client.get(f"/quizzes/{quiz_id}/progress", headers=headers).json()
    assert set(progress) == {"accepted", "rejected", "target", "stage"}
    assert progress["stage"] == "done" and progress["accepted"] == 5 and progress["target"] == 5


def test_start_returns_questions_without_answers_and_keeps_the_first_start(client):
    headers, doc_id = ready_document(client)
    quiz_id = make_quiz(client, headers, doc_id)["id"]
    started = client.post(f"/quizzes/{quiz_id}/start", headers=headers).json()
    assert len(started["questions"]) == 5
    assert not _keys(started) & FORBIDDEN_KEYS
    assert all(q["fact_idxs"] is None for q in started["questions"])
    assert [q["position"] for q in started["questions"]] == [1, 2, 3, 4, 5]
    again = client.post(f"/quizzes/{quiz_id}/start", headers=headers).json()
    assert again["started_at"] == started["started_at"]


def test_start_refuses_unless_ready(client, test_engine):
    headers, doc_id = ready_document(client)
    quiz_id = make_quiz(client, headers, doc_id)["id"]
    with test_engine.begin() as conn:
        conn.execute(text("UPDATE quizzes SET status='generating' WHERE id=:id"), {"id": quiz_id})
    assert client.post(f"/quizzes/{quiz_id}/start", headers=headers).status_code == 409
    assert client.get(f"/quizzes/{quiz_id}", headers=headers).json()["questions"] == []


def test_quiz_needs_own_ready_document(client):
    headers, doc_id = ready_document(client)
    other, _ = ready_document(client, "other@b.com")
    assert client.post("/quizzes", json={"document_id": doc_id}, headers=other).status_code == 404
    quiz_id = make_quiz(client, headers, doc_id)["id"]
    assert client.get(f"/quizzes/{quiz_id}", headers=other).status_code == 404


def test_second_quiz_has_zero_repeated_targets_and_fingerprints(client, test_engine):
    headers, doc_id = ready_document(client)
    first = make_quiz(client, headers, doc_id, n=8)["id"]
    second = make_quiz(client, headers, doc_id, n=8)["id"]
    t1, t2 = _targets(test_engine, first), _targets(test_engine, second)
    assert len(t1) == len(t2) == 8
    assert not set(t1) & set(t2)
    with Session(test_engine) as db:
        fps = db.scalars(select(Question.fingerprint)).all()
    assert len(fps) == len(set(fps)) == 16
    metrics = client.get(f"/metrics/{doc_id}", headers=headers).json()
    assert metrics["repeat_rate_between_quizzes"] == 0.0


def test_targets_spread_across_sections(client, test_engine):
    headers, doc_id = ready_document(client)
    quiz_id = make_quiz(client, headers, doc_id, n=8)["id"]
    with Session(test_engine) as db:
        sections = db.scalars(
            select(Fact.section_id).where(
                Fact.document_id == uuid.UUID(doc_id), Fact.idx.in_(_targets(test_engine, quiz_id))
            )
        ).all()
    assert sorted(np.unique(sections, return_counts=True)[1].tolist()) == [2, 2, 2, 2]


def test_one_generator_call_when_everything_passes(client, calls):
    headers, doc_id = ready_document(client)
    make_quiz(client, headers, doc_id)
    generator = [c for c in calls.log if c[0] == "generator"]
    assert generator == [("generator", provider.TASK_GENERATE_QUESTIONS, 0)]
    checker_tasks = sorted(c[1] for c in calls.log if c[0] == "checker")
    assert checker_tasks == sorted([provider.TASK_GATE_GROUNDING, provider.TASK_GATE_SOLVABILITY, provider.TASK_GATE_DEPENDENCE])


def _fail_gate1_for(calls, targets: set, attempts: set):
    def rewrite(task, user, attempt, reply):
        if task != provider.TASK_GATE_GROUNDING:
            return reply
        for item, result in zip(user["items"], reply["results"]):
            fact_idx = int(item["stem"].rsplit("(fact ", 1)[1].split(",")[0])
            if fact_idx in targets and int(item["stem"].rsplit("try ", 1)[1].rstrip(")")) in attempts:
                result["verdict"], result["reason"] = "NOT_SUPPORTED", "answer not stated in facts"
        return reply

    calls.rewrites.append(rewrite)


def test_failures_share_one_batched_regeneration_with_attempt_1(client, calls, test_engine):
    headers, doc_id = ready_document(client)
    # 5 questions + 2 spares = 7 targets; fail 4 of them on the first try, so a retry is needed.
    _fail_gate1_for(calls, set(range(24)), {0})
    quiz = make_quiz(client, headers, doc_id)
    generator = [c for c in calls.log if c[0] == "generator"]
    assert generator == [
        ("generator", provider.TASK_GENERATE_QUESTIONS, 0),
        ("generator", provider.TASK_GENERATE_QUESTIONS, 1),
    ]
    assert client.get(f"/quizzes/{quiz['id']}", headers=headers).json()["generation"]["accepted"] == 5
    with Session(test_engine) as db:
        stems = db.scalars(select(Question.stem)).all()
    assert all("try 1" in s for s in stems)


def test_target_failing_twice_is_dropped(client, calls, test_engine):
    headers, doc_id = ready_document(client)
    _fail_gate1_for(calls, set(range(24)), {0, 1})  # everything fails both times
    quiz = make_quiz(client, headers, doc_id)
    assert len([c for c in calls.log if c[0] == "generator"]) == 2
    body = client.get(f"/quizzes/{quiz['id']}", headers=headers).json()
    assert body["status"] == "failed"
    with Session(test_engine) as db:
        gate1 = db.scalars(select(GenerationLog).where(GenerationLog.gate == "gate1")).all()
    assert len(gate1) == 14 and not any(r.passed for r in gate1)
    metrics = client.get(f"/metrics/{doc_id}", headers=headers).json()
    assert metrics["rejected_by_gate"]["gate1"] == 14
    assert metrics["top_reasons"][0]["count"] == 14 and "answer not stated" in metrics["top_reasons"][0]["reason"]


def test_gate3_wrong_choice_rejects(client, calls, test_engine):
    headers, doc_id = ready_document(client)

    def rewrite(task, user, attempt, reply):
        if task == provider.TASK_GATE_SOLVABILITY:
            for result, item in zip(reply["results"], user["items"]):
                if item["stem"].endswith("try 0)"):  # first round only
                    result["choice"] = (result["choice"] + 1) % 4
        return reply

    calls.rewrites.append(rewrite)
    make_quiz(client, headers, doc_id)
    with Session(test_engine) as db:
        gate3 = db.scalars(select(GenerationLog).where(GenerationLog.gate == "gate3")).all()
        questions = db.scalars(select(Question)).all()
    assert sum(not r.passed for r in gate3) == 7  # all of the first round
    assert len(questions) == 5
    assert all(q.gate_results["gate3"]["passed"] and q.gate_results["gate3"]["choice"] == q.answer_index for q in questions)


def test_gate_results_shape_and_dependence(client, calls, test_engine):
    headers, doc_id = ready_document(client)

    def rewrite(task, user, attempt, reply):
        if task == provider.TASK_GATE_DEPENDENCE:
            # The blind checker "knows" every answer with 90% confidence: shown option = the fact text.
            for result, item in zip(reply["results"], user["items"]):
                stem_fact = item["stem"].split(": which option", 1)[0]
                result["choice"] = next(i for i, o in enumerate(item["options"]) if o.rstrip(".") == stem_fact)
                result["confidence"] = 90
        return reply

    calls.rewrites.append(rewrite)
    make_quiz(client, headers, doc_id)
    with Session(test_engine) as db:
        questions = db.scalars(select(Question)).all()
    for q in questions:
        assert set(q.gate_results) == {"gate1", "gate3", "gate4"}
        assert q.gate_results["gate1"]["verdict"] == "SUPPORTED"
        assert q.gate_results["gate4"] == {"choice": q.answer_index, "confidence": 90, "reason": "fake"}
        assert q.dependence_score == pytest.approx(0.1) and q.flagged_general
    metrics = client.get(f"/metrics/{doc_id}", headers=headers).json()
    assert metrics["flagged_general"] == 5 and metrics["avg_dependence"] == pytest.approx(0.1)


def test_same_family_checker_is_logged_and_shown(client, test_engine, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_generator_model", "openai/gpt-oss-120b")
    monkeypatch.setattr(settings, "llm_checker_model", "openai/gpt-oss-20b")
    headers, doc_id = ready_document(client)
    make_quiz(client, headers, doc_id)
    with Session(test_engine) as db:
        rows = db.execute(select(GenerationLog.gate, GenerationLog.same_family_fallback)).all()
    assert all(flag for gate, flag in rows if gate.startswith("gate"))
    metrics = client.get(f"/metrics/{doc_id}", headers=headers).json()
    assert metrics["same_family_checker_used"] is True
    assert metrics["same_family_gate_calls"] == sum(1 for gate, _ in rows if gate.startswith("gate"))


def test_metrics_exclude_ingestion_checks(client):
    headers, doc_id = ready_document(client)
    metrics = client.get(f"/metrics/{doc_id}", headers=headers).json()
    assert metrics["candidates"] == 0 and metrics["rejected_by_gate"] == {"gate1": 0, "gate3": 0}
    assert metrics["same_family_checker_used"] is False


# --- selection -----------------------------------------------------------------------------


def _add_question(db, quiz, position, target_idx, fact_idxs, bloom="remember"):
    db.add(
        Question(
            quiz_id=quiz.id, position=position, stem=f"q{position}", options=["a", "b", "c", "d"], answer_index=0,
            fact_idxs=fact_idxs, target_fact_idx=target_idx, bloom_level=bloom,
            fingerprint=fingerprint(fact_idxs, bloom), gate_results={}, dependence_score=1.0,
            stem_embedding=[0.0] * 384,
        )
    )


def test_earlier_quiz_without_attempt_counts_as_used_but_context_facts_do_not(client, test_engine):
    headers, doc_id = ready_document(client)
    with Session(test_engine) as db:
        user_id = db.scalar(text("SELECT id FROM users"))
        quiz = Quiz(user_id=user_id, document_id=uuid.UUID(doc_id), status="ready", time_limit_sec=600)
        db.add(quiz)
        db.flush()
        _add_question(db, quiz, 1, target_idx=0, fact_idxs=[0, 1])  # idx 1 is only context
        db.commit()
        targets = select_targets(db, user_id, uuid.UUID(doc_id), 23, "seed")
    idxs = {t.fact.idx for t in targets if t.tier == 1}
    assert 0 not in idxs and 1 in idxs


def test_failed_quiz_does_not_count_as_used(client, test_engine):
    headers, doc_id = ready_document(client)
    with Session(test_engine) as db:
        user_id = db.scalar(text("SELECT id FROM users"))
        quiz = Quiz(user_id=user_id, document_id=uuid.UUID(doc_id), status="failed", time_limit_sec=600)
        db.add(quiz)
        db.flush()
        _add_question(db, quiz, 1, target_idx=0, fact_idxs=[0])
        db.commit()
        targets = select_targets(db, user_id, uuid.UUID(doc_id), 24, "seed")
    assert 0 in {t.fact.idx for t in targets if t.tier == 1}


def test_at_most_two_targets_per_concept(client, test_engine):
    headers, doc_id = ready_document(client)
    with test_engine.begin() as conn:
        conn.execute(text("UPDATE facts SET concept='Same thing'"))
    with Session(test_engine) as db:
        user_id = db.scalar(text("SELECT id FROM users"))
        targets = select_targets(db, user_id, uuid.UUID(doc_id), 10, "seed")
    assert len(targets) == 2


def test_retest_asks_for_the_other_bloom_level(client, test_engine):
    headers, doc_id = ready_document(client)
    with Session(test_engine) as db:
        user_id = db.scalar(text("SELECT id FROM users"))
        quiz = Quiz(user_id=user_id, document_id=uuid.UUID(doc_id), status="ready", time_limit_sec=600)
        db.add(quiz)
        db.flush()
        for i in range(24):  # every fact used once as a "remember" target, never answered
            _add_question(db, quiz, i + 1, target_idx=i, fact_idxs=[i])
        db.commit()
        targets = select_targets(db, user_id, uuid.UUID(doc_id), 5, "seed")
    assert len(targets) == 5
    assert all(t.tier == 3 and t.bloom_level == "understand" and t.previous_bloom == "remember" for t in targets)


# --- validation and duplicates -------------------------------------------------------------


def _target(idx=5):
    fact = Fact(idx=idx, text="t", concept="c", section_id=1)
    return Target(fact, 1, "remember", None)


@pytest.mark.parametrize(
    "raw, error",
    [
        (None, "no question"),
        ({"stem": "", "options": ["a", "b", "c", "d"], "answer_index": 0, "fact_idxs": [5]}, "empty stem"),
        ({"stem": "s", "options": ["a", "b", "c"], "answer_index": 0, "fact_idxs": [5]}, "4 non-empty"),
        ({"stem": "s", "options": ["a", "A", "c", "d"], "answer_index": 0, "fact_idxs": [5]}, "not distinct"),
        ({"stem": "s", "options": ["a", "b", "c", "d"], "answer_index": 4, "fact_idxs": [5]}, "0-3"),
        ({"stem": "s", "options": ["a", "b", "c", "d"], "answer_index": True, "fact_idxs": [5]}, "0-3"),
        ({"stem": "s", "options": ["a", "b", "c", "d"], "answer_index": 0, "fact_idxs": [99]}, "outside"),
        ({"stem": "s", "options": ["a", "b", "c", "d"], "answer_index": 0, "fact_idxs": [5, 6, 7, 8]}, "more than"),
    ],
)
def test_validation_rejects_bad_shapes(raw, error):
    assert error in validate(raw, _target(), {5, 6, 7, 8}).error


def test_validation_adds_the_target_and_sorts():
    c = validate({"stem": "s", "options": ["a", "b", "c", "d"], "answer_index": 2, "fact_idxs": [7]}, _target(), {5, 7})
    assert c.error is None and c.fact_idxs == [5, 7] and c.bloom_level == "remember"


def test_fingerprint_matches_spec_example():
    import hashlib

    assert fingerprint([216, 214], "remember") == hashlib.sha256(b"214,216|remember").hexdigest()


def test_duplicate_checker_fingerprint_then_cosine(client, test_engine):
    headers, doc_id = ready_document(client)
    with Session(test_engine) as db:
        user_id = db.scalar(text("SELECT id FROM users"))
        checker = DuplicateChecker(db, user_id, uuid.UUID(doc_id))
    v = np.zeros(384, dtype=np.float32)
    v[0] = 1.0
    assert checker.check("fp", v) == (None, "")
    checker.add("fp", v)
    assert checker.check("fp", v)[0] == "dup_fingerprint"
    near = v.copy()
    near[1] = 0.3
    near /= np.linalg.norm(near)
    assert checker.check("other", near)[0] == "dup_cosine"
    far = np.zeros(384, dtype=np.float32)
    far[2] = 1.0
    assert checker.check("other", far) == (None, "")


def test_cosine_duplicate_is_logged_and_blocked(client, calls, test_engine, monkeypatch):
    headers, doc_id = ready_document(client)
    make_quiz(client, headers, doc_id)
    # Every new stem embeds identically to an earlier one.
    with Session(test_engine) as db:
        earlier = np.asarray(db.scalars(select(Question.stem_embedding)).first(), dtype=np.float32)
    monkeypatch.setattr(job, "embed_texts", lambda texts: np.stack([earlier] * len(texts)))
    quiz = make_quiz(client, headers, doc_id)
    assert client.get(f"/quizzes/{quiz['id']}", headers=headers).json()["status"] == "failed"
    metrics = client.get(f"/metrics/{doc_id}", headers=headers).json()
    assert metrics["duplicates_blocked"]["cosine"] == 7


def test_server_shuffles_option_positions_and_keeps_the_answer():
    raw = {"stem": "s", "options": ["right", "w1", "w2", "w3"], "answer_index": 0, "fact_idxs": [5]}
    positions = set()
    for _ in range(40):
        c = validate(raw, _target(), {5})
        assert c.options[c.answer_index] == "right" and sorted(c.options) == sorted(raw["options"])
        positions.add(c.answer_index)
    assert positions == {0, 1, 2, 3}
