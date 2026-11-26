---
description: R08 · Credentials API — roles, wallet, result anchoring, badges (address or custodial), co-sign, revocation, verify endpoints
---
Wire the credentials contract into the API so results, badges and educator actions are verifiable.

/context: CLAUDE.md rules 6 and 7; docs/SPEC.md sections 2 (chain_status rules), 9.7 (apply_educator_grade) and 9.9. Code: api/app/chain/service.py (extend, same nonce lock and fee logic), routers, new api/app/routers/educator.py, badges.py.
/workflow:
1. Migration per SPEC 9.9. api/scripts/make_educator.py <email>.
2. attempt_hash when grading becomes final; merkle batch of unanchored final attempts; POST /educator/anchor.
3. Badges: POST /badges (mastered check, anchor first if needed, holder = wallet_address or custodial; custodial refused with 503 while CUSTODY_SECRET is empty, SPEC 9.9), GET /badges, PUT /auth/me/wallet, /auth/me role + wallet.
4. Educator: grading queue + grade (calls apply_educator_grade), documents list, cosign (EIP-712 signature with EDUCATOR_PRIVATE_KEY via eth_account, matching the contract's domain), revoke document, revoke badge (signed reason hash).
5. Public /verify/attempt and /verify/badge; VerifyQuestionOut cosign + document_revoked. Offline → nulls (503 when CHAIN_OPTIONAL=false).
6. MasteryOut.badge_id filled.
/test: role guard 403, wallet validation, custodial address deterministic, attempt hash stable, anchoring batches only final unanchored attempts, badge 409 when not mastered, EIP-712 digest matches the R07 fixture, verify endpoints with a local Hardhat node (skip without one, as before), offline null rules.
/stats: Real Amoy run: anchor tx, badge mint to the learner MetaMask address and to a custodial one, co-sign tx, revoke tx; POL spent per tx.

First show a short plan and wait for my "go". When finished: run the API tests (and any other suite you touched), append an entry to docs/STATUS.md (done, how to run, test result, open issues), suggest a commit message for Deepesh (do not commit or push), then tell me to run /compact.
