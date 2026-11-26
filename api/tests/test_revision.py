"""R04: revision notes for weak concepts, every sentence cited and Gate 1 checked (SPEC 9.5). FAKE LLM."""
import json
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.learn import revision
from app.llm import provider
from app.models import Fact, GenerationLog, Mastery, RevisionNote
from app.quiz.gates import NO_VERDICT
from tests.conftest import signup_headers
from tests.quiz_helpers import ready_document


class Calls:
    """Wraps provider.generate_json: records every call, lets a test replace the reply per role."""

    def __init__(self, monkeypatch, generator=None, checker=None):
        self.log: list[tuple[str, int, dict]] = []
        real = provider.generate_json
        override = {"generator": generator, "checker": checker}

        def fake(role, system, user, attempt=0):
            payload = json.loads(user)
            self.log.append((role, attempt, payload))
            if override[role]:
                return override[role](payload, attempt)
            return real(role, system, user, attempt)

        monkeypatch.setattr(provider, "generate_json", fake)

    def roles(self) -> list[str]:
        return [r for r, _, _ in self.log]


def _facts(test_engine, doc) -> dict[int, Fact]:
    with Session(test_engine) as db:
        return {f.idx: f for f in db.scalars(select(Fact).where(Fact.document_id == uuid.UUID(doc)))}


def _set_mastery(client, test_engine, headers, doc, rows: dict[int, tuple[float, int]]) -> dict[int, Fact]:
    facts = _facts(test_engine, doc)
    user_id = uuid.UUID(client.get("/auth/me", headers=headers).json()["id"])
    with Session(test_engine) as db:
        for idx, (p, n) in rows.items():
            db.add(Mastery(user_id=user_id, document_id=uuid.UUID(doc), concept=facts[idx].concept, p_mastery=p, answered=n))
        db.commit()
    return facts


def _log(test_engine) -> list[GenerationLog]:
    with Session(test_engine) as db:
        return db.scalars(select(GenerationLog).where(GenerationLog.gate == revision.GATE).order_by(GenerationLog.id)).all()


def test_409_when_no_weak_or_learning_concept(client, test_engine, monkeypatch):
    headers, doc = ready_document(client)
    _set_mastery(client, test_engine, headers, doc, {0: (0.97, 5)})  # mastered only, the rest untested
    calls = Calls(monkeypatch)
    r = client.post(f"/documents/{doc}/revision", json={"concepts": None}, headers=headers)
    assert r.status_code == 409
    assert calls.log == []  # no request spent
    assert client.get(f"/documents/{doc}/revision", headers=headers).json() == {"notes": []}


def test_null_picks_the_three_weakest_with_two_requests(client, test_engine, monkeypatch):
    headers, doc = ready_document(client)
    facts = _set_mastery(client, test_engine, headers, doc, {0: (0.97, 5), 1: (0.35, 2), 2: (0.10, 3), 3: (0.60, 1), 4: (0.45, 2)})
    calls = Calls(monkeypatch)
    r = client.post(f"/documents/{doc}/revision", json={}, headers=headers)
    assert r.status_code == 200, r.text

    assert calls.roles() == ["generator", "checker"]
    sent = calls.log[0][2]["concepts"]  # the generator sees only these concepts' facts
    assert [c["facts"] for c in sent] == [[{"idx": i, "text": facts[i].text}] for i in (2, 1, 4)]

    notes = r.json()["notes"]
    assert [n["concept"] for n in notes] == [facts[i].concept for i in (2, 1, 4)]
    for n, i in zip(notes, (2, 1, 4)):
        assert n["sentences"] == [{"text": facts[i].text, "fact_idxs": [i]}] and n["dropped"] == 0
    log = _log(test_engine)
    assert len(log) == 3 and all(row.passed and row.quiz_id is None for row in log)


def test_invalid_sentences_are_dropped_and_counted(client, test_engine, monkeypatch):
    headers, doc = ready_document(client)
    facts = _facts(test_engine, doc)
    concept = facts[0].concept

    def generator(payload, attempt):
        ok = {"text": "Round robin gives each process the same time slice.", "fact_idxs": [0]}
        return {
            "notes": [
                {
                    "concept": concept.upper(),  # names match case-insensitively
                    "sentences": [
                        ok,
                        {"text": "Paging uses frames.", "fact_idxs": [1]},  # another concept's fact
                        {"text": "Cites both.", "fact_idxs": [0, 1]},  # partly outside
                        {"text": "No citation.", "fact_idxs": []},
                        {"text": "Bool idx.", "fact_idxs": [True]},
                        {"text": "   ", "fact_idxs": [0]},
                        {"text": "x" * (revision.MAX_SENTENCE_CHARS + 1), "fact_idxs": [0]},
                        *[dict(ok, text=f"Sentence {k}.") for k in range(6)],  # 7 valid in all: one over the cap
                    ],
                },
                {"concept": facts[2].concept, "sentences": [{"text": "Unrequested.", "fact_idxs": [2]}]},
            ]
        }

    calls = Calls(monkeypatch, generator=generator)
    r = client.post(f"/documents/{doc}/revision", json={"concepts": [concept]}, headers=headers)
    assert r.status_code == 200, r.text
    (note,) = r.json()["notes"]
    assert note["concept"] == concept
    assert len(note["sentences"]) == revision.MAX_SENTENCES
    assert all(s["fact_idxs"] == [0] for s in note["sentences"])
    assert note["dropped"] == 7  # 6 invalid + 1 over the cap
    checked = calls.log[1][2]["items"]
    assert len(checked) == revision.MAX_SENTENCES and checked[0]["facts"] == [facts[0].text]


