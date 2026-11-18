"""Two things the server says or does by itself behind a booklet.

A booklet two reads were asked for and one answered alone says so once behind its answers: an unmarked answer otherwise
means that two reads agree, and nothing told the two apart (found 2026-11-17).

The clips' sweep (app/retention.py) runs at a start and after a booklet is finalized: nothing else removes a clip, and
nobody is at the phone.
"""

import threading

from tests.test_chatgpt_work import BrowserReply
from tests.test_route_order import booklet
from tests.test_work_bridge import client as _client_fixture, picture

client = _client_fixture


class Cli:
    name = "codex-cli"

    def __init__(self, once: bool, reduced: bool = False):
        self.once, self.reduced = once, reduced

    def answer_all(self, *, question):
        from app.solvers.base import SolveResult

        result = SolveResult(answer="4")
        if self.once:
            result.extras["read_once"] = True  # what codex_cli leaves when one read of two answered
        if self.reduced:
            result.extras["pages_reduced"] = True  # ... and when no read saw every page at its own size
        return [({"group": "第1問", "label": "問1", "pages": [1], "answer_no": [1]}, result)]


def items(client, session):
    return client.get(f"/v1/exam-sessions/{session}/answer-bundle").json()["items"]


def test_a_booklet_one_read_answered_alone_says_once_that_nothing_was_compared(client, monkeypatch):
    _, session = booklet(client, monkeypatch, Cli(once=True), BrowserReply(), None)
    answers = items(client, session)
    assert [(item["status"], item["answer"]) for item in answers[:-1]] == [("ready", "4")], "the answer itself stays as it is"
    notice = answers[-1]
    assert (notice["question_id"], notice["status"], notice["question_label"]) == ("read-once", "needs_review", "照合なし")
    assert notice["answer"].strip() and "照合" in notice["issue"], "the glasses refuse a blank answer to review"


def test_a_booklet_both_reads_answered_carries_no_such_item(client, monkeypatch):
    _, session = booklet(client, monkeypatch, Cli(once=False), BrowserReply(), None)
    assert [(item["status"], item["answer"]) for item in items(client, session)] == [("ready", "4")]


def test_a_booklet_whose_pages_had_to_be_reduced_says_so_once_behind_its_answers(client, monkeypatch):
    """A booklet too long for one request whose major problems could not be told is read with every page reduced
    (app/solvers/codex_cli.py). Until 2026-11-18 that happened from about twenty gathered pages on with nothing
    said. On a page with a known text the model read characters of nine pixels as it read them at twenty-five and
    worse at six (M-44 (20)): what is small on the paper is what to check."""
    _, session = booklet(client, monkeypatch, Cli(once=False, reduced=True), BrowserReply(), None)
    answers = items(client, session)
    assert [(item["status"], item["answer"]) for item in answers[:-1]] == [("ready", "4")], "the answer itself stays as it is"
    notice = answers[-1]
    assert (notice["question_id"], notice["status"], notice["question_label"]) == ("pages-reduced", "needs_review", "縮小")
    assert notice["answer"].strip() and "縮小" in notice["issue"] and "小さい字" in notice["issue"]


def test_reduced_pages_and_one_read_are_each_said_and_the_read_stays_last(client, monkeypatch):
    """The item about the reads is the one a later revision replaces: it stays where the glasses know it."""
    _, session = booklet(client, monkeypatch, Cli(once=True, reduced=True), BrowserReply(), None)
    assert [item["question_id"] for item in items(client, session)[-2:]] == ["pages-reduced", "read-once"]


def test_the_clips_sweep_runs_after_a_booklet_is_finalized(client, monkeypatch):
    from app import main

    swept = threading.Event()
    monkeypatch.setattr(main.retention, "sweep", swept.set)
    document = client.post("/v1/documents", json={"title": "sweep"}).json()["document_id"]
    assert client.post(f"/v1/documents/{document}/pages", data={"page_index": 0},
                       files={"image": ("page.png", picture(), "image/png")}).status_code == 201
    assert not swept.is_set(), "not in the path of a page"
    assert client.post(f"/v1/documents/{document}/finalize").status_code == 200
    assert swept.wait(5)


def test_the_clips_sweep_runs_when_the_server_starts(client, monkeypatch):
    from app import main

    swept = threading.Event()
    monkeypatch.setattr(main.retention, "sweep", swept.set)
    with client:
        assert swept.wait(5)
