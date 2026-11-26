"""The one "on final grade" hook (SPEC 9.4). Every graded answer goes through here, in the caller's transaction:
fact coverage (target fact only) and mastery now; FSRS cards (R05) and short-answer grades (R06) plug in here."""
import uuid
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.learn.mastery import update_mastery
from app.models import Fact, FactCoverage


def on_final_grade(
    db: Session,
    user_id: uuid.UUID,
    target: Fact,
    bloom_level: str,
    grade: str,
    now: datetime,
    qtype: str = "mcq",
) -> None:
    """grade: correct / partial / wrong. Coverage stores last_correct only for a full correct answer."""
    correct = grade == "correct"
    # Coverage tracks the target fact only, never the context facts.
    stmt = insert(FactCoverage).values(
        user_id=user_id, fact_id=target.id, times_tested=1, last_correct=correct, last_bloom=bloom_level, updated_at=now
    )
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=[FactCoverage.user_id, FactCoverage.fact_id],
            set_={
                "times_tested": FactCoverage.times_tested + 1,
                "last_correct": correct,
                "last_bloom": bloom_level,
                "updated_at": now,
            },
        )
    )
    update_mastery(db, user_id, target.document_id, target.concept, grade, qtype, now)
