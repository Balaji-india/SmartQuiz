"""Concept badges (SPEC 9.9): evidence, custodial holder addresses and the hashes sent with a mint.

Custodial address = address of the private key keccak256(utf-8(CUSTODY_SECRET + "|" + user UUID)). The key is derived
only to get its address: it is never stored, logged or used to sign. CUSTODY_SECRET must never change once a custodial
badge exists (every custodial address would change with it).
"""
import uuid

from eth_account import Account
from eth_utils import keccak
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.learn.mastery import concept_key
from app.models import Attempt, Badge, Fact, Question, Quiz


class CustodyUnavailable(RuntimeError):
    """CUSTODY_SECRET is empty, so no custodial address can be derived."""


def custodial_address(user_id: uuid.UUID | str) -> str:
    secret = get_settings().custody_secret
    if not secret:
        raise CustodyUnavailable("custodial badges are disabled: CUSTODY_SECRET is empty")
    return Account.from_key(keccak(f"{secret}|{user_id}".encode("utf-8"))).address


def evidence_attempts(db: Session, user_id: uuid.UUID, document_id: uuid.UUID, concept: str) -> list[Attempt]:
    """The user's final attempts on this document with at least one question whose TARGET fact has the concept."""
    ids = (
        select(Attempt.id)
        .join(Quiz, Quiz.id == Attempt.quiz_id)
        .join(Question, Question.quiz_id == Quiz.id)
        .join(Fact, (Fact.document_id == Quiz.document_id) & (Fact.idx == Question.target_fact_idx))
        .where(
            Attempt.user_id == user_id,
            Attempt.grading_status == "final",
            Quiz.document_id == document_id,
            func.lower(func.trim(Fact.concept)) == concept_key(concept),
        )
        .distinct()
    )
    return list(db.scalars(select(Attempt).where(Attempt.id.in_(ids)).order_by(Attempt.created_at, Attempt.id)))


def live_badge(db: Session, user_id: uuid.UUID, document_id: uuid.UUID, concept: str) -> Badge | None:
    return db.scalar(
        select(Badge).where(
            Badge.user_id == user_id,
            Badge.document_id == document_id,
            func.lower(func.trim(Badge.concept)) == concept_key(concept),
            Badge.revoked.is_(False),
        )
    )


def live_badge_ids(db: Session, user_id: uuid.UUID, document_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """concept key -> id of the user's unrevoked badge (MasteryOut.badge_id)."""
    rows = db.execute(
        select(Badge.concept, Badge.id).where(
            Badge.user_id == user_id, Badge.document_id == document_id, Badge.revoked.is_(False)
        )
    ).all()
    return {concept_key(c): i for c, i in rows}
