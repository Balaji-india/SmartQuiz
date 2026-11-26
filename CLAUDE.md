# SmartQuiz — project memory for Claude Code

Claude Code reads this file at the start of every session. Keep it short. Change it with `/memory` when a rule changes.
The Review 1 slice (P00–P11) is built and in the repo as of 2026-11-04. Current work: Review 2 / final (R00–R12 in
`docs/PLAN.md`, shapes in `docs/SPEC.md` section 9). Final submission (code, mini project report, slides): Monday 2026-11-30.

## What we are building
SmartQuiz turns an uploaded PDF or text file into a closed-book "textbook" of numbered facts, then generates cited
quizzes from it. Unique claim: **Proof of Grounding** — every question is derived from specific facts of a specific
document, passes verification gates, and its quiz hash is committed on chain before the learner starts.
Industry partner: Dopove Private Limited. Team (CMRIT): Deepesh, Balaji, Aravindh. Since 2026-11-26 every command runs in one
Claude Code session on Deepesh's Fedora Linux laptop (Review 1 ran on Balaji's Windows laptop). The team members are also
the educators (co-signing, deferred grading, revocation).

Read these before any task:
- `docs/PLAN.md` — Review 2 plan (R00–R12, day plan, final demo, cut list) and the completed Review 1 plan
- `docs/SPEC.md` — schema, API contract, hashing, gate prompts (the source of truth for shapes)
- `docs/STATUS.md` — what is done so far (append to it after every task)
- `docs/SUMMARY.md` — one-page overview of the project state (research basis, what is built, results, open issues)

## Repo layout (monorepo)
```
api/         FastAPI (Python 3.11+), sync SQLAlchemy 2, Alembic, pytest
  app/main.py, app/config.py, app/db.py, app/models/, app/routers/
  app/llm/provider.py      <- ONLY place that calls an LLM
  app/ingest/              <- Textbook Mode
  app/quiz/                <- selection, generation, gates, metrics
  app/chat/                <- closed-book chat
  app/chain/               <- merkle.py, quizhash.py, service.py (web3.py)
  scripts/                 <- every Python script (check_llm, merkle_fixture, seed_demo)
  tests/
web/         Next.js (App Router, TypeScript, Tailwind)
contracts/   Hardhat 2.29.1 (exact pin) + OpenZeppelin v5, Solidity ^0.8.20 (SmartQuizRegistry + SmartQuizCredentials)
docs/        plan, spec, research, status, demo
scripts/     dev.ps1 (Windows) and dev.sh (Linux) only (db, migrate, api, web, test; dev.sh also setup)
samples/     sample.pdf (our real course chapter, 15–30 pages) + fixtures
docker-compose.yml   Postgres 16 with pgvector
```

## Stack decisions (do not change without the team)
- LLM: FREE tiers only, both called through OpenAI-compatible endpoints with the `openai` Python SDK in `app/llm/provider.py`
  - generator: Groq free tier, OpenAI family (`GROQ_API_KEY`, `GENERATOR_BASE_URL`, `LLM_GENERATOR_MODEL`). Gemini stays configurable as an optional generator (`GEMINI_API_KEY`), but its free tier can be as low as 20 requests/day.
  - checker (gates): Groq free tier, Qwen family (`GROQ_API_KEY`, `CHECKER_BASE_URL`, `LLM_CHECKER_MODEL`) — a different model family from the generator on purpose. Independence is by model family, not vendor. A same-family checker is an emergency-only fallback and must show on the metrics page (SPEC section 4).
  - Model names change often: never hard-code them; read them from .env. `provider.py` throttles to the RPM / TPM values per role, retries per-minute 429s with backoff, and counts requests against GENERATOR_REQUESTS_PER_DAY / CHECKER_REQUESTS_PER_DAY. A daily limit stops immediately with no retries. It caches by sha256(role + model + system + user + attempt) in a sqlite file in api/.cache, so a regeneration (higher attempt number) gets a new response and re-runs cost nothing. FAKE responses are never cached.
  - Upload only course notes to LLM providers, never personal data; free tiers may use inputs to improve their products.
- Embeddings: local `BAAI/bge-small-en-v1.5` (sentence-transformers), 384 dims, pgvector
- Chain: Polygon Amoy testnet (chain id 80002), one server issuer wallet sends every tx, learners need no wallet (they may add
  one for badges; otherwise a custodial address). Review 2 adds `SmartQuizCredentials.sol` next to the unchanged registry;
  educator actions carry an EIP-712 signature from a separate educator wallet
- Auth: simple email + password (argon2-cffi), JWT bearer tokens
- Database access: sync SQLAlchemy (async psycopg conflicts with the default Windows event loop)

## Closed-book rules (never break these)
1. Every chat answer, question, correct answer, distractor (Review 2), revision-note sentence and short-answer grade carries
   fact idx values from the `facts` table.
2. A fact is stored only if its quote is found in the source text (exact, or rapidfuzz partial ratio >= 90); keep page + char offsets. It must also pass `gate0_fact`: the checker model confirms the quote supports the fact (SPEC section 3).
3. Chat answers only from retrieved facts. If best similarity < `CHAT_MIN_SIM`, abstain:
   "This isn't covered in your material" + the two nearest section headings.
4. Generation receives only target facts chosen per SPEC section 4: unused first (not the target of any earlier quiz of this user + document, even before an attempt), then last answered wrong.
   Coverage tracks the target fact only (`questions.target_fact_idx`). fingerprint per SPEC section 4, unique per user + document.
   Backup: drop a question whose stem embedding has cosine >= 0.85 with an earlier stem for that user + document.
   Review mode (SPEC 9.6) is separate: it takes only FSRS cards that are due; practice selection above is unchanged.
