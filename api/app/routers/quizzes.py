"""Quizzes (SPEC section 2, short answers 9.7). answer_index, target_fact_idx and model_answer never leave the server through QuizOut;
fact_idxs only after the attempt is submitted (CLAUDE.md rule 7)."""
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictInt, StrictStr, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.auth import get_current_user
from app.chain.service import explorer_url
from app.config import get_settings
from app.db import get_db
from app.credentials import results as attempt_results
from app.learn.grading import on_final_grade
from app.learn.review import review_summary
from app.learn.shortgrade import HOOK_GRADE, MAX_ANSWER_CHARS, grade_attempt_shorts, score_attempt
from app.models import AnswerGrade, Attempt, Document, Fact, GenerationLog, Question, Quiz, Section, User
from app.quiz.job import get_progress, run_quiz_job

router = APIRouter(prefix="/quizzes", tags=["quizzes"])

TIME_GRACE_SEC = 30


class QuizCreate(BaseModel):
    document_id: uuid.UUID
    num_questions: int = Field(10, ge=1, le=20)
    time_limit_sec: int = Field(600, ge=60, le=7200)
    mode: Literal["practice", "review"] = "practice"  # SPEC 9.6
    num_short: int = Field(0, ge=0, le=3)  # SPEC 9.7: short-answer questions among num_questions

    @model_validator(mode="after")
    def _short_fits(self):
        if self.num_short > self.num_questions:
            raise ValueError("num_short cannot exceed num_questions")
        return self


class QuestionOut(BaseModel):
    id: uuid.UUID
    position: int
    qtype: str  # mcq / short (short: options [])
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
    mode: str
    time_limit_sec: int
    quiz_hash: str | None
    commit_tx: str | None
    explorer_url: str | None
    chain_status: str
    started_at: datetime | None
    submitted: bool
    attempt_id: uuid.UUID | None
    questions: list[QuestionOut]
    generation: GenerationOut | None


class QuizProgressOut(BaseModel):
    accepted: int
    rejected: int
    target: int
    stage: str


class AttemptIn(BaseModel):
    answers: list[StrictInt | StrictStr | None]  # strict: true is not 1, "1" is not 1; int|null for an MCQ, string|null (≤ 500 chars) for a short answer
    time_taken_sec: int = Field(ge=0)


class SourceOut(BaseModel):
    idx: int
    text: str
    page: int
    section: str


class MisconceptionOut(BaseModel):
    option: int
    misconception: str
    sources: list[SourceOut]


class GradeOut(BaseModel):
    """SPEC 9.7. verdict and by are null while the grade waits for an educator."""

    verdict: str | None
    confidence: int | None
    reason: str
    deferred: bool
    by: Literal["checker", "educator"] | None
    fact_idxs: list[int]


class ResultOut(BaseModel):
    question_id: uuid.UUID
    qtype: str = "mcq"
    chosen: int | None
    correct_index: int | None  # null for a short answer
    correct: bool  # a short answer: true only once its final verdict is correct
    sources: list[SourceOut]
    misconceptions: list[MisconceptionOut]  # SPEC 9.2: after submit only; [] for Review 1 questions and short answers
    answer_text: str | None = None
    model_answer: str | None = None
    grade: GradeOut | None = None


class WeakConceptOut(BaseModel):
    concept: str
    wrong: int
    facts: list[int]


class AttemptResult(BaseModel):
    attempt_id: uuid.UUID
    score: int
    total: int
    grading_status: str  # final / pending_review
    pending_review: int  # short answers waiting for an educator
    results: list[ResultOut]
    weak_concepts: list[WeakConceptOut]


def _chain_status(quiz: Quiz) -> str:
    if quiz.status == "generating":
        return "pending"
    return "confirmed" if quiz.commit_tx else "offline"


def _questions(db: Session, quiz: Quiz) -> list[Question]:
    return db.scalars(select(Question).where(Question.quiz_id == quiz.id).order_by(Question.position)).all()


