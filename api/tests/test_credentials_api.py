"""R08: credentials API (SPEC 9.9). FAKE LLM; chain tests run on a local Hardhat node and skip without one."""
import json
import uuid

import pytest
from eth_account import Account
from eth_utils import keccak
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.chain import credentials as cred
from app.chain import merkle, service
from app.config import ROOT_DIR, get_settings
from app.credentials import results
from app.credentials.badges import CustodyUnavailable, custodial_address
from app.models import AnswerGrade, Attempt, Badge, Fact, Mastery, Question, ResultBatch, User
from app.routers import verify as verify_router
from scripts.make_educator import set_role
from tests.conftest import signup_headers
from tests.quiz_helpers import make_quiz, ready_document

WALLET = "0x6C25595bbcdE46DF391bE795fA6D558Eb7bF8B57"  # any valid checksummed address
SECRET = "pytest-only custody secret"


@pytest.fixture(autouse=True)
def fresh_rate_limit():
    verify_router.rate_limit.hits.clear()
    yield
    verify_router.rate_limit.hits.clear()


def _user_id(client, headers) -> uuid.UUID:
    return uuid.UUID(client.get("/auth/me", headers=headers).json()["id"])


def _educator(client, test_engine, email="edu@b.com") -> dict:
    headers = signup_headers(client, email)
    with Session(test_engine) as db:
        set_role(db, email, "educator")
    return headers


def _questions(test_engine, quiz_id) -> list[Question]:
    with Session(test_engine) as db:
        return db.scalars(select(Question).where(Question.quiz_id == uuid.UUID(quiz_id)).order_by(Question.position)).all()


def _answered_quiz(client, test_engine, headers, doc, right=True, num_short=0, short_answer=None) -> dict:
    if num_short:
        r = client.post("/quizzes", json={"document_id": doc, "num_questions": 5, "num_short": num_short}, headers=headers)
        quiz_id = r.json()["id"]
    else:
        quiz_id = make_quiz(client, headers, doc)["id"]
    qs = _questions(test_engine, quiz_id)
    answers = [
        short_answer if q.qtype == "short" else (q.answer_index if right else (q.answer_index + 1) % 4) for q in qs
    ]
    client.post(f"/quizzes/{quiz_id}/start", headers=headers)
    body = client.post(f"/quizzes/{quiz_id}/attempts", json={"answers": answers, "time_taken_sec": 5}, headers=headers)
    assert body.status_code == 200, body.text
    return {"quiz_id": quiz_id, "questions": qs, **body.json()}


def _master(test_engine, user_id, doc, question) -> str:
    """Marks the concept of a question's target fact as mastered (the BKT steps have their own tests)."""
    with Session(test_engine) as db:
        concept = db.scalar(
            select(Fact.concept).where(Fact.document_id == uuid.UUID(doc), Fact.idx == question.target_fact_idx)
        )
        db.execute(
            update(Mastery)
            .where(Mastery.user_id == user_id, Mastery.document_id == uuid.UUID(doc), Mastery.concept == concept.strip())
            .values(p_mastery=0.97)
        )
        db.commit()
    return concept.strip()


# ---- roles and wallet ----
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/educator/anchor", None),
        ("get", "/educator/grading", None),
        ("post", f"/educator/grading/{uuid.uuid4()}", {"verdict": "correct"}),
        ("get", "/educator/documents", None),
        ("post", f"/educator/documents/{uuid.uuid4()}/cosign", None),
        ("post", f"/educator/documents/{uuid.uuid4()}/revoke", {"reason": "x"}),
        ("post", f"/educator/badges/{uuid.uuid4()}/revoke", {"reason": "x"}),
    ],
)
def test_educator_endpoints_are_403_for_learners(client, method, path, body):
    headers = signup_headers(client)
    r = getattr(client, method)(path, headers=headers, **({"json": body} if body else {}))
    assert r.status_code == 403 and r.json()["detail"] == "Educators only"
    assert getattr(client, method)(path, **({"json": body} if body else {})).status_code == 401


def test_make_educator_sets_the_role_and_me_shows_it(client, test_engine):
    headers = _educator(client, test_engine)
    me = client.get("/auth/me", headers=headers).json()
    assert me["role"] == "educator" and me["wallet_address"] is None
    assert client.get("/educator/documents", headers=headers).status_code == 200
    with Session(test_engine) as db, pytest.raises(LookupError):
        set_role(db, "nobody@b.com", "educator")


