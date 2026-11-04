# SmartQuiz — Summary of work to date (Review 1)

As of 2026-11-04. A short overview of everything built so far. Detail lives in `docs/STATUS.md` (log),
`docs/SPEC.md` (shapes) and `docs/PLAN.md` (scope). This file summarises them and adds no new decisions.

## The idea in one line
SmartQuiz turns an uploaded PDF or text file into a closed-book textbook of numbered facts, then generates cited quizzes
from it. **Proof of Grounding:** anyone can verify that a question came from a specific fact of a specific document,
passed verification gates, and was committed on chain before the attempt.

## Research basis (`docs/RESEARCH.md`)
- **What exists:** source-grounded AI quizzes (NotebookLM) and AI quizzes with blockchain certificates (ICanProveIt,
  LearningRec, Proof of Learning, ProofLearn, IEEE Access 2024 blockchain exams). None prove where a *question* came from.
- **What we took from the papers:**

| Our feature | Built from | What is new |
| --- | --- | --- |
| Textbook Mode (section → concept → atomic fact) | HALOGEN, RAPTOR, K12-KGraph | Each fact has an exact quote, page and offsets in the source, and a hash |
| Independent verification gates | Hallucination-free MCQ gen (2601.14280), CaLM, MCQGen | Checker is a different model family from the generator; every gate result is logged |
| Document Dependence Score | Our own | Blind test: can the question be answered without the notes? |
| No repeats by design | KAQG, KT4EQG, dedup studies | Coverage ledger picks unused facts first; fingerprint + cosine 0.85 as backup |
| Closed-book chat that abstains | Corrective RAG | Calibrated threshold, "not covered" + 2 nearest sections |
| Proof of Grounding on chain | Gap in blockchain-exam work | Merkle root of facts on chain, quiz hash committed before the attempt, public Verify page |

## What is built (command by command)
| Step | What it delivered |
| --- | --- |
| P00 bootstrap | Monorepo (FastAPI api, Next.js web, Hardhat contracts, Postgres 16 + pgvector in Docker), `provider.py` (the only LLM caller: throttling, daily budgets, sqlite cache), `merkle.py`, `dev.ps1` |
| P01 schema + auth | 9 SPEC tables, Alembic migrations, email + password signup/login (argon2, JWT), `/auth/me` |
| P02 ingestion | PDF/TXT → sections from the outline → LLM fact extraction → quote location (exact or fuzzy ≥ 90, page + offsets) → `gate0_fact` faithfulness check → hashes → Merkle root |
| Quota fix + coverage fix | Both roles on Groq free tier (generator `openai/gpt-oss-120b`, checker `qwen/qwen3.8-27b`); per-role request budgets; coverage raised from ~25% to 74% by `GENERATOR_REASONING_EFFORT=low`, a follow-up call on short replies and splitting chunks on bad JSON |
| Fedora move | `scripts/dev.sh` (Linux twin of `dev.ps1`), separate Windows and Linux command blocks, venv rebuilt with uv (Python 3.12) |
| P03 contract | `SmartQuizRegistry.sol` (OpenZeppelin v5): `registerDocument`, `commitQuiz`, `verifyFact`; Python ↔ Solidity Merkle cross-check; deployed to Polygon Amoy |
| P04 chain service | web3.py `ChainService` (PoA middleware, nonce lock, EIP-1559 fees, decoded custom errors); documents registered on chain after ingestion; retry endpoint |
| P05 quiz generation | Fact selection (unused → last wrong → …, spread by section), one generator call, Gates 1 / 3 / 4 on the checker, one batched regeneration, duplicate blocking, `generation_log`, metrics endpoint |
| P06 commit + attempts | Canonical quiz hash with salt, committed on chain before the quiz is `ready`; timed attempts, scoring, Source chips after submit, weak concepts, fact coverage updates |
| P07 chat | Top-8 fact retrieval (pgvector), abstain below `CHAT_MIN_SIM = 0.69`, answers must cite retrieved `[F#]` facts, calibration script |
| P08 verify API | Public `/verify/question` (409 until submitted), `/verify/fact` (tamper test), `/verify/quiz` (hash match); offline = null, never false |
| P09 web core | Auth, documents + upload, textbook tree, timed quiz with progress and start screen, results with sources, metrics page (navy/orange deck theme) |
| P10 web chat + verify | Chat with fact chips and abstain card; public Verify page with Question and Quiz tabs, re-check after editing, verified / not verified / chain offline badges |
| P11 integration | End-to-end test, `seed_demo.py`, README "Run the demo", two browser rehearsals of the 6-step demo |

## Results on our chapter (`samples/sample.pdf`, real models, Polygon Amoy)
| Measure | Value |
| --- | --- |
| Sections / facts kept | 50 / 482 |
| Source text covered by fact quotes | 74.1% |
| Facts rejected by `gate0_fact` | 100 (17%) |
| Repeated target facts, quiz 1 vs quiz 2 | 0 |
| Quiz generation time | ~48 s for 10 verified questions |
| Chat threshold | 0.69 (in-scope 0.75–0.89, out-of-scope 0.40–0.63), 0 of 20 misplaced |
| Tamper test | real text → true, one-word edit → false |
| Quiz hash match (recomputed vs on chain) | true |
| Average document dependence | 0.19–0.20 (low) |
| Same-family checker fallback used | No |
| Demo rehearsals | 206 s and 253 s (target < 6 min) |
| Tests | pytest 204 passed (with a local Hardhat node), Hardhat 13 passing, web build + lint clean |

## Review 1 cut list
All seven items are done: textbook ingestion, coverage-based generation with gates, document root on chain + Verify
page, quiz commit before attempt, closed-book chat, dependence score (weak result, shown honestly), metrics page.

## Key references
| Item | Value |
| --- | --- |
| Registry (Amoy, chain 80002) | `0x4093F5F19Eacf69Fc8144A1d39A3f6838D4dc518` |
| Sample fact root | `0xdc79cf855291af5c7df949392bf9b29399709267b06e760ae242c6757c045a0d` |
| Demo document | `3ce3f1e0-fb57-4d46-910f-64658822e850` (user `demo@example.com`) |
| Demo quiz 1 | `b16a8c21-b3e9-4044-8af0-18b177d48664` (ready, not started) |
| Issuer wallet balance | ~0.030 POL (~12 transactions); top up before the review |

## Open issues
- **Low document dependence:** the chapter is general cyber security, so the blind checker answers many questions.
  Better distractors raised it from 0.09 to 0.20; this is the main quality lever for Review 2.
- **Extraction gaps:** ~26% of section text has no fact (e.g. the AIIMS Delhi line); chat abstains on those correctly.
- **`gate0_fact` too strict in places:** the checker sees no section headings.
- **Results after refresh** rely on the tab's sessionStorage (no GET attempt endpoint).
- **Single vendor:** both models run on Groq, so a Groq outage stops both roles.
- **Not run yet:** `/code-review` and `/security-review`. Python packages are unpinned.

## Next (Review 2)
Distractor-falsity gate and misconception-based distractors, Bloom's ladder, mastery (BKT) with gap report and revision
notes, FSRS review, open-ended grading against cited facts, batched result anchoring, ERC-5192 concept badge, revocation,
educator co-signing; stretch: ZK proof of passing.
