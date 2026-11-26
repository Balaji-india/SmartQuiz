"""BKT mastery per user + document + concept (SPEC 9.4). Pure functions plus one row update; no LLM.

The concept of a graded question is the concept of its TARGET fact, never of its context facts.
Concepts match case-insensitively (strip + lower); the stored name is the spelling on the concept's lowest-idx fact.
"""
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Fact, Mastery

P_INIT = 0.2
P_LEARN = 0.15
P_SLIP = 0.10
P_GUESS = {"mcq": 0.25, "short": 0.05}
WEAK_BELOW = 0.40
MASTERED_FROM = 0.95
GRADES = ("correct", "partial", "wrong")


def bkt_update(p: float, grade: str, qtype: str = "mcq") -> float:
    """One BKT step: the posterior given the answer, then the learning transition. Partial counts as wrong."""
    if grade not in GRADES:
        raise ValueError(f"unknown grade {grade!r}")
    g = P_GUESS[qtype]
    if grade == "correct":
        posterior = p * (1 - P_SLIP) / (p * (1 - P_SLIP) + (1 - p) * g)
    else:
        posterior = p * P_SLIP / (p * P_SLIP + (1 - p) * (1 - g))
    return posterior + (1 - posterior) * P_LEARN


def mastery_status(p: float, answered: int) -> str:
    if answered == 0:
        return "untested"
    if p < WEAK_BELOW:
        return "weak"
    return "mastered" if p >= MASTERED_FROM else "learning"


def concept_key(concept: str) -> str:
    return concept.strip().lower()


def canonical_concept(db: Session, document_id: uuid.UUID, concept: str) -> str:
    """The stored spelling: the concept text of the lowest-idx fact with the same key."""
    first = db.scalar(
        select(Fact.concept)
        .where(Fact.document_id == document_id, func.lower(func.trim(Fact.concept)) == concept_key(concept))
        .order_by(Fact.idx)
        .limit(1)
    )
    return (first or concept).strip()


def update_mastery(
    db: Session, user_id: uuid.UUID, document_id: uuid.UUID, concept: str, grade: str, qtype: str, now: datetime
) -> float:
    """Apply one final grade to the concept's row (created at P_INIT). Runs in the caller's transaction."""
    name = canonical_concept(db, document_id, concept)
    row = db.scalar(
        select(Mastery)
        .where(Mastery.user_id == user_id, Mastery.document_id == document_id, Mastery.concept == name)
        .with_for_update()
    )
    p = bkt_update(row.p_mastery if row else P_INIT, grade, qtype)
    stmt = insert(Mastery).values(
        user_id=user_id, document_id=document_id, concept=name, p_mastery=p, answered=1, updated_at=now
    )
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=[Mastery.user_id, Mastery.document_id, Mastery.concept],
            set_={"p_mastery": p, "answered": Mastery.answered + 1, "updated_at": now},
        )
    )
    return p
