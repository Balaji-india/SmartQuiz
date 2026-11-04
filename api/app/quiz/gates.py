"""Gates 1, 3 and 4 (SPEC section 4). Checker model only; one batched call per gate, items keyed by id.

Results go into gate_results with integers only, so the quiz hash is stable. Missing verdicts are
retried once (attempt=1), then fail closed (gates 1 and 3) or count as a blind miss (gate 4).
"""
import json
import random

from app.llm import provider
from app.quiz.generate import Candidate
from app.quiz.prompts import GATE_DEPENDENCE_SYSTEM, GATE_GROUNDING_SYSTEM, GATE_SOLVABILITY_SYSTEM

NO_VERDICT = "checker returned no verdict"
FLAG_GENERAL_BELOW = 0.3
MAX_REASON_CHARS = 300


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _reason(result: dict) -> str:
    return str(result.get("reason") or "")[:MAX_REASON_CHARS]


def _batch(system: str, items: list[dict]) -> dict[int, dict]:
    """id -> result. One call; the ids still missing get one more call with attempt=1."""
    if not items:
        return {}

    def call(batch: list[dict], attempt: int) -> dict[int, dict]:
        reply = provider.generate_json("checker", system, json.dumps({"items": batch}, ensure_ascii=False), attempt=attempt)
        results = reply.get("results") if isinstance(reply, dict) else reply if isinstance(reply, list) else []
        wanted = {item["id"] for item in batch}
        found = {}
        for r in results or []:
            if isinstance(r, dict) and _is_int(r.get("id")) and r["id"] in wanted and r["id"] not in found:
                found[r["id"]] = r
        return found

    found = call(items, 0)
    missing = [item for item in items if item["id"] not in found]
    if missing:
        found.update(call(missing, 1))
    return found


def _shuffle(c: Candidate, salt: str) -> list[int]:
    """order[k] = stored index shown at position k. Seeded per candidate, so a re-run gives the same order."""
    order = list(range(len(c.options)))
    random.Random(f"{c.candidate_id}:{salt}").shuffle(order)
    return order


def _mapped_choice(result: dict | None, order: list[int]) -> int:
    choice = result.get("choice") if result else None
    return order[choice] if _is_int(choice) and 0 <= choice < len(order) else -1


def gate1_grounding(candidates: list[Candidate], fact_text: dict[int, str]) -> None:
    items = [
        {
            "id": i,
            "facts": [fact_text[idx] for idx in c.fact_idxs],
            "stem": c.stem,
            "answer": c.options[c.answer_index],
        }
        for i, c in enumerate(candidates)
    ]
    found = _batch(GATE_GROUNDING_SYSTEM, items)
    for i, c in enumerate(candidates):
        r = found.get(i)
        verdict = str(r.get("verdict", "")).strip().upper() if r else ""
        if verdict not in ("SUPPORTED", "NOT_SUPPORTED"):
            verdict, reason = "NOT_SUPPORTED", NO_VERDICT
        else:
            reason = _reason(r)
        c.gate_results["gate1"] = {"verdict": verdict, "reason": reason}


def gate3_solvability(candidates: list[Candidate], fact_text: dict[int, str]) -> None:
    orders = [_shuffle(c, "gate3") for c in candidates]
    items = [
        {
            "id": i,
            "facts": [fact_text[idx] for idx in c.fact_idxs],
            "stem": c.stem,
            "options": [c.options[k] for k in order],
        }
        for i, (c, order) in enumerate(zip(candidates, orders))
    ]
    found = _batch(GATE_SOLVABILITY_SYSTEM, items)
    for i, (c, order) in enumerate(zip(candidates, orders)):
        r = found.get(i)
        choice = _mapped_choice(r, order)
        c.gate_results["gate3"] = {
            "passed": choice == c.answer_index,
            "choice": choice,
            "reason": _reason(r) if r else NO_VERDICT,
        }


def gate4_dependence(candidates: list[Candidate]) -> None:
    """Blind: stem + options only. Always passes; the score says how much the question needs the document."""
    orders = [_shuffle(c, "gate4") for c in candidates]
    items = [
        {"id": i, "stem": c.stem, "options": [c.options[k] for k in order]}
        for i, (c, order) in enumerate(zip(candidates, orders))
    ]
    found = _batch(GATE_DEPENDENCE_SYSTEM, items)
    for i, (c, order) in enumerate(zip(candidates, orders)):
        r = found.get(i)
        confidence = r.get("confidence") if r else None
        if isinstance(confidence, float):
            confidence = round(confidence)
        confidence = min(max(confidence, 0), 100) if _is_int(confidence) else 0
        c.gate_results["gate4"] = {
            "choice": _mapped_choice(r, order),
            "confidence": confidence,
            "reason": _reason(r) if r else NO_VERDICT,
        }


def passed_gate1(c: Candidate) -> bool:
    return c.gate_results.get("gate1", {}).get("verdict") == "SUPPORTED"


def passed_gate3(c: Candidate) -> bool:
    return bool(c.gate_results.get("gate3", {}).get("passed"))


def dependence_score(c: Candidate) -> float:
    """1 − (confidence/100 if the blind choice is correct else 0)."""
    g4 = c.gate_results["gate4"]
    return 1.0 - (g4["confidence"] / 100 if g4["choice"] == c.answer_index else 0.0)
