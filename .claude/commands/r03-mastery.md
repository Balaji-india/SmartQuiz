---
description: R03 · BKT mastery per user + concept, gap report endpoint
---
Track mastery per concept and show the learner exactly where the gaps are.

/context: docs/SPEC.md section 9.4. Code: api/app/routers/quizzes.py (attempt scoring, coverage update), new api/app/learn/mastery.py, new api/app/routers/learn.py.
/workflow:
1. Migration: mastery table per SPEC 9.4.
2. learn/mastery.py: pure BKT update function (params from SPEC as constants), applied per final grade to the target fact's concept, in the same transaction as coverage. One shared "on final grade" hook (mastery now; FSRS in R05 and short answers in R06 plug into it).
3. GET /documents/{id}/mastery → MasteryOut (all concepts of the document, untested included, ordered per SPEC; badge_id null until R08).
4. Backfill script api/scripts/backfill_mastery.py replays existing attempts in order (idempotent).
/test: BKT numbers against hand-computed values, status thresholds, ordering, untested concepts present, owner-only access, backfill idempotent.
/stats: On the dev DB after backfill: summary counts and the 5 weakest concepts.

First show a short plan and wait for my "go". When finished: run the API tests (and any other suite you touched), append an entry to docs/STATUS.md (done, how to run, test result, open issues), suggest a commit message for Deepesh (do not commit or push), then tell me to run /compact.
