"""Public verify endpoints (SPEC sections 2 and 9.9). No auth, read-only, never any answer key or learner answer.

chain_status: confirmed (on-chain read succeeded), offline (registration/commit missing or the read failed).
When offline, verified_on_chain / onchain_* / match are null, never false: false always means a real
mismatch. With CHAIN_OPTIONAL=false a failed chain read returns 503.
"""
import threading
import time
import uuid
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.chain import credentials as cred
from app.chain import merkle
from app.chain.quizhash import quiz_hash
from app.chain.service import ChainError, chain_id_of, explorer_url, get_chain
from app.config import get_settings
from app.credentials import results
from app.db import get_db
from app.models import Attempt, Badge, CoSignature, Document, Fact, Question, Quiz, ResultBatch

RATE_LIMIT_PER_MINUTE = 30


class _RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def __call__(self, request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] >= 60:
                q.popleft()
            if len(q) >= self.per_minute:
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many verify requests; try again in a minute")
            q.append(now)


rate_limit = _RateLimiter(RATE_LIMIT_PER_MINUTE)
router = APIRouter(prefix="/verify", tags=["verify"], dependencies=[Depends(rate_limit)])


class VerifiedFactOut(BaseModel):
    idx: int
    text: str
    page: int
    text_hash: str
    leaf: str
    proof: list[str]
    verified_on_chain: bool | None


class CoSignInfo(BaseModel):
    educator_address: str
    at: int  # unix seconds, from the chain
    cosign_tx: str | None


class VerifyQuestionOut(BaseModel):
    question_id: uuid.UUID
    stem: str
    document_id: uuid.UUID
    doc_id_onchain: str
    onchain_root: str | None
    db_root: str
    chain_status: str
    facts: list[VerifiedFactOut]
    registry_address: str | None
    explorer_url: str | None
    cosign: CoSignInfo | None
    document_revoked: bool | None


class VerifyFactIn(BaseModel):
    document_id: uuid.UUID
    idx: int = Field(ge=0)
    text: str = Field(max_length=5000)


class VerifyFactOut(BaseModel):
    leaf: str
    verified_on_chain: bool | None
    root: str
    chain_status: str


class VerifyQuizOut(BaseModel):
    quiz_id: uuid.UUID
    recomputed_hash: str
    onchain_hash: str | None
    match: bool | None
    chain_status: str
    commit_tx: str | None
    explorer_url: str | None


class VerifyAttemptOut(BaseModel):
    attempt_id: uuid.UUID
    quiz_id: uuid.UUID
    score: int
    total: int
    attempt_hash: str
    recomputed_hash: str
    leaf: str
    proof: list[str]
    batch_id: str
    onchain_root: str | None
    match: bool | None
    verified_on_chain: bool | None
    anchor_tx: str | None
    explorer_url: str | None
    chain_status: str


class OnchainBadge(BaseModel):
    concept_hash: str
    evidence_hash: str
    issued_at: int
    revoked: bool


class VerifyBadgeOut(BaseModel):
    token_id: int
    holder_address: str
    document_id: uuid.UUID
    concept: str
    concept_hash: str
    evidence_hash: str
    evidence_attempts: list[uuid.UUID]
    onchain: OnchainBadge | None
    match: bool | None
    revoked: bool
    chain_status: str
    explorer_url: str | None


# Leaves per (document, root). A document's facts never change once it is ready.
_leaves_cache: dict[tuple[uuid.UUID, str], list[str]] = {}
_leaves_lock = threading.Lock()


def _leaves(db: Session, document: Document) -> list[str]:
    key = (document.id, document.fact_root)
    with _leaves_lock:
        if key in _leaves_cache:
            return _leaves_cache[key]
    leaves = db.scalars(select(Fact.leaf_hash).where(Fact.document_id == document.id).order_by(Fact.idx)).all()
    with _leaves_lock:
        _leaves_cache[key] = list(leaves)
    return list(leaves)


def _chain_failed(exc: ChainError) -> None:
    """Offline is acceptable only when the chain is optional."""
    if not get_settings().chain_optional:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Chain read failed: {exc}") from None


def _ready_document(db: Session, document_id: uuid.UUID) -> Document:
    document = db.get(Document, document_id)
    if document is None or document.status != "ready" or not document.fact_root:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return document


def _registry_address() -> str | None:
    return get_settings().registry_address or None


