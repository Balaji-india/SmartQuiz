---
description: P02 · Textbook Mode ingestion (PDF/TXT → sections → verified atomic facts → hashes → Merkle root)
---
Build the Textbook Mode ingestion pipeline and the document upload endpoints.

/context: CLAUDE.md (closed-book rules 1–2, Hashing), docs/SPEC.md sections 1, 2 (/documents), 3 and 8. P01 is done.
/focus: api/app/ingest/ (parser.py, extractor.py, locator.py, hasher.py, pipeline.py), api/app/routers/documents.py.
/workflow: Follow SPEC section 3 steps 1–6 exactly. Step 7 (chain registration) is P04 — leave a clear hook `register_document_onchain(document)` that does nothing yet.
/details:
- Reuse api/app/chain/merkle.py from P00. Do not write a second implementation.
- Extraction prompt: system prompt that demands JSON only; each fact one self-contained claim; quote copied character-for-character; concept = short noun phrase. Put the prompt text in app/ingest/prompts.py so we can tune it.
- Embeddings: load bge-small-en-v1.5 once (module-level singleton), normalize vectors.
- Upload runs ingestion in a FastAPI BackgroundTask; document.status moves ingesting → ready/failed; GET /documents/{id} lets the web poll.
- GET /documents/{id}/textbook returns the nested section tree per SPEC.
- DocumentOut includes `chain_status`, derived: `pending` while ingesting, `confirmed` when register_tx exists, otherwise `offline`.
/constraints: All LLM calls through app/llm/provider.py (generator model). Max file size 25 MB. Idempotent on (user, file_sha256). Read and write text as UTF-8 explicitly.
/examples: "Round-robin gives each process a fixed time quantum." → idx 214, page 37, chars 1022–1071, concept "Round-robin scheduling".
/test:
- Generate a 3-page fixture PDF in api/tests/fixtures/ with reportlab (two headings, a few factual paragraphs).
- With the FAKE LLM: pipeline produces facts, every fact's quote is found at its offsets, root is identical across two runs, tampering one fact text changes the root.
- One live run (real API key) on samples/sample.pdf if it exists.
/stats: Print sections, facts kept, facts dropped, root and seconds taken for samples/sample.pdf.

First show a short plan and wait for my "go". When finished: commit "feat: textbook ingestion", append a P02 entry to docs/STATUS.md including the stats, then tell me to run /compact.
