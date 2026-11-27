"""The quiz background job (SPEC section 4): select → generate → gates → duplicates → save → commit → ready.

Request budget per quiz: ONE generator call (attempt 0) for all targets plus spares, then at most ONE
batched regeneration (attempt 1) shared by every target that failed validation, Gate 1, 2 or 3.
Checker calls: one batch per gate per round, plus one gate-4 batch.
Short answers (SPEC 9.7) ride in the same generator calls; they run Gate 1 and Gate 3s, never Gate 2 or 4.
"""
import logging
import math
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.chain.quizhash import HASH_VERSION, new_salt, quiz_hash
from app.chain.service import ChainError, get_chain
from app.config import get_settings
from app.db import SessionLocal
from app.ingest.hasher import embed_texts
from app.llm.provider import same_family_checker
from app.models import Fact, GenerationLog, Question, Quiz
from app.quiz import gates
from app.quiz.dedup import DuplicateChecker, fingerprint
from app.quiz.generate import Candidate, generate
from app.quiz.select import Target, context_facts, select_review_targets, select_targets

log = logging.getLogger(__name__)

SPARE_SHARE = 0.3  # extra targets in the first call, so drops still leave N questions
MIN_SPARE = 2


@dataclass
class Progress:
    target: int
    accepted: int = 0
    rejected: int = 0
    stage: str = "selecting"  # selecting | generating | verifying | committing | done | failed


_progress: dict[uuid.UUID, Progress] = {}
_progress_lock = threading.Lock()


def get_progress(quiz_id: uuid.UUID) -> Progress | None:
    with _progress_lock:
        return _progress.get(quiz_id)


def _set_progress(quiz_id: uuid.UUID, **changes) -> None:
    with _progress_lock:
        p = _progress.setdefault(quiz_id, Progress(target=changes.get("target", 0)))
        for name, value in changes.items():
            setattr(p, name, value)


def _bump(quiz_id: uuid.UUID, name: str) -> None:
    with _progress_lock:
        p = _progress.get(quiz_id)
        if p:
            setattr(p, name, getattr(p, name) + 1)


def spare_count(n: int) -> int:
    return max(MIN_SPARE, math.ceil(n * SPARE_SHARE))


def mark_short(targets: list[Target], n: int, num_short: int) -> list[Target]:
    """num_short of the first n targets become short answers, spread evenly; spares stay MCQ."""
    first = min(n, len(targets))
    k = min(num_short, first)
    picks = {math.floor((j + 0.5) * first / k) for j in range(k)} if k else set()
    return [replace(t, qtype="short") if i in picks else t for i, t in enumerate(targets)]


