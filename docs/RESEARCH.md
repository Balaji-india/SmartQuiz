# SmartQuiz — Research summary (Step 1)

## Bottom line
Source-grounded AI quizzes already exist (Google NotebookLM, Sept 2025), and several hackathon/grant projects pair AI
quizzes with blockchain certificates. So "AI quiz + blockchain badge" alone is not unique.
**Our unique claim: Proof of Grounding** — anyone can verify that a specific AI-generated question came from a specific
fact of a specific document, passed verification gates, and was committed on chain before the attempt.

## Closest existing solutions
| Solution | What it does | Gap vs SmartQuiz |
| --- | --- | --- |
| NotebookLM Flashcards & Quizzes | Quizzes grounded in uploaded sources, with citations; adjustable topic/difficulty | No verifiable provenance, no closed-book abstention, no gate metrics |
| ICanProveIt (Stellar) | AI exams from studied content, on-chain certificates, coverage score | Certifies results, not question grounding |
| LearningRec (Celo) | AI quizzes on YouTube paths, on-chain certificate | No source citations |
| Proof of Learning (ETHGlobal) | AI tutor, MCQ pass mark, soulbound NFT | Course-level pass/fail only |
| ProofLearn (HackQuest) | Human-reviewed tasks, soulbound credential | Not document quizzes |
| Blockchain online exams (IEEE Access 2024) | Moodle questions/answers stored on chain | Human-written questions, no AI grounding |

## Papers and what we take from them
| Paper | Idea we use |
| --- | --- |
| Curriculum-aligned MCQs with GenAI (arXiv 2508.04442) | RAG beats non-grounded prompting for curriculum MCQs |
| MCQGen (IEEE Access 2024) | Self-refine loop; we refine against a separate verifier |
| Hallucination-free MCQ generation (arXiv 2601.14280) | Multi-agent detectors, >90% fewer hallucinations → our gates |
| CaLM (arXiv 2406.05365) | Small model verifies the large model's citations → checker model |
| HALOGEN (ACL 2025) | Atomic-fact verification → Textbook Mode facts |
| Corrective RAG (arXiv 2401.15884) | Retrieval evaluator → our abstain threshold (no web fallback) |
| RAPTOR (ICLR 2024) | Tree-organised retrieval → section/concept/fact tree |
| KAQG (arXiv 2505.07618) | Chapter-proportional question budget, concept ranking |
| K12-KGraph (2026) | Textbook KG with evidence backlinks |
| Concept-map MCQs (arXiv 2505.02850) | Misconception-targeted distractors (Review 2) |
| Math distractor generation (NAACL 2024) | LLM distractors miss real student errors → distractor gate (Review 2) |
| Dedup studies (arXiv 2505.04132, 2608.11074) | Embedding-similarity dedup → our cosine 0.85 backup |
| Bloom's-level QG (AIED 2024) | Bloom tags per question |
| KT4EQG (2026) | Mastery model picks the concept; LLM only words the question |
| SMART (EMNLP 2025) | Simulated students + IRT for difficulty (later) |
| Rubric-conditioned grading (arXiv 2601.08843) | Grade open answers against cited facts, defer on disagreement (later) |
| ParikkhaChain (arXiv 2604.16827) | ZK proof of passing without revealing score (stretch) |

## Gaps SmartQuiz fills
1. Question provenance is never externally verifiable → Merkle root of facts on chain + per-question proofs.
2. Distractors are not checked against the source → distractor-falsity gate (Review 2).
3. Repeats are filtered after generation, not prevented → fact-coverage ledger.
4. "Generic" questions are not measured → Document Dependence Score (blind test).
5. No closed-book abstention → chat says "not in your material" with nearest sections.
6. Mastery and credentials are disconnected → concept badge from the mastery model with an evidence trail (Review 2).
