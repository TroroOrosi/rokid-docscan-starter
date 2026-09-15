"""Stable solver interface (a 'port' in ports-and-adapters terms).

A Solver turns a structured Question (problem text, choices, subject, and any
retrieved reference context) into a SolveResult: an answer plus solution steps,
rationale, cautions, and separated confidences.

Concrete adapters (local placeholder today; Gemini/OpenAI/Claude/on-device VLM
later) implement this interface and register themselves. The server depends
only on this contract, identified by version.SOLVER_API_VERSION.

The default offline adapter does NOT actually solve problems — it returns a
clearly-marked placeholder. Real answering requires registering a model-backed
adapter (kept out of this repo so it stays credential-free and offline).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field


@dataclass
class Question:
    """Structured input to a solver (one question / sub-question)."""

    question_no: str | None = None
    body_text: str | None = None
    choices: list[str] = field(default_factory=list)
    subject: str | None = None
    # Reference context retrieved from prior documents (RAG, Phase 3). Optional.
    context: str | None = None
    # Path to the captured page image. A vision-capable solver reads it so the
    # model sees figures / equations / tables directly (OCR text is imperfect).
    # Optional/last so existing positional construction keeps working.
    image_path: str | None = None
    # Every page of this question's 大問, in reading order. A 大問 that spans
    # pages keeps its passage on one page and its figures on another, so a
    # single starting-page image loses the diagram the question asks about.
    # `image_path` stays the first/primary page for adapters that take one.
    image_paths: list[str] = field(default_factory=list)
    # Written-answer mode keeps the complete answer and excludes tutorial text.
    # False preserves the existing tutor/overlay API for older clients.
    answer_only: bool = False
    # The listening recording itself, not only its transcript. A solver that
    # accepts audio hears the intonation, speaker turns and numbers that a
    # transcript flattens; adapters that cannot take audio ignore this and keep
    # using the transcript folded into `body_text`/`context`.
    audio_path: str | None = None
    # EVERY page of the paper this question came from, in reading order. The
    # browser route attaches the whole booklet once as a single PDF and then
    # only says which question to answer, so the OCR body does not have to be
    # retyped into every message (and cannot be truncated on the way).
    # Adapters that take one image ignore this and keep using image_path(s).
    document_image_paths: list[str] = field(default_factory=list)
    # 1-based page numbers this question occupies, used to point at it inside
    # that PDF ("P05-P07") instead of quoting its text.
    page_numbers: list[int] = field(default_factory=list)
    # Which conversation this question belongs to, when the adapter has the
    # concept (the browser route). The SERVER decides it -- one exam session is
    # one 科目's paper. It must not be derived from `subject`: that field is a
    # per-row heuristic, and a single 物理基礎 paper was measured producing
    # 現代文/物理/化学/数学/地学 across its rows, which would scatter one paper
    # over five chats and re-upload its pages into each.
    chat_key: str | None = None
    # Set only by the out-of-range retry: the first answer named a choice label
    # that does not exist, so the re-ask states the valid labels instead of
    # sending the identical prompt again.
    retry_hint: str | None = None
    # Stable capture-page identities with OCR, image path and question references.
    document_pages: list[dict] = field(default_factory=list)
    document_id: str = ""
    audio_transcript: str = ""
    question_id: str = ""


@dataclass
class SolveResult:
    """Solver output. Confidences are SEPARATED (read vs answer vs rationale)."""

    answer: str
    solution_steps: list[str] = field(default_factory=list)
    rationale: str = ""
    cautions: str = ""
    subject: str | None = None
    # 0..1 confidences, intentionally distinct so the HUD can show them apart.
    answer_confidence: float = 0.0
    rationale_confidence: float = 0.0
    # Legacy API v1 list. Keep each route/provider's pre-existing indexing
    # semantics; new consumers should use evidence_refs.
    evidence_pages: list[int] = field(default_factory=list)
    # Canonical cross-document identity. `page_number` is user-facing/1-based;
    # `document_id` prevents two different P01 pages being conflated.
    evidence_refs: list[dict] = field(default_factory=list)
    # Long internal reasoning kept off the HUD (shown only in detail/logs).
    raw_reasoning: str = ""
    # Free-form provider diagnostics; never relied on by the server.
    extras: dict = field(default_factory=dict)
    diagrams: list[dict] = field(default_factory=list)


class Solver(abc.ABC):
    """Provider-agnostic solver port."""

    #: Stable registry key, e.g. "local", "gemini", "openai", "claude".
    name: str = "base"
    #: Provider/model identity surfaced in responses & eval reports.
    provider_version: str = "0.0.0"
    #: True if this adapter runs fully on-device/offline (no network, no creds).
    offline: bool = True

    @abc.abstractmethod
    def solve(self, *, question: Question, max_answer_len: int = 64) -> SolveResult:
        """Return a SolveResult. Implementations must not raise on empty input;
        return a best-effort placeholder instead."""

    def ready(self) -> bool:
        """Whether this adapter can actually run, as opposed to being selected.

        Offline adapters always run. Cloud adapters override this: they fall
        back to the offline placeholder without saying so when no credential is
        present, so "selected" and "will run" are different questions and a
        pre-flight has to be able to ask the second one.
        """
        return True

    def info(self) -> dict:
        return {
            "name": self.name,
            "provider_version": self.provider_version,
            "offline": self.offline,
            "ready": self.ready(),
        }
