// Copied from docs/SPEC.md section 2. Keep in step with the API.

export type ChainStatus = "pending" | "confirmed" | "offline";

export type User = { id: string; email: string; name: string; role: "learner" | "educator"; wallet_address: string | null };
export type AuthOut = { token: string; user: User };

export type DocumentOut = {
  id: string;
  filename: string;
  status: "ingesting" | "ready" | "failed";
  sections_count: number;
  fact_count: number;
  facts_dropped: number;
  facts_unfaithful: number;
  fact_root: string | null;
  register_tx: string | null;
  explorer_url: string | null;
  chain_status: ChainStatus;
  created_at: string;
};

export type FactOut = { idx: number; text: string; page: number; concept: string };

export type SectionOut = {
  id: number;
  heading: string;
  level: number;
  page_start: number;
  page_end: number;
  facts: FactOut[];
  children: SectionOut[];
};

export type TextbookOut = { document: DocumentOut; sections: SectionOut[] };

export type QuestionType = "mcq" | "short";

export type QuestionOut = {
  id: string;
  position: number;
  qtype: QuestionType; // short: options [] and the learner types an answer (SPEC 9.7)
  stem: string;
  options: string[];
  bloom_level: "remember" | "understand" | "apply" | "analyze";
  flagged_general: boolean;
  fact_idxs: number[] | null; // only after the attempt is submitted
};

export type QuizOut = {
  id: string;
  document_id: string;
  status: "generating" | "ready" | "failed";
  mode: QuizMode;
  time_limit_sec: number;
  quiz_hash: string | null;
  commit_tx: string | null;
  explorer_url: string | null;
  chain_status: ChainStatus;
  started_at: string | null;
  submitted: boolean;
  attempt_id: string | null;
  questions: QuestionOut[];
  generation: { candidates: number; accepted: number; rejected: number } | null;
};

export type QuizProgressOut = {
  accepted: number;
  rejected: number;
  target: number;
  stage: "selecting" | "generating" | "verifying" | "committing" | "done" | "failed";
};

export type SourceOut = { idx: number; text: string; page: number; section: string };
export type MisconceptionOut = { option: number; misconception: string; sources: SourceOut[] };

export type GradeOut = {
  verdict: "correct" | "partial" | "incorrect" | null; // null while it waits for an educator
  confidence: number | null;
  reason: string;
  deferred: boolean;
  by: "checker" | "educator" | null;
  fact_idxs: number[];
};

export type AttemptResult = {
  attempt_id: string;
  score: number; // final grades only
  total: number;
  grading_status: "final" | "pending_review";
  pending_review: number;
  results: {
    question_id: string;
    qtype: QuestionType;
    chosen: number | null; // null for a short answer
    correct_index: number | null; // null for a short answer
    correct: boolean;
    sources: SourceOut[];
    misconceptions: MisconceptionOut[]; // after submit only; [] for Review 1 questions and short answers
    answer_text: string | null; // short answers only
    model_answer: string | null;
    grade: GradeOut | null;
  }[];
  weak_concepts: { concept: string; wrong: number; facts: number[] }[];
};

export type ChatOut = {
  abstained: boolean;
  answer: string;
  citations: { idx: number; text: string; page: number }[];
  nearest_sections: { id: number; heading: string }[];
  best_similarity: number;
};

export type MetricsOut = {
  document_id: string;
  candidates: number;
  accepted: number;
  rejected_by_gate: Record<string, number>;
  top_reasons: { gate: string; reason: string; count: number }[];
  duplicates_blocked: { fingerprint: number; cosine: number };
  flagged_general: number;
  avg_dependence: number | null;
  repeat_rate_between_quizzes: number;
  same_family_checker_used: boolean;
  same_family_gate_calls: number;
  bloom_levels: Record<"remember" | "understand" | "apply" | "analyze", number>;
  bloom_mismatches: number;
  short_questions: number;
  deferred_grades: number;
};

export type MasteryStatus = "weak" | "learning" | "untested" | "mastered";

export type ConceptMastery = {
  concept: string;
  section_id: number;
  section: string;
  p_mastery: number;
  answered: number;
  status: MasteryStatus;
  fact_idxs: number[];
  badge_id: string | null;
};