@pytest.mark.parametrize(
    "given,stored",
    [
        (WALLET.lower(), WALLET),  # all lower case: no checksum to check, stored checksummed
        ("0x" + WALLET[2:].upper(), WALLET),
        (WALLET, WALLET),
        (None, None),
    ],
)
def test_wallet_is_checksummed(client, given, stored):
    headers = signup_headers(client)
    r = client.put("/auth/me/wallet", json={"wallet_address": given}, headers=headers)
    assert r.status_code == 200 and r.json()["wallet_address"] == stored
    assert client.get("/auth/me", headers=headers).json()["wallet_address"] == stored


@pytest.mark.parametrize(
    "bad",
    [
        WALLET[:-1] + ("7" if WALLET[-1] != "7" else "8"),  # one wrong hex digit... still 40 chars
        WALLET.replace("C", "c", 1),  # mixed case with a broken checksum
        "0x1234",
        "6C25595bbcdE46DF391bE795fA6D558Eb7bF8B57",
        "0x" + "0" * 40,
        "0x" + "g" * 40,
    ],
)
def test_invalid_wallet_is_422(client, bad):
    headers = signup_headers(client)
    r = client.put("/auth/me/wallet", json={"wallet_address": bad}, headers=headers)
    assert r.status_code == 422, bad
    assert client.get("/auth/me", headers=headers).json()["wallet_address"] is None


def test_custodial_address_is_deterministic_and_needs_the_secret(monkeypatch):
    user = uuid.UUID("00000000-0000-4000-8000-000000000001")
    with pytest.raises(CustodyUnavailable):
        custodial_address(user)
    monkeypatch.setattr(get_settings(), "custody_secret", SECRET)
    a = custodial_address(user)
    assert a == custodial_address(str(user)) == Account.from_key(keccak(f"{SECRET}|{user}".encode())).address
    assert a != custodial_address(uuid.uuid4())
    monkeypatch.setattr(get_settings(), "custody_secret", SECRET + "!")
    assert custodial_address(user) != a  # why CUSTODY_SECRET must never change


# ---- attempt hashes ----
def test_attempt_hash_is_set_when_final_and_stable(client, test_engine):
    headers, doc = ready_document(client)
    done = _answered_quiz(client, test_engine, headers, doc)
    with Session(test_engine) as db:
        attempt = db.get(Attempt, uuid.UUID(done["attempt_id"]))
        h, salt = attempt.attempt_hash, attempt.attempt_salt
        assert h and len(salt) == 32
        assert results.recompute_hash(db, attempt) == h
        assert h == cred.attempt_hash(attempt.quiz_id, attempt.answers, attempt.score, attempt.total, [None] * 5, salt)
        assert results.ensure_attempt_hash(db, attempt) == h  # never recomputed with a new salt
        attempt.score += 1
        assert results.recompute_hash(db, attempt) != h  # tamper-evident


def test_deferred_attempt_is_hashed_only_after_the_educator_grade(client, test_engine):
    headers, doc = ready_document(client)
    done = _answered_quiz(client, test_engine, headers, doc, num_short=1, short_answer="unsure, maybe")
    assert done["grading_status"] == "pending_review"
    with Session(test_engine) as db:
        assert db.get(Attempt, uuid.UUID(done["attempt_id"])).attempt_hash is None

    edu = _educator(client, test_engine)
    queue = client.get("/educator/grading", headers=edu).json()
    assert len(queue) == 1
    item = queue[0]
    assert item["answer_text"] == "unsure, maybe" and item["checker"]["confidence"] == 40 and item["facts"]
    assert client.post(f"/educator/grading/{item['grade_id']}", json={"verdict": "wrong"}, headers=edu).status_code == 422
    r = client.post(f"/educator/grading/{item['grade_id']}", json={"verdict": "partial"}, headers=edu)
    assert r.json() == {"grade_id": item["grade_id"], "attempt_id": done["attempt_id"], "grading_status": "final"}
    assert client.post(f"/educator/grading/{item['grade_id']}", json={"verdict": "correct"}, headers=edu).status_code == 409
    assert client.post(f"/educator/grading/{uuid.uuid4()}", json={"verdict": "correct"}, headers=edu).status_code == 404
    assert client.get("/educator/grading", headers=edu).json() == []

    with Session(test_engine) as db:
        attempt = db.get(Attempt, uuid.UUID(done["attempt_id"]))
        grades = results.final_grades(db, attempt)
        assert grades.count("partial") == 1 and grades.count(None) == 4
        assert attempt.attempt_hash == results.recompute_hash(db, attempt)


