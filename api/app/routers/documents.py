import hashlib
import uuid
from datetime import datetime
from pathlib import PurePosixPath

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.auth import get_current_user
from app.db import get_db
from app.ingest.pipeline import ingest_document
from app.models import Document, Fact, Section, User

router = APIRouter(prefix="/documents", tags=["documents"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_SUFFIXES = {".pdf", ".txt"}
EXPLORER_TX = "https://amoy.polygonscan.com/tx/"


class DocumentOut(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    sections_count: int
    fact_count: int
    facts_dropped: int
    facts_unfaithful: int
    fact_root: str | None
    register_tx: str | None
    explorer_url: str | None
    chain_status: str
    created_at: datetime


class FactOut(BaseModel):
    idx: int
    text: str
    page: int
    concept: str


class SectionOut(BaseModel):
    id: int
    heading: str
    level: int
    page_start: int
    page_end: int
    facts: list[FactOut]
    children: list["SectionOut"]


class TextbookOut(BaseModel):
    document: DocumentOut
    sections: list[SectionOut]


def _chain_status(document: Document) -> str:
    if document.status == "ingesting":
        return "pending"
    return "confirmed" if document.register_tx else "offline"


def _document_out(document: Document) -> DocumentOut:
    return DocumentOut(
        id=document.id,
        filename=document.filename,
        status=document.status,
        sections_count=document.sections_count,
        fact_count=document.fact_count,
        facts_dropped=document.facts_dropped,
        facts_unfaithful=document.facts_unfaithful,
        fact_root=document.fact_root,
        register_tx=document.register_tx,
        explorer_url=f"{EXPLORER_TX}{document.register_tx}" if document.register_tx else None,
        chain_status=_chain_status(document),
        created_at=document.created_at,
    )


def _own_document(document_id: uuid.UUID, db: Session, user: User) -> Document:
    document = db.get(Document, document_id)
    # The same 404 for another user's document, so its existence is not revealed.
    if document is None or document.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return document


def _find_existing(db: Session, user: User, file_sha256: str) -> Document | None:
    return db.scalar(select(Document).where(Document.user_id == user.id, Document.file_sha256 == file_sha256))


@router.post("", response_model=DocumentOut)
def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentOut:
    filename = PurePosixPath((file.filename or "").replace("\\", "/")).name
    if PurePosixPath(filename).suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only .pdf and .txt files are supported")

    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413,"File is larger than 25 MB")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File is empty")
    if filename.lower().endswith(".txt"):
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Text files must be UTF-8") from None

    file_sha256 = hashlib.sha256(data).hexdigest()
    # The background job gets its own session on the same database as this request.
    session_factory = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)

    document = _find_existing(db, user, file_sha256)
    if document is None:
        document = Document(user_id=user.id, filename=filename, file_sha256=file_sha256)
        db.add(document)
        try:
            db.commit()
        except IntegrityError:
            # The same file uploaded twice at once: the other request won.
            db.rollback()
            return _document_out(_find_existing(db, user, file_sha256))
    elif document.status == "failed":
        # Only one of several simultaneous retries gets to restart it.
        restarted = db.execute(
            update(Document).where(Document.id == document.id, Document.status == "failed").values(status="ingesting")
        ).rowcount
        db.commit()
        db.refresh(document)
        if not restarted:
            return _document_out(document)
    else:
        return _document_out(document)

    background_tasks.add_task(ingest_document, document.id, filename, data, session_factory)
    return _document_out(document)


@router.get("", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[DocumentOut]:
    documents = db.scalars(
        select(Document).where(Document.user_id == user.id).order_by(Document.created_at.desc())
    ).all()
    return [_document_out(d) for d in documents]


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> DocumentOut:
    return _document_out(_own_document(document_id, db, user))


@router.get("/{document_id}/textbook", response_model=TextbookOut)
def get_textbook(
    document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> TextbookOut:
    document = _own_document(document_id, db, user)
    sections = db.scalars(select(Section).where(Section.document_id == document.id).order_by(Section.position)).all()
    facts = db.scalars(select(Fact).where(Fact.document_id == document.id).order_by(Fact.idx)).all()

    nodes = {
        s.id: SectionOut(
            id=s.id,
            heading=s.heading,
            level=s.level,
            page_start=s.page_start,
            page_end=s.page_end,
            facts=[],
            children=[],
        )
        for s in sections
    }
    for fact in facts:
        nodes[fact.section_id].facts.append(
            FactOut(idx=fact.idx, text=fact.text, page=fact.page, concept=fact.concept)
        )
    roots = []
    for section in sections:
        parent = nodes.get(section.parent_id)
        (parent.children if parent else roots).append(nodes[section.id])
    return TextbookOut(document=_document_out(document), sections=roots)
