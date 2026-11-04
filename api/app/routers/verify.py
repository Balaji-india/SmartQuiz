"""Public verify endpoints (SPEC section 2). No auth, read-only, never any answer key.

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

from app.chain import merkle
from app.chain.quizhash import quiz_hash
from app.chain.service import ChainError, chain_id_of, explorer_url, get_chain
from app.config import get_settings
from app.db import get_db
from app.models import Attempt, Document, Fact, Question, Quiz

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
    recomputed = quiz_hash(questions, quiz.salt)

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
