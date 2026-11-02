# SmartQuiz — project memory for Claude Code

Claude Code reads this file at the start of every session. Keep it short. Change it with `/memory` when a rule changes.
We are building from scratch. There is no existing code.

## What we are building
SmartQuiz turns an uploaded PDF or text file into a closed-book "textbook" of numbered facts, then generates cited
quizzes from it. Unique claim: **Proof of Grounding** — every question is derived from specific facts of a specific
document, passes verification gates, and its quiz hash is committed on chain before the learner starts.
Industry partner: Dopove Private Limited. Team (CMRIT): Balaji runs every command, in one Claude Code session on a Windows laptop. Deepesh and Aravindh review, test and present.

Read these before any task:
- `docs/PLAN.md` — Review 1 scope, command sequence, demo
- `docs/SPEC.md` — schema, API contract, hashing, gate prompts (the source of truth for shapes)
- `docs/STATUS.md` — what is done so far (append to it after every task)

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
contracts/   Hardhat 2.29.1 (exact pin) + OpenZeppelin v5, Solidity ^0.8.20
docs/        plan, spec, research, status, demo
scripts/     dev.ps1 only (db, api, web, test)
samples/     sample.pdf (our real course chapter, 15–30 pages) + fixtures
docker-compose.yml   Postgres 16 with pgvector
```

## Stack decisions (do not change without the team)
- LLM: FREE tiers only, both called through OpenAI-compatible endpoints with the `openai` Python SDK in `app/llm/provider.py`
  - generator: Google Gemini free tier (`GEMINI_API_KEY`, `GENERATOR_BASE_URL`, `LLM_GENERATOR_MODEL`)
  - checker (gates): Groq free tier (`GROQ_API_KEY`, `CHECKER_BASE_URL`, `LLM_CHECKER_MODEL`) — a different model family from the generator on purpose. A same-family checker is an emergency-only fallback and must show on the metrics page (SPEC section 4).
  - Model names change often: never hard-code them; read them from .env. `provider.py` throttles to GENERATOR_RPM / CHECKER_RPM / CHECKER_TPM and retries on HTTP 429 with backoff. It caches by sha256(role + model + system + user + attempt) in a sqlite file in api/.cache, so a regeneration (higher attempt number) gets a new response and re-runs cost nothing. FAKE responses are never cached.
  - Free Gemini tier may use inputs to improve Google products: only upload course notes, never personal data.
- Embeddings: local `BAAI/bge-small-en-v1.5` (sentence-transformers), 384 dims, pgvector
- Chain: Polygon Amoy testnet (chain id 80002), one server issuer wallet signs every tx, learners need no wallet
- Auth: simple email + password (argon2-cffi), JWT bearer tokens
- Database access: sync SQLAlchemy (async psycopg conflicts with the default Windows event loop)

## Closed-book rules (never break these)
1. Every chat answer, question and correct answer carries fact idx values from the `facts` table. Distractors do not need them in Review 1 (Review 2 adds the distractor gate).
2. A fact is stored only if its quote is found in the source text (exact, or rapidfuzz partial ratio >= 90); keep page + char offsets.
3. Chat answers only from retrieved facts. If best similarity < `CHAT_MIN_SIM`, abstain:
   "This isn't covered in your material" + the two nearest section headings.
4. Generation receives only target facts chosen per SPEC section 4: unused first (not the target of any earlier quiz of this user + document, even before an attempt), then last answered wrong.
   Coverage tracks the target fact only (`questions.target_fact_idx`). fingerprint per SPEC section 4, unique per user + document.
   Backup: drop a question whose stem embedding has cosine >= 0.85 with an earlier stem for that user + document.
5. Gates (checker model only): Gate 1 grounding, Gate 3 solvability, Gate 4 document dependence (see SPEC).
   Gate 1 or 3 fails → regenerate up to 2 times, then drop. Log every gate result to `generation_log`.
6. Only hashes go on chain. Never document text, names or emails.
7. Sources stay hidden until submit: `QuizOut` omits `fact_idxs` and Source chips stay hidden until the attempt is submitted; `/verify/question` answers 409 until then.

## Hashing (must match Solidity exactly; exact formats in SPEC section 8)
- text_hash = keccak256(utf-8 fact text)
- leaf = keccak256(bytes.concat(keccak256(abi.encode(uint256 idx, bytes32 text_hash))))  (OpenZeppelin leaf format)
- tree: leaves in our idx order (not sorted first), internal nodes = keccak256 of the sorted pair, odd last node promoted unchanged; root → `documents.fact_root`
- doc_id (on chain) = keccak256(utf-8 document UUID string)
- quiz_hash = keccak256(canonical JSON, sorted keys, no spaces, of {"questions":[{stem, options, answer_index, fact_idxs, gate_results}] ordered by position, "salt": lowercase hex})

## Commands (Windows PowerShell 5.1: no `&&`; always quote paths, the repo path contains a space)
Shortcut: `powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 <db|api|web|test>` (sets PYTHONUTF8=1)
- DB: `docker compose up -d db`
- API: `Set-Location api; $env:PYTHONUTF8=1; .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000`
- Web: `Set-Location web; npm.cmd run dev` (port 3000, `NEXT_PUBLIC_API_URL=http://localhost:8000`)
- Contracts: `Set-Location contracts; npx.cmd hardhat test` · deploy: `npx.cmd hardhat run scripts/deploy.ts --network amoy`
- API tests: `Set-Location api; $env:PYTHONUTF8=1; .\.venv\Scripts\python.exe -m pytest -q`
- Never rely on venv activation, `make`, `python3`, or bare `npx`/`npm`. Open text files with explicit `encoding="utf-8"`.

## Env (never commit `.env`; keep `.env.example` current)
GEMINI_API_KEY, GENERATOR_BASE_URL, LLM_GENERATOR_MODEL, GROQ_API_KEY, CHECKER_BASE_URL, LLM_CHECKER_MODEL,
GENERATOR_RPM, CHECKER_RPM, CHECKER_TPM, DATABASE_URL, JWT_SECRET, AMOY_RPC_URL,
ISSUER_PRIVATE_KEY (testnet only), REGISTRY_ADDRESS, CHAIN_OPTIONAL, CHAT_MIN_SIM, NEXT_PUBLIC_API_URL
Settings load the ROOT `.env` by absolute path with `extra="ignore"`, whatever the working directory.
`CHAIN_OPTIONAL=false` for the live demo, so chain failures cannot pass silently.

## Working style
- Before changing more than one file, show a short plan and wait for "go".
- Write tests with the code; run them before saying a task is done.
- Small git commits per feature with clear messages.
- After every task, append to `docs/STATUS.md` (what was done, how to run it, test result, open issues).
- If a requirement is unclear, ask. Never invent API shapes — follow `docs/SPEC.md`, and update SPEC if a shape must change.
- Prompts may contain labels like `/context:` or `/constraints:`. They are section headings, not commands.
