"""P07: closed-book chat. The calibration runs on the real sample.pdf textbook (tests/data/sample_facts.json)
with real embeddings and the FAKE generator, so it tests retrieval, the threshold and the post-check."""
import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.chat import answer as chat_answer
from app.chat.answer import NOT_COVERED, cited_idxs
from app.config import get_settings
from app.ingest.hasher import embed_texts, hash_fact
from app.models import Document, Fact, Section
from tests.conftest import signup_headers

DATA = Path(__file__).parent / "data"
CALIBRATION = json.loads((DATA / "chat_calibration.json").read_text("utf-8"))
SAMPLE_FACTS = json.loads((DATA / "sample_facts.json").read_text("utf-8"))
# The calibrated value from .env.example; tests must not depend on a developer's .env.
CALIBRATED_MIN_SIM = 0.69


@pytest.fixture(scope="module")
def sample_vectors():
    return embed_texts([f["text"] for f in SAMPLE_FACTS])


@pytest.fixture
def sample_doc(client, test_engine, sample_vectors, monkeypatch):
    monkeypatch.setattr(get_settings(), "chat_min_sim", CALIBRATED_MIN_SIM)
    headers = signup_headers(client)
    with Session(test_engine) as db:
        user_id = db.scalar(text("SELECT id FROM users"))
        doc = Document(user_id=user_id, filename="sample.pdf", file_sha256="0" * 64, status="ready", fact_count=len(SAMPLE_FACTS))
        db.add(doc)
        db.flush()
        sections: dict[str, int] = {}
        for f in SAMPLE_FACTS:
            if f["section"] not in sections:
                s = Section(document_id=doc.id, heading=f["section"], level=1, page_start=f["page"], page_end=f["page"], position=len(sections))
                db.add(s)
                db.flush()
                sections[f["section"]] = s.id
        for f, vector in zip(SAMPLE_FACTS, sample_vectors):
            th, leaf = hash_fact(f["idx"], f["text"])
            db.add(Fact(document_id=doc.id, section_id=sections[f["section"]], idx=f["idx"], concept=f["concept"], text=f["text"],
                        quote=f["text"], page=f["page"], char_start=0, char_end=len(f["text"]), text_hash=th, leaf_hash=leaf,
                        embedding=vector.tolist()))
        db.commit()
        return headers, str(doc.id)


def _chat(client, headers, doc_id, message):
    response = client.post("/chat", json={"document_id": doc_id, "message": message}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("question", CALIBRATION["in_scope"])
def test_in_scope_question_is_answered_with_citations(client, sample_doc, question):
    out = _chat(client, *sample_doc, question)
    assert out["abstained"] is False, out["best_similarity"]
    assert out["citations"] and out["nearest_sections"] == []
    assert {c["idx"] for c in out["citations"]} == set(cited_idxs(out["answer"]))
    assert out["best_similarity"] >= CALIBRATED_MIN_SIM


@pytest.mark.parametrize("question", CALIBRATION["out_of_scope"])
def test_out_of_scope_question_abstains_with_two_sections(client, sample_doc, question):
    out = _chat(client, *sample_doc, question)
    assert out["abstained"] is True, out["best_similarity"]
    assert out["answer"] == NOT_COVERED and out["citations"] == []
    assert len(out["nearest_sections"]) == 2 and all(s["heading"] for s in out["nearest_sections"])


def _replies(monkeypatch, *replies):
    calls = []

    def fake(role, system, user, attempt=0):
        calls.append(attempt)
        reply = replies[len(calls) - 1]
        return reply(json.loads(user)) if callable(reply) else reply

    monkeypatch.setattr(chat_answer.provider, "generate_json", fake)
    return calls


def test_citation_outside_retrieved_facts_retries_then_abstains(client, sample_doc, monkeypatch):
    calls = _replies(monkeypatch, {"answer": "Made up [F99999]."}, {"answer": "Still made up [F99998]."})
    out = _chat(client, *sample_doc, CALIBRATION["in_scope"][0])
    assert calls == [0, 1]
    assert out["abstained"] is True and len(out["nearest_sections"]) == 2


def test_answer_without_citation_retries_and_can_recover(client, sample_doc, monkeypatch):
    good = lambda user: {"answer": f"Yes [F{user['facts'][1]['idx']}]."}  # noqa: E731
    calls = _replies(monkeypatch, {"answer": "No citation at all."}, good)
    out = _chat(client, *sample_doc, CALIBRATION["in_scope"][0])
    assert calls == [0, 1] and out["abstained"] is False and len(out["citations"]) == 1


def test_model_saying_not_covered_abstains_without_retry(client, sample_doc, monkeypatch):
    calls = _replies(monkeypatch, {"answer": "", "not_covered": True})
    out = _chat(client, *sample_doc, CALIBRATION["in_scope"][0])
    assert calls == [0] and out["abstained"] is True


def test_below_threshold_never_calls_the_generator(client, sample_doc, monkeypatch):
    calls = _replies(monkeypatch)
    _chat(client, *sample_doc, CALIBRATION["out_of_scope"][0])
    assert calls == []


def test_cited_idxs_parsing():
    assert cited_idxs("A [F12]. B [F3, F12] and [F7][F8]. Not F9 or [x].") == [12, 3, 7, 8]


def test_chat_needs_own_ready_document(client, sample_doc):
    other = signup_headers(client, "other@b.com")
    _, doc_id = sample_doc
    response = client.post("/chat", json={"document_id": doc_id, "message": "hi"}, headers=other)
    assert response.status_code == 404
    response = client.post("/chat", json={"document_id": str(uuid.uuid4()), "message": "hi"}, headers=sample_doc[0])
    assert response.status_code == 404
