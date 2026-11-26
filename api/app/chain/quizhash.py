"""quiz_hash, exactly as SPEC section 8 (v1) and 9.2 (v2). Used when committing (P06) and when verifying (P08).

Review 1 quizzes are v1 and must keep matching their on-chain hash; new quizzes are v2 (quizzes.hash_version).
"""
import json
import secrets

from eth_utils import keccak

HASHED_FIELDS = ("stem", "options", "answer_index", "fact_idxs", "gate_results")
HASHED_FIELDS_V2 = HASHED_FIELDS + ("distractors",)
HASH_VERSION = 2  # for new quizzes


def new_salt() -> str:
    """32 lowercase hex chars, no 0x."""
    return secrets.token_hex(16)


def canonical_json(questions, salt: str, version: int = 1) -> bytes:
    """questions: objects or dicts with position + the hashed fields. Ordered by position ascending."""

    def get(q, name, default=None):
        if isinstance(q, dict):
            return q.get(name, default)
        return getattr(q, name, default)

    def item(q) -> dict:
        base = {
            "stem": get(q, "stem"),
            "options": list(get(q, "options")),
            "answer_index": int(get(q, "answer_index")),
            "fact_idxs": [int(i) for i in get(q, "fact_idxs")],
            "gate_results": get(q, "gate_results"),
        }
        if version == 1:
            return base
        # qtype and model_answer arrive with short answers (R06); until then every question is an MCQ.
        return base | {
            "qtype": get(q, "qtype") or "mcq",
            "distractors": list(get(q, "distractors") or []),
            "model_answer": get(q, "model_answer"),
        }

    if version not in (1, 2):
        raise ValueError(f"unknown quiz hash version {version}")
    ordered = sorted(questions, key=lambda q: get(q, "position"))
    obj = {"questions": [item(q) for q in ordered], "salt": salt}
    if version == 2:
        obj["v"] = 2
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def quiz_hash(questions, salt: str, version: int = 1) -> str:
    return "0x" + keccak(canonical_json(questions, salt, version)).hex()
