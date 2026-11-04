"""quiz_hash, exactly as SPEC section 8. Used when committing (P06) and when verifying (P08)."""
import json
import secrets

from eth_utils import keccak

HASHED_FIELDS = ("stem", "options", "answer_index", "fact_idxs", "gate_results")


def new_salt() -> str:
    """32 lowercase hex chars, no 0x."""
    return secrets.token_hex(16)


def canonical_json(questions, salt: str) -> bytes:
    """questions: objects or dicts with position + the hashed fields. Ordered by position ascending."""

    def get(q, name):
        return q[name] if isinstance(q, dict) else getattr(q, name)

    ordered = sorted(questions, key=lambda q: get(q, "position"))
    obj = {
        "questions": [
            {
                "stem": get(q, "stem"),
                "options": list(get(q, "options")),
                "answer_index": int(get(q, "answer_index")),
                "fact_idxs": [int(i) for i in get(q, "fact_idxs")],
                "gate_results": get(q, "gate_results"),
            }
            for q in ordered
        ],
        "salt": salt,
    }
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def quiz_hash(questions, salt: str) -> str:
    return "0x" + keccak(canonical_json(questions, salt)).hex()
