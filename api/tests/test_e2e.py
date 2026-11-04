"""P11: the Review 1 demo end to end through the API, on samples/sample.pdf, a local Hardhat chain and the
FAKE LLM (each sentence becomes a fact). CHAIN_OPTIONAL=false, as on stage. Skips without a chain node."""
import io

import pytest

from app.config import ROOT_DIR, get_settings
from tests.conftest import signup_headers

SAMPLE = ROOT_DIR / "samples" / "sample.pdf"


@pytest.mark.skipif(not SAMPLE.exists(), reason="samples/sample.pdf is missing")
def test_review1_demo_end_to_end(client, local_chain, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "chain_optional", False)
    monkeypatch.setattr(settings, "chat_min_sim", 0.69)
    headers = signup_headers(client, "demo@example.com")

    # 1. upload → textbook, root, registration
    created = client.post("/documents", files={"file": ("sample.pdf", io.BytesIO(SAMPLE.read_bytes()))}, headers=headers).json()
    doc = client.get(f"/documents/{created['id']}", headers=headers).json()
    assert doc["status"] == "ready" and doc["chain_status"] == "confirmed" and doc["fact_count"] > 100
    assert local_chain.get_document(doc["id"])[0] == doc["fact_root"]
    book = client.get(f"/documents/{doc['id']}/textbook", headers=headers).json()
    assert len(book["sections"]) >= 8

    # 2. quiz 1, committed before it can start
    quiz1 = client.post("/quizzes", json={"document_id": doc["id"]}, headers=headers).json()
    assert quiz1["status"] == "generating"
    quiz1 = client.get(f"/quizzes/{quiz1['id']}", headers=headers).json()
    assert quiz1["status"] == "ready" and quiz1["chain_status"] == "confirmed" and quiz1["generation"]["accepted"] == 10
    assert local_chain.get_quiz(quiz1["id"])[1] == quiz1["quiz_hash"]
    started = client.post(f"/quizzes/{quiz1['id']}/start", headers=headers).json()
    question_id = started["questions"][0]["id"]
    assert client.get(f"/verify/question/{question_id}").status_code == 409

    # 3. attempt → score, sources, weak concepts
    result = client.post(f"/quizzes/{quiz1['id']}/attempts", json={"answers": [0] * 10, "time_taken_sec": 120}, headers=headers).json()
    assert result["total"] == 10 and all(r["sources"] for r in result["results"])
    if result["score"] < 10:
        assert result["weak_concepts"]

    # quiz 2: zero repeated target facts
    quiz2 = client.post("/quizzes", json={"document_id": doc["id"]}, headers=headers).json()
    assert client.get(f"/quizzes/{quiz2['id']}", headers=headers).json()["status"] == "ready"
    metrics = client.get(f"/metrics/{doc['id']}", headers=headers).json()
    assert metrics["accepted"] == 20 and metrics["repeat_rate_between_quizzes"] == 0.0
    assert metrics["same_family_checker_used"] is False

    # 4. chat: in scope → cited, out of scope → abstain with 2 sections
    answer = client.post("/chat", json={"document_id": doc["id"], "message": "What does XDR stand for?"}, headers=headers).json()
    assert not answer["abstained"] and answer["citations"]
    abstain = client.post("/chat", json={"document_id": doc["id"], "message": "What is the capital of France?"}, headers=headers).json()
    assert abstain["abstained"] and len(abstain["nearest_sections"]) == 2

    # 5. verify question: true; one word edited → false
    proof = client.get(f"/verify/question/{question_id}").json()
    assert proof["chain_status"] == "confirmed" and all(f["verified_on_chain"] for f in proof["facts"])
    fact = proof["facts"][0]
    tampered = fact["text"].replace(fact["text"].split()[0], fact["text"].split()[0] + "x", 1)
    assert client.post("/verify/fact", json={"document_id": doc["id"], "idx": fact["idx"], "text": fact["text"]}).json()["verified_on_chain"] is True
    assert client.post("/verify/fact", json={"document_id": doc["id"], "idx": fact["idx"], "text": tampered}).json()["verified_on_chain"] is False

    # 6. verify quiz: recomputed hash matches the hash committed before the attempt
    quiz_check = client.get(f"/verify/quiz/{quiz1['id']}").json()
    assert quiz_check["match"] is True and quiz_check["onchain_hash"] == quiz1["quiz_hash"]
