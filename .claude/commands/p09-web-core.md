---
description: P09 · Web core — auth, documents + upload, textbook tree, timed quiz with sources, results, metrics
---
Build the main SmartQuiz web screens in Next.js against the real API, which already exists at this point.

/context: CLAUDE.md, docs/SPEC.md sections 2 (all shapes) and 7 (pages), docs/PLAN.md demo steps 1–3. P00–P08 are done.
/style: Match our Review 1 deck: deep navy (#13203B) panels, warm off-white (#F6F4EF) background, orange accent (#E8913F) for highlights, Space Grotesk for headings and IBM Plex Sans for body (Google Fonts via next/font). Calm, clean, no gradients. Works on a laptop projector and on mobile.
/structure:
- lib/types.ts: TypeScript types copied from SPEC shapes. lib/api.ts: one function per endpoint, always calling the real API. Mock data lives only in test fixtures, with no runtime mock switch.
- A shared `ChainBadge` component: shows a visible "chain offline" badge when `chain_status` is `offline`.
- /signup, /login: forms, token stored in localStorage, redirect to /.
- /: my documents list + drag-and-drop upload (.pdf/.txt); while status is `ingesting`, poll every 3 s with a progress message.
- /documents/[id]: upload card (sections, facts, facts dropped, Merkle root shortened with copy button, "View on Polygon Amoy" link when register_tx and explorer_url exist, ChainBadge); collapsible section tree; clicking a fact shows text, page and concept; buttons Start quiz (10 questions, 10 minutes), Chat, Metrics.
- /quiz/[id]: Start quiz calls POST /quizzes, which returns immediately with status `generating`. While generating, poll GET /quizzes/{id}/progress and show "Verifying question 6 of 10 · 3 rejected so far" (from accepted, rejected, target, stage); handle `failed`. Once `ready`: start screen with the commit tx link and ChainBadge; its Begin button calls POST /quizzes/{id}/start; then countdown timer, one question per screen with progress dots, "general knowledge" tag when flagged_general, submit (auto-submit at 0:00). No Source chips or fact references before submit. Results: score, each question correct/incorrect with a "Source" chip showing fact text, page, section; weak concepts list; buttons "New quiz (no repeats)" and "Verify this quiz" (links /verify?quiz=<id>).
- /documents/[id]/metrics: bar or stat tiles for accepted vs rejected per gate, top reasons, duplicates blocked, flagged general, average dependence, repeat rate. If same_family_checker_used is true, show a warning banner: "Emergency fallback: same-family checker used for N gate calls".
/constraints: No UI library heavier than Tailwind (shadcn/ui components are fine). Loading and error states on every page. Never show answer_index or sources before submission.
/test: `npm.cmd run build` passes; click through every page with the real API running, including one run with the chain unreachable to see the "chain offline" badge. Record results in STATUS.

First show a short plan and wait for my "go". When finished: commit "feat: web core screens", append a P09 entry to docs/STATUS.md, then tell me to run /compact.