class _Run:
    """One quiz's generation, with its logging."""

    def __init__(self, db: Session, quiz: Quiz, n: int, num_short: int = 0):
        self.db, self.quiz, self.n, self.num_short = db, quiz, n, num_short
        self.same_family = same_family_checker()
        facts = db.scalars(select(Fact).where(Fact.document_id == quiz.document_id)).all()
        self.fact_text = {f.idx: f.text for f in facts}

    def log(self, c: Candidate | None, gate: str, passed: bool, reason: str, checker: bool = False) -> None:
        self.db.add(
            GenerationLog(
                document_id=self.quiz.document_id,
                quiz_id=self.quiz.id,
                candidate_id=c.candidate_id if c else None,
                gate=gate,
                passed=passed,
                reason=reason,
                same_family_fallback=self.same_family and checker,
            )
        )

    def reject(self, c: Candidate, gate: str, reason: str) -> None:
        c.failed_gate, c.failed_reason = gate, reason
        _bump(self.quiz.id, "rejected")

    def verify(self, candidates: list[Candidate]) -> list[Candidate]:
        """Validation, then Gates 1, 2 and 3 in parallel (short answers: Gate 1 and Gate 3s). Returns the passed ones."""
        valid = []
        for c in candidates:
            if c.error:
                self.log(c, "generator_error", False, c.error)
                self.reject(c, "generator_error", c.error)
            else:
                valid.append(c)
        if not valid:
            return []
        mcq = [c for c in valid if c.qtype == "mcq"]
        short = [c for c in valid if c.qtype == "short"]
        calls = [(gates.gate1_grounding, valid)]  # Gate 1 batches MCQs and short answers together
        if mcq:
            calls += [(gates.gate2_distractors, mcq), (gates.gate3_solvability, mcq)]
        if short:
            calls.append((gates.gate3_short, short))
        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            for job in [pool.submit(fn, cs, self.fact_text) for fn, cs in calls]:
                job.result()
        passed = []
        for c in valid:
            g1, g3 = c.gate_results["gate1"], c.gate_results["gate3"]
            self.log(c, "gate1", gates.passed_gate1(c), f"{g1['verdict']}: {g1['reason']}", checker=True)
            if g1.get("bloom") and g1["bloom"] != c.bloom_level:  # logged only, never dropped (SPEC 9.3)
                self.log(c, "bloom_mismatch", True, f"asked {c.bloom_level}, checker says {g1['bloom']}")
            if c.qtype == "mcq":
                self.log(c, "gate2", gates.passed_gate2(c), c.gate_results["gate2"]["reason"], checker=True)
            self.log(c, "gate3", gates.passed_gate3(c), g3["reason"], checker=True)
            if not gates.passed_gate1(c):
                self.reject(c, "gate1", g1["reason"])
            elif not gates.passed_gate2(c):
                self.reject(c, "gate2", c.gate_results["gate2"]["reason"])
            elif not gates.passed_gate3(c):
                why = f"checker said {g3['verdict']}" if c.qtype == "short" else f"checker chose option {g3['choice']}"
                self.reject(c, "gate3", f"{why}: {g3['reason']}")
            else:
                passed.append(c)
        return passed

    def build(self) -> list[Question]:
        quiz_id = self.quiz.id
        review = self.quiz.mode == "review"
        want = self.n + spare_count(self.n)
        if review:  # SPEC 9.6: due cards only; spares are simply more due cards, if any
            targets = select_review_targets(
                self.db, self.quiz.user_id, self.quiz.document_id, want, datetime.now(timezone.utc)
            )
        else:
            targets = select_targets(self.db, self.quiz.user_id, self.quiz.document_id, want, str(quiz_id))
        if not targets:
            return []
        targets = mark_short(targets, self.n, self.num_short)
        contexts = {t.fact.idx: context_facts(self.db, self.quiz.document_id, t.fact) for t in targets}

        _set_progress(quiz_id, stage="generating")
        first = generate(targets, contexts, attempt=0)
        _set_progress(quiz_id, stage="verifying")
        passed = self.verify(first)

        failed = [c for c in first if c.failed_gate]
        # Also regenerate when a short item failed, or the MCQ spares would quietly fill its place.
        if failed and (len(passed) < self.n or any(c.qtype == "short" for c in failed)):
            # The one batched regeneration, with attempt=1 so the cache returns a new response.
            problems = {c.target_idx: f"{c.failed_gate}: {c.failed_reason}" for c in failed}
            _set_progress(quiz_id, stage="generating")
            retry = generate([c.target for c in failed], contexts, attempt=1, problems=problems)
            _set_progress(quiz_id, stage="verifying")
            passed += self.verify(retry)

        # Back in target order, so section spread and tier priority decide who is kept.
        # Short items sit inside the first n targets, so they are kept whenever they passed.
        order = {t.fact.idx: i for i, t in enumerate(targets)}
        passed.sort(key=lambda c: order[c.target_idx])

        mcq_passed = [c for c in passed if c.qtype == "mcq"]
        if mcq_passed:
            gates.gate4_dependence(mcq_passed)  # blind guessing needs options: MCQs only
        vectors = embed_texts([c.stem for c in passed]) if passed else []
        dup = DuplicateChecker(
            self.db, self.quiz.user_id, self.quiz.document_id, exclude_quiz=quiz_id, within_quiz_only=review
        )
        questions: list[Question] = []
        for c, vector in zip(passed, vectors):
            if c.qtype == "mcq":
                g4 = c.gate_results["gate4"]
                self.log(c, "gate4", True, f"blind choice {g4['choice']}, confidence {g4['confidence']}: {g4['reason']}", checker=True)
            if len(questions) >= self.n:
                continue  # a spare that is not needed: neither accepted nor rejected
            fp = fingerprint(c.fact_idxs, c.bloom_level)
            dup_gate, reason = dup.check(fp, vector, c.target_idx, c.bloom_level)
            if dup_gate:
                self.log(c, dup_gate, False, reason)
                self.reject(c, dup_gate, reason)
                continue
            dup.add(fp, vector, c.target_idx, c.bloom_level)
            score = gates.dependence_score(c) if c.qtype == "mcq" else None
            questions.append(
                Question(
                    quiz_id=quiz_id,
                    position=len(questions) + 1,
                    stem=c.stem,
                    options=c.options,
                    answer_index=c.answer_index,
                    fact_idxs=c.fact_idxs,
                    target_fact_idx=c.target_idx,
                    bloom_level=c.bloom_level,
                    fingerprint=fp,
                    gate_results=c.gate_results,
                    distractors=c.distractors,
                    dependence_score=score,
                    flagged_general=score is not None and score < gates.FLAG_GENERAL_BELOW,
                    qtype=c.qtype,
                    model_answer=c.model_answer,
                    stem_embedding=vector.tolist(),
                )
            )
            _bump(quiz_id, "accepted")
        return questions