def test_gate1_not_supported_and_missing_verdicts_are_dropped(client, test_engine, monkeypatch):
    headers, doc = ready_document(client)
    facts = _facts(test_engine, doc)

    def generator(payload, attempt):
        c = payload["concepts"][0]
        idx = c["facts"][0]["idx"]
        return {"notes": [{"concept": c["concept"], "sentences": [{"text": f"S{k}.", "fact_idxs": [idx]} for k in range(3)]}]}

    def checker(payload, attempt):
        # id 0 unsupported, id 1 never answered (even on the retry), id 2 supported
        verdicts = {0: "NOT_SUPPORTED", 2: "SUPPORTED"}
        return {"results": [{"id": i["id"], "verdict": verdicts[i["id"]], "reason": "adds a claim"}
                            for i in payload["items"] if i["id"] in verdicts]}

    calls = Calls(monkeypatch, generator=generator, checker=checker)
    r = client.post(f"/documents/{doc}/revision", json={"concepts": [facts[5].concept]}, headers=headers)
    assert r.status_code == 200, r.text
    (note,) = r.json()["notes"]
    assert note["sentences"] == [{"text": "S2.", "fact_idxs": [5]}] and note["dropped"] == 2
    # 1 generator call, 1 checker call + 1 retry for the missing id only
    assert calls.roles() == ["generator", "checker", "checker"]
    assert [i["id"] for i in calls.log[2][2]["items"]] == [1] and calls.log[2][1] == 1

    log = _log(test_engine)
    assert [(row.passed, row.reason) for row in log] == [(False, "adds a claim"), (False, NO_VERDICT), (True, "adds a claim")]
    with Session(test_engine) as db:
        stored = db.scalars(select(RevisionNote)).one()
    assert {row.candidate_id for row in log} == {stored.id}


def test_get_returns_the_latest_note_per_concept(client, test_engine, monkeypatch):
    headers, doc = ready_document(client)
    facts = _set_mastery(client, test_engine, headers, doc, {1: (0.35, 2), 2: (0.10, 3)})
    a, b = facts[1].concept, facts[2].concept
    version = {"n": 0}

    def generator(payload, attempt):
        version["n"] += 1
        return {
            "notes": [
                {"concept": c["concept"], "sentences": [{"text": f"v{version['n']}", "fact_idxs": [c["facts"][0]["idx"]]}]}
                for c in payload["concepts"]
            ]
        }

    Calls(monkeypatch, generator=generator)
    assert client.post(f"/documents/{doc}/revision", json={"concepts": [a, b]}, headers=headers).status_code == 200
    assert client.post(f"/documents/{doc}/revision", json={"concepts": [a]}, headers=headers).status_code == 200

    notes = client.get(f"/documents/{doc}/revision", headers=headers).json()["notes"]
    assert [(n["concept"], n["sentences"][0]["text"]) for n in notes] == [(b, "v1"), (a, "v2")]  # weakest first
    with Session(test_engine) as db:
        assert len(db.scalars(select(RevisionNote)).all()) == 3


def test_revision_is_owner_only_and_validates_concepts(client, test_engine, monkeypatch):
    headers, doc = ready_document(client)
    other = signup_headers(client, "other@b.com")
    calls = Calls(monkeypatch)
    url = f"/documents/{doc}/revision"
    assert client.post(url, json={"concepts": None}, headers=other).status_code == 404
    assert client.get(url, headers=other).status_code == 404
    assert client.get(f"/documents/{uuid.uuid4()}/revision", headers=headers).status_code == 404
    assert client.get(url).status_code == 401 and client.post(url, json={}).status_code == 401
    assert client.post(url, json={"concepts": ["not in these notes"]}, headers=headers).status_code == 422
    assert client.post(url, json={"concepts": []}, headers=headers).status_code == 422
    six = [f.concept for f in list(_facts(test_engine, doc).values())[:6]]
    assert client.post(url, json={"concepts": six}, headers=headers).status_code == 422
    assert calls.log == []


@pytest.mark.parametrize("exc, code", [(provider.DailyLimitError("daily"), 429), (provider.LLMError("down"), 502)])
def test_llm_errors_store_nothing(client, test_engine, monkeypatch, exc, code):
    headers, doc = ready_document(client)
    concept = _facts(test_engine, doc)[0].concept

    def generator(payload, attempt):
        raise exc

    Calls(monkeypatch, generator=generator)
    assert client.post(f"/documents/{doc}/revision", json={"concepts": [concept]}, headers=headers).status_code == code
    with Session(test_engine) as db:
        assert db.scalars(select(RevisionNote)).all() == []
