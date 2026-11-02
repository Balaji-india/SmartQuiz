---
description: Debug an error with the smallest fix that keeps SPEC and closed-book rules intact
argument-hint: <paste the error or describe what is broken>
---
Find and fix this problem in SmartQuiz with the smallest correct change.

Problem: $ARGUMENTS

/context: CLAUDE.md, docs/SPEC.md, docs/STATUS.md.
/debug: Reproduce it first (run the failing command or test). Find the root cause before editing; explain it in 2–3 sentences.
/constraints: Do not change API shapes, hashing formats or closed-book rules unless the bug is in them; if so, ask me first. No unrelated refactors.
/test: Add or update a test that fails before the fix and passes after. Run the affected test suite.

When finished: commit "fix: <short description>" and append one line to docs/STATUS.md.
