"""One generator call writes the MCQs for a batch of targets; each reply item is validated (SPEC section 4)."""
import json
import random
import uuid
from dataclasses import dataclass, field

from app.llm import provider
from app.models import Fact
from app.quiz.prompts import GENERATE_QUESTIONS_SYSTEM, REGENERATE_NOTE
from app.quiz.select import BLOOM_LEVELS, Target

MAX_CONTEXT_FACTS = 2


@dataclass
class Candidate:
    """One generator output for one target. candidate_id groups its generation_log rows."""

    target: Target
    candidate_id: uuid.UUID = field(default_factory=uuid.uuid4)
    stem: str = ""
    options: list[str] = field(default_factory=list)
    answer_index: int = -1
    fact_idxs: list[int] = field(default_factory=list)
    bloom_level: str = ""
    error: str | None = None  # set when the reply item is missing or malformed
    gate_results: dict = field(default_factory=dict)
    failed_gate: str | None = None
    failed_reason: str | None = None

    @property
    def target_idx(self) -> int:
        return self.target.fact.idx


def _request(targets: list[Target], contexts: dict[int, list[Fact]], problems: dict[int, str] | None) -> str:
    items = []
    for t in targets:
        item = {
            "target": {"idx": t.fact.idx, "text": t.fact.text, "concept": t.fact.concept},
            "context": [{"idx": c.idx, "text": c.text} for c in contexts.get(t.fact.idx, [])],
            "bloom_level": t.bloom_level,
        }
        if problems and t.fact.idx in problems:
            item["previous_problem"] = problems[t.fact.idx]
        items.append(item)
    return json.dumps({"items": items}, ensure_ascii=False)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate(raw, target: Target, allowed_idxs: set[int]) -> Candidate:
    """Shape rules: 4 distinct non-empty options, answer_index 0-3, fact_idxs from this item and including the target."""
    c = Candidate(target)
    if not isinstance(raw, dict):
        c.error = "no question returned for this target"
        return c
    stem, options, answer, idxs = raw.get("stem"), raw.get("options"), raw.get("answer_index"), raw.get("fact_idxs")
    if not isinstance(stem, str) or not stem.strip():
        c.error = "empty stem"
    elif not isinstance(options, list) or len(options) != 4 or not all(isinstance(o, str) and o.strip() for o in options):
        c.error = "options must be 4 non-empty strings"
    elif len({o.strip().lower() for o in options}) != 4:
        c.error = "options are not distinct"
    elif not _is_int(answer) or not 0 <= answer <= 3:
        c.error = "answer_index must be 0-3"
    elif not isinstance(idxs, list) or not all(_is_int(i) for i in idxs):
        c.error = "fact_idxs must be a list of integers"
    else:
        cited = sorted(set(idxs) | {target.fact.idx})
        if not set(cited) <= allowed_idxs:
            c.error = "fact_idxs cites a fact outside this item"
        elif len(cited) > 1 + MAX_CONTEXT_FACTS:
            c.error = f"fact_idxs cites more than {MAX_CONTEXT_FACTS} context facts"
        else:
            c.fact_idxs = cited
    if c.error:
        return c
    c.stem = stem.strip()
    # Models put the answer first far too often (7 of 10 in one real quiz), so the server decides the
    # position: a shuffle seeded by candidate_id, before the gates and the hash, so what is committed is what is shown.
    order = list(range(4))
    random.Random(str(c.candidate_id)).shuffle(order)
    c.options = [options[k].strip() for k in order]
    c.answer_index = order.index(answer)
    level = raw.get("bloom_level")
    c.bloom_level = level if level in BLOOM_LEVELS else target.bloom_level
    return c


def generate(
    targets: list[Target],
    contexts: dict[int, list[Fact]],
    attempt: int = 0,
    problems: dict[int, str] | None = None,
) -> list[Candidate]:
    """ONE generator call for all targets. attempt=1 is the batched regeneration (a new cache key)."""
    if not targets:
        return []
    system = GENERATE_QUESTIONS_SYSTEM + (REGENERATE_NOTE if attempt else "")
    reply = provider.generate_json("generator", system, _request(targets, contexts, problems), attempt=attempt)
    items = reply.get("questions") if isinstance(reply, dict) else reply if isinstance(reply, list) else None
    by_target: dict[int, dict] = {}
    for item in items or []:
        if isinstance(item, dict) and _is_int(item.get("target_idx")) and item["target_idx"] not in by_target:
            by_target[item["target_idx"]] = item
    if not by_target and items and len(items) == len(targets):
        # No target_idx at all: fall back to reply order.
        by_target = {t.fact.idx: item for t, item in zip(targets, items) if isinstance(item, dict)}

    candidates = []
    for t in targets:
        allowed = {t.fact.idx} | {c.idx for c in contexts.get(t.fact.idx, [])}
        candidates.append(validate(by_target.get(t.fact.idx), t, allowed))
    return candidates
