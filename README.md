# SmartQuiz

Turn any study material into grounded, source-cited quizzes — with on-chain **Proof of Grounding** for every question.
Industrial project · CMRIT Bengaluru · Industry partner: Dopove Private Limited
Team: Balaji Keerthi (runs the build) · Deepesh Kumar Kotta and Aravindh Balaji (review, test, present)

Claude Code built this repo step by step with the slash commands in `.claude/commands/`. **Status (2026-11-04):** the
Review 1 slice is complete (P00–P11 done, all six demo steps pass). See `docs/SUMMARY.md` for an overview and
`docs/STATUS.md` for the full log.

## 1. Install once
- Windows: Git, Python 3.11+, Node.js 24, Docker Desktop (PowerShell)
- Linux: Git, Docker + Compose, Node.js 22+, uv (bash) — see "Getting started → Linux"
- Claude Code (install guide: https://docs.claude.com → Claude Code → Quickstart)
- One FREE AI key for the app (no credit card): Groq from console.groq.com/keys, used for both generator and checker. A Gemini key is optional. Paste into `.env`
- A fresh MetaMask account used ONLY as the testnet issuer wallet, plus Amoy test POL from a Polygon faucet

## 2. Start
```powershell
Set-Location "C:\path\to\smartquiz"   # keep the quotes: paths may contain spaces
claude
```
Inside Claude Code, type `/` to see the project commands. Each one is a full prompt that Claude Code runs.

## 3. Order of commands
One person runs all of these, in order, in one session. Time estimates are in `docs/PLAN.md`.
All twelve were completed on 2026-11-04; they stay here as the record of how the code was built.

| # | Command | What it builds | State |
| --- | --- | --- | --- |
| 1 | `/p00-bootstrap` | Empty monorepo → api, web, contracts, Postgres, `merkle.py`. GitHub push as a backup | Done |
| 2 | `/p01-schema-auth` | Database schema and auth | Done |
| 3 | `/p02-ingest` | Textbook Mode | Done |
| 4 | `/p03-contract` | Registry contract | Done (Amoy `0x4093F5F19Eacf69Fc8144A1d39A3f6838D4dc518`) |
| 5 | `/p04-chain` | Chain service and document registration | Done |
| 6 | `/p05-quizgen` | Verified quiz generation and metrics | Done |
| 7 | `/p06-commit-attempt` | Quiz commit, attempts, coverage | Done |
| 8 | `/p07-chat` | Closed-book chat | Done |
| 9 | `/p08-verify-api` | Public verify API | Done |
| 10 | `/p09-web-core` | Main web screens, on the real API | Done |
| 11 | `/p10-web-chat-verify` | Chat and Verify pages | Done |
| 12 | `/p11-integrate` | End-to-end demo, seed script. GitHub push as a backup | Done |

Helpers anytime:
- `/next` — what to run next
- `/fix <error message>` — smallest correct fix with a test
- `/status` — writes docs/STATUS.md and prints an update block. **Paste that block back into the planning chat with Claude** so the plan can be adjusted.

## 4. Real Claude Code commands we use
| Command | When |
| --- | --- |
| `/memory` | Check or edit CLAUDE.md (project rules) |
| `/compact` | After each P-command finishes, to keep context small |
| `/clear` | When switching to unrelated work |
| `/code-review` | After P05 and P11 |
| `/security-review` | After P03, P08 and P11 |
| `/plan` or Shift+Tab | Optional: plan mode before a big change (every P-command already shows a plan and waits for "go") |

Inside the command files you will see labels such as `/context:`, `/constraints:`, `/test:`. These come from the
Claude Command cheat sheet and only structure the prompt; they are not commands you type.

## 5. Docs
- `CLAUDE.md` — rules Claude Code follows every session
- `docs/PLAN.md` — scope, command sequence, demo, cut list
- `docs/SPEC.md` — schema, API shapes, hashing, gates, contract
- `docs/RESEARCH.md` — research summary and why our approach is unique
- `docs/STATUS.md` — progress log (updated by every command)
- `docs/SUMMARY.md` — one-page overview of everything done so far (research basis, what is built, results, open issues)
- `docs/SLIDES-PROMPT.md` — prompt for the Review 1 slides (use in the Claude app)

## Getting started
There are two sets of commands: **Windows** (PowerShell, `scripts/dev.ps1`) and **Linux** (bash, `scripts/dev.sh`).
Use the one for your laptop. `.env` (repo root) must be filled in first on either.

### Linux (Fedora / bash)
Needs Docker with Compose, Node.js 22+ and [uv](https://docs.astral.sh/uv/) (uv fetches Python 3.12; the system
Python may be too new for PyTorch). Your user must be in the `docker` group. From the repo root:
```bash
./scripts/dev.sh setup     # once: api/.venv (Python 3.12, CPU torch), npm ci in web and contracts, web/.env.local
./scripts/dev.sh db        # Postgres on 5432
./scripts/dev.sh migrate   # apply database migrations (after db starts)
./scripts/dev.sh api       # http://localhost:8000/health   (own terminal)
./scripts/dev.sh web       # http://localhost:3000          (own terminal)
./scripts/dev.sh test      # pytest, hardhat test, web build
```
Stop `dev.sh web` before `dev.sh test` (or any `npm run build`): both use `web/.next`, and a build under a running dev
server leaves it serving stale CSS. If styles look missing, stop it, delete `web/.next` and start it again.

Check the LLM keys and model names:
```bash
PYTHONUTF8=1 api/.venv/bin/python api/scripts/check_llm.py
```
Copying the repo from Windows? Delete `api/.venv` and every `node_modules` first (they hold Windows binaries), then
run `setup`. Keep `api/.cache/llm.sqlite`: it holds cached LLM replies that save free-tier quota.

### Windows (PowerShell)
From the repo root. Keep the quotes, because paths may contain spaces. PowerShell 5.1 has no `&&`.

First-time setup (`.env` must already be filled in):
```powershell
python -m venv api\.venv
# CPU-only PyTorch first, so no GPU files are downloaded
api\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
api\.venv\Scripts\python.exe -m pip install -r api\requirements.txt
Push-Location web; npm.cmd install; Pop-Location
Push-Location contracts; npm.cmd install; Pop-Location
Set-Content -Path web\.env.local -Value "NEXT_PUBLIC_API_URL=http://localhost:8000" -Encoding ascii
```

Run each of these from the repo root, with `api` and `web` in their own terminals:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 db     # Postgres on 5432
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 migrate   # apply database migrations (after db starts)
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 api    # http://localhost:8000/health
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 web    # http://localhost:3000
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 test   # pytest, hardhat test, web build
```

Check the LLM keys and model names (prints no key values, sends one tiny request to each provider):
```powershell
api\.venv\Scripts\python.exe api\scripts\check_llm.py
```

## Run the demo (Review 1)
The demo runs with `CHAIN_OPTIONAL=false`, so a chain failure cannot pass silently. Set it in `.env` before the
review (or pass it as an environment variable for one run, as below), and check the issuer wallet has test POL
(each document registration or quiz commit costs about 0.0025 POL on Amoy).

**Linux (bash)**, from the repo root, each server in its own terminal:
```bash
./scripts/dev.sh db
./scripts/dev.sh migrate
(cd api && CHAIN_OPTIONAL=false PYTHONUTF8=1 .venv/bin/python -m uvicorn app.main:app --port 8000)
./scripts/dev.sh web
# before the review: ingest the chapter and pre-generate quiz 1 (not started), then paste what it prints
(cd api && PYTHONUTF8=1 .venv/bin/python scripts/seed_demo.py)
```

**Windows (PowerShell)**, from the repo root, each server in its own window:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 db
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 migrate
Set-Location api; $env:PYTHONUTF8=1; $env:CHAIN_OPTIONAL="false"; .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 web
Set-Location api; $env:PYTHONUTF8=1; .\.venv\Scripts\python.exe scripts\seed_demo.py
```

`seed_demo.py` logs in as `demo@example.com` (password `review1-demo`, or `--password` / `SMARTQUIZ_DEMO_PASSWORD`).
Then open http://localhost:3000, log in as the demo user and follow the six demo steps in `docs/PLAN.md`:
textbook and Amoy link → open quiz 1 (already committed) → submit → **New quiz (no repeats)** → **Ask a doubt**
(in scope, then out of scope) → **Verify this question** (edit one word, Re-check) → **Verify this quiz**.
If Amoy is unreachable, use a local chain instead (SPEC section 6) with `CHAIN_OPTIONAL=true`, and say so on stage.
