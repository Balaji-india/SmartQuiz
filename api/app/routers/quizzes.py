"""Quizzes (SPEC section 2). answer_index and target_fact_idx never leave the server through QuizOut;
fact_idxs only after the attempt is submitted (CLAUDE.md rule 7)."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.auth import get_current_user
from app.chain.service import explorer_url
from app.config import get_settings
from app.db import get_db
from app.models import Attempt, Document, Fact, FactCoverage, GenerationLog, Question, Quiz, Section, User
from app.quiz.job import get_progress, run_quiz_job

router = APIRouter(prefix="/quizzes", tags=["quizzes"])

TIME_GRACE_SEC = 30


class QuizCreate(BaseModel):
    document_id: uuid.UUID
    num_questions: int = Field(10, ge=1, le=20)
    time_limit_sec: int = Field(600, ge=60, le=7200)


class QuestionOut(BaseModel):
    id: uuid.UUID
    position: int
    stem: str
    options: list[str]
    bloom_level: str
    flagged_general: bool
    fact_idxs: list[int] | None = None  # only after the attempt is submitted


class GenerationOut(BaseModel):
    candidates: int
    accepted: int
    rejected: int


class QuizOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    status: str
    time_limit_sec: int
    quiz_hash: str | None
    commit_tx: str | None
    explorer_url: str | None
    chain_status: str
    started_at: datetime | None
    submitted: bool
    questions: list[QuestionOut]
    generation: GenerationOut | None


class QuizProgressOut(BaseModel):
    accepted: int
    rejected: int
    target: int
    stage: str


class AttemptIn(BaseModel):
    answers: list[int | None]
    time_taken_sec: int = Field(ge=0)


class SourceOut(BaseModel):
    idx: int
    text: str
    page: int
    section: str


class ResultOut(BaseModel):
    question_id: uuid.UUID
    chosen: int | None
    correct_index: int
    correct: bool
    sources: list[SourceOut]


class WeakConceptOut(BaseModel):
    concept: str
    wrong: int
    facts: list[int]


class AttemptResult(BaseModel):
    attempt_id: uuid.UUID
    score: int
    total: int
    results: list[ResultOut]
    weak_concepts: list[WeakConceptOut]


def _chain_status(quiz: Quiz) -> str:
    if quiz.status == "generating":
        return "pending"
    return "confirmed" if quiz.commit_tx else "offline"


def _questions(db: Session, quiz: Quiz) -> list[Question]:
    return db.scalars(select(Question).where(Question.quiz_id == quiz.id).order_by(Question.position)).all()


def _has_attempt(db: Session, quiz: Quiz) -> bool:
    return db.scalar(select(func.count()).select_from(Attempt).where(Attempt.quiz_id == quiz.id)) > 0


def _generation(db: Session, quiz: Quiz) -> GenerationOut:
    candidates = db.scalar(
        select(func.count(func.distinct(GenerationLog.candidate_id))).where(
            GenerationLog.quiz_id == quiz.id, GenerationLog.candidate_id.is_not(None)
        )
    )
    rejected = db.scalar(
        select(func.count(func.distinct(GenerationLog.candidate_id))).where(
            GenerationLog.quiz_id == quiz.id, GenerationLog.candidate_id.is_not(None), GenerationLog.passed.is_(False)
        )
    )
    accepted = db.scalar(select(func.count()).select_from(Question).where(Question.quiz_id == quiz.id))
    return GenerationOut(candidates=candidates, accepted=accepted, rejected=rejected)


def quiz_out(db: Session, quiz: Quiz) -> QuizOut:
    submitted = _has_attempt(db, quiz)
    questions = []
    if quiz.status == "ready" and quiz.started_at is not None:
        questions = [
            QuestionOut(
                id=q.id,
                position=q.position,
                stem=q.stem,
                options=q.options,
                bloom_level=q.bloom_level,
                flagged_general=q.flagged_general,
                fact_idxs=sorted(q.fact_idxs) if submitted else None,
            )
            for q in _questions(db, quiz)
        ]
    return QuizOut(
        id=quiz.id,
        document_id=quiz.document_id,
        status=quiz.status,
        time_limit_sec=quiz.time_limit_sec,
        quiz_hash=quiz.quiz_hash if quiz.status == "ready" else None,
        commit_tx=quiz.commit_tx,
        explorer_url=explorer_url(quiz.commit_tx),
        chain_status=_chain_status(quiz),
        started_at=quiz.started_at,
        submitted=submitted,
        questions=questions,
        generation=None if quiz.status == "generating" else _generation(db, quiz),
    )


def _own_quiz(quiz_id: uuid.UUID, db: Session, user: User) -> Quiz:
    quiz = db.get(Quiz, quiz_id)
    if quiz is None or quiz.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    return quiz


@router.post("", response_model=QuizOut)
def create_quiz(
    body: QuizCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> QuizOut:
    document = db.get(Document, body.document_id)
    if document is None or document.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    if document.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "Document is not ready")
    quiz = Quiz(user_id=user.id, document_id=document.id, time_limit_sec=body.time_limit_sec)
    db.add(quiz)
    db.commit()
    session_factory = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    background_tasks.add_task(run_quiz_job, quiz.id, body.num_questions, session_factory)
    return quiz_out(db, quiz)


@router.get("/{quiz_id}", response_model=QuizOut)
def get_quiz(quiz_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> QuizOut:
    return quiz_out(db, _own_quiz(quiz_id, db, user))


@router.get("/{quiz_id}/progress", response_model=QuizProgressOut)
def get_quiz_progress(
    quiz_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> QuizProgressOut:
    quiz = _own_quiz(quiz_id, db, user)
    p = get_progress(quiz.id)
    if quiz.status == "generating":
        if p is None:
            return QuizProgressOut(accepted=0, rejected=0, target=0, stage="selecting")
        return QuizProgressOut(accepted=p.accepted, rejected=p.rejected, target=p.target, stage=p.stage)
    g = _generation(db, quiz)
    return QuizProgressOut(
        accepted=g.accepted,
        rejected=g.rejected,
        target=p.target if p else g.accepted,
        stage="done" if quiz.status == "ready" else "failed",
    )


@router.post("/{quiz_id}/start", response_model=QuizOut)
def start_quiz(quiz_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> QuizOut:
    quiz = _own_quiz(quiz_id, db, user)
    if quiz.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "Quiz is not ready")
    # Set once, atomically: a second start (or a refresh) keeps the original time.
    db.execute(
        update(Quiz).where(Quiz.id == quiz.id, Quiz.started_at.is_(None)).values(started_at=datetime.now(timezone.utc))
    )
    db.commit()
    db.refresh(quiz)
    return quiz_out(db, quiz)


@router.post("/{quiz_id}/attempts", response_model=AttemptResult)
def submit_attempt(
    quiz_id: uuid.UUID, body: AttemptIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> AttemptResult:
    quiz = _own_quiz(quiz_id, db, user)
    # Row lock: two simultaneous submits cannot both pass the one-attempt check.
    quiz = db.scalar(select(Quiz).where(Quiz.id == quiz.id).with_for_update().execution_options(populate_existing=True))
    if quiz.status != "ready" or quiz.started_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Quiz is not started")
    if quiz.commit_tx is None and not get_settings().chain_optional:
        raise HTTPException(status.HTTP_409_CONFLICT, "Quiz hash is not committed on chain, so it cannot be attempted")
    elapsed = (datetime.now(timezone.utc) - quiz.started_at).total_seconds()
    if elapsed > quiz.time_limit_sec + TIME_GRACE_SEC:
        raise HTTPException(status.HTTP_409_CONFLICT, "Time limit exceeded")
    if _has_attempt(db, quiz):
        raise HTTPException(status.HTTP_409_CONFLICT, "Quiz already submitted")

    questions = _questions(db, quiz)
    if len(body.answers) != len(questions):
        raise HTTPException(422, f"Expected {len(questions)} answers")
    if any(a is not None and not 0 <= a <= 3 for a in body.answers):
        raise HTTPException(422, "Each answer is 0-3 or null")

    cited = sorted({i for q in questions for i in q.fact_idxs})
    facts = {
        f.idx: f
        for f in db.scalars(select(Fact).where(Fact.document_id == quiz.document_id, Fact.idx.in_(cited)))
    }
    headings = {
        s.id: s.heading
        for s in db.scalars(select(Section).where(Section.id.in_({f.section_id for f in facts.values()})))
    }

    results, score = [], 0
    weak: dict[str, list[int]] = {}
    now = datetime.now(timezone.utc)
    for q, chosen in zip(questions, body.answers):
        correct = chosen == q.answer_index
        score += correct
        results.append(
            ResultOut(
                question_id=q.id,
                chosen=chosen,
                correct_index=q.answer_index,
                correct=correct,
                sources=[
                    SourceOut(idx=i, text=facts[i].text, page=facts[i].page, section=headings[facts[i].section_id])
                    for i in sorted(q.fact_idxs)
                ],
            )
        )
        target = facts[q.target_fact_idx]
        if not correct:
            weak.setdefault(target.concept, []).append(target.idx)
        # Coverage tracks the target fact only, never the context facts.
        stmt = insert(FactCoverage).values(
            user_id=user.id, fact_id=target.id, times_tested=1, last_correct=correct, last_bloom=q.bloom_level, updated_at=now
        )
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=[FactCoverage.user_id, FactCoverage.fact_id],
                set_={
                    "times_tested": FactCoverage.times_tested + 1,
                    "last_correct": correct,
                    "last_bloom": q.bloom_level,
                    "updated_at": now,
                },
            )
        )

    attempt = Attempt(
        quiz_id=quiz.id,
        user_id=user.id,
        answers=list(body.answers),
        score=score,
        total=len(questions),
        time_taken_sec=min(body.time_taken_sec, quiz.time_limit_sec + TIME_GRACE_SEC),
    )
    db.add(attempt)
    db.commit()
    weak_concepts = sorted(
        (WeakConceptOut(concept=c, wrong=len(idxs), facts=sorted(idxs)) for c, idxs in weak.items()),
        key=lambda w: (-w.wrong, w.concept),
    )
    return AttemptResult(attempt_id=attempt.id, score=score, total=len(questions), results=results, weak_concepts=weak_concepts)
