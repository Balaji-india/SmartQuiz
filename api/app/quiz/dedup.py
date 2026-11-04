"""Duplicate blocking for one user + document (SPEC sections 4 and 8): fingerprint first, then stem cosine."""
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

    def __init__(self, db: Session, user_id: uuid.UUID, document_id: uuid.UUID, exclude_quiz: uuid.UUID | None = None):
        query = (
            select(Question.fingerprint, Question.stem_embedding)
            .join(Quiz, Quiz.id == Question.quiz_id)
            .where(Quiz.user_id == user_id, Quiz.document_id == document_id, Quiz.status != "failed")
        )
        if exclude_quiz is not None:
            query = query.where(Quiz.id != exclude_quiz)
        rows = db.execute(query).all()
        self.fingerprints: set[str] = {r.fingerprint for r in rows}
        self.vectors: list[np.ndarray] = [np.asarray(r.stem_embedding, dtype=np.float32) for r in rows]

    def check(self, fp: str, vector: np.ndarray) -> tuple[str | None, str]:
        """(None, "") if new, else (gate, reason) with gate dup_fingerprint or dup_cosine."""
        if fp in self.fingerprints:
            return "dup_fingerprint", "same facts and bloom level as an earlier question"
        if self.vectors:
            best = float(np.max(np.stack(self.vectors) @ vector))
            if best >= COSINE_DUPLICATE:
                return "dup_cosine", f"stem cosine {best:.2f} with an earlier question"
        return None, ""

    def add(self, fp: str, vector: np.ndarray) -> None:
        self.fingerprints.add(fp)
        self.vectors.append(np.asarray(vector, dtype=np.float32))
