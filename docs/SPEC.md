# SmartQuiz — Technical spec (source of truth for Review 1)

If a shape here must change, change it here first, then in code, and note it in `docs/STATUS.md`.

## 1. Database (PostgreSQL 16 + pgvector)

| Table | Columns |
| --- | --- |
| users | id uuid pk, email unique, password_hash, name, created_at |
| documents | id uuid pk, user_id fk, filename, file_sha256, fact_root (hex, nullable until ingestion finishes), fact_count int, sections_count int, facts_dropped int, facts_unfaithful int, register_tx (nullable), status (`ingesting`/`ready`/`failed`), created_at |
| sections | id serial pk, document_id fk, parent_id nullable, heading, level int, page_start, page_end, position int |
| facts | id serial pk, document_id fk, section_id fk, idx int (0-based, unique per document), concept, text, quote, page, char_start, char_end, text_hash (hex), leaf_hash (hex), embedding vector(384) |
| quizzes | id uuid pk, user_id fk, document_id fk, status (`generating`/`ready`/`failed`), quiz_hash (hex, nullable until ready), salt (hex, nullable until ready), commit_tx nullable, time_limit_sec int, started_at nullable, created_at |
| questions | id uuid pk, quiz_id fk, position int, stem, options jsonb (list of 4 strings), answer_index int, fact_idxs int[] (facts.idx values, sorted ascending), target_fact_idx int (facts.idx, always in fact_idxs), bloom_level (`remember`/`understand`), fingerprint, gate_results jsonb, dependence_score float, flagged_general bool, stem_embedding vector(384) |
| attempts | id uuid pk, quiz_id fk, user_id fk, answers jsonb, score int, total int, time_taken_sec int, created_at |
| fact_coverage | user_id, fact_id (facts.id), times_tested int, last_correct bool, last_bloom, updated_at — pk (user_id, fact_id) |
| generation_log | id serial pk, document_id fk, quiz_id nullable, candidate_id uuid nullable (one per generator output), gate (`gate0_fact`/`gate1`/`gate3`/`gate4`/`dup_fingerprint`/`dup_cosine`/`generator_error`), passed bool, reason text, same_family_fallback bool default false, created_at |

Indexes: HNSW on facts.embedding (cosine); unique (document_id, idx) on facts; unique (user_id, file_sha256) on documents; index on questions.fingerprint.

Fact references: `questions` store `facts.idx`, `fact_coverage` stores `facts.id`. Convert through (document_id, idx); never compare the two directly.

## 2. API (FastAPI, JSON, bearer JWT except where marked public)

```
POST /auth/signup        {email, password, name}            -> {token, user:{id,email,name}}
POST /auth/login         {email, password}                  -> {token, user}
GET  /auth/me                                               -> {id,email,name}

POST /documents          multipart file (.pdf or .txt)      -> DocumentOut
GET  /documents                                             -> [DocumentOut]
GET  /documents/{id}                                        -> DocumentOut
GET  /documents/{id}/textbook                               -> {document:DocumentOut, sections:[SectionOut]}
POST /documents/{id}/register                               -> DocumentOut   (retry chain registration)

POST /quizzes            {document_id, num_questions:10, time_limit_sec:600} -> QuizOut (returns immediately, status "generating")
GET  /quizzes/{id}                                          -> QuizOut (no answers; "questions":[] until started)
GET  /quizzes/{id}/progress                                 -> QuizProgressOut
POST /quizzes/{id}/start                                    -> QuizOut (with questions; sets started_at once; 409 unless status is "ready")
POST /quizzes/{id}/attempts {answers:[int|null], time_taken_sec} -> AttemptResult

POST /chat               {document_id, message}             -> ChatOut

GET  /metrics/{document_id}                                 -> MetricsOut

PUBLIC (no auth):
GET  /verify/question/{question_id}                         -> VerifyQuestionOut (409 until the quiz has a submitted attempt)
POST /verify/fact        {document_id, idx, text}           -> {leaf, verified_on_chain:bool|null, root, chain_status}
GET  /verify/quiz/{quiz_id}                                 -> VerifyQuizOut
```

