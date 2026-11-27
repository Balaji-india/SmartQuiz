"""FSRS review cards per user + fact (SPEC 9.6). No LLM.

One card per (user, target fact), updated on every final grade from the "on final grade" hook:
wrong → Again, partial → Hard, correct → Good, with the default `fsrs.Scheduler`.
The card is stored as `Card.to_dict()`; `due` is copied into its own column so review selection can sort on it.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from fsrs import Card, Rating, Scheduler
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Fact, ReviewCard

RATING = {"wrong": Rating.Again, "partial": Rating.Hard, "correct": Rating.Good}

_scheduler = Scheduler()


def rating_for(grade: str) -> Rating:
    if grade not in RATING:
        raise ValueError(f"unknown grade {grade!r}")
    return RATING[grade]


def _utc(when: datetime) -> datetime:
    """fsrs wants tz-aware UTC; the database may hand back another offset."""
    if when.tzinfo is None:
        return when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc)


def update_card(db: Session, user_id: uuid.UUID, fact: Fact, grade: str, now: datetime) -> Card:
    """Apply one final grade to the (user, fact) card, created on first use. Runs in the caller's transaction."""
    rating = rating_for(grade)
    now = _utc(now)
    row = db.scalar(
        select(ReviewCard).where(ReviewCard.user_id == user_id, ReviewCard.fact_id == fact.id).with_for_update()
    )
    card = Card.from_dict(row.card) if row else Card(card_id=fact.id)  # card_id = fact id: stable, no clock wait
    card, _ = _scheduler.review_card(card, rating, review_datetime=now)
    values = {"card": card.to_dict(), "due": card.due, "last_rating": int(rating)}
    db.execute(
        insert(ReviewCard)
        .values(user_id=user_id, fact_id=fact.id, **values)
        .on_conflict_do_update(index_elements=[ReviewCard.user_id, ReviewCard.fact_id], set_=values)
    )
    return card


@dataclass(frozen=True)
class ReviewSummary:
    due_now: int
    next_due: datetime | None
    cards: int


def review_summary(db: Session, user_id: uuid.UUID, document_id: uuid.UUID, now: datetime) -> ReviewSummary:
    """due_now = cards with due <= now; next_due = the earliest due after now (null if none)."""
    base = (
        select(ReviewCard.due)
        .join(Fact, Fact.id == ReviewCard.fact_id)
        .where(ReviewCard.user_id == user_id, Fact.document_id == document_id)
        .subquery()
    )
    total, due_now, next_due = db.execute(
        select(
            func.count(),
            func.count().filter(base.c.due <= now),
            func.min(base.c.due).filter(base.c.due > now),
        ).select_from(base)
    ).one()
    return ReviewSummary(due_now=due_now, next_due=next_due, cards=total)


def due_cards(db: Session, user_id: uuid.UUID, document_id: uuid.UUID, now: datetime) -> list[tuple[Fact, ReviewCard]]:
    """Due cards of this user + document, most overdue first (ties by fact idx)."""
    return [
        (fact, card)
        for card, fact in db.execute(
            select(ReviewCard, Fact)
            .join(Fact, Fact.id == ReviewCard.fact_id)
            .where(ReviewCard.user_id == user_id, Fact.document_id == document_id, ReviewCard.due <= now)
            .order_by(ReviewCard.due, Fact.idx)
        ).all()
    ]
