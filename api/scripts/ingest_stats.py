"""Run the ingestion pipeline on a file and print stats. Writes nothing to the database.

Usage: python scripts/ingest_stats.py [path]   (default: samples/sample.pdf)
"""
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ROOT_DIR  # noqa: E402
from app.ingest.pipeline import run_ingestion  # noqa: E402
from app.llm.provider import requests_used, role_config, same_family_checker  # noqa: E402

ROLES = ("generator", "checker")
RANDOM_FACTS = 5


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT_DIR / "samples" / "sample.pdf"
    if not path.exists():
        print(f"not found: {path}")
        return 1
    for role in ROLES:
        cfg = role_config(role)
        print(f"{role}: {'FAKE' if not cfg.api_key else cfg.model}")
    print(f"same family:      {same_family_checker()}")

    before = {role: requests_used(role) for role in ROLES}
    started = time.perf_counter()
    result = run_ingestion(path.name, path.read_bytes())
    seconds = time.perf_counter() - started

    print(f"file:             {path.name}")
    print(f"sections:         {len(result.sections)}")
    print(f"facts kept:       {len(result.facts)}")
    print(f"facts dropped:    {result.facts_dropped}")
    print(f"facts unfaithful: {result.facts_unfaithful}")
    print(f"duplicates:       {result.duplicates}")
    print(f"root:             {result.root}")
    print(f"seconds:          {seconds:.1f}")
    for role in ROLES:
        print(f"{role} requests: {requests_used(role) - before[role]} (today: {requests_used(role)})")

    rejected = [c.reason for c in result.checks if not c.passed]
    if rejected:
        print("rejected by gate0_fact:")
        for reason in rejected:
            print(f"  - {reason}")
    print(f"{RANDOM_FACTS} random facts:")
    for fact in random.sample(result.facts, min(RANDOM_FACTS, len(result.facts))):
        print(f"  [F{fact.idx}, p{fact.page}] {fact.text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