Shapes:
```json
DocumentOut = {"id":"uuid","filename":"os_ch3.pdf","status":"ready","sections_count":12,"fact_count":184,
  "facts_dropped":9,"facts_unfaithful":2,"fact_root":"0x…","register_tx":"0x…|null","explorer_url":"https://amoy.polygonscan.com/tx/0x…|null",
  "chain_status":"confirmed","created_at":"iso"}

SectionOut = {"id":3,"heading":"3.2 Process Scheduling","level":2,"page_start":37,"page_end":41,
  "facts":[{"idx":214,"text":"…","page":37,"concept":"Round-robin scheduling"}],"children":[SectionOut]}

QuizOut = {"id":"uuid","document_id":"uuid","status":"ready","time_limit_sec":600,"quiz_hash":"0x…|null","commit_tx":"0x…|null",
  "explorer_url":"…|null","chain_status":"confirmed","questions":[{"id":"uuid","position":1,"stem":"…","options":["a","b","c","d"],
  "bloom_level":"remember","flagged_general":false}],
  "started_at":"iso|null","submitted":false,
  "generation":{"candidates":14,"accepted":10,"rejected":4}}
  // status "generating": "questions":[], "generation":null, quiz_hash and commit_tx null, chain_status "pending".
  // status "ready", not started: hash and commit fields filled, "questions":[].
  // After the attempt is submitted, each question also has "fact_idxs":[214]. Never before.
  // target_fact_idx and answer_index are never in QuizOut.
  // started_at lets the web timer survive a refresh; submitted is true once the attempt exists.
  // generation.rejected = candidates with a failed gate, validation or duplicate row; a spare that passed but was not needed is neither accepted nor rejected.

QuizProgressOut = {"accepted":6,"rejected":3,"target":10,"stage":"verifying"}
  // stage: selecting | generating | verifying | committing | done | failed

AttemptResult = {"attempt_id":"uuid","score":7,"total":10,"results":[{"question_id":"uuid","chosen":2,
  "correct_index":1,"correct":false,"sources":[{"idx":214,"text":"…","page":37,"section":"3.2 Process Scheduling"}]}],
  "weak_concepts":[{"concept":"Round-robin scheduling","wrong":2,"facts":[214,216]}]}
  // weak_concepts come from the target facts of wrong answers.

ChatOut = {"abstained":false,"answer":"… [F214] …","citations":[{"idx":214,"text":"…","page":37}],
  "nearest_sections":[],"best_similarity":0.71}
  // abstained: {"abstained":true,"answer":"This isn't covered in your material.","citations":[],
  //             "nearest_sections":[{"id":3,"heading":"…"},{"id":5,"heading":"…"}],"best_similarity":0.32}

MetricsOut = {"document_id":"uuid","candidates":28,"accepted":20,
  "rejected_by_gate":{"gate1":3,"gate3":4},   // plus "generator_error" when there are any"top_reasons":[{"gate":"gate1","reason":"…","count":2}],
  "duplicates_blocked":{"fingerprint":2,"cosine":1},"flagged_general":2,"avg_dependence":0.78,
  "repeat_rate_between_quizzes":0.0,"same_family_checker_used":false,"same_family_gate_calls":0}
  // candidates = distinct generation_log.candidate_id.
  // gate0_fact rows belong to ingestion (candidate_id null): exclude them from rejected_by_gate and top_reasons, which describe questions.
  // same_family_gate_calls counts them, because they are checker calls.
  // repeat_rate_between_quizzes = share of target facts that were the target in more than one of this user's quizzes for the document.

VerifyQuestionOut = {"question_id":"uuid","stem":"…","document_id":"uuid","doc_id_onchain":"0x…",
  "onchain_root":"0x…|null","db_root":"0x…","chain_status":"confirmed","facts":[{"idx":214,"text":"…","page":37,"text_hash":"0x…",
  "leaf":"0x…","proof":["0x…"],"verified_on_chain":true}],"registry_address":"0x…","explorer_url":"…|null"}

VerifyQuizOut = {"quiz_id":"uuid","recomputed_hash":"0x…","onchain_hash":"0x…|null","match":true,
  "chain_status":"confirmed","commit_tx":"0x…|null","explorer_url":"…|null"}
```

