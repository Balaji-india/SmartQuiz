"""Rebuild the mastery table (SPEC 9.4) and the FSRS review cards (SPEC 9.6) by replaying every submitted attempt
in order, each at its attempt's created_at. Idempotent: each (user, document) with attempts has its mastery rows and
review cards deleted and recomputed in one transaction. Coverage is not touched.
Short answers (SPEC 9.7) replay their final verdict from answer_grades; one still waiting for an educator is skipped.

Usage: cd api && PYTHONUTF8=1 .venv/bin/python scripts/backfill_mastery.py
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.learn.mastery import update_mastery  # noqa: E402
from app.learn.review import review_summary, update_card  # noqa: E402
from app.learn.shortgrade import HOOK_GRADE  # noqa: E402
from app.models import AnswerGrade, Attempt, Fact, Mastery, Question, Quiz, ReviewCard  # noqa: E402

WEAKEST = 5


def backfill(db: Session) -> dict:
    """Replays all attempts; returns {"attempts", "answers", "pairs", "cards"}. The caller commits."""
    attempts = db.execute(
        select(Attempt, Quiz.document_id).join(Quiz, Quiz.id == Attempt.quiz_id).order_by(Attempt.created_at, Attempt.id)
    ).all()
    pairs = {(a.user_id, doc) for a, doc in attempts}
    for user_id, doc in pairs:
        db.execute(delete(Mastery).where(Mastery.user_id == user_id, Mastery.document_id == doc))
        db.execute(
            delete(ReviewCard).where(
                ReviewCard.user_id == user_id, ReviewCard.fact_id.in_(select(Fact.id).where(Fact.document_id == doc))
            )
        )

    answers = 0
    for attempt, doc in attempts:
        questions = db.scalars(select(Question).where(Question.quiz_id == attempt.quiz_id).order_by(Question.position)).all()
        facts = {
            f.idx: f
            for f in db.scalars(
                select(Fact).where(Fact.document_id == doc, Fact.idx.in_([q.target_fact_idx for q in questions]))
            )
        }
        grades = {g.question_id: g for g in db.scalars(select(AnswerGrade).where(AnswerGrade.attempt_id == attempt.id))}
        when = attempt.created_at or datetime.now(timezone.utc)
        for q, chosen in zip(questions, attempt.answers):
            if q.qtype == "short":
                verdict = grades[q.id].final_verdict if q.id in grades else None
                if verdict is None:
                    continue  # pending educator review: not a final grade yet
                grade = HOOK_GRADE[verdict]
            else:
                grade = "correct" if chosen == q.answer_index else "wrong"
            target = facts[q.target_fact_idx]
            update_mastery(db, attempt.user_id, doc, target.concept, grade, q.qtype, when)
            update_card(db, attempt.user_id, target, grade, when)
            answers += 1
    db.flush()
    cards = sum(review_summary(db, u, d, datetime.now(timezone.utc)).cards for u, d in pairs)
    return {"attempts": len(attempts), "answers": answers, "pairs": len(pairs), "cards": cards}


def main() -> int:
    from app.db import SessionLocal
    from app.routers.learn import mastery_report

    with SessionLocal() as db:
        stats = backfill(db)
        db.commit()
        print(f"replayed {stats['attempts']} attempts, {stats['answers']} answers, {stats['pairs']} user+document pairs")
        now = datetime.now(timezone.utc)
        due = [review_summary(db, u, d, now) for u, d in db.execute(
            select(Attempt.user_id, Quiz.document_id).join(Quiz, Quiz.id == Attempt.quiz_id).distinct()
        ).all()]
        upcoming = [s.next_due for s in due if s.next_due]
        print(f"review cards: {stats['cards']}, due now {sum(s.due_now for s in due)}, "
              f"next due {min(upcoming).isoformat() if upcoming else None}")
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
