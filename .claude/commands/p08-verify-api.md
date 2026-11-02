---
description: P08 · Public verify endpoints — question grounding proofs, tamper check, quiz hash match
---
Add the public endpoints that let anyone verify a question's grounding and a quiz's integrity.

/context: docs/SPEC.md sections 2 (VerifyQuestionOut, VerifyQuizOut, POST /verify/fact, Rules), 6 and 8; api/app/chain/merkle.py and quizhash.py. P06 is done.
/api:
- GET /verify/question/{id}: 409 until the quiz has a submitted attempt (SPEC section 2 Rules). Then for each cited fact → text, page, text_hash, leaf, proof (rebuilt from the document's leaves), verified_on_chain from ChainService.verify_fact; plus db_root, onchain_root, chain_status, registry address, explorer link.
- POST /verify/fact {document_id, idx, text}: recompute text_hash + leaf from the given text, use the stored proof for that idx, call verify_fact. Editing one word must return false.
- GET /verify/quiz/{id}: recompute quiz_hash from stored data + salt, read the on-chain hash, return match.
- When a chain read fails: with CHAIN_OPTIONAL=true return `chain_status: "offline"` and null for verified_on_chain, onchain_* and match, never false; with CHAIN_OPTIONAL=false return 503.
/constraints: No auth. Read-only. Never return answer_index or options' correctness. Cache each document's leaves in memory to keep responses fast. Rate-limit lightly (e.g., 30 requests/minute per IP) if simple.
/test: Valid question after an attempt → all facts verified true; before an attempt → 409; tampered text → false; quiz match true; after editing a stored question in the test DB → match false; chain down with CHAIN_OPTIONAL=true → offline with nulls.

First show a short plan and wait for my "go". When finished: commit "feat: verify endpoints", append a P08 entry to docs/STATUS.md, then tell me to run /security-review, fix findings, then /compact.
