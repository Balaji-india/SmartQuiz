"""Gap report: GET /documents/{id}/mastery (SPEC 9.4). Owner only; every concept of the document, untested included."""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.learn.mastery import P_INIT, concept_key, mastery_status
from app.models import Fact, Mastery, Section, User
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
    badge_id: uuid.UUID | None  # set by R08 credentials


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
                badge_id=None,
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
