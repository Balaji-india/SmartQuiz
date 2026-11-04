"""MetricsOut for one document (SPEC section 2).

gate0_fact rows are ingestion checks (candidate_id null): they are excluded from rejected_by_gate and
top_reasons, which describe questions, but counted in same_family_gate_calls, because they are checker calls.
"""
import uuid
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import GenerationLog, Question, Quiz

QUESTION_GATES = ("gate1", "gate3", "generator_error")
DUPLICATE_GATES = {"dup_fingerprint": "fingerprint", "dup_cosine": "cosine"}
TOP_REASONS = 5


def document_metrics(db: Session, document_id: uuid.UUID) -> dict:
    quiz_rows = db.execute(
        select(Quiz.id, Quiz.user_id).where(Quiz.document_id == document_id, Quiz.status != "failed")
    ).all()
    quiz_ids = [q.id for q in quiz_rows]

    logs = db.execute(
        select(GenerationLog.gate, GenerationLog.passed, GenerationLog.reason, GenerationLog.candidate_id, GenerationLog.same_family_fallback)
        .where(GenerationLog.document_id == document_id)
    ).all()
    question_logs = [r for r in logs if r.candidate_id is not None]
    candidates = len({r.candidate_id for r in question_logs})

    rejected_by_gate = Counter(r.gate for r in question_logs if not r.passed and r.gate in QUESTION_GATES)
    reasons = Counter((r.gate, r.reason or "") for r in question_logs if not r.passed and r.gate in QUESTION_GATES)
    duplicates = Counter(DUPLICATE_GATES[r.gate] for r in question_logs if r.gate in DUPLICATE_GATES)
    same_family_calls = sum(1 for r in logs if r.same_family_fallback)

    questions = db.execute(
        select(Question.quiz_id, Question.target_fact_idx, Question.dependence_score, Question.flagged_general).where(
            Question.quiz_id.in_(quiz_ids)
        )
    ).all() if quiz_ids else []

    # Share of target facts that were the target in more than one quiz of the same user.
    user_of = {q.id: q.user_id for q in quiz_rows}
    quizzes_per_target: dict[tuple, set] = {}
    for q in questions:
        quizzes_per_target.setdefault((user_of[q.quiz_id], q.target_fact_idx), set()).add(q.quiz_id)
    repeated = sum(1 for qs in quizzes_per_target.values() if len(qs) > 1)

    return {
        "document_id": document_id,
        "candidates": candidates,
        "accepted": len(questions),
        "rejected_by_gate": {g: rejected_by_gate.get(g, 0) for g in ("gate1", "gate3")}
        | ({"generator_error": rejected_by_gate["generator_error"]} if rejected_by_gate.get("generator_error") else {}),
        "top_reasons": [
            {"gate": gate, "reason": reason, "count": count} for (gate, reason), count in reasons.most_common(TOP_REASONS)
        ],
        "duplicates_blocked": {"fingerprint": duplicates.get("fingerprint", 0), "cosine": duplicates.get("cosine", 0)},
        "flagged_general": sum(1 for q in questions if q.flagged_general),
        "avg_dependence": round(sum(q.dependence_score for q in questions) / len(questions), 2) if questions else None,
        "repeat_rate_between_quizzes": round(repeated / len(quizzes_per_target), 3) if quizzes_per_target else 0.0,
        "same_family_checker_used": same_family_calls > 0,
        "same_family_gate_calls": same_family_calls,
    }
