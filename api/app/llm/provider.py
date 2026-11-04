"""The ONLY place that calls an LLM.

generate_json(role, system, user, attempt=0): role is "generator" or "checker".
Real responses are cached by sha256(role + model + system + user + attempt), so a
regeneration (higher attempt) gets a new response. An empty key for a role means
FAKE mode, which never touches the cache.
"""
import hashlib
import json
import random
import re
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from app.config import API_DIR, get_settings

CACHE_PATH: Path = API_DIR / ".cache" / "llm.sqlite"
MAX_RETRIES = 5
MAX_BAD_JSON_RETRIES = 1
JSON_ONLY = "Return valid JSON only. No prose and no code fences."
_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")
# Prompts carry these markers so FAKE mode knows which reply shape to produce.
TASK_EXTRACT_FACTS = "[task:extract_facts]"
TASK_CHECK_FAITHFULNESS = "[task:check_faithfulness]"
TASK_GENERATE_QUESTIONS = "[task:generate_questions]"
TASK_GATE_GROUNDING = "[task:gate_grounding]"
TASK_GATE_SOLVABILITY = "[task:gate_solvability]"
TASK_GATE_DEPENDENCE = "[task:gate_dependence]"
TASK_CHAT_ANSWER = "[task:chat_answer]"


_DAILY_LIMIT = re.compile(r"per[ _-]?day|\b[tr]pd\b|\bdaily\b", re.IGNORECASE)
# A wait this long is a daily-style cap, whatever the message says.
DAILY_RETRY_AFTER_SEC = 3600
JSON_VALIDATE_FAILED = "json_validate_failed"
REQUEST_TOO_LARGE = "request too large"


class LLMError(RuntimeError):
    pass


class DailyLimitError(LLMError):
    """A daily limit was reached. Retrying cannot help, so this always stops the work."""


class BadJSONError(LLMError):
    """The model failed to produce valid JSON twice. Usually the reply is too long: send less."""


@dataclass(frozen=True)
class RoleConfig:
    api_key: str
    base_url: str
    model: str
    rpm: int
    tpm: int | None
    requests_per_day: int = 0  # 0 = no budget
    max_tokens: int | None = None
    reasoning_effort: str | None = None


def _generator_key(s) -> str:
    # Gemini stays available as an optional generator, chosen by its base URL.
    host = urlparse(s.generator_base_url).hostname or ""
    return s.gemini_api_key if host.endswith("googleapis.com") else s.groq_api_key


def role_config(role: str) -> RoleConfig:
    s = get_settings()
    if role == "generator":
        return RoleConfig(
            _generator_key(s),
            s.generator_base_url,
            s.llm_generator_model,
            s.generator_rpm,
            s.generator_tpm,
            s.generator_requests_per_day,
            s.generator_max_tokens or None,
            s.generator_reasoning_effort or None,
        )
    if role == "checker":
        return RoleConfig(
            s.groq_api_key,
            s.checker_base_url,
            s.llm_checker_model,
            s.checker_rpm,
            s.checker_tpm,
            s.checker_requests_per_day,
            s.checker_max_tokens or None,
            s.checker_reasoning_effort or None,
        )
    raise ValueError(f"unknown role: {role!r}")


def model_family(model: str) -> str:
    """openai/gpt-oss-120b -> openai, qwen/qwen3.8-27b -> qwen, gemini-3.6-flash -> gemini."""
    name = model.removeprefix("models/").lower()
    return name.split("/", 1)[0] if "/" in name else name.split("-", 1)[0]


def same_family_checker() -> bool:
    """Independence depends on the model family, not on the host: both roles may share a vendor."""
    return model_family(role_config("generator").model) == model_family(role_config("checker").model)


def cache_key(role: str, model: str, system: str, user: str, attempt: int = 0) -> str:
    # A JSON list keeps field boundaries unambiguous.
    raw = json.dumps([role, model, system, user, attempt], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _connect() -> sqlite3.Connection:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CACHE_PATH, timeout=30)
    conn.execute("CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, body TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS request_counts "
        "(day TEXT, role TEXT, model TEXT, count INTEGER NOT NULL, PRIMARY KEY (day, role, model))"
    )
    return conn


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def requests_used(role: str) -> int:
    """Network requests sent today (UTC) for this role's model. Cache hits and FAKE replies are not requests."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT count FROM request_counts WHERE day = ? AND role = ? AND model = ?",
            (_today(), role, role_config(role).model),
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else 0


def _reserve_request(role: str, cfg: RoleConfig) -> None:
    """Counts one request, or raises without sending it if today's budget is spent."""
    conn = _connect()
    try:
        with conn:
            count = conn.execute(
                "INSERT INTO request_counts (day, role, model, count) VALUES (?, ?, ?, 1) "
                "ON CONFLICT (day, role, model) DO UPDATE SET count = count + 1 RETURNING count",
                (_today(), role, cfg.model),
            ).fetchone()[0]
            if cfg.requests_per_day and count > cfg.requests_per_day:
                # Rolling back keeps the stored count at the budget.
                conn.rollback()
                raise DailyLimitError(
                    f"{role} request budget reached: {cfg.requests_per_day} requests today for {cfg.model}. "
                    "Stopped; raise the budget in .env or wait until tomorrow (UTC)."
                )
    finally:
        conn.close()


