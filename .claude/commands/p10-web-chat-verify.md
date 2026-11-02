---
description: P10 · Web chat with citations/abstain state and the public Verify page with tamper test
---
Add the closed-book chat screen and the public Verify page to the web app.

/context: docs/SPEC.md (ChatOut, VerifyQuestionOut, VerifyQuizOut, POST /verify/fact, Rules), docs/PLAN.md demo steps 4–6. P09 is done; reuse its styles, types, api.ts and ChainBadge.
/structure:
- /documents/[id]/chat: message list; answers render [F214] as chips that open the fact (text + page); abstained replies show "This isn't covered in your material" in a muted card with the two nearest sections as links to the textbook tree.
- /verify (public, no login): tabs "Question" and "Quiz"; reads ?question= or ?quiz= from the URL.
  - Question tab: stem, then for each fact an editable textarea with the fact text, its leaf, proof list (collapsible), on-chain root vs DB root, and a big badge: green "Verified on Polygon Amoy", red "Not verified" (false), or the "chain offline" badge (null, never shown as red). A "Re-check" button calls POST /verify/fact with the edited text so reviewers can watch tampering fail. A 409 shows "Available after the quiz is submitted".
  - Quiz tab: recomputed hash, on-chain hash, match badge (same three states), commit tx explorer link.
- On quiz results (P09) each question gets a small "Verify" link to /verify?question=<id>.
/constraints: Verify page works logged out and on mobile. Hashes in monospace, shortened with copy buttons.
/test: `npm.cmd run build`; walk through demo steps 4–6 on the real API, including a question from an unsubmitted quiz (409 message) and one run with the chain unreachable (offline badge).

First show a short plan and wait for my "go". When finished: commit "feat: chat and verify pages", append a P10 entry to docs/STATUS.md, then tell me to run /compact.
