# SmartQuiz

Turn any study material into grounded, source-cited quizzes — with on-chain **Proof of Grounding** for every question.
Industrial project · CMRIT Bengaluru · Industry partner: Dopove Private Limited
Team: Balaji Keerthi (runs the build) · Deepesh Kumar Kotta and Aravindh Balaji (review, test, present)

This repo starts empty on purpose. Claude Code builds it step by step using the slash commands in `.claude/commands/`.

## 1. Install once
- Git, Python 3.11+, Node.js 24, Docker Desktop (Windows, PowerShell)
- Claude Code (install guide: https://docs.claude.com → Claude Code → Quickstart)
- Two FREE AI keys for the app (no credit card): Google Gemini from aistudio.google.com and Groq from console.groq.com/keys. Paste both into `.env`
- A fresh MetaMask account used ONLY as the testnet issuer wallet, plus Amoy test POL from a Polygon faucet

## 2. Start
```powershell
Set-Location "C:\path\to\smartquiz"   # keep the quotes: paths may contain spaces
claude
```
Inside Claude Code, type `/` to see the project commands. Each one is a full prompt that Claude Code runs.

## 3. Order of commands
One person runs all of these, in order, in one session. Time estimates are in `docs/PLAN.md`.

| # | Command | What it builds |
| --- | --- | --- |
| 1 | `/p00-bootstrap` | Empty monorepo → api, web, contracts, Postgres, `merkle.py`. GitHub push as a backup |
| 2 | `/p01-schema-auth` | Database schema and auth |
| 3 | `/p02-ingest` | Textbook Mode |
| 4 | `/p03-contract` | Registry contract |
| 5 | `/p04-chain` | Chain service and document registration |
| 6 | `/p05-quizgen` | Verified quiz generation and metrics |
| 7 | `/p06-commit-attempt` | Quiz commit, attempts, coverage |
| 8 | `/p07-chat` | Closed-book chat |
| 9 | `/p08-verify-api` | Public verify API |
| 10 | `/p09-web-core` | Main web screens, on the real API |
| 11 | `/p10-web-chat-verify` | Chat and Verify pages |
| 12 | `/p11-integrate` | End-to-end demo, seed script. GitHub push as a backup |

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
- `docs/SLIDES-PROMPT.md` — prompt for the Review 1 slides (use in the Claude app)

## Getting started
Windows PowerShell, from the repo root. Keep the quotes, because paths may contain spaces. PowerShell 5.1 has no `&&`.

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
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 api    # http://localhost:8000/health
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 web    # http://localhost:3000
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 test   # pytest, hardhat test, web build
```

Check the LLM keys and model names (prints no key values, sends one tiny request to each provider):
```powershell
api\.venv\Scripts\python.exe api\scripts\check_llm.py
```
