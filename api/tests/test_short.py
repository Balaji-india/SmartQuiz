"""R06: short-answer questions, checker grading from cited facts, educator deferral (SPEC 9.7). FAKE LLM.

FAKE grading (provider._fake_grade_short): the model answer → correct 95; "partly …" → partial 85;
"unsure …" → correct with confidence 40 (deferred); anything else → incorrect 90.
"""
import json
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.chain import quizhash
from app.learn import shortgrade
from app.learn.shortgrade import CONFIDENCE_MIN, apply_educator_grade, grade_short
from app.llm import provider
from app.models import AnswerGrade, Attempt, Fact, FactCoverage, GenerationLog, Mastery, Question, Quiz, ReviewCard, User
from app.quiz.generate import validate_short
from app.quiz.job import mark_short
from app.quiz.select import Target
from scripts.backfill_mastery import backfill
from tests.quiz_helpers import ready_document


@pytest.fixture
def calls(monkeypatch):
    """Records (role, task marker, attempt) for every LLM call; the FAKE replies are unchanged."""
    seen = []
    real = provider.generate_json

    def spy(role, system, user, attempt=0):
        seen.append((role, system.split("]", 1)[0] + "]", attempt))
        return real(role, system, user, attempt)

    monkeypatch.setattr(provider, "generate_json", spy)
    return seen


def _mixed_quiz(client, headers, doc, n=5, num_short=2) -> dict:
    r = client.post("/quizzes", json={"document_id": doc, "num_questions": n, "num_short": num_short}, headers=headers)
    assert r.status_code == 200, r.text
    # TestClient runs the job after building the response, so read the finished quiz back.
    return client.get(f"/quizzes/{r.json()['id']}", headers=headers).json()


def _questions(test_engine, quiz_id) -> list[Question]:
    with Session(test_engine) as db:
        return db.scalars(select(Question).where(Question.quiz_id == uuid.UUID(quiz_id)).order_by(Question.position)).all()


def _submit(client, headers, quiz_id, answers):
    client.post(f"/quizzes/{quiz_id}/start", headers=headers)
    return client.post(f"/quizzes/{quiz_id}/attempts", json={"answers": answers, "time_taken_sec": 30}, headers=headers)


def _answers(qs, short_answers: list, mcq_right=True) -> list:
    """MCQs answered right (or wrong); short questions take short_answers in order ("MODEL" = the model answer)."""
    out, it = [], iter(short_answers)
    for q in qs:
        if q.qtype == "short":
            a = next(it)
            out.append(q.model_answer if a == "MODEL" else a)
        else:
            out.append(q.answer_index if mcq_right else (q.answer_index + 1) % 4)
    return out


def _target(test_engine, doc, q) -> Fact:
    with Session(test_engine) as db:
        return db.scalar(select(Fact).where(Fact.document_id == uuid.UUID(doc), Fact.idx == q.target_fact_idx))


# ---- generation ----
def test_mark_short_spreads_over_the_first_n_targets_only():
    targets = [Target(fact=None, tier=1, bloom_level="remember", previous_bloom=None) for _ in range(13)]
    marked = mark_short(targets, 10, 2)
    assert [i for i, t in enumerate(marked) if t.qtype == "short"] == [2, 7]
    assert [i for i, t in enumerate(mark_short(targets[:4], 10, 3)) if t.qtype == "short"] == [0, 2, 3]
    assert all(t.qtype == "mcq" for t in mark_short(targets, 10, 0))


def test_validate_short_rules():
    class F:
        idx = 5

    t = Target(fact=F(), tier=1, bloom_level="understand", previous_bloom=None, qtype="short")
    ok = validate_short({"qtype": "short", "stem": " Why? ", "model_answer": " Because  so. ", "fact_idxs": [5, 6]}, t, {5, 6})
    assert ok.error is None and ok.stem == "Why?" and ok.model_answer == "Because so."
    assert ok.options == [] and ok.answer_index == -1 and ok.distractors == [] and ok.fact_idxs == [5, 6]
    assert ok.bloom_level == "understand"
    bad = [
        ({"stem": "Why?", "model_answer": "", "fact_idxs": [5]}, "empty model_answer"),
        ({"stem": "", "model_answer": "x", "fact_idxs": [5]}, "empty stem"),
        ({"stem": "Why?", "model_answer": "x", "fact_idxs": [9]}, "outside"),
        ({"qtype": "mcq", "stem": "Why?", "model_answer": "x", "fact_idxs": [5]}, "expected a short-answer"),
        ({"stem": "Why?", "model_answer": "word " * 61, "fact_idxs": [5]}, "over 60 words"),
        (None, "no question"),
    ]
    for raw, message in bad:
        assert message in validate_short(raw, t, {5, 6}).error


