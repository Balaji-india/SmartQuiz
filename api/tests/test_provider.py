"""Offline: the network call is stubbed, and the cache is a temp file."""
import sqlite3
from types import SimpleNamespace

import httpx
import pytest
from openai import APIStatusError

from app.llm import provider
from app.llm.provider import RoleConfig


@pytest.fixture
def cache(tmp_path, monkeypatch):
    path = tmp_path / "llm.sqlite"
    monkeypatch.setattr(provider, "CACHE_PATH", path)
    return path


@pytest.fixture
def real_mode(cache, monkeypatch):
    """A non-empty key with a counting stub in place of the API."""
    cfg = RoleConfig("not-a-real-key", "http://invalid.test", "m", 1000, None)
    monkeypatch.setattr(provider, "role_config", lambda role: cfg)
    calls = []

    def fake_chat(role, cfg, system, user):
        calls.append(user)
        return '{"n": %d}' % len(calls)

    monkeypatch.setattr(provider, "_chat", fake_chat)
    return calls


@pytest.fixture
def fake_mode(cache, monkeypatch):
    cfg = RoleConfig("", "http://invalid.test", "m", 1000, None)
    monkeypatch.setattr(provider, "role_config", lambda role: cfg)


def rows(path):
    if not path.exists():
        return 0
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM responses").fetchone()[0]
    finally:
        conn.close()


def test_attempt_changes_cache_key():
    assert provider.cache_key("generator", "m", "s", "u", 0) != provider.cache_key("generator", "m", "s", "u", 1)


def test_every_field_changes_cache_key():
    base = provider.cache_key("generator", "m", "s", "u", 0)
    for other in [("checker", "m", "s", "u"), ("generator", "x", "s", "u"),
                  ("generator", "m", "x", "u"), ("generator", "m", "s", "x")]:
        assert provider.cache_key(*other, 0) != base


def test_field_boundaries_are_unambiguous():
    assert provider.cache_key("generator", "m", "ab", "c") != provider.cache_key("generator", "m", "a", "bc")


def test_same_attempt_hits_the_cache(real_mode, cache):
    first = provider.generate_json("generator", "s", "u", attempt=0)
    second = provider.generate_json("generator", "s", "u", attempt=0)
    assert first == second
    assert len(real_mode) == 1
    assert rows(cache) == 1


def test_higher_attempt_gets_a_new_response(real_mode, cache):
    first = provider.generate_json("generator", "s", "u", attempt=0)
    second = provider.generate_json("generator", "s", "u", attempt=1)
    assert first != second
    assert len(real_mode) == 2
    assert rows(cache) == 2


def test_fake_leaves_the_cache_empty(fake_mode, cache):
    assert provider.generate_json("checker", "s", "u")["fake"] is True
    assert rows(cache) == 0


def test_fake_does_not_read_the_cache(fake_mode, cache):
    provider._cache_put(provider.cache_key("checker", "m", "s", "u", 0), {"real": True})
    assert provider.generate_json("checker", "s", "u")["fake"] is True


@pytest.mark.parametrize("text", ['{"a": 1}', '```json\n{"a": 1}\n```', '  ```\n{"a": 1}\n```  '])
def test_parse_strips_code_fences(text):
    assert provider.parse_json(text) == {"a": 1}


def test_invalid_json_retries_once_then_caches(cache, monkeypatch):
    monkeypatch.setattr(provider, "role_config", lambda r: RoleConfig("k", "http://invalid.test", "m", 1000, None))
    replies = iter(["not json", '{"ok": true}'])
    systems = []

    def fake_chat(role, cfg, system, user):
        systems.append(system)
        return next(replies)

    monkeypatch.setattr(provider, "_chat", fake_chat)
    assert provider.generate_json("generator", "s", "u") == {"ok": True}
    assert provider.JSON_ONLY in systems[1]


