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
from pathlib import Path

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from app.config import API_DIR, get_settings

CACHE_PATH: Path = API_DIR / ".cache" / "llm.sqlite"
MAX_RETRIES = 5
JSON_ONLY = "Return valid JSON only. No prose and no code fences."
_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class RoleConfig:
    api_key: str
    base_url: str
    model: str
    rpm: int
    tpm: int | None


def role_config(role: str) -> RoleConfig:
    s = get_settings()
    if role == "generator":
        return RoleConfig(s.gemini_api_key, s.generator_base_url, s.llm_generator_model, s.generator_rpm, None)
    if role == "checker":
        return RoleConfig(s.groq_api_key, s.checker_base_url, s.llm_checker_model, s.checker_rpm, s.checker_tpm)
    raise ValueError(f"unknown role: {role!r}")


def cache_key(role: str, model: str, system: str, user: str, attempt: int = 0) -> str:
    # A JSON list keeps field boundaries unambiguous.
    raw = json.dumps([role, model, system, user, attempt], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _connect() -> sqlite3.Connection:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CACHE_PATH, timeout=30)
    conn.execute("CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, body TEXT NOT NULL)")
    return conn


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
        self.calls: deque[tuple[float, int]] = deque()
        self.lock = threading.Lock()

    def acquire(self, tokens: int) -> None:
        # A single request larger than the budget must still be able to run.
        tokens = min(tokens, self.tpm) if self.tpm else tokens
        while True:
            with self.lock:
                now = time.monotonic()
                while self.calls and now - self.calls[0][0] >= 60:
                    self.calls.popleft()
                used = sum(t for _, t in self.calls)
                if len(self.calls) < self.rpm and (not self.tpm or used + tokens <= self.tpm):
                    self.calls.append((now, tokens))
                    return
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


def _chat(role: str, cfg: RoleConfig, system: str, user: str) -> str:
    client = _client(role, cfg)
    for retry in range(MAX_RETRIES + 1):
        _throttle(role, cfg).acquire(_estimate_tokens(system, user))
        try:
            response = client.chat.completions.create(
                model=cfg.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={"type": "json_object"},
            )
            return response.choices[0].message.content or ""
        except (APIStatusError, APIConnectionError, APITimeoutError) as exc:
            status = getattr(exc, "status_code", None)
            if (status is not None and status != 429 and status < 500) or retry == MAX_RETRIES:
                raise LLMError(f"{role} call failed (status {status}): {type(exc).__name__}") from exc
            time.sleep(min(2**retry + random.random(), 60))
    raise AssertionError("unreachable")


def _fake(role: str, system: str, user: str, attempt: int) -> dict:
    """Deterministic offline stand-in. Later commands extend it for their prompts."""
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
            raise LLMError(f"{role} returned invalid JSON twice") from exc

    _cache_put(key, value)
    return value
