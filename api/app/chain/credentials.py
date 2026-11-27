"""Hashes and EIP-712 messages for SmartQuizCredentials (SPEC 9.8 and 9.9). Lowercase 0x hex everywhere.

Pure functions only (no RPC): R08's ChainService and api/scripts/credentials_fixture.py both use them, and the
Hardhat test checks the fixture against the contract, so Python and Solidity are proven to agree.
Only hashes and addresses leave this module for the chain (CLAUDE.md rule 6).
"""
import json
import uuid

from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak, to_checksum_address

EIP712_NAME = "SmartQuizCredentials"
EIP712_VERSION = "1"

# Must match the *_TYPEHASH strings in SmartQuizCredentials.sol.
EIP712_TYPES = {
    "CoSign": [{"name": "docId", "type": "bytes32"}, {"name": "factRoot", "type": "bytes32"}],
    "RevokeBadge": [{"name": "tokenId", "type": "uint256"}, {"name": "reasonHash", "type": "bytes32"}],
    "RevokeDocument": [{"name": "docId", "type": "bytes32"}, {"name": "reasonHash", "type": "bytes32"}],
}


def _hex(raw: bytes) -> str:
    return "0x" + raw.hex()


def _b32(hex_str: str) -> bytes:
    raw = bytes.fromhex(hex_str.removeprefix("0x"))
    if len(raw) != 32:
        raise ValueError(f"expected 32 bytes, got {len(raw)}")
    return raw


def canonical(obj) -> bytes:
    """SPEC section 8 canonical JSON: sorted keys, no spaces, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def attempt_hash(quiz_id: uuid.UUID | str, answers: list, score: int, total: int, grades: list, salt: str) -> str:
    """SPEC 9.9: keccak256 of the canonical {"quiz_id","answers","score","total","grades","salt"}.
    grades: one entry per position, the final verdict for a short question and null otherwise."""
    obj = {"quiz_id": str(quiz_id), "answers": list(answers), "score": int(score), "total": int(total),
           "grades": list(grades), "salt": salt}
    return _hex(keccak(canonical(obj)))


def batch_chain_id(batch_uuid: uuid.UUID | str) -> str:
    """batch_id on chain = keccak256(utf-8 batch UUID string)."""
    return _hex(keccak(str(batch_uuid).encode("utf-8")))


def concept_hash(document_uuid: uuid.UUID | str, concept: str) -> str:
    return _hex(keccak(f"{document_uuid}|{concept}".encode("utf-8")))


def evidence_hash(attempt_hashes: list[str]) -> str:
    """keccak256 of the concatenated bytes of the sorted attempt hashes."""
    if not attempt_hashes:
        raise ValueError("a badge needs at least one attempt hash as evidence")
    return _hex(keccak(b"".join(_b32(h) for h in sorted(h.lower() for h in attempt_hashes))))


def reason_hash(reason: str) -> str:
    """Revocation reasons stay off chain; only keccak256(utf-8 reason) is sent."""
    return _hex(keccak(reason.encode("utf-8")))


def domain(chain_id: int, verifying_contract: str) -> dict:
    return {"name": EIP712_NAME, "version": EIP712_VERSION, "chainId": int(chain_id),
            "verifyingContract": to_checksum_address(verifying_contract)}


def _message(primary: str, fields: dict) -> dict:
    out = {}
    for field in EIP712_TYPES[primary]:
        value = fields[field["name"]]
        out[field["name"]] = _b32(value) if field["type"] == "bytes32" else int(value)
    return out


def sign(private_key: str, chain_id: int, verifying_contract: str, primary: str, **fields) -> str:
    """EIP-712 signature (65 bytes, 0x hex) of one of the EIP712_TYPES messages."""
    signed = Account.sign_typed_data(
        private_key,
        domain_data=domain(chain_id, verifying_contract),
        message_types={primary: EIP712_TYPES[primary]},
        message_data=_message(primary, fields),
    )
    return _hex(bytes(signed.signature))


def recover(signature: str, chain_id: int, verifying_contract: str, primary: str, **fields) -> str:
    msg = encode_typed_data(
        domain_data=domain(chain_id, verifying_contract),
        message_types={primary: EIP712_TYPES[primary]},
        message_data=_message(primary, fields),
    )
    return Account.recover_message(msg, signature=signature)
