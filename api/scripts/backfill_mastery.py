"""Rebuild the mastery table (SPEC 9.4) by replaying every submitted attempt in order. Idempotent: each
(user, document) with attempts has its mastery rows deleted and recomputed in one transaction. Coverage is not touched.

Usage: cd api && PYTHONUTF8=1 .venv/bin/python scripts/backfill_mastery.py
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.learn.mastery import update_mastery  # noqa: E402
from app.models import Attempt, Fact, Mastery, Question, Quiz  # noqa: E402

WEAKEST = 5


def backfill(db: Session) -> dict:
    """Replays all attempts; returns {"attempts", "answers", "pairs"}. The caller commits."""
    attempts = db.execute(
        select(Attempt, Quiz.document_id).join(Quiz, Quiz.id == Attempt.quiz_id).order_by(Attempt.created_at, Attempt.id)
    ).all()
    pairs = {(a.user_id, doc) for a, doc in attempts}
    for user_id, doc in pairs:
        db.execute(delete(Mastery).where(Mastery.user_id == user_id, Mastery.document_id == doc))

    answers = 0
    for attempt, doc in attempts:
        questions = db.scalars(select(Question).where(Question.quiz_id == attempt.quiz_id).order_by(Question.position)).all()
        concepts = dict(
            db.execute(
                select(Fact.idx, Fact.concept).where(
                    Fact.document_id == doc, Fact.idx.in_([q.target_fact_idx for q in questions])
                )
            ).all()
        )
        when = attempt.created_at or datetime.now(timezone.utc)
        for q, chosen in zip(questions, attempt.answers):
            grade = "correct" if chosen == q.answer_index else "wrong"
            update_mastery(db, attempt.user_id, doc, concepts[q.target_fact_idx], grade, "mcq", when)
            answers += 1
    db.flush()
    return {"attempts": len(attempts), "answers": answers, "pairs": len(pairs)}


def main() -> int:
    from app.db import SessionLocal
    from app.routers.learn import mastery_report

    with SessionLocal() as db:
        stats = backfill(db)
        db.commit()
        print(f"replayed {stats['attempts']} attempts, {stats['answers']} answers, {stats['pairs']} user+document pairs")
        pairs = db.execute(select(Mastery.user_id, Mastery.document_id).distinct()).all()
        total = {"weak": 0, "learning": 0, "untested": 0, "mastered": 0}
        weakest = []
        for user_id, doc in pairs:
            report = mastery_report(db, user_id, doc)
            for k, v in report.summary.model_dump().items():
                total[k] += v
            weakest += [c for c in report.concepts if c.answered]
        print("summary (all pairs):", total)
        print(f"{WEAKEST} weakest concepts:")
        for c in sorted(weakest, key=lambda c: (c.p_mastery, -c.answered))[:WEAKEST]:
            print(f"  {c.p_mastery:.3f}  {c.status:<8} answered {c.answered}  {c.concept!r}  [{c.section}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
