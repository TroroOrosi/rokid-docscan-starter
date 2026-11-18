"""The stand-in CLI of the rehearsals (scripts/standin_codex.py) speaks what the Codex route asks of the real one.

A rehearsal on the phone runs the whole route against it before a change goes live. If the route's requests change
and the stand-in is not brought along, this fails here, on the PC, and not as a rehearsal that proves nothing.
"""
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

from app import config
from app.solvers import codex_cli
from app.solvers.base import Question
from tests.test_codex_ahead import _settled

STANDIN = Path(__file__).resolve().parents[1] / "scripts" / "standin_codex.py"


@pytest.fixture
def standin(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_cli, "_command", lambda: [sys.executable, str(STANDIN)])
    monkeypatch.setattr(codex_cli, "_needs_proxy", lambda: False)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    for name in ("ROKID_CODEX_READS", "ROKID_CODEX_PARTS", "ROKID_CODEX_MODEL", "ROKID_CODEX_AHEAD", "ROKID_CODEX_LOCATE",
                 "STANDIN_CODEX_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    yield
    _settled()
    with codex_cli._ahead_lock:
        codex_cli._ahead.clear()
        codex_cli._ahead_outlines.clear()


def _booklet(tmp_path, pages) -> Question:
    rows = []
    for number in range(1, pages + 1):
        path = tmp_path / f"page-{number}.png"
        Image.new("L", (600, 800), 180 + number).save(path)  # grey, as a gathered page is stored
        rows.append({"page_number": number, "image_path": str(path),
                     "capture_provenance": {"source_kind": "clip_frame"}})
    return Question(question_no=None, chat_key="session:rehearsal", document_pages=rows, document_id="1")


def _printed(capsys, event):
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if f'"{event}"' in line]


@pytest.mark.parametrize("ahead", [False, True])
def test_a_booklet_goes_through_the_whole_route_against_the_stand_in(standin, tmp_path, monkeypatch, capsys, ahead):
    monkeypatch.setenv("ROKID_CODEX_PARTS", "3")
    question = _booklet(tmp_path, pages=6)
    solver = codex_cli.CodexCliSolver()
    assert solver.ready(), "signed in, as far as the route can tell"
    if ahead:
        solver.prepare(question.document_pages[:4])
        solver.prepare(question.document_pages, booklet=True)
        _settled()
    replies = solver.answer_all(question=question)

    assert len(replies) == 6 and not [result for _, result in replies if isinstance(result, Exception)]
    assert all(result.answer == "①" and not result.extras.get("review_note") for _, result in replies), (
        "two reads that agree: nothing is marked")
    out = capsys.readouterr().out
    [plan] = [json.loads(line) for line in out.splitlines() if '"codex_plan"' in line]
    assert (plan["pages"], plan["parts"]) == (6, 2), "the first read in parts by the stand-in's two major problems"
    [prepared] = [json.loads(line) for line in out.splitlines() if '"codex_prepared"' in line]
    assert prepared["ahead"] == (6 if ahead else 0)
    assert '"codex_ahead_failed"' not in out and '"codex_outline_failed"' not in out


def test_the_stand_in_passes_the_routes_own_check(standin):
    assert codex_cli.CodexCliSolver().check() is None, "the squares were counted; no allowance to report"
