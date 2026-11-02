"""Offline: the network call is stubbed, and the cache is a temp file."""
import sqlite3

import pytest

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


def test_throttle_enforces_tpm(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(provider.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(provider.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    throttle = provider._Throttle(rpm=100, tpm=1000)
    throttle.acquire(800)
    throttle.acquire(800)
    assert clock["t"] >= 60
