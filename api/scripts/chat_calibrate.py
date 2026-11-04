"""Calibrate CHAT_MIN_SIM on an ingested document (P07). No LLM calls: retrieval similarity only.

Usage (from api/): .venv/bin/python scripts/chat_calibrate.py <document_id> [--write]
  Prints the best similarity of every question in tests/data/chat_calibration.json and the threshold that
  separates in-scope from out-of-scope best. --write replaces only the CHAT_MIN_SIM line in .env and
  .env.example (with a comment showing both ranges in .env.example) and exports the document's facts to
  tests/data/sample_facts.json for the calibration test. Never prints other .env values.
Windows: .\\.venv\\Scripts\\python.exe scripts\\chat_calibrate.py <document_id> [--write]
"""
import json
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.chat.retrieve import retrieve  # noqa: E402
from app.config import API_DIR, ROOT_DIR  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Fact, Section  # noqa: E402

CALIBRATION = API_DIR / "tests" / "data" / "chat_calibration.json"
FACTS_FIXTURE = API_DIR / "tests" / "data" / "sample_facts.json"


def best_threshold(ins: list[float], outs: list[float]) -> float:
    """Midpoint of the gap if the sets separate; otherwise the cut with the fewest mistakes."""
    if min(ins) > max(outs):
        return round((min(ins) + max(outs)) / 2, 2)
    cuts = sorted(set(ins + outs))
    errors = lambda t: sum(x < t for x in ins) + sum(x >= t for x in outs)  # noqa: E731
    return round(min(cuts, key=errors), 2)


def replace_line(path: Path, key: str, value: str, comment: str | None = None) -> None:
    text = path.read_text(encoding="utf-8")
    eol = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(eol)
    out, done = [], False
    for line in lines:
        if comment and line.startswith("# CHAT_MIN_SIM calibrated"):
            continue  # drop an older calibration comment
        if re.match(rf"^{key}=", line):
            if comment:
                out.append(comment)
            out.append(f"{key}={value}")
            done = True
        else:
            out.append(line)
    if not done:
        out[-1:-1] = ([comment] if comment else []) + [f"{key}={value}"]
    path.write_text(eol.join(out), encoding="utf-8")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    document_id = uuid.UUID(sys.argv[1])
    data = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    with SessionLocal() as db:
        def best(q: str) -> float:
            hits = retrieve(db, document_id, q, 1)
            return hits[0].similarity if hits else 0.0

        ins = [best(q) for q in data["in_scope"]]
        outs = [best(q) for q in data["out_of_scope"]]
        for label, qs, scores in (("in-scope", data["in_scope"], ins), ("out-of-scope", data["out_of_scope"], outs)):
            print(label)
            for q, s in zip(qs, scores):
                print(f"  {s:.3f}  {q}")
        threshold = best_threshold(ins, outs)
        mistakes = sum(x < threshold for x in ins) + sum(x >= threshold for x in outs)
        print(f"in-scope {min(ins):.3f}–{max(ins):.3f}, out-of-scope {min(outs):.3f}–{max(outs):.3f}")
        print(f"threshold {threshold:.2f}, mistakes {mistakes}/{len(ins) + len(outs)}")

        if "--write" in sys.argv:
            comment = (
                f"# CHAT_MIN_SIM calibrated on samples/sample.pdf: in-scope best similarity {min(ins):.2f}–{max(ins):.2f}, "
                f"out-of-scope {min(outs):.2f}–{max(outs):.2f}"
            )
            replace_line(ROOT_DIR / ".env", "CHAT_MIN_SIM", f"{threshold:.2f}")
            replace_line(ROOT_DIR / ".env.example", "CHAT_MIN_SIM", f"{threshold:.2f}", comment)
            headings = {s.id: s.heading for s in db.scalars(select(Section).where(Section.document_id == document_id))}
            facts = db.scalars(select(Fact).where(Fact.document_id == document_id).order_by(Fact.idx)).all()
            FACTS_FIXTURE.write_text(
                json.dumps(
                    [{"idx": f.idx, "text": f.text, "concept": f.concept, "page": f.page, "section": headings[f.section_id]} for f in facts],
                    ensure_ascii=False,
                    indent=0,
                )
                + "\n",
                encoding="utf-8",
            )
            print(f"wrote CHAT_MIN_SIM={threshold:.2f} to .env and .env.example; {len(facts)} facts to {FACTS_FIXTURE.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
