# SmartQuiz — Plan

Two parts: **Review 2 / final submission** (draft, below) and **Review 1** (completed 2026-11-04, kept further down).
Detailed shapes are in `docs/SPEC.md`; SPEC is updated before any code in each Review 2 step.

---

# Review 2 / final — plan (approved 2026-11-26)

Goal: the full project (the remaining ~60%) on top of the Review 1 slice. Proof of Grounding extends from *questions*
to *distractors, results and credentials*, plus the learning loop (mastery, revision, spaced review, open answers).
**Deadline: final submission Monday 2026-11-30** (code + mini project report + presentation). Budget ≈ 30 working hours
over 4 days, one sequence, all run in one Claude Code session on Deepesh's Fedora laptop (Linux commands only).

## Decisions (approved by the team 2026-11-26)
| Item | Decision |
| --- | --- |
| Scope | Everything listed in "After Review 1", ZK proof of passing as stretch |
| Badge holder | (a) Main: the learner pastes their own wallet address on a profile page; the badge is minted to it. (b) Fallback: no address given → a custodial address per learner, derived on the server from `CUSTODY_SECRET` + user id. Learners still never need a wallet or gas. |
| Educator (co-signing, deferred grading, revocation) | Our team. Team accounts get `users.role = "educator"`; co-signatures come from a separate educator wallet (`EDUCATOR_PRIVATE_KEY`, testnet only), not the issuer wallet |
| Review 1 registry | Unchanged at `0x4093…c518`. Review 2 deploys a **second contract** `SmartQuizCredentials.sol`, so all Review 1 roots, commits and proofs stay valid |
| Quiz hash | New format v2 (adds distractor facts, misconception labels and question type). `quizzes.hash_version` (1 or 2) picks the format; Review 1 quizzes still verify as v1 |
| Closed-book rule 4 (selection order) | Unchanged for practice quizzes. FSRS adds a separate **review quiz** mode that uses only facts due for review |

## Design per feature (shapes go into SPEC before code)
- **Gate 2, distractor falsity (R01).** The generator gives each distractor `fact_idxs` (the facts that show it is false)
  and a `misconception` label ("confuses X with Y", built from the notes' own terms). Gate 2 (checker, one batched call,
  in parallel with Gates 1 and 3) judges every distractor against its facts: `FALSE` passes; `TRUE`, `UNSUPPORTED` or
  "same as the answer" fails. Gate 2 failures join the one batched regeneration call (CLAUDE.md rule 5 extended).
  Results show the misconception for each wrong choice. Goal: average dependence ≥ 0.35 over 3 quizzes (now 0.19–0.36).
- **Bloom's ladder (R02).** Levels `remember → understand → apply → analyze`. A retest goes one level up after a correct
  answer, and stays or goes one down after a wrong one. Gate 1 also returns the checker's Bloom level (no new call);
  mismatches are logged and shown on metrics, not dropped.
- **Mastery (R03).** BKT per user + concept (p_init 0.2, p_learn 0.15, p_slip 0.1, p_guess 0.25; mastered ≥ 0.95),
  updated from the target fact's concept on every graded answer. `GET /documents/{id}/mastery` → gap report: concepts by
  mastery, untested concepts, their sections and cited facts.
- **Revision notes (R04).** For the weakest concepts, one generator call writes notes from only their facts, every
  sentence ending in `[F#]`; one batched Gate 1 call drops unsupported sentences. Stored, regenerated after new attempts.
- **FSRS review (R05).** `fsrs` package, one card per user + fact; wrong → Again, correct → Good. `POST /quizzes`
  gets `mode: "practice" | "review"`; review takes only due facts (most overdue first) and keeps all gates.
- **Open-ended questions (R06).** Question type `short` (default 2 of 10): stem, model answer, cited facts. On submit,
  one batched checker call grades each answer against the cited facts → `correct | partial | incorrect` + confidence.
  Confidence < 70 → **deferred** to the educator queue; the score is final once the educator grades it.