def _attempt_id(db: Session, quiz: Quiz) -> uuid.UUID | None:
    return db.scalar(select(Attempt.id).where(Attempt.quiz_id == quiz.id).limit(1))


def _has_attempt(db: Session, quiz: Quiz) -> bool:
    return _attempt_id(db, quiz) is not None


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
    attempt_id = _attempt_id(db, quiz)
    submitted = attempt_id is not None
    questions = []
    if quiz.status == "ready" and quiz.started_at is not None:
        questions = [
            QuestionOut(
                id=q.id,
                position=q.position,
                qtype=q.qtype,
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
        mode=quiz.mode,
        time_limit_sec=quiz.time_limit_sec,
        quiz_hash=quiz.quiz_hash if quiz.status == "ready" else None,
        commit_tx=quiz.commit_tx,
        explorer_url=explorer_url(quiz.commit_tx),
        chain_status=_chain_status(quiz),
        started_at=quiz.started_at,
        submitted=submitted,
        attempt_id=attempt_id,
        questions=questions,
        generation=None if quiz.status == "generating" else _generation(db, quiz),
    )


def _quiz_facts(db: Session, quiz: Quiz, questions: list[Question]) -> dict[int, Fact]:
    """Every cited, target and distractor fact of the quiz, by idx."""
    cited = sorted(
        {i for q in questions for i in q.fact_idxs}
        | {q.target_fact_idx for q in questions}
        | {i for q in questions for d in q.distractors for i in d["fact_idxs"]}
    )
    return {
        f.idx: f
        for f in db.scalars(select(Fact).where(Fact.document_id == quiz.document_id, Fact.idx.in_(cited)))
    }


def _grade_out(g: AnswerGrade) -> GradeOut:
    pending = g.final_verdict is None
    return GradeOut(
        verdict=g.final_verdict,
        confidence=g.confidence,
        reason=g.reason or "",
        deferred=g.deferred,
        by=None if pending else "educator" if g.educator_verdict else "checker",
        fact_idxs=sorted(g.fact_idxs or []),
    )


def _build_result(
    db: Session,
    facts: dict[int, Fact],
    questions: list[Question],
    answers: list,
    attempt_id: uuid.UUID,
    grades: dict[uuid.UUID, AnswerGrade],
) -> AttemptResult:
    """Scores answers against the stored key (MCQ) and the stored grades (short answers). Shared by submit and
    GET /attempts/{id}, so both return the same shape."""
    headings = {
        s.id: s.heading
        for s in db.scalars(select(Section).where(Section.id.in_({f.section_id for f in facts.values()})))
    }
    def sources(idxs) -> list[SourceOut]:
        return [
            SourceOut(idx=i, text=facts[i].text, page=facts[i].page, section=headings[facts[i].section_id])
            for i in sorted(idxs)
        ]

    results = []
    weak: dict[str, list[int]] = {}
    for q, chosen in zip(questions, answers):
        if q.qtype == "short":
            g = grades[q.id]
            verdict = g.final_verdict
            correct, wrong = verdict == "correct", verdict in ("partial", "incorrect")  # pending is neither
            results.append(
                ResultOut(
                    question_id=q.id, qtype="short", chosen=None, correct_index=None, correct=correct,
                    sources=sources(q.fact_idxs), misconceptions=[], answer_text=g.answer_text,
                    model_answer=q.model_answer, grade=_grade_out(g),
                )
            )
        else:
            correct = chosen == q.answer_index
            wrong = not correct
            results.append(
                ResultOut(
                    question_id=q.id,
                    chosen=chosen,
                    correct_index=q.answer_index,
                    correct=correct,
                    sources=sources(q.fact_idxs),
                    misconceptions=[
                        MisconceptionOut(option=d["option"], misconception=d["misconception"], sources=sources(d["fact_idxs"]))
                        for d in q.distractors
                    ],
                )
            )
        if wrong:
            target = facts[q.target_fact_idx]
            weak.setdefault(target.concept, []).append(target.idx)
    weak_concepts = sorted(
        (WeakConceptOut(concept=c, wrong=len(idxs), facts=sorted(idxs)) for c, idxs in weak.items()),
        key=lambda w: (-w.wrong, w.concept),
    )
    score, pending = score_attempt(questions, answers, grades)
    return AttemptResult(
        attempt_id=attempt_id,
        score=score,
        total=len(questions),
        grading_status="pending_review" if pending else "final",
        pending_review=pending,
        results=results,
        weak_concepts=weak_concepts,
    )


def _grades(db: Session, attempt_id: uuid.UUID) -> dict[uuid.UUID, AnswerGrade]:
    return {g.question_id: g for g in db.scalars(select(AnswerGrade).where(AnswerGrade.attempt_id == attempt_id))}


def attempt_result(db: Session, attempt: Attempt) -> AttemptResult:
    quiz = db.get(Quiz, attempt.quiz_id)
    questions = _questions(db, quiz)
    return _build_result(db, _quiz_facts(db, quiz, questions), questions, attempt.answers, attempt.id, _grades(db, attempt.id))


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
    if body.mode == "review":
        summary = review_summary(db, user.id, document.id, datetime.now(timezone.utc))
        if summary.due_now == 0:  # SPEC 9.6: no quiz row, no LLM call
            next_due = summary.next_due.isoformat() if summary.next_due else None
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT, content={"detail": "Nothing due for review", "next_due": next_due}
            )
    quiz = Quiz(user_id=user.id, document_id=document.id, time_limit_sec=body.time_limit_sec, mode=body.mode)
    db.add(quiz)
    db.commit()
    session_factory = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    background_tasks.add_task(run_quiz_job, quiz.id, body.num_questions, session_factory, body.num_short)
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
    for q, a in zip(questions, body.answers):  # validated per position (SPEC 9.7)
        if q.qtype == "short":
            if a is not None and (not isinstance(a, str) or len(a) > MAX_ANSWER_CHARS):
                raise HTTPException(422, f"Answer {q.position} is a short answer: a string of at most {MAX_ANSWER_CHARS} characters, or null")
        elif a is not None and (not isinstance(a, int) or isinstance(a, bool) or not 0 <= a <= 3):
            raise HTTPException(422, f"Answer {q.position} is multiple choice: 0-3 or null")

    attempt_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    facts = _quiz_facts(db, quiz, questions)
    # One batched checker call for every short answer; deferred grades wait for an educator.
    grades = grade_attempt_shorts(db, quiz, questions, body.answers, facts, attempt_id, now)
    results = _build_result(db, facts, questions, body.answers, attempt_id, grades)
    for q, r in zip(questions, results.results):
        # Only final grades update coverage, mastery and the FSRS card, in this transaction.
        if q.qtype == "short":
            verdict = grades[q.id].final_verdict
            if verdict is not None:
                on_final_grade(db, user.id, facts[q.target_fact_idx], q.bloom_level, HOOK_GRADE[verdict], now, qtype="short")
        else:
            on_final_grade(db, user.id, facts[q.target_fact_idx], q.bloom_level, "correct" if r.correct else "wrong", now)

    attempt = Attempt(
        id=attempt_id,
        quiz_id=quiz.id,
        user_id=user.id,
        answers=list(body.answers),
        score=results.score,
        total=len(questions),
        time_taken_sec=min(body.time_taken_sec, quiz.time_limit_sec + TIME_GRACE_SEC),
        grading_status=results.grading_status,
    )
    db.add(attempt)
    db.flush()  # the grades reference the attempt
    db.add_all(grades.values())
    db.flush()
    attempt_results.ensure_attempt_hash(db, attempt)  # SPEC 9.9; none while a short answer waits for an educator
    db.commit()
    return results
