# SmartQuiz — Status log

Every slash command appends an entry here. `/status` adds a summary block under "Updates".

## Updates
### SmartQuiz update — 2026-11-04
**Tests:** api pytest 204 passed, 0 failed (with a local Hardhat node; chain tests skip without one). Hardhat 13 passing. Web build and lint clean.

**Progress**
- Done: P00–P11. All 7 Review 1 cut-list items are done.
- Demo: steps 1–6 pass in the browser with real Groq models and Polygon Amoy (`CHAIN_OPTIONAL=false`); rehearsals 206 s and 253 s.
- Stage demo seeded: user `demo@example.com`, document `3ce3f1e0-fb57-4d46-910f-64658822e850`, quiz 1 `b16a8c21-b3e9-4044-8af0-18b177d48664` (ready, not started).
- Registry on Amoy: `0x4093F5F19Eacf69Fc8144A1d39A3f6838D4dc518`.

**Key results on samples/sample.pdf**
482 facts / 50 sections, quotes cover 74.1% of section text, `gate0_fact` rejects 17%; 0 repeated target facts between quizzes; CHAT_MIN_SIM 0.69 (0 of 20 misplaced); tamper test true → false; quiz hash match true; average dependence 0.19–0.20; same-family checker not used.

**Open issues**
1. Low document dependence (the blind checker answers many questions on a general cyber-security chapter): main lever for Review 2.
2. Extraction misses ~26% of section text (e.g. the AIIMS Delhi line); `gate0_fact` is too strict in places (no headings).
3. Results after a refresh rely on sessionStorage (no GET attempt endpoint).
4. Both roles depend on Groq; Python packages unpinned.

**Run next**
1. Top up the issuer wallet (≈0.030 POL, ~12 transactions left) before the review.
2. `/code-review` and `/security-review`.
3. Commit and push (Deepesh does this himself).

**Reviewers should check**
- Deepesh: fact and question quality in the dev DB; whether `gate0_fact` and the chat prompt need to be stricter or looser.
- Aravindh: the screens, following the six demo steps in `docs/PLAN.md`.

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

### P02 textbook ingestion (2026-11-02)
- **Done:** `api/app/ingest/` (parser, prompts, extractor, locator, hasher, pipeline) and `api/app/routers/documents.py` with `POST /documents`, `GET /documents`, `GET /documents/{id}` and `GET /documents/{id}/textbook`. SPEC section 3 steps 1–6 are implemented. `register_document_onchain(document)` is an empty hook for P04. `POST /documents/{id}/register` is left for P04.
- **Added at Balaji's request, `gate0_fact`:** after quotes are located, one batched checker call per chunk returns FAITHFUL or NOT_FAITHFUL for each quote and fact. Rejected facts are dropped and counted in `facts_unfaithful` (column, `DocumentOut`, stats, SPEC). Each check gets a `generation_log` row. Rule 2 in CLAUDE.md now mentions it.
- **How to run:** `dev.ps1 migrate` (applies 0002), then `dev.ps1 api`. Stats without touching the database: `Set-Location api; $env:PYTHONUTF8=1; .\.venv\Scripts\python.exe scripts\ingest_stats.py [path]` (default `samples/sample.pdf`).
- **Test results:** pytest 72 passed (30 new), FAKE LLM with keys blanked, real bge model.
- **Live stats, on the fixture only:** `samples/sample.pdf` was NOT present, so the requested sample run is still outstanding. On `api/tests/fixtures/fixture_3p.pdf` (invented notes), with the real generator and checker: 2 sections, 10 facts kept, 0 dropped, 0 unfaithful, 0 duplicates, root `0xd940b07cfa6b0ad434cb062fe81fcb3da58da0d62bc15d36309d1d896188ce6e`, 32.1 s. A fixture this clean says nothing about drop rates on real notes.
- **Live gate check:** the real checker got 7 of 7 known pairs right: 2 faithful (rewording, pronoun resolved) accepted; added number, negation, true-but-unstated, wrong subject and overgeneralisation rejected. The check script was not committed.
- **Live API check:** real uvicorn on the dev database with the fixture. Upload returned `ingesting`/`pending`, polling reached `ready`/`offline`, the root matched the stats run, the textbook tree was correct, a repeat upload returned the same document, and 10 `gate0_fact` rows were logged. Test rows were then deleted; `users` and `documents` have 0 rows. Dev database is at migration 0002.
- **Decisions SPEC did not cover:** `facts.quote` stores the source span, so it always equals the text at its offsets; offsets refer to whitespace-collapsed section text; quotes under 20 chars must match exactly; quotes are searched only in their own chunk; a failed LLM call on any chunk fails the whole document, and re-uploading restarts it on the same row; `ingesting` rows become `failed` at API startup; 413 over 25 MB; 400 for other types, empty files, non-UTF-8 text.
- **Spec changes:** extraction reply is `{"facts":[...]}`; added `facts_unfaithful`, gate `gate0_fact`, unique `(user_id, file_sha256)` (migration 0002). P05 must exclude `gate0_fact` from `rejected_by_gate` and `top_reasons`, and count it in `same_family_gate_calls`.
- **Issues:** `samples/sample.pdf` is still missing, and heading detection, repeated headers/footers, drop rates, Gemini and Groq quota use, and timing on a real chapter are all untested until it arrives. A failed document stores no reason; the cause is only in the API log. Non-English text is untested. If `gate0_fact` rejects too many good facts on real notes, tune `CHECK_FAITHFULNESS_SYSTEM`.

### P02 live run on samples/sample.pdf: blocked (2026-11-02)
- **Result:** the run did not finish, so there are no final stats: no kept, dropped, unfaithful or duplicate counts, root or total time. No code was changed.
- **Blocker:** the Gemini free tier allows 20 requests per day for the configured generator model (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, reset about 18 h after the failure). The sample needs 67 generator chunks and 8 are cached, so 59 remain. Quizzes (P05) and chat (P07) use the same generator quota, so this limit also threatens the demo. A model or quota decision is needed from the team.
- **Parser, no LLM needed:** 50 sections, 1:1 with the PDF outline's 50 entries. 42 titles were found on their page. The 8 "Week N:" titles were not, because the page prints "WEEK N" without the colon, so that text stays in the section body. Section starts are still correct, because those headings sit at the top of their pages.
- **Partial, 8 of 67 chunks, generator output only:** 60 facts extracted, 60 quotes located. At least 6 come from the "How they'll ask it" block in "What the course covers" (page 2). "Quick recall" blocks have not been reached. Those blocks are inside normal sections because they are not in the outline.
- **Other findings:** printed footers enter section text (for example "5 / 122" on PDF page 2), and fact pages use the PDF page number, which differs from that printed number. On a daily cap, `provider.py` still spends all its retries, and each attempt is another request.

### Quota fix and sample run (2026-11-02)
- **Done:** generator is `openai/gpt-oss-120b` and checker is `qwen/qwen3.8-27b`, both on Groq (`qwen3.6-27b` does not exist there; 3.8 is the closest non-OpenAI model). Gemini stays optional, chosen by `GENERATOR_BASE_URL`. Added `REQUESTS_PER_DAY` per role with a counter in `provider.py`; an immediate stop on a daily limit, with no retries; chunks up to 6000 chars; one `gate0_fact` call per chunk; `SKIPPED_HEADINGS` in `prompts.py`; `N / N` footer removal; per-role RPM and TPM throttling using real token counts. CLAUDE.md, SPEC, PLAN, README, `.env.example` and the P05 command are updated, including one generator call plus one batched regeneration for P05.
- **Added because of what the run showed:** same-family detection now compares model families, because both roles share a host. Chunks pack several sections together, because 50 short sections would otherwise still mean 50 calls. `gate0_fact` replies are compact (`{"faithful":[ids],"not_faithful":[{id,reason}]}`, so only rejections carry a reason) with `CHECKER_MAX_TOKENS=1000`, because Qwen's free tier allows 1000 output tokens per minute. "Request too large" stops without retrying. `json_validate_failed` is retried.
- **Tests:** pytest 103 passed on the last full run. `check_llm.py` found both models. The real checker got 7 of 7 known pairs right with the new prompt.
- **Sample stats, NOT final:** 50 sections, all from the PDF outline. Before de-duplication: 191 extracted, 170 kept, 3 dropped, 18 unfaithful, so 11.0% lost. Duplicates, root and final fact count are unknown, because the last run was stopped by the system for low memory before its local embedding step. No clean total time exists, because the run hit limits and was restarted. Requests counted today, including failed runs and retries: generator 35, checker 24, for 11 chunks.
- **Finish without LLM calls:** when memory is free, run `scripts/ingest_stats.py`; every chunk is cached, so it should send no requests.
- **Filter check:** all 13 marker headings, all 24 question-then-answer lines and all `N / 122` footers are gone from the parsed text.
- **BLOCKING DEFECT, coverage:** facts cover only about 25% of the source text. In most chunks the last quote ends well before the chunk does (chunk 0: 2 facts, ending 4% into 5760 chars; chunk 6: 9%; chunk 8: 12%; chunk 10: 13%). The model stops early, and no gate catches it because what it returns is accurate. Likely cause, not yet verified: long replies hit an output cap and fail JSON validation, and retries then return short valid replies. 35 generator requests for 11 chunks fits that. Do not treat this textbook as complete or start P05 on it.
- **New limits found:** `openai/gpt-oss-120b` has 200,000 tokens per day (rolling, and exhausted by this run). Groq's headers show only RPD and TPM; TPD and OTPM appear only in error messages. Two earlier stats runs and one verification script also used this quota.
- **Other issues:** `gate0_fact` rejections look too strict in places, such as a fact using the section's topic name ("McCumber model") that its quote does not repeat, because the checker never sees headings. Both roles now depend on one vendor and one key, so a Groq outage stops both. Whether a `max_tokens` reservation paces the P05 gate calls is unmeasured. Repo privacy was checked with an anonymous GitHub lookup returning 404, which is consistent with private.

### Moved to Fedora Linux (2026-11-04)
- **Done:** rebuilt the machine-specific parts on Deepesh's Fedora 44 laptop. No tracked code was changed. Deleted and rebuilt the Windows `api/.venv` (Python 3.12.14 via uv, the same minor version as Windows; torch 2.15.0+cpu) and the Windows `node_modules` in `web/` and `contracts/` (`npm ci` from the lockfiles). `api/.cache/llm.sqlite` was kept, so cached LLM replies still cost nothing.
- **Toolchain here:** Node 22.23.1 (Windows had 24), Docker 29.9 + Compose v5.6, system Python 3.14 (not used, the venv is 3.12).
- **How to run on Linux (bash):** new `scripts/dev.sh <setup|db|migrate|api|web|test>`, the Linux twin of `dev.ps1` (Windows). CLAUDE.md and README now have separate Windows and Linux command blocks. `.gitattributes` forces LF on `*.sh`.
- **Test results:** alembic upgrade to 0002 on a fresh Docker volume; pytest 103 passed; hardhat test 1 passing on Node 22 (Hardhat 2.29.1); `npm run build` passed; `./scripts/dev.sh test` passed the same three; `dev.sh db/migrate/api/web` brought the stack up, web on :3000 returned 200; live `/health` → `{"ok":true,"db":true}` with CORS for localhost:3000; `check_llm.py` → both OK (generator openai/gpt-oss-120b, checker qwen/qwen3.8-27b).
- **Issues:** the Postgres volume here is new, so the Windows dev database (and its data) did not come over; it was empty apart from migrations anyway. Python packages are unpinned, so uv installed the latest versions; a `pip freeze` lock would make machines match. The open P02 coverage defect still stands.

