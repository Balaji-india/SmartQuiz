---
description: R02 · Bloom's ladder (remember → understand → apply → analyze), retest climbing, Bloom check in Gate 1
---
Retests climb Bloom's ladder, and the checker labels each question's level.

/context: docs/SPEC.md sections 4 and 9.3. Code: api/app/quiz/select.py (BLOOM_LEVELS, retest level), generate.py, prompts.py, gates.py, metrics.py.
/workflow:
1. BLOOM_LEVELS gains apply and analyze; prompt explains each level in one line, all answerable from the facts alone.
2. Retest rule per SPEC 9.3 (up after correct, down after wrong, neighbour if capped), so the fingerprint differs.
3. Gate 1 output adds "bloom"; store in gate_results.gate1.bloom; log a mismatch (no drop).
4. MetricsOut: bloom_levels, bloom_mismatches.
/test: ladder transitions (incl. caps and floor), fingerprint differs on retest, gate1 bloom parsing with a missing field, metrics counts. Hash v2 includes gate_results, so update fixtures, not formats.
/stats: Real run: answer a quiz with some right and some wrong, generate the next quiz until retests appear (or force with a small test document); print levels before → after.

First show a short plan and wait for my "go". When finished: run the API tests (and any other suite you touched), append an entry to docs/STATUS.md (done, how to run, test result, open issues), suggest a commit message for Deepesh (do not commit or push), then tell me to run /compact.
