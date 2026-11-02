---
description: Summarise progress into docs/STATUS.md and print an update to paste back to Claude in the chat
argument-hint: [optional note, e.g. a blocker]
---
Write a progress update for the SmartQuiz team that I can paste into my planning chat with Claude.

/context: CLAUDE.md, docs/PLAN.md, docs/STATUS.md, `git log --oneline -20`, `git status`, and the test commands in CLAUDE.md.
/analyze: Run the test suites that exist (api pytest, contracts hardhat test, web `npm.cmd run build`) and record pass/fail counts. Do not fix anything in this command.
/summary: Map progress to the PLAN sequence P00–P11 and the 6 demo steps: done / in progress / not started / blocked.
/key-points: Blockers and errors with the exact error message (first 15 lines), decisions made that differ from SPEC, what should run next, and what the reviewers should check.
/format: Print one markdown block titled "SmartQuiz update — <date time>" under 300 words, ready to copy. Then add the same block to the top of docs/STATUS.md under a "## Updates" heading.
Extra note from me: $ARGUMENTS
