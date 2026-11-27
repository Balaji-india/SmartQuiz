"""R05: FSRS review cards and review quiz mode (SPEC 9.6). FAKE LLM; the chain is a FAKE where a test needs one."""
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from fsrs import Card, Rating
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.chain.quizhash import quiz_hash
from app.config import get_settings
from app.learn.review import rating_for, review_summary, update_card
from app.models import Fact, FactCoverage, Question, Quiz, ReviewCard
from app.quiz import job
from app.quiz.dedup import DuplicateChecker
from app.quiz.select import MAX_PER_CONCEPT, next_bloom, select_review_targets
from scripts.backfill_mastery import backfill
from tests.conftest import signup_headers
from tests.quiz_helpers import make_quiz, ready_document


def _user_id(client, headers) -> uuid.UUID:
    return uuid.UUID(client.get("/auth/me", headers=headers).json()["id"])


def _answer(client, test_engine, headers, quiz_id, right) -> list[Question]:
    """Start and submit a quiz; right(i) says whether question i (0-based) is answered right."""
    with Session(test_engine) as db:
        qs = db.scalars(select(Question).where(Question.quiz_id == uuid.UUID(quiz_id)).order_by(Question.position)).all()
    client.post(f"/quizzes/{quiz_id}/start", headers=headers)
    answers = [q.answer_index if right(i) else (q.answer_index + 1) % 4 for i, q in enumerate(qs)]
    r = client.post(f"/quizzes/{quiz_id}/attempts", json={"answers": answers, "time_taken_sec": 30}, headers=headers)
    assert r.status_code == 200, r.text
    return qs


def _age_cards(test_engine, minutes: float) -> None:
    """Move every card's due back in time, as if `minutes` had passed."""
    with test_engine.begin() as conn:
        conn.execute(text("UPDATE review_cards SET due = due - make_interval(secs => :s)"), {"s": minutes * 60})


def _review(client, headers, doc, n=5):
    return client.post("/quizzes", json={"document_id": doc, "num_questions": n, "mode": "review"}, headers=headers)


@pytest.fixture
def fake_chain(monkeypatch):
    """CHAIN_OPTIONAL=false with a FAKE chain that records every commit."""
    commits = []

    class FakeChain:
        def commit_quiz(self, quiz_uuid, document_uuid, h):
            commits.append((str(quiz_uuid), str(document_uuid), h))
            return "0x" + f"{len(commits):064x}"

    monkeypatch.setattr(get_settings(), "chain_optional", False)
    monkeypatch.setattr(job, "get_chain", lambda: FakeChain())
    return commits


# ---- rating mapping and the card ----
@pytest.mark.parametrize("grade, rating", [("wrong", Rating.Again), ("partial", Rating.Hard), ("correct", Rating.Good)])
def test_rating_mapping(grade, rating):
    assert rating_for(grade) == rating


def test_rating_rejects_an_unknown_grade():
    with pytest.raises(ValueError):
        rating_for("maybe")


def test_card_is_created_then_updated_from_its_stored_dict(client, test_engine):
    headers, doc = ready_document(client)
    user_id = _user_id(client, headers)
    now = datetime(2026, 11, 27, 9, 0, tzinfo=timezone.utc)
    with Session(test_engine) as db:
        fact = db.scalar(select(Fact).where(Fact.document_id == uuid.UUID(doc), Fact.idx == 3))
        update_card(db, user_id, fact, "wrong", now)
        db.commit()
        row = db.get(ReviewCard, (user_id, fact.id))
        assert row.last_rating == int(Rating.Again) and row.due == now + timedelta(minutes=1)
        assert Card.from_dict(row.card).due == row.due and row.card["card_id"] == fact.id
        first_stability = row.card["stability"]

        update_card(db, user_id, fact, "correct", now + timedelta(minutes=2))  # reads the stored card back
        db.commit()
        db.refresh(row)
        assert row.last_rating == int(Rating.Good) and row.card["stability"] != first_stability
        assert row.due > now + timedelta(minutes=2)
        assert db.scalar(select(func.count()).select_from(ReviewCard)) == 1


def test_submit_creates_one_card_per_target_and_wrong_ones_come_due_first(client, test_engine):
    headers, doc = ready_document(client)
    quiz = make_quiz(client, headers, doc)
    qs = _answer(client, test_engine, headers, quiz["id"], right=lambda i: i >= 2)  # first 2 wrong

    summary = client.get(f"/documents/{doc}/review", headers=headers).json()
    assert summary["cards"] == 5 and summary["due_now"] == 0 and summary["next_due"] is not None
    _age_cards(test_engine, 2)  # past Again (1 min), before Good (10 min)
    summary = client.get(f"/documents/{doc}/review", headers=headers).json()
    assert summary["due_now"] == 2
    with Session(test_engine) as db:
        due = db.scalars(
            select(Fact.idx).join(ReviewCard, ReviewCard.fact_id == Fact.id).where(ReviewCard.due <= func.now())
        ).all()
    assert sorted(due) == sorted(q.target_fact_idx for q in qs[:2])