def test_mixed_quiz_one_generator_call_short_items_skip_gates_2_and_4(client, test_engine, calls):
    headers, doc = ready_document(client)
    calls.clear()  # ingestion calls
    quiz = _mixed_quiz(client, headers, doc)
    assert quiz["status"] == "ready"
    qs = _questions(test_engine, quiz["id"])
    short = [q for q in qs if q.qtype == "short"]
    assert len(qs) == 5 and len(short) == 2
    for q in short:
        assert q.options == [] and q.answer_index == -1 and q.distractors == [] and q.model_answer
        assert q.dependence_score is None and q.flagged_general is False
        assert set(q.gate_results) == {"gate1", "gate3"}
        assert q.gate_results["gate3"] == {"passed": True, "verdict": "ANSWERABLE", "reason": "fake"}
    for q in qs:
        if q.qtype == "mcq":
            assert set(q.gate_results) == {"gate1", "gate2", "gate3", "gate4"} and q.dependence_score is not None

    tasks = [t for role, t, _ in calls if role == "generator"]
    assert tasks == [provider.TASK_GENERATE_QUESTIONS]  # ONE generator call wrote MCQs and short answers
    assert sum(t == provider.TASK_GATE_SHORT_SOLVABILITY for _, t, _ in calls) == 1
    assert sum(t == provider.TASK_GATE_DISTRACTORS for _, t, _ in calls) == 1
    with Session(test_engine) as db:
        gates_by_candidate = {}
        for cid, gate in db.execute(
            select(GenerationLog.candidate_id, GenerationLog.gate).where(GenerationLog.quiz_id == uuid.UUID(quiz["id"]))
        ):
            gates_by_candidate.setdefault(cid, set()).add(gate)
    # 7 candidates (5 + 2 spares); the 2 short ones logged gate1 + gate3 (+ bloom_mismatch) and never gate2 / gate4.
    no_mcq_gates = [g for g in gates_by_candidate.values() if not g & {"gate2", "gate4"}]
    assert len(gates_by_candidate) == 7 and len(no_mcq_gates) == 2
    assert all({"gate1", "gate3"} <= g <= {"gate1", "gate3", "bloom_mismatch"} for g in no_mcq_gates)


def test_short_failing_gate3s_joins_the_one_regeneration(client, test_engine, calls, monkeypatch):
    real = provider._fake

    def ambiguous_first_try(role, system, user, attempt):
        if provider.TASK_GATE_SHORT_SOLVABILITY in system:
            items = json.loads(user)["items"]
            return {"results": [
                {"id": i["id"], "verdict": "AMBIGUOUS" if "try 0" in i["stem"] else "ANSWERABLE", "reason": "two answers"}
                for i in items
            ]}
        return real(role, system, user, attempt)

    monkeypatch.setattr(provider, "_fake", ambiguous_first_try)
    headers, doc = ready_document(client)
    calls.clear()
    quiz = _mixed_quiz(client, headers, doc)
    short = [q for q in _questions(test_engine, quiz["id"]) if q.qtype == "short"]
    assert len(short) == 2 and all("try 1" in q.stem for q in short)
    assert [a for role, _, a in calls if role == "generator"] == [0, 1]
    with Session(test_engine) as db:
        reasons = db.scalars(
            select(GenerationLog.reason).where(GenerationLog.gate == "gate3", GenerationLog.passed.is_(False))
        ).all()
    assert reasons == ["two answers", "two answers"]


@pytest.mark.parametrize("body", [{"num_short": 4}, {"num_short": -1}, {"num_questions": 2, "num_short": 3}])
def test_num_short_out_of_range_is_422(client, body):
    headers, doc = ready_document(client)
    r = client.post("/quizzes", json={"document_id": doc, "num_questions": 5} | body, headers=headers)
    assert r.status_code == 422