- **Credentials contract (R07).** `SmartQuizCredentials.sol` (OpenZeppelin v5, ERC-721 + ERC-5192 locked):
  `anchorResults(batchId, root, count)` (Merkle root of attempt hashes; only hashes, never names or emails),
  `mintBadge(to, docId, conceptHash, evidenceHash)`, `revokeBadge(tokenId, reasonHash)`,
  `addEducator(addr)`, `coSignDocument(docId, factRoot, signature)` (EIP-712, checked with ECDSA against the educator list),
  `revokeDocument(docId, reasonHash)`. Issuer pays all gas.
- **Credentials API (R08).** attempt_hash = keccak256 of canonical JSON {quiz_id, answers, score, total, salt}.
  Educator "Anchor now" puts all unanchored attempts in one batch tx. A badge needs: concept mastered, its attempts
  anchored; evidenceHash = keccak256 of the sorted attempt hashes. New public endpoints `/verify/attempt/{id}`
  (proof + on-chain root + match) and `/verify/badge/{token_id}` (holder, concept, document, revoked, evidence);
  `/verify/question` adds co-sign and revocation status.
- **Web (R09, R10).** Learning: mastery + gap report page, revision notes, review queue, short-answer questions in the quiz.
  Credentials: profile (wallet address, my badges), educator page (co-sign documents, deferred grading queue, anchor
  results, revoke), Verify page tabs for Result and Badge.
- **Stretch: ZK proof of passing.** Only if R11 finishes before Monday morning; otherwise it goes in the report as future work.

## Before you start
- **Issuer wallet top-up: at least 0.25 POL** (now ~0.015). Review 2 needs about 25–35 transactions across tests and
  rehearsals, plus deploying the credentials contract. If faucets fall short: `CHAIN_OPTIONAL=true` + local Hardhat node.
- A second MetaMask account for the educator wallet (no POL needed; the issuer submits the signature).
- A learner MetaMask account on Amoy, to show the badge in a real wallet.

## Command sequence (dependency order)
Run `/compact` after each command. Each command updates SPEC first, writes tests with the code, appends to STATUS,
and tells Deepesh what to commit (no commits by Claude).

| # | Command | Builds | Est. | Done when |
| --- | --- | --- | --- | --- |
| 1 | `/r00-cleanup` | `/code-review` + `/security-review` fixes, `GET /attempts/{id}` (results survive refresh), pinned Python packages, npm audit triage, section headings shown to `gate0_fact`, issuer wallet vs registry owner check | 2 h | Reviews clean, pytest green, refresh keeps results |
| 2 | `/r01-distractor-gate` | Gate 2, distractor facts + misconceptions, hash v2, metrics | 3 h | 10 questions pass all gates; avg dependence reported on 3 quizzes; v1 quizzes still verify |
| 3 | `/r02-bloom` | Four-level ladder, retest climbing, Bloom check in Gate 1 | 1.5 h | A retested fact moves up a level; tests green |
| 4 | `/r03-mastery` | BKT table + updates, gap report endpoint | 2.5 h | Mastery changes after an attempt; gap report lists weak + untested concepts |
| 5 | `/r04-revision` | Revision notes with cited, gated sentences | 1.5 h | Every kept sentence cites a supporting fact |
| 6 | `/r05-fsrs` | FSRS cards, review quiz mode | 2 h | Wrong answers become due; review quiz uses only due facts |
| 7 | `/r06-open-ended` | Short-answer questions, grading, deferral queue | 2.5 h | Graded with citations; a low-confidence answer is deferred |
| 8 | `/r07-credentials-contract` | `SmartQuizCredentials.sol`, Hardhat tests, Python↔Solidity cross-check, Amoy deploy | 3 h | Contract tests green; deployed; educator added |
| 9 | `/r08-credentials-api` | Anchoring, badges (address or custodial), co-sign, revocation, verify endpoints | 2 h | Attempt proof verifies on chain; badge minted and revocable |
| 10 | `/r09-web-learning` | Mastery, revision, review, short-answer screens | 3 h | Final demo steps 7–9 work in the browser |
| 11 | `/r10-web-credentials` | Profile, educator page, Verify Result/Badge tabs | 2 h | Final demo steps 10–12 work in the browser |
| 12 | `/r11-final` | End-to-end test, new seed on Fedora, rehearsals, README, SUMMARY, final metrics | 3 h | Two clean rehearsals under 12 minutes |
| 13 | `/r12-report-slides` | Mini project report (`docs/REPORT.md` → PDF) and presentation from real metrics (`docs/SLIDES-PROMPT.md` updated) | 1.5 h | Report and deck ready to submit |