@router.get("/question/{question_id}", response_model=VerifyQuestionOut)
def verify_question(question_id: uuid.UUID, db: Session = Depends(get_db)) -> VerifyQuestionOut:
    question = db.get(Question, question_id)
    if question is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
    submitted = db.scalar(select(func.count()).select_from(Attempt).where(Attempt.quiz_id == question.quiz_id))
    if not submitted:
        # Otherwise a learner could read the cited facts mid-quiz (CLAUDE.md rule 7).
        raise HTTPException(status.HTTP_409_CONFLICT, "Available after the quiz is submitted")
    quiz = db.get(Quiz, question.quiz_id)
    document = _ready_document(db, quiz.document_id)
    leaves = _leaves(db, document)
    facts = db.scalars(
        select(Fact).where(Fact.document_id == document.id, Fact.idx.in_(question.fact_idxs)).order_by(Fact.idx)
    ).all()

    onchain_root: str | None = None
    verified: dict[int, bool | None] = {f.idx: None for f in facts}
    chain_status = "offline"
    cosign: CoSignInfo | None = None
    document_revoked: bool | None = None
    if document.register_tx:
        try:
            chain = get_chain()
            stored = chain.get_document(document.id)
            onchain_root = stored[0] if stored else None
            if stored:
                for f in facts:
                    verified[f.idx] = chain.verify_fact(document.id, f.leaf_hash, merkle.proof(leaves, f.idx))
                chain_status = "confirmed"
        except ChainError as exc:
            _chain_failed(exc)
            onchain_root, verified = None, {f.idx: None for f in facts}
    if chain_status == "confirmed" and get_settings().credentials_address:
        # Without a credentials contract (Review 1 setups) both stay null.
        try:
            chain = get_chain()
            signed = chain.get_cosign(document.id)
            document_revoked = chain.is_document_revoked(document.id)
            if signed:
                row = db.get(CoSignature, document.id)
                cosign = CoSignInfo(educator_address=signed[0], at=signed[1], cosign_tx=row.cosign_tx if row else None)
        except ChainError as exc:
            _chain_failed(exc)
            cosign, document_revoked = None, None

    return VerifyQuestionOut(
        question_id=question.id,
        stem=question.stem,
        document_id=document.id,
        doc_id_onchain=chain_id_of(document.id),
        onchain_root=onchain_root,
        db_root=document.fact_root,
        chain_status=chain_status,
        facts=[
            VerifiedFactOut(
                idx=f.idx,
                text=f.text,
                page=f.page,
                text_hash=f.text_hash,
                leaf=f.leaf_hash,
                proof=merkle.proof(leaves, f.idx),
                verified_on_chain=verified[f.idx],
            )
            for f in facts
        ],
        registry_address=_registry_address(),
        explorer_url=explorer_url(document.register_tx),
        cosign=cosign,
        document_revoked=document_revoked,
    )


@router.post("/fact", response_model=VerifyFactOut)
def verify_fact(body: VerifyFactIn, db: Session = Depends(get_db)) -> VerifyFactOut:
    """Recomputes the leaf from the given text and checks it with the stored proof for that idx."""
    document = _ready_document(db, body.document_id)
    leaves = _leaves(db, document)
    if body.idx >= len(leaves):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No fact with that idx")
    leaf = merkle.leaf(body.idx, merkle.text_hash(body.text))
    proof = merkle.proof(leaves, body.idx)
    verified: bool | None = None
    chain_status = "offline"
    if document.register_tx:
        try:
            chain = get_chain()
            if chain.get_document(document.id):
                verified = chain.verify_fact(document.id, leaf, proof)
                chain_status = "confirmed"
        except ChainError as exc:
            _chain_failed(exc)
            verified = None
    return VerifyFactOut(leaf=leaf, verified_on_chain=verified, root=document.fact_root, chain_status=chain_status)


@router.get("/quiz/{quiz_id}", response_model=VerifyQuizOut)
def verify_quiz(quiz_id: uuid.UUID, db: Session = Depends(get_db)) -> VerifyQuizOut:
    quiz = db.get(Quiz, quiz_id)
    if quiz is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    if quiz.status != "ready" or not quiz.salt:
        raise HTTPException(status.HTTP_409_CONFLICT, "Quiz is not ready")
    questions = db.scalars(select(Question).where(Question.quiz_id == quiz.id).order_by(Question.position)).all()
    recomputed = quiz_hash(questions, quiz.salt, quiz.hash_version)

    onchain_hash: str | None = None
    match: bool | None = None
    chain_status = "offline"
    if quiz.commit_tx:
        try:
            stored = get_chain().get_quiz(quiz.id)
            chain_status = "confirmed"
            onchain_hash = stored[1] if stored else None
            # Committed per our records but absent on chain is a real mismatch, not an outage.
            match = recomputed == onchain_hash
        except ChainError as exc:
            _chain_failed(exc)
            chain_status, onchain_hash, match = "offline", None, None

    return VerifyQuizOut(
        quiz_id=quiz.id,
        recomputed_hash=recomputed,
        onchain_hash=onchain_hash,
        match=match,
        chain_status=chain_status,
        commit_tx=quiz.commit_tx,
        explorer_url=explorer_url(quiz.commit_tx),
    )


