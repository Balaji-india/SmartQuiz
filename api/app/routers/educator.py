"""Educator-only endpoints (SPEC 9.9): result anchoring, the deferred-grading queue, document co-sign and revocation,
badge revocation. 403 for everyone else.

Every educator action on chain carries an EIP-712 signature from the server-held educator wallet
(EDUCATOR_PRIVATE_KEY); the issuer sends the tx. educator_id records which educator user asked for it.
Revocation reasons stay in the database: only keccak256(reason) goes on chain (CLAUDE.md rule 6).
"""
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_educator
from app.chain import credentials as cred
from app.chain.service import ChainError, chain_id_of, explorer_url, get_chain
from app.credentials import results
from app.db import get_db
from app.learn.shortgrade import apply_educator_grade
from app.models import AnswerGrade, Attempt, Badge, CoSignature, Document, Fact, Question, Quiz, ResultBatch, User
from app.routers.badges import BadgeOut, badge_out, chain_http_error
from app.routers.documents import DocumentOut, _document_out

router = APIRouter(prefix="/educator", tags=["educator"], dependencies=[Depends(require_educator)])


class AnchorOut(BaseModel):
    batch_id: str
    root: str
    count: int
    anchor_tx: str | None
    explorer_url: str | None
    chain_status: str


class BatchOut(BaseModel):
    batch_id: str
    root: str
    count: int
    anchor_tx: str | None
    explorer_url: str | None
    created_at: datetime


class ResultsOut(BaseModel):
    unanchored: int  # final attempts waiting for the next batch
    pending_grading: int  # attempts still waiting for an educator grade (anchorable once final)
    batches: list[BatchOut]  # newest first


class EducatorBadgeOut(BadgeOut):
    learner_name: str  # off chain only


class CheckerOut(BaseModel):
    verdict: str | None
    confidence: int | None
    reason: str | None


class GradingFactOut(BaseModel):
    idx: int
    text: str
    page: int


class GradingItemOut(BaseModel):
    grade_id: uuid.UUID
    attempt_id: uuid.UUID
    question_id: uuid.UUID
    stem: str
    model_answer: str | None
    answer_text: str | None
    checker: CheckerOut
    facts: list[GradingFactOut]


class GradeIn(BaseModel):
    verdict: Literal["correct", "partial", "incorrect"]


class GradeDoneOut(BaseModel):
    grade_id: uuid.UUID
    attempt_id: uuid.UUID
    grading_status: str


class CoSignOut(BaseModel):
    educator_address: str
    at: datetime
    cosign_tx: str | None


class EducatorDocumentOut(DocumentOut):
    cosign: CoSignOut | None
    revoked: bool


class CoSignResultOut(BaseModel):
    educator_address: str
    signature: str
    cosign_tx: str | None
    explorer_url: str | None
    chain_status: str


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


def _educator_document_out(db: Session, document: Document) -> EducatorDocumentOut:
    c = db.get(CoSignature, document.id)
    return EducatorDocumentOut(
        **_document_out(document).model_dump(),
        cosign=CoSignOut(educator_address=c.educator_address, at=c.created_at, cosign_tx=c.cosign_tx) if c else None,
        revoked=document.revoked,
    )


def _ready_document(db: Session, document_id: uuid.UUID) -> Document:
    document = db.scalar(select(Document).where(Document.id == document_id).with_for_update())
    if document is None or document.status != "ready":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return document


# ---- results ----
@router.get("/results", response_model=ResultsOut)
def results_overview(db: Session = Depends(get_db)) -> ResultsOut:
    def waiting(grading_status: str) -> int:
        return db.scalar(
            select(func.count()).select_from(Attempt)
            .where(Attempt.grading_status == grading_status, Attempt.batch_id.is_(None))
        )

    batches = db.scalars(select(ResultBatch).order_by(ResultBatch.created_at.desc(), ResultBatch.id)).all()
    return ResultsOut(
        unanchored=waiting("final"),
        pending_grading=waiting("pending_review"),
        batches=[BatchOut(batch_id=b.batch_id, root=b.root, count=b.count, anchor_tx=b.anchor_tx,
                          explorer_url=explorer_url(b.anchor_tx), created_at=b.created_at) for b in batches],
    )


@router.post("/anchor", response_model=AnchorOut)
def anchor_results(db: Session = Depends(get_db)) -> AnchorOut:
    attempts = results.unanchored_final(db)
    if not attempts:
        raise HTTPException(status.HTTP_409_CONFLICT, "No final results waiting to be anchored")
    try:
        batch = results.anchor(db, attempts)
    except ChainError as exc:
        db.rollback()
        raise chain_http_error(exc) from None
    db.commit()
    return AnchorOut(batch_id=batch.batch_id, root=batch.root, count=batch.count, anchor_tx=batch.anchor_tx,
                     explorer_url=explorer_url(batch.anchor_tx), chain_status="confirmed")