5. Gates (checker model only): Gate 1 grounding, Gate 2 distractor falsity (MCQ), Gate 3 solvability, Gate 4 document
   dependence (MCQ) (see SPEC 4 and 9). One generator call writes all target questions; Gate 1, 2 or 3 failures share one
   batched regeneration call, then drop. Log every gate result to `generation_log`.
   Short answers are graded by the checker only from the question's cited facts; confidence < 70 goes to an educator.
6. Only hashes (and wallet addresses) go on chain. Never document text, concept text, answers, names or emails.
7. Sources stay hidden until submit: `QuizOut` omits `fact_idxs`, distractors, misconceptions and model answers, and Source
   chips stay hidden until the attempt is submitted; `/verify/question` answers 409 until then.

## Hashing (must match Solidity exactly; exact formats in SPEC section 8)
- text_hash = keccak256(utf-8 fact text)
- leaf = keccak256(bytes.concat(keccak256(abi.encode(uint256 idx, bytes32 text_hash))))  (OpenZeppelin leaf format)
- tree: leaves in our idx order (not sorted first), internal nodes = keccak256 of the sorted pair, odd last node promoted unchanged; root → `documents.fact_root`
- doc_id (on chain) = keccak256(utf-8 document UUID string)
- quiz_hash v1 = keccak256(canonical JSON, sorted keys, no spaces, of {"questions":[{stem, options, answer_index, fact_idxs, gate_results}] ordered by position, "salt": lowercase hex})
- quiz_hash v2 (Review 2 quizzes, `quizzes.hash_version = 2`) adds "v":2 and per question qtype, distractors, model_answer (SPEC 9.2). Review 1 quizzes must still verify as v1.
- attempt hashes, result batches and badge hashes: SPEC 9.9

## Commands
Review 2 runs on Deepesh's Fedora laptop: use the Linux block. The Windows block is kept for Balaji's laptop.
Always quote paths (a repo path may contain a space). Never rely on venv activation or `make`.

### Linux (bash, Fedora) — venv is Python 3.12 via uv
Shortcut: `./scripts/dev.sh <setup|db|migrate|api|web|test>` (sets PYTHONUTF8=1)
- DB: `docker compose up -d db`
- API: `cd api && PYTHONUTF8=1 .venv/bin/python -m uvicorn app.main:app --reload --port 8000`
- Web: `cd web && npm run dev` (port 3000)
- Contracts: `cd contracts && npx hardhat test` (only inside `contracts/`, or npx fetches Hardhat 3) · deploy: `npx hardhat run scripts/deploy.ts --network amoy`
- API tests: `cd api && PYTHONUTF8=1 .venv/bin/python -m pytest -q`
- Use `.venv/bin/python`, never the system `python3` (3.14 on Fedora, too new for this stack).

### Windows (PowerShell 5.1: no `&&`)
Shortcut: `powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 <db|migrate|api|web|test>` (sets PYTHONUTF8=1)
- DB: `docker compose up -d db`
- API: `Set-Location api; $env:PYTHONUTF8=1; .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000`
- Web: `Set-Location web; npm.cmd run dev` (port 3000, `NEXT_PUBLIC_API_URL=http://localhost:8000`)
- Contracts: `Set-Location contracts; npx.cmd hardhat test` · deploy: `npx.cmd hardhat run scripts/deploy.ts --network amoy`
- API tests: `Set-Location api; $env:PYTHONUTF8=1; .\.venv\Scripts\python.exe -m pytest -q`
- On Windows never use `python3` or bare `npx`/`npm` (use `npx.cmd`/`npm.cmd`).

On both: open text files with explicit `encoding="utf-8"`.

## Env (never commit `.env`; keep `.env.example` current)
GROQ_API_KEY, GENERATOR_BASE_URL, LLM_GENERATOR_MODEL, CHECKER_BASE_URL, LLM_CHECKER_MODEL, GEMINI_API_KEY (optional),
GENERATOR_RPM, GENERATOR_TPM, GENERATOR_REQUESTS_PER_DAY, CHECKER_RPM, CHECKER_TPM, CHECKER_REQUESTS_PER_DAY, DATABASE_URL, JWT_SECRET, AMOY_RPC_URL,
ISSUER_PRIVATE_KEY (testnet only), REGISTRY_ADDRESS, CREDENTIALS_ADDRESS, EDUCATOR_PRIVATE_KEY (testnet only), CUSTODY_SECRET,
CHAIN_OPTIONAL, CHAT_MIN_SIM, NEXT_PUBLIC_API_URL
Settings load the ROOT `.env` by absolute path with `extra="ignore"`, whatever the working directory.
`CHAIN_OPTIONAL=false` for the live demo, so chain failures cannot pass silently.

## Working style
- Before changing more than one file, show a short plan and wait for "go".
- Write tests with the code; run them before saying a task is done.
- Small git commits per feature with clear messages, made by Deepesh: Claude suggests the message and never commits or pushes.
- After every task, append to `docs/STATUS.md` (what was done, how to run it, test result, open issues).
- If a requirement is unclear, ask. Never invent API shapes — follow `docs/SPEC.md`, and update SPEC if a shape must change.
- Prompts may contain labels like `/context:` or `/constraints:`. They are section headings, not commands.
