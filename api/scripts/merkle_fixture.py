"""Writes contracts/test/fixtures/merkle.json from app/chain/merkle.py (the only Merkle implementation).

The Hardhat test registers this root and checks every proof with the contract's verifyFact,
which proves Python and Solidity agree. 7 facts, so the last leaf is promoted at the first level.

Run from api/:  .venv/bin/python scripts/merkle_fixture.py   (Windows: .\\.venv\\Scripts\\python.exe ...)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.chain import merkle  # noqa: E402
from app.config import ROOT_DIR  # noqa: E402

OUT = ROOT_DIR / "contracts" / "test" / "fixtures" / "merkle.json"

FACTS = [
    "Round-robin scheduling gives each process a fixed time quantum.",
    "A process control block stores the state of a process.",
    "Paging divides physical memory into fixed-size frames.",
    "A deadlock requires mutual exclusion, hold and wait, no preemption and circular wait.",
    "Thrashing happens when a system spends more time paging than executing.",
    "A semaphore is an integer variable accessed only through wait and signal.",
    "Ünïcode facts are hashed as UTF-8 bytes without normalisation.",
]


def main() -> None:
    text_hashes = [merkle.text_hash(t) for t in FACTS]
    leaves = [merkle.leaf(i, h) for i, h in enumerate(text_hashes)]
    root = merkle.build_tree(leaves)
    proofs = [merkle.proof(leaves, i) for i in range(len(leaves))]
    assert all(merkle.verify(root, leaves[i], proofs[i]) for i in range(len(leaves)))
    data = {
        "doc_uuid": "00000000-0000-4000-8000-000000000007",
        "root": root,
        "facts": [
            {"idx": i, "text": t, "text_hash": h, "leaf": l, "proof": p}
            for i, (t, h, l, p) in enumerate(zip(FACTS, text_hashes, leaves, proofs))
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT} root={root}")


if __name__ == "__main__":
    main()
