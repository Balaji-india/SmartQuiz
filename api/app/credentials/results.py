"""Attempt hashes and result batches (SPEC 9.9). Only hashes go on chain (CLAUDE.md rule 6).

attempt_hash is computed once grading is final (at submit, or when an educator grades the last deferred answer) and
lazily for older final attempts when they are anchored. A batch's leaves are its attempts in (created_at, id) order.
"""
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chain import credentials as cred
from app.chain import merkle
from app.chain.service import get_chain
from app.models import AnswerGrade, Attempt, Question, ResultBatch


def final_grades(db: Session, attempt: Attempt) -> list[str | None]:
    """One entry per position: the final verdict of a short answer, null for MCQ (SPEC 9.9)."""
    questions = db.scalars(select(Question).where(Question.quiz_id == attempt.quiz_id).order_by(Question.position)).all()
    grades = {g.question_id: g for g in db.scalars(select(AnswerGrade).where(AnswerGrade.attempt_id == attempt.id))}
    return [grades[q.id].final_verdict if q.qtype == "short" and q.id in grades else None for q in questions]


def recompute_hash(db: Session, attempt: Attempt) -> str:
    """The attempt hash from the stored fields (used by /verify/attempt)."""
    return cred.attempt_hash(
        attempt.quiz_id, attempt.answers, attempt.score, attempt.total, final_grades(db, attempt), attempt.attempt_salt
    )


def ensure_attempt_hash(db: Session, attempt: Attempt) -> str | None:
    """Sets attempt_salt and attempt_hash once grading is final; None while a grade is pending. Never changes a hash."""
    if attempt.grading_status != "final":
        return None
    if attempt.attempt_hash is None:
        attempt.attempt_salt = attempt.attempt_salt or secrets.token_hex(16)
        attempt.attempt_hash = recompute_hash(db, attempt)
    return attempt.attempt_hash


def unanchored_final(db: Session, user_id: uuid.UUID | None = None) -> list[Attempt]:
    """Final attempts not in any batch, locked so two anchors cannot take the same attempt."""
    q = select(Attempt).where(Attempt.grading_status == "final", Attempt.batch_id.is_(None))
    if user_id is not None:
        q = q.where(Attempt.user_id == user_id)
    return list(db.scalars(q.order_by(Attempt.created_at, Attempt.id).with_for_update(skip_locked=True)))


def anchor(db: Session, attempts: list[Attempt]) -> ResultBatch:
    """Anchors one batch on chain (raises ChainError) and records it. The caller commits; on any error it must roll
    back, so nothing is marked anchored (a later retry builds a new batch)."""
    if not attempts:
        raise ValueError("nothing to anchor")
    attempts = sorted(attempts, key=lambda a: (a.created_at, a.id))
    leaves = [merkle.result_leaf(ensure_attempt_hash(db, a)) for a in attempts]
    root = merkle.build_tree(leaves)
    batch = ResultBatch(id=uuid.uuid4(), root=root, count=len(leaves))
    batch.batch_id = cred.batch_chain_id(batch.id)
    batch.anchor_tx = get_chain().anchor_results(batch.batch_id, root, len(leaves))
    db.add(batch)
    db.flush()
    for a in attempts:
        a.batch_id = batch.id
    db.flush()
    return batch


def batch_leaves(db: Session, batch: ResultBatch) -> list[str]:
    hashes = db.scalars(
        select(Attempt.attempt_hash).where(Attempt.batch_id == batch.id).order_by(Attempt.created_at, Attempt.id)
    ).all()
    return [merkle.result_leaf(h) for h in hashes]
