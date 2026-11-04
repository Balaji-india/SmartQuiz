// Copied from docs/SPEC.md section 2. Keep in step with the API.

export type ChainStatus = "pending" | "confirmed" | "offline";

export type User = { id: string; email: string; name: string };
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

export type QuestionOut = {
  id: string;
  position: number;
  stem: string;
  options: string[];
  bloom_level: "remember" | "understand";
  flagged_general: boolean;
  fact_idxs: number[] | null; // only after the attempt is submitted
};

export type QuizOut = {
  id: string;
  document_id: string;
  status: "generating" | "ready" | "failed";
  time_limit_sec: number;
  quiz_hash: string | null;
  commit_tx: string | null;
  explorer_url: string | null;
  chain_status: ChainStatus;
  started_at: string | null;
  submitted: boolean;
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

export type AttemptResult = {
  attempt_id: string;
  score: number;
  total: number;
  results: { question_id: string; chosen: number | null; correct_index: number; correct: boolean; sources: SourceOut[] }[];
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
};

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
