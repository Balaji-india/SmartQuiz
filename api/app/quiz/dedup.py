"""Duplicate blocking for one user + document (SPEC sections 4 and 8): fingerprint first, then stem cosine.

The cosine check skips earlier questions with the same target fact at a different Bloom level: those are the
planned retests (SPEC 9.3), they naturally ask about the same thing, and their fingerprint already differs.

Review mode (SPEC 9.6) uses within_quiz_only=True: fingerprints are checked only against the new quiz's own
questions, and the stem cosine check is skipped (repeats across reviews are expected).
"""
import hashlib
import uuid

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Question, Quiz

COSINE_DUPLICATE = 0.85


def fingerprint(fact_idxs: list[int], bloom_level: str) -> str:
    """sha256(utf-8("214,216|remember")), lowercase hex, no prefix."""
    key = ",".join(str(i) for i in sorted(set(fact_idxs))) + "|" + bloom_level
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class DuplicateChecker:
    """Holds earlier questions of this user + document (non-failed quizzes) plus those accepted so far."""

    def __init__(
        self,
        db: Session,
        user_id: uuid.UUID,
        document_id: uuid.UUID,
        exclude_quiz: uuid.UUID | None = None,
        within_quiz_only: bool = False,
    ):
        self.within_quiz_only = within_quiz_only
        query = (
            select(Question.fingerprint, Question.stem_embedding, Question.target_fact_idx, Question.bloom_level)
            .join(Quiz, Quiz.id == Question.quiz_id)
            .where(Quiz.user_id == user_id, Quiz.document_id == document_id, Quiz.status != "failed")
        )
        if exclude_quiz is not None:
            query = query.where(Quiz.id != exclude_quiz)
        rows = [] if within_quiz_only else db.execute(query).all()
        self.fingerprints: set[str] = {r.fingerprint for r in rows}
        self.vectors: list[np.ndarray] = [np.asarray(r.stem_embedding, dtype=np.float32) for r in rows]
        # (target_fact_idx, bloom_level) per vector, same order.
        self.keys: list[tuple[int | None, str | None]] = [(r.target_fact_idx, r.bloom_level) for r in rows]

    def check(
        self, fp: str, vector: np.ndarray, target_idx: int | None = None, bloom_level: str | None = None
    ) -> tuple[str | None, str]:
        """(None, "") if new, else (gate, reason) with gate dup_fingerprint or dup_cosine.
        With target_idx and bloom_level, earlier stems of that target at another level (retests) are not compared."""
        if fp in self.fingerprints:
            return "dup_fingerprint", "same facts and bloom level as an earlier question"
        if self.within_quiz_only:
            return None, ""
        compare = [
            v for v, (idx, level) in zip(self.vectors, self.keys)
            if target_idx is None or idx != target_idx or level == bloom_level
        ]
        if compare:
            best = float(np.max(np.stack(compare) @ vector))
            if best >= COSINE_DUPLICATE:
                return "dup_cosine", f"stem cosine {best:.2f} with an earlier question"
        return None, ""

    def add(self, fp: str, vector: np.ndarray, target_idx: int | None = None, bloom_level: str | None = None) -> None:
        self.fingerprints.add(fp)
        self.vectors.append(np.asarray(vector, dtype=np.float32))
        self.keys.append((target_idx, bloom_level))
