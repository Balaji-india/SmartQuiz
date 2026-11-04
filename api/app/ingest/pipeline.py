"""Textbook Mode (SPEC section 3). run_ingestion needs no database; ingest_document saves its result."""
import logging
import uuid
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import delete, update
from sqlalchemy.orm import Session, sessionmaker

from app.chain.service import get_chain
from app.config import get_settings
from app.db import SessionLocal
from app.ingest.extractor import PackedChunk, check_faithfulness, extract_facts, pack_chunks
from app.ingest.hasher import embed_texts, fact_root, hash_fact
from app.ingest.locator import locate
from app.ingest.parser import ParsedSection, parse_document
from app.llm.provider import same_family_checker
from app.models import Document, Fact, GenerationLog, Section

log = logging.getLogger(__name__)

DEDUP_COSINE = 0.95
GATE_FACT = "gate0_fact"


@dataclass
class KeptFact:
    section_position: int
    concept: str
    text: str
    quote: str
    page: int
    char_start: int
    char_end: int
    idx: int = -1
    text_hash: str = ""
    leaf_hash: str = ""
    embedding: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class FactCheck:
    passed: bool
    reason: str


@dataclass
class IngestResult:
    sections: list[ParsedSection]
    facts: list[KeptFact]
    checks: list[FactCheck]
    facts_dropped: int
    facts_unfaithful: int
    duplicates: int
    root: str | None


def _extract_chunk(
    chunk: PackedChunk, sections: list[ParsedSection]
) -> tuple[list[KeptFact], list[FactCheck], int, int]:
    raw_facts, dropped = extract_facts(chunk.text)
    located = []
    for raw in raw_facts:
        # Only this chunk: a sentence repeated elsewhere must not get the wrong page.
        span = locate(raw.quote, chunk.text)
        target = chunk.to_section(*span) if span else None
        if target is None:
            dropped += 1
        else:
            located.append((raw, *target))

    # The checker sees the source span, not the model's copy of it.
    pairs = [(sections[p].text[s:e], raw.fact) for raw, p, s, e in located]
    kept: list[KeptFact] = []
    checks: list[FactCheck] = []
    unfaithful = 0
    for (raw, position, s, e), verdict in zip(located, check_faithfulness(pairs)):
        checks.append(FactCheck(verdict.faithful, f"{raw.concept}: {verdict.reason}"))
        if not verdict.faithful:
            unfaithful += 1
            continue
        section = sections[position]
        kept.append(
            KeptFact(
                section_position=position,
                concept=raw.concept,
                text=raw.fact,
                quote=section.text[s:e],
                page=section.page_at(s),
                char_start=s,
                char_end=e,
            )
        )
    return kept, checks, dropped, unfaithful


def _dedupe(facts: list[KeptFact]) -> tuple[list[KeptFact], np.ndarray, int]:
    """The first fact in reading order wins."""
    if not facts:
        return [], np.empty((0, 0)), 0
    vectors = embed_texts([f.text for f in facts])
    keep: list[int] = []
    for i, vector in enumerate(vectors):
        if not keep or float(np.max(vectors[keep] @ vector)) < DEDUP_COSINE:
            keep.append(i)
    return [facts[i] for i in keep], vectors[keep], len(facts) - len(keep)


def run_ingestion(filename: str, data: bytes) -> IngestResult:
    sections = parse_document(filename, data)
    facts: list[KeptFact] = []
    checks: list[FactCheck] = []
    dropped = unfaithful = 0
    for chunk in pack_chunks(sections):
        chunk_facts, chunk_checks, chunk_dropped, chunk_unfaithful = _extract_chunk(chunk, sections)
        facts += chunk_facts
        checks += chunk_checks
        dropped += chunk_dropped
        unfaithful += chunk_unfaithful

    facts.sort(key=lambda f: (f.section_position, f.char_start, f.char_end))
    facts, vectors, duplicates = _dedupe(facts)
    for idx, (fact, vector) in enumerate(zip(facts, vectors)):
        fact.idx = idx
        fact.text_hash, fact.leaf_hash = hash_fact(idx, fact.text)
        fact.embedding = vector.tolist()
    root = fact_root([f.leaf_hash for f in facts]) if facts else None
    return IngestResult(sections, facts, checks, dropped, unfaithful, duplicates, root)


