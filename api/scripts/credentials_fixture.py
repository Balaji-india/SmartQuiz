"""Writes contracts/test/fixtures/credentials.json from app/chain/credentials.py and merkle.py (SPEC 9.8, 9.9).

The Hardhat test deploys the registry and SmartQuizCredentials from DEPLOYER (nonces 0 and 1 on a fresh account), so
the contract address, and with it the EIP-712 domain, is known here in advance. It then anchors the Python root,
checks every result proof, co-signs and revokes with the Python signatures, and checks the hashes, which proves that
Python and Solidity agree. 5 attempts, so a leaf is promoted at the first level.

Every key below is a TEST-ONLY key derived from a public label. Never fund them; they are not the .env keys.
Run from api/:  .venv/bin/python scripts/credentials_fixture.py   (Windows: .\\.venv\\Scripts\\python.exe ...)
"""
import json
import sys
from pathlib import Path

import rlp
from eth_account import Account
from eth_utils import keccak, to_checksum_address

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.chain import credentials as cred  # noqa: E402
from app.chain import merkle  # noqa: E402
from app.config import ROOT_DIR  # noqa: E402

OUT = ROOT_DIR / "contracts" / "test" / "fixtures" / "credentials.json"
HARDHAT_CHAIN_ID = 31337


def test_key(label: str) -> str:
    return "0x" + keccak(f"smartquiz test-only {label}".encode("utf-8")).hex()


def create_address(sender: str, nonce: int) -> str:
    return to_checksum_address(keccak(rlp.encode([bytes.fromhex(sender[2:]), nonce]))[12:])


DOC_UUID = "00000000-0000-4000-8000-000000000008"
BATCH_UUID = "00000000-0000-4000-8000-0000000000b1"
CONCEPT = "Round-robin scheduling"
FACTS = ["Round-robin gives each process a fixed time quantum.", "A context switch saves the process state."]
ATTEMPTS = [
    {"quiz_id": "00000000-0000-4000-8000-00000000a001", "answers": [0, 2, 1, 3], "score": 3, "total": 4,
     "grades": [None, None, None, None], "salt": "0" * 31 + "1"},
    {"quiz_id": "00000000-0000-4000-8000-00000000a002", "answers": [1, "Each process gets a fixed slice.", None],
     "score": 1, "total": 3, "grades": [None, "correct", None], "salt": "0" * 31 + "2"},
    {"quiz_id": "00000000-0000-4000-8000-00000000a003", "answers": ["Ünïcode answer", 0], "score": 1, "total": 2,
     "grades": ["partial", None], "salt": "0" * 31 + "3"},
    {"quiz_id": "00000000-0000-4000-8000-00000000a004", "answers": [3, 3, 3], "score": 0, "total": 3,
     "grades": [None, None, None], "salt": "0" * 31 + "4"},
    {"quiz_id": "00000000-0000-4000-8000-00000000a005", "answers": [2], "score": 1, "total": 1,
     "grades": [None], "salt": "0" * 31 + "5"},
]
BADGE_TOKEN_ID = 1
BADGE_REASON = "evidence attempt was retaken under another account"
DOC_REASON = "wrong chapter uploaded"


def main() -> None:
    deployer = Account.from_key(test_key("deployer"))
    educator = Account.from_key(test_key("educator"))
    stranger = Account.from_key(test_key("not an educator"))
    registry_address = create_address(deployer.address, 0)
    credentials_address = create_address(deployer.address, 1)

    hashes = [cred.attempt_hash(**a) for a in ATTEMPTS]
    leaves = [merkle.result_leaf(h) for h in hashes]
    root = merkle.build_tree(leaves)
    proofs = [merkle.proof(leaves, i) for i in range(len(leaves))]
    assert all(merkle.verify(root, leaves[i], proofs[i]) for i in range(len(leaves)))

    doc_id = "0x" + keccak(DOC_UUID.encode("utf-8")).hex()
    fact_leaves = [merkle.leaf(i, merkle.text_hash(t)) for i, t in enumerate(FACTS)]
    fact_root = merkle.build_tree(fact_leaves)
    badge_reason, doc_reason = cred.reason_hash(BADGE_REASON), cred.reason_hash(DOC_REASON)

    def sig(account, primary, **fields) -> str:
        s = cred.sign("0x" + bytes(account.key).hex(), HARDHAT_CHAIN_ID, credentials_address, primary, **fields)
        assert cred.recover(s, HARDHAT_CHAIN_ID, credentials_address, primary, **fields) == account.address
        return s

    data = {
        "_note": "TEST-ONLY keys derived from public labels; never fund them. Written by api/scripts/credentials_fixture.py.",
        "chain_id": HARDHAT_CHAIN_ID,
        "deployer_key": "0x" + bytes(deployer.key).hex(),
        "deployer": deployer.address,
        "registry_address": registry_address,
        "credentials_address": credentials_address,
        "educator": educator.address,
        "stranger": stranger.address,
        "batch_uuid": BATCH_UUID,
        "batch_id": cred.batch_chain_id(BATCH_UUID),
        "root": root,
        "attempts": [
            {"attempt": a, "attempt_hash": h, "leaf": l, "proof": p}
            for a, h, l, p in zip(ATTEMPTS, hashes, leaves, proofs)
        ],
        "doc_uuid": DOC_UUID,
        "doc_id": doc_id,
        "fact_root": fact_root,
        "fact_count": len(FACTS),
        "concept": CONCEPT,
        "concept_hash": cred.concept_hash(DOC_UUID, CONCEPT),
        "evidence_hash": cred.evidence_hash(hashes[:3]),
        "badge_token_id": BADGE_TOKEN_ID,
        "badge_reason_hash": badge_reason,
        "doc_reason_hash": doc_reason,
        "sigs": {
            "cosign": sig(educator, "CoSign", docId=doc_id, factRoot=fact_root),
            "revoke_badge": sig(educator, "RevokeBadge", tokenId=BADGE_TOKEN_ID, reasonHash=badge_reason),
            "revoke_document": sig(educator, "RevokeDocument", docId=doc_id, reasonHash=doc_reason),
            "cosign_by_stranger": sig(stranger, "CoSign", docId=doc_id, factRoot=fact_root),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT} root={root} credentials={credentials_address}")


if __name__ == "__main__":
    main()