Total ≈ 30 h.

## Day plan (to make Monday)
| Day | Commands | Hours | Checkpoint |
| --- | --- | --- | --- |
| Thu 26 (today, evening) | Approve plan → SPEC sections + command files → R00 | 3 h | Clean base, reviews done |
| Fri 27 | R01, R02, R03 | 7 h | Deepesh checks distractor and question quality |
| Sat 28 | R04, R05, R06, R07 | 9 h | **Cut decision Saturday night**: if R07 is not deployed, drop co-signing and revocation (cut list) |
| Sun 29 | R08, R09, R10 | 7 h | Aravindh tests all new screens |
| Mon 30 (morning) | R11, rehearsals, R12 report + slides, submit | 4.5 h | Submit |

## Final demo (≈ 12 minutes; also the acceptance test; `CHAIN_OPTIONAL=false`)
Steps 1–6 as in Review 1, then:
7. Results show each wrong choice's misconception and its cited fact; metrics show Gate 2 rejections and Bloom levels.
8. Mastery page: gap report after two attempts; revision notes for the weakest concept, every sentence cited.
9. Start a review quiz: only the facts answered wrong come back; a short-answer question is graded with citations.
10. Educator page: grade a deferred answer; co-sign the document → Verify shows "co-signed by educator 0x…".
11. Anchor results → Verify (Result tab): attempt hash, Merkle proof, on-chain root, match = true.
12. Badge for a mastered concept minted to the learner's wallet (custodial if none) → Verify (Badge tab) valid;
    revoke it → Verify shows revoked.

## Cut list (cut from the bottom if short on time)
1. R00 cleanup and the Gate 2 distractor gate — must (the main quality fix, and a Review 1 promise)
2. Mastery + gap report — must
3. Result anchoring + concept badge (address or custodial) — must (extends the on-chain claim)
4. Bloom's ladder
5. Revision notes
6. FSRS review mode
7. Open-ended grading with deferral
8. Educator co-signing
9. Revocation
10. ZK proof of passing (stretch; report only if not built)

## Risks → fallback
- **Not enough POL** → local Hardhat node with `CHAIN_OPTIONAL=true` for development; rehearse on Amoy only once topped up.
- **Groq daily caps** (Gate 2, Bloom, grading and revision add checker calls) → batch every gate, cache everything,
  seed the demo early; count requests per quiz in STATUS after R01.
- **Dependence stays low after Gate 2** → report it honestly with the per-quiz spread; the misconception labels are still new.
- **Hash v2 breaks Review 1 proofs** → `hash_version` column + a v1 regression test on the stored demo quiz.
- **Time** → follow the day plan; the Saturday-night cut decision is fixed in advance.
- **Demo IDs differ per database** → the final demo runs on the Fedora laptop and is re-seeded there in R11; the Windows IDs from 2026-11-04 are not used. IDs recorded in STATUS.

## Answered 2026-11-26
- Review 2 runs entirely on Deepesh's Fedora laptop, in this Claude Code session. The Windows blocks stay in CLAUDE.md for reference only.
- Monday's submission: code, a mini project report and a presentation (R12).
- Hours: the team works until it is done; the day plan stands, with the Saturday-night cut decision as the safety valve.

---

# Review 1 — plan (completed 2026-11-04)

Goal for Review 1 (~40%): one end-to-end slice on one PDF that proves **Proof of Grounding** live.
Budget: ~23 working hours, one operator, one sequence. Detailed shapes are in `docs/SPEC.md`.

