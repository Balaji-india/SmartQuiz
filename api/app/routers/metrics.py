import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import Document, User
from app.quiz.metrics import document_metrics

router = APIRouter(prefix="/metrics", tags=["metrics"])


class ReasonOut(BaseModel):
    gate: str
    reason: str
    count: int


class MetricsOut(BaseModel):
    document_id: uuid.UUID
    candidates: int
    accepted: int
    rejected_by_gate: dict[str, int]
    top_reasons: list[ReasonOut]
    duplicates_blocked: dict[str, int]
    flagged_general: int
    avg_dependence: float | None
    repeat_rate_between_quizzes: float
    same_family_checker_used: bool
    same_family_gate_calls: int


@router.get("/{document_id}", response_model=MetricsOut)
def get_metrics(document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> MetricsOut:
    document = db.get(Document, document_id)
    if document is None or document.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return MetricsOut(**document_metrics(db, document_id))
