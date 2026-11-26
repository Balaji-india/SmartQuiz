"""R01: distractor validation and remap, Gate 2, shared regeneration, quiz hash v2, misconceptions after submit (FAKE LLM)."""
import json
import uuid

import pytest
from eth_utils import keccak
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chain import quizhash
from app.llm import provider
from app.models import Fact, GenerationLog, Question, Quiz
from app.quiz import gates
from app.quiz.generate import Candidate, validate
from app.quiz.select import Target
from tests.quiz_helpers import make_quiz, ready_document
from tests.test_quiz import calls  # noqa: F401  (fixture)

FIXTURE_V1 = "tests/data/quiz_v1.json"


def _target(idx=5):
    return Target(Fact(idx=idx, text="t", concept="c", section_id=1), 1, "remember", None)


def _raw(answer=0, distractors=None):
    if distractors is None:
        distractors = [{"option": k, "fact_idxs": [6], "misconception": f"confuses w{k} with right"} for k in range(4) if k != answer]
    options = [f"w{k}" for k in range(4)]
    options[answer] = "right"
    return {"stem": "s", "options": options, "answer_index": answer, "fact_idxs": [5], "distractors": distractors}


def _stem_fact(stem: str) -> int:
    return int(stem.rsplit("(fact ", 1)[1].split(",")[0])


def _stem_try(stem: str) -> int:
    return int(stem.rsplit("try ", 1)[1].rstrip(")"))


# --- validation and remap ------------------------------------------------------------------

D = {"fact_idxs": [6], "misconception": "m"}


@pytest.mark.parametrize(
    "distractors, error",
    [
        (None, "must be a list"),
        ([{"option": 1, **D}, {"option": 2, **D}], "every wrong option"),
        ([{"option": 1, **D}, {"option": 1, **D}, {"option": 2, **D}], "duplicated"),
        ([{"option": 0, **D}, {"option": 1, **D}, {"option": 2, **D}], "points at the answer"),
        ([{"option": 4, **D}, {"option": 1, **D}, {"option": 2, **D}], "0-3"),
        ([{"option": 1, "fact_idxs": [], "misconception": "m"}, {"option": 2, **D}, {"option": 3, **D}], "non-empty"),
        ([{"option": 1, "fact_idxs": [99], "misconception": "m"}, {"option": 2, **D}, {"option": 3, **D}], "outside"),
        ([{"option": 1, "fact_idxs": [6], "misconception": " "}, {"option": 2, **D}, {"option": 3, **D}], "empty"),
        ([{"option": 1, "fact_idxs": [6], "misconception": "w " * 13}, {"option": 2, **D}, {"option": 3, **D}], "over 12 words"),
        (["x", {"option": 2, **D}, {"option": 3, **D}], "not an object"),
    ],
)
def test_distractor_validation_rejects_bad_entries(distractors, error):
    raw = _raw(0)
    raw["distractors"] = distractors
    c = validate(raw, _target(), {5, 6})
    assert c.error and error in c.error


def test_distractor_may_cite_any_offered_context_fact_and_twelve_words_is_fine():
    raw = _raw(0, [{"option": k, "fact_idxs": [7, 6, 6], "misconception": "one two three four five six seven eight nine ten eleven twelve"} for k in (1, 2, 3)])
    c = validate(raw, _target(), {5, 6, 7})
    assert c.error is None and all(d["fact_idxs"] == [6, 7] for d in c.distractors)


def test_distractor_options_are_remapped_after_the_shuffle():
    for answer in range(4):
        for _ in range(20):
            raw = _raw(answer)
            c = validate(raw, _target(), {5, 6})
            assert c.error is None
            assert [d["option"] for d in c.distractors] == sorted(k for k in range(4) if k != c.answer_index)
            for d in c.distractors:
                # The label still describes the option text it was written for.
                assert d["misconception"] == f"confuses {c.options[d['option']]} with right"


# --- Gate 2 unit ---------------------------------------------------------------------------


def _candidate() -> Candidate:
    c = validate(_raw(0), _target(), {5, 6})
    assert c.error is None
    return c


def _fake_checker(monkeypatch, reply_for):
    seen = []

    def fake(role, system, user, attempt=0):
        seen.append((json.loads(user), attempt))
        return reply_for(json.loads(user), attempt)

    monkeypatch.setattr(gates.provider, "generate_json", fake)
    return seen


