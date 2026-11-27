"""app/chain/credentials.py + merkle.result_leaf (SPEC 9.8, 9.9). The Hardhat suite checks the same fixture on chain."""
import json

import pytest
from eth_account import Account
from eth_utils import keccak

from app.chain import credentials as cred
from app.chain import merkle
from app.config import ROOT_DIR

FIXTURE = json.loads((ROOT_DIR / "contracts" / "test" / "fixtures" / "credentials.json").read_text(encoding="utf-8"))
ATTEMPT = {"quiz_id": "00000000-0000-4000-8000-00000000a001", "answers": [0, "Ünïcode", None], "score": 1,
           "total": 3, "grades": [None, "partial", None], "salt": "ab" * 16}
KEY = "0x" + keccak(b"pytest-only educator key").hex()


def test_fixture_is_up_to_date_with_the_python_code():
    """Fails if credentials.py or merkle.py changed without rerunning scripts/credentials_fixture.py."""
    hashes = [cred.attempt_hash(**a["attempt"]) for a in FIXTURE["attempts"]]
    assert hashes == [a["attempt_hash"] for a in FIXTURE["attempts"]]
    leaves = [merkle.result_leaf(h) for h in hashes]
    assert leaves == [a["leaf"] for a in FIXTURE["attempts"]]
    assert merkle.build_tree(leaves) == FIXTURE["root"]
    assert [merkle.proof(leaves, i) for i in range(len(leaves))] == [a["proof"] for a in FIXTURE["attempts"]]
    assert cred.batch_chain_id(FIXTURE["batch_uuid"]) == FIXTURE["batch_id"]
    assert cred.concept_hash(FIXTURE["doc_uuid"], FIXTURE["concept"]) == FIXTURE["concept_hash"]
    assert cred.evidence_hash(hashes[:3]) == FIXTURE["evidence_hash"]
    args = (FIXTURE["chain_id"], FIXTURE["credentials_address"])
    assert cred.recover(FIXTURE["sigs"]["cosign"], *args, "CoSign", docId=FIXTURE["doc_id"],
                        factRoot=FIXTURE["fact_root"]) == FIXTURE["educator"]


def test_attempt_hash_is_canonical_and_tamper_evident():
    h = cred.attempt_hash(**ATTEMPT)
    assert h.startswith("0x") and len(h) == 66 and h == h.lower()
    assert cred.attempt_hash(**dict(reversed(list(ATTEMPT.items())))) == h  # argument order does not matter
    canonical = json.dumps(ATTEMPT, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert h == "0x" + keccak(canonical).hex()
    assert cred.attempt_hash(**(ATTEMPT | {"score": 2})) != h
    assert cred.attempt_hash(**(ATTEMPT | {"grades": [None, "correct", None]})) != h
    assert cred.attempt_hash(**(ATTEMPT | {"salt": "cd" * 16})) != h


def test_result_leaf_differs_from_a_fact_leaf_and_verifies():
    hashes = [cred.attempt_hash(**(ATTEMPT | {"salt": f"{i:032x}"})) for i in range(3)]
    leaves = [merkle.result_leaf(h) for h in hashes]
    root = merkle.build_tree(leaves)
    assert all(merkle.verify(root, leaves[i], merkle.proof(leaves, i)) for i in range(3))
    tampered = cred.attempt_hash(**(ATTEMPT | {"salt": f"{0:032x}", "score": 3}))
    assert not merkle.verify(root, merkle.result_leaf(tampered), merkle.proof(leaves, 0))
    assert merkle.result_leaf(hashes[0]) != hashes[0]


def test_evidence_hash_sorts_and_needs_evidence():
    a, b = cred.attempt_hash(**ATTEMPT), cred.attempt_hash(**(ATTEMPT | {"score": 0}))
    assert cred.evidence_hash([a, b]) == cred.evidence_hash([b, a.upper().replace("0X", "0x")])
    assert cred.evidence_hash([a]) == "0x" + keccak(bytes.fromhex(a[2:])).hex()
    with pytest.raises(ValueError):
        cred.evidence_hash([])
    with pytest.raises(ValueError):
        cred.evidence_hash(["0x1234"])


def test_concept_and_reason_hashes_are_hashes_of_text_only():
    assert cred.concept_hash("doc-uuid", "Paging") == "0x" + keccak("doc-uuid|Paging".encode()).hex()
    assert cred.reason_hash("wrong chapter") == "0x" + keccak(b"wrong chapter").hex()


@pytest.mark.parametrize(
    "primary,fields",
    [
        ("CoSign", {"docId": "0x" + "11" * 32, "factRoot": "0x" + "22" * 32}),
        ("RevokeBadge", {"tokenId": 7, "reasonHash": "0x" + "33" * 32}),
        ("RevokeDocument", {"docId": "0x" + "11" * 32, "reasonHash": "0x" + "33" * 32}),
    ],
)
def test_eip712_sign_recovers_the_signer_only_in_its_own_domain(primary, fields):
    contract = "0x" + "ab" * 20
    sig = cred.sign(KEY, 80002, contract, primary, **fields)
    assert len(bytes.fromhex(sig[2:])) == 65
    assert cred.recover(sig, 80002, contract, primary, **fields) == Account.from_key(KEY).address
    assert cred.recover(sig, 31337, contract, primary, **fields) != Account.from_key(KEY).address
    assert cred.recover(sig, 80002, "0x" + "cd" * 20, primary, **fields) != Account.from_key(KEY).address
