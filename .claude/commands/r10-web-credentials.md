---
description: R10 · Web credentials screens — profile + badges, educator page, Verify Result and Badge tabs
---
Build the credential screens against the real API.

/context: docs/SPEC.md sections 9.8–9.10; existing web patterns (see R09), the Verify page from P10.
/workflow:
1. /profile: wallet address form (custodial notice when empty, checksum errors shown), my badges with token id, holder, explorer and Verify links, revoked state.
2. Mastery page: Claim badge enabled for mastered concepts.
3. /educator (role guard): tabs Documents (co-sign, revoke with reason), Grading queue (facts, model answer, learner answer, checker verdict → grade), Results (unanchored count, Anchor now), Badges (revoke with reason).
4. /verify: Result tab (attempt ID → hash, proof, on-chain root, match) and Badge tab (token ID → holder, hashes, on-chain match, revoked); Question tab shows co-signed by and document revoked.
5. Header: Profile, and Educator for educators. ChainBadge on every chain view.
/test: build + lint. Then I check final demo steps 10–12 in the browser; give me the exact click path.

First show a short plan and wait for my "go". When finished: run the API tests (and any other suite you touched), append an entry to docs/STATUS.md (done, how to run, test result, open issues), suggest a commit message for Deepesh (do not commit or push), then tell me to run /compact.
