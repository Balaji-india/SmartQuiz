"""R03: BKT mastery per concept and the gap report (SPEC 9.4). FAKE LLM, chain optional."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.learn.mastery import bkt_update, mastery_status
from app.models import Fact, Mastery, Question
from scripts.backfill_mastery import backfill
from tests.conftest import signup_headers
from tests.quiz_helpers import make_quiz, ready_document


# ---- BKT numbers, worked by hand from SPEC 9.4 (p_init 0.2, t 0.15, s 0.10, g 0.25 MCQ / 0.05 short) ----
# correct MCQ:  p' = .2*.9 / (.18 + .8*.25) = .18/.38;   p = (.18 + .15*.20)/.38 = .21/.38
# wrong MCQ:    p' = .2*.1 / (.02 + .8*.75) = .02/.62;   p = (.02 + .15*.60)/.62 = .11/.62
# correct short: p' = .18/(.18 + .8*.05) = .18/.22;      p = (.18 + .15*.04)/.22 = .186/.22
# wrong short:  p' = .02/(.02 + .8*.95) = .02/.78;       p = (.02 + .15*.76)/.78 = .134/.78
@pytest.mark.parametrize(
    "grade, qtype, expected",
    [
        ("correct", "mcq", 0.21 / 0.38),
        ("wrong", "mcq", 0.11 / 0.62),
        ("partial", "mcq", 0.11 / 0.62),  # partial counts as wrong
        ("correct", "short", 0.186 / 0.22),
        ("wrong", "short", 0.134 / 0.78),
    ],
)
def test_bkt_one_step_from_p_init(grade, qtype, expected):
    assert bkt_update(0.2, grade, qtype) == pytest.approx(expected, abs=1e-9)


def test_bkt_two_correct_answers_in_a_row():
    # p1 = 21/38. p' = (21/38*.9) / (21/38*.9 + 17/38*.25) = 378/463; p2 = (378 + 85*.15)/463 = 390.75/463
    assert bkt_update(bkt_update(0.2, "correct"), "correct") == pytest.approx(390.75 / 463, abs=1e-9)


def test_bkt_rejects_an_unknown_grade():
    with pytest.raises(ValueError):
        bkt_update(0.2, "maybe")


@pytest.mark.parametrize(
    "p, answered, status",
    [(0.2, 0, "untested"), (0.99, 0, "untested"), (0.3999, 1, "weak"), (0.40, 1, "learning"),
     (0.9499, 4, "learning"), (0.95, 4, "mastered"), (1.0, 9, "mastered")],
)
def test_status_thresholds(p, answered, status):
    assert mastery_status(p, answered) == status


# ---- endpoint ----
def _submit(client, test_engine, headers, doc, n=5, right=lambda i: i % 2 == 0) -> list[Question]:
    quiz = make_quiz(client, headers, doc, n=n)
    with Session(test_engine) as db:
        qs = db.scalars(select(Question).where(Question.quiz_id == uuid.UUID(quiz["id"])).order_by(Question.position)).all()
    client.post(f"/quizzes/{quiz['id']}/start", headers=headers)
    answers = [q.answer_index if right(i) else (q.answer_index + 1) % 4 for i, q in enumerate(qs)]
    r = client.post(f"/quizzes/{quiz['id']}/attempts", json={"answers": answers, "time_taken_sec": 30}, headers=headers)
    assert r.status_code == 200, r.text
    return qs


def _concepts(test_engine, doc) -> dict[int, str]:
    with Session(test_engine) as db:
        return dict(db.execute(select(Fact.idx, Fact.concept).where(Fact.document_id == uuid.UUID(doc))).all())


def test_attempt_updates_mastery_of_target_concepts_only(client, test_engine):
    headers, doc = ready_document(client)
    qs = _submit(client, test_engine, headers, doc)
    concepts = _concepts(test_engine, doc)
    expected = {concepts[q.target_fact_idx]: (0.21 / 0.38 if i % 2 == 0 else 0.11 / 0.62) for i, q in enumerate(qs)}
    context_only = {concepts[i] for q in qs for i in q.fact_idxs} - set(expected)

    report = client.get(f"/documents/{doc}/mastery", headers=headers).json()
    by_name = {c["concept"]: c for c in report["concepts"]}
    for name, p in expected.items():
        assert by_name[name]["answered"] == 1 and by_name[name]["p_mastery"] == pytest.approx(p, abs=1e-4)
    for name in context_only:
        assert by_name[name]["answered"] == 0 and by_name[name]["status"] == "untested"
    assert sum(c["answered"] for c in report["concepts"]) == len(qs)


def test_report_lists_every_concept_with_sections_and_facts(client, test_engine):
    headers, doc = ready_document(client)
    report = client.get(f"/documents/{doc}/mastery", headers=headers).json()
    concepts = _concepts(test_engine, doc)
    assert report["document_id"] == doc
    assert report["summary"] == {"mastered": 0, "learning": 0, "weak": 0, "untested": len(set(concepts.values()))}
    assert sorted(i for c in report["concepts"] for i in c["fact_idxs"]) == sorted(concepts)
    first = report["concepts"][0]
    assert first["fact_idxs"] == [0] and first["section"] == "1 Operating Systems" and first["badge_id"] is None
    assert first["p_mastery"] == 0.2 and first["status"] == "untested"
    assert [c["fact_idxs"][0] for c in report["concepts"]] == sorted(c["fact_idxs"][0] for c in report["concepts"])


def test_report_order_weak_learning_untested_mastered(client, test_engine):
    headers, doc = ready_document(client)
    concepts = _concepts(test_engine, doc)
    user_id = client.get("/auth/me", headers=headers).json()["id"]
    rows = {0: (0.97, 5), 1: (0.35, 2), 2: (0.10, 3), 3: (0.60, 1), 4: (0.45, 2), 5: (0.99, 6)}
    with Session(test_engine) as db:
        for idx, (p, n) in rows.items():
            db.add(Mastery(user_id=uuid.UUID(user_id), document_id=uuid.UUID(doc), concept=concepts[idx], p_mastery=p, answered=n))
        db.commit()
    report = client.get(f"/documents/{doc}/mastery", headers=headers).json()
    order = [c["fact_idxs"][0] for c in report["concepts"]]
    untested = [i for i in sorted(concepts) if i not in rows]
    assert order == [2, 1, 4, 3, *untested, 0, 5]
    assert [c["status"] for c in report["concepts"][:4]] == ["weak", "weak", "learning", "learning"]
    assert report["summary"] == {"mastered": 2, "learning": 2, "weak": 2, "untested": len(untested)}


def test_concepts_match_case_insensitively(client, test_engine):
    headers, doc = ready_document(client)
    with Session(test_engine) as db:
        f0, f1 = db.scalars(select(Fact).where(Fact.document_id == uuid.UUID(doc), Fact.idx.in_([0, 1])).order_by(Fact.idx))
        f1.concept = f"  {f0.concept.upper()} "
        db.commit()
        name, user_id = f0.concept, uuid.UUID(client.get("/auth/me", headers=headers).json()["id"])
        from app.learn.mastery import update_mastery

        update_mastery(db, user_id, f1.document_id, f1.concept, "correct", "mcq", datetime.now(timezone.utc))
        db.commit()
        assert db.scalars(select(Mastery.concept)).all() == [name]
    merged = [c for c in client.get(f"/documents/{doc}/mastery", headers=headers).json()["concepts"] if 0 in c["fact_idxs"]]
    assert len(merged) == 1 and merged[0]["fact_idxs"] == [0, 1] and merged[0]["concept"] == name
    assert merged[0]["answered"] == 1


def test_mastery_is_owner_only(client):
    headers, doc = ready_document(client)
    other = signup_headers(client, "other@b.com")
    assert client.get(f"/documents/{doc}/mastery", headers=other).status_code == 404
    assert client.get(f"/documents/{uuid.uuid4()}/mastery", headers=headers).status_code == 404
    assert client.get(f"/documents/{doc}/mastery").status_code == 401


# ---- backfill ----
def _rows(test_engine) -> dict:
    with Session(test_engine) as db:
        return {(m.user_id, m.concept): (round(m.p_mastery, 9), m.answered) for m in db.scalars(select(Mastery))}


def test_backfill_matches_live_updates_and_is_idempotent(client, test_engine):
    headers, doc = ready_document(client)
    # 3 x 10 questions on 24 facts: the third quiz retests concepts, so replay order matters.
    for k in range(3):
        _submit(client, test_engine, headers, doc, n=10, right=lambda i, k=k: (i + k) % 3 != 0)
    live = _rows(test_engine)
    assert any(n > 1 for _, n in live.values())

    with test_engine.begin() as conn:
        conn.execute(text("DELETE FROM mastery"))
    for _ in range(2):
        with Session(test_engine) as db:
            stats = backfill(db)
            db.commit()
        assert {k: stats[k] for k in ("attempts", "answers", "pairs")} == {"attempts": 3, "answers": 30, "pairs": 1}
        assert _rows(test_engine) == live
