"""Concept badges (SPEC 9.9). A badge exists only on chain, so a mint needs the chain even with CHAIN_OPTIONAL=true.

POST /badges: 404 unknown concept, 409 unless mastered (or the document is revoked), the live badge is returned as is
if one exists; otherwise this user's unanchored final attempts are anchored first, then the badge is minted to the
user's wallet or, without one, to the custodial address (503 while CUSTODY_SECRET is empty).
"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.chain import credentials as cred
from app.chain.service import ChainError, ChainRevert, explorer_url, get_chain
from app.credentials import results
from app.credentials.badges import CustodyUnavailable, custodial_address, evidence_attempts, live_badge
from app.db import get_db
from app.learn.mastery import concept_key, mastery_status
from app.models import Badge, Fact, Mastery, User
from app.routers.documents import _own_document

router = APIRouter(prefix="/badges", tags=["badges"])

# Contract errors that mean "this request conflicts with the chain state", not "the chain is down".
CONFLICT_REVERTS = {"RootMismatch", "AlreadyRevoked", "BatchExists", "UnknownToken", "Soulbound"}


def chain_http_error(exc: ChainError) -> HTTPException:
    if isinstance(exc, ChainRevert) and exc.name in CONFLICT_REVERTS:
        return HTTPException(status.HTTP_409_CONFLICT, f"Rejected on chain: {exc.name}")
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Chain unavailable: {exc}")


class BadgeIn(BaseModel):
    document_id: uuid.UUID
    concept: str


class BadgeOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    concept: str
    token_id: int | None
    holder_address: str
    custodial: bool
    concept_hash: str
    evidence_hash: str
    mint_tx: str | None
    explorer_url: str | None
    revoked: bool
    chain_status: str
    created_at: datetime


def badge_out(b: Badge) -> BadgeOut:
    return BadgeOut(
        id=b.id, document_id=b.document_id, concept=b.concept, token_id=b.token_id, holder_address=b.holder_address,
        custodial=b.custodial, concept_hash=b.concept_hash, evidence_hash=b.evidence_hash, mint_tx=b.mint_tx,
        explorer_url=explorer_url(b.mint_tx), revoked=b.revoked,
        chain_status="confirmed" if b.mint_tx else "offline", created_at=b.created_at,
    )


@router.post("", response_model=BadgeOut)
def claim_badge(body: BadgeIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> BadgeOut:
    document = _own_document(body.document_id, db, user)
    if document.revoked:
        raise HTTPException(status.HTTP_409_CONFLICT, "This document was revoked by an educator")
    key = concept_key(body.concept)
    concept = db.scalar(
        select(Fact.concept)
        .where(Fact.document_id == document.id, func.lower(func.trim(Fact.concept)) == key)
        .order_by(Fact.idx)
        .limit(1)
    )
    if concept is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such concept in this document")
    concept = concept.strip()

    # One claim at a time per user: two requests cannot both mint.
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    existing = live_badge(db, user.id, document.id, concept)
    if existing is not None:
        return badge_out(existing)
    row = db.scalar(
        select(Mastery).where(
            Mastery.user_id == user.id, Mastery.document_id == document.id, func.lower(func.trim(Mastery.concept)) == key
        )
    )
    if row is None or mastery_status(row.p_mastery, row.answered) != "mastered":
        raise HTTPException(status.HTTP_409_CONFLICT, "Concept is not mastered yet")
    evidence = evidence_attempts(db, user.id, document.id, concept)
    if not evidence:  # mastery comes only from final grades, so this means the attempts were removed
        raise HTTPException(status.HTTP_409_CONFLICT, "No final attempt tested this concept")

    if user.wallet_address:
        holder, custodial = user.wallet_address, False
    else:
        try:
            holder, custodial = custodial_address(user.id), True
        except CustodyUnavailable as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None

    try:
        chain = get_chain()
        chain.credentials  # fail before anchoring if the contract is not configured
        if any(a.batch_id is None for a in evidence):
            # Anchor every unanchored final attempt of this user, then keep the batch even if the mint fails.
            results.anchor(db, results.unanchored_final(db, user.id))
            db.commit()
        hashes = [a.attempt_hash for a in evidence]
        if any(h is None for h in hashes):  # another request is anchoring them right now
            raise HTTPException(status.HTTP_409_CONFLICT, "Results are being anchored; try again")
        badge = Badge(
            user_id=user.id, document_id=document.id, concept=concept, holder_address=holder, custodial=custodial,
            concept_hash=cred.concept_hash(document.id, concept), evidence_hash=cred.evidence_hash(hashes),
            evidence_attempt_ids=[a.id for a in evidence],
        )
        badge.mint_tx, badge.token_id = chain.mint_badge(holder, document.id, badge.concept_hash, badge.evidence_hash)
    except ChainError as exc:
        db.rollback()
        raise chain_http_error(exc) from None
    db.add(badge)
    db.commit()
    db.refresh(badge)
    return badge_out(badge)


@router.get("", response_model=list[BadgeOut])
def list_badges(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[BadgeOut]:
    rows = db.scalars(select(Badge).where(Badge.user_id == user.id).order_by(Badge.created_at.desc())).all()
    return [badge_out(b) for b in rows]
