---
description: R09 · Web learning screens — mastery + gap report, revision notes, review queue, short answers, misconceptions in results
---
Build the learning screens against the real API.

/context: docs/SPEC.md sections 7, 9.4–9.7 and 9.10; existing web/ patterns (lib/api.ts one function per endpoint, lib/types.ts, components/ui.tsx, server page.tsx wrapping a client view in Suspense, useLoad; Next.js 16 notes in STATUS).
/workflow:
1. Types and api functions for the new endpoints.
2. /documents/[id]/mastery: summary tiles, concepts by status with section + Source chips, revision notes (generate/view, fact chips per sentence), Claim badge placeholder (enabled in R10).
3. /documents/[id]/review: due now / next due, Start review quiz (handles the 409).
4. /quiz/[id]: short-answer textarea; results with misconceptions + sources per wrong choice, short-answer grade, "waiting for educator" state; results reload via GET /attempts.
5. Document page: buttons for Mastery and Review.
/constraints: Same deck theme; no mock data outside tests; keep sources hidden before submit.
/test: `cd web && npm run build && npm run lint`. Then I check final demo steps 7–9 in the browser; give me the exact click path.

First show a short plan and wait for my "go". When finished: run the API tests (and any other suite you touched), append an entry to docs/STATUS.md (done, how to run, test result, open issues), suggest a commit message for Deepesh (do not commit or push), then tell me to run /compact.
