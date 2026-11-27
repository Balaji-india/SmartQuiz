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
