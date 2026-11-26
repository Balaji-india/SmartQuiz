---
description: R00 · Review 2 base — code + security review fixes, GET attempt, pinned packages, npm audit, gate0 headings, issuer wallet check
---
Make the Review 1 code a clean base before Review 2 features land.

/context: CLAUDE.md, docs/PLAN.md (Review 2), docs/SPEC.md sections 2 and 9.1, docs/STATUS.md open issues.
/workflow:
1. Tell me to run `/code-review high` and `/security-review` (I run them; you cannot start them). Fix every confirmed finding with the smallest change; list skipped ones with a reason.
2. `GET /attempts/{attempt_id}` → AttemptResult (owner only, 404 otherwise); `QuizOut.attempt_id`. The web results view loads from the API; sessionStorage is only a fallback.
3. `gate0_fact` items add `"section"` (heading path), per SPEC 9.1. Do not re-ingest the sample unless I ask (it costs requests).
4. Pin Python packages: `api/requirements.txt` keeps the CPU torch index line, every package gets `==` from the working venv (`.venv/bin/python -m pip freeze` for the listed names only).
5. `npm audit` in web/ and contracts/: apply only non-breaking fixes (`npm audit fix`, never `--force`); list what remains and why it is dev-only or safe.
6. Issuer wallet (already moved on 2026-11-26, see STATUS "New issuer wallet"): only confirm that ISSUER_PRIVATE_KEY derives to 0x6fa045726eF3F0d84eb100e159517930C249b665, that it equals the registry `owner()`, and print the Amoy balance. Never print keys. Give `scripts/deploy.ts` the same Amoy fee floor as `scripts/transfer-owner.ts` (tip ≥ 30 gwei).
/constraints: Linux commands only (CLAUDE.md). No shape changes beyond SPEC 9.1. No refactors.
/test: tests for GET /attempts (owner, other user 404, before submit 404), QuizOut.attempt_id, gate0 section field in the prompt payload (FAKE LLM). Full pytest, Hardhat tests, `cd web && npm run build && npm run lint`.

First show a short plan and wait for my "go". When finished: run the API tests (and any other suite you touched), append an entry to docs/STATUS.md (done, how to run, test result, open issues), suggest a commit message for Deepesh (do not commit or push), then tell me to run /compact.
