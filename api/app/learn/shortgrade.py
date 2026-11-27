"""Short-answer grading (SPEC 9.7). Checker only, from the question's cited facts only (CLAUDE.md rules 1 and 5).

On submit, ONE batched `grade_short` checker call grades every answered short question; ids still missing get one
more call (attempt = 1). A grade is deferred to an educator when:
- the checker's confidence is below 70,
- it gave no valid verdict after the retry (or the LLM failed or the daily limit was reached), or
- its fact_idxs are not a non-empty subset of the question's facts (a grade must cite the notes).
An empty answer is graded `incorrect` without an LLM call. Only final grades count in the score and fire the
"on final grade" hook; `apply_educator_grade` finalizes a deferred one (wired to an endpoint in R08).
"""
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.learn.grading import on_final_grade
from app.llm import provider
from app.models import AnswerGrade, Attempt, Fact, GenerationLog, Question, Quiz, User
from app.quiz.prompts import GRADE_SHORT_SYSTEM

log = logging.getLogger(__name__)

MAX_ANSWER_CHARS = 500
CONFIDENCE_MIN = 70
VERDICTS = ("correct", "partial", "incorrect")
HOOK_GRADE = {"correct": "correct", "partial": "partial", "incorrect": "wrong"}  # grading.py / mastery / FSRS names
MAX_REASON_CHARS = 300
NO_ANSWER = "No answer given"


@dataclass
class CheckerGrade:
    verdict: str | None
    confidence: int | None
    fact_idxs: list[int]
    reason: str
    deferred: bool


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _call(items: list[dict], attempt: int) -> dict[int, dict]:
    """id -> raw grade. A broken JSON reply counts as no grades; any other LLM error is re-raised."""
    try:
        reply = provider.generate_json("checker", GRADE_SHORT_SYSTEM, json.dumps({"items": items}, ensure_ascii=False), attempt=attempt)
    except provider.BadJSONError as exc:
        log.warning("grade_short attempt %d: %s; treating it as no grades", attempt, exc)
        return {}
    grades = reply.get("grades") if isinstance(reply, dict) else reply if isinstance(reply, list) else []
    wanted = {item["id"] for item in items}
    found: dict[int, dict] = {}
    for g in grades or []:
        if isinstance(g, dict) and _is_int(g.get("id")) and g["id"] in wanted and g["id"] not in found:
            found[g["id"]] = g
    return found


def _parse(raw: dict | None, allowed: set[int], llm_error: str | None) -> CheckerGrade:
    if raw is None:
        return CheckerGrade(None, None, [], llm_error or "checker returned no verdict", deferred=True)
    verdict = str(raw.get("verdict", "")).strip().lower()
    confidence = raw.get("confidence")
    if isinstance(confidence, float):
        confidence = round(confidence)
    confidence = min(max(confidence, 0), 100) if _is_int(confidence) else None
    idxs = raw.get("fact_idxs")
    idxs = sorted({i for i in idxs if _is_int(i)}) if isinstance(idxs, list) else []
    reason = str(raw.get("reason") or "")[:MAX_REASON_CHARS]
    if verdict not in VERDICTS:
        return CheckerGrade(None, confidence, [], f"unknown verdict {verdict!r}", deferred=True)
    if not idxs or not set(idxs) <= allowed:
        return CheckerGrade(verdict, confidence, [i for i in idxs if i in allowed], f"cited facts outside the question: {reason}", deferred=True)
    if confidence is None or confidence < CONFIDENCE_MIN:
        return CheckerGrade(verdict, confidence, idxs, reason, deferred=True)
    return CheckerGrade(verdict, confidence, idxs, reason, deferred=False)


def grade_short(items: list[dict], allowed: dict[int, set[int]]) -> dict[int, CheckerGrade]:
    """items: [{"id","facts":[{"idx","text"}],"stem","model_answer","answer"}]; allowed: id -> the question's fact idxs.
    One call, one retry for missing ids. An LLM failure (daily limit included) defers every item instead of failing."""
    if not items:
        return {}
    llm_error = None
    try:
        found = _call(items, 0)
        missing = [item for item in items if item["id"] not in found]
        if missing:
            found.update(_call(missing, 1))
    except provider.LLMError as exc:
        log.warning("grade_short failed, deferring %d answers to an educator: %s", len(items), exc)
        found, llm_error = {}, f"checker unavailable: {type(exc).__name__}"
    return {item["id"]: _parse(found.get(item["id"]), allowed[item["id"]], llm_error) for item in items}


