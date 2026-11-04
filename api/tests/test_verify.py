"""P08: public verify endpoints on a local Hardhat chain (skips without a node), plus offline behaviour."""
import json
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.chain import merkle, service
from app.config import get_settings
from app.models import Question
from app.routers import verify as verify_router
from tests.quiz_helpers import make_quiz, ready_document


@pytest.fixture(autouse=True)
def fresh_rate_limit():
    verify_router.rate_limit.hits.clear()
    yield
    verify_router.rate_limit.hits.clear()


def _submitted_quiz(client, test_engine, submit=True):
    headers, doc_id = ready_document(client)
    quiz_id = make_quiz(client, headers, doc_id)["id"]
    if submit:
        client.post(f"/quizzes/{quiz_id}/start", headers=headers)
        client.post(f"/quizzes/{quiz_id}/attempts", json={"answers": [0] * 5, "time_taken_sec": 5}, headers=headers)
    with Session(test_engine) as db:
        questions = db.scalars(select(Question).where(Question.quiz_id == uuid.UUID(quiz_id)).order_by(Question.position)).all()
    return headers, doc_id, quiz_id, questions


def _break_chain(monkeypatch):
    monkeypatch.setattr(get_settings(), "amoy_rpc_url", "http://127.0.0.1:9")
    service.reset_chain()


def test_question_is_409_before_the_attempt(client, test_engine):
    _, _, _, questions = _submitted_quiz(client, test_engine, submit=False)
    response = client.get(f"/verify/question/{questions[0].id}")
    assert response.status_code == 409 and response.json()["detail"] == "Available after the quiz is submitted"


def test_valid_question_verifies_every_fact_on_chain(client, test_engine, local_chain):
    _, doc_id, _, questions = _submitted_quiz(client, test_engine)
    out = client.get(f"/verify/question/{questions[0].id}").json()  # public: no auth header
    assert out["chain_status"] == "confirmed"
    assert out["onchain_root"] == out["db_root"]
    assert out["doc_id_onchain"] == service.chain_id_of(doc_id)
    assert out["registry_address"] == get_settings().registry_address
    assert [f["idx"] for f in out["facts"]] == sorted(questions[0].fact_idxs)
    for f in out["facts"]:
        assert f["verified_on_chain"] is True
        assert f["text_hash"] == merkle.text_hash(f["text"])
        assert merkle.verify(out["db_root"], f["leaf"], f["proof"])
    assert not {"answer_index", "options", "correct_index"} & set(json.dumps(out).replace('"', " ").split())


def test_fact_check_true_for_real_text_false_after_one_word_edit(client, test_engine, local_chain):
    _, doc_id, _, questions = _submitted_quiz(client, test_engine)
    fact = client.get(f"/verify/question/{questions[0].id}").json()["facts"][0]
    good = client.post("/verify/fact", json={"document_id": doc_id, "idx": fact["idx"], "text": fact["text"]}).json()
    assert good["verified_on_chain"] is True and good["leaf"] == fact["leaf"] and good["chain_status"] == "confirmed"
    words = fact["text"].split()
    words[1] = words[1] + "x"
    bad = client.post("/verify/fact", json={"document_id": doc_id, "idx": fact["idx"], "text": " ".join(words)}).json()
    assert bad["verified_on_chain"] is False and bad["leaf"] != fact["leaf"]


def test_quiz_hash_matches_then_mismatches_after_editing_a_question(client, test_engine, local_chain):
    _, _, quiz_id, _ = _submitted_quiz(client, test_engine)
    out = client.get(f"/verify/quiz/{quiz_id}").json()
    assert out["match"] is True and out["chain_status"] == "confirmed"
    assert out["recomputed_hash"] == out["onchain_hash"] and out["commit_tx"]
    with test_engine.begin() as conn:
        conn.execute(text("UPDATE questions SET answer_index = (answer_index + 1) % 4 WHERE quiz_id = :q AND position = 1"), {"q": quiz_id})
    tampered = client.get(f"/verify/quiz/{quiz_id}").json()
    assert tampered["match"] is False and tampered["recomputed_hash"] != tampered["onchain_hash"]


def test_chain_down_with_optional_chain_gives_offline_nulls(client, test_engine, local_chain, monkeypatch):
    _, doc_id, quiz_id, questions = _submitted_quiz(client, test_engine)
    _break_chain(monkeypatch)
    q = client.get(f"/verify/question/{questions[0].id}").json()
    assert q["chain_status"] == "offline" and q["onchain_root"] is None
    assert all(f["verified_on_chain"] is None for f in q["facts"])
    f = client.post("/verify/fact", json={"document_id": doc_id, "idx": 0, "text": "anything"}).json()
    assert f["chain_status"] == "offline" and f["verified_on_chain"] is None
    quiz = client.get(f"/verify/quiz/{quiz_id}").json()
    assert quiz["chain_status"] == "offline" and quiz["match"] is None and quiz["onchain_hash"] is None


def test_chain_down_with_required_chain_is_503(client, test_engine, local_chain, monkeypatch):
    _, doc_id, quiz_id, questions = _submitted_quiz(client, test_engine)
    _break_chain(monkeypatch)
    monkeypatch.setattr(get_settings(), "chain_optional", False)
    assert client.get(f"/verify/question/{questions[0].id}").status_code == 503
    assert client.post("/verify/fact", json={"document_id": doc_id, "idx": 0, "text": "x"}).status_code == 503
    assert client.get(f"/verify/quiz/{quiz_id}").status_code == 503


def test_never_registered_document_is_offline_not_false(client, test_engine):
    # No chain configured at all: registration and commit were skipped.
    _, doc_id, quiz_id, questions = _submitted_quiz(client, test_engine)
    q = client.get(f"/verify/question/{questions[0].id}").json()
    assert q["chain_status"] == "offline" and all(f["verified_on_chain"] is None for f in q["facts"])
    assert client.get(f"/verify/quiz/{quiz_id}").json()["match"] is None


def test_unknown_ids(client, test_engine):
    assert client.get(f"/verify/question/{uuid.uuid4()}").status_code == 404
    assert client.get(f"/verify/quiz/{uuid.uuid4()}").status_code == 404
    assert client.post("/verify/fact", json={"document_id": str(uuid.uuid4()), "idx": 0, "text": "x"}).status_code == 404
    _, doc_id, _, _ = _submitted_quiz(client, test_engine)
    assert client.post("/verify/fact", json={"document_id": doc_id, "idx": 9999, "text": "x"}).status_code == 404


def test_rate_limit_per_ip(client):
    codes = [client.get(f"/verify/quiz/{uuid.uuid4()}").status_code for _ in range(verify_router.RATE_LIMIT_PER_MINUTE + 1)]
    assert codes[:-1] == [404] * verify_router.RATE_LIMIT_PER_MINUTE and codes[-1] == 429