export type MasteryOut = {
  document_id: string;
  summary: Record<MasteryStatus, number>;
  concepts: ConceptMastery[]; // weak (lowest first), learning, untested, mastered
};

export type RevisionNote = {
  concept: string;
  sentences: { text: string; fact_idxs: number[] }[]; // every sentence passed Gate 1
  dropped: number;
  created_at: string;
};

export type RevisionOut = { notes: RevisionNote[] }; // latest note per concept, weakest first

// SPEC 9.6: FSRS review mode
export type QuizMode = "practice" | "review";
export type ReviewSummaryOut = { due_now: number; next_due: string | null; cards: number };
export type NothingDueOut = { detail: "Nothing due for review"; next_due: string | null }; // POST /quizzes 409 in review mode

export type VerifiedFact = {
  idx: number;
  text: string;
  page: number;
  text_hash: string;
  leaf: string;
  proof: string[];
  verified_on_chain: boolean | null;
};

export type VerifyQuestionOut = {
  question_id: string;
  stem: string;
  document_id: string;
  doc_id_onchain: string;
  onchain_root: string | null;
  db_root: string;
  chain_status: ChainStatus;
  facts: VerifiedFact[];
  registry_address: string | null;
  explorer_url: string | null;
  cosign: { educator_address: string; at: number; cosign_tx: string | null } | null; // at = unix seconds (chain)
  document_revoked: boolean | null; // null when the chain could not be read
};

export type VerifyFactOut = { leaf: string; verified_on_chain: boolean | null; root: string; chain_status: ChainStatus };

export type VerifyQuizOut = {
  quiz_id: string;
  recomputed_hash: string;
  onchain_hash: string | null;
  match: boolean | null;
  chain_status: ChainStatus;
  commit_tx: string | null;
  explorer_url: string | null;
};

// SPEC 9.9: credentials (badges, educator actions, result and badge verification)
export type BadgeOut = {
  id: string;
  document_id: string;
  concept: string;
  token_id: number | null;
  holder_address: string;
  custodial: boolean;
  concept_hash: string;
  evidence_hash: string;
  mint_tx: string | null;
  explorer_url: string | null;
  revoked: boolean;
  chain_status: ChainStatus;
  created_at: string;
};
export type EducatorBadgeOut = BadgeOut & { learner_name: string };

export type AnchorOut = { batch_id: string; root: string; count: number; anchor_tx: string | null; explorer_url: string | null; chain_status: ChainStatus };
export type BatchOut = { batch_id: string; root: string; count: number; anchor_tx: string | null; explorer_url: string | null; created_at: string };
export type EducatorResultsOut = { unanchored: number; pending_grading: number; batches: BatchOut[] };

export type Verdict = "correct" | "partial" | "incorrect";
export type GradingItemOut = {
  grade_id: string;
  attempt_id: string;
  question_id: string;
  stem: string;
  model_answer: string | null;
  answer_text: string | null;
  checker: { verdict: Verdict | null; confidence: number | null; reason: string | null };
  facts: { idx: number; text: string; page: number }[];
};
export type GradeDoneOut = { grade_id: string; attempt_id: string; grading_status: "final" | "pending_review" };

export type EducatorDocumentOut = DocumentOut & {
  cosign: { educator_address: string; at: string; cosign_tx: string | null } | null;
  revoked: boolean;
};
export type CoSignResultOut = { educator_address: string; signature: string; cosign_tx: string | null; explorer_url: string | null; chain_status: ChainStatus };

export type VerifyAttemptOut = {
  attempt_id: string;
  quiz_id: string;
  score: number;
  total: number;
  attempt_hash: string;
  recomputed_hash: string;
  leaf: string;
  proof: string[];
  batch_id: string;
  onchain_root: string | null;
  match: boolean | null;
  verified_on_chain: boolean | null;
  anchor_tx: string | null;
  explorer_url: string | null;
  chain_status: ChainStatus;
};

export type VerifyBadgeOut = {
  token_id: number;
  holder_address: string;
  document_id: string;
  concept: string;
  concept_hash: string;
  evidence_hash: string;
  evidence_attempts: string[];
  onchain: { concept_hash: string; evidence_hash: string; issued_at: number; revoked: boolean } | null;
  match: boolean | null;
  revoked: boolean;
  chain_status: ChainStatus;
  explorer_url: string | null;
};
