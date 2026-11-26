"""GET /attempts/{attempt_id} (SPEC 9.1): reload a submitted result after a refresh. Owner only."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import Attempt, User
from app.routers.quizzes import AttemptResult, attempt_result

router = APIRouter(prefix="/attempts", tags=["attempts"])


@router.get("/{attempt_id}", response_model=AttemptResult)
def get_attempt(attempt_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> AttemptResult:
    attempt = db.get(Attempt, attempt_id)
    # The same 404 for another user's attempt, so its existence is not revealed.
    if attempt is None or attempt.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")
    return attempt_result(db, attempt)