def _cache_get(key: str):
    conn = _connect()
    try:
        row = conn.execute("SELECT body FROM responses WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    return json.loads(row[0]) if row else None


def _cache_put(key: str, value) -> None:
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO responses (key, body) VALUES (?, ?)",
                (key, json.dumps(value, ensure_ascii=False)),
            )
    finally:
        conn.close()


class _Throttle:
    """Sliding 60-second window on requests and, when set, estimated tokens."""

    def __init__(self, rpm: int, tpm: int | None):
        self.rpm, self.tpm = rpm, tpm
        self.calls: deque[list] = deque()
        self.lock = threading.Lock()

    def settle(self, entry: list, actual_tokens: int) -> None:
        """Replaces an estimate with the provider's real count, because long replies dwarf the estimate."""
        with self.lock:
            entry[1] = actual_tokens

    def acquire(self, tokens: int) -> list:
        # A single request larger than the budget must still be able to run.
        tokens = min(tokens, self.tpm) if self.tpm else tokens
        while True:
            with self.lock:
                now = time.monotonic()
                while self.calls and now - self.calls[0][0] >= 60:
                    self.calls.popleft()
                used = sum(t for _, t in self.calls)
                if len(self.calls) < self.rpm and (not self.tpm or used + tokens <= self.tpm):
                    entry = [now, tokens]
                    self.calls.append(entry)
                    return entry
                wait = 60 - (now - self.calls[0][0])
            time.sleep(max(wait, 0.05))


_throttles: dict[str, _Throttle] = {}
_clients: dict[str, OpenAI] = {}
_registry_lock = threading.Lock()


def _throttle(role: str, cfg: RoleConfig) -> _Throttle:
    with _registry_lock:
        return _throttles.setdefault(role, _Throttle(cfg.rpm, cfg.tpm))


def _client(role: str, cfg: RoleConfig) -> OpenAI:
    with _registry_lock:
        if role not in _clients:
            # Retries are ours, so they pass through the throttle.
            _clients[role] = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url, max_retries=0, timeout=120)
        return _clients[role]


def parse_json(text: str):
    return json.loads(_FENCE.sub("", text.strip()))


def _estimate_tokens(system: str, user: str) -> int:
    # ~4 chars per token, plus room for the reply.
    return (len(system) + len(user)) // 4 + 500


def _retry_after(exc: APIStatusError) -> float | None:
    try:
        return float(exc.response.headers.get("retry-after"))
    except (TypeError, ValueError):
        return None


def _is_daily_limit(exc: APIStatusError) -> bool:
    if exc.status_code != 429:
        return False
    wait = _retry_after(exc)
    return bool(_DAILY_LIMIT.search(exc.response.text)) or (wait is not None and wait >= DAILY_RETRY_AFTER_SEC)


def _chat(role: str, cfg: RoleConfig, system: str, user: str) -> str:
    client = _client(role, cfg)
    throttle = _throttle(role, cfg)
    bad_json_seen = 0
    for retry in range(MAX_RETRIES + 1):
        entry = throttle.acquire(_estimate_tokens(system, user))
        _reserve_request(role, cfg)
        try:
            response = client.chat.completions.create(
                model=cfg.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={"type": "json_object"},
                **({"max_tokens": cfg.max_tokens} if cfg.max_tokens else {}),
                **({"reasoning_effort": cfg.reasoning_effort} if cfg.reasoning_effort else {}),
            )
            if response.usage:
                throttle.settle(entry, response.usage.total_tokens)
            return response.choices[0].message.content or ""
        except (APIStatusError, APIConnectionError, APITimeoutError) as exc:
            status = getattr(exc, "status_code", None)
            wait = None
            if isinstance(exc, APIStatusError):
                if _is_daily_limit(exc):
                    raise DailyLimitError(
                        f"{role} daily limit reached for {cfg.model}. Stopped with no retries; "
                        "completed work is cached, so run again after the limit resets."
                    ) from exc
                if status == 429 and REQUEST_TOO_LARGE in exc.response.text.lower():
                    raise LLMError(
                        f"{role} request is larger than a per-minute limit of {cfg.model}. Waiting cannot help; "
                        "lower the role's MAX_TOKENS in .env or send less."
                    ) from exc
                wait = _retry_after(exc)
            # Groq answers 400 when a model breaks JSON mode; another try usually succeeds.
            bad_json = status == 400 and JSON_VALIDATE_FAILED in exc.response.text
            if bad_json:
                # Each failed try can cost thousands of tokens of the daily budget, so try only once more.
                bad_json_seen += 1
                if bad_json_seen > MAX_BAD_JSON_RETRIES:
                    raise BadJSONError(f"{role} could not produce valid JSON (status 400, {JSON_VALIDATE_FAILED})") from exc
            fatal = status is not None and status != 429 and status < 500 and not bad_json
            if fatal or retry == MAX_RETRIES:
                raise LLMError(f"{role} call failed (status {status}): {type(exc).__name__}") from exc
            time.sleep(min(wait if wait is not None else 2**retry + random.random(), 60))
    raise AssertionError("unreachable")


