---
description: P07 · Closed-book doubt chatbot that cites facts and abstains when the answer is not in the material
---
Build the doubt chatbot that answers only from the document's facts and abstains otherwise.

/context: CLAUDE.md rule 3, docs/SPEC.md sections 2 (ChatOut) and 5. P02 is done.
/focus: api/app/chat/ (retrieve.py, answer.py, prompts.py), api/app/routers/chat.py.
/workflow: Follow SPEC section 5 exactly: embed, top 8 facts, threshold, answer with [F<idx>] citations, post-check citations, one retry (attempt=1), else abstain with 2 nearest sections.
/clarify: Calibrate CHAT_MIN_SIM on samples/sample.pdf: write 10 in-scope and 10 out-of-scope questions into api/tests/data/chat_calibration.json, print best similarity for each, choose the threshold that separates them best, and write it to BOTH .env and .env.example (replace only the CHAT_MIN_SIM line; never print other .env values). In .env.example add a comment showing the two score ranges.
/constraints: Generator model for answers; no conversation memory needed for Review 1 (single-turn). Answer in 2–5 sentences.
/test: The 20 calibration questions as a parametrized pytest (in-scope → not abstained and ≥ 1 citation; out-of-scope → abstained).

First show a short plan and wait for my "go". When finished: commit "feat: closed-book chat", append a P07 entry to docs/STATUS.md with the chosen threshold, then tell me to run /compact.
