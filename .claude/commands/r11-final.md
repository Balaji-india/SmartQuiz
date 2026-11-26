---
description: R11 · Final integration on Fedora — end-to-end test, new seed, rehearsals of all 12 demo steps, docs
---
Run the full final demo end to end on our real PDF and fix whatever breaks.

/context: docs/PLAN.md (final demo steps 1–12, cut list), docs/STATUS.md, docs/SUMMARY.md.
/checklist: Fresh database on this Fedora laptop, CHAIN_OPTIONAL=false, real Groq models and Amoy (or a local node with CHAIN_OPTIONAL=true if Amoy fails, and say so). Run steps 1–12 in order; each pass/fail with evidence (IDs, tx links, numbers). Confirm same_family_checker_used is false.
/debug: Smallest fix per failure, no refactors.
/test: extend api/tests/test_e2e.py with distractor gate, mastery, revision, review mode, short answer + educator grade, anchor, badge, co-sign, revoke, verify attempt/badge.
/automate: extend api/scripts/seed_demo.py: demo learner + educator accounts (make_educator), document ingested and co-signed, quiz 1 ready and unstarted, a second learner state with one attempt (so mastery and review have data); print every ID and link we paste on stage.
/stats: Final metrics: facts, coverage, gate rejections per gate, avg dependence (Review 1 vs Review 2), repeat rate, chat calibration, timings, requests per quiz, POL spent.
/report: README "Run the demo" (Linux), docs/SUMMARY.md updated for the final state, docs/STATUS.md final summary mapped to the cut list (done / partial / not done).

First show a short plan and wait for my "go". When finished: run the API tests (and any other suite you touched), append an entry to docs/STATUS.md (done, how to run, test result, open issues), suggest a commit message for Deepesh (do not commit or push), then tell me to run /compact.
