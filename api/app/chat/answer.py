"""Closed-book answers (SPEC section 5, CLAUDE.md rule 3).

Abstain when the best similarity is under CHAT_MIN_SIM. Otherwise the generator answers from the top
facts, citing [F<idx>]. Cited idx must be a non-empty subset of the retrieved facts; otherwise retry
once (attempt=1), then abstain.
"""
import json
import re
import uuid

from sqlalchemy.orm import Session

from app.chat.prompts import CHAT_ANSWER_SYSTEM
from app.chat.retrieve import nearest_sections, retrieve
from app.config import get_settings
from app.llm import provider

NOT_COVERED = "This isn't covered in your material."
_BRACKET = re.compile(r"\[([^\[\]]*)\]")
_FACT_REF = re.compile(r"\bF(\d+)\b")
MAX_MESSAGE_CHARS = 1000


def cited_idxs(answer: str) -> list[int]:
    """[F12], [F12, F13] or [F12][F13] → [12, 13] in order of first mention."""
    found: list[int] = []
    for group in _BRACKET.findall(answer):
        for ref in _FACT_REF.findall(group):
            if int(ref) not in found:
                found.append(int(ref))
    return found


def _abstain(db: Session, document_id: uuid.UUID, message: str, best: float) -> dict:
    return {
        "abstained": True,
        "answer": NOT_COVERED,
        "citations": [],
        "nearest_sections": nearest_sections(db, document_id, message),
        "best_similarity": round(best, 2),
    }


def answer_question(db: Session, document_id: uuid.UUID, message: str) -> dict:
    hits = retrieve(db, document_id, message)
    best = hits[0].similarity if hits else 0.0
    if best < get_settings().chat_min_sim:
        return _abstain(db, document_id, message, best)

    facts = {h.fact.idx: h.fact for h in hits}
    user = json.dumps({"question": message, "facts": [{"idx": h.fact.idx, "text": h.fact.text} for h in hits]}, ensure_ascii=False)
    for attempt in (0, 1):
        reply = provider.generate_json("generator", CHAT_ANSWER_SYSTEM, user, attempt=attempt)
        if not isinstance(reply, dict) or reply.get("not_covered"):
            if isinstance(reply, dict):
                break  # the model says the facts do not answer it: no retry needed
            continue
        answer = str(reply.get("answer") or "").strip()
        cited = cited_idxs(answer)
        if answer and cited and set(cited) <= set(facts):
            return {
                "abstained": False,
                "answer": answer,
                "citations": [{"idx": i, "text": facts[i].text, "page": facts[i].page} for i in cited],
                "nearest_sections": [],
                "best_similarity": round(best, 2),
            }
    return _abstain(db, document_id, message, best)
