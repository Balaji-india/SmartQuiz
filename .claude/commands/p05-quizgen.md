---
description: P05 · Coverage-based quiz generation with verification gates 1, 3, 4, duplicate blocking and metrics
---
Build quiz generation that picks facts by coverage, writes MCQs, and only keeps questions that pass the gates.

/context: CLAUDE.md rules 4–5 and 7, docs/SPEC.md sections 2 (/quizzes, /metrics), 4 and 8. P02 is done.
/focus: api/app/quiz/ (select.py, generate.py, gates.py, dedup.py, metrics.py, prompts.py), api/app/routers/quizzes.py, api/app/routers/metrics.py.
/workflow:
1. select.py: choose target facts per SPEC section 4 (unused, including targets of earlier non-failed quizzes with no attempt → last wrong → used but never answered → oldest tested; proportional across sections; ≤ 2 per concept).
2. generate.py: generator model writes one MCQ per target as JSON; validate shape (4 distinct options, answer_index 0–3, fact_idxs all exist in this document and include the target). Save target_fact_idx separately and store fact_idxs sorted. On a retest, ask for the other bloom_level (SPEC section 4).
3. gates.py: gate1 grounding, gate3 solvability (shuffle options, map the checker's choice back), gate4 blind dependence (choice + integer confidence). Checker model only. JSON outputs with a short reason, in the exact `gate_results` shape from SPEC section 4.
4. dedup.py: fingerprint per SPEC section 8, then stem-embedding cosine ≥ 0.85 against earlier questions of this user + document.
5. Retry policy: gate1/gate3 fail → regenerate same target, passing attempt=1 then attempt=2 to provider.py so the cache returns a new response → drop and take the next fact. Stop when N accepted or facts run out.
6. Log every gate and duplicate outcome to generation_log, with a candidate_id per generator output and `same_family_fallback` when the CHECKER_BASE_URL host equals the GENERATOR_BASE_URL host.
7. POST /quizzes creates the quiz with status `generating`, starts a background job and returns QuizOut immediately. The job ends by calling a hook `commit_quiz_onchain(quiz)` (P06 implements it), then sets status `ready`, or `failed` if it cannot produce questions. GET /quizzes/{id}/progress returns {accepted, rejected, target, stage}. POST /quizzes/{id}/start sets started_at once and returns the questions; GET /quizzes/{id} returns "questions":[] until then.
8. QuizOut never contains answer_index or target_fact_idx, and contains fact_idxs only after an attempt exists (P06 creates attempts; until then always omit).
9. GET /metrics/{document_id} returns MetricsOut, including repeat_rate_between_quizzes (share of target facts reused across this user's quizzes) and same_family_checker_used / same_family_gate_calls.
/constraints: We use free tiers (Gemini generator, Groq checker), so stay inside provider.py's throttling: run calls concurrently but let the provider pace them; expect 2–4 minutes for 10 questions. Keep gate prompts short (only the cited facts) to save Groq tokens. Prompts live in prompts.py.
/examples: Gate1 checker output → {"verdict":"NOT_SUPPORTED","reason":"Fact 214 says fixed quantum; option claims variable quantum"}.
/test:
- FAKE LLM unit tests for selection (including: an earlier quiz with no attempt still counts as used; context facts do not), validation, retry/drop (a retry uses a higher attempt number), fingerprint and cosine duplicates, QuizOut hiding fields, POST returning `generating` immediately, progress shape, fallback logging.
- Integration on sample.pdf (real key): two consecutive 10-question quizzes for one user, no attempts between them, share zero target facts and zero fingerprints; print MetricsOut.
/stats: Print candidates, accepted, rejections per gate, average dependence, and time taken.

First show a short plan and wait for my "go". When finished: commit "feat: verified quiz generation", append a P05 entry to docs/STATUS.md with the stats, then tell me to run /code-review, fix findings, then /compact.
