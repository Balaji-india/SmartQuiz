---
description: R12 · Mini project report (docs/REPORT.md → PDF) and the final presentation prompt with real metrics
---
Write the mini project report and prepare the final slides from real results.

/context: docs/SUMMARY.md, docs/RESEARCH.md, docs/PLAN.md, docs/SPEC.md, docs/STATUS.md (final R11 metrics), docs/SLIDES-PROMPT.md.
/report: docs/REPORT.md, about 15–20 pages as PDF: title page (SmartQuiz, CMRIT, team, industry partner Dopove Private Limited), abstract, introduction and problem, literature survey (from RESEARCH.md), objectives, system design (architecture, Textbook Mode, gates, selection, chain design, hashing), implementation (stack, modules), results (tables from the final metrics, honest weak points), testing, conclusion and future work (ZK proof if not built), references. Diagrams as Mermaid or simple tables. Ask me for any college template rules (headings, fonts, page count) before writing.
/export: docs/REPORT.pdf (pandoc if installed, else a small reportlab script in api/scripts/); check that the page count and tables render.
/slides: Update docs/SLIDES-PROMPT.md for the final deck (use in the Claude app): Proof of Grounding headline, architecture with both contracts, comparison slide, results slide with real numbers, live demo outline, future work. Max 25 words of body text per slide, navy/orange style.
/constraints: Only real numbers from STATUS/R11; never invent results. No personal data beyond the team names.

First show the outline and wait for my "go". When finished: append to docs/STATUS.md, suggest a commit message for Deepesh (do not commit or push).