### P03 registry contract (2026-11-04, Fedora)
- **Done:** `contracts/contracts/SmartQuizRegistry.sol` (OpenZeppelin v5 `Ownable` + `MerkleProof.verifyCalldata`; Document and Quiz structs; events `DocumentRegistered`, `QuizCommitted`; custom errors `UnknownDocument`, `AlreadyRegistered`, `AlreadyCommitted`; exact SPEC section 6 signatures). `contracts/scripts/deploy.ts` (owner = issuer address; on `amoy` it rewrites only the `REGISTRY_ADDRESS` line of `.env`, keeping line endings; on `localhost` it sends the issuer 100 test ETH and never touches `.env`). `api/scripts/merkle_fixture.py` writes `contracts/test/fixtures/merkle.json` (7 facts, one non-ASCII) from `app/chain/merkle.py`, no second implementation. Placeholder contract and test removed.
- **How to run:** Linux `cd contracts && npx hardhat test`; Windows `Set-Location contracts; npx.cmd hardhat test`. Regenerate the fixture: `cd api && .venv/bin/python scripts/merkle_fixture.py`.
- **Test results:** hardhat 13 passing: register + event + getter, duplicate register reverts, onlyOwner for register and commit, commit happy path, re-commit reverts, unknown doc reverts, getters zero for unknown ids, Python text_hash/leaf recomputed in Solidity, verifyFact true for all 7 Python proofs (including the promoted node), false for a one-byte leaf change, an unknown document and a one-word text edit.
- **Local deploy:** `npx hardhat node` + deploy to localhost → `0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512`, `.env` sha256 unchanged.
- **Amoy deploy:** `REGISTRY_ADDRESS=0x4093F5F19Eacf69Fc8144A1d39A3f6838D4dc518`, owner (issuer) `0x795572DC3409686907430dedF753EfD5d0A5ed39`, tx https://amoy.polygonscan.com/tx/0x457d82bc0c8bad8f2090d6e5cd018f42f5a33dd09e8135240bbe44ff50afeeef. Only the REGISTRY_ADDRESS line of `.env` changed.
- **Decisions SPEC did not cover:** `verifyFact` returns false (no revert) for an unknown document; events index `docId`/`quizId`.
- **Issues:** the deploy cost about 0.024 POL; 0.076 POL is left at 30 gwei, roughly 20 more transactions. Top up from a faucet before rehearsals. `/security-review` not yet run.

### P02 coverage defect fixed (2026-11-04, Fedora)
- **Root cause (verified):** `openai/gpt-oss-120b` at its default reasoning effort spent its output on hidden reasoning. Long chunks came back either empty (Groq `json_validate_failed`, `failed_generation` of 0 chars) or as a short valid reply after a few facts (chunk 0: 2 facts, ending 4% into 5760 chars). Not an output-token cap on the JSON itself.
- **Fix:** `GENERATOR_REASONING_EFFORT=low` (new per-role `*_REASONING_EFFORT` settings in config, provider and `.env.example`, sent only when set); a coverage-first extraction prompt with shorter quotes; in `extractor.extract_facts` one follow-up call on the rest when quotes end before 75% of a chunk, and a split into two halves when a reply fails JSON twice. `json_validate_failed` is now retried once (was 5 times, each costing thousands of tokens), then raises `BadJSONError`. SPEC section 3 updated.
- **Sample stats (final, real models):** 50 sections, **482 facts kept** (was ~170), 4 dropped, 100 unfaithful (17%), 2 duplicates, root `0xdc79cf855291af5c7df949392bf9b29399709267b06e760ae242c6757c045a0d`. Kept-fact quotes cover **74.1%** of section text (was ~25%); the rest is mostly headings and lines with no claim. 75.8 s with all LLM replies cached (embedding only). A re-run sends 0 requests and gives the same root.
- **Requests today:** generator 26, checker 23 (including the 9-minute failed run before the split fix).
- **Tests:** pytest 121 passed (new: follow-up on a lazy reply, no follow-up on a full one, split on bad JSON, no split on a daily limit, reasoning_effort sent only when set, BadJSONError after two JSON failures).
- **Issues for Deepesh to review:** `gate0_fact` rejects 17%. Many rejections look too strict ("Quote lacks context of 'example'", "Quote is term, fact defines it") because the checker sees no headings. That loses facts but never admits an unsupported one, so it was left as is.