def register_document_onchain(document: Document) -> None:
    """SPEC section 3 step 7: puts the fact root on chain and saves register_tx. Raises ChainError."""
    if document.register_tx or not document.fact_root:
        return
    document.register_tx = get_chain().register_document(document.id, document.fact_root, document.fact_count)


def log_chain_failure(what: str, exc: Exception) -> None:
    # CHAIN_OPTIONAL=false is the demo setting, so a failure there is an error, not a warning.
    level = logging.WARNING if get_settings().chain_optional else logging.ERROR
    log.log(level, "%s: chain offline (%s)", what, exc)


def _clear_previous_run(db: Session, document: Document) -> None:
    db.execute(delete(Fact).where(Fact.document_id == document.id))
    db.execute(delete(Section).where(Section.document_id == document.id))
    db.execute(
        delete(GenerationLog).where(GenerationLog.document_id == document.id, GenerationLog.gate == GATE_FACT)
    )
    document.fact_root = None
    document.fact_count = document.sections_count = document.facts_dropped = document.facts_unfaithful = 0


def _save(db: Session, document: Document, result: IngestResult) -> None:
    section_ids: dict[int, int] = {}
    for parsed in result.sections:
        row = Section(
            document_id=document.id,
            parent_id=section_ids.get(parsed.parent_position),
            heading=parsed.heading,
            level=parsed.level,
            page_start=parsed.page_start,
            page_end=parsed.page_end,
            position=parsed.position,
        )
        db.add(row)
        db.flush()
        section_ids[parsed.position] = row.id

    db.add_all(
        Fact(
            document_id=document.id,
            section_id=section_ids[f.section_position],
            idx=f.idx,
            concept=f.concept,
            text=f.text,
            quote=f.quote,
            page=f.page,
            char_start=f.char_start,
            char_end=f.char_end,
            text_hash=f.text_hash,
            leaf_hash=f.leaf_hash,
            embedding=f.embedding,
        )
        for f in result.facts
    )
    same_family = same_family_checker()
    db.add_all(
        GenerationLog(
            document_id=document.id,
            gate=GATE_FACT,
            passed=c.passed,
            reason=c.reason,
            same_family_fallback=same_family,
        )
        for c in result.checks
    )
    document.fact_root = result.root
    document.fact_count = len(result.facts)
    document.sections_count = len(result.sections)
    document.facts_dropped = result.facts_dropped
    document.facts_unfaithful = result.facts_unfaithful


def ingest_document(document_id: uuid.UUID, filename: str, data: bytes, session_factory: sessionmaker = SessionLocal) -> None:
    """The background job: document.status moves ingesting -> ready or failed. Never raises."""
    with session_factory() as db:
        document = db.get(Document, document_id)
        if document is None:
            return
        try:
            result = run_ingestion(filename, data)
            _clear_previous_run(db, document)
            _save(db, document, result)
            db.commit()
        except Exception:
            db.rollback()
            log.exception("ingestion failed for document %s", document_id)
            _clear_previous_run(db, document)
            document.status = "failed"
            db.commit()
            return

        if not result.facts:
            document.status = "failed"
            db.commit()
            return

        try:
            register_document_onchain(document)
        except Exception as exc:
            # SPEC: a chain failure does not block. register_tx stays null, chain_status is offline.
            db.rollback()
            document.register_tx = None
            log_chain_failure(f"registration of document {document_id}", exc)
        document.status = "ready"
        db.commit()


def fail_interrupted_ingestions(session_factory: sessionmaker = SessionLocal) -> int:
    """Background jobs die with the server. Without this, the web page would poll them forever."""
    with session_factory() as db:
        count = db.execute(
            update(Document).where(Document.status == "ingesting").values(status="failed")
        ).rowcount
        db.commit()
    return count