# ---- badges without a chain ----
def test_badge_404_unknown_concept_409_not_mastered_503_without_custody(client, test_engine):
    headers, doc = ready_document(client)
    done = _answered_quiz(client, test_engine, headers, doc, right=False)
    with Session(test_engine) as db:
        concept = db.scalar(select(Fact.concept).where(Fact.document_id == uuid.UUID(doc), Fact.idx == done["questions"][0].target_fact_idx))
    assert client.post("/badges", json={"document_id": doc, "concept": "No such concept"}, headers=headers).status_code == 404
    r = client.post("/badges", json={"document_id": doc, "concept": concept}, headers=headers)
    assert r.status_code == 409 and r.json()["detail"] == "Concept is not mastered yet"

    _master(test_engine, _user_id(client, headers), doc, done["questions"][0])
    r = client.post("/badges", json={"document_id": doc, "concept": concept.upper()}, headers=headers)
    assert r.status_code == 503 and "CUSTODY_SECRET" in r.json()["detail"]
    # With a wallet, the chain is the next requirement: a badge exists only on chain.
    client.put("/auth/me/wallet", json={"wallet_address": WALLET}, headers=headers)
    assert client.post("/badges", json={"document_id": doc, "concept": concept}, headers=headers).status_code == 503
    other = signup_headers(client, "other@b.com")
    assert client.post("/badges", json={"document_id": doc, "concept": concept}, headers=other).status_code == 404
    assert client.get("/badges", headers=headers).json() == []
    with Session(test_engine) as db:
        assert db.scalar(select(ResultBatch)) is None  # nothing was anchored


def test_anchor_without_a_chain_is_503_and_marks_nothing(client, test_engine, chain_down):
    headers, doc = ready_document(client)
    _answered_quiz(client, test_engine, headers, doc)
    edu = _educator(client, test_engine)
    assert client.post("/educator/anchor", headers=edu).status_code == 503
    with Session(test_engine) as db:
        assert db.scalar(select(Attempt.batch_id)) is None and db.scalar(select(ResultBatch)) is None


def test_eip712_signature_matches_the_r07_fixture():
    """The service signs exactly what Hardhat verified in R07 (deterministic RFC 6979 signatures)."""
    fx = json.loads((ROOT_DIR / "contracts" / "test" / "fixtures" / "credentials.json").read_text(encoding="utf-8"))
    educator_key = "0x" + keccak(b"smartquiz test-only educator").hex()  # the fixture's public test label
    chain = service.ChainService(
        "http://127.0.0.1:9", "0x" + "11" * 32, "0x" + "22" * 20, fx["credentials_address"], educator_key
    )
    chain._chain_id = fx["chain_id"]  # no RPC needed for signing
    address, sig = chain.educator_sign("CoSign", docId=fx["doc_id"], factRoot=fx["fact_root"])
    assert address == fx["educator"] and sig == fx["sigs"]["cosign"]
    _, sig = chain.educator_sign("RevokeBadge", tokenId=fx["badge_token_id"], reasonHash=fx["badge_reason_hash"])
    assert sig == fx["sigs"]["revoke_badge"]
    _, sig = chain.educator_sign("RevokeDocument", docId=fx["doc_id"], reasonHash=fx["doc_reason_hash"])
    assert sig == fx["sigs"]["revoke_document"]
    with pytest.raises(service.ChainError, match="EDUCATOR_PRIVATE_KEY"):
        service.ChainService("http://127.0.0.1:9", "0x" + "11" * 32, "0x" + "22" * 20, fx["credentials_address"]).educator_sign(
            "CoSign", docId=fx["doc_id"], factRoot=fx["fact_root"]
        )