# ---- attempt validation ----
def test_wrong_answer_types_are_422_per_position(client, test_engine):
    headers, doc = ready_document(client)
    quiz = _mixed_quiz(client, headers, doc)
    qs = _questions(test_engine, quiz["id"])
    s = next(i for i, q in enumerate(qs) if q.qtype == "short")
    m = next(i for i, q in enumerate(qs) if q.qtype == "mcq")
    good = _answers(qs, ["MODEL", "MODEL"])
    client.post(f"/quizzes/{quiz['id']}/start", headers=headers)
    for position, value in [(s, 1), (m, "1"), (m, "text"), (s, "x" * 501), (m, True), (m, 4)]:
        answers = list(good)
        answers[position] = value
        r = client.post(f"/quizzes/{quiz['id']}/attempts", json={"answers": answers, "time_taken_sec": 5}, headers=headers)
        assert r.status_code == 422, (position, value, r.text)
    with Session(test_engine) as db:
        assert db.scalar(select(func.count()).select_from(Attempt)) == 0
    answers = list(good)
    answers[s] = "x" * 500  # exactly at the limit is fine
    assert _submit(client, headers, quiz["id"], answers).status_code == 200


# ---- grading ----
def test_one_grading_call_verdicts_and_score(client, test_engine, calls):
    headers, doc = ready_document(client)
    quiz = _mixed_quiz(client, headers, doc, n=6, num_short=3)
    qs = _questions(test_engine, quiz["id"])
    calls.clear()
    r = _submit(client, headers, quiz["id"], _answers(qs, ["MODEL", "partly about something", "no idea at all"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert [t for _, t, _ in calls] == [provider.TASK_GRADE_SHORT]  # one batched checker call
    short = [x for x in body["results"] if x["qtype"] == "short"]
    assert [(x["grade"]["verdict"], x["grade"]["confidence"], x["correct"]) for x in short] == [
        ("correct", 95, True), ("partial", 85, False), ("incorrect", 90, False)
    ]
    for x in short:
        assert x["chosen"] is None and x["correct_index"] is None and x["misconceptions"] == []
        assert x["model_answer"] and x["answer_text"] and x["sources"]
        assert x["grade"]["by"] == "checker" and x["grade"]["deferred"] is False
        assert x["grade"]["fact_idxs"] and set(x["grade"]["fact_idxs"]) <= {s["idx"] for s in x["sources"]}
    assert body["score"] == 3 + 1 and body["total"] == 6
    assert body["grading_status"] == "final" and body["pending_review"] == 0
    # partial and incorrect count as wrong for the weak-concept list
    assert sum(w["wrong"] for w in body["weak_concepts"]) == 2
    with Session(test_engine) as db:
        logs = db.scalars(select(GenerationLog.passed).where(GenerationLog.gate == "grade_short")).all()
        assert logs == [True, True, True]
        attempt = db.scalar(select(Attempt))
        assert attempt.answers == _answers(qs, ["MODEL", "partly about something", "no idea at all"])
    # GET /attempts reloads the same result from answer_grades
    assert client.get(f"/attempts/{body['attempt_id']}", headers=headers).json() == body


def test_empty_short_answer_is_incorrect_without_an_llm_call(client, test_engine, calls):
    headers, doc = ready_document(client)
    quiz = _mixed_quiz(client, headers, doc)
    qs = _questions(test_engine, quiz["id"])
    calls.clear()
    body = _submit(client, headers, quiz["id"], _answers(qs, [None, "   "])).json()
    assert calls == []
    grades = [x["grade"] for x in body["results"] if x["qtype"] == "short"]
    assert [(g["verdict"], g["deferred"], g["reason"]) for g in grades] == [("incorrect", False, "No answer given")] * 2


def test_parse_threshold_and_citation_rules():
    allowed = {3, 4}
    g = lambda **kw: {"id": 0, "verdict": "correct", "confidence": 90, "fact_idxs": [3], "reason": "r"} | kw  # noqa: E731
    p = shortgrade._parse
    assert p(g(confidence=CONFIDENCE_MIN), allowed, None).deferred is False
    assert p(g(confidence=CONFIDENCE_MIN - 1), allowed, None).deferred is True
    assert p(g(confidence=None), allowed, None).deferred is True
    assert p(g(confidence=150), allowed, None).confidence == 100
    assert p(g(verdict="maybe"), allowed, None).deferred is True
    assert p(g(fact_idxs=[3, 99]), allowed, None).deferred is True  # cites a fact outside the question
    assert p(g(fact_idxs=[]), allowed, None).deferred is True
    assert p(None, allowed, None).deferred is True
    assert p(g(verdict=" Partial "), allowed, None).verdict == "partial"


def test_no_verdict_after_one_retry_is_deferred(monkeypatch, calls):
    monkeypatch.setattr(provider, "_fake", lambda role, system, user, attempt: {"grades": []})
    items = [{"id": 0, "facts": [{"idx": 1, "text": "t"}], "stem": "s", "model_answer": "m", "answer": "a"}]
    out = grade_short(items, {0: {1}})
    assert [a for _, _, a in calls] == [0, 1]
    assert out[0].deferred and out[0].verdict is None


def test_llm_failure_defers_instead_of_failing_the_submit(client, test_engine, monkeypatch):
    headers, doc = ready_document(client)
    quiz = _mixed_quiz(client, headers, doc)
    qs = _questions(test_engine, quiz["id"])
    real = provider.generate_json

    def daily_limit(role, system, user, attempt=0):
        if provider.TASK_GRADE_SHORT in system:
            raise provider.DailyLimitError("checker daily limit")
        return real(role, system, user, attempt)

    monkeypatch.setattr(provider, "generate_json", daily_limit)
    body = _submit(client, headers, quiz["id"], _answers(qs, ["MODEL", "MODEL"])).json()
    assert body["grading_status"] == "pending_review" and body["pending_review"] == 2 and body["score"] == 3
    assert all(x["grade"]["deferred"] and x["grade"]["verdict"] is None for x in body["results"] if x["qtype"] == "short")


# ---- deferral and the educator hook ----
def test_deferred_grade_is_pending_hooks_fire_only_when_final(client, test_engine):
    headers, doc = ready_document(client)
    quiz = _mixed_quiz(client, headers, doc)
    qs = _questions(test_engine, quiz["id"])
    unsure, sure = [q for q in qs if q.qtype == "short"]
    body = _submit(client, headers, quiz["id"], _answers(qs, ["unsure, maybe the same thing", "MODEL"])).json()

    assert body["grading_status"] == "pending_review" and body["pending_review"] == 1
    assert body["score"] == 3 + 1  # the deferred answer does not count yet
    pending = next(x for x in body["results"] if x["question_id"] == str(unsure.id))
    assert pending["grade"] == {
        "verdict": None, "confidence": 40, "reason": "fake", "deferred": True, "by": None, "fact_idxs": [unsure.target_fact_idx]
    }
    assert pending["correct"] is False

    user_id = uuid.UUID(client.get("/auth/me", headers=headers).json()["id"])
    unsure_fact, sure_fact = _target(test_engine, doc, unsure), _target(test_engine, doc, sure)
    with Session(test_engine) as db:
        # Hooks ran for the final grades only: no coverage and no FSRS card for the deferred target.
        assert db.get(FactCoverage, (user_id, unsure_fact.id)) is None
        assert db.get(ReviewCard, (user_id, unsure_fact.id)) is None
        assert db.get(FactCoverage, (user_id, sure_fact.id)).last_correct is True
        assert db.get(ReviewCard, (user_id, sure_fact.id)) is not None
        assert db.scalar(select(func.count()).select_from(ReviewCard)) == 4
        answered_before = sum(db.scalars(select(Mastery.answered)).all())
        assert answered_before == 4
        grade = db.scalar(select(AnswerGrade).where(AnswerGrade.question_id == unsure.id))
        assert grade.deferred and grade.graded_at is None
        educator = db.get(User, user_id)  # R08 adds the educator role; the function takes any user for now

        apply_educator_grade(db, grade.id, "correct", educator)
        db.commit()

        assert db.get(FactCoverage, (user_id, unsure_fact.id)).last_correct is True
        assert db.get(ReviewCard, (user_id, unsure_fact.id)).last_rating == 3  # Good
        assert sum(db.scalars(select(Mastery.answered)).all()) == answered_before + 1
        attempt = db.get(Attempt, uuid.UUID(body["attempt_id"]))
        assert attempt.grading_status == "final" and attempt.score == 5
        with pytest.raises(ValueError, match="already graded"):
            apply_educator_grade(db, grade.id, "incorrect", educator)
        final = db.scalar(select(AnswerGrade).where(AnswerGrade.question_id == sure.id))
        with pytest.raises(ValueError, match="final"):
            apply_educator_grade(db, final.id, "incorrect", educator)
        with pytest.raises(ValueError, match="verdict"):
            apply_educator_grade(db, grade.id, "wrong", educator)
        with pytest.raises(LookupError):
            apply_educator_grade(db, uuid.uuid4(), "correct", educator)

    reloaded = client.get(f"/attempts/{body['attempt_id']}", headers=headers).json()
    assert reloaded["grading_status"] == "final" and reloaded["pending_review"] == 0 and reloaded["score"] == 5
    graded = next(x for x in reloaded["results"] if x["question_id"] == str(unsure.id))
    assert graded["grade"]["verdict"] == "correct" and graded["grade"]["by"] == "educator" and graded["correct"] is True
    assert graded["grade"]["deferred"] is True  # the history stays visible


def test_backfill_replays_final_short_grades_and_skips_pending(client, test_engine):
    headers, doc = ready_document(client)
    quiz = _mixed_quiz(client, headers, doc)
    qs = _questions(test_engine, quiz["id"])
    _submit(client, headers, quiz["id"], _answers(qs, ["unsure", "partly"]))
    with Session(test_engine) as db:
        before = {(r.concept, r.p_mastery, r.answered) for r in db.scalars(select(Mastery))}
        cards = db.scalar(select(func.count()).select_from(ReviewCard))
        stats = backfill(db)
        db.commit()
        after = {(r.concept, round(r.p_mastery, 9), r.answered) for r in db.scalars(select(Mastery))}
    assert stats["answers"] == 4 and stats["cards"] == cards == 4
    assert after == {(c, round(p, 9), a) for c, p, a in before}


# ---- hash and leaks ----
def test_hash_v2_with_a_short_question(client, test_engine):
    headers, doc = ready_document(client)
    quiz = _mixed_quiz(client, headers, doc)
    qs = _questions(test_engine, quiz["id"])
    with Session(test_engine) as db:
        stored = db.get(Quiz, uuid.UUID(quiz["id"]))
        assert stored.hash_version == 2
        assert quizhash.quiz_hash(qs, stored.salt, 2) == stored.quiz_hash == quiz["quiz_hash"]
        obj = json.loads(quizhash.canonical_json(qs, stored.salt, 2))
    short = next(o for o, q in zip(obj["questions"], qs) if q.qtype == "short")
    assert short["qtype"] == "short" and short["options"] == [] and short["answer_index"] == -1
    assert short["distractors"] == [] and short["model_answer"]
    assert all(o["model_answer"] is None for o, q in zip(obj["questions"], qs) if q.qtype == "mcq")
    # Changing a model answer changes the hash.
    q = next(q for q in qs if q.qtype == "short")
    q.model_answer += " (edited)"
    assert quizhash.quiz_hash(qs, stored.salt, 2) != stored.quiz_hash


def test_nothing_leaks_before_submit(client, test_engine):
    headers, doc = ready_document(client)
    quiz = _mixed_quiz(client, headers, doc)
    qs = _questions(test_engine, quiz["id"])
    started = client.post(f"/quizzes/{quiz['id']}/start", headers=headers).json()
    again = client.get(f"/quizzes/{quiz['id']}", headers=headers).json()
    for out in (started, again):
        raw = json.dumps(out)
        assert "model_answer" not in raw and "answer_index" not in raw and "distractors" not in raw
        for q in qs:
            if q.qtype == "short":
                assert q.model_answer not in raw
        short = [x for x in out["questions"] if x["qtype"] == "short"]
        assert len(short) == 2 and all(x["options"] == [] and x["fact_idxs"] is None for x in short)
    short_id = next(q.id for q in qs if q.qtype == "short")
    assert client.get(f"/verify/question/{short_id}").status_code == 409
    assert client.get(f"/attempts/{uuid.uuid4()}", headers=headers).status_code == 404


# ---- metrics ----
def test_metrics_avg_dependence_over_mcqs_and_short_counts(client, test_engine):
    headers, doc = ready_document(client)
    quiz = _mixed_quiz(client, headers, doc)
    qs = _questions(test_engine, quiz["id"])
    _submit(client, headers, quiz["id"], _answers(qs, ["unsure", "MODEL"]))
    m = client.get(f"/metrics/{doc}", headers=headers).json()
    mcq_scores = [q.dependence_score for q in qs if q.qtype == "mcq"]
    assert m["avg_dependence"] == round(sum(mcq_scores) / len(mcq_scores), 2)
    assert m["short_questions"] == 2 and m["deferred_grades"] == 1
    assert m["accepted"] == 5 and "grade_short" not in m["rejected_by_gate"]
