---
description: P06 · Commit quiz hash on chain before the attempt; timed attempt scoring and fact coverage updates
---
Commit each quiz's hash on chain before the learner sees it, and score attempts while updating fact coverage.

/context: CLAUDE.md Hashing (quiz_hash) and rule 7, docs/SPEC.md sections 2 (QuizOut, AttemptResult), 4, 6 and 8. P04 and P05 are done.
/workflow:
1. Implement the P05 hook `commit_quiz_onchain(quiz)` at the end of the background job (progress stage `committing`): random 16-byte salt, canonical JSON exactly as SPEC section 8, quiz_hash, ChainService.commit_quiz(keccak(quiz UUID), doc_id, quiz_hash), save salt/quiz_hash/commit_tx. Put the canonical-JSON + hash function in api/app/chain/quizhash.py so P08 reuses it.
2. The quiz becomes `ready` only after the commit (or the CHAIN_OPTIONAL=true fallback, with `chain_status: "offline"`). With CHAIN_OPTIONAL=false, a failed commit sets status `failed`. Questions are never returned while status is `generating`.
3. POST /quizzes/{id}/start (from P05) refuses with 409 unless status is `ready`. POST /quizzes/{id}/attempts: 409 unless status is `ready` and the quiz is started; reject if `now − started_at` exceeds time_limit_sec + 30 s grace; score; build AttemptResult with sources (fact text, page, section, from all cited facts) and weak_concepts (target-fact concepts of wrong answers); upsert fact_coverage for the target fact only (times_tested+1, last_correct, last_bloom), resolving target_fact_idx to facts.id.
4. One attempt per quiz per user for Review 1. After an attempt, QuizOut includes fact_idxs.
/constraints: If commit_tx is null and CHAIN_OPTIONAL is false, refuse attempts with a clear 409 message.
/test: Changing any stored hashed question field after commit changes the recomputed hash; the hash follows position order and the exact format in SPEC section 8; the commit happens before status `ready`; generation time and reading the quiz before start do not count against the timer; scoring and coverage updates are correct; context facts get no coverage row; fact_idxs are absent before an attempt and present after; once untested facts are exhausted, selection prefers wrongly answered facts over the rest.

First show a short plan and wait for my "go". When finished: commit "feat: quiz commit and attempts", append a P06 entry to docs/STATUS.md with a commit tx link, then tell me to run /compact.