# ---- grading queue (SPEC 9.7) ----
@router.get("/grading", response_model=list[GradingItemOut])
def grading_queue(db: Session = Depends(get_db)) -> list[GradingItemOut]:
    rows = db.execute(
        select(AnswerGrade, Question, Quiz.document_id)
        .join(Question, Question.id == AnswerGrade.question_id)
        .join(Quiz, Quiz.id == Question.quiz_id)
        .where(AnswerGrade.deferred.is_(True), AnswerGrade.educator_verdict.is_(None))
        .order_by(AnswerGrade.created_at, AnswerGrade.id)
    ).all()
    out = []
    for grade, question, document_id in rows:
        facts = db.scalars(
            select(Fact).where(Fact.document_id == document_id, Fact.idx.in_(question.fact_idxs)).order_by(Fact.idx)
        ).all()
        out.append(
            GradingItemOut(
                grade_id=grade.id, attempt_id=grade.attempt_id, question_id=question.id, stem=question.stem,
                model_answer=question.model_answer, answer_text=grade.answer_text,
                checker=CheckerOut(verdict=grade.verdict, confidence=grade.confidence, reason=grade.reason),
                facts=[GradingFactOut(idx=f.idx, text=f.text, page=f.page) for f in facts],
            )
        )
    return out


@router.post("/grading/{grade_id}", response_model=GradeDoneOut)
def grade_answer(
    grade_id: uuid.UUID, body: GradeIn, db: Session = Depends(get_db), educator: User = Depends(require_educator)
) -> GradeDoneOut:
    try:
        grade = apply_educator_grade(db, grade_id, body.verdict, educator)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Grade not found") from None
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    db.commit()
    attempt = db.get(Attempt, grade.attempt_id)
    return GradeDoneOut(grade_id=grade.id, attempt_id=attempt.id, grading_status=attempt.grading_status)


# ---- documents ----
@router.get("/documents", response_model=list[EducatorDocumentOut])
def list_documents(db: Session = Depends(get_db)) -> list[EducatorDocumentOut]:
    docs = db.scalars(select(Document).where(Document.status == "ready").order_by(Document.created_at.desc())).all()
    return [_educator_document_out(db, d) for d in docs]


@router.post("/documents/{document_id}/cosign", response_model=CoSignResultOut)
def cosign_document(
    document_id: uuid.UUID, db: Session = Depends(get_db), educator: User = Depends(require_educator)
) -> CoSignResultOut:
    document = _ready_document(db, document_id)
    if document.revoked:
        raise HTTPException(status.HTTP_409_CONFLICT, "Document is revoked")
    if not document.register_tx or not document.fact_root:
        raise HTTPException(status.HTTP_409_CONFLICT, "Document is not registered on chain yet")
    try:
        chain = get_chain()
        address, signature = chain.educator_sign("CoSign", docId=chain_id_of(document.id), factRoot=document.fact_root)
        tx = chain.cosign_document(document.id, document.fact_root, signature)
    except ChainError as exc:
        db.rollback()
        raise chain_http_error(exc) from None
    row = db.get(CoSignature, document.id) or CoSignature(document_id=document.id)
    row.educator_id, row.educator_address, row.signature, row.cosign_tx = educator.id, address, signature, tx
    row.created_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    return CoSignResultOut(educator_address=address, signature=signature, cosign_tx=tx,
                           explorer_url=explorer_url(tx), chain_status="confirmed")


@router.post("/documents/{document_id}/revoke", response_model=EducatorDocumentOut)
def revoke_document(document_id: uuid.UUID, body: ReasonIn, db: Session = Depends(get_db)) -> EducatorDocumentOut:
    document = _ready_document(db, document_id)
    if document.revoked:
        raise HTTPException(status.HTTP_409_CONFLICT, "Document is already revoked")
    reason_hash = cred.reason_hash(body.reason)
    try:
        chain = get_chain()
        _, signature = chain.educator_sign("RevokeDocument", docId=chain_id_of(document.id), reasonHash=reason_hash)
        tx = chain.revoke_document(document.id, reason_hash, signature)
    except ChainError as exc:
        db.rollback()
        raise chain_http_error(exc) from None
    document.revoked, document.revoke_tx, document.revoke_reason = True, tx, body.reason
    db.commit()
    return _educator_document_out(db, document)


# ---- badges ----
@router.get("/badges", response_model=list[EducatorBadgeOut])
def list_all_badges(db: Session = Depends(get_db)) -> list[EducatorBadgeOut]:
    rows = db.execute(
        select(Badge, User.name).join(User, User.id == Badge.user_id)
        .where(Badge.token_id.is_not(None)).order_by(Badge.created_at.desc(), Badge.id)
    ).all()
    return [EducatorBadgeOut(**badge_out(b).model_dump(), learner_name=name) for b, name in rows]


@router.post("/badges/{badge_id}/revoke", response_model=BadgeOut)
def revoke_badge(badge_id: uuid.UUID, body: ReasonIn, db: Session = Depends(get_db)) -> BadgeOut:
    badge = db.scalar(select(Badge).where(Badge.id == badge_id).with_for_update())
    if badge is None or badge.token_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Badge not found")
    if badge.revoked:
        raise HTTPException(status.HTTP_409_CONFLICT, "Badge is already revoked")
    reason_hash = cred.reason_hash(body.reason)
    try:
        chain = get_chain()
        _, signature = chain.educator_sign("RevokeBadge", tokenId=badge.token_id, reasonHash=reason_hash)
        tx = chain.revoke_badge(badge.token_id, reason_hash, signature)
    except ChainError as exc:
        db.rollback()
        raise chain_http_error(exc) from None
    badge.revoked, badge.revoke_tx, badge.revoke_reason = True, tx, body.reason
    db.commit()
    return badge_out(badge)