def test_gate2_payload_and_pass(monkeypatch):
    c = _candidate()
    seen = _fake_checker(
        monkeypatch, lambda u, a: {"results": [{"id": i["id"], "verdicts": [{"d": d["d"], "verdict": "FALSE"} for d in i["distractors"]]} for i in u["items"]]}
    )
    gates.gate2_distractors([c], {5: "target fact", 6: "context fact"})
    item = seen[0][0]["items"][0]
    assert item["facts"] == [{"idx": 5, "text": "target fact"}, {"idx": 6, "text": "context fact"}]
    assert item["answer"] == "right"
    assert [d["text"] for d in item["distractors"]] == [c.options[d["option"]] for d in c.distractors]
    g2 = c.gate_results["gate2"]
    assert g2["passed"] and g2["verdicts"] == [{"option": d["option"], "verdict": "FALSE"} for d in c.distractors]
    assert gates.passed_gate2(c)


@pytest.mark.parametrize("bad", ["TRUE", "UNSUPPORTED", "SAME_AS_ANSWER", "maybe"])
def test_gate2_fails_unless_every_verdict_is_false(monkeypatch, bad):
    c = _candidate()
    _fake_checker(
        monkeypatch,
        lambda u, a: {"results": [{"id": 0, "verdicts": [{"d": 0, "verdict": "FALSE"}, {"d": 1, "verdict": bad}, {"d": 2, "verdict": "FALSE"}]}]},
    )
    gates.gate2_distractors([c], {5: "a", 6: "b"})
    g2 = c.gate_results["gate2"]
    assert not g2["passed"]
    assert g2["verdicts"][1]["verdict"] == (bad if bad != "maybe" else "UNSUPPORTED")
    assert f"option {c.distractors[1]['option']}" in g2["reason"]  # reason filled in when the checker gave none


def test_gate2_missing_verdict_for_one_distractor_fails_closed(monkeypatch):
    c = _candidate()
    _fake_checker(monkeypatch, lambda u, a: {"results": [{"id": 0, "verdicts": [{"d": 0, "verdict": "FALSE"}, {"d": 1, "verdict": "FALSE"}]}]})
    gates.gate2_distractors([c], {5: "a", 6: "b"})
    assert not c.gate_results["gate2"]["passed"]


def test_gate2_missing_id_is_retried_once_with_attempt_1_then_fails_closed(monkeypatch):
    c1, c2 = _candidate(), _candidate()
    all_false = lambda i: {"id": i["id"], "verdicts": [{"d": d["d"], "verdict": "FALSE"} for d in i["distractors"]]}
    # id 1 never comes back.
    seen = _fake_checker(monkeypatch, lambda u, a: {"results": [all_false(i) for i in u["items"] if i["id"] != 1]})
    gates.gate2_distractors([c1, c2], {5: "a", 6: "b"})
    assert [(len(u["items"]), a) for u, a in seen] == [(2, 0), (1, 1)]
    assert c1.gate_results["gate2"]["passed"]
    assert not c2.gate_results["gate2"]["passed"] and c2.gate_results["gate2"]["reason"] == gates.NO_VERDICT

    # Missing only on the first call: the retry recovers it.
    c3 = _candidate()
    seen = _fake_checker(monkeypatch, lambda u, a: {"results": [all_false(i) for i in u["items"]] if a else []})
    gates.gate2_distractors([c3], {5: "a", 6: "b"})
    assert [a for _, a in seen] == [0, 1] and c3.gate_results["gate2"]["passed"]


# --- in the job ----------------------------------------------------------------------------


def test_distractors_are_stored_in_shown_order_with_gate2_results(client, test_engine):
    headers, doc_id = ready_document(client)
    make_quiz(client, headers, doc_id)
    with Session(test_engine) as db:
        questions = db.scalars(select(Question)).all()
        gate2 = db.scalars(select(GenerationLog).where(GenerationLog.gate == "gate2")).all()
    assert len(questions) == 5 and len(gate2) == 7 and all(r.passed for r in gate2)
    for q in questions:
        assert [d["option"] for d in q.distractors] == [k for k in range(4) if k != q.answer_index]
        for d in q.distractors:
            assert q.options[d["option"]].startswith("Option ")  # FAKE wrong options, not the fact text
            assert d["misconception"].endswith(f"option {q.options[d['option']].split()[1]}")
        g2 = q.gate_results["gate2"]
        assert g2["passed"] and [v["option"] for v in g2["verdicts"]] == [d["option"] for d in q.distractors]