# ---- selection ----
def _set_cards(test_engine, user_id, doc, dues: dict[int, float], concept_of: dict[int, str] | None = None) -> None:
    """dues: fact idx -> minutes overdue (negative = not due yet). Each card gets a coverage row (wrong, remember)."""
    now = datetime.now(timezone.utc)
    with Session(test_engine) as db:
        facts = {f.idx: f for f in db.scalars(select(Fact).where(Fact.document_id == uuid.UUID(doc)))}
        for idx, concept in (concept_of or {}).items():
            facts[idx].concept = concept
        for idx, minutes in dues.items():
            due = now - timedelta(minutes=minutes)
            db.add(ReviewCard(user_id=user_id, fact_id=facts[idx].id, card=Card(card_id=idx, due=due).to_dict(), due=due, last_rating=1))
            db.add(FactCoverage(user_id=user_id, fact_id=facts[idx].id, times_tested=1, last_correct=False, last_bloom="understand"))
        db.commit()


def test_review_selects_due_only_most_overdue_first_max_two_per_concept(client, test_engine):
    headers, doc = ready_document(client)
    user_id = _user_id(client, headers)
    # 7, 8 and 9 share one concept; 9 is the most overdue of them, 8 the least, so 8 is dropped by the cap.
    _set_cards(
        test_engine, user_id, doc,
        {1: 30, 7: 50, 8: 5, 9: 90, 12: 10, 15: -5, 20: -60},
        concept_of={7: "Shared", 8: "shared ", 9: "SHARED"},
    )
    with Session(test_engine) as db:
        targets = select_review_targets(db, user_id, uuid.UUID(doc), 10, datetime.now(timezone.utc))
    assert [t.fact.idx for t in targets] == [9, 7, 1, 12]
    assert MAX_PER_CONCEPT == 2
    # Bloom ladder: last answer wrong at understand → one level down.
    assert all(t.bloom_level == next_bloom("understand", False) == "remember" for t in targets)
    assert all(t.previous_bloom == "understand" for t in targets)
    with Session(test_engine) as db:
        assert [t.fact.idx for t in select_review_targets(db, user_id, uuid.UUID(doc), 2, datetime.now(timezone.utc))] == [9, 7]


def test_review_ignores_other_users_and_documents(client, test_engine):
    headers, doc = ready_document(client)
    other_headers, other_doc = ready_document(client, "other@b.com")
    _set_cards(test_engine, _user_id(client, other_headers), other_doc, {1: 30})
    with Session(test_engine) as db:
        assert select_review_targets(db, _user_id(client, headers), uuid.UUID(doc), 5, datetime.now(timezone.utc)) == []
        assert select_review_targets(db, _user_id(client, other_headers), uuid.UUID(doc), 5, datetime.now(timezone.utc)) == []


# ---- POST /quizzes mode ----
def test_nothing_due_is_409_with_next_due_and_no_quiz_or_llm_call(client, test_engine, monkeypatch):
    headers, doc = ready_document(client)
    spent = []
    monkeypatch.setattr(job, "generate", lambda *a, **k: spent.append(1) or [])

    r = _review(client, headers, doc)
    assert r.status_code == 409 and r.json() == {"detail": "Nothing due for review", "next_due": None}

    _set_cards(test_engine, _user_id(client, headers), doc, {4: -30})
    r = _review(client, headers, doc)
    assert r.status_code == 409 and r.json()["detail"] == "Nothing due for review"
    next_due = datetime.fromisoformat(r.json()["next_due"])
    assert timedelta(minutes=29) < next_due - datetime.now(timezone.utc) <= timedelta(minutes=30)
    with Session(test_engine) as db:
        assert db.scalar(select(func.count()).select_from(Quiz)) == 0
    assert spent == []


def test_mode_is_validated_and_defaults_to_practice(client):
    headers, doc = ready_document(client)
    bad = client.post("/quizzes", json={"document_id": doc, "mode": "exam"}, headers=headers)
    assert bad.status_code == 422
    assert make_quiz(client, headers, doc)["mode"] == "practice"


