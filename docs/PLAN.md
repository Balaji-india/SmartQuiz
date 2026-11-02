# SmartQuiz — Review 1 plan (build from scratch)

Goal for Review 1 (~40%): one end-to-end slice on one PDF that proves **Proof of Grounding** live.
Budget: ~23 working hours, one operator, one sequence. Detailed shapes are in `docs/SPEC.md`.

## Who does what
- **Balaji** runs every command, in one Claude Code session on a Windows laptop.
- **Deepesh and Aravindh** review, test and present. They do not run build commands, so there are no parallel lanes or hand-offs.

## Decisions (approved)
| Item | Decision |
| --- | --- |
| Headline claim | Proof of Grounding: each question is provably derived from a fact of your document, verified, and committed on chain |
| Data foundation | Textbook Mode: document → sections → concepts → atomic facts with exact spans and hashes |
| Review 1 scope | Auth, upload, Textbook Mode (A1), gates 1+3 (A2), dependence score (A3), coverage-based no-repeat generation (A4), timed quiz + scoring, closed-book chat (A8), on-chain doc root (B1), quiz commit (B2), Verify page (B5), metrics (A12) |
| LLM | Free tiers, no card: generator and checker both on Groq, different model families on purpose (Gemini is an optional generator); model names live only in .env, swappable through `app/llm/provider.py` |
| Embeddings | Local `BAAI/bge-small-en-v1.5`, 384 dims |
| Wallet | One server issuer wallet; learners need no wallet in Review 1 |
| Chain | Polygon Amoy testnet; local Hardhat node as fallback |
| Web data | Built after the API exists, against the real API; mocks only in tests |
| Toolchain | Windows PowerShell 5.1, Hardhat 2.29.1 + hardhat-toolbox 6.1.2 (exact pins; Hardhat 2.29.1 declares Node ^24 support) |

## Before you start
- P00: Docker running, `.env` filled (done).
- P02: `samples/sample.pdf` in place (a 15–30 page text-based chapter).
- P03/P04: issuer wallet funded with Amoy test POL from a faucet, for the real deploy and registration.

## Command sequence (dependency order)
Run `/compact` after each command. Times are estimates, including review of the plan and test runs.

| # | Command | Builds | Estimate | Done when |
| --- | --- | --- | --- | --- |
| 1 | `/p00-bootstrap` | Monorepo, provider, `merkle.py` with tests, `scripts/dev.ps1`; GitHub backup push | 1.5 h | DB up, API `/health`, web home page, contracts compile, merkle + provider tests pass |
| 2 | `/p01-schema-auth` | Schema, migrations, auth | 1 h | Signup → login → `/auth/me` tests pass |
| 3 | `/p02-ingest` | Textbook Mode | 2.5 h | sample.pdf → facts + root |
| 4 | `/p03-contract` | Registry contract, Python↔Solidity cross-check | 1.5 h | Contract tests green; deployed to Amoy if funded |
| 5 | `/p04-chain` | Chain service, document registration | 1.5 h | Upload shows an Amoy tx link |
| 6 | `/p05-quizgen` | Selection, generation, gates, metrics | 3 h | 10 verified questions; second quiz has 0 repeated target facts |
| 7 | `/p06-commit-attempt` | Quiz commit, attempts, coverage | 1.5 h | Hash committed before start; attempt scored |
| 8 | `/p07-chat` | Closed-book chat | 1.5 h | 20 calibration questions pass |
| 9 | `/p08-verify-api` | Public verify endpoints | 1 h | Valid → true, tampered → false, quiz match |
| 10 | `/p09-web-core` | Auth, documents, textbook, quiz, results, metrics screens | 3.5 h | Demo steps 1–3 work in the browser |
| 11 | `/p10-web-chat-verify` | Chat and Verify pages | 1.5 h | Demo steps 4–6 work in the browser |
| 12 | `/p11-integrate` | End-to-end test, seed script, rehearsal fixes; GitHub backup push | 3 h | Two clean rehearsals under 6 minutes |

Total ≈ 23 h.

Review checkpoints on Balaji's laptop: Deepesh checks fact and question quality after P02, P05 and P07. Aravindh tests the screens after P09 and P10. Both rehearse in P11 and present. Slides come from `docs/SLIDES-PROMPT.md` after P11, using real metrics.

## Review 1 demo (6 minutes, this is also the acceptance test)
Run with `CHAIN_OPTIONAL=false`, so a chain failure cannot pass silently.
1. Sign up, upload our chapter PDF → textbook tree, fact count, Merkle root, Amoy explorer link.
2. Start a timed 10-question quiz → progress shows accepted and rejected counts; metrics show gate rejections and reasons.
3. Submit → score, Source chip on each question, weak concepts with cited passages. Start a second quiz → 0 repeated target facts.
4. Chat: an in-scope doubt gets a cited answer; an out-of-scope question gets "not covered" + nearest sections.
5. Verify page: paste a question ID from the submitted quiz → fact, Merkle proof, contract `verifyFact` = true. Edit one word → false.
6. Verify page: paste the quiz ID → recomputed hash matches the hash committed on chain before the attempt.

## Cut list (cut from the bottom if short on time)
1. Textbook ingestion with spans + root — must
2. Coverage-based generation with gates 1 and 3 — must
3. Doc root on chain + Verify page with tamper test — must (this is the unique claim)
4. Quiz commit before attempt
5. Closed-book chat abstain
6. Dependence score
7. Metrics page (fallback: print numbers from `api/scripts/seed_demo.py`)

## Risks → fallback
- No Amoy POL in time → set `CHAIN_OPTIONAL=true` and use a local Hardhat node (SPEC section 6). The UI shows a "chain offline" badge if a chain call fails.
- PDF without a table of contents → font-size headings, worst case one section per page.
- Slow ingestion → demo a 15–30 page chapter, ingest it before the review (upload is idempotent).
- Gates reject too much → show it as evidence on the metrics page; improve the generator prompt, not the gates.
- Free-tier rate limits (Groq ~25 requests/min, 8k tokens/min, 1000 requests/day per model) → provider throttles, counts requests and caches by input hash; ingest the demo PDF and pre-generate quiz 1 before the review so nothing waits on stage.
- Groq daily cap → work stops with a clear error, and cached work is kept. Both roles depend on one vendor and key, so a Groq outage stops both. Emergency only: a same-family checker (SPEC section 4) weakens independence, so the metrics page shows a warning. Revert it before the demo if possible; if not, say so on stage.

## After Review 1 (Review 2 / final)
Distractor-falsity gate with fact IDs on distractors, Bloom's ladder, misconception-tagged distractors, BKT mastery + gap report, revision notes,
batched result anchoring, ERC-5192 concept badge, FSRS review, open-ended grading, revocation, educator co-signing, ZK threshold proof (stretch).
