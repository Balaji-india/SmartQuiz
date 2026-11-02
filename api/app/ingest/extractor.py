"""Chunking, fact extraction (generator) and the faithfulness check (checker)."""
import json
from dataclasses import dataclass

from app.ingest.prompts import CHECK_FAITHFULNESS_SYSTEM, EXTRACT_FACTS_SYSTEM
from app.llm import provider

CHUNK_CHARS = 6000
SECTION_SEPARATOR = "\n\n"
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


@dataclass(frozen=True)
class Piece:
    """A span of one section, placed at chunk_start in a packed chunk."""

    section_position: int
    start: int
    end: int
    chunk_start: int

    @property
    def chunk_end(self) -> int:
        return self.chunk_start + self.end - self.start


@dataclass(frozen=True)
class PackedChunk:
    text: str
    pieces: tuple[Piece, ...]

    def to_section(self, start: int, end: int) -> tuple[int, int, int] | None:
        """Maps a chunk span to (section position, start, end), or None if it crosses a section boundary."""
        for piece in self.pieces:
            if piece.chunk_start <= start and end <= piece.chunk_end:
                offset = piece.start - piece.chunk_start
                return piece.section_position, start + offset, end + offset
        return None


def pack_chunks(sections, size: int = CHUNK_CHARS) -> list[PackedChunk]:
    """Fills each request with consecutive sections, so many short sections need few requests."""
    chunks: list[PackedChunk] = []
    text, pieces = "", []

    def flush() -> None:
        nonlocal text, pieces
        if pieces:
            chunks.append(PackedChunk(text, tuple(pieces)))
        text, pieces = "", []

    for section in sections:
        for start, end in chunk_spans(section.text, size):
            segment = section.text[start:end]
            if pieces and len(text) + len(SECTION_SEPARATOR) + len(segment) > size:
                flush()
            if pieces:
                text += SECTION_SEPARATOR
            pieces.append(Piece(section.position, start, end, len(text)))
            text += segment
    flush()
    return chunks


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


def _is_id(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _verdicts_by_id(reply) -> dict[int, Verdict] | None:
    if not isinstance(reply, dict):
        return None
    faithful, rejected = reply.get("faithful"), reply.get("not_faithful")
    if not isinstance(faithful, list) or not isinstance(rejected, list):
        return None
    verdicts = {i: Verdict(True, FAITHFUL) for i in faithful if _is_id(i)}
    # Rejections come second, so an id in both lists counts as rejected.
    for item in rejected:
        if isinstance(item, dict) and _is_id(item.get("id")):
            verdicts[item["id"]] = Verdict(False, str(item.get("reason") or "no reason given"))
        elif _is_id(item):
            verdicts[item] = Verdict(False, "no reason given")
    return verdicts


def check_faithfulness(pairs: list[tuple[str, str]]) -> list[Verdict]:
    """pairs: (source quote, fact). One checker call per chunk, retried once if results are missing.

    The reply lists ids rather than one object per fact, to fit Groq's output-token limit on a large batch.
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

    return [found.get(i, Verdict(False, NO_VERDICT_REASON)) for i in range(len(pairs))]
