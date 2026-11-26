---
description: R04 · Revision notes for weak concepts, every sentence cited and checked by Gate 1
---
Write short revision notes for the weakest concepts, using only their facts, with every sentence cited and verified.

/context: CLAUDE.md rules 1 and 5; docs/SPEC.md section 9.5. Code: api/app/learn/, api/app/quiz/prompts.py (Gate 1 prompt reuse), provider.py.
/workflow:
1. Migration: revision_notes.
2. learn/revision.py: one generator call for all requested concepts (only their facts), validate fact_idxs ⊆ concept facts, one batched Gate 1 call per sentence (gate revision_gate1 in generation_log), drop and count unsupported sentences.
3. POST and GET /documents/{id}/revision per SPEC 9.5 (409 when no weak/learning concept).
/constraints: 2 requests per generation (1 generator + 1 checker, + at most 1 retry each). Notes are 3–6 sentences per concept, plain language.
/test: FAKE LLM: fact_idxs outside the concept dropped, gate1 drop counted, 409 path, GET returns latest per concept, owner-only.
/stats: Real run for the 3 weakest concepts: sentences kept/dropped, requests used.

First show a short plan and wait for my "go". When finished: run the API tests (and any other suite you touched), append an entry to docs/STATUS.md (done, how to run, test result, open issues), suggest a commit message for Deepesh (do not commit or push), then tell me to run /compact.
