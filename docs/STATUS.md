# SmartQuiz — Status log

Every slash command appends an entry here. `/status` adds a summary block under "Updates".

## Updates
_(none yet)_

## Entries
### Setup
- Starter pack created on 2026-11-02: CLAUDE.md, docs (PLAN, SPEC, RESEARCH, STATUS, SLIDES-PROMPT), .claude/commands (p00–p11, status, fix, next).
- No application code yet.

### Doc fixes before P00 (2026-11-02)
- **Done:** docs and command files only; nothing scaffolded or installed. `.env` was not edited.
- **Single operator:** Balaji runs p00 → p11 in one session on Windows. Deepesh and Aravindh review, test and present. Web uses the real API; mocks only in tests. GitHub push is a backup at the end of P00 and P11.
- **Spec changes:** `fact_ids` → `fact_idxs`; added `questions.target_fact_idx`, `quizzes.status`, `quizzes.started_at`, `generation_log.candidate_id`, `generation_log.same_family_fallback`, `chain_status`, `/auth/me`, `/quizzes/{id}/progress`; exact fingerprint, Merkle and quiz_hash formats in SPEC section 8. `merkle.py` moves to P00; LLM cache key includes the attempt number; FAKE responses are never cached.
- **Added beyond the requested list (needed to make the decisions work):** `/verify/question` returns 409 until the quiz is submitted; `started_at` and `POST /quizzes/{id}/start` so generation and the start screen do not count against the timer; retests ask for the other bloom level so the fingerprint can differ; null (not false) on verify when the chain is offline; `candidate_id` so candidates can be counted.
- **Interpretation:** "used" facts in selection means earlier target facts, not context facts. A context fact can reappear in a later quiz.
- **Toolchain:** Hardhat 2.29.1 + hardhat-toolbox 6.1.2, exact pins. Hardhat 2.29.1's package source lists Node ^24 as supported (inspected, not yet run); P00 proves it with compile and test.
- **How to run:** nothing to run at the time of this entry.
- **Tests:** none; docs only.
- **Open issues:** `samples/sample.pdf` is missing (needed from P02). Model names in `.env` are untested until `check_llm.py` in P00. `.env` still has `CHAIN_OPTIONAL=true` (set false for the demo) and an unused `NEXT_PUBLIC_USE_MOCK` line (harmless). During a quiz a learner can still open the textbook or chat in another tab; not addressed in Review 1.

### P00 bootstrap (2026-11-02)
- **Done:** monorepo with api (FastAPI skeleton, `/health`, CORS, root `.env` settings, sync DB), `app/llm/provider.py`, `app/chain/merkle.py`, `api/scripts/check_llm.py`; web (Next.js 16.4.4, `lib/api.ts`, home page calling `/health`); contracts (Hardhat 2.29.1, toolbox 6.1.2, OpenZeppelin 5.6.1, placeholder contract); `docker-compose.yml`; `scripts/dev.ps1`.
- **How to run:** `powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 <db|api|web|test>`. Setup steps are in README "Getting started".
- **Test results:** pytest 32 passed (merkle + provider). `/health` → `{"ok":true,"db":true}`, CORS allows localhost:3000. `check_llm.py` → both models found, both JSON requests OK. `npm.cmd run build` passed. `hardhat compile` and `hardhat test` (1 passing) passed on Node 24.14.0. `dev.ps1 test` and `dev.ps1 db` exit 0.
- **PyTorch:** CPU-only build installed first (2.15.0+cpu, CUDA unavailable). `pip check` clean. `requirements.txt` also lists the CPU index.
- **Added beyond the prompt:** a one-test Hardhat placeholder so `hardhat test` runs something.
- **Issues:** the home page was built but not opened in a browser, so its live `/health` display is unconfirmed (P09 covers real screens). npm printed deprecation warnings for Hardhat's dependencies and audit notices for web; neither was reviewed or changed. `samples/sample.pdf` is still missing (needed for P02).

### P01 schema and auth (2026-11-02)
- **Done:** SQLAlchemy models for all 9 SPEC tables (`api/app/models/tables.py`); one Alembic migration (`vector` extension, all tables, HNSW cosine index on `facts.embedding`, unique `(document_id, idx)`, index on `questions.fingerprint`); `POST /auth/signup`, `POST /auth/login`, `GET /auth/me`; argon2 passwords; JWT HS256 with 7-day expiry; `get_current_user`.
- **How to run:** `powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 migrate` (new target), then `dev.ps1 api`. Tests: `dev.ps1 test`, or pytest in `api/`.
- **Test results:** pytest 42 passed (10 new, 32 from P00), run against `smartquiz_test`, which is recreated each session. Covers upgrade and downgrade, models matching the migration, signup → login → `/auth/me`, wrong password and unknown email → the same 401, and bad tokens → 401. Hardhat and the web build were not re-run because nothing in them changed.
- **Live check on the dev database:** migration applied; signup, login and `/auth/me` worked and a wrong password returned 401. The `a@b.com` test user was then deleted, so `users` has 0 rows.
- **Decisions SPEC did not cover:** duplicate email → 409; emails stored in lowercase; password 8–128 characters, otherwise 422; name 1–200 characters; empty `JWT_SECRET` → 503 instead of signing with an empty key. Added `email-validator`. Added a test that fails if the models and migration drift apart.
- **Spec change:** `documents.fact_root` is nullable until ingestion finishes. Other columns are NOT NULL unless SPEC marks them nullable, so a later command that needs an empty value (for example `questions.dependence_score`) must add a migration.
- **Process change:** Claude now commits at the end of each command, under Balaji's git identity with no Claude attribution. Balaji pushes.
- **Issues:** in PowerShell 5.1, `http://localhost:8000` takes about 2.3 s per request (IPv6 attempt first) while `127.0.0.1` takes 0.01 s. Use a timeout above 3 s, or `127.0.0.1`, when scripting checks. There is no login rate limiting in Review 1. Open items from P00 remain.
