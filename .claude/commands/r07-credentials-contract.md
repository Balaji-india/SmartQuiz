---
description: R07 · SmartQuizCredentials.sol — result anchoring, ERC-5192 badges, EIP-712 educator co-sign and revocation; deploy to Amoy
---
Write the second contract (the registry stays unchanged), test it fully, cross-check with Python, and deploy it.

/context: CLAUDE.md Hashing and rule 6; docs/SPEC.md sections 6, 8, 9.8 and 9.9 (hash formats). contracts/ (Hardhat 2.29.1, toolbox 6.1.2, OpenZeppelin 5.x already installed).
/code: contracts/contracts/SmartQuizCredentials.sol per SPEC 9.8 (Ownable, ERC721, EIP712, ECDSA, MerkleProof; custom errors NotEducator, BatchExists, UnknownBatch, Soulbound, RootMismatch, AlreadyRevoked, UnknownToken). contracts/scripts/deploy-credentials.ts per SPEC 9.8.
/test:
- Hardhat: educator add/remove (onlyOwner), anchor + duplicate revert, verifyResult true/false, mint emits Locked, locked() true, supportsInterface 0xb45a3c0e, every transfer path reverts, getBadge, revokeBadge with valid educator sig / non-educator sig / replay on revoked, coSign with matching root / mismatching root / non-educator, revokeDocument, tokenURI has no text.
- Cross-check: api/scripts/credentials_fixture.py writes attempt-hash leaves, root, proofs and EIP-712 signatures made in Python (eth_account) to contracts/test/fixtures/credentials.json; Hardhat verifies them. Reuse merkle.py.
/workflow: Local node deploy first (.env untouched). Then Amoy, only if the issuer balance covers it (print balance first); record CREDENTIALS_ADDRESS and the educator address in STATUS. If POL is short, stop and tell me.
/fees: Amoy rejects tips below 25 gwei and Hardhat's default can sit unmined (seen 2026-11-26 in transfer-owner.ts). Use `amoyFees()` from scripts/fees.ts in deploy-credentials.ts (tip = max(network tip, 30 gwei)); the Python ChainService uses the same 30 gwei floor.
/constraints: Solidity ^0.8.20, no upgradeability, no strings with user or document text on chain, no payable.

First show a short plan and wait for my "go". When finished: run the API tests (and any other suite you touched), append an entry to docs/STATUS.md (done, how to run, test result, open issues), suggest a commit message for Deepesh (do not commit or push), then tell me to run /compact.