# ---- on a local Hardhat chain ----
def test_anchor_batches_only_final_unanchored_attempts(client, test_engine, local_chain):
    a_headers, a_doc = ready_document(client, "a@b.com")
    b_headers, b_doc = ready_document(client, "b@b.com")
    first = _answered_quiz(client, test_engine, a_headers, a_doc)
    second = _answered_quiz(client, test_engine, b_headers, b_doc, right=False)
    pending = _answered_quiz(client, test_engine, a_headers, a_doc, num_short=1, short_answer="unsure, maybe")
    assert pending["grading_status"] == "pending_review"
    edu = _educator(client, test_engine)

    r = client.post("/educator/anchor", headers=edu).json()
    assert r["count"] == 2 and r["chain_status"] == "confirmed" and r["anchor_tx"].startswith("0x")
    assert r["explorer_url"] is None  # not Amoy
    assert local_chain.get_batch(r["batch_id"])[:2] == (r["root"], 2)
    assert client.post("/educator/anchor", headers=edu).status_code == 409  # nothing new

    with Session(test_engine) as db:
        hashes = [db.get(Attempt, uuid.UUID(x["attempt_id"])).attempt_hash for x in (first, second)]
        assert db.get(Attempt, uuid.UUID(pending["attempt_id"])).batch_id is None
    assert r["root"] == merkle.build_tree([merkle.result_leaf(h) for h in hashes])  # created_at order

    v = client.get(f"/verify/attempt/{first['attempt_id']}").json()
    assert v["match"] is True and v["verified_on_chain"] is True and v["onchain_root"] == r["root"]
    assert v["score"] == 5 and v["total"] == 5 and v["recomputed_hash"] == v["attempt_hash"] == hashes[0]
    assert "answers" not in v and "grades" not in v
    assert client.get(f"/verify/attempt/{pending['attempt_id']}").status_code == 409

    # The pending attempt joins the next batch once an educator grades it.
    grade_id = client.get("/educator/grading", headers=edu).json()[0]["grade_id"]
    client.post(f"/educator/grading/{grade_id}", json={"verdict": "correct"}, headers=edu)
    r2 = client.post("/educator/anchor", headers=edu).json()
    assert r2["count"] == 1 and r2["batch_id"] != r["batch_id"]
    assert client.get(f"/verify/attempt/{pending['attempt_id']}").json()["match"] is True

    # Tampering with a stored score is a real mismatch, never null.
    with Session(test_engine) as db:
        db.execute(update(Attempt).where(Attempt.id == uuid.UUID(first["attempt_id"])).values(score=0))
        db.commit()
    v = client.get(f"/verify/attempt/{first['attempt_id']}").json()
    assert v["match"] is False and v["verified_on_chain"] is False and v["chain_status"] == "confirmed"


def test_badges_cosign_and_revocation_end_to_end(client, test_engine, local_chain, monkeypatch):
    monkeypatch.setattr(get_settings(), "custody_secret", SECRET)
    headers, doc = ready_document(client)
    user_id = _user_id(client, headers)
    done = _answered_quiz(client, test_engine, headers, doc)
    concept = _master(test_engine, user_id, doc, done["questions"][0])
    client.put("/auth/me/wallet", json={"wallet_address": WALLET.lower()}, headers=headers)

    badge = client.post("/badges", json={"document_id": doc, "concept": concept}, headers=headers).json()
    assert badge["holder_address"] == WALLET and badge["custodial"] is False and badge["token_id"] == 1
    assert badge["chain_status"] == "confirmed" and badge["revoked"] is False
    assert badge["concept_hash"] == cred.concept_hash(doc, concept)
    assert local_chain.owner_of(1) == WALLET
    # Claiming again returns the same badge without a second mint.
    assert client.post("/badges", json={"document_id": doc, "concept": concept}, headers=headers).json()["id"] == badge["id"]
    assert [b["id"] for b in client.get("/badges", headers=headers).json()] == [badge["id"]]
    mastery = client.get(f"/documents/{doc}/mastery", headers=headers).json()
    assert next(c for c in mastery["concepts"] if c["concept"] == concept)["badge_id"] == badge["id"]
    with Session(test_engine) as db:
        attempt = db.get(Attempt, uuid.UUID(done["attempt_id"]))
        assert attempt.batch_id is not None  # anchored first
        assert badge["evidence_hash"] == cred.evidence_hash([attempt.attempt_hash])

    vb = client.get("/verify/badge/1").json()
    assert vb["match"] is True and vb["revoked"] is False and vb["evidence_attempts"] == [done["attempt_id"]]
    assert vb["onchain"]["concept_hash"] == badge["concept_hash"] and vb["onchain"]["issued_at"] > 0
    assert client.get("/verify/badge/99").status_code == 404

    # A custodial badge for a learner without a wallet.
    c_headers, c_doc = ready_document(client, "c@b.com")
    c_done = _answered_quiz(client, test_engine, c_headers, c_doc)
    c_concept = _master(test_engine, _user_id(client, c_headers), c_doc, c_done["questions"][0])
    custodial = client.post("/badges", json={"document_id": c_doc, "concept": c_concept}, headers=c_headers).json()
    assert custodial["custodial"] is True and custodial["token_id"] == 2
    assert custodial["holder_address"] == custodial_address(_user_id(client, c_headers))
    assert client.get("/verify/badge/2").json()["match"] is True

    # Co-sign, then the verify page shows it.
    edu = _educator(client, test_engine)
    cs = client.post(f"/educator/documents/{doc}/cosign", headers=edu).json()
    educator_address = Account.from_key(get_settings().educator_private_key).address
    assert cs["educator_address"] == educator_address and cs["chain_status"] == "confirmed"
    assert cred.recover(cs["signature"], 31337, get_settings().credentials_address, "CoSign",
                        docId=service.chain_id_of(doc), factRoot=client.get(f"/documents/{doc}", headers=headers).json()["fact_root"]) == educator_address
    vq = client.get(f"/verify/question/{done['questions'][0].id}").json()
    assert vq["cosign"]["educator_address"] == educator_address and vq["cosign"]["cosign_tx"] == cs["cosign_tx"]
    assert vq["document_revoked"] is False
    listed = {d["id"]: d for d in client.get("/educator/documents", headers=edu).json()}
    assert listed[doc]["cosign"]["cosign_tx"] == cs["cosign_tx"] and listed[c_doc]["cosign"] is None

    # Revoke the badge: the reason stays off chain.
    rb = client.post(f"/educator/badges/{badge['id']}/revoke", json={"reason": "retaken under another account"}, headers=edu)
    assert rb.status_code == 200 and rb.json()["revoked"] is True
    assert client.post(f"/educator/badges/{badge['id']}/revoke", json={"reason": "again"}, headers=edu).status_code == 409
    assert client.get("/verify/badge/1").json()["revoked"] is True and local_chain.get_badge(1)["revoked"] is True
    assert next(c for c in client.get(f"/documents/{doc}/mastery", headers=headers).json()["concepts"] if c["concept"] == concept)["badge_id"] is None

    # Revoke the document.
    rd = client.post(f"/educator/documents/{doc}/revoke", json={"reason": "wrong chapter uploaded"}, headers=edu).json()
    assert rd["revoked"] is True and rd["id"] == doc
    assert local_chain.is_document_revoked(doc) is True
    assert client.get(f"/verify/question/{done['questions'][0].id}").json()["document_revoked"] is True
    assert client.post(f"/educator/documents/{doc}/revoke", json={"reason": "x"}, headers=edu).status_code == 409
    assert client.post(f"/educator/documents/{doc}/cosign", headers=edu).status_code == 409
    assert client.post("/badges", json={"document_id": doc, "concept": concept}, headers=headers).status_code == 409
    with Session(test_engine) as db:
        assert db.get(Badge, uuid.UUID(badge["id"])).revoke_reason == "retaken under another account"