def test_gate2_failures_join_the_one_regeneration(client, calls, test_engine):
    headers, doc_id = ready_document(client)

    def rewrite(task, user, attempt, reply):
        # First generation round: gate1 fails fact 0's question, gate2 fails every other first-round question but one,
        # gate3 fails that one. Everything passes on the retry.
        stems = {item["id"]: item["stem"] for item in user.get("items", []) if "stem" in item}
        for result in reply.get("results", []) if isinstance(reply, dict) else []:
            stem = stems.get(result.get("id"), "")
            if not stem or _stem_try(stem) != 0:
                continue
            fact = _stem_fact(stem)
            if task == provider.TASK_GATE_DISTRACTORS and fact % 3 == 0:
                result["verdicts"][0]["verdict"] = "TRUE"
                result["reason"] = "the facts make it correct too"
            if task == provider.TASK_GATE_GROUNDING and fact % 3 == 1:
                result["verdict"] = "NOT_SUPPORTED"
            if task == provider.TASK_GATE_SOLVABILITY and fact % 3 == 2:
                result["choice"] = (result["choice"] + 1) % 4
        return reply

    calls.rewrites.append(rewrite)
    quiz = make_quiz(client, headers, doc_id)
    generator = [c for c in calls.log if c[0] == "generator"]
    assert generator == [
        ("generator", provider.TASK_GENERATE_QUESTIONS, 0),
        ("generator", provider.TASK_GENERATE_QUESTIONS, 1),
    ]
    # Checker calls stay batched: one per gate per round, plus one gate-4 call.
    checker = [c for c in calls.log if c[0] == "checker"]
    assert len(checker) == 3 * 2 + 1
    assert client.get(f"/quizzes/{quiz['id']}", headers=headers).json()["generation"]["accepted"] == 5
    with Session(test_engine) as db:
        rejected = db.execute(select(GenerationLog.gate).where(GenerationLog.passed.is_(False))).scalars().all()
    assert {"gate1", "gate2", "gate3"} <= set(rejected) and len(rejected) == 7
    metrics = client.get(f"/metrics/{doc_id}", headers=headers).json()
    assert metrics["rejected_by_gate"]["gate2"] == rejected.count("gate2") > 0
    assert any(r["gate"] == "gate2" and "correct too" in r["reason"] for r in metrics["top_reasons"])


def test_gate2_missing_everywhere_fails_closed_and_still_two_generator_calls(client, calls):
    headers, doc_id = ready_document(client)

    def rewrite(task, user, attempt, reply):
        return {"results": []} if task == provider.TASK_GATE_DISTRACTORS else reply

    calls.rewrites.append(rewrite)
    quiz = make_quiz(client, headers, doc_id)
    assert len([c for c in calls.log if c[0] == "generator"]) == 2
    gate2_calls = [c for c in calls.log if c[1] == provider.TASK_GATE_DISTRACTORS]
    assert [a for _, _, a in gate2_calls] == [0, 1, 0, 1]  # per round: the call, then the missing-ids retry
    assert client.get(f"/quizzes/{quiz['id']}", headers=headers).json()["status"] == "failed"
    metrics = client.get(f"/metrics/{doc_id}", headers=headers).json()
    assert metrics["rejected_by_gate"]["gate2"] == 14


# --- quiz hash v2 --------------------------------------------------------------------------


def test_stored_review1_quiz_still_hashes_as_v1():
    with open(FIXTURE_V1, encoding="utf-8") as f:
        fixture = json.load(f)
    assert quizhash.quiz_hash(fixture["questions"], fixture["salt"]) == fixture["quiz_hash"]
    assert quizhash.quiz_hash(fixture["questions"], fixture["salt"], 1) == fixture["quiz_hash"]
    assert quizhash.quiz_hash(fixture["questions"], fixture["salt"], 2) != fixture["quiz_hash"]


def _q(position=1, **changes):
    q = {
        "position": position,
        "stem": "Which?",
        "options": ["a", "b", "c", "d"],
        "answer_index": 1,
        "fact_idxs": [3],
        "gate_results": {"gate1": {"verdict": "SUPPORTED", "reason": "r"}},
        "distractors": [{"option": k, "fact_idxs": [3], "misconception": "m"} for k in (0, 2, 3)],
    }
    return q | changes


def test_v2_canonical_object_matches_spec_and_is_deterministic():
    q = _q()
    expected = (
        '{"questions":[{"answer_index":1,"distractors":[{"fact_idxs":[3],"misconception":"m","option":0},'
        '{"fact_idxs":[3],"misconception":"m","option":2},{"fact_idxs":[3],"misconception":"m","option":3}],'
        '"fact_idxs":[3],"gate_results":{"gate1":{"reason":"r","verdict":"SUPPORTED"}},"model_answer":null,'
        '"options":["a","b","c","d"],"qtype":"mcq","stem":"Which?"}],"salt":"00ff","v":2}'
    )
    assert quizhash.canonical_json([q], "00ff", 2) == expected.encode("utf-8")
    assert quizhash.quiz_hash([q], "00ff", 2) == "0x" + keccak(expected.encode("utf-8")).hex()
    assert quizhash.quiz_hash([_q(2), _q(1, stem="x")], "aa", 2) == quizhash.quiz_hash([_q(1, stem="x"), _q(2)], "aa", 2)


