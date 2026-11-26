"""Revision notes for weak concepts (SPEC 9.5). Closed book: every kept sentence cites facts of its own concept and
passed a statement form of Gate 1.

Requests per generation: 1 generator call (provider retries invalid JSON once) + 1 batched checker call
(ids without a verdict get one more call, then fail closed). Nothing else calls an LLM.
"""
import json
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.learn.mastery import concept_key
from app.llm import provider
from app.models import Fact, GenerationLog, RevisionNote
from app.quiz.gates import NO_VERDICT, _batch, _reason
from app.quiz.prompts import GATE_REVISION_SYSTEM, REVISION_NOTES_SYSTEM

GATE = "revision_gate1"
WEAKEST = 3
MAX_CONCEPTS = 5
MAX_SENTENCES = 6
MAX_SENTENCE_CHARS = 400


class NoWeakConcepts(Exception):
    """No weak or learning concept to revise (POST answers 409)."""


class UnknownConcepts(Exception):
    """Requested concepts that the document does not have (POST answers 422)."""


@dataclass
class _Draft:
    concept: str  # canonical spelling (lowest-idx fact)
    facts: dict[int, str]  # idx -> text, only this concept's facts
    note_id: uuid.UUID = field(default_factory=uuid.uuid4)
    sentences: list[dict] = field(default_factory=list)
    dropped: int = 0


def concept_facts(db: Session, document_id: uuid.UUID) -> dict[str, tuple[str, dict[int, str]]]:
    """concept key -> (canonical name, {idx: text}) in document order."""
    groups: dict[str, tuple[str, dict[int, str]]] = {}
    for f in db.scalars(select(Fact).where(Fact.document_id == document_id).order_by(Fact.idx)):
        groups.setdefault(concept_key(f.concept), (f.concept.strip(), {}))[1][f.idx] = f.text
    return groups


def pick_concepts(db: Session, user_id: uuid.UUID, document_id: uuid.UUID, requested: list[str] | None) -> list[str]:
    """Concept keys to revise. None = the WEAKEST weakest weak/learning concepts (gap report order)."""
    if requested is None:
        from app.routers.learn import mastery_report  # the report owns the SPEC 9.4 order

        report = mastery_report(db, user_id, document_id)
        keys = [concept_key(c.concept) for c in report.concepts if c.status in ("weak", "learning")][:WEAKEST]
        if not keys:
            raise NoWeakConcepts()
        return keys
    known = concept_facts(db, document_id)
    keys = list(dict.fromkeys(concept_key(c) for c in requested if c.strip()))
    unknown = [c for c in keys if c not in known]
    if unknown or not keys or len(keys) > MAX_CONCEPTS:
        raise UnknownConcepts(unknown)
    return keys


def _valid_idxs(value, allowed: dict[int, str]) -> list[int] | None:
    if not isinstance(value, list) or not value:
        return None
    if not all(isinstance(i, int) and not isinstance(i, bool) for i in value):
        return None
    idxs = sorted(set(value))
    return idxs if all(i in allowed for i in idxs) else None


def _collect(drafts: dict[str, _Draft], reply) -> list[tuple[_Draft, str, list[int]]]:
    """Valid sentences from the generator reply; every invalid or surplus sentence is counted as dropped."""
    notes = reply.get("notes") if isinstance(reply, dict) else None
    if not isinstance(notes, list):
        raise provider.LLMError("generator returned no notes")
    out, seen = [], set()
    for note in notes:
        if not isinstance(note, dict) or not isinstance(note.get("concept"), str):
            continue
        key = concept_key(note["concept"])
        if key not in drafts or key in seen:  # an unrequested or repeated concept is ignored
            continue
        seen.add(key)
        draft, kept = drafts[key], 0
        for s in note.get("sentences") if isinstance(note.get("sentences"), list) else []:
            text = s.get("text").strip() if isinstance(s, dict) and isinstance(s.get("text"), str) else ""
            idxs = _valid_idxs(s.get("fact_idxs"), draft.facts) if isinstance(s, dict) else None
            if not text or len(text) > MAX_SENTENCE_CHARS or idxs is None or kept >= MAX_SENTENCES:
                draft.dropped += 1
                continue
            kept += 1
            out.append((draft, text, idxs))
    return out


def generate_revision(db: Session, user_id: uuid.UUID, document_id: uuid.UUID, keys: list[str]) -> list[RevisionNote]:
    """One generator call for all concepts, one batched Gate 1 call for all sentences. The caller commits."""
    known = concept_facts(db, document_id)
    drafts = {k: _Draft(concept=known[k][0], facts=known[k][1]) for k in keys}
    payload = {
        "concepts": [
            {"concept": d.concept, "facts": [{"idx": i, "text": t} for i, t in d.facts.items()]} for d in drafts.values()
        ]
    }
    reply = provider.generate_json("generator", REVISION_NOTES_SYSTEM, json.dumps(payload, ensure_ascii=False))
    candidates = _collect(drafts, reply)

    items = [{"id": i, "facts": [d.facts[x] for x in idxs], "sentence": text} for i, (d, text, idxs) in enumerate(candidates)]
    found = _batch(GATE_REVISION_SYSTEM, items)
    same_family = provider.same_family_checker()
    for i, (draft, text, idxs) in enumerate(candidates):
        r = found.get(i)
        verdict = str(r.get("verdict", "")).strip().upper() if r else ""
        passed = verdict == "SUPPORTED"
        reason = _reason(r) if verdict in ("SUPPORTED", "NOT_SUPPORTED") else NO_VERDICT
        db.add(
            GenerationLog(
                document_id=document_id,
                quiz_id=None,
                candidate_id=draft.note_id,
                gate=GATE,
                passed=passed,
                reason=reason,
                same_family_fallback=same_family,
            )
        )
        if passed:
            draft.sentences.append({"text": text, "fact_idxs": idxs})
        else:
            draft.dropped += 1

    notes = [
        RevisionNote(
            id=d.note_id, user_id=user_id, document_id=document_id, concept=d.concept, sentences=d.sentences, dropped=d.dropped
        )
        for d in drafts.values()
    ]
    db.add_all(notes)
    db.flush()
    return notes


def latest_notes(db: Session, user_id: uuid.UUID, document_id: uuid.UUID) -> list[RevisionNote]:
    """The newest note per concept (the router orders them weakest first)."""
    rows = db.scalars(
        select(RevisionNote)
        .where(RevisionNote.user_id == user_id, RevisionNote.document_id == document_id)
        .ext(distinct_on(RevisionNote.concept))
        .order_by(RevisionNote.concept, RevisionNote.created_at.desc(), RevisionNote.id)
    ).all()
    return sorted(rows, key=lambda n: n.created_at, reverse=True)
