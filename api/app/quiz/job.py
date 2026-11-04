"""The quiz background job (SPEC section 4): select → generate → gates → duplicates → save → commit → ready.

Request budget per quiz: ONE generator call (attempt 0) for all targets plus spares, then at most ONE
batched regeneration (attempt 1) shared by every target that failed validation, Gate 1 or Gate 3.
Checker calls: one batch per gate per round, plus one gate-4 batch.
"""
import logging
import math
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.chain.quizhash import new_salt, quiz_hash
from app.chain.service import ChainError, get_chain
from app.config import get_settings
from app.db import SessionLocal
from app.ingest.hasher import embed_texts
from app.llm.provider import same_family_checker
from app.models import Fact, GenerationLog, Question, Quiz
from app.quiz import gates
from app.quiz.dedup import DuplicateChecker, fingerprint
from app.quiz.generate import Candidate, generate
from app.quiz.select import Target, context_facts, select_targets

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


class _Run:
    """One quiz's generation, with its logging."""

    def __init__(self, db: Session, quiz: Quiz, n: int):
        self.db, self.quiz, self.n = db, quiz, n
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
        """Validation, then Gates 1 and 3 in parallel. Returns the candidates that passed both."""
        valid = []
        for c in candidates:
            if c.error:
                self.log(c, "generator_error", False, c.error)
                self.reject(c, "generator_error", c.error)
            else:
                valid.append(c)
        if not valid:
            return []
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [
                pool.submit(gates.gate1_grounding, valid, self.fact_text),
                pool.submit(gates.gate3_solvability, valid, self.fact_text),
            ]
            for job in jobs:
                job.result()
        passed = []
        for c in valid:
            g1, g3 = c.gate_results["gate1"], c.gate_results["gate3"]
            self.log(c, "gate1", gates.passed_gate1(c), f"{g1['verdict']}: {g1['reason']}", checker=True)
            self.log(c, "gate3", gates.passed_gate3(c), g3["reason"], checker=True)
            if not gates.passed_gate1(c):
                self.reject(c, "gate1", g1["reason"])
            elif not gates.passed_gate3(c):
                self.reject(c, "gate3", f"checker chose option {g3['choice']}: {g3['reason']}")
            else:
                passed.append(c)
        return passed

    def build(self) -> list[Question]:
        quiz_id = self.quiz.id
        targets = select_targets(self.db, self.quiz.user_id, self.quiz.document_id, self.n + spare_count(self.n), str(quiz_id))
        if not targets:
            return []
        contexts = {t.fact.idx: context_facts(self.db, self.quiz.document_id, t.fact) for t in targets}

        _set_progress(quiz_id, stage="generating")
        first = generate(targets, contexts, attempt=0)
        _set_progress(quiz_id, stage="verifying")
        passed = self.verify(first)

        failed = [c for c in first if c.failed_gate]
        if failed and len(passed) < self.n:
            # The one batched regeneration, with attempt=1 so the cache returns a new response.
            problems = {c.target_idx: f"{c.failed_gate}: {c.failed_reason}" for c in failed}
            _set_progress(quiz_id, stage="generating")
            retry = generate([c.target for c in failed], contexts, attempt=1, problems=problems)
            _set_progress(quiz_id, stage="verifying")
            passed += self.verify(retry)

        # Back in target order, so section spread and tier priority decide who is kept.
        order = {t.fact.idx: i for i, t in enumerate(targets)}
        passed.sort(key=lambda c: order[c.target_idx])

        if passed:
            gates.gate4_dependence(passed)
        vectors = embed_texts([c.stem for c in passed]) if passed else []
        dup = DuplicateChecker(self.db, self.quiz.user_id, self.quiz.document_id, exclude_quiz=quiz_id)
        questions: list[Question] = []
        for c, vector in zip(passed, vectors):
            g4 = c.gate_results["gate4"]
            self.log(c, "gate4", True, f"blind choice {g4['choice']}, confidence {g4['confidence']}: {g4['reason']}", checker=True)
            if len(questions) >= self.n:
                continue  # a spare that is not needed: neither accepted nor rejected
            fp = fingerprint(c.fact_idxs, c.bloom_level)
            dup_gate, reason = dup.check(fp, vector)
            if dup_gate:
                self.log(c, dup_gate, False, reason)
                self.reject(c, dup_gate, reason)
                continue
            dup.add(fp, vector)
            score = gates.dependence_score(c)
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
                    dependence_score=score,
                    flagged_general=score < gates.FLAG_GENERAL_BELOW,
                    stem_embedding=vector.tolist(),
                )
            )
            _bump(quiz_id, "accepted")
        return questions


def commit_quiz_onchain(db: Session, quiz: Quiz, questions: list[Question]) -> None:
    """P06: salt + quiz_hash (SPEC section 8), then commitQuiz on chain. Raises ChainError only when the
    chain is required (CHAIN_OPTIONAL=false); otherwise commit_tx stays null and chain_status is offline."""
    quiz.salt = new_salt()
    quiz.quiz_hash = quiz_hash(questions, quiz.salt)
    try:
        quiz.commit_tx = get_chain().commit_quiz(quiz.id, quiz.document_id, quiz.quiz_hash)
    except ChainError as exc:
        quiz.commit_tx = None
        if not get_settings().chain_optional:
            log.error("quiz %s: chain commit failed and the chain is required: %s", quiz.id, exc)
            raise
        log.warning("quiz %s: chain offline, commit skipped (%s)", quiz.id, exc)


def run_quiz_job(quiz_id: uuid.UUID, n: int, session_factory: sessionmaker = SessionLocal) -> None:
    """The background job. quiz.status moves generating → ready or failed. Never raises."""
    _set_progress(quiz_id, target=n, stage="selecting")
    with session_factory() as db:
        quiz = db.get(Quiz, quiz_id)
        if quiz is None:
            return
        try:
            run = _Run(db, quiz, n)
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
