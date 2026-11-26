"""R02: Bloom's ladder on retests, Gate 1 bloom label, bloom mismatches and metrics (FAKE LLM)."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Fact, FactCoverage, GenerationLog, Question, Quiz
from app.quiz import gates, prompts
from app.quiz.dedup import fingerprint
from app.quiz.generate import validate
from app.quiz.select import BLOOM_LEVELS, Target, next_bloom, select_targets
from tests.quiz_helpers import make_quiz, ready_document
from tests.test_distractors import _candidate, _fake_checker, _raw
from tests.test_quiz import _add_question


# --- the ladder ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "previous, last_correct, expected",
    [
        ("remember", True, "understand"),
        ("understand", True, "apply"),
        ("apply", True, "analyze"),
        ("analyze", True, "apply"),  # cap: analyze again would repeat, so the neighbour
        ("analyze", False, "apply"),
        ("apply", False, "understand"),
        ("understand", False, "remember"),
        ("remember", False, "understand"),  # floor: remember again would repeat, so the neighbour
        ("remember", None, "understand"),  # tier 3, never answered: one up
        ("analyze", None, "apply"),
        (None, None, "understand"),
    ],
)
def test_ladder_transitions(previous, last_correct, expected):
    assert next_bloom(previous, last_correct) == expected
    assert expected != previous


def test_levels_and_prompts_name_all_four():
    assert BLOOM_LEVELS == ("remember", "understand", "apply", "analyze")
    for system in (prompts.GENERATE_QUESTIONS_SYSTEM, prompts.GATE_GROUNDING_SYSTEM):
        assert all(f"{level} =" in system for level in BLOOM_LEVELS)
    assert '"bloom"' in prompts.GATE_GROUNDING_SYSTEM


# history per fact idx: (bloom of the earlier question, last_correct or None = never answered)
HISTORY = {
    0: ("remember", False), 1: ("understand", False), 2: ("apply", False), 3: ("analyze", False),
    4: ("remember", True), 5: ("understand", True), 6: ("apply", True), 7: ("analyze", True),
    8: ("remember", None), 9: ("analyze", None),
}


def _used_document(client, test_engine) -> tuple[uuid.UUID, uuid.UUID]:
    """Every fact used once (so no unused ones), with answered/unanswered history per HISTORY; others never answered."""
    _, doc_id = ready_document(client)
    doc = uuid.UUID(doc_id)
    with Session(test_engine) as db:
        user_id = db.scalar(text("SELECT id FROM users"))
        # Every fact gets its own concept, so the 2-per-concept cap does not hide any.
        db.execute(text("UPDATE facts SET concept = 'c' || idx::text"))
        quiz = Quiz(user_id=user_id, document_id=doc, status="ready", time_limit_sec=600)
        db.add(quiz)
        db.flush()
        facts = {f.idx: f for f in db.scalars(select(Fact).where(Fact.document_id == doc))}
        start = datetime.now(timezone.utc) - timedelta(days=1)
        for idx in sorted(facts):
            bloom, correct = HISTORY.get(idx, ("remember", None))
            _add_question(db, quiz, idx + 1, target_idx=idx, fact_idxs=[idx], bloom=bloom)
            if correct is not None:
                db.add(FactCoverage(
                    user_id=user_id, fact_id=facts[idx].id, times_tested=1, last_correct=correct,
                    last_bloom=bloom, updated_at=start + timedelta(minutes=idx),
                ))
        db.commit()
    return user_id, doc


def test_retests_climb_and_fall_per_spec(client, test_engine):
    user_id, doc = _used_document(client, test_engine)
    with Session(test_engine) as db:
        targets = {t.fact.idx: t for t in select_targets(db, user_id, doc, 30, "seed")}
    for idx, (bloom, correct) in HISTORY.items():
        t = targets[idx]
        assert t.previous_bloom == bloom
        assert t.bloom_level == next_bloom(bloom, correct)
        assert t.tier == {False: 2, None: 3, True: 4}[correct]
    # spot checks of the caps and floors, written out
    assert targets[0].bloom_level == "understand" and targets[3].bloom_level == "apply"
    assert targets[7].bloom_level == "apply" and targets[6].bloom_level == "analyze"


def test_retest_fingerprint_differs_from_the_earlier_question(client, test_engine):
    user_id, doc = _used_document(client, test_engine)
    with Session(test_engine) as db:
        earlier = dict(db.execute(select(Question.target_fact_idx, Question.fingerprint)).all())
        targets = select_targets(db, user_id, doc, 30, "seed")
    assert targets
    for t in targets:
        assert fingerprint([t.fact.idx], t.bloom_level) != earlier[t.fact.idx]


def test_question_keeps_the_ladder_level_not_the_generators_echo():
    target = Target(Fact(idx=5, text="t", concept="c", section_id=1), 4, "apply", "understand")
    raw = _raw(0) | {"bloom_level": "understand"}
    c = validate(raw, target, {5, 6})
    assert c.error is None and c.bloom_level == "apply"


# --- Gate 1 bloom label --------------------------------------------------------------------


@pytest.mark.parametrize(
    "reply, expected",
    [
        ({"verdict": "SUPPORTED", "bloom": " Apply ", "reason": "ok"}, "apply"),
        ({"verdict": "SUPPORTED", "reason": "ok"}, None),  # missing field
        ({"verdict": "SUPPORTED", "bloom": "evaluate", "reason": "ok"}, None),  # not one of ours
        ({"verdict": "SUPPORTED", "bloom": None, "reason": "ok"}, None),
        ({"verdict": "NOT_SUPPORTED", "bloom": "analyze", "reason": "no"}, "analyze"),
    ],
)
def test_gate1_bloom_parsing_never_changes_the_verdict(monkeypatch, reply, expected):
    _fake_checker(monkeypatch, lambda payload, attempt: {"results": [{"id": 0, **reply}]})
    c = _candidate()
    gates.gate1_grounding([c], {5: "five", 6: "six"})
    g1 = c.gate_results["gate1"]
    assert g1["bloom"] == expected and g1["verdict"] == reply["verdict"]
    assert gates.passed_gate1(c) is (reply["verdict"] == "SUPPORTED")


def test_gate1_payload_does_not_tell_the_checker_the_asked_level(monkeypatch):
    seen = _fake_checker(monkeypatch, lambda payload, attempt: {"results": [{"id": 0, "verdict": "SUPPORTED"}]})
    gates.gate1_grounding([_candidate()], {5: "five", 6: "six"})
    assert set(seen[0][0]["items"][0]) == {"id", "facts", "stem", "answer"}


# --- mismatches are logged, not dropped; metrics -------------------------------------------


def test_mismatch_is_logged_and_kept_and_metrics_count_levels(client, test_engine):
    headers, doc_id = ready_document(client)
    quiz = make_quiz(client, headers, doc_id, n=6)
    with Session(test_engine) as db:
        questions = db.scalars(select(Question).where(Question.quiz_id == uuid.UUID(quiz["id"]))).all()
        mismatches = db.scalars(select(GenerationLog).where(GenerationLog.gate == "bloom_mismatch")).all()
    # New targets alternate remember / understand; the FAKE checker always says remember.
    assert len(questions) == 6
    understand = [q for q in questions if q.bloom_level == "understand"]
    assert len(understand) == 3 and all(q.gate_results["gate1"]["bloom"] == "remember" for q in questions)
    # One row per gated candidate asked "understand" (spares included); metrics count accepted questions only.
    assert len(mismatches) >= 3 and all(m.passed for m in mismatches)
    assert {m.reason for m in mismatches} == {"asked understand, checker says remember"}
    assert {m.candidate_id for m in mismatches} <= {m.candidate_id for m in db_logs(test_engine, "gate1")}

    metrics = client.get(f"/metrics/{doc_id}", headers=headers).json()
    assert metrics["bloom_levels"] == {"remember": 3, "understand": 3, "apply": 0, "analyze": 0}
    assert metrics["bloom_mismatches"] == 3
    assert "bloom_mismatch" not in metrics["rejected_by_gate"]
    assert all(r["gate"] != "bloom_mismatch" for r in metrics["top_reasons"])


def test_metrics_skip_questions_without_a_checker_label(client, test_engine):
    headers, doc_id = ready_document(client)
    with Session(test_engine) as db:
        user_id = db.scalar(text("SELECT id FROM users"))
        quiz = Quiz(user_id=user_id, document_id=uuid.UUID(doc_id), status="ready", time_limit_sec=600)
        db.add(quiz)
        db.flush()
        for i, (asked, label) in enumerate([("apply", None), ("analyze", "analyze"), ("analyze", "understand")]):
            _add_question(db, quiz, i + 1, target_idx=i, fact_idxs=[i], bloom=asked)
            db.flush()
            q = db.scalars(select(Question).where(Question.position == i + 1)).one()
            q.gate_results = {} if label is None else {"gate1": {"verdict": "SUPPORTED", "bloom": label, "reason": "r"}}
        db.commit()
    metrics = client.get(f"/metrics/{doc_id}", headers=headers).json()
    assert metrics["bloom_levels"] == {"remember": 0, "understand": 0, "apply": 1, "analyze": 2}
    assert metrics["bloom_mismatches"] == 1


def db_logs(test_engine, gate: str) -> list[GenerationLog]:
    with Session(test_engine) as db:
        return db.scalars(select(GenerationLog).where(GenerationLog.gate == gate)).all()
