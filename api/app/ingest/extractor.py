"""Chunking, fact extraction (generator) and the faithfulness check (checker)."""
import json
from dataclasses import dataclass

from app.ingest.prompts import CHECK_FAITHFULNESS_SYSTEM, EXTRACT_FACTS_SYSTEM
from app.llm import provider

CHUNK_CHARS = 1500
FAITHFUL = "FAITHFUL"
NO_VERDICT_REASON = "checker returned no verdict"


class ExtractionError(RuntimeError):
    pass


@dataclass(frozen=True)
class RawFact:
    fact: str
    quote: str
    concept: str


@dataclass(frozen=True)
class Verdict:
    faithful: bool
    reason: str


def chunk_spans(text: str, size: int = CHUNK_CHARS) -> list[tuple[int, int]]:
    """Consecutive (start, end) spans, cut at a sentence end where possible, with no overlap."""
    spans = []
    start, n = 0, len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            floor = start + size // 2
            cut = max(text.rfind(mark, floor, end) for mark in (". ", "? ", "! "))
            if cut != -1:
                end = cut + 1
            else:
                space = text.rfind(" ", floor, end)
                end = space if space != -1 else end
        spans.append((start, end))
        start = end
        while start < n and text[start] == " ":
            start += 1
    return spans


def _facts_list(reply) -> list | None:
    if isinstance(reply, list):
        return reply
    if isinstance(reply, dict) and isinstance(reply.get("facts"), list):
        return reply["facts"]
    return None


def extract_facts(chunk: str) -> tuple[list[RawFact], int]:
    """Returns (facts, malformed item count). A wrong-shaped reply is retried once, then raises."""
    items = _facts_list(provider.generate_json("generator", EXTRACT_FACTS_SYSTEM, chunk))
    if items is None:
        items = _facts_list(provider.generate_json("generator", EXTRACT_FACTS_SYSTEM, chunk, attempt=1))
    if items is None:
        raise ExtractionError("generator reply has the wrong shape")

    facts, malformed = [], 0
    for item in items:
        values = [item.get(k) if isinstance(item, dict) else None for k in ("fact", "quote", "concept")]
        if all(isinstance(v, str) and v.strip() for v in values):
            facts.append(RawFact(values[0].strip(), values[1], values[2].strip()))
        else:
            malformed += 1
    return facts, malformed


def _verdicts_by_id(reply) -> dict[int, dict] | None:
    results = reply.get("results") if isinstance(reply, dict) else None
    if not isinstance(results, list):
        return None
    return {r["id"]: r for r in results if isinstance(r, dict) and isinstance(r.get("id"), int)}


def check_faithfulness(pairs: list[tuple[str, str]]) -> list[Verdict]:
    """pairs: (source quote, fact). One checker call per chunk, retried once if results are missing.

    Fails closed: an item still without a verdict counts as not faithful.
    """
    if not pairs:
        return []
    user = json.dumps(
        {"items": [{"id": i, "quote": q, "fact": f} for i, (q, f) in enumerate(pairs)]}, ensure_ascii=False
    )
    found = _verdicts_by_id(provider.generate_json("checker", CHECK_FAITHFULNESS_SYSTEM, user))
    if found is None or len(set(found) & set(range(len(pairs)))) < len(pairs):
        again = _verdicts_by_id(provider.generate_json("checker", CHECK_FAITHFULNESS_SYSTEM, user, attempt=1))
        if found is None and again is None:
            raise ExtractionError("checker reply has the wrong shape")
        found = {**(again or {}), **(found or {})}

    verdicts = []
    for i in range(len(pairs)):
        result = found.get(i)
        if result is None:
            verdicts.append(Verdict(False, NO_VERDICT_REASON))
        else:
            # Anything other than exactly FAITHFUL is a rejection.
            verdicts.append(Verdict(result.get("verdict") == FAITHFUL, str(result.get("reason") or "")))
    return verdicts