Rules:
- `answer_index` is never sent to the client before an attempt is submitted. `/verify/*` never returns answer keys.
- `fact_idxs` and Source chips are hidden until the attempt is submitted. `GET /verify/question/{id}` returns 409 `{"detail":"Available after the quiz is submitted"}` until then, otherwise a learner could read the cited facts mid-quiz.
- `chain_status`: `pending` (work not finished), `confirmed` (tx or on-chain read succeeded), `offline` (registration/commit/read failed or is missing). When offline, every `verified_on_chain`, `onchain_*` and `match` value is `null`, never `false`, and the UI shows a visible "chain offline" badge. `false` always means a real mismatch. With `CHAIN_OPTIONAL=false`, a failed read on `/verify/*` returns 503.
- `explorer_url` is null when the connected chain id is not 80002.

## 3. Ingestion (Textbook Mode)
1. Hash the file (sha256). Same user + same hash → return the existing document (idempotent).
2. Parse: PyMuPDF. Headings from `get_toc()`; if empty, detect by font size/bold; fallback one section per page. `.txt`: lines that look like headings (short, no full stop, numbered or Title Case) start sections.
   Skipped while parsing: page footers matching `N / N`, and text under the headings in `SKIPPED_HEADINGS` (`app/ingest/prompts.py`), up to the next bold line at least as large as that heading.
3. Consecutive sections are packed into chunks of up to 6000 chars (a longer section is split at sentence ends), to save requests → one generator call per chunk → JSON `{"facts":[{"fact": str, "quote": str, "concept": str}]}` (an object, because the provider forces JSON object mode).
   - fact = one self-contained claim (understandable without the passage); quote = verbatim text copied from the chunk.
   - Coverage: if the reply's located quotes end before 75% of the chunk (and at least 1000 chars remain), one follow-up call extracts the rest. A reply that fails JSON validation twice (`BadJSONError`, usually too long) is retried as two halves cut at the sentence end nearest the middle, at most 2 levels deep. Generator `reasoning_effort` comes from `GENERATOR_REASONING_EFFORT` (`low`), because gpt-oss at the default effort spent its output on reasoning.