@router.get("/attempt/{attempt_id}", response_model=VerifyAttemptOut)
def verify_attempt(attempt_id: uuid.UUID, db: Session = Depends(get_db)) -> VerifyAttemptOut:
    """Recomputes the attempt hash from the stored fields and checks its leaf against the anchored batch root.
    Score and hashes only: the learner's answers never leave the server."""
    attempt = db.get(Attempt, attempt_id)
    if attempt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")
    batch = db.get(ResultBatch, attempt.batch_id) if attempt.batch_id else None
    if batch is None or attempt.attempt_hash is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Available after the result is anchored")
    recomputed = results.recompute_hash(db, attempt)
    leaves = results.batch_leaves(db, batch)
    leaf = merkle.result_leaf(attempt.attempt_hash)
    proof = merkle.proof(leaves, leaves.index(leaf))

    onchain_root: str | None = None
    verified: bool | None = None
    match: bool | None = None
    chain_status = "offline"
    if batch.anchor_tx:
        try:
            chain = get_chain()
            stored = chain.get_batch(batch.batch_id)
            chain_status = "confirmed"
            onchain_root = stored[0] if stored else None
            # Anchored per our records but absent on chain is a real mismatch, not an outage.
            verified = chain.verify_result(batch.batch_id, merkle.result_leaf(recomputed), proof) if stored else False
            match = recomputed == attempt.attempt_hash and verified
        except ChainError as exc:
            _chain_failed(exc)
            chain_status, onchain_root, verified, match = "offline", None, None, None

    return VerifyAttemptOut(
        attempt_id=attempt.id, quiz_id=attempt.quiz_id, score=attempt.score, total=attempt.total,
        attempt_hash=attempt.attempt_hash, recomputed_hash=recomputed, leaf=leaf, proof=proof,
        batch_id=batch.batch_id, onchain_root=onchain_root, match=match, verified_on_chain=verified,
        anchor_tx=batch.anchor_tx, explorer_url=explorer_url(batch.anchor_tx), chain_status=chain_status,
    )


@router.get("/badge/{token_id}", response_model=VerifyBadgeOut)
def verify_badge(token_id: int, db: Session = Depends(get_db)) -> VerifyBadgeOut:
    """match: the on-chain hashes and holder equal ours, and the evidence hash recomputes from the evidence attempts."""
    badge = db.scalar(select(Badge).where(Badge.token_id == token_id))
    if badge is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Badge not found")
    hashes = db.scalars(select(Attempt.attempt_hash).where(Attempt.id.in_(badge.evidence_attempt_ids))).all()
    evidence_ok = (
        len(hashes) == len(badge.evidence_attempt_ids)
        and all(hashes)
        and cred.evidence_hash(list(hashes)) == badge.evidence_hash
        and cred.concept_hash(badge.document_id, badge.concept) == badge.concept_hash
    )

    onchain: OnchainBadge | None = None
    match: bool | None = None
    revoked = badge.revoked
    chain_status = "offline"
    if badge.mint_tx:
        try:
            chain = get_chain()
            stored = chain.get_badge(token_id)
            chain_status = "confirmed"
            if stored is None:
                match = False
            else:
                onchain = OnchainBadge(**{k: stored[k] for k in ("concept_hash", "evidence_hash", "issued_at", "revoked")})
                holder = chain.owner_of(token_id)
                match = (
                    evidence_ok
                    and stored["doc_id"] == chain_id_of(badge.document_id)
                    and stored["concept_hash"] == badge.concept_hash
                    and stored["evidence_hash"] == badge.evidence_hash
                    and holder == badge.holder_address
                )
                revoked = stored["revoked"]  # the chain is the authority on revocation
        except ChainError as exc:
            _chain_failed(exc)
            chain_status, onchain, match, revoked = "offline", None, None, badge.revoked

    return VerifyBadgeOut(
        token_id=token_id, holder_address=badge.holder_address, document_id=badge.document_id, concept=badge.concept,
        concept_hash=badge.concept_hash, evidence_hash=badge.evidence_hash,
        evidence_attempts=list(badge.evidence_attempt_ids), onchain=onchain, match=match, revoked=revoked,
        chain_status=chain_status, explorer_url=explorer_url(badge.mint_tx),
    )
