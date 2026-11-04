"""Fact retrieval for chat: cosine over facts.embedding (pgvector HNSW), same document only."""
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingest.hasher import embed_texts
from app.models import Fact, Section

TOP_K = 8
NEAREST_SECTIONS = 2
SECTION_SEARCH_K = 40  # wider search, so two distinct section headings are found


@dataclass(frozen=True)
class Hit:
    fact: Fact
    similarity: float


def retrieve(db: Session, document_id: uuid.UUID, message: str, k: int = TOP_K) -> list[Hit]:
    vector = embed_texts([message])[0].tolist()
    distance = Fact.embedding.cosine_distance(vector)
    rows = db.execute(
        select(Fact, distance.label("distance")).where(Fact.document_id == document_id).order_by(distance).limit(k)
    ).all()
    return [Hit(fact, 1.0 - float(d)) for fact, d in rows]


def nearest_sections(db: Session, document_id: uuid.UUID, message: str) -> list[dict]:
    """The sections of the closest facts, nearest first, distinct."""
    seen: list[int] = []
    for hit in retrieve(db, document_id, message, SECTION_SEARCH_K):
        if hit.fact.section_id not in seen:
            seen.append(hit.fact.section_id)
        if len(seen) == NEAREST_SECTIONS:
            break
    headings = {s.id: s.heading for s in db.scalars(select(Section).where(Section.id.in_(seen)))}
    return [{"id": sid, "heading": headings[sid]} for sid in seen]
