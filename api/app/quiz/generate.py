"""One generator call writes the questions (MCQ and short answer, SPEC 9.7) for a batch of targets; each reply item is validated (SPEC section 4)."""
import json
import random
import uuid
from dataclasses import dataclass, field

from app.llm import provider
from app.models import Fact
from app.quiz.prompts import GENERATE_QUESTIONS_SYSTEM, REGENERATE_NOTE
from app.quiz.select import Target

MAX_CONTEXT_FACTS = 2
MAX_MISCONCEPTION_WORDS = 12
MAX_MODEL_ANSWER_WORDS = 60


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
    distractors: list[dict] = field(default_factory=list)  # [{option, fact_idxs, misconception}], stored order
    model_answer: str | None = None  # short answers only (SPEC 9.7)
    error: str | None = None  # set when the reply item is missing or malformed
    gate_results: dict = field(default_factory=dict)
    failed_gate: str | None = None
    failed_reason: str | None = None

    @property
    def target_idx(self) -> int:
        return self.target.fact.idx

    @property
    def qtype(self) -> str:
        return self.target.qtype

    @property
    def answer_text(self) -> str:
        """What Gate 1 checks: the correct option, or the model answer of a short question."""
        return self.model_answer if self.qtype == "short" else self.options[self.answer_index]


def _request(targets: list[Target], contexts: dict[int, list[Fact]], problems: dict[int, str] | None) -> str:
    items = []
    for t in targets:
        item = {
            "target": {"idx": t.fact.idx, "text": t.fact.text, "concept": t.fact.concept},
            "context": [{"idx": c.idx, "text": c.text} for c in contexts.get(t.fact.idx, [])],
            "bloom_level": t.bloom_level,
        }
        if t.qtype == "short":  # MCQ items stay unmarked, which keeps the prompt short
            item["qtype"] = "short"
        if problems and t.fact.idx in problems:
            item["previous_problem"] = problems[t.fact.idx]
        items.append(item)
    return json.dumps({"items": items}, ensure_ascii=False)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _distractors(raw, answer: int, allowed_idxs: set[int]) -> tuple[list[dict], str | None]:
    """SPEC 9.2: one entry per wrong option (generator order), fact_idxs ⊆ this item, misconception ≤ 12 words."""
    if not isinstance(raw, list):
        return [], "distractors must be a list"
    entries: dict[int, dict] = {}
    for d in raw:
        if not isinstance(d, dict):
            return [], "distractor entry is not an object"
        option, idxs, misconception = d.get("option"), d.get("fact_idxs"), d.get("misconception")
        if not _is_int(option) or not 0 <= option <= 3:
            return [], "distractor option must be 0-3"
        if option == answer:
            return [], "distractor points at the answer"
        if option in entries:
            return [], "distractor option is duplicated"
        if not isinstance(idxs, list) or not idxs or not all(_is_int(i) for i in idxs):
            return [], "distractor fact_idxs must be a non-empty list of integers"
        if not set(idxs) <= allowed_idxs:
            return [], "distractor fact_idxs cites a fact outside this item"
        if not isinstance(misconception, str) or not misconception.strip():
            return [], "distractor misconception is empty"
        if len(misconception.split()) > MAX_MISCONCEPTION_WORDS:
            return [], f"distractor misconception is over {MAX_MISCONCEPTION_WORDS} words"
        entries[option] = {"option": option, "fact_idxs": sorted(set(idxs)), "misconception": " ".join(misconception.split())}
    if len(entries) != 3:
        return [], "distractors must cover every wrong option"
    return [entries[k] for k in sorted(entries)], None


def _cited(idxs, target: Target, allowed_idxs: set[int]) -> tuple[list[int], str | None]:
    if not isinstance(idxs, list) or not all(_is_int(i) for i in idxs):
        return [], "fact_idxs must be a list of integers"
    cited = sorted(set(idxs) | {target.fact.idx})
    if not set(cited) <= allowed_idxs:
        return [], "fact_idxs cites a fact outside this item"
    if len(cited) > 1 + MAX_CONTEXT_FACTS:
        return [], f"fact_idxs cites more than {MAX_CONTEXT_FACTS} context facts"
    return cited, None


def validate_short(raw, target: Target, allowed_idxs: set[int]) -> Candidate:
    """SPEC 9.7: a stem, a model answer (≤ 60 words) and fact_idxs from this item. Stored with options [] and
    answer_index -1; no distractors."""
    c = Candidate(target)
    if not isinstance(raw, dict):
        c.error = "no question returned for this target"
        return c
    stem, model_answer = raw.get("stem"), raw.get("model_answer")
    if raw.get("qtype") not in (None, "short"):
        c.error = "expected a short-answer item"
    elif not isinstance(stem, str) or not stem.strip():
        c.error = "empty stem"
    elif not isinstance(model_answer, str) or not model_answer.strip():
        c.error = "empty model_answer"
    elif len(model_answer.split()) > MAX_MODEL_ANSWER_WORDS:
        c.error = f"model_answer is over {MAX_MODEL_ANSWER_WORDS} words"
    else:
        c.fact_idxs, c.error = _cited(raw.get("fact_idxs"), target, allowed_idxs)
    if c.error:
        return c
    c.stem = stem.strip()
    c.model_answer = " ".join(model_answer.split())
    c.options, c.answer_index, c.distractors = [], -1, []
    c.bloom_level = target.bloom_level
    return c


def validate(raw, target: Target, allowed_idxs: set[int]) -> Candidate:
    """Shape rules: 4 distinct non-empty options, answer_index 0-3, fact_idxs from this item and including the target,
    and one valid distractor entry per wrong option (SPEC 9.2)."""
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
    else:
        c.fact_idxs, c.error = _cited(idxs, target, allowed_idxs)
    if not c.error:
        distractors, c.error = _distractors(raw.get("distractors"), answer, allowed_idxs)
    if c.error:
        return c
    c.stem = stem.strip()
    # Models put the answer first far too often (7 of 10 in one real quiz), so the server decides the
    # position: a shuffle seeded by candidate_id, before the gates and the hash, so what is committed is what is shown.
    order = list(range(4))
    random.Random(str(c.candidate_id)).shuffle(order)
    c.options = [options[k].strip() for k in order]
    c.answer_index = order.index(answer)
    # option was in the generator's order; store it in the shown order, sorted by option.
    c.distractors = sorted(({**d, "option": order.index(d["option"])} for d in distractors), key=lambda d: d["option"])
    # The ladder decides the level (SPEC 9.3); the generator's echo is ignored so it cannot repeat a fingerprint.
    c.bloom_level = target.bloom_level
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
        check = validate_short if t.qtype == "short" else validate
        candidates.append(check(by_target.get(t.fact.idx), t, allowed))
    return candidates
