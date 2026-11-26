---
description: R06 · Short-answer questions, checker grading from cited facts, educator deferral
---
Add short-answer questions graded only against their cited facts, with unsure grades deferred to an educator.

/context: CLAUDE.md rules 1, 5, 7; docs/SPEC.md sections 4, 9.2 (hash v2 fields) and 9.7. Code: api/app/quiz/*, routers/quizzes.py, the "on final grade" hook.
/workflow:
1. Migration: questions.qtype, model_answer, dependence_score nullable, attempts.grading_status, answer_grades.
2. Generation: num_short targets get short items; validation; Gate 1 + Gate 3s for short, no Gate 2/4; still one generator call + one regeneration.
3. Attempt: answers may be strings for short questions (≤ 500 chars, validated per position). One batched grading call (grade_short); defer when confidence < 70 or no verdict after one retry; score and hooks only for final grades.
4. AttemptResult/QuizOut fields per SPEC 9.7; metrics avg_dependence over MCQs only; add short_questions and deferred_grades to MetricsOut.
5. The educator grading endpoints come in R08; add an internal function `apply_educator_grade(grade_id, verdict, educator)` now so R08 only wires it.
/test: FAKE LLM: mixed quiz generation, wrong answer types 422, grading verdicts, deferral threshold, pending score, hooks fire only on final, hash v2 with a short question, nothing leaks before submit.
/stats: Real run: one quiz with 2 short questions answered (one good, one vague): verdicts, confidence, deferred count, requests used.

First show a short plan and wait for my "go". When finished: run the API tests (and any other suite you touched), append an entry to docs/STATUS.md (done, how to run, test result, open issues), suggest a commit message for Deepesh (do not commit or push), then tell me to run /compact.
