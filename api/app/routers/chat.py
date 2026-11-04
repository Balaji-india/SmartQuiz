import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.chat.answer import MAX_MESSAGE_CHARS, answer_question
from app.db import get_db
from app.models import Document, User

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatIn(BaseModel):
    document_id: uuid.UUID
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class CitationOut(BaseModel):
    idx: int
    text: str
    page: int


class SectionRef(BaseModel):
    id: int
    heading: str


class ChatOut(BaseModel):
    abstained: bool
    answer: str
    citations: list[CitationOut]
    nearest_sections: list[SectionRef]
    best_similarity: float


@router.post("", response_model=ChatOut)
def chat(body: ChatIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> ChatOut:
    document = db.get(Document, body.document_id)
    if document is None or document.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    if document.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "Document is not ready")
    if not body.message.strip():
        raise HTTPException(422, "Message is empty")
    return ChatOut(**answer_question(db, document.id, body.message.strip()))
