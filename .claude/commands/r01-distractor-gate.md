---
description: R01 · Gate 2 distractor falsity, distractor fact idxs + misconceptions, quiz hash v2
---
Every distractor must be provably false from the notes, and carry the misconception it targets.

/context: CLAUDE.md rules 1, 5, 7 and Hashing; docs/SPEC.md sections 4, 8 and 9.2. Code: api/app/quiz/ (generate.py, gates.py, prompts.py, job.py, metrics.py), api/app/chain/quizhash.py, api/app/routers/quizzes.py, api/app/routers/verify.py.
/workflow:
1. Migration 0003: questions.distractors jsonb default '[]', quizzes.hash_version int default 1 (existing rows stay 1).
2. Generator prompt + validation: one distractors entry per wrong option (fact_idxs ⊆ target + context, non-empty; misconception ≤ 12 words from the notes' terms). Remap `option` after the shuffle.
3. gates.py: Gate 2 as one batched checker call in parallel with Gates 1 and 3; pass only if every verdict is FALSE; missing ids retried once with attempt=1, then fail closed. Gate 1/2/3 failures share the ONE regeneration call. Log gate2 rows.
4. quizhash.py: v2 canonical object per SPEC 9.2; new quizzes use v2; /verify/quiz picks the version from the quiz.
5. AttemptResult misconceptions with sources after submit; never before (QuizOut unchanged except nothing new leaks). Metrics: gate2 in rejected_by_gate and top_reasons.
/constraints: Keep requests per quiz at: 1 generator call + at most 1 regeneration; checker calls only batched. Strengthen the distractor prompt (plausible, specific, from the notes) since this is the main lever for document dependence.
/test: FAKE LLM: validation of distractors, remap after shuffle, gate2 pass/fail/missing, shared regeneration (still ≤ 2 generator calls), hash v1 unchanged for a stored v1 quiz fixture, v2 deterministic, verify picks the version, nothing leaks before submit.
/stats: Real run: three 10-question quizzes on the sample for one user. Print per quiz: candidates, accepted, rejections per gate (gate2 reasons), avg dependence, requests used, seconds. Goal avg dependence ≥ 0.35; report honestly if not met. If gate2 rejects > 40%, stop and show me examples before loosening anything.

First show a short plan and wait for my "go". When finished: run the API tests (and any other suite you touched), append an entry to docs/STATUS.md (done, how to run, test result, open issues), suggest a commit message for Deepesh (do not commit or push), then tell me to run /compact.
