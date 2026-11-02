---
description: P04 · web3.py chain service and on-chain document registration after ingestion
---
Connect the API to SmartQuizRegistry and register every ingested document's Merkle root on chain.

/context: CLAUDE.md (Hashing, Env), docs/SPEC.md sections 2, 3 and 6. P02 and P03 are done; REGISTRY_ADDRESS is in .env if Amoy is funded.
/code: api/app/chain/service.py — a `ChainService` using web3.py: load ABI from contracts/artifacts (copy the ABI JSON to api/app/chain/abi/SmartQuizRegistry.json so the API does not depend on a Hardhat build), issuer account from ISSUER_PRIVATE_KEY, chain id read from the RPC, methods register_document, commit_quiz, verify_fact, get_document, get_quiz. Handle nonce (serialize transactions with a process-wide lock, since one wallet signs everything), gas estimation, EIP-1559 fees, wait for receipt (timeout 120 s), return tx hash hex.
/integrate: Implement the P02 hook `register_document_onchain`: doc_id = keccak256(document UUID string); save register_tx; DocumentOut gets explorer_url (null unless chain id is 80002) and chain_status. POST /documents/{id}/register retries a failed registration.
/constraints: If CHAIN_OPTIONAL=true and the RPC or wallet fails, log a warning, leave register_tx null, report `chain_status: "offline"` and continue. Never log the private key. Only hashes leave the server.
/test: pytest with a local Hardhat node (skip the test cleanly if no node on 127.0.0.1:8545). The test deploys its own registry with a public Hardhat test key and never reads REGISTRY_ADDRESS or ISSUER_PRIVATE_KEY from .env. Include chain failure → `offline` with CHAIN_OPTIONAL=true. Then one real Amoy run: upload samples/sample.pdf and open the explorer link.

First show a short plan and wait for my "go". When finished: commit "feat: on-chain document registration", append a P04 entry to docs/STATUS.md with the tx link, then tell me to run /compact.