### P04 chain service and document registration (2026-11-04, Fedora)
- **Done:** `api/app/chain/service.py` `ChainService` (web3.py 8): ABI copied to `api/app/chain/abi/SmartQuizRegistry.json`; issuer from ISSUER_PRIVATE_KEY (never logged, key errors are not passed on); chain id read from the RPC; Polygon PoA middleware; one process-wide lock around nonce → send → receipt (120 s); EIP-1559 fees with a 25 gwei minimum tip on Amoy; gas estimate × 1.2; custom-error names decoded from reverts. Methods `register_document`, `commit_quiz`, `verify_fact`, `get_document`, `get_quiz`; `chain_id_of(uuid)` = keccak256 of the UUID string. `register_document` on an already-registered document with the same root recovers the original tx from `DocumentRegistered` logs (receipt-timeout case). `get_chain()` caches the service and fails fast for 30 s after a failure. P02 hook `register_document_onchain` implemented; `DocumentOut.explorer_url` is null unless chain id is 80002; `POST /documents/{id}/register` retries (409 unless ready, 404 for another user's document, 503 on failure when CHAIN_OPTIONAL=false).
- **Test safety:** `tests/conftest.py` now blanks LLM keys and all chain settings for every test, so no test can reach Groq or Amoy with `.env` values. `local_chain` deploys a fresh registry on a local Hardhat node with Hardhat's public key #0 (skips without a node); `chain_down` points at a closed port.
- **How to run the chain tests:** start `npx hardhat node` in `contracts/` (Windows `npx.cmd`), then pytest. Without a node those tests skip.
- **Test results:** pytest 121 passed with a node running (10 chain tests: register/read/verify/commit, promoted-leaf proofs, tampered leaf false, AlreadyCommitted/UnknownDocument decoded, re-register returns the original tx, explorer null off Amoy, upload → confirmed and root on chain, chain down → ready + offline, register retry after an outage, 503 with chain required, 404 for other users).
- **Real Amoy run:** uploaded `samples/sample.pdf` through the API (dev DB, user `p04-check@example.com`). The first attempt went offline with `ExtraDataLengthError` (Polygon PoA headers), fixed with web3's `ExtraDataToPOAMiddleware`; `POST /documents/{id}/register` then confirmed it. Document `9756c9c4-54bd-41d4-9ef5-8148c09dc12b`, tx https://amoy.polygonscan.com/tx/0xb943ab1121c152b9049dd84937ea3c76299dbb2fe30633060f45c38cfbb29d77. `getDocument` on chain returns the same root and 482 facts. Cost ≈ 0.0024 POL; 0.0735 POL left.
- **Issues:** Hardhat tests cannot catch PoA-only problems, so keep one real Amoy check in P11.

### P05 verified quiz generation (2026-11-04, Fedora)
- **Done:** `api/app/quiz/` — `select.py` (tiers unused → last wrong → used never answered → oldest tested; largest-remainder spread by section fact count, seeded per quiz; ≤ 2 targets per concept; interleaved across sections; retests ask for the other bloom level), `generate.py` (ONE generator call per round, shape validation), `gates.py` (Gate 1 grounding, Gate 3 solvability with shuffled options mapped back, Gate 4 blind dependence; one batched checker call each, missing ids retried once with attempt=1 then fail closed), `dedup.py` (SPEC fingerprint, then stem cosine ≥ 0.85 vs this user + document), `metrics.py`, `prompts.py`, `job.py` (background job, in-memory progress, batched regeneration with attempt=1 only when needed, spares, `generation_log` rows for every gate, validation error and duplicate with candidate_id and `same_family_fallback`). Routers `quizzes.py` (POST, GET, progress, start) and `metrics.py`. Interrupted `generating` quizzes become `failed` at startup. FAKE provider handlers for every new task.
- **How to run:** API as usual; `POST /quizzes {document_id, num_questions, time_limit_sec}` then poll `/quizzes/{id}/progress`.
- **Tests:** pytest 167 passed (30 in `test_quiz.py`): `generating` returned at once, ready with questions hidden until start, start sets `started_at` once, 409 before ready, ownership 404s, two quizzes share 0 targets and 0 fingerprints, spread 2/2/2/2 over 4 sections, one generator call when all pass, failures share one attempt=1 regeneration, failing twice drops (quiz `failed` with no questions), Gate 3 wrong choice rejects, `gate_results` shape and dependence/flag maths, same-family logging and metrics, gate0 rows excluded from question metrics, earlier unattempted quiz counts as used but context facts do not, failed quizzes do not count, concept cap, retest bloom flip, validation shapes, fingerprint matches the SPEC example, cosine duplicates blocked and counted.
- **Real run on sample.pdf (document `9756c9c4-…`, real Groq models, Amoy):** quiz 1 `4e4d9a98-ad2f-49a9-a0b0-d6276019528b` 24 s, 13 candidates, 10 accepted, 0 rejected. Quiz 2 `dbc64930-3cfb-4f95-a27a-b67dc80cd892` 105 s (one Gate 1 rejection → the batched regeneration), 10 accepted, 1 rejected. **0 repeated target facts.** MetricsOut: candidates 26, accepted 20, rejected gate1 1 / gate3 0, duplicates 0/0, flagged_general 13, avg_dependence 0.33, repeat_rate 0.0, same_family_checker_used false. Requests today: generator 28, checker 35.
- **Spec changes:** generator reply is `{"questions":[{target_idx,…}]}`; QuizOut adds `started_at` and `submitted`; `rejected_by_gate` may include `generator_error`; batching and spares described in SPEC section 4.
- **Prompt change after the run:** 13 of 20 questions were answerable from general knowledge (e.g. "What term describes a safe app identified as malware?" → false positive, blind confidence 100), and one was a NOT question ("Which is NOT a built-in Windows XP role?") that a list of roles cannot prove. The generator prompt now asks for the notes' specifics and bans NOT/EXCEPT stems. Not yet re-measured; P11 measures it.
- **For Deepesh to check:** question quality in quizzes 1 and 2 above (dev DB). `/code-review` not yet run.

### P06 quiz commit and attempts (2026-11-04, Fedora)
- **Done:** `api/app/chain/quizhash.py` (salt = 16 random bytes hex; canonical JSON exactly as SPEC section 8; keccak). `commit_quiz_onchain` in `job.py` runs at stage `committing`: salt + hash, then `commitQuiz(keccak(quiz UUID), keccak(document UUID), hash)`; the quiz becomes `ready` only after it. With CHAIN_OPTIONAL=false a failed commit makes the quiz `failed`; with true it is `ready` + `offline`. `POST /quizzes/{id}/attempts`: 409 unless ready and started, 409 if uncommitted while the chain is required, 409 after time_limit + 30 s, 409 on a second attempt (row lock), 422 on a wrong answer count or value; AttemptResult with sources from every cited fact (text, page, section heading) and weak concepts from wrong target facts; `fact_coverage` upsert for the target fact only.
- **Tests:** 16 in `test_attempts.py`: exact canonical JSON and hash, position order, every hashed field changes the hash and non-hashed fields do not, salt format, stored hash recomputes and changes after editing a stored stem, commit on a local chain before `ready` with the on-chain hash equal to `quiz_hash`, required chain down → `failed`, optional chain down → ready + offline, uncommitted + required → 409, before start → 409, generation time and reading before start not counted, time limit + grace → 409, scoring + sources + weak concepts + coverage values, context facts get no coverage row, fact_idxs hidden before and shown after, one attempt and answer validation, wrong answers come first once unused facts run out (with the other bloom level).
- **Real run:** quiz 1 commit tx https://amoy.polygonscan.com/tx/0x934cc7a6c42c8e1c0b96f764d46dc704ba7c7d49e3896727bff61db0ec53c780, quiz 2 https://amoy.polygonscan.com/tx/0x44713c6022fbc392dea8431c7dce6bf4e2ddf33b3b1403eb757990a6267f2a0b. Quiz 1 attempt: 409 before start, start returned 10 questions with no answer keys, 7/10 scored, Source chips and 3 weak concepts returned, `fact_idxs` present only after submit.
- **Note:** with the FAKE LLM a retest repeats the earlier stem, so the cosine backup drops it; real stems at the other bloom level differ. Real retests of one fact may still sometimes exceed 0.85 and be dropped, as SPEC intends.

### P07 closed-book chat (2026-11-04, Fedora)
- **Done:** `api/app/chat/` (`retrieve.py` top 8 facts by pgvector cosine and the 2 nearest distinct section headings; `answer.py` threshold → abstain, generator answer citing `[F<idx>]`, post-check that citations are a non-empty subset of the retrieved facts, one retry with attempt=1, then abstain; `prompts.py`), `POST /chat` (404 for another user's document, 409 unless ready, message 1–1000 chars). A model reply of `{"not_covered": true}` abstains without a retry. `api/scripts/chat_calibrate.py <document_id> [--write]` (no LLM calls).
- **Calibration on samples/sample.pdf (482 facts):** in-scope best similarity 0.75–0.89, out-of-scope 0.40–0.63 → **CHAT_MIN_SIM = 0.69**, 0 of 20 misplaced. Written to the CHAT_MIN_SIM line of `.env` and `.env.example` (with a comment giving both ranges). Query embeddings use no bge instruction prefix; the prefix separated the sets less well (gap −0.02 vs −0.01 before the question fix).
- **Calibration finding:** "What happened to AIIMS Delhi's servers?" scored 0.62 because the textbook has **no AIIMS fact**: extraction skipped the sentence "AIIMS Delhi (Nov–Dec 2022): five servers hacked." Abstaining is correct closed-book behaviour, so the question was replaced with an in-scope one (HIPAA) rather than lowering the threshold. It is an example of the remaining ~26% extraction gap.
- **Tests:** 26 in `test_chat.py`: the 20 calibration questions run on the real textbook (`tests/data/sample_facts.json`, exported by the calibration script) with real embeddings and the FAKE generator (in-scope → answered with ≥ 1 citation, out-of-scope → abstained with 2 sections); a citation outside the retrieved facts retries with attempt=1 then abstains; a missing citation retries and can recover; `not_covered` abstains with no retry; below the threshold the generator is never called; citation parsing; ownership.
- **Real run:** "Why did the Target breach go undetected…" → answered at 0.78 with [F77] [F78] [F237]. "Who painted the Mona Lisa?" → abstained at 0.47 with "Access control technology" and "Why GRC". The last sentence of the answer joins F237 (an IDS only raises an alarm) to the case as a mild inference; Deepesh should judge whether the prompt needs to be stricter.

### P08 verify endpoints (2026-11-04, Fedora)
- **Done:** `api/app/routers/verify.py`, public, read-only, no answer keys. `GET /verify/question/{id}` (409 "Available after the quiz is submitted" until an attempt exists; per cited fact: text, page, text_hash, leaf, proof rebuilt from the document's leaves, `verified_on_chain` from the contract; db_root, onchain_root, doc_id_onchain, registry address, registration explorer link). `POST /verify/fact` (recomputes text_hash + leaf from the given text, uses the stored proof for that idx). `GET /verify/quiz/{id}` (recomputes quiz_hash from stored questions + salt with `quizhash.py`, reads the on-chain hash; 409 unless ready). Leaves cached in memory per (document, root). 30 requests/minute per IP → 429.
- **Offline rules:** a document never registered (or a quiz never committed) is `offline` with nulls, never false. A failed chain read is `offline` with nulls when CHAIN_OPTIONAL=true and 503 when false. A quiz committed per our records but missing on chain gives `match: false` (a real mismatch).
- **Tests:** 9 in `test_verify.py` (local Hardhat chain): 409 before the attempt; every cited fact verified true, proofs verify locally, roots equal, no answer fields; real text true and one-word edit false; quiz match true, then false after changing a stored answer_index; chain down + optional → offline nulls on all three endpoints; chain down + required → 503 on all three; never registered → offline nulls; unknown ids 404; rate limit 429 on request 31. Full suite: **202 passed** (with a local node running).
- **Real Amoy run (dev DB):** question `29495ccd-1f47-4031-ba3d-d86df4c89a4a` (quiz 1, submitted) → fact 92 verified true with a 9-hash proof, onchain_root = db_root. `/verify/fact` with the real text → true; "false positive" → "false negative" → false. `/verify/quiz/4e4d9a98-…` → match true, hash `0xc9b3b7cf…e8c8`. A question of the unsubmitted quiz 2 → 409. Demo steps 5 and 6 work at the API level.
- **Issues:** the rate limiter is per process and in memory (fine for one uvicorn worker). `/security-review` not yet run.

### P09 web core screens (2026-11-04, Fedora)
- **Done:** deck theme in `web/app/globals.css` (navy #13203B panels, #F6F4EF paper, #E8913F accent; Space Grotesk headings, IBM Plex Sans body via next/font). `lib/types.ts` (SPEC shapes), `lib/api.ts` (one function per endpoint, real API only), `lib/use-load.ts`, `components/ui.tsx` (Button, Card, NavyPanel, Loading, ErrorBox, `ChainBadge`, Hash with copy, Stat, ExplorerLink), `components/shell.tsx` (header, auth guard), `components/auth-form.tsx`. Pages: `/signup`, `/login`, `/` (documents + drag-and-drop upload, polls every 3 s while ingesting), `/documents/[id]` (upload card with counts, shortened Merkle root + copy, Amoy link, ChainBadge, "Retry chain registration" when offline; collapsible section tree; fact panel; Start quiz / Ask a doubt / Metrics; `?section=` opens and scrolls to a section), `/quiz/[id]` (progress "Verifying question 6 of 10 · 3 rejected so far" → start screen with quiz hash, commit link and ChainBadge → Begin → countdown, one question per screen, progress dots, "General knowledge" tag, auto-submit at 0:00, no sources before submit → results with score, correct/incorrect, Source chips with fact, page and section, weak concepts, "New quiz (no repeats)", "Verify this quiz", per-question Verify link), `/documents/[id]/metrics` (stat tiles, accepted vs rejected bars, top reasons, duplicates, same-family warning banner).
- **Next.js 16 notes:** with `cacheComponents`, each dynamic route is a server `page.tsx` wrapping a client view in `<Suspense>` (useParams/useSearchParams suspend otherwise). The React Compiler lint rule `set-state-in-effect` is satisfied with `useLoad` (state set only in promise callbacks) and `useSyncExternalStore` for the token.
- **Tests:** `npm run build` passes; `npm run lint` and `tsc --noEmit` clean. Headless Chromium walkthrough (Playwright, real API, real LLM, Amoy) of demo steps 1–3: logged-out `/` → `/login`; signup; upload `sample.pdf` → ready (482 facts, On Polygon Amoy, explorer link); fact panel; Start quiz → progress → start screen with commit link → 10:00 timer, 0 sources before submit → submit → score, 10 Source chips, weak concepts; metrics tiles. No console or page errors. Mobile (390 px): no horizontal scroll.
- **Chain unreachable run:** API started with `AMOY_RPC_URL=http://127.0.0.1:9`. A new upload became Ready with "⚠ Chain offline" and a Retry button, and no explorer link. After restoring the RPC, `POST /documents/{id}/register` confirmed it (tx https://amoy.polygonscan.com/tx/0xe198de0f4d428d069d3b0dd41d94cba72c0087a07054175154e9356b34c7a422).
- **Bug found and fixed in the walkthrough:** the first run showed no theme at all. `next build` run while `next dev` used the same `web/.next` left the dev server serving the old `globals.css`. Fix: stop dev, delete `.next`, restart. README now warns about it.
- **Quiz-quality fixes found in the walkthrough:** the correct option was at position A in 7 of 10 questions. The server now shuffles options after validation (seeded by candidate_id, before gates and hash) and the prompt no longer controls the position. The distractor rule now asks for options as specific and plausible as the answer, built from the notes' own terms, never extreme. Average dependence on the next real quiz rose from 0.09 to 0.20; still low, because the blind checker knows general cyber security. That is a real finding for the metrics slide, not hidden. pytest 203 passed.
- **Issues:** the results screen after a refresh relies on this tab's sessionStorage (there is no GET attempt endpoint in SPEC); without it, the page shows "This quiz has been submitted" with sources and Verify links but no per-question correctness. Aravindh should test the screens.

### P10 chat and verify pages (2026-11-04, Fedora)
- **Done:** `/documents/[id]/chat` (message list; `[F214]` rendered as chips that open the fact text and page in a side panel; abstained replies in a muted dashed card with "This isn't covered in your material" and the 2 nearest sections linking to `/documents/[id]?section=<id>`). `/verify` (public, works logged out; Question and Quiz tabs; reads `?question=` / `?quiz=`; per fact an editable textarea, Re-check calling `POST /verify/fact`, leaf, collapsible proof, DB root vs on-chain root with a match pill, registry address; big badges: green "Verified on Polygon Amoy", red "Not verified" (false only), amber "Chain offline" for null; 409 shows "Available after the quiz is submitted."; Quiz tab shows recomputed vs committed hash, match badge and commit link). Hashes monospace, shortened, with copy buttons.
- **Tests:** `npm run build`. Walkthrough of demo steps 4–6 in headless Chromium: in-scope doubt → answer with 2 fact chips, chip opens F77 (page 4); "Who painted the Mona Lisa?" → not covered + "Access control technology · Why GRC", link opens the section in the textbook; Verify (logged out) → "✓ Verified on Polygon Amoy"; one-word edit + Re-check → "✗ Not verified"; quiz tab → "✓ Match". Mobile 390 px: no horizontal scroll. Chain unreachable: question and quiz verify show the offline badge, 0 red verdicts, also after Re-check. The 409 state was checked through the API in P08 (the walkthrough submits before verifying).

### P11 Review 1 integration (2026-11-04, Fedora)
- **Done:** `api/tests/test_e2e.py` (signup → upload samples/sample.pdf → ready and registered → quiz 1 ready and committed → start → verify question 409 → attempt → quiz 2 with 0 repeated targets → chat in-scope cited and out-of-scope abstained → verify question true, one-word edit false → verify quiz match; FAKE LLM, local chain, CHAIN_OPTIONAL=false). `api/scripts/seed_demo.py` (HTTP against the running API: demo user, upload + ingest, quiz 1 ready and NOT started, prints IDs, explorer links, MetricsOut and timings). README "Run the demo" for Linux and Windows.
- **Checklist run (real Groq models, Polygon Amoy, API with CHAIN_OPTIONAL=false):** seed + two browser rehearsals in headless Chromium with a fresh user each. Not a fresh database: the dev DB keeps today's test users. The tests recreate `smartquiz_test` from migrations each session, which covers a clean schema.
  1. Upload → textbook, 482 facts, root `0xdc79cf85…7c045a0d`, On Polygon Amoy + explorer link — **pass** (both rehearsals).
  2. Timed 10-question quiz → progress, start screen with commit link, metrics with rejections and reasons — **pass**.
  3. Submit → score, 10 Source chips, weak concepts; second quiz → **0 repeated target facts** (10/10 vs 10/10, both rehearsals) — **pass**.
  4. Chat: in-scope cited answer (F77, F78…), out-of-scope "not covered" + 2 nearest sections — **pass**.
  5. Verify question → "Verified on Polygon Amoy"; one-word edit → "Not verified" — **pass**.
  6. Verify quiz → recomputed hash matches the on-chain hash — **pass**.
  - Rehearsal wall time 206 s and 253 s (both under 6 minutes, including ingestion and two quiz generations, which are pre-done on stage). No console or page errors. `same_family_checker_used` is **false**.
- **Stage demo seeded:** user `demo@example.com`, document `3ce3f1e0-fb57-4d46-910f-64658822e850` (registration https://amoy.polygonscan.com/tx/0x5aafebdeef1e19971e5de8726d0e7814c7fc438606bfe2079e907c4fe0bed924), quiz 1 `b16a8c21-b3e9-4044-8af0-18b177d48664` ready and not started (commit https://amoy.polygonscan.com/tx/0x883fc6fdd1d580d3037db1a969dfc7b199f6b1351609a3f74d2d32db3eb5370e), 17 candidates / 10 accepted / 4 generator_error (3 items the model skipped, 1 citing too many facts), avg dependence 0.19, flagged general 9. Timings: ingestion 30 s (LLM replies cached; a cold run of the chapter took about 3.5 min), quiz generation 48 s.
- **Tests:** `./scripts/dev.sh test` → pytest **204 passed** (with a local Hardhat node; chain tests skip without one), hardhat **13 passing**, web build OK; lint clean.
- **Budget left:** issuer wallet **0.030 POL** (~12 transactions). Requests today: generator 39, checker 70 of 1000 each.

## Review 1 summary (mapped to the PLAN cut list)
| # | Item | State |
| --- | --- | --- |
| 1 | Textbook ingestion with spans + root | **Done.** 482 facts on sample.pdf, quotes located with offsets, gate0_fact, root on chain. Coverage 74% of section text. |
| 2 | Coverage-based generation with gates 1 and 3 | **Done.** One generator call + one batched regeneration, gates 1/3/4, fingerprint + cosine duplicates, 0 repeats between quizzes. |
| 3 | Doc root on chain + Verify page with tamper test | **Done.** Registry on Amoy `0x4093F5F19Eacf69Fc8144A1d39A3f6838D4dc518`; Verify true/false/offline states. |
| 4 | Quiz commit before attempt | **Done.** Committed before `ready`; attempts refused when uncommitted with the chain required. |
| 5 | Closed-book chat abstain | **Done.** CHAT_MIN_SIM 0.69 calibrated (0/20 misplaced). |
| 6 | Dependence score | **Done, weak result.** Average 0.19–0.20: the blind checker answers most questions on a general cyber-security course. Shown honestly on the metrics page. |
| 7 | Metrics page | **Done.** |

**Partially done / open:**
- Extraction misses some sentences (e.g. AIIMS Delhi), and gate0_fact rejects 17%, some too strictly. Deepesh should review fact quality.
- Question dependence is low; distractors improved after the walkthrough, but this is the main quality lever for Review 2.
- Results after a page refresh rely on sessionStorage (no GET attempt endpoint).
- Not done (not in Review 1 scope): distractor gate, Bloom ladder, mastery, Review 2 items in PLAN.
- Not run yet: `/code-review` and `/security-review` (P03, P05, P08, P11 ask for them). No commits made: Deepesh commits and pushes.

### Review 1 docs and presentation (2026-11-04, Fedora)
- **Done:** added `docs/SUMMARY.md` (one-page overview: research basis, what each command built, results, references, open issues, Review 2). Replaced the stale 2026-11-02 block under "Updates" with a current one. CLAUDE.md: removed "no existing code", added the Fedora laptop and `docs/SUMMARY.md` to the read list (no rules changed). README: status line, command table marked done, SUMMARY in the docs list. PLAN: title marked completed and an "Outcome" section added; the original plan is kept below it. SPEC unchanged.
- **Outside the repo:** a three-speaker presentation script was generated at `~/Downloads/SmartQuiz_Review1_Presentation_Script.pdf` (research, unique features, what was built, demo script, results, Q&A). It is not tracked in git.
- **How to run:** nothing to run; docs only.
- **Tests:** not run; no code changed.
- **Issues:** none new. No commits made: Deepesh commits and pushes.

### Windows demo setup for Review 1 (2026-11-04, Windows)
- **Done:** moved the demo to Balaji's Windows laptop. `AMOY_RPC_URL` in `.env` now points to a private Alchemy Polygon Amoy endpoint, because the public RPC kept dropping (chainId 80002 confirmed). The issuer key is set and derives to `0x795572DC3409686907430dedF753EfD5d0A5ed39`, which is the registry `owner()`, so it can call `registerDocument` and `commitQuiz`. `CHAIN_OPTIONAL=false` set in `.env` for the demo. The repo had been copied from Fedora with Linux-only `api/.venv` (uv, `/home/deepesh/...`) and `web/node_modules` (`swc-linux-*` only); both were rebuilt for Windows (`py -3.12 -m venv api\.venv` + `pip install -r requirements.txt`; `npm.cmd ci` in `web` and `contracts`, `web/.next` deleted). No code changed.
- **Demo data re-seeded:** the Windows Postgres was empty and no Fedora dump was available, so `seed_demo.py` was re-run against the Windows API (2 transactions, LLM replies mostly from `api/.cache`). New IDs:
  - document `6045356b-3122-46d5-8192-def96b4728fb`: 50 sections / 482 facts, dropped 4, unfaithful 100, root `0xdc79cf85…7c045a0d` (same as Fedora), registration https://amoy.polygonscan.com/tx/0x99169f8837eeb98590d75739623f5d7046e0a046ba3ee9a44388a1de22844e38
  - quiz 1 `904867cf-2663-4609-b869-36adb89e2e22`: ready and committed, not started, commit https://amoy.polygonscan.com/tx/0x8fac4f27672300edf6557e74153825fdef1a4d9a0e6ced1c806a275da658ea86. 13 candidates / 10 accepted / 0 rejected, flagged general 7, **avg dependence 0.36** (Fedora quizzes: 0.19–0.20; it varies per quiz), same-family checker not used.
  - The Fedora IDs (`3ce3f1e0…`, `b16a8c21…`) exist only in the Fedora DB; slides and the presentation script must use the new ones.
- **Checks (all pass):** API `/health` ok + db, `/docs`, web `/`, `/login`, `/verify` 200; Alembic at `0002`; pgvector 0.8.7; `/verify/quiz` on quiz 1 → match true, recomputed = on-chain hash; `/verify/fact` fact 91 real text → true, "vulnerable" → "banana" → false; `chain_status` confirmed throughout, no offline/null. Balaji then tested the screens in the browser, which created two more demo-user quizzes (`66fa8511…`, `42ef23a2…`, committed and attempted); quiz 1 stays unstarted.
- **How to run:** Docker Desktop, then `powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 db`, then `... dev.ps1 api` and `... dev.ps1 web` in separate windows. Log in as `demo@example.com` (password per README).
- **Tests:** pytest not run (no code changed); checks above only.
- **Issues:** issuer balance **~0.015 POL** after 4 transactions tonight, about 3–5 more at the observed 0.003–0.0045 POL each; top up before the review. Each on-stage "New quiz" costs one. `npm ci` reports 46 audit warnings (not addressed).

### Review 2 planning (2026-11-26, Fedora)
- **Done:** Review 2 plan approved and written. `docs/PLAN.md`: Review 2 section on top (decisions, design per feature, R00–R12 sequence ≈ 30 h, day plan to Monday 2026-11-30, 12-step final demo, cut list, risks); the Review 1 plan is kept below with headings one level down. `docs/SPEC.md`: new section 9 (Review 2 shapes, 9.1–9.11), sections 1–8 unchanged. `CLAUDE.md`: Fedora is the only operator laptop from now on; rules 1, 4, 5, 6, 7 and Hashing extended for distractors, review mode, Gate 2, short-answer grading, hash v2 and credentials; new env vars; Claude never commits. `.claude/commands/r00-…r12-*.md` added; `/next` and `/status` point at R00–R12. `.env.example`: CREDENTIALS_ADDRESS, EDUCATOR_PRIVATE_KEY, CUSTODY_SECRET.
- **Decisions:** badges go to the learner's pasted wallet address, custodial address as fallback; the team are the educators (separate educator wallet signs EIP-712, issuer pays gas); Review 1 registry unchanged, second contract `SmartQuizCredentials.sol`; quiz hash v2 with `hash_version`; FSRS as a separate review mode so practice selection (rule 4) is unchanged; submission = code + mini project report + slides (R12).
- **How to run:** nothing to run; docs only. Next: `/compact`, then `/r00-cleanup`.
- **Tests:** not run; no code changed.
- **Issues:** the issuer wallet needs ≥ 0.25 POL before R07 (≈ 0.015 on the old wallet). A new issuer wallet is being set up: the registry owner is still the old issuer `0x7955…ed39`, so R00 checks ownership and asks whether to transfer it or redeploy. No commits made: Deepesh commits and pushes.

### New issuer wallet (2026-11-26, Fedora)
- **Done:** new testnet-only issuer `0x6fa045726eF3F0d84eb100e159517930C249b665` (MetaMask in Brave), funded with 1.0 POL from a faucet. Registry `0x4093F5F19Eacf69Fc8144A1d39A3f6838D4dc518` ownership moved from the old issuer `0x795572DC3409686907430dedF753EfD5d0A5ed39` with `transferOwnership`: https://amoy.polygonscan.com/tx/0x486021e38a91785836a38e778d0a778ad232dc1f51bd88863b5b208f3e6902c9 (nonce 23). `.env` `ISSUER_PRIVATE_KEY` now holds the new key; checked that it derives to the new address and that `owner()` returns it. Review 1 roots, commits and proofs are unaffected (only the owner changed).
- **Added:** `contracts/scripts/transfer-owner.ts` (`NEW_OWNER=0x… npx hardhat run scripts/transfer-owner.ts --network amoy`). It checks the signer is the current owner, sets an Amoy-safe fee (network tip with a 25 gwei floor, +50%; max fee = 2 × base + tip) and uses the confirmed nonce, so a rerun replaces a stuck attempt.
- **Finding:** the first send used Hardhat's default fee and stayed pending (Amoy needs a tip ≥ 25 gwei; the network asked ~31 gwei). Any new Hardhat script that sends on Amoy (e.g. R07 deploy) must set fees the same way; `deploy.ts` does not yet.
- **Tests:** contracts compile; script type-checks; run live on Amoy as above.
- **Issues:** the old issuer key can no longer register or commit; Balaji's Windows `.env` (old key) will fail on chain calls. The old wallet keeps ~0.01 POL. The public RPC `rpc-amoy.polygon.technology` was down today; `polygon-amoy-bor-rpc.publicnode.com` and `polygon-amoy.drpc.org` work.

### R00 cleanup (2026-11-26, Fedora)
- **Done:**
  - `GET /attempts/{attempt_id}` (new `api/app/routers/attempts.py`, owner only, 404 otherwise) and `QuizOut.attempt_id` (SPEC 9.1). Submit and GET share `_build_result`, so both return the same `AttemptResult`; the attempt id is generated before scoring.
  - Web `/quiz/[id]` reloads results with `getAttempt(quiz.attempt_id)`; sessionStorage is only the fallback.
  - `gate0_fact` items carry `"section"` (heading path via `pipeline.heading_path`, e.g. "3 Threats > 3.2 Malware"); the faithfulness prompt says it is context only, not evidence. The sample was not re-ingested.
  - `api/requirements.txt` pinned with `==` from the working venv (torch `2.15.0+cpu`, CPU index line kept); `uv pip install --dry-run` → no changes.
  - `npm audit fix` (no `--force`): web 8 → 1 moderate, contracts lockfile bumps (undici 6.29.1 and one more). package.json files unchanged.
  - Amoy fee floor in one place: `contracts/scripts/fees.ts` (tip = max(network tip, 30 gwei), max fee = 2 × base + tip), used by `deploy.ts` and `transfer-owner.ts`; `ChainService` floor raised 25 → 30 gwei to match.
  - Issuer check (read-only): ISSUER_PRIVATE_KEY derives to `0x6fa045726eF3F0d84eb100e159517930C249b665` = registry `owner()`; balance 1.0 POL; chain id 80002.
- **Code review fixes (`/code-review high` on b644de5, 9 findings, none skipped):**
  - `transfer-owner.ts`: checksummed NEW_OWNER only, CONFIRM=yes required, refuses a contract address, clear error when the key is empty, `tx.wait(1, 180 s)` with nonce + hint on timeout, a rerun outbids a pending tx at the same nonce by 12.5% (or TIP_GWEI override).
  - SPEC 9.6 + CLAUDE.md rule 4: review mode checks fingerprints (and the stem-embedding backup) only within the new quiz, so a fact reviewed past 4 Bloom levels is not dropped forever.
  - PLAN aligned with SPEC: Bloom wrong answer = one level down (9.3), revocation needs the educator signature (9.8), attempt_hash includes grades (9.9), issuer balance line updated.
  - `.env.example` `CUSTODY_SECRET=` empty; SPEC 9.9 and R08: custodial mints refused (503) while it is empty.
- **Second `/code-review high` (on the R00 diff, 6 findings, none skipped):**
  - `ChainService._send` (pre-existing): uses the confirmed nonce; if pending > latest (a stranded tx), it replaces it at that nonce with doubled fees instead of queueing every later tx behind it for 120 s each.
  - `transfer-owner.ts`: TIP_GWEI is clamped to the 30 gwei floor; the error says to beat the stuck tip by 12.5%.
  - Web results: a loading state while GET /attempts runs, an ErrorBox with retry if it fails, no extra fetch right after submit.
  - Submit loads the quiz facts once (`_quiz_facts`, shared with GET /attempts).
  - `check_faithfulness` raises ValueError when `sections` does not match `pairs`.
  - Cache note: the gate0 prompt and payload changed, so the next ingestion of any document (including `samples/sample.pdf` via seed_demo) misses the LLM cache and pays full checker requests. Budget one full re-ingest before the R11 rehearsals.
- **Security pass (manual; `/security-review` had no diff to review because `main` = `origin/main`):** auth (argon2, JWT HS256 with exp/sub required, empty secret → 503), owner checks on every document/quiz/metrics/chat/attempt route (same 404 for other users), upload limits (25 MB, .pdf/.txt, UTF-8 check, basename only), chain errors never pass on exception text, no key logged, verify endpoints rate-limited and 409 before submit, no `dangerouslySetInnerHTML` in the web. No new issues needing a fix.
- **How to run:** `./scripts/dev.sh test`; contracts `cd contracts && npx hardhat test`; web `cd web && npm run build && npm run lint`.
- **Test results:** pytest **211 passed** with a local Hardhat node (199 passed + 12 chain skips without one); 7 new tests (stranded-nonce replacement, sections length check, and (attempt_id null → set, owner reload equals submit, other user / unknown / no token → 404/404/401, heading path, gate0 payload `section`). Hardhat **13 passing**; contract scripts `tsc --noEmit` clean. Web build OK, lint clean. Next 16.4.4 stops every other `npm run build` with its own security notice; running it again builds.
- **Open issues:**
  - web: `next` 16.4.4 has moderate advisories (`use cache`/`unstable_cache` leaks, image-optimizer SVG bypass). We use neither `next/image` nor `use cache`, so the demo is not exposed; fixing needs a Next version bump (pinned) — team decision.
  - contracts: 37 audit warnings remain, all in Hardhat 2 / toolbox 6 dev tooling (never shipped, never runs on a server); the fix is Hardhat 3 / toolbox 7, which CLAUDE.md rules out.
  - Still no login rate limiting; the verify rate limiter keeps one entry per client IP in memory (fine for a demo).
  - `.env` has no CREDENTIALS_ADDRESS, EDUCATOR_PRIVATE_KEY or CUSTODY_SECRET yet: add the last two before R07/R08.
  - No commits made: Deepesh commits and pushes.

### R01 distractor gate (2026-11-26, Fedora)
- **Done:**
  - Migration `0003`: `questions.distractors jsonb` (default `[]`), `quizzes.hash_version int` (default 1). Existing rows stay v1 with no distractors.
  - Generator: each MCQ now returns `distractors` (one per wrong option: `option`, `fact_idxs` ⊆ target + offered context, `misconception` ≤ 12 words). The prompt has a separate distractor section: built from real terms, list neighbours and numbers in the item's facts, plausible to someone who has not read the notes, and provably false by a cited fact. `validate()` rejects missing, duplicated, answer-pointing or out-of-item entries as `generator_error`; `option` is remapped after the server shuffle and stored sorted.
  - Gate 2 (`gates.gate2_distractors`): one batched checker call, run in parallel with Gates 1 and 3; facts = cited + distractor facts. Passes only if every verdict is `FALSE`; missing or unknown verdicts count as `UNSUPPORTED`; missing ids get one retry with attempt = 1, then fail closed. Logged as `gate2` rows. Rejection order Gate 1 → 2 → 3, and all three share the one regeneration call (still ≤ 2 generator calls per quiz).
  - Quiz hash v2 (`quizhash.quiz_hash(questions, salt, version)`, SPEC 9.2). New quizzes are `hash_version = 2`; `/verify/quiz` recomputes with the stored version. `tests/data/quiz_v1.json` is a frozen copy of the real Review 1 quiz `4e4d9a98…` (committed on Amoy), and it still hashes to its on-chain value.
  - `AttemptResult.results[].misconceptions` (`option`, `misconception`, `sources` with section) after submit; `[]` for Review 1 questions. `QuizOut` is unchanged. Metrics: `rejected_by_gate.gate2` and gate2 reasons in `top_reasons`; the web metrics page labels it "Gate 2 · distractor falsity"; `web/lib/types.ts` has the new result field (showing it is R09).
  - SPEC 9.2: Gate 2 facts, unknown verdicts and the rejection order spelled out.
- **How to run:** `./scripts/dev.sh migrate` (dev DB is at 0003), then `./scripts/dev.sh test`; web `cd web && npm run build && npm run lint`.
- **Test results:** pytest **239 passed** with a local Hardhat node (211 before + 28 new in `tests/test_distractors.py`: distractor validation (10 bad shapes), remap after the shuffle, Gate 2 payload/pass/each failing verdict/missing verdict/missing id retried then fail closed, stored order + gate2 rows in the job, Gate 1/2/3 failures sharing one regeneration (2 generator + 7 checker calls), Gate 2 missing everywhere → failed with 2 generator calls, v1 fixture unchanged, v2 canonical JSON exact + deterministic, v2 covers distractors and v1 does not, `/verify/quiz` uses the stored version (v2 quiz and the v1 fixture), nothing leaks before submit, misconceptions with sources after submit and on reload). Five Review 1 tests were updated to the new shape. Web `tsc`, lint and build clean.
- **Real run** (Groq: generator `openai/gpt-oss-120b`, checker `qwen/qwen3.8-27b`; sample.pdf, 482 facts, one user `f268ace0…`, document `ce5c75ce…`; chain disabled for the run so no POL was spent; script in the session scratchpad, not in the repo):

  | Quiz | Candidates | Accepted | Rejected | Gate 2 rejected | Avg dependence | Flagged general | Requests (gen + chk) | Seconds |
  | --- | --- | --- | --- | --- | --- | --- | --- | --- |
  | 6b55320a | 17 | 10 | gate2 4, generator_error 1 | 4 / 16 (25%) | 0.275 | 7 | 2 + 8 | 73 |
  | 3b744620 | 13 | 10 | generator_error 1 | 0 / 12 | 0.322 | 5 | 1 + 6 | 76 |
  | 86c723fd | — | 0 (failed) | Gate 4 call: `BadJSONError` | — | — | — | 2 + 17 | 232 |
  | f78d68d0 | 13 | 10 | gate2 2 | 2 / 13 (15%) | 0.17 | 9 | 1 + 7 | 111 |

  Gate 2 reasons: `option N TRUE` (2) and `option N UNSUPPORTED` (5). Gate 2 rejected 6 of 41 (15%), well under the 40% stop line.
  **Goal not met:** average dependence over the 30 accepted questions is **0.256** (goal ≥ 0.35; Review 1 range was 0.19–0.36). The blind checker picked the right answer on 28 of 30. The questions with low dependence test general knowledge ("who decrypts with the recipient's private key", "Target breach via the HVAC vendor"), so no distractor can make them depend on the notes. The ones with high dependence (1.0) test the notes' own case details (names of team members, incident timestamps). Some distractors are still weak: one question mixed in options of a different kind (system components offered as "access-control practices"), and some labels are generic ("confuses encryption with hashing").
- **Open issues:**
  - Dependence: the biggest lever is now the choice of target fact, not the distractors. Possible next step (team decision, not done): prefer facts with case-specific detail at selection, or regenerate when the blind checker is ≥ 90% confident. Both cost requests and change SPEC 4.
  - Quiz `86c723fd` failed (Review 1 code path): Qwen broke JSON mode twice on the Gate 4 batch, `BadJSONError` stopped the job, and the rollback also removed its gate log. Likely cause: Qwen's hidden reasoning fills `CHECKER_MAX_TOKENS=1000` before the JSON ends (the same failure gpt-oss had at ingest). Before R11, either treat a `BadJSONError` in `gates._batch` as "no results" (retry with attempt = 1, then fail closed) or test `CHECKER_REASONING_EFFORT` for Qwen. With `CHAIN_OPTIONAL=false` in the demo this would show as a failed quiz on stage.
  - Gate 2 adds a third parallel checker call; a quiz now takes 75–110 s (Review 1: about 60 s) because of the checker's 8000 TPM.
  - Requests per quiz: 1–2 generator + 6–8 checker when the JSON is fine.
  - No commits made: Deepesh commits and pushes.

### R01 follow-up: checker BadJSON no longer fails a quiz (2026-11-26, Fedora)
- **Done:** `gates._batch` (shared by Gates 1–4) treats a `BadJSONError` (Groq `json_validate_failed` twice) as a call with no results and logs a warning. The ids still missing get the existing attempt = 1 retry, a new cache key and so a fresh reply, and after that the existing rule applies: Gates 1–3 fail closed, and Gate 4 counts it as a blind miss with reason "checker returned no verdict". A daily limit or any other `LLMError` still stops the job. This fixes the failed quiz `86c723fd` from the R01 real run. Worst case per gate is now 4 checker requests (2 tries per call, 2 calls).
- **How to run:** `./scripts/dev.sh test`.
- **Test results:** pytest **243 passed** with a local Hardhat node (4 new: bad JSON then a good retry passes; bad JSON on both calls fails closed in all four gates without raising; a daily limit still raises; a quiz whose Gate 4 never returns JSON is `ready`, not `failed`). Not re-run against Groq: the failing reply cannot be reproduced on demand, and the change only touches the exception path.
- **Open issues:**
  - A Gate 4 miss sets dependence to 1.0, the Review 1 rule. If Gate 4 fails for a whole quiz, that quiz's dependence and the metrics average are overstated. The reason is logged ("checker returned no verdict"), so it can be counted. Excluding those questions from `avg_dependence` would be a small metrics change (team decision).
  - The root cause (Qwen's reasoning likely filling `CHECKER_MAX_TOKENS=1000`) is not fixed; testing `CHECKER_REASONING_EFFORT` is still open.

### R02 — Bloom's ladder (2026-11-26, Fedora)
- **Done:**
  - `BLOOM_LEVELS = remember, understand, apply, analyze` (`app/quiz/select.py`). New targets still alternate remember / understand. Retests use `next_bloom(previous, last_correct)` (SPEC 9.3): right → one up, wrong → one down. Tier 3 (asked, never answered) → one up. At the cap or floor it takes the neighbour (analyze → apply, remember → understand), so the level never repeats. The question stores the ladder's level; the generator's echoed `bloom_level` is ignored, so it cannot undo the ladder.
  - Generator prompt: one line per level, and every level must be answerable from the cited facts alone. Gate 1 prompt asks for `"bloom"` with the same definitions; the checker is not told the asked level. `gate_results.gate1.bloom` is one of the four or `null` (missing or unknown), and it never changes the verdict. A mismatch writes a `generation_log` row `gate="bloom_mismatch"`, `passed=true`; the question is kept and it is not counted as a rejection.
  - `MetricsOut.bloom_levels` (accepted questions per level, all 4 keys) and `bloom_mismatches` (accepted questions whose Gate 1 label is set and differs). `web/lib/types.ts` updated (UI is R09). SPEC sections 1, 4 and 9.3 updated (tier 3 rule, `null` label, mismatch row).
  - Fixed a flaky R01 test (`test_gate2_failures_join_the_one_regeneration` picked the failing gate by `fact_idx % 3`, so about 6% of random target sets had no Gate 2 failure); it now keys on the batch id. 15/15 runs pass.
- **How to run:** `./scripts/dev.sh test`. No migration (`bloom_level` is already `String(16)`).
- **Test results:** pytest **266 passed** with a local Hardhat node (243 before + 23 new in `tests/test_bloom.py`: 11 ladder transitions incl. caps, floor and tier 3; prompts name all four levels; selection over a fully used document gives the ladder level and tier per history; retest fingerprint differs from the earlier question; the generator's echo is ignored; Gate 1 bloom parsing (valid, missing, unknown, null, with NOT_SUPPORTED) never changes the verdict; the asked level is not in the Gate 1 payload; mismatch rows logged and questions kept; metrics counts incl. a question without a label). One R01 assertion updated for the new `bloom` key. Web `tsc` and lint clean.
- **Real run** (Groq, chain disabled; a `.txt` of one sample section, "Access control: four steps", ingested as a new document `1b279f76…` with 8 facts for a new user; script in the session scratchpad):

  | Quiz | Accepted | Rejected | Requests (gen + chk) | Answers | Levels before → after |
  | --- | --- | --- | --- | --- | --- |
  | 1 | 2 | generator_error 9, gate2 3 | 2 + 7 | 1/2 | new → remember ×2 |
  | 2 | 3 | generator_error 12, gate1 1 | 2 + 4 | 1/3 | new → remember ×2, understand ×1 |
  | 3 | 4 | generator_error 7, dup_cosine 3 | 2 + 7 | 4/4 | new ×3; fact 7: remember (wrong) → **understand** (floor neighbour) |
  | 4 | 3 | dup_cosine 5 | 1 + 6 | 2/3 | fact 1: remember (right) → **understand**; fact 6: remember (right) → **understand**; fact 2: understand (right) → **apply** (checker agreed) |
  | 5 | 0 (failed) | generator_error 8, dup_cosine 3, dup_fingerprint 1, gate1 1 | 2 + 11 | — | — |

  Ingest: 1 + 1 requests. Metrics: `bloom_levels` remember 6, understand 5, apply 1, analyze 0; `bloom_mismatches` 5 of 12. The Qwen checker labels nearly everything "remember" (it agreed on 1 understand and 1 apply). avg_dependence 0.06: these are textbook definitions of access control, so the blind checker knows them (expected for this section, not a Bloom result).
- **Open issues:**
  - **The stem cosine check blocks retests (team decision).** 12 of 13 duplicates on the small document were `dup_cosine` (0.86–0.98): a retest of the same fact at a new level still asks about the same thing, so its stem embedding is close to the earlier one. The fingerprint (facts + level) already differs. Options: skip the cosine check against earlier questions with the same target fact when the level differs, or raise the threshold for those. This changes SPEC 4 / CLAUDE.md rule 4 ("Backup"), so not done. On the 482-fact sample this hardly shows until unused facts run out, but R05 review mode (9.6) checks only within the quiz, so it is not affected.
  - On a small document the generator often cites facts from neighbouring items (21 × "distractor fact_idxs cites a fact outside this item", 7 × "more than 2 context facts"): every item's context is the same section. This is R01 validation working as designed; the cost is the regeneration call. Quiz 5 failed because all 8 facts were used up and every retry was a duplicate or invalid, which is the SPEC 4 rule ("If it cannot produce any question … failed").
  - The checker's Bloom labels lean to "remember" (5 of 12 accepted questions mismatched), so `bloom_mismatches` mainly measures checker strictness. Worth one sentence in the report.
  - Retesting with 4 levels can return to an earlier level (right then wrong); its fingerprint can match an older question and the SPEC 4 rule drops it (seen once: `dup_fingerprint` in quiz 5).
  - No commits made: Deepesh commits and pushes.

### R02 follow-up: the stem cosine check no longer blocks retests (2026-11-26, Fedora)
- **Done:** `DuplicateChecker` (`app/quiz/dedup.py`) keeps `(target_fact_idx, bloom_level)` with every earlier stem and with each question accepted in this quiz. The cosine check skips earlier questions with the **same target fact at a different Bloom level** (the planned retests; their fingerprint already differs). It still compares with every other earlier stem, and with the same target at the same level. The fingerprint check is unchanged. `job.py` passes the candidate's target and level; without them `check()` compares everything as before. SPEC 4 + 9.3 and CLAUDE.md rule 4 ("Backup") updated.
- **How to run:** `./scripts/dev.sh test`.
- **Test results:** pytest **272 passed** with a local Hardhat node (266 + 6 new in `tests/test_bloom.py`: near-identical retest stem at a new level kept; same stem for another target still `dup_cosine`; same target + same level with other context still `dup_cosine`; no target/level → old behaviour; same rule within one quiz; end-to-end, 5 FAKE retests whose stems repeat the earlier ones are all accepted with no `dup_cosine`). Without the `job.py` change the end-to-end test fails (2 of 5 kept).
- **Real run** (Groq, chain disabled, same small document `1b279f76…` and user as the R02 run):

  | Quiz | Accepted | Rejected | Requests (gen + chk) | Levels before → after |
  | --- | --- | --- | --- | --- |
  | 6 | 4 | generator_error 8, gate2 3 | 1 + 8 | fact 0: remember (wrong) → understand (floor neighbour); facts 4, 5: remember (right) → understand; fact 1: understand (right) → apply |
  | 7 | 5 | generator_error 9, gate2 1, dup_fingerprint 1 | 2 + 9 | fact 3: understand (wrong) → **remember**; facts 7, 6, 4, 5: understand (right) → apply |

  9 retests accepted, **0 `dup_cosine`** (quizzes 1–5 before the fix: 12 of 13 duplicates were `dup_cosine`). Totals for the document: remember 7, understand 8, apply 6, analyze 0; `bloom_mismatches` 12 of 21 (the Qwen checker still labels most questions "remember").
- **Open issues:**
  - A retest may now repeat the earlier stem almost word for word at a new level label. It is not blocked; a stricter ceiling (e.g. cosine ≥ 0.97 still blocks) would be a new SPEC number (team decision, not done).
  - The one `dup_fingerprint` in quiz 7 is the expected case: a level the fact had already been asked at, with the same facts.
  - No commits made: Deepesh commits and pushes.

### R03 — Mastery (BKT) and gap report (2026-11-26, Fedora)
- **Done:**
  - Migration `0004_mastery`: the `mastery` table per SPEC 9.4, and the `Mastery` model.
  - `app/learn/mastery.py`:
    - BKT constants from SPEC (p_init 0.2, t 0.15, s 0.10, g 0.25 MCQ / 0.05 short) and a pure `bkt_update` (partial counts as wrong);
    - `mastery_status` (weak < 0.40 ≤ learning < 0.95 ≤ mastered; answered 0 → untested);
    - `update_mastery` (one row upsert).
  - Concepts match case-insensitively and are stored under the spelling on the concept's lowest-idx fact. This is now noted in SPEC 9.4.
  - `app/learn/grading.py on_final_grade`: the one hook per final grade. It does the coverage upsert (moved from `submit_attempt`, unchanged) and the mastery update for the target fact's concept, in the submit transaction. R05 (FSRS) and R06 (short answers) plug in here.
  - `GET /documents/{id}/mastery -> MasteryOut` (`app/routers/learn.py`), owner only (404 otherwise):
    - every concept is listed, untested ones at p 0.2;
    - each concept has its section (the first fact's heading) and all its fact idxs;
    - `badge_id` is null until R08;
    - order: weak, then learning (lowest p first), then untested (document order), then mastered.
  - `web/lib/types.ts` adds `MasteryOut` for R09.
  - `api/scripts/backfill_mastery.py` replays every attempt in `created_at` order. It deletes and rebuilds the rows per (user, document) in one transaction, so it is idempotent, and it does not touch coverage.
- **How to run:**
  - `cd api && PYTHONUTF8=1 .venv/bin/python -m alembic upgrade head`
  - `PYTHONUTF8=1 .venv/bin/python scripts/backfill_mastery.py`
  - tests: `./scripts/dev.sh test`
- **Test results:**
  - pytest **292 passed** with a local Hardhat node. The 20 new tests are in `tests/test_mastery.py`:
    - BKT steps checked against values worked out by hand (correct/wrong/partial, MCQ and short, two correct in a row);
    - status thresholds;
    - an attempt updates only the target concepts, and context-only concepts stay untested;
    - all concepts are listed with sections and facts;
    - ordering across all four statuses;
    - case-insensitive merge;
    - owner-only access (404 / 404 / 401);
    - backfill equals the live updates over 3 quizzes with retests, and a second run gives the same rows.
  - `test_migrations` checks the new table.
  - Web: `tsc --noEmit` and `npm run lint` are clean.
- **Stats (dev DB after backfill):**
  - 11 attempts, 71 answers, 6 user+document pairs.
  - Summary over all pairs: weak 36, learning 20, mastered 2, untested 2200.
  - Most concepts are untested because the sample has about 480 facts and only a few quizzes were taken.
  - A second run printed the same numbers.
  - 5 weakest concepts:
    - 0.174 "Access control steps" (2 wrong)
    - 0.174 "Password" (2 wrong)
    - 0.177 "Reputational impact" (Case: Target Corporation)
    - 0.177 "IR phase count" (Case: iPremier)
    - 0.177 "Committee terms" (What a policy is)
- **Open issues:**
  - With p_init 0.2, one wrong answer (0.177) and one untested concept (0.2) are close. The gap report keeps them apart by status, not by p.
  - Reaching "mastered" from scratch takes 3 correct answers in a row (0.553 → 0.844 → 0.958). The demo needs 3 attempts on one concept to show a mastered row.
  - Two simultaneous submits of different quizzes on a concept that has no row yet could race on the first insert. The upsert stops a crash, but one update would be lost. This is very unlikely with one learner.
  - No commits made: Deepesh commits and pushes.

### R04 — Revision notes for weak concepts (2026-11-26, Fedora)
- **Done:**
  - Migration `0005_revision_notes` and the `RevisionNote` model (SPEC 9.5), indexed on (user, document, concept, created_at).
  - `app/learn/revision.py`:
    - **Picking concepts:** with no list, the 3 weakest weak/learning concepts in gap-report order (409 if none). With a list, names match case-insensitively; an unknown name or more than 5 gives 422.
    - **One generator call** (`REVISION_NOTES_SYSTEM`) that gets only those concepts' facts.
    - **Validation:** a sentence is dropped and counted if its text is empty or over 400 characters, if its `fact_idxs` are empty or not all from its own concept, or if it comes after the 6th.
    - **One batched Gate 1 call:** `GATE_REVISION_SYSTEM`, a statement form of the Gate 1 prompt, through `gates._batch`. Ids without a verdict get one retry, then fail closed. `NOT_SUPPORTED` means dropped and counted.
    - One `generation_log` row per checked sentence: gate `revision_gate1`, quiz_id null, candidate_id = the note id.
  - `POST` and `GET /documents/{id}/revision -> RevisionOut` in `app/routers/learn.py`:
    - owner only (404);
    - POST gives 409 when the document isn't ready or nothing is weak or learning, 429 at the daily LLM limit, and 502 on any other LLM failure, and nothing is stored on an error;
    - GET returns the latest note per concept, weakest first.
  - FAKE provider handlers for both new prompts.
  - `web/lib/types.ts` adds `RevisionOut`.
  - SPEC 9.5 gains a details paragraph: validation, the statement Gate 1, the error codes and the order.
- **How to run:**
  - `cd api && PYTHONUTF8=1 .venv/bin/python -m alembic upgrade head` (the dev DB is at 0005)
  - `POST /documents/{id}/revision {"concepts": null}`
  - tests: `./scripts/dev.sh test`
- **Test results:**
  - pytest **300 passed** with a local Hardhat node. The 8 new tests are in `tests/test_revision.py`:
    - the 409 path spends no request;
    - null picks the 3 weakest, using exactly 1 generator call and 1 checker call;
    - invalid sentences are dropped and counted: another concept's idx, partly outside, empty, bool, blank, too long, over the cap;
    - a Gate 1 `NOT_SUPPORTED` and a missing verdict are both dropped, with one retry for the missing id only;
    - log rows are written;
    - GET returns the latest note per concept;
    - owner only, plus 422 validation;
    - a daily limit gives 429 and another LLM error gives 502, with nothing stored either way.
  - Web: `tsc --noEmit` and `npm run lint` are clean.
- **Stats (real Groq run, dev DB, 3 weakest concepts of the pair with the most gaps):**
  - requests used: generator 1, checker 1; 3.3 s.
  - "Financial impact" (2 facts): kept 2, dropped 1
  - "Market position" (1 fact): kept 2, dropped 1
  - "IR phases" (1 fact): kept 2, dropped 1
  - In total, 6 sentences kept and 3 dropped.
  - All 3 drops were Gate 1 `NOT_SUPPORTED`, each for a claim the facts don't make, such as "causal link to breach is not in facts".
- **Open issues:**
  - Concepts with only 1–2 facts can't support 3 distinct sentences. The generator pads, and Gate 1 removes the padding, so real notes end up with 2 sentences, under the 3–6 target. Raising the 3-sentence minimum would only add padding; letting the prompt write fewer sentences for small concepts would save checker tokens.
  - A note with 0 sentences kept is still stored and becomes the "latest" for its concept on GET, replacing an earlier good note.
  - Notes are generated synchronously in the request, which takes about 3 s on Groq. There is no progress state.
  - No commits made: Deepesh commits and pushes.

### R05 — FSRS review cards and review quiz mode (2026-11-27, Fedora)
- **Done:**
  - `fsrs==6.3.3` pinned in `api/requirements.txt` (no dependencies).
  - Migration `0006_review_cards`:
    - table `review_cards` (user_id, fact_id, card jsonb, due, last_rating), pk (user_id, fact_id), index (user_id, due);
    - `quizzes.mode`, default `practice`.
    - Models `ReviewCard` and `Quiz.mode`.
  - `app/learn/review.py`:
    - rating map wrong → Again, partial → Hard, correct → Good;
    - `update_card` locks the row, rebuilds the card with `Card.from_dict` (or `Card(card_id=fact.id)`), runs the default `Scheduler`, and upserts `to_dict()`, `due` and `last_rating`;
    - `review_summary` and `due_cards`.
  - The "on final grade" hook (`learn/grading.py`) now also updates the card, in the same transaction as coverage and mastery.
  - `quiz/select.py`: new `select_review_targets` (due cards only, most overdue first, max 2 per concept, Bloom ladder from coverage). `select_targets` (practice) is unchanged.
  - `quiz/job.py`: review mode uses the review selector. Its spares are only more due cards. `DuplicateChecker(within_quiz_only=True)` checks fingerprints only within the new quiz and skips the stem cosine check. Gates 1–4 and the on-chain commit run as usual.
  - `POST /quizzes`:
    - `mode: "practice" | "review"`;
    - in review mode with nothing due: 409 `{"detail":"Nothing due for review","next_due":…}`, sent before any quiz row or LLM call;
    - `QuizOut.mode`.
  - `GET /documents/{id}/review -> {"due_now","next_due","cards"}` (owner only).
  - `scripts/backfill_mastery.py` also rebuilds review cards, replaying each attempt at its `created_at`, and prints card counts.
  - `web/lib/types.ts`: `QuizMode`, `QuizOut.mode`, `ReviewSummaryOut`, `NothingDueOut`.
  - SPEC 9.6 has a new details paragraph.
- **How to run:**
  - `cd api && PYTHONUTF8=1 .venv/bin/python -m alembic upgrade head` (the dev DB is at 0006)
  - `PYTHONUTF8=1 .venv/bin/python scripts/backfill_mastery.py`
  - `POST /quizzes {"document_id", "num_questions", "mode": "review"}`
  - `GET /documents/{id}/review`
  - Tests: `./scripts/dev.sh test`
- **Test results:**
  - pytest **315 passed**, with a local Hardhat node. The 15 new tests are in `tests/test_review.py`:
    - the rating mapping, and an unknown grade is rejected;
    - a card is created, then updated from its stored dict;
    - a submit makes one card per target, and the wrong ones come due first;
    - due ordering and the per-concept cap, including case-insensitive concept names;
    - Bloom ladder targets;
    - other users and documents are ignored;
    - the 409 shape, both with and without `next_due`, with no quiz row and no generator call;
    - `mode` is validated and defaults to practice;
    - a review quiz targets ⊆ due facts, passes all 4 gates, commits on a FAKE chain with `CHAIN_OPTIONAL=false`, and its hash matches;
    - after the review is answered, nothing is due;
    - practice selection is unchanged when cards exist;
    - within-quiz-only duplicate behaviour;
    - the GET summary is owner only;
    - the backfill rebuilds the same cards and is idempotent.
  - `test_mastery.py`: the backfill stats assertion now ignores the new `cards` key. All existing selection tests pass unchanged.
  - Web: `tsc --noEmit` and `npm run lint` are clean.
- **Stats:**
  - **Backfill on the dev DB:** 11 attempts and 71 answers give 58 cards. 55 are due now, because those attempts are days old. The next one is due 2026-11-27T15:00Z.
  - **One-quiz scenario (FAKE LLM, test DB):** a 10-question quiz with 4 wrong answers.
    - Right after submit: `due_now` 0, `next_due` +1 min, 10 cards.
    - 2 min later: `due_now` 4, `next_due` 05:01:33Z (the cards answered right, due at +10 min).
    - Wrong targets [4, 9, 12, 19] = due [4, 9, 12, 19] = review quiz targets. Targets ⊆ due: true.
    - Bloom levels went remember → understand (at the floor, the neighbouring level) and understand → remember.
    - Quiz status: ready.
- **Open issues:**
  - Default learning steps: a correct answer comes due again after 10 min. Demo step 9 ("only the facts answered wrong come back") must start the review quiz between 1 and 10 min after the attempt. After that, the facts answered right come back too.
  - The backfilled dev cards are mostly overdue, because old attempts were replayed at their real times. The dev pairs therefore show many due cards. The demo is re-seeded in R11 anyway.
  - The 409 check counts due cards before the job runs. If a card stops being due in between (another submit), the job can find 0 targets, and the quiz then fails as in practice mode.
  - No web screen yet: the review queue page comes in R09.
  - No commits made: Deepesh commits and pushes.

## R06 — Short-answer questions, checker grading, educator deferral (2026-11-27)
- **Done:**
  - Migration `0007_short_answers`:
    - `questions.qtype` (default `mcq`) and `model_answer`; `dependence_score` may now be null;
    - `attempts.grading_status` (default `final`);
    - table `answer_grades`, unique (attempt, question), with index `ix_answer_grades_pending` for the R08 educator queue.
  - Generation:
    - `POST /quizzes` takes `num_short` (0–3, at most `num_questions`). `job.mark_short` spreads the short targets over the first N.
    - Short and MCQ items still come from one generator call, plus at most one batched regeneration. A short item that fails always joins the regeneration, so MCQ spares cannot quietly take its place.
    - Short items run Gate 1 (on the model answer) and the new Gate 3s (`ANSWERABLE`/`AMBIGUOUS`); no Gate 2 or 4.
    - New prompts `GATE_SHORT_SOLVABILITY_SYSTEM` and `GRADE_SHORT_SYSTEM`, with FAKE replies in `provider.py`.
  - Submit:
    - Answers are checked strictly per position, and a wrong type gets a 422.
    - New `app/learn/shortgrade.py` makes one batched `grade_short` checker call, retries missing ids once, and logs each grade to `generation_log`.
    - A grade is deferred when its confidence is below 70, there is no verdict, it cites facts outside the question, or the LLM call fails. A Groq error therefore never breaks a submit.
    - An empty short answer is `incorrect` without an LLM call.
    - The score and the hooks (coverage, mastery, FSRS) count final grades only.
  - Educator grading: `apply_educator_grade(db, grade_id, verdict, educator)`, ready for R08 to wire. It runs the hook, rescores the attempt, and sets it to final once nothing is pending.
  - Outputs:
    - `AttemptResult` and `GET /attempts` are rebuilt from `answer_grades`.
    - `QuizOut.questions[].qtype` is new.
    - Metrics: `short_questions`, `deferred_grades`, and `avg_dependence` over MCQs only.
  - The backfill replays final short grades and skips pending ones.
  - `web/lib/types.ts` and `submitAttempt` are updated. SPEC 9.7 has a new details paragraph, which adds `grade.fact_idxs`.
- **How to run:**
  - `cd api && PYTHONUTF8=1 .venv/bin/python -m alembic upgrade head` (the dev DB is at 0007)
  - `POST /quizzes {"document_id", "num_questions": 4, "num_short": 2}`, then submit with strings at the short positions.
  - Tests: `./scripts/dev.sh test`
- **Test results:**
  - pytest **333 passed**, with a local Hardhat node and none skipped. The 18 new tests are in `tests/test_short.py`:
    - `mark_short` spread and `validate_short` rules;
    - a mixed quiz uses one generator call, and short items have no Gate 2 or 4 rows;
    - a short item failing Gate 3s joins the one regeneration;
    - a bad `num_short` gets a 422;
    - wrong answer types get a 422 (500 characters is still accepted);
    - one grading call, the verdicts and the score, and `GET /attempts` returns the same body;
    - an empty answer makes no LLM call;
    - the threshold and citation rules, including no verdict after one retry;
    - an LLM failure defers the grade and the submit still succeeds;
    - a deferred grade is pending, and the hooks fire only once it is final, then again after the educator grade (plus its error cases);
    - the backfill;
    - hash v2 with a short question;
    - nothing leaks before submit;
    - metrics.
  - All existing tests pass unchanged. Web `tsc --noEmit` and lint are clean.
- **Stats (real Groq, dev DB doc `d56e16f5` sample.pdf, throwaway user `r06-stats-…@example.invalid`, chain stubbed offline so no Amoy tx):**
  - **Quiz:** 4 questions, 2 of them short. 1 candidate was dropped as a `generator_error` (a distractor cited an outside fact). Both short items passed Gate 3s as ANSWERABLE.
  - **Good answer** (Q2, a paraphrase of "VP of Business Development, worried about stock and PR") → **correct, confidence 95**, fact [132].
  - **Vague answer** (Q3, "quite a lot of attacks every week") → **incorrect, confidence 90**, fact [241], "misses specific required number 1,168".
  - **Deferred:** 0. Score 3 / 4, status final.
  - **Extra probe** (graded by the checker, nothing saved): "roughly a thousand a week, maybe a bit more" → partial, confidence 95, not deferred.
  - **Requests:** 1 generator and 5 checker for generation (Gates 1, 2, 3 and 3s, then 4), plus 1 checker for grading. The probe used 1 more checker request.
- **Open issues:**
  - Qwen reports confidence 90–95 even on vague or borderline answers, so with real grades the threshold of 70 almost never defers. The deferral path is tested with FAKE only. Options for R08/R11: ask the checker for a calibrated confidence, defer every `partial`, or seed one deferred grade for demo step 10.
  - A short item that fails twice is dropped, and a spare MCQ fills its place, so the quiz can have fewer than `num_short` short questions. The count is visible in metrics as `short_questions`.
  - The grading call runs inside the submit transaction, which holds the quiz row lock for about 1–3 s. That is fine at demo scale.
  - No web screen yet (R09 adds the text inputs and grade display); the educator endpoints come in R08.
  - The dev DB now holds the R06 stats user, quiz and attempt.
  - No commits made: Deepesh commits and pushes.

## R07 — SmartQuizCredentials.sol: result anchoring, ERC-5192 badges, EIP-712 co-sign and revocation (2026-11-27)
- **Done:**
  - `contracts/contracts/SmartQuizCredentials.sol` per SPEC 9.8 (details as built are under 9.8): Ownable + ERC721 ("SmartQuiz Concept Badge", "SQB") + EIP712 ("SmartQuizCredentials", "1"), ECDSA, MerkleProof. The registry is unchanged; the new contract reads its `getDocument` for co-signing.
    - Educators: add/remove (onlyOwner). Result batches: `anchorResults` (BatchExists), `verifyResult` (UnknownBatch), `getBatch`.
    - Badges: soulbound (every transfer, safe transfer and approval reverts `Soulbound`), `Locked` on mint, `locked()` true, ERC-5192 interface `0xb45a3c0e`, `getBadge`, revoked badges kept and marked. `tokenURI` is base64 JSON with the name and hex hashes only.
    - `revokeBadge`, `coSignDocument` (factRoot must equal the registry's, else `RootMismatch`) and `revokeDocument` take an EIP-712 educator signature; the issuer sends the tx. No payable, no upgradeability, no text on chain.
  - `contracts/scripts/deploy-credentials.ts`: owner = issuer, registry = REGISTRY_ADDRESS, `addEducator(address of EDUCATOR_PRIVATE_KEY)`. On Amoy it prints the issuer balance and the worst-case cost first and sends nothing if the balance is short; both txs use `amoyFees()` (tip ≥ 30 gwei). It writes CREDENTIALS_ADDRESS to `.env` only for `--network amoy`. On localhost it funds the issuer and deploys a throwaway registry when REGISTRY_ADDRESS has no code there.
  - `contracts/scripts/env.ts`: shared `.env` helpers; `deploy.ts` now uses `writeEnvLine` (same behaviour).
  - `contracts/hardhat.config.ts`: `evmVersion: "cancun"`, needed because OpenZeppelin 5.6 ERC721 → Strings uses `mcopy`. The deployed registry is untouched; only the local build changed.
  - Python: `app/chain/credentials.py` (attempt_hash per SPEC 9.9, batch_chain_id, concept_hash, evidence_hash, reason_hash, EIP-712 `sign`/`recover` with `eth_account`) and `merkle.result_leaf`. They are ready for R08. ABI copied to `app/chain/abi/SmartQuizCredentials.json`.
  - Cross-check: `api/scripts/credentials_fixture.py` writes `contracts/test/fixtures/credentials.json`: 5 attempt hashes (one leaf promoted), their result leaves, root and proofs, the concept and evidence hashes, and EIP-712 CoSign / RevokeBadge / RevokeDocument signatures by a test-only educator key plus one by a non-educator. The test deploys from the fixture's fresh test-only deployer, so the contract address (and the EIP-712 domain) is the one Python predicted.
  - `.env`: added a new testnet-only `EDUCATOR_PRIVATE_KEY` (generated locally, never printed); `CREDENTIALS_ADDRESS` written by the Amoy deploy. `.env.example` already had both keys.
- **Deployed (Amoy, chain id 80002):**
  - **CREDENTIALS_ADDRESS = `0xe1B32EAfa2673E775bcdFB67F4816aF90DA40f4E`**, owner = issuer `0x6fa045726eF3F0d84eb100e159517930C249b665`, registry `0x4093F5F19Eacf69Fc8144A1d39A3f6838D4dc518`.
  - **Educator address = `0x6C25595bbcdE46DF391bE795fA6D558Eb7bF8B57`** (`isEducator` true on chain; the wallet needs no POL).
  - Deploy tx https://amoy.polygonscan.com/tx/0xe436f3ae5ae7239e37c4395f7346d29808d39d2118611ee0566d3b9cce3a724c (4,243,690 gas, 0.2546 POL); addEducator tx https://amoy.polygonscan.com/tx/0xf09f5c4564c1daa796159be9143aa3a9ee530e52b32d4143b6f7b55831f38ca8 (54,410 gas, 0.0033 POL). Issuer balance 1.0 → 0.742 POL.
  - Read back from Amoy: owner, registry, `isEducator`, `supportsInterface(0xb45a3c0e)` all as expected.
  - Local node first: deployed with `.env` unchanged (checksum checked), then web3.py co-signed a registered document with a signature made in Python from the real `.env` educator key, and `getCoSign` returned the educator.
- **How to run:**
  - Contract tests: `cd contracts && npx hardhat test`
  - Regenerate the fixture after changing credentials.py or merkle.py: `cd api && PYTHONUTF8=1 .venv/bin/python scripts/credentials_fixture.py` (a pytest fails if it is stale)
  - Local deploy: `cd contracts && npx hardhat node`, then `npx hardhat run scripts/deploy-credentials.ts --network localhost`
  - Amoy deploy (already done; rerunning deploys a second contract and rewrites CREDENTIALS_ADDRESS): `npx hardhat run scripts/deploy-credentials.ts --network amoy`
- **Test result:**
  - Hardhat **46 passing**: 33 new for SmartQuizCredentials (educators and onlyOwner, typehashes, no payable, anchor + duplicate, verifyResult true/false/UnknownBatch, mint emits BadgeMinted + Locked, locked/getBadge/tokenURI UnknownToken, interface ids, every transfer and approval path Soulbound even for holder and owner, tokenURI hashes only, revokeBadge valid / non-educator / wrong values / removed educator / replay AlreadyRevoked / UnknownToken / non-owner, coSign matching / mismatching / unregistered / non-educator / foreign domain, revokeDocument with replay and a CoSign signature reused, and the Python fixture block: predicted addresses, hashes recomputed in TypeScript, every Python proof on chain, tampered attempt false, Python signatures accepted, stranger rejected) plus the 13 registry tests unchanged.
  - pytest **341 passed** with a local Hardhat node (8 new in `tests/test_credentials_hash.py`: fixture not stale, attempt_hash canonical and tamper-evident, result leaves, evidence sorting and errors, concept/reason hashes, EIP-712 sign/recover per type and domain).
- **Open issues:**
  - Deploy gas is high (4.24M) because the optimizer is off; mint, anchor and revoke calls are small. Turning on the optimizer would change the registry's local bytecode too, so it was left off.
  - The fixture keys are test-only keys derived from public labels and are committed on purpose; they must never be funded or used on Amoy.
  - `coSignDocument` allows a re-co-sign (latest kept). R08 can refuse a second co-sign in the API if wanted.
  - The ChainService does not call the new contract yet; R08 adds that (Settings also need CREDENTIALS_ADDRESS, EDUCATOR_PRIVATE_KEY and CUSTODY_SECRET).
  - No commits made: Deepesh commits and pushes.

## R08 — Credentials API (2026-11-27)
- **Done:**
  - Migration `0008_credentials` per SPEC 9.9: `users.role` / `wallet_address`; `attempts.attempt_hash` / `attempt_salt` / `batch_id`; tables `result_batches`, `badges` (plus `evidence_attempt_ids`, recorded in SPEC), `cosignatures`; `documents.revoked` / `revoke_tx` / `revoke_reason`. Applied to the dev DB.
  - `api/scripts/make_educator.py <email> [--learner]`.
  - Settings: `CREDENTIALS_ADDRESS`, `EDUCATOR_PRIVATE_KEY`, `CUSTODY_SECRET` (tests blank them by default). `.env` got a generated `CUSTODY_SECRET` (never printed; must never change now that custodial badges exist).
  - `ChainService` (same send lock, nonce replacement and 30 gwei fee floor): anchor, mint (token id from `BadgeMinted`), revoke badge, co-sign, revoke document, the reads, and `educator_sign` (EIP-712 with EDUCATOR_PRIVATE_KEY in the connected chain's domain). New `ChainRevert` carries the contract error name.
  - `app/credentials/results.py`: attempt hash when grading is final (at submit, or in `apply_educator_grade` once nothing is pending), batches of final unanchored attempts. `app/credentials/badges.py`: evidence attempts, custodial addresses, live badges.
  - Routers: `badges.py` (`POST/GET /badges`), `educator.py` (anchor, grading queue + grade, documents, co-sign, revoke document, revoke badge; `require_educator` → 403), `auth.py` (`role`, `wallet_address`, `PUT /auth/me/wallet`), `verify.py` (`/verify/attempt`, `/verify/badge`, `cosign` + `document_revoked` on `/verify/question`), `MasteryOut.badge_id`.
  - SPEC 9.9 gained a "Details (R08, as built)" block (status codes, match rules, the extra column).
- **Real Amoy run** (dev DB, learner from R02 with 2 mastered concepts, a new educator user `r08-educator@example.invalid`; MetaMask mint skipped for now at Deepesh's choice):
  | step | tx | gas | POL |
  |---|---|---|---|
  | anchor via `POST /badges` (6 attempts) | [0x241de50c…](https://amoy.polygonscan.com/tx/0x241de50cb7d9997557abbee93f7d6f66d02e75abfb1c8ff152cfe929455ebaeb) | 79,866 | 0.004792 |
  | mint custodial badge #1 "Authorization" | [0x0aaae333…](https://amoy.polygonscan.com/tx/0x0aaae33300a7b84f009dab85d7e7f2202d8122f2d62ae36371472a0fec55ee12) | 190,297 | 0.011418 |
  | mint custodial badge #2 "Multi-factor authentication" | [0x09081653…](https://amoy.polygonscan.com/tx/0x0908165347f61ccdbc2b5804d6fa141d1cf55afb0b5064438b7a3b20a9177571) | 172,357 | 0.010341 |
  | `POST /educator/anchor` (6 other attempts) | [0xd2c1701b…](https://amoy.polygonscan.com/tx/0xd2c1701b6546d78a3aff97fe0f1ec0f171507abd3efc81d8a765bfdc60026442) | 79,866 | 0.004792 |
  | co-sign demo `sample.pdf` (3ce3f1e0…) | [0x76eaad44…](https://amoy.polygonscan.com/tx/0x76eaad44bb79d399556fb81b751a165fa27e342f669d3c1c97739e180a767ce1) | 84,498 | 0.005070 |
  | revoke badge #2 | [0x130ea64d…](https://amoy.polygonscan.com/tx/0x130ea64d6e366595d2f030e43191231ffc7356e314f516de13466dcb79947a33) | 56,024 | 0.003361 |
  - Total 0.0398 POL; issuer 0.742 → 0.702 POL. Custodial holder `0x25a83bDe5edD5df854F23a118A806829A06af02F`. Public verify on Amoy: `/verify/attempt` match true + verified_on_chain true; `/verify/badge/1` match true, not revoked; `/verify/badge/2` match true, revoked true.
  - MetaMask mint (same day, after the run): the learner's wallet set to Deepesh's MetaMask learner account `0x22FADbe67911A1f95B0A0c1DA4812676E8467181` (`PUT /auth/me/wallet`), then "Multi-factor authentication" claimed again (the revoked badge #2 did not block it): **badge #3** to that address, tx [0x1ba661cf…](https://amoy.polygonscan.com/tx/0x1ba661cff552f9e6f2c6fb282dfa59c89f98d22d4bdd063f65bfefff5d4b5857), 190,297 gas, 0.011418 POL. `ownerOf(3)` = the MetaMask address; `/verify/badge/3` match true, not revoked. Issuer now 0.691 POL.
- **How to run:**
  - Migrate: `./scripts/dev.sh migrate`
  - Make an educator: `cd api && PYTHONUTF8=1 .venv/bin/python scripts/make_educator.py <email>`
  - Tests: `cd contracts && npx hardhat node` (for the chain tests, in a second terminal), then `cd api && PYTHONUTF8=1 .venv/bin/python -m pytest -q`
- **Test result:**
  - pytest **369 passed** with a local Hardhat node (28 new in `tests/test_credentials_api.py`: 403 on all 7 educator endpoints, make_educator, wallet checksum and 6 invalid forms, custodial address deterministic + secret-dependent, attempt hash stable and tamper-evident, deferred attempt hashed only after the educator grade (queue, 422/409/404), badge 404/409/503 rules, anchor 503 marks nothing, EIP-712 signatures equal the R07 fixture byte for byte, anchoring takes only final unanchored attempts in order + tampered score gives match false, end-to-end badges (wallet and custodial), co-sign, revocations and mastery badge_id, offline nulls and 503 when required, co-sign needs registration). `test_auth` updated for the new user fields.
  - Hardhat 46 passing (contracts unchanged).
- **Open issues:**
  - One server-held educator wallet signs for every educator user; per-educator wallets (signing in the browser) would be a later change.
  - `GET /educator/documents` and the grading queue show every user's data to every educator (fine for the team as educators; no course scoping).
  - A send whose receipt times out may still land: for an anchor that leaves an orphan batch on chain (harmless; the retry anchors a new one); a mint could land without a DB row (the learner could claim again and get a second token). Not seen on Amoy.
  - Revoking a document does not block new quizzes on it yet; it blocks badge claims and co-signing.
  - No commits made: Deepesh commits and pushes.

## R09 — Web learning screens (2026-11-27)
- **Done:**
  - `lib/types.ts`: `User` adds `role` and `wallet_address`. `lib/api.ts`: `getMastery`, `getRevision`, `createRevision`, `getReviewSummary`; `createQuiz(…, mode, num_short)`; `ApiError.body` keeps the parsed error body (the review 409's `next_due`).
  - `components/facts.tsx`: `factIndex(sections)` and `FactChips` (F-numbered chips; a click shows the fact's text, page and section).
  - `/documents/[id]/mastery`: status tiles, concepts grouped weak → learning → untested → mastered (section, answered count, mastery bar, Source chips), "Revise" per weak or learning concept and "Generate notes for my 3 weakest concepts"; notes show every sentence with its cited fact chips and the Gate 1 dropped count. Mastered concepts show a disabled "Claim badge" (enabled in R10), or "Badge minted" when `badge_id` is set.
  - `/documents/[id]/review`: due now / next due / cards; "Start review quiz" (up to 10 due facts, optional 1 short answer); the "Nothing due" 409 shows the next due time.
  - `/quiz/[id]`: short-answer textarea (500 chars, counter, saved per tab; empty → null); results show the misconception and cited fact for the wrong choice picked, the other choices' misconceptions behind "Why the other choices are wrong", short answers with answer, model answer, verdict, confidence, grader and "Graded against" chips, "Waiting for educator" for deferred grades with "+N pending" under the score and "Check grading again" (reloads via `GET /attempts/{id}`). Sources stay hidden until submit (unchanged).
  - Document page: Mastery and Review buttons, "2 short answers" checkbox (on) for Start quiz; "New quiz" on the results also asks for 2 short answers.
  - Metrics page: Bloom levels card (accepted per level, mismatches, short answers, deferred grades) for demo step 7.
  - No API change. Real dev-DB shapes for mastery, revision, review, attempt results and `/auth/me` were checked against `lib/types.ts`.
- **How to run:** `./scripts/dev.sh db`, `./scripts/dev.sh api`, `./scripts/dev.sh web`, then open http://localhost:3000.
- **Test result:** `npm run build` OK (Next 16.4.4 stopped the first run with its security notice, as before; the rerun built all 13 routes), `npm run lint` clean. pytest 354 passed + 15 chain skips without a Hardhat node (369 with one, as in R08).
- **Open issues:**
  - "Claim badge" stays disabled until R10 (profile + educator screens).
  - Next.js 16.4.4 shows a security advisory on build; upgrading Next is a separate task for the team.
  - The review quiz time limit is 1 min per question (min 2 min); the practice quiz stays 10 questions / 10 min.
