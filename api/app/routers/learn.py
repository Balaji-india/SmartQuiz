"""Gap report (SPEC 9.4), revision notes (SPEC 9.5) and the review summary (SPEC 9.6). Owner only."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.credentials.badges import live_badge_ids
from app.learn import revision
from app.learn.review import review_summary
from app.learn.mastery import P_INIT, concept_key, mastery_status
from app.llm import provider
from app.models import Fact, Mastery, RevisionNote, Section, User
from app.routers.documents import _own_document

router = APIRouter(prefix="/documents", tags=["learn"])

STATUS_ORDER = {"weak": 0, "learning": 1, "untested": 2, "mastered": 3}


class ConceptMasteryOut(BaseModel):
    concept: str
    section_id: int
    section: str
    p_mastery: float
    answered: int
    status: str
    fact_idxs: list[int]
    badge_id: uuid.UUID | None  # the unrevoked badge for this concept (SPEC 9.9)


class MasterySummary(BaseModel):
    mastered: int
    learning: int
    weak: int
    untested: int


class MasteryOut(BaseModel):
    document_id: uuid.UUID
    summary: MasterySummary
    concepts: list[ConceptMasteryOut]


def mastery_report(db: Session, user_id: uuid.UUID, document_id: uuid.UUID) -> MasteryOut:
    facts = db.scalars(select(Fact).where(Fact.document_id == document_id).order_by(Fact.idx)).all()
    headings = dict(db.execute(select(Section.id, Section.heading).where(Section.document_id == document_id)).all())
    rows = {
        concept_key(m.concept): m
        for m in db.scalars(select(Mastery).where(Mastery.user_id == user_id, Mastery.document_id == document_id))
    }

    groups: dict[str, list[Fact]] = {}
    for fact in facts:  # idx order, so groups[key][0] is the concept's first fact
        groups.setdefault(concept_key(fact.concept), []).append(fact)

    badges = live_badge_ids(db, user_id, document_id)
    concepts = []
    for key, group in groups.items():
        first, row = group[0], rows.get(key)
        p, answered = (row.p_mastery, row.answered) if row else (P_INIT, 0)
        concepts.append(
            ConceptMasteryOut(
                concept=first.concept.strip(),
                section_id=first.section_id,
                section=headings[first.section_id],
                p_mastery=round(p, 4),
                answered=answered,
                status=mastery_status(p, answered),
                fact_idxs=[f.idx for f in group],
                badge_id=badges.get(key),
            )
        )
    # weak (lowest first), learning (lowest first), untested (document order), mastered (lowest first).
    concepts.sort(key=lambda c: (STATUS_ORDER[c.status], c.p_mastery if c.status != "untested" else 0, c.fact_idxs[0]))
    counts = {s: sum(c.status == s for c in concepts) for s in STATUS_ORDER}
    return MasteryOut(document_id=document_id, summary=MasterySummary(**counts), concepts=concepts)


@router.get("/{document_id}/mastery", response_model=MasteryOut)
def get_mastery(document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> MasteryOut:
    document = _own_document(document_id, db, user)
    return mastery_report(db, user.id, document.id)


# ---- revision notes (SPEC 9.5) ----
class RevisionIn(BaseModel):
    concepts: list[str] | None = None


class RevisionSentenceOut(BaseModel):
    text: str
    fact_idxs: list[int]


class RevisionNoteOut(BaseModel):
    concept: str
    sentences: list[RevisionSentenceOut]
    dropped: int
    created_at: datetime


class RevisionOut(BaseModel):
    notes: list[RevisionNoteOut]


def _revision_out(db: Session, user_id: uuid.UUID, document_id: uuid.UUID, notes: list[RevisionNote]) -> RevisionOut:
    """Notes in gap-report order (weakest first)."""
    rank = {concept_key(c.concept): i for i, c in enumerate(mastery_report(db, user_id, document_id).concepts)}
    notes = sorted(notes, key=lambda n: rank.get(concept_key(n.concept), len(rank)))
    return RevisionOut(
        notes=[
            RevisionNoteOut(concept=n.concept, sentences=n.sentences, dropped=n.dropped, created_at=n.created_at) for n in notes
        ]
    )


@router.post("/{document_id}/revision", response_model=RevisionOut)
def post_revision(
    document_id: uuid.UUID, body: RevisionIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> RevisionOut:
    document = _own_document(document_id, db, user)
    if document.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "Document is not ready")
    try:
        keys = revision.pick_concepts(db, user.id, document.id, body.concepts)
    except revision.NoWeakConcepts:
        raise HTTPException(status.HTTP_409_CONFLICT, "No weak or learning concept to revise yet") from None
    except revision.UnknownConcepts:
        raise HTTPException(422, f"Give 1 to {revision.MAX_CONCEPTS} concepts of this document") from None
    try:
        notes = revision.generate_revision(db, user.id, document.id, keys)
    except provider.DailyLimitError:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "The daily LLM limit is reached; try again later") from None
    except provider.LLMError:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The note generator failed; try again") from None
    db.commit()
    return _revision_out(db, user.id, document.id, notes)


@router.get("/{document_id}/revision", response_model=RevisionOut)
def get_revision(document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> RevisionOut:
    document = _own_document(document_id, db, user)
    return _revision_out(db, user.id, document.id, revision.latest_notes(db, user.id, document.id))


# ---- FSRS review summary (SPEC 9.6) ----
class ReviewSummaryOut(BaseModel):
    due_now: int
    next_due: datetime | None
    cards: int


@router.get("/{document_id}/review", response_model=ReviewSummaryOut)
def get_review(document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> ReviewSummaryOut:
    document = _own_document(document_id, db, user)
    s = review_summary(db, user.id, document.id, datetime.now(timezone.utc))
    return ReviewSummaryOut(due_now=s.due_now, next_due=s.next_due, cards=s.cards)