def test_verify_offline_gives_nulls_and_503_when_required(client, test_engine, local_chain, monkeypatch):
    monkeypatch.setattr(get_settings(), "custody_secret", SECRET)
    headers, doc = ready_document(client)
    done = _answered_quiz(client, test_engine, headers, doc)
    concept = _master(test_engine, _user_id(client, headers), doc, done["questions"][0])
    token = client.post("/badges", json={"document_id": doc, "concept": concept}, headers=headers).json()["token_id"]

    monkeypatch.setattr(get_settings(), "amoy_rpc_url", "http://127.0.0.1:9")
    service.reset_chain()
    v = client.get(f"/verify/attempt/{done['attempt_id']}").json()
    assert v["chain_status"] == "offline"
    assert v["match"] is None and v["verified_on_chain"] is None and v["onchain_root"] is None
    assert v["recomputed_hash"] == v["attempt_hash"]  # still computed off chain
    b = client.get(f"/verify/badge/{token}").json()
    assert b["chain_status"] == "offline" and b["onchain"] is None and b["match"] is None and b["revoked"] is False
    q = client.get(f"/verify/question/{done['questions'][0].id}").json()
    assert q["cosign"] is None and q["document_revoked"] is None

    monkeypatch.setattr(get_settings(), "chain_optional", False)
    assert client.get(f"/verify/attempt/{done['attempt_id']}").status_code == 503
    assert client.get(f"/verify/badge/{token}").status_code == 503


def test_cosign_needs_a_registered_document(client, test_engine):
    headers, doc = ready_document(client)  # no chain: never registered
    edu = _educator(client, test_engine)
    r = client.post(f"/educator/documents/{doc}/cosign", headers=edu)
    assert r.status_code == 409 and "registered" in r.json()["detail"]
    assert client.post(f"/educator/documents/{uuid.uuid4()}/cosign", headers=edu).status_code == 404
    assert client.post(f"/educator/documents/{doc}/revoke", json={"reason": ""}, headers=edu).status_code == 422
