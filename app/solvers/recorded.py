"""A stand-in for the model, for exercising the whole route without sending anything to it.

``ROKID_SOLVER=recorded`` answers a whole booklet from a reply recorded in a file. It exists so that the route
glasses -> phone server -> answer bundle -> glasses can be driven end to end on real devices: the operator's ChatGPT
usage is not to be spent on route checks, and until 2026-11-13 the route had only ever been run in parts with fakes.

It is armed only when both hold, and unready otherwise (``ROKID_REAL_MODE=1`` then refuses it at finalize):

- ``ROKID_CHATGPT_SEND_ENABLED`` is not ``1`` (the gate every browser send also checks);
- ``ROKID_RECORDED_REPLY`` names an existing file holding ``{"questions": [...]}`` in the booklet reply shape.

It never opens a browser, is not a booklet fallback, and does not answer single questions.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from app.solvers.base import Question, Solver, SolveResult
from app.solvers.chatgpt_web import _booklet_replies, chatgpt_send_enabled


class RecordedSolver(Solver):
    name = "recorded"
    provider_version = "recorded-reply-v1"
    offline = True
    placeholder = False
    accepts_images = True

    @staticmethod
    def _reply() -> Path | None:
        named = os.environ.get("ROKID_RECORDED_REPLY", "")
        return Path(named) if named and Path(named).is_file() else None

    def ready(self) -> bool:
        return not chatgpt_send_enabled() and self._reply() is not None

    def answer_all(self, *, question: Question) -> list[SolveResult]:
        reply = self._reply()
        if chatgpt_send_enabled() or reply is None:
            raise RuntimeError("the recorded solver is not armed: sending must be off and ROKID_RECORDED_REPLY must name a file")
        time.sleep(float(os.environ.get("ROKID_RECORDED_DELAY_S") or 0))  # stands for the minutes the model takes
        recorded = json.loads(reply.read_text(encoding="utf-8"))
        return _booklet_replies(recorded, subject=question.subject, extras={"source": self.name, "provider": self.name})

    def solve(self, *, question: Question, max_answer_len: int = 64) -> SolveResult:
        raise ValueError("the recorded solver answers a whole booklet only")