def grade_attempt_shorts(
    db: Session,
    quiz: Quiz,
    questions: list[Question],
    answers: list,
    facts: dict[int, Fact],
    attempt_id: uuid.UUID,
    now: datetime,
) -> dict[uuid.UUID, AnswerGrade]:
    """Grades every short question of a submitted attempt; returns unsaved AnswerGrade rows by question id and logs
    one `grade_short` generation_log row per graded answer."""
    rows: dict[uuid.UUID, AnswerGrade] = {}
    items, allowed, by_id = [], {}, {}
    for q, answer in zip(questions, answers):
        if q.qtype != "short":
            continue
        text = " ".join(answer.split()) if isinstance(answer, str) else ""
        if not text:
            rows[q.id] = AnswerGrade(
                attempt_id=attempt_id, question_id=q.id, answer_text=None, verdict="incorrect", confidence=100,
                reason=NO_ANSWER, fact_idxs=[q.target_fact_idx], deferred=False, graded_at=now,
            )
            continue
        i = len(items)
        items.append(
            {
                "id": i,
                "facts": [{"idx": idx, "text": facts[idx].text} for idx in q.fact_idxs],
                "stem": q.stem,
                "model_answer": q.model_answer,
                "answer": text,
            }
        )
        allowed[i], by_id[i] = set(q.fact_idxs), (q, text)

    same_family = provider.same_family_checker()
    for i, g in grade_short(items, allowed).items():
        q, text = by_id[i]
        rows[q.id] = AnswerGrade(
            attempt_id=attempt_id, question_id=q.id, answer_text=text, verdict=g.verdict, confidence=g.confidence,
            reason=g.reason, fact_idxs=g.fact_idxs, deferred=g.deferred, graded_at=None if g.deferred else now,
        )
        status = "deferred" if g.deferred else "final"
        db.add(
            GenerationLog(
                document_id=quiz.document_id, quiz_id=quiz.id, candidate_id=None, gate="grade_short",
                passed=not g.deferred, reason=f"{status} {g.verdict} {g.confidence}: {g.reason}",
                same_family_fallback=same_family,
            )
        )
    return rows


def score_attempt(questions: list[Question], answers: list, grades: dict[uuid.UUID, AnswerGrade]) -> tuple[int, int]:
    """(score, pending): MCQ correct = 1; short correct = 1 once final; partial and incorrect = 0."""
    score = pending = 0
    for q, answer in zip(questions, answers):
        if q.qtype == "short":
            verdict = grades[q.id].final_verdict
            pending += verdict is None
            score += verdict == "correct"
        else:
            score += answer == q.answer_index
    return score, pending


def apply_educator_grade(db: Session, grade_id: uuid.UUID, verdict: str, educator: User) -> AnswerGrade:
    """Finalizes one deferred grade (R08 wires the endpoint and the educator role check). Runs the on-final-grade
    hook for it, rescores the attempt and marks it final once nothing is pending. The caller commits.
    Raises LookupError (no such grade) or ValueError (bad verdict, not deferred, or already graded)."""
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {', '.join(VERDICTS)}")
    grade = db.scalar(select(AnswerGrade).where(AnswerGrade.id == grade_id).with_for_update())
    if grade is None:
        raise LookupError("grade not found")
    if not grade.deferred:
        raise ValueError("this grade is final; only deferred grades go to an educator")
    if grade.educator_verdict is not None:
        raise ValueError("this grade was already graded by an educator")
    attempt = db.scalar(select(Attempt).where(Attempt.id == grade.attempt_id).with_for_update())
    quiz = db.get(Quiz, attempt.quiz_id)
    now = datetime.now(timezone.utc)
    grade.educator_id, grade.educator_verdict, grade.graded_at = educator.id, verdict, now

    question = db.get(Question, grade.question_id)
    target = db.scalar(select(Fact).where(Fact.document_id == quiz.document_id, Fact.idx == question.target_fact_idx))
    on_final_grade(db, attempt.user_id, target, question.bloom_level, HOOK_GRADE[verdict], now, qtype="short")

    questions = db.scalars(select(Question).where(Question.quiz_id == quiz.id).order_by(Question.position)).all()
    grades = {g.question_id: g for g in db.scalars(select(AnswerGrade).where(AnswerGrade.attempt_id == attempt.id))}
    attempt.score, pending = score_attempt(questions, attempt.answers, grades)
    attempt.grading_status = "pending_review" if pending else "final"
    db.flush()
    return grade
