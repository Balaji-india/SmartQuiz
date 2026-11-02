---
description: P11 · End-to-end integration, demo seed script, final checks for Review 1
---
Run the full Review 1 demo end to end on our real PDF and fix whatever breaks.

/context: docs/PLAN.md (demo steps 1–6 and cut list), docs/STATUS.md (what is finished).
/checklist: With a fresh database and a new user, run demo steps 1–6 in order using the real API, real LLM and Amoy with CHAIN_OPTIONAL=false (or a local node with CHAIN_OPTIONAL=true if Amoy is unavailable, and say so). Report each step as pass/fail with evidence (IDs, tx links, numbers). Confirm same_family_checker_used is false, or report it.
/debug: For each failure, find the root cause and fix it with the smallest change. Do not refactor working code.
/test: api/tests/test_e2e.py: signup → upload samples/sample.pdf → wait for ready → quiz 1 → wait for ready → start → verify question gives 409 → attempt → quiz 2 (zero repeated target facts) → chat in-scope + out-of-scope → verify question true, tampered false → verify quiz match.
/automate: api/scripts/seed_demo.py: creates the demo user, uploads and ingests the PDF, creates one quiz, waits for ready without starting it (so the timer stays untouched for the stage), prints the document ID, quiz ID, explorer links and MetricsOut — everything we paste on stage.
/stats: Print the final metrics and timings (ingestion seconds, quiz generation seconds).
/report: Update README.md with a "Run the demo" section (PowerShell) and docs/STATUS.md with a final Review 1 summary: done, partially done, not done (mapped to the PLAN cut list).

First show a short plan and wait for my "go". When finished: commit "chore: review 1 integration", remind me to push to GitHub as a backup, then tell me to run /code-review and /security-review, then /compact.
