"""Target fact selection (SPEC section 4, CLAUDE.md rule 4).

Tiers, for this user + document:
  1. unused: never the target_fact_idx of an earlier non-failed quiz (even one with no attempt)
  2. last answered wrong, oldest first
  3. used as a target but never answered
  4. oldest tested
Spread across sections in proportion to their fact counts; at most 2 targets per concept.
Only the target fact counts as used; context facts in fact_idxs do not.
"""
import random
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Fact, FactCoverage, Question, Quiz

MAX_PER_CONCEPT = 2
BLOOM_LEVELS = ("remember", "understand")


@dataclass(frozen=True)
class Target:
    fact: Fact
    tier: int
    bloom_level: str  # the level to ask for
    previous_bloom: str | None  # set on a retest: the new question must use the other level


def _other(level: str | None) -> str:
    return "understand" if level == "remember" else "remember"


def _proportional_quota(counts: dict[int, int], n: int, rng: random.Random) -> dict[int, int]:
    """Largest-remainder split of n over sections, ties broken at random (seeded per quiz)."""
    total = sum(counts.values())
    if not total or n <= 0:
        return {}
    exact = {s: n * c / total for s, c in counts.items()}
    quota = {s: int(v) for s, v in exact.items()}
    order = sorted(counts, key=lambda s: (-(exact[s] - quota[s]), rng.random()))
    for s in order[: n - sum(quota.values())]:
        quota[s] += 1
    return quota


def _pick_spread(facts: list[Fact], n: int, concepts: Counter, rng: random.Random) -> list[Fact]:
    """Up to n facts, spread over sections by fact count, honouring the concept cap."""
    by_section: dict[int, list[Fact]] = defaultdict(list)
    for fact in facts:
        by_section[fact.section_id].append(fact)
    for pool in by_section.values():
        rng.shuffle(pool)

    chosen: list[Fact] = []

    def take(pool: list[Fact], limit: int) -> None:
        for fact in list(pool):
            if limit <= 0 or len(chosen) >= n:
                return
            key = fact.concept.strip().lower()
            if concepts[key] >= MAX_PER_CONCEPT:
                continue
            concepts[key] += 1
            chosen.append(fact)
            pool.remove(fact)
            limit -= 1

    quota = _proportional_quota({s: len(p) for s, p in by_section.items()}, n, rng)
    for section_id in sorted(by_section):
        take(by_section[section_id], quota.get(section_id, 0))
    # Fill any shortfall (concept cap, tiny sections) from what is left, still in section order.
    for section_id in sorted(by_section):
        take(by_section[section_id], n - len(chosen))
    return _interleave(chosen)


def _interleave(facts: list[Fact]) -> list[Fact]:
    """Round-robin over sections, so any prefix (the N kept out of N + spares) is still spread."""
    queues: dict[int, list[Fact]] = defaultdict(list)
    for fact in facts:
        queues[fact.section_id].append(fact)
    order: list[Fact] = []
    while any(queues.values()):
        for section_id in sorted(queues):
            if queues[section_id]:
                order.append(queues[section_id].pop(0))
    return order


def select_targets(db: Session, user_id: uuid.UUID, document_id: uuid.UUID, n: int, seed: str) -> list[Target]:
    rng = random.Random(seed)
    facts = db.scalars(select(Fact).where(Fact.document_id == document_id).order_by(Fact.idx)).all()

    earlier = db.execute(
        select(Question.target_fact_idx, Question.bloom_level, Quiz.created_at)
        .join(Quiz, Quiz.id == Question.quiz_id)
        .where(Quiz.user_id == user_id, Quiz.document_id == document_id, Quiz.status != "failed")
        .order_by(Quiz.created_at)
    ).all()
    used_bloom: dict[int, str] = {}
    for idx, bloom, _ in earlier:
        used_bloom[idx] = bloom  # the latest question's level wins

    coverage = {
        row.fact_id: row
        for row in db.scalars(
            select(FactCoverage).where(
                FactCoverage.user_id == user_id, FactCoverage.fact_id.in_([f.id for f in facts])
            )
        )
    }

    unused = [f for f in facts if f.idx not in used_bloom]
    tested = [f for f in facts if f.id in coverage]
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    wrong = sorted((f for f in tested if not coverage[f.id].last_correct), key=lambda f: coverage[f.id].updated_at or epoch)
    never_answered = [f for f in facts if f.idx in used_bloom and f.id not in coverage]
    right = sorted((f for f in tested if coverage[f.id].last_correct), key=lambda f: coverage[f.id].updated_at or epoch)

    concepts: Counter = Counter()
    targets: list[Target] = []
    for i, fact in enumerate(_pick_spread(unused, n, concepts, rng)):
        targets.append(Target(fact, 1, BLOOM_LEVELS[i % 2], None))

    for tier, pool in ((2, wrong), (3, never_answered), (4, right)):
        for fact in pool:
            if len(targets) >= n:
                break
            key = fact.concept.strip().lower()
            if concepts[key] >= MAX_PER_CONCEPT:
                continue
            concepts[key] += 1
            previous = coverage[fact.id].last_bloom if fact.id in coverage else used_bloom.get(fact.idx)
            targets.append(Target(fact, tier, _other(previous), previous))
    return targets


def context_facts(db: Session, document_id: uuid.UUID, target: Fact, limit: int = 4) -> list[Fact]:
    """Same-section neighbours of the target (nearest idx first), offered as optional context."""
    pool = db.scalars(
        select(Fact).where(Fact.document_id == document_id, Fact.section_id == target.section_id, Fact.idx != target.idx)
    ).all()
    return sorted(pool, key=lambda f: (abs(f.idx - target.idx), f.idx))[:limit]
