---
description: P03 · SmartQuizRegistry Solidity contract, tests, and Python↔Solidity Merkle cross-check
---
Write the SmartQuizRegistry contract with full tests and prove our Python Merkle proofs verify on chain.

/context: CLAUDE.md Hashing, docs/SPEC.md sections 6 (exact function signatures and local fallback) and 8. contracts/ and api/app/chain/merkle.py were created in P00.
/code: contracts/contracts/SmartQuizRegistry.sol — OpenZeppelin v5 `Ownable(initialOwner)` and `MerkleProof`; structs for Document and Quiz; events; custom errors (UnknownDocument, AlreadyRegistered, AlreadyCommitted).
/code: contracts/scripts/deploy.ts — uses the address of ISSUER_PRIVATE_KEY as owner and prints the contract address. Only when `network.name === "amoy"`, it writes REGISTRY_ADDRESS into ../.env (replace the line, keep every other line and the existing line endings, never print other values). On `localhost` it never touches .env and sends the issuer 100 test ETH from account 0, per SPEC section 6.
/details: Reuse merkle.py; do not write a second implementation. Leaf = keccak256(bytes.concat(keccak256(abi.encode(uint256 idx, bytes32 textHash)))), sorted-pair internal nodes, leaves in idx order, odd node promoted. This matches OpenZeppelin's leaf format and `MerkleProof.verify`, not the root of its JS `StandardMerkleTree`.
/test:
- Hardhat tests: register, duplicate register reverts, onlyOwner reverts for others, commitQuiz happy path, re-commit reverts, unknown doc reverts, getters return stored values, verifyFact true for a valid proof and false for a tampered leaf.
- Cross-check: a Python script (api/scripts/merkle_fixture.py) writes 7 facts' leaves, root and the proof for every index to contracts/test/fixtures/merkle.json; the Hardhat test loads it, registers the root and checks verifyFact true for all (including the promoted node), and false after changing one byte of a leaf.
/constraints: Solidity ^0.8.20, no upgradeability, no strings or text stored on chain, no payable functions.
/workflow: After tests pass, deploy to a local node (`npx.cmd hardhat node` + `npx.cmd hardhat run scripts/deploy.ts --network localhost`) and confirm .env is unchanged. Deploy to Amoy only if the issuer wallet has test POL; otherwise note it in STATUS.

First show a short plan and wait for my "go". When finished: commit "feat: registry contract", append a P03 entry to docs/STATUS.md (contract address if deployed), then tell me to run /security-review and after fixing, /compact.
