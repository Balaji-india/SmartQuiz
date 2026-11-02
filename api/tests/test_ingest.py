"""Ingestion with the FAKE LLM. The real keys are blanked so these tests can never call a provider."""
import io
import time
from pathlib import Path

import pymupdf
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.chain import merkle
from app.config import get_settings
from app.ingest import extractor, locator, parser, pipeline
from app.ingest.pipeline import fail_interrupted_ingestions, run_ingestion
from app.models import Document, Fact, GenerationLog, Section
from app.routers import documents as documents_router

FIXTURE = Path(__file__).parent / "fixtures" / "fixture_3p.pdf"
SIGNUP = {"email": "a@b.com", "password": "secret12", "name": "Test User"}
NOTES = (
    "1 Memory\n\nPaging divides physical memory into fixed size frames for the system.\n\n"
    "1.1 Segments\n\nSegmentation divides a program into logical parts of varying size.\n"
).encode("utf-8")


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "")
    monkeypatch.setattr(get_settings(), "groq_api_key", "")


def _fixture_result():
    return run_ingestion(FIXTURE.name, FIXTURE.read_bytes())


def _headers(client, email="a@b.com") -> dict:
    token = client.post("/auth/signup", json={**SIGNUP, "email": email}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _upload(client, headers, name="notes.txt", data=NOTES):
    return client.post("/documents", files={"file": (name, io.BytesIO(data))}, headers=headers)


def _unfaithful_when(monkeypatch, phrase: str, reason="adds a claim"):
    def fake(pairs):
        return [extractor.Verdict(phrase not in fact, reason if phrase in fact else "ok") for _, fact in pairs]

    monkeypatch.setattr(pipeline, "check_faithfulness", fake)


# --- Parser ---


def test_fixture_headings_come_from_font_size():
    sections = parser.parse_document(FIXTURE.name, FIXTURE.read_bytes())
    assert [s.heading for s in sections] == ["Process Management", "CPU Scheduling"]
    assert (sections[0].page_start, sections[0].page_end) == (1, 2)
    assert (sections[1].page_start, sections[1].page_end) == (3, 3)
    assert "Process Management" not in sections[0].text


def _pdf(pages: list[str], toc=None) -> bytes:
    doc = pymupdf.open()
    for body in pages:
        doc.new_page().insert_text((72, 72), body, fontsize=11)
    if toc:
        doc.set_toc(toc)
    return doc.tobytes()


def test_toc_headings_nest_and_split_within_a_page():
    data = _pdf(
        ["Overview\nIntro text here.\nDetails\nDetail text here.", "Summary\nClosing text here."],
        toc=[[1, "Overview", 1], [2, "Details", 1], [1, "Summary", 2]],
    )
    overview, details, summary = parser.parse_pdf(data)
    assert overview.text == "Intro text here."
    assert details.text == "Detail text here."
    assert details.parent_position == overview.position
    assert summary.parent_position is None and summary.page_start == 2


def test_pdf_without_any_heading_gets_one_section_per_page():
    sections = parser.parse_pdf(_pdf(["First page text here.", "Second page text here."]))
    assert [s.heading for s in sections] == ["Page 1", "Page 2"]


def test_txt_headings_nest():
    first, second = parser.parse_document("notes.txt", NOTES)
    assert (first.heading, first.level, second.heading, second.level) == ("1 Memory", 1, "1.1 Segments", 2)
    assert second.parent_position == first.position


def test_page_at_uses_the_offset_map():
    section = next(s for s in parser.parse_document(FIXTURE.name, FIXTURE.read_bytes()) if s.page_end == 2)
    assert section.page_at(0) == 1
    assert section.page_at(section.text.index("A context switch")) == 2


# --- Chunking and locating ---


def test_chunks_cover_the_text_in_order_and_end_at_sentences():
    text_ = " ".join(f"Sentence number {i} says something about the topic." for i in range(200))
    spans = extractor.chunk_spans(text_)
    assert len(spans) > 1
    assert all(end - start <= extractor.CHUNK_CHARS for start, end in spans)
    assert all(text_[end - 1] == "." for _, end in spans)
    assert " ".join(text_[s:e] for s, e in spans) == text_


def test_locator_exact_fuzzy_and_rejected():
    source = "Round-robin gives each process a fixed time quantum. Other text follows here."
    assert locator.locate("fixed time quantum", source) == (33, 51)
    start, end = locator.locate("Round-robin gives every process a fixed time quantum.", source)
    assert source[start:end].startswith("Round-robin")
    assert locator.locate("Deadlock needs four conditions to hold at the same time.", source) is None
    assert locator.locate("is a", "this was") is None  # short quotes must match exactly


# --- Pipeline ---


def test_every_fact_quote_is_at_its_offsets_and_on_its_page():
    result = _fixture_result()
    assert len(result.facts) == 10
    assert [f.idx for f in result.facts] == list(range(10))
    for fact in result.facts:
        section = result.sections[fact.section_position]
        assert section.text[fact.char_start : fact.char_end] == fact.quote
        assert section.page_at(fact.char_start) == fact.page
        assert len(fact.embedding) == 384
    assert {f.page for f in result.facts} == {1, 2, 3}


def test_root_is_stable_and_tampering_changes_it():
    first, second = _fixture_result(), _fixture_result()
    assert first.root == second.root

    leaves = [f.leaf_hash for f in first.facts]
    assert merkle.build_tree(leaves) == first.root
    leaves[3] = merkle.leaf(3, merkle.text_hash(first.facts[3].text + " tampered"))
    assert merkle.build_tree(leaves) != first.root


def test_invented_quote_is_dropped(monkeypatch):
    real = extractor.RawFact("Paging uses frames of fixed size.", "Paging divides physical memory", "Paging")
    fake = extractor.RawFact("The moon is made of cheese.", "The moon is made of green cheese entirely.", "Moon")
    monkeypatch.setattr(pipeline, "extract_facts", lambda chunk: ([real, fake], 1))
    result = run_ingestion("notes.txt", b"Paging divides physical memory into frames of a fixed size.")
    assert [f.text for f in result.facts] == [real.fact]
    assert result.facts_dropped == 2  # the invented quote and the malformed item


def test_unfaithful_fact_is_dropped_and_counted_separately(monkeypatch):
    _unfaithful_when(monkeypatch, "round-robin")
    result = _fixture_result()
    assert result.facts_unfaithful == 1
    assert result.facts_dropped == 0
    assert all("round-robin" not in f.text for f in result.facts)
    assert [f.idx for f in result.facts] == list(range(len(result.facts)))


def test_near_duplicates_are_removed_keeping_the_first(monkeypatch):
    sentence = "Paging divides physical memory into frames of a fixed size."
    result = run_ingestion("notes.txt", f"{sentence} {sentence}".encode("utf-8"))
    assert result.duplicates == 1
    assert len(result.facts) == 1 and result.facts[0].char_start == 0


# --- Faithfulness check ---


def _checker_replies(monkeypatch, *replies):
    calls = []

    def fake(role, system, user, attempt=0):
        calls.append((role, attempt))
        return replies[len(calls) - 1]

    monkeypatch.setattr(extractor.provider, "generate_json", fake)
    return calls


def test_check_uses_the_checker_once_per_batch(monkeypatch):
    calls = _checker_replies(
        monkeypatch,
        {"results": [{"id": 0, "verdict": "FAITHFUL", "reason": "ok"}, {"id": 1, "verdict": "NOT_FAITHFUL", "reason": "adds"}]},
    )
    verdicts = extractor.check_faithfulness([("q0", "f0"), ("q1", "f1")])
    assert calls == [("checker", 0)]
    assert [v.faithful for v in verdicts] == [True, False]
    assert verdicts[1].reason == "adds"


def test_missing_verdict_retries_then_fails_closed(monkeypatch):
    partial = {"results": [{"id": 0, "verdict": "FAITHFUL", "reason": "ok"}]}
    calls = _checker_replies(monkeypatch, partial, partial)
    verdicts = extractor.check_faithfulness([("q0", "f0"), ("q1", "f1")])
    assert calls == [("checker", 0), ("checker", 1)]
    assert [v.faithful for v in verdicts] == [True, False]
    assert verdicts[1].reason == extractor.NO_VERDICT_REASON


def test_unknown_verdict_word_counts_as_rejection(monkeypatch):
    _checker_replies(monkeypatch, {"results": [{"id": 0, "verdict": "MOSTLY_FAITHFUL", "reason": "?"}]})
    assert not extractor.check_faithfulness([("q", "f")])[0].faithful


def test_wrong_shape_from_checker_raises_after_retry(monkeypatch):
    calls = _checker_replies(monkeypatch, {"nope": 1}, {"nope": 2})
    with pytest.raises(extractor.ExtractionError):
        extractor.check_faithfulness([("q", "f")])
    assert len(calls) == 2


def test_wrong_shape_from_generator_retries_with_new_attempt(monkeypatch):
    good = {"facts": [{"fact": "F", "quote": "Q", "concept": "C"}, {"fact": "no quote"}]}
    calls = _checker_replies(monkeypatch, {"fake": True}, good)
    facts, malformed = extractor.extract_facts("chunk")
    assert calls == [("generator", 0), ("generator", 1)]
    assert len(facts) == 1 and malformed == 1


# --- Endpoints ---


def test_upload_reaches_ready_and_logs_every_check(client, test_engine):
    headers = _headers(client)
    created = _upload(client, headers, FIXTURE.name, FIXTURE.read_bytes()).json()
    assert created["status"] == "ingesting"
    assert created["chain_status"] == "pending"

    # TestClient finishes background tasks before returning.
    doc = client.get(f"/documents/{created['id']}", headers=headers).json()
    assert doc["status"] == "ready"
    assert doc["chain_status"] == "offline"
    assert doc["register_tx"] is None and doc["explorer_url"] is None
    assert (doc["sections_count"], doc["fact_count"], doc["facts_dropped"], doc["facts_unfaithful"]) == (2, 10, 0, 0)
    assert doc["fact_root"].startswith("0x") and len(doc["fact_root"]) == 66
    assert doc["fact_root"] == _fixture_result().root

    with Session(test_engine) as db:
        logs = db.scalars(select(GenerationLog)).all()
    assert len(logs) == 10
    assert all(row.gate == "gate0_fact" and row.passed and row.candidate_id is None for row in logs)


def test_unfaithful_fact_shows_in_document_and_log(client, test_engine, monkeypatch):
    _unfaithful_when(monkeypatch, "round-robin", "quote does not say this")
    headers = _headers(client)
    created = _upload(client, headers, FIXTURE.name, FIXTURE.read_bytes()).json()
    doc = client.get(f"/documents/{created['id']}", headers=headers).json()
    assert doc["facts_unfaithful"] == 1 and doc["fact_count"] == 9

    with Session(test_engine) as db:
        failed = db.scalars(select(GenerationLog).where(GenerationLog.passed.is_(False))).all()
        stored = db.scalars(select(Fact.text)).all()
    assert len(failed) == 1 and "quote does not say this" in failed[0].reason
    assert not any("round-robin" in t for t in stored)


def test_same_family_checker_is_flagged_in_the_log(client, test_engine, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "checker_base_url", settings.generator_base_url or "https://same.example/v1")
    monkeypatch.setattr(settings, "generator_base_url", settings.checker_base_url)
    _upload(client, _headers(client))
    with Session(test_engine) as db:
        assert all(db.scalars(select(GenerationLog.same_family_fallback)).all())


def test_textbook_is_a_nested_tree(client):
    headers = _headers(client)
    doc_id = _upload(client, headers).json()["id"]
    book = client.get(f"/documents/{doc_id}/textbook", headers=headers).json()
    assert book["document"]["id"] == doc_id
    assert [s["heading"] for s in book["sections"]] == ["1 Memory"]
    parent = book["sections"][0]
    assert parent["facts"] == [
        {
            "idx": 0,
            "text": "Paging divides physical memory into fixed size frames for the system.",
            "page": 1,
            "concept": "Paging divides physical",
        }
    ]
    assert [c["heading"] for c in parent["children"]] == ["1.1 Segments"]
    assert parent["children"][0]["facts"][0]["idx"] == 1
    assert parent["children"][0]["children"] == []


def test_same_file_is_idempotent_per_user(client, test_engine, monkeypatch):
    headers, other = _headers(client), _headers(client, "c@d.com")
    first = _upload(client, headers).json()

    calls = []
    monkeypatch.setattr(documents_router, "ingest_document", lambda *a: calls.append(a))
    again = _upload(client, headers, "renamed.txt").json()
    assert again["id"] == first["id"] and again["filename"] == "notes.txt"
    assert calls == []

    assert _upload(client, other).json()["id"] != first["id"]
    assert len(calls) == 1


def test_failed_document_can_be_retried_without_leftovers(client, test_engine, monkeypatch):
    headers = _headers(client)

    def boom(*args, **kwargs):
        raise extractor.ExtractionError("provider down")

    with monkeypatch.context() as m:
        m.setattr(pipeline, "extract_facts", boom)
        doc_id = _upload(client, headers).json()["id"]
    failed = client.get(f"/documents/{doc_id}", headers=headers).json()
    assert failed["status"] == "failed" and failed["fact_root"] is None

    assert _upload(client, headers).json()["id"] == doc_id
    ready = client.get(f"/documents/{doc_id}", headers=headers).json()
    assert ready["status"] == "ready" and ready["fact_count"] == 2
    with Session(test_engine) as db:
        assert len(db.scalars(select(Section)).all()) == 2
        assert len(db.scalars(select(GenerationLog)).all()) == 2


def test_zero_facts_is_failed(client):
    headers = _headers(client)
    doc_id = _upload(client, headers, data=b"Too short.").json()["id"]
    doc = client.get(f"/documents/{doc_id}", headers=headers).json()
    assert doc["status"] == "failed" and doc["fact_count"] == 0 and doc["fact_root"] is None


def test_corrupt_pdf_is_failed_not_stuck(client):
    headers = _headers(client)
    doc_id = _upload(client, headers, "bad.pdf", b"this is not a pdf").json()["id"]
    assert client.get(f"/documents/{doc_id}", headers=headers).json()["status"] == "failed"


def test_chain_hook_failure_does_not_block_ready(client, monkeypatch):
    def boom(document):
        raise RuntimeError("rpc down")

    monkeypatch.setattr(pipeline, "register_document_onchain", boom)
    headers = _headers(client)
    doc_id = _upload(client, headers).json()["id"]
    doc = client.get(f"/documents/{doc_id}", headers=headers).json()
    assert doc["status"] == "ready" and doc["chain_status"] == "offline" and doc["fact_count"] == 2


def test_other_users_document_is_404(client):
    doc_id = _upload(client, _headers(client)).json()["id"]
    other = _headers(client, "c@d.com")
    assert client.get(f"/documents/{doc_id}", headers=other).status_code == 404
    assert client.get(f"/documents/{doc_id}/textbook", headers=other).status_code == 404
    assert client.get("/documents", headers=other).json() == []


def test_documents_require_auth(client):
    assert client.get("/documents").status_code == 401
    assert client.post("/documents", files={"file": ("n.txt", io.BytesIO(NOTES))}).status_code == 401


def test_upload_rejections(client, monkeypatch):
    headers = _headers(client)
    assert _upload(client, headers, "notes.docx").status_code == 400
    assert _upload(client, headers, data=b"").status_code == 400
    assert _upload(client, headers, data=b"\xff\xfe bad").status_code == 400
    monkeypatch.setattr(documents_router, "MAX_UPLOAD_BYTES", 10)
    assert _upload(client, headers).status_code == 413


def test_interrupted_ingestions_become_failed(client, test_engine):
    headers = _headers(client)
    doc_id = _upload(client, headers).json()["id"]
    with test_engine.begin() as conn:
        conn.execute(text("UPDATE documents SET status = 'ingesting' WHERE id = :id"), {"id": doc_id})

    from sqlalchemy.orm import sessionmaker

    assert fail_interrupted_ingestions(sessionmaker(bind=test_engine)) == 1
    with Session(test_engine) as db:
        assert db.scalars(select(Document.status)).all() == ["failed"]
