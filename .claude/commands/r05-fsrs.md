---
description: R05 · FSRS review cards and review quiz mode
---
Schedule spaced review per fact with FSRS and add a review quiz made only of due facts.

/context: CLAUDE.md rule 4 (practice selection unchanged); docs/SPEC.md sections 4 and 9.6. Code: api/app/quiz/select.py, job.py, routers/quizzes.py, the R03 "on final grade" hook.
/workflow:
1. Add the `fsrs` package (pinned). Migration: review_cards, quizzes.mode default 'practice'.
2. learn/review.py: update card on every final grade (Again / Hard / Good per SPEC), store Card.to_dict() and due.
3. select.py: review mode = due cards only, most overdue first, max 2 per concept, Bloom ladder; 409 with next_due when none. Practice mode untouched.
4. POST /quizzes mode; GET /documents/{id}/review; backfill cards from existing attempts (extend the R03 backfill script).
/test: rating mapping, due ordering, 409 shape, practice selection unchanged (existing selection tests stay green), review quizzes still pass all gates and commit on chain (FAKE chain).
/stats: After answering one quiz with wrong answers: due_now, next_due, and a generated review quiz's targets ⊆ due facts.

First show a short plan and wait for my "go". When finished: run the API tests (and any other suite you touched), append an entry to docs/STATUS.md (done, how to run, test result, open issues), suggest a commit message for Deepesh (do not commit or push), then tell me to run /compact.