4. Locate quote in its chunk: exact `find`, else rapidfuzz `partial_ratio_alignment` ≥ 90 (exact only under 20 chars) → char_start/char_end in section text (whitespace collapsed to single spaces), page from offset map. `facts.quote` stores the source span at those offsets. Not found, malformed, or crossing two sections → drop, count `facts_dropped`.
4a. Faithfulness (`gate0_fact`): one batched checker call per chunk, on the located quotes and their facts. Input `{"items":[{"id","quote","fact"}]}`, output `{"faithful":[id],"not_faithful":[{"id","reason"}]}` (compact, to fit the checker's 1000 output tokens per minute; only rejections carry a reason). NOT_FAITHFUL → drop, count `facts_unfaithful`. Each check → one `generation_log` row (`candidate_id` and `quiz_id` null). Missing verdicts → retry once with attempt = 1, then treated as NOT_FAITHFUL. A wrong-shaped reply twice → the document is `failed`.
5. De-duplicate facts within a document by cosine ≥ 0.95, keeping the first in reading order. Not counted in `facts_dropped`.
6. idx assigned 0..n-1 in reading order. text_hash, leaf, embedding. Merkle root over leaves per section 8. Zero facts → status `failed`.
7. Attempt chain registration, then set status `ready`. Failure does not block: register_tx stays null, `status` is still `ready`, `chain_status` is `offline`.

## 4. Quiz generation and gates
`POST /quizzes` creates the quiz with status `generating` and returns immediately. A background job does selection, generation, gates and duplicate checks, saves the questions, computes quiz_hash, commits on chain, then sets status `ready`. If it cannot produce any question, or the commit fails with `CHAIN_OPTIONAL=false`, status is `failed`. Failed quizzes do not count as used in selection.

Selection (N target facts, for this user + document), in order:
1. Unused: never `target_fact_idx` of an earlier non-failed quiz, even if that quiz has no attempt.
2. `last_correct=false`, oldest first.
3. Used as a target but never answered.
4. Oldest tested.

Spread across sections proportional to fact count; max 2 targets per concept.
Only the target fact counts as used or covered. A context fact in `fact_idxs` does not. "0 repeated facts" means 0 repeated target facts, and holds until unused facts run out.

Retesting a fact (tiers 2–4): ask for the other `bloom_level` than `last_bloom` (or than the earlier question's level), so the fingerprint differs. If still a duplicate, drop it and take the next fact.

Generator prompt output (JSON): `{"questions":[{"target_idx", "stem", "options":[4], "answer_index", "fact_idxs":[target + up to 2 same-section idx], "bloom_level"}]}` (`target_idx` maps each question back to its target). Context offered per target: up to 4 same-section facts nearest by idx. A reply item that is missing or malformed is logged as `generator_error` and joins the batched regeneration. First call: N targets + max(2, ceil(0.3·N)) spares, interleaved across sections so the first N kept stay spread.
Gates run as one batched checker call each (Gate 1 and Gate 3 in parallel, then Gate 4 on the survivors); ids still missing get one more call with attempt = 1, then fail closed. Gate 3 and Gate 4 see the options shuffled (seeded by candidate_id).
Distractors must be plausible and must not be true according to the cited facts.

| Gate | Model | Input | Pass rule |
| --- | --- | --- | --- |
| gate1 grounding | checker | cited fact texts + stem + correct option | verdict `SUPPORTED` |
| gate3 solvability | checker | cited fact texts + stem + options shuffled | picks the correct option |
| gate4 dependence | checker | stem + options only (no facts) | always passes; returns choice + confidence 0–100 |

dependence_score = 1 − (confidence/100 if blind choice correct else 0). `flagged_general = dependence_score < 0.3`.
Duplicate checks after gates: fingerprint, then cosine ≥ 0.85 vs earlier stems (same user + document).
Request budget: all target questions come from ONE generator call (attempt = 0). Targets that fail Gate 1 or 3 share ONE batched regeneration call (attempt = 1; the attempt number is part of the LLM cache key); a target that fails again is dropped. To end up with N questions, the first call may request spare targets beyond N.
Checker responses are JSON with a short `reason`. Every gate call → one `generation_log` row.

`gate_results` (integers only, no floats, so the hash is stable):
`{"gate1":{"verdict":"SUPPORTED","reason":"…"},"gate3":{"passed":true,"choice":1,"reason":"…"},"gate4":{"choice":1,"confidence":40,"reason":"…"}}`
`choice` is the index in the stored option order, mapped back from any shuffle.

Checker independence depends on the model family, not the vendor: generator and checker both run on Groq, using `openai/gpt-oss-120b` and `qwen/qwen3.8-27b`. Family = the model id before `/`, otherwise before the first `-` (`provider.model_family`).

Same-family fallback (emergency only): if the checker must use a model of the generator's family, gate calls are logged with `same_family_fallback=true`, and the metrics page shows a warning banner with the count. Revert it before the demo if possible; if not, say so on stage. Gemini remains an optional generator: set GENERATOR_BASE_URL to its URL and LLM_GENERATOR_MODEL to a Gemini model, and `provider.py` uses GEMINI_API_KEY.

Limits (`provider.py`): each role has RPM, TPM and REQUESTS_PER_DAY in `.env`. Every network request, including retries, counts against the day's budget (UTC, per role and model, in `api/.cache/llm.sqlite`); cache hits do not. Budget spent, or a provider reporting a daily limit → `DailyLimitError` at once with no retries. Per-minute 429s wait and retry, honouring `Retry-After`.

## 5. Chat
Embed message → top 8 facts by cosine (same document). best < CHAT_MIN_SIM → abstain with 2 nearest section headings (by section-heading embedding or by the sections of the top facts).
Else generator answers using only those facts, citing `[F<idx>]`. Post-check: cited idx ⊆ retrieved; else retry once (attempt = 1), then abstain.

## 6. Smart contract `SmartQuizRegistry.sol` (Amoy)
```solidity
constructor(address initialOwner)                // OpenZeppelin v5 Ownable
function registerDocument(bytes32 docId, bytes32 factRoot, uint32 factCount) external onlyOwner;   // event DocumentRegistered(docId, factRoot, factCount)
function commitQuiz(bytes32 quizId, bytes32 docId, bytes32 quizHash) external onlyOwner;           // event QuizCommitted(quizId, docId, quizHash); reverts if already committed or doc unknown
function verifyFact(bytes32 docId, bytes32 leaf, bytes32[] calldata proof) external view returns (bool); // MerkleProof.verify
function getDocument(bytes32 docId) external view returns (bytes32 factRoot, uint32 factCount, uint64 registeredAt);
function getQuiz(bytes32 quizId) external view returns (bytes32 docId, bytes32 quizHash, uint64 committedAt);
```
quizId on chain = keccak256(utf-8 quiz UUID string).
Explorer: `https://amoy.polygonscan.com/tx/<hash>`.

Local fallback: run `npx.cmd hardhat node`, then `npx.cmd hardhat run scripts/deploy.ts --network localhost`. The script uses the issuer address as owner, sends the issuer 100 test ETH from account 0, and prints the address. It writes REGISTRY_ADDRESS to `.env` only for `--network amoy`. To use the local chain, set AMOY_RPC_URL=http://127.0.0.1:8545 and REGISTRY_ADDRESS to the printed value by hand, keeping the Amoy address noted. ChainService reads the chain id from the RPC.

## 7. Web pages (Next.js)
`/login`, `/signup`, `/` (my documents + upload), `/documents/[id]` (textbook tree, upload card with root + tx link, buttons: Start quiz, Chat, Metrics), `/quiz/[id]` (generation progress bar, then timer, one question per screen, Source chip after submit only, result + weak concepts), `/documents/[id]/chat`, `/documents/[id]/metrics`, `/verify` (public; question ID or quiz ID).
Any page showing chain data shows a visible "chain offline" badge when `chain_status` is `offline`.
The web app always uses the real API. Mock data is for tests only.

Attempt timing: `POST /quizzes/{id}/start` sets `started_at`, and the server enforces `now − started_at ≤ time_limit_sec + 30`. Neither generation time nor time on the start screen counts against the learner. `time_taken_sec` is for display.

## 8. Exact hash formats
All hashes are stored and returned as lowercase hex with `0x`, except `salt` and `fingerprint` (lowercase hex, no prefix).

**Fingerprint**
```
sha256(utf-8(",".join(str(i) for i in sorted(set(fact_idxs))) + "|" + bloom_level)).hexdigest()
example: fact_idxs [216, 214], "remember" → sha256 of "214,216|remember"
```

**Merkle tree**
- text_hash = keccak256(utf-8 fact text), with no normalisation.
- leaf = keccak256(keccak256(abi.encode(uint256 idx, bytes32 text_hash))), the OpenZeppelin leaf format.
- Leaves stay in our idx order. They are not sorted first, so the root differs from OpenZeppelin's JS `StandardMerkleTree`, but proofs verify with Solidity `MerkleProof.verify`.
- Build level by level, pairing left to right: parent = keccak256(min(a,b) || max(a,b)), comparing the 32 bytes as unsigned big-endian.
- An odd last node is promoted unchanged to the next level.
- One leaf: root = leaf. Zero leaves: an error.
- Proof = sibling hashes from bottom to top, with nothing added at levels where the node was promoted.

**quiz_hash**
```python
salt = secrets.token_hex(16)   # 32 lowercase hex chars, no 0x
obj = {"questions": [{"stem": ..., "options": [...], "answer_index": ..., "fact_idxs": [...], "gate_results": {...}}
                     for q in questions ordered by position ascending], "salt": salt}
canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
quiz_hash = "0x" + keccak256(canonical).hex()
```
`target_fact_idx`, `dependence_score`, `flagged_general` and `bloom_level` are not hashed.