def commit_quiz_onchain(db: Session, quiz: Quiz, questions: list[Question]) -> None:
    """P06: salt + quiz_hash (SPEC section 8), then commitQuiz on chain. Raises ChainError only when the
    chain is required (CHAIN_OPTIONAL=false); otherwise commit_tx stays null and chain_status is offline."""
    quiz.salt = new_salt()
    quiz.hash_version = HASH_VERSION
    quiz.quiz_hash = quiz_hash(questions, quiz.salt, quiz.hash_version)
    try:
        quiz.commit_tx = get_chain().commit_quiz(quiz.id, quiz.document_id, quiz.quiz_hash)
    except ChainError as exc:
        quiz.commit_tx = None
        if not get_settings().chain_optional:
            log.error("quiz %s: chain commit failed and the chain is required: %s", quiz.id, exc)
            raise
        log.warning("quiz %s: chain offline, commit skipped (%s)", quiz.id, exc)


def run_quiz_job(
    quiz_id: uuid.UUID, n: int, session_factory: sessionmaker = SessionLocal, num_short: int = 0
) -> None:
    """The background job. quiz.status moves generating → ready or failed. Never raises."""
    _set_progress(quiz_id, target=n, stage="selecting")
    with session_factory() as db:
        quiz = db.get(Quiz, quiz_id)
        if quiz is None:
            return
        try:
            run = _Run(db, quiz, n, num_short)
            questions = run.build()
            db.add_all(questions)
            db.commit()  # keeps the gate log even if the commit below fails
            if not questions:
                quiz.status = "failed"
                db.commit()
                _set_progress(quiz_id, stage="failed")
                return
            _set_progress(quiz_id, stage="committing")
            commit_quiz_onchain(db, quiz, questions)
            quiz.status = "ready"
            db.commit()
            _set_progress(quiz_id, stage="done")
        except Exception:
            db.rollback()
            log.exception("quiz generation failed for %s", quiz_id)
            quiz = db.get(Quiz, quiz_id)
            quiz.status = "failed"
            db.commit()
            _set_progress(quiz_id, stage="failed")


def fail_interrupted_quizzes(session_factory: sessionmaker = SessionLocal) -> int:
    """Background jobs die with the server; without this the web page would poll them forever."""
    with session_factory() as db:
        count = db.execute(update(Quiz).where(Quiz.status == "generating").values(status="failed")).rowcount
        db.commit()
    return count