def test_invalid_json_twice_raises_and_is_not_cached(cache, monkeypatch):
    monkeypatch.setattr(provider, "role_config", lambda r: RoleConfig("k", "http://invalid.test", "m", 1000, None))
    monkeypatch.setattr(provider, "_chat", lambda *a: "not json")
    with pytest.raises(provider.LLMError):
        provider.generate_json("generator", "s", "u")
    assert rows(cache) == 0


def test_unknown_role_rejected():
    with pytest.raises(ValueError):
        provider.role_config("nobody")


def test_throttle_enforces_rpm(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(provider.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(provider.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    throttle = provider._Throttle(rpm=2, tpm=None)
    for _ in range(3):
        throttle.acquire(10)
    assert clock["t"] >= 60


def test_throttle_counts_the_settled_tokens(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(provider.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(provider.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    throttle = provider._Throttle(rpm=100, tpm=1000)
    entry = throttle.acquire(100)
    throttle.settle(entry, 950)
    throttle.acquire(100)
    assert clock["t"] >= 60


class _Completions:
    """Plays back replies: an exception to raise, or text to return."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.count = 0

    def create(self, **kwargs):
        self.count += 1
        self.kwargs = kwargs
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        message = SimpleNamespace(content=reply)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=SimpleNamespace(total_tokens=10))


def _status_error(status: int, body: str, headers: dict | None = None) -> APIStatusError:
    request = httpx.Request("POST", "http://invalid.test")
    response = httpx.Response(status, text=body, headers=headers or {}, request=request)
    return APIStatusError("error", response=response, body=None)


@pytest.fixture
def api(cache, monkeypatch):
    """Real _chat with a stubbed HTTP client. sleep() records instead of waiting."""
    monkeypatch.setattr(provider, "_throttles", {})
    sleeps = []
    monkeypatch.setattr(provider.time, "sleep", sleeps.append)

    def install(replies, budget=0, **extra):
        cfg = RoleConfig("k", "http://invalid.test", "m", 1000, None, budget, **extra)
        monkeypatch.setattr(provider, "role_config", lambda role: cfg)
        completions = _Completions(replies)
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        monkeypatch.setattr(provider, "_client", lambda role, cfg: client)
        return completions, sleeps

    return install


@pytest.mark.parametrize(
    "body, headers",
    [
        ("Rate limit reached for model on tokens per day (TPD): Limit 200000", None),
        ("Rate limit reached for model on requests per day (RPD): Limit 1000", None),
        ('{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}', None),
        ("rate limited", {"retry-after": "7200"}),
    ],
)
def test_daily_limit_stops_with_no_retry(api, body, headers):
    completions, sleeps = api([_status_error(429, body, headers), '{"never": "reached"}'])
    with pytest.raises(provider.DailyLimitError, match="daily limit"):
        provider.generate_json("generator", "s", "u")
    assert completions.count == 1
    assert sleeps == []


def test_per_minute_limit_waits_as_told_and_retries(api):
    error = _status_error(429, "Rate limit reached on tokens per minute (TPM)", {"retry-after": "7"})
    completions, sleeps = api([error, '{"ok": true}'])
    assert provider.generate_json("generator", "s", "u") == {"ok": True}
    assert completions.count == 2
    assert sleeps == [7.0]


def test_failed_json_mode_is_retried(api):
    completions, _ = api([_status_error(400, '{"error":{"code":"json_validate_failed"}}'), '{"ok": true}'])
    assert provider.generate_json("generator", "s", "u") == {"ok": True}
    assert completions.count == 2


def test_request_too_large_is_not_retried(api):
    error = _status_error(429, "Request too large for model on output tokens per minute (OTPM): Limit 1000")
    completions, sleeps = api([error, '{"never": "reached"}'])
    with pytest.raises(provider.LLMError, match="larger than a per-minute limit"):
        provider.generate_json("checker", "s", "u")
    assert completions.count == 1 and sleeps == []


def test_other_client_errors_are_not_retried(api):
    completions, _ = api([_status_error(401, "bad key"), '{"never": "reached"}'])
    with pytest.raises(provider.LLMError) as caught:
        provider.generate_json("generator", "s", "u")
    assert not isinstance(caught.value, provider.DailyLimitError)
    assert completions.count == 1


def test_requests_are_counted_and_cache_hits_are_not(api):
    api(['{"a": 1}', '{"b": 2}'])
    provider.generate_json("generator", "s", "u")
    provider.generate_json("generator", "s", "u")  # cache hit
    assert provider.requests_used("generator") == 1
    provider.generate_json("generator", "s", "other")
    assert provider.requests_used("generator") == 2


def test_retries_count_as_requests(api):
    api([_status_error(500, "oops"), '{"ok": true}'])
    provider.generate_json("generator", "s", "u")
    assert provider.requests_used("generator") == 2


def test_budget_stops_before_sending(api):
    completions, _ = api(['{"a": 1}', '{"b": 2}'], budget=1)
    provider.generate_json("generator", "s", "one")
    with pytest.raises(provider.DailyLimitError, match="budget"):
        provider.generate_json("generator", "s", "two")
    assert completions.count == 1
    assert provider.requests_used("generator") == 1


def test_counter_starts_fresh_each_day(api, monkeypatch):
    api(['{"a": 1}'])
    provider.generate_json("generator", "s", "u")
    monkeypatch.setattr(provider, "_today", lambda: "2099-01-01")
    assert provider.requests_used("generator") == 0


@pytest.mark.parametrize(
    "model, family",
    [
        ("openai/gpt-oss-120b", "openai"),
        ("qwen/qwen3.8-27b", "qwen"),
        ("gemini-3.6-flash", "gemini"),
        ("models/gemini-3.6-flash", "gemini"),
    ],
)
def test_model_family(model, family):
    assert provider.model_family(model) == family


def test_generator_key_follows_its_base_url(monkeypatch):
    settings = provider.get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "gemini")
    monkeypatch.setattr(settings, "groq_api_key", "groq")
    monkeypatch.setattr(settings, "generator_base_url", "https://api.groq.com/openai/v1")
    assert provider.role_config("generator").api_key == "groq"
    monkeypatch.setattr(settings, "generator_base_url", "https://generativelanguage.googleapis.com/v1beta/openai/")
    assert provider.role_config("generator").api_key == "gemini"


def test_same_vendor_different_family_keeps_independence(monkeypatch):
    settings = provider.get_settings()
    monkeypatch.setattr(settings, "generator_base_url", "https://api.groq.com/openai/v1")
    monkeypatch.setattr(settings, "checker_base_url", "https://api.groq.com/openai/v1")
    monkeypatch.setattr(settings, "llm_generator_model", "openai/gpt-oss-120b")
    monkeypatch.setattr(settings, "llm_checker_model", "qwen/qwen3.8-27b")
    assert provider.same_family_checker() is False
    monkeypatch.setattr(settings, "llm_checker_model", "openai/gpt-oss-20b")
    assert provider.same_family_checker() is True


def test_throttle_enforces_tpm(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(provider.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(provider.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    throttle = provider._Throttle(rpm=100, tpm=1000)
    throttle.acquire(800)
    throttle.acquire(800)
    assert clock["t"] >= 60


@pytest.mark.parametrize("effort", [None, "low"])
def test_reasoning_effort_is_sent_only_when_set(api, effort):
    completions, _ = api(['{"ok": true}'], reasoning_effort=effort)
    provider.generate_json("generator", "s", "u")
    assert completions.kwargs.get("reasoning_effort") == effort


def test_settings_pass_reasoning_effort_per_role(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "generator_reasoning_effort", "low")
    monkeypatch.setattr(get_settings(), "checker_reasoning_effort", "")
    assert provider.role_config("generator").reasoning_effort == "low"
    assert provider.role_config("checker").reasoning_effort is None


def test_json_validate_failed_twice_stops_with_bad_json_error(api):
    error = '{"error":{"code":"json_validate_failed"}}'
    completions, _ = api([_status_error(400, error), _status_error(400, error), '{"never": "reached"}'])
    with pytest.raises(provider.BadJSONError):
        provider.generate_json("generator", "s", "u")
    assert completions.count == 2
