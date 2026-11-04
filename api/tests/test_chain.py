"""P04: ChainService on a local Hardhat node, and on-chain document registration after ingestion."""
import io
import uuid
from pathlib import Path

import pytest
from eth_utils import keccak

from app.chain import merkle, service
from app.chain.service import ChainError, chain_id_of
from app.config import get_settings
from tests.conftest import signup_headers

FIXTURE = Path(__file__).parent / "fixtures" / "fixture_3p.pdf"


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch):
    monkeypatch.setattr(get_settings(), "groq_api_key", "")


def _upload(client, headers):
    return client.post(
        "/documents", files={"file": (FIXTURE.name, io.BytesIO(FIXTURE.read_bytes()))}, headers=headers
    ).json()


def test_chain_ids_are_keccak_of_the_uuid_string():
    doc = uuid.UUID("11111111-1111-4111-8111-111111111111")
    assert chain_id_of(doc) == "0x" + keccak(b"11111111-1111-4111-8111-111111111111").hex()
    assert chain_id_of(str(doc)) == chain_id_of(doc)


def test_unconfigured_chain_raises():
    with pytest.raises(ChainError, match="not configured"):
        service.get_chain()


def test_register_read_verify_and_commit(local_chain):
    doc = uuid.uuid4()
    leaves = [merkle.leaf(i, merkle.text_hash(f"fact {i}")) for i in range(5)]
    root = merkle.build_tree(leaves)

    assert local_chain.get_document(doc) is None
    tx = local_chain.register_document(doc, root, len(leaves))
    assert tx.startswith("0x") and len(tx) == 66
    stored_root, count, at = local_chain.get_document(doc)
    assert (stored_root, count) == (root, 5) and at > 0

    for i, leaf in enumerate(leaves):  # includes the promoted 5th leaf
        assert local_chain.verify_fact(doc, leaf, merkle.proof(leaves, i)) is True
    tampered = merkle.leaf(0, merkle.text_hash("fact 0 edited"))
    assert local_chain.verify_fact(doc, tampered, merkle.proof(leaves, 0)) is False

    quiz, quiz_hash = uuid.uuid4(), "0x" + "ab" * 32
    assert local_chain.get_quiz(quiz) is None
    local_chain.commit_quiz(quiz, doc, quiz_hash)
    assert local_chain.get_quiz(quiz)[:2] == (chain_id_of(doc), quiz_hash)
    with pytest.raises(ChainError, match="AlreadyCommitted"):
        local_chain.commit_quiz(quiz, doc, quiz_hash)
    with pytest.raises(ChainError, match="UnknownDocument"):
        local_chain.commit_quiz(uuid.uuid4(), uuid.uuid4(), quiz_hash)


def test_re_registering_returns_the_original_tx(local_chain):
    doc, root = uuid.uuid4(), "0x" + "cd" * 32
    first = local_chain.register_document(doc, root, 3)
    assert local_chain.register_document(doc, root, 3) == first
    with pytest.raises(ChainError, match="different root"):
        local_chain.register_document(doc, "0x" + "ef" * 32, 3)


def test_explorer_url_is_null_off_amoy(local_chain):
    assert local_chain.chain_id == 31337
    assert local_chain.explorer_url("0x" + "00" * 32) is None


def test_upload_registers_the_root_on_chain(client, local_chain):
    headers = signup_headers(client)
    created = _upload(client, headers)
    doc = client.get(f"/documents/{created['id']}", headers=headers).json()
    assert doc["status"] == "ready"
    assert doc["chain_status"] == "confirmed"
    assert doc["register_tx"].startswith("0x")
    assert doc["explorer_url"] is None  # chain id 31337, not Amoy
    root, count, _ = local_chain.get_document(created["id"])
    assert (root, count) == (doc["fact_root"], doc["fact_count"])


def test_chain_down_still_ingests_and_reports_offline(client, chain_down):
    headers = signup_headers(client)
    created = _upload(client, headers)
    doc = client.get(f"/documents/{created['id']}", headers=headers).json()
    assert doc["status"] == "ready"
    assert doc["chain_status"] == "offline"
    assert doc["register_tx"] is None and doc["explorer_url"] is None
    assert doc["fact_count"] > 0


def test_register_endpoint_retries_after_an_outage(client, monkeypatch, request):
    headers = signup_headers(client)
    created = _upload(client, headers)  # chain unconfigured → offline
    assert client.get(f"/documents/{created['id']}", headers=headers).json()["chain_status"] == "offline"

    chain = request.getfixturevalue("local_chain")
    doc = client.post(f"/documents/{created['id']}/register", headers=headers).json()
    assert doc["chain_status"] == "confirmed" and doc["register_tx"]
    assert chain.get_document(created["id"])[0] == doc["fact_root"]
    # A second retry changes nothing.
    again = client.post(f"/documents/{created['id']}/register", headers=headers).json()
    assert again["register_tx"] == doc["register_tx"]


def test_register_endpoint_with_chain_required_returns_503(client, chain_down, monkeypatch):
    headers = signup_headers(client)
    created = _upload(client, headers)
    monkeypatch.setattr(get_settings(), "chain_optional", False)
    service.reset_chain()
    response = client.post(f"/documents/{created['id']}/register", headers=headers)
    assert response.status_code == 503


def test_register_endpoint_hides_other_users_documents(client):
    created = _upload(client, signup_headers(client, "owner@b.com"))
    other = signup_headers(client, "other@b.com")
    assert client.post(f"/documents/{created['id']}/register", headers=other).status_code == 404
