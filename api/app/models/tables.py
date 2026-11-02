"""Every table in docs/SPEC.md section 1. No feature logic here.

questions store facts.idx; fact_coverage stores facts.id. Convert through (document_id, idx).
"""
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 384


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # Unknown while status is "ingesting", so these start empty or at zero.
    fact_root: Mapped[str | None] = mapped_column(String(66))
    fact_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    sections_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    facts_dropped: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    register_tx: Mapped[str | None] = mapped_column(String(66))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ingesting", server_default="ingesting")
    created_at: Mapped[datetime] = _created_at()


class Section(Base):
    __tablename__ = "sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("sections.id"))
    heading: Mapped[str] = mapped_column(String, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class Fact(Base):
    __tablename__ = "facts"
    __table_args__ = (
        UniqueConstraint("document_id", "idx", name="uq_facts_document_id_idx"),
        Index(
            "ix_facts_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), nullable=False)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), nullable=False)
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    concept: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    leaf_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=False)


class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="generating", server_default="generating")
    quiz_hash: Mapped[str | None] = mapped_column(String(66))
    salt: Mapped[str | None] = mapped_column(String(66))
    commit_tx: Mapped[str | None] = mapped_column(String(66))
    time_limit_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    quiz_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quizzes.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list] = mapped_column(JSONB, nullable=False)
    answer_index: Mapped[int] = mapped_column(Integer, nullable=False)
    fact_idxs: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    target_fact_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    bloom_level: Mapped[str] = mapped_column(String(16), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String, nullable=False, index=True)
    gate_results: Mapped[dict] = mapped_column(JSONB, nullable=False)
    dependence_score: Mapped[float] = mapped_column(Float, nullable=False)
    flagged_general: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    stem_embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=False)


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    quiz_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quizzes.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    answers: Mapped[list] = mapped_column(JSONB, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    time_taken_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class FactCoverage(Base):
    __tablename__ = "fact_coverage"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    fact_id: Mapped[int] = mapped_column(ForeignKey("facts.id"), primary_key=True)
    times_tested: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    last_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    last_bloom: Mapped[str] = mapped_column(String(16), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class GenerationLog(Base):
    __tablename__ = "generation_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), nullable=False)
    quiz_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("quizzes.id"))
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    gate: Mapped[str] = mapped_column(String(32), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    same_family_fallback: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = _created_at()