### Outcome
- All 12 commands (P00–P11) and all 7 cut-list items are done. Details in `docs/STATUS.md`, overview in `docs/SUMMARY.md`.
- All six demo steps pass on the real chapter with real Groq models and Polygon Amoy; two rehearsals took 206 s and 253 s.
- Sample chapter: 482 facts from 50 sections, 74% of section text covered; 0 repeated target facts between quizzes; chat threshold 0.69 with 0 of 20 misplaced.
- Weak result, shown honestly: average document dependence is 0.19–0.20, because the blind checker answers many questions on a general cyber-security chapter.
- Work moved partly to Fedora Linux (`scripts/dev.sh`); the Windows commands still apply on Balaji's laptop.
- Not done yet: `/code-review` and `/security-review` runs; GitHub backup push is left to the team.

The rest of this file is the plan as approved before the build.

### Who does what
- **Balaji** runs every command, in one Claude Code session on a Windows laptop.
- **Deepesh and Aravindh** review, test and present. They do not run build commands, so there are no parallel lanes or hand-offs.

### Decisions (approved)
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

### Before you start
- P00: Docker running, `.env` filled (done).
- P02: `samples/sample.pdf` in place (a 15–30 page text-based chapter).
- P03/P04: issuer wallet funded with Amoy test POL from a faucet, for the real deploy and registration.

### Command sequence (dependency order)
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

### Review 1 demo (6 minutes, this is also the acceptance test)
Run with `CHAIN_OPTIONAL=false`, so a chain failure cannot pass silently.
1. Sign up, upload our chapter PDF → textbook tree, fact count, Merkle root, Amoy explorer link.
2. Start a timed 10-question quiz → progress shows accepted and rejected counts; metrics show gate rejections and reasons.
3. Submit → score, Source chip on each question, weak concepts with cited passages. Start a second quiz → 0 repeated target facts.
4. Chat: an in-scope doubt gets a cited answer; an out-of-scope question gets "not covered" + nearest sections.
5. Verify page: paste a question ID from the submitted quiz → fact, Merkle proof, contract `verifyFact` = true. Edit one word → false.
6. Verify page: paste the quiz ID → recomputed hash matches the hash committed on chain before the attempt.

### Cut list (cut from the bottom if short on time)
1. Textbook ingestion with spans + root — must
2. Coverage-based generation with gates 1 and 3 — must
3. Doc root on chain + Verify page with tamper test — must (this is the unique claim)
4. Quiz commit before attempt
5. Closed-book chat abstain
6. Dependence score
7. Metrics page (fallback: print numbers from `api/scripts/seed_demo.py`)

### Risks → fallback
- No Amoy POL in time → set `CHAIN_OPTIONAL=true` and use a local Hardhat node (SPEC section 6). The UI shows a "chain offline" badge if a chain call fails.
- PDF without a table of contents → font-size headings, worst case one section per page.
- Slow ingestion → demo a 15–30 page chapter, ingest it before the review (upload is idempotent).
- Gates reject too much → show it as evidence on the metrics page; improve the generator prompt, not the gates.
- Free-tier rate limits (Groq ~25 requests/min, 8k tokens/min, 1000 requests/day per model) → provider throttles, counts requests and caches by input hash; ingest the demo PDF and pre-generate quiz 1 before the review so nothing waits on stage.
- Groq daily cap → work stops with a clear error, and cached work is kept. Both roles depend on one vendor and key, so a Groq outage stops both. Emergency only: a same-family checker (SPEC section 4) weakens independence, so the metrics page shows a warning. Revert it before the demo if possible; if not, say so on stage.

### After Review 1 (Review 2 / final)
Distractor-falsity gate with fact IDs on distractors, Bloom's ladder, misconception-tagged distractors, BKT mastery + gap report, revision notes,
batched result anchoring, ERC-5192 concept badge, FSRS review, open-ended grading, revocation, educator co-signing, ZK threshold proof (stretch).