def test_v2_covers_distractors_and_v1_ignores_them():
    base = [_q()]
    changed = [_q(distractors=[{"option": k, "fact_idxs": [3], "misconception": "other"} for k in (0, 2, 3)])]
    assert quizhash.quiz_hash(changed, "aa", 2) != quizhash.quiz_hash(base, "aa", 2)
    assert quizhash.quiz_hash(changed, "aa", 1) == quizhash.quiz_hash(base, "aa", 1)
    with pytest.raises(ValueError):
        quizhash.quiz_hash(base, "aa", 3)


def _replace_questions_with_fixture(test_engine, quiz_id: str) -> dict:
    """Turn a quiz into the stored Review 1 quiz: its questions, salt and hash_version 1."""
    with open(FIXTURE_V1, encoding="utf-8") as f:
        fixture = json.load(f)
    with Session(test_engine) as db:
        template = db.scalars(select(Question).where(Question.quiz_id == uuid.UUID(quiz_id))).first()
        for q in db.scalars(select(Question).where(Question.quiz_id == uuid.UUID(quiz_id))).all():
            db.delete(q)
        db.flush()
        for q in fixture["questions"]:
            db.add(
                Question(
                    quiz_id=uuid.UUID(quiz_id),
                    target_fact_idx=q["fact_idxs"][0],
                    bloom_level="remember",
                    fingerprint=f"fixture-{q['position']}",
                    dependence_score=0.5,
                    stem_embedding=list(template.stem_embedding),
                    **{k: q[k] for k in ("position", *quizhash.HASHED_FIELDS)},
                )
            )
        quiz = db.get(Quiz, uuid.UUID(quiz_id))
        quiz.salt, quiz.hash_version, quiz.commit_tx = fixture["salt"], 1, None
        db.commit()
    return fixture


def test_verify_quiz_uses_the_version_stored_on_the_quiz(client, test_engine):
    headers, doc_id = ready_document(client)
    quiz_id = make_quiz(client, headers, doc_id)["id"]
    with Session(test_engine) as db:
        quiz = db.get(Quiz, uuid.UUID(quiz_id))
        assert quiz.hash_version == 2
        stored = quiz.quiz_hash
    assert client.get(f"/verify/quiz/{quiz_id}").json()["recomputed_hash"] == stored

    fixture = _replace_questions_with_fixture(test_engine, quiz_id)
    assert client.get(f"/verify/quiz/{quiz_id}").json()["recomputed_hash"] == fixture["quiz_hash"]


# --- misconceptions: never before submit, with sources after -------------------------------


def test_nothing_about_distractors_leaks_before_submit(client, test_engine):
    headers, doc_id = ready_document(client)
    quiz_id = make_quiz(client, headers, doc_id)["id"]
    with Session(test_engine) as db:
        labels = [d["misconception"] for q in db.scalars(select(Question)).all() for d in q.distractors]
    assert labels
    bodies = [
        client.get(f"/quizzes/{quiz_id}", headers=headers).text,
        client.post(f"/quizzes/{quiz_id}/start", headers=headers).text,
        client.get(f"/quizzes/{quiz_id}", headers=headers).text,
    ]
    for body in bodies:
        assert "distractor" not in body and "misconception" not in body and "gate2" not in body
        assert not any(label in body for label in labels)
    assert client.get(f"/verify/question/{json.loads(bodies[1])['questions'][0]['id']}").status_code == 409


def test_results_carry_misconceptions_with_sources_after_submit(client, test_engine):
    headers, doc_id = ready_document(client)
    quiz_id = make_quiz(client, headers, doc_id)["id"]
    client.post(f"/quizzes/{quiz_id}/start", headers=headers)
    result = client.post(f"/quizzes/{quiz_id}/attempts", json={"answers": [0] * 5, "time_taken_sec": 5}, headers=headers).json()
    with Session(test_engine) as db:
        questions = {str(q.id): q for q in db.scalars(select(Question)).all()}
    for r in result["results"]:
        q = questions[r["question_id"]]
        assert [m["option"] for m in r["misconceptions"]] == [d["option"] for d in q.distractors]
        for m, d in zip(r["misconceptions"], q.distractors):
            assert m["misconception"] == d["misconception"]
            assert [s["idx"] for s in m["sources"]] == d["fact_idxs"]
            assert all(s["text"] and s["section"] for s in m["sources"])
    reloaded = client.get(f"/attempts/{result['attempt_id']}", headers=headers).json()
    assert reloaded == result