def test_review_quiz_targets_due_facts_passes_all_gates_and_commits_on_chain(client, test_engine, fake_chain):
    headers, doc = ready_document(client)
    first = make_quiz(client, headers, doc)
    qs = _answer(client, test_engine, headers, first["id"], right=lambda i: i in (1, 3))  # 3 wrong
    _age_cards(test_engine, 2)
    due_now = client.get(f"/documents/{doc}/review", headers=headers).json()["due_now"]
    with Session(test_engine) as db:
        due = set(db.scalars(select(Fact.idx).join(ReviewCard, ReviewCard.fact_id == Fact.id).where(ReviewCard.due <= func.now())))
    assert due_now == 3 and due == {qs[i].target_fact_idx for i in (0, 2, 4)}

    r = _review(client, headers, doc, n=5)
    assert r.status_code == 200, r.text
    quiz_id = r.json()["id"]
    body = client.get(f"/quizzes/{quiz_id}", headers=headers).json()
    assert body["status"] == "ready" and body["mode"] == "review"
    with Session(test_engine) as db:
        quiz = db.get(Quiz, uuid.UUID(quiz_id))
        review_qs = db.scalars(select(Question).where(Question.quiz_id == quiz.id).order_by(Question.position)).all()
        earlier_bloom = {q.target_fact_idx: q.bloom_level for q in qs}
        assert len(review_qs) == 3  # fewer due than asked → a shorter quiz
        assert {q.target_fact_idx for q in review_qs} <= due
        for q in review_qs:
            assert set(q.gate_results) == {"gate1", "gate2", "gate3", "gate4"}
            assert q.gate_results["gate1"]["verdict"] == "SUPPORTED" and q.gate_results["gate3"]["passed"]
            assert q.bloom_level == next_bloom(earlier_bloom[q.target_fact_idx], False)
        assert quiz.commit_tx and len(fake_chain) == 2 and fake_chain[-1] == (quiz_id, doc, quiz.quiz_hash)
        assert quiz.quiz_hash == quiz_hash(review_qs, quiz.salt, quiz.hash_version)

    # The review is answered like any quiz: right answers push the cards out of "due".
    _answer(client, test_engine, headers, quiz_id, right=lambda i: True)
    after = client.get(f"/documents/{doc}/review", headers=headers).json()
    assert after["due_now"] == 0 and after["cards"] == 5


def test_practice_selection_is_unchanged_by_review_cards(client, test_engine):
    headers, doc = ready_document(client)
    first = make_quiz(client, headers, doc)
    qs = _answer(client, test_engine, headers, first["id"], right=lambda i: False)
    _age_cards(test_engine, 60)  # everything due
    second = make_quiz(client, headers, doc)
    assert second["mode"] == "practice"
    with Session(test_engine) as db:
        targets = set(db.scalars(select(Question.target_fact_idx).where(Question.quiz_id == uuid.UUID(second["id"]))))
    assert targets.isdisjoint(q.target_fact_idx for q in qs)  # still tier 1 (unused) first, not the due cards


# ---- duplicates in review mode ----
def test_review_duplicate_check_is_within_the_quiz_only(client, test_engine):
    headers, doc = ready_document(client)
    make_quiz(client, headers, doc)
    with Session(test_engine) as db:
        earlier = db.scalars(select(Question)).first()
        checker = DuplicateChecker(db, earlier_user := _user_id(client, headers), uuid.UUID(doc), within_quiz_only=True)
        practice = DuplicateChecker(db, earlier_user, uuid.UUID(doc))
    vector = np.asarray(earlier.stem_embedding, dtype=np.float32)
    assert practice.check(earlier.fingerprint, vector)[0] == "dup_fingerprint"
    assert checker.check(earlier.fingerprint, vector) == (None, "")  # earlier quizzes are not compared
    checker.add(earlier.fingerprint, vector)
    assert checker.check(earlier.fingerprint, vector)[0] == "dup_fingerprint"  # within the new quiz they are
    assert checker.check("other", vector) == (None, "")  # no stem cosine in review mode


# ---- GET /documents/{id}/review ----
def test_review_summary_is_owner_only(client):
    headers, doc = ready_document(client)
    assert client.get(f"/documents/{doc}/review", headers=headers).json() == {"due_now": 0, "next_due": None, "cards": 0}
    other = signup_headers(client, "other@b.com")
    assert client.get(f"/documents/{doc}/review", headers=other).status_code == 404
    assert client.get(f"/documents/{doc}/review").status_code == 401


# ---- backfill ----
def _cards(test_engine) -> dict:
    with Session(test_engine) as db:
        return {
            (c.user_id, c.fact_id): (c.last_rating, c.card["state"], c.card["step"], round(c.card["stability"], 6),
                                     round(c.card["difficulty"], 6))
            for c in db.scalars(select(ReviewCard))
        }


def test_backfill_rebuilds_cards_and_is_idempotent(client, test_engine):
    headers, doc = ready_document(client)
    for k in range(3):
        quiz = make_quiz(client, headers, doc, n=10)
        _answer(client, test_engine, headers, quiz["id"], right=lambda i, k=k: (i + k) % 3 != 0)
    live = _cards(test_engine)
    assert len(live) > 0

    with test_engine.begin() as conn:
        conn.execute(text("DELETE FROM review_cards"))
    for _ in range(2):
        with Session(test_engine) as db:
            stats = backfill(db)
            db.commit()
        assert stats["cards"] == len(live)
        assert _cards(test_engine) == live
    with Session(test_engine) as db:
        assert review_summary(db, _user_id(client, headers), uuid.UUID(doc), datetime.now(timezone.utc)).cards == len(live)