def _fake_extract_facts(passage: str) -> dict:
    # Each sentence of five or more words becomes a fact quoting itself.
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", passage)]
    return {
        "facts": [
            {"fact": s, "quote": s, "concept": " ".join(s.split()[:3])}
            for s in sentences
            if len(s.split()) >= 5
        ]
    }


def _fake_check_faithfulness(user: str) -> dict:
    return {"faithful": [i["id"] for i in json.loads(user)["items"]], "not_faithful": []}


def _fake_generate_questions(user: str, attempt: int) -> dict:
    # The correct option is the target fact itself, so the FAKE solvability gate can find it.
    questions = []
    for item in json.loads(user)["items"]:
        target = item["target"]
        idx, answer = target["idx"], target["idx"] % 4
        options = [f"Option {k} about {target['concept']} (fact {idx}, try {attempt})" for k in range(4)]
        options[answer] = target["text"]
        questions.append(
            {
                "target_idx": idx,
                # Built from the fact text, so different facts give dissimilar stems (no cosine duplicates).
                "stem": f"{target['text'].rstrip('.')}: which option says this? (fact {idx}, try {attempt})",
                "options": options,
                "answer_index": answer,
                "fact_idxs": [idx],
                "bloom_level": item.get("bloom_level", "remember"),
            }
        )
    return {"questions": questions}


def _fake_gate(system: str, user: str) -> dict:
    results = []
    for item in json.loads(user)["items"]:
        if TASK_GATE_GROUNDING in system:
            results.append({"id": item["id"], "verdict": "SUPPORTED", "reason": "fake"})
            continue
        facts = item.get("facts", [])
        choice = next((i for i, o in enumerate(item["options"]) if o in facts), 0)
        result = {"id": item["id"], "choice": choice, "reason": "fake"}
        if TASK_GATE_DEPENDENCE in system:
            result["confidence"] = 0
        results.append(result)
    return {"results": results}


def _fake_chat_answer(user: str) -> dict:
    facts = json.loads(user)["facts"]
    first = facts[0]
    return {"answer": f"{first['text']} [F{first['idx']}]"}


def _fake(role: str, system: str, user: str, attempt: int) -> dict:
    """Deterministic offline stand-in. Later commands extend it for their prompts."""
    if TASK_EXTRACT_FACTS in system:
        return _fake_extract_facts(user)
    if TASK_CHECK_FAITHFULNESS in system:
        return _fake_check_faithfulness(user)
    if TASK_GENERATE_QUESTIONS in system:
        return _fake_generate_questions(user, attempt)
    if any(task in system for task in (TASK_GATE_GROUNDING, TASK_GATE_SOLVABILITY, TASK_GATE_DEPENDENCE)):
        return _fake_gate(system, user)
    if TASK_CHAT_ANSWER in system:
        return _fake_chat_answer(user)
    return {"fake": True, "role": role, "attempt": attempt}


def generate_json(role: str, system: str, user: str, attempt: int = 0):
    cfg = role_config(role)
    if not cfg.api_key:
        return _fake(role, system, user, attempt)

    key = cache_key(role, cfg.model, system, user, attempt)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    text = _chat(role, cfg, system, user)
    try:
        value = parse_json(text)
    except json.JSONDecodeError:
        text = _chat(role, cfg, f"{system}\n\n{JSON_ONLY}", user)
        try:
            value = parse_json(text)
        except json.JSONDecodeError as exc:
            raise BadJSONError(f"{role} returned invalid JSON twice") from exc

    _cache_put(key, value)
    return value
