"""A booklet ends: with its answers, or with a sentence the glasses can show. It never waits without an end.

The glasses' display sleeps until no item is pending. Each test here is one way a booklet was left pending for
good, or was answered late or twice, found by reading the solving code end to end on 2026-11-17.
"""

import json

import pytest

from tests.test_answer_bundle_api import (
    _background_finalize_and_wait, _replies, _session_with, client as _client_fixture,
)
from tests.test_booklet_route_fallback import _raise
from tests.test_chatgpt_work import BrowserReply
from tests.test_route_order import Chat, Cli, answered_by, answers, booklet, work_jobs
from tests.test_work_bridge import client as _work_client_fixture, picture, wait_for

client = _client_fixture
work_client = _work_client_fixture  # an API key, a bound wearer and Work's store, as tests/test_route_order.py uses


def test_a_batch_that_dies_outside_every_handler_ends_the_booklet_with_a_sentence(client, monkeypatch):
    """A page file that does not match its record raised before the first try: the thread died, no row was
    written, the glasses were told "the answers are being made" for good and every poll started the thread again.
    The first crashes still end that way (the restart is what reads a received reply back after a locked commit:
    tests/test_answer_bundle_api.py, "answers lost before their commit"); the batch that crashes for the
    RESUME_LIMIT-th time leaves the failure instead."""
    from app import main

    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")
    started = []

    def unreadable(conn, doc_id, session_id, **_):
        started.append(session_id)
        raise ValueError("saved native capture does not match its canonical page")

    monkeypatch.setattr(main, "_document_source_pages", unreadable)
    bundle = _background_finalize_and_wait(client, session_id, lambda items: items[0]["status"] == "failed")
    assert bundle["items"][0]["issue"] == "解析に失敗しました。資料は保持しています"
    assert bundle["available_stage"] == "complete"  # nothing pending: the watcher wakes the glasses
    # A later poll starts nothing: the failure is final.
    assert client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").status_code == 200
    assert started == [session_id] * main.RESUME_LIMIT and session_id not in main._background_solves


def test_with_the_send_gate_off_the_bundle_says_so_and_not_that_no_problem_was_found(client, monkeypatch):
    """ROKID_CHATGPT_SEND_ENABLED=0 keeps the booklet for later permission and writes nothing; the bundle then
    answered "no problems were detected in this document" for as long as the gate stayed off."""
    from app import main

    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-web")
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "0")
    assert client.post(f"/v1/exam-sessions/{session_id}/finalize-reading?solve=background").status_code == 200
    wait_for(lambda: session_id not in main._background_solves)
    response = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle")
    assert (response.status_code, response.json()["detail"]) == (409, "sending is not authorized")


# --- What a start of the server resumes --------------------------------------------------------------------------

def _left_by_a_restart(client, title):
    """A reviewing session with no deck and no batch running: what a restart in the middle of an analysis leaves."""
    from app import main

    doc = client.post("/v1/documents", json={"title": title}).json()["document_id"]
    assert client.post(f"/v1/documents/{doc}/pages", data={"page_index": 0},
                       files={"image": ("page.png", picture(), "image/png")}).status_code == 201
    assert client.post(f"/v1/documents/{doc}/finalize").status_code == 200
    session = client.post("/v1/exam-sessions", json={"document_id": doc, "mode": "study",
                                                     "exam_type": "written"}).json()["session_id"]
    with main.db.connect() as conn:
        conn.execute("UPDATE exam_sessions SET status = 'reviewing' WHERE id = ?", (session,))
    return session


def _glasses_on(client, session, phase="analyzing"):
    assert client.post("/v1/glasses/state", json={"device_id": "fixture-glasses", "session_id": session,
                       "generation": 7, "sequence": 1, "phase": phase}).json()["accepted"]


def _asked(monkeypatch):
    from app import main

    asked = []

    def answer_all(question):
        asked.append(question.chat_key)
        return _replies(("第1問", "問1", [1], "4"))

    monkeypatch.setenv("ROKID_SOLVER", "test-provider")
    monkeypatch.setattr(main, "_answer_all", answer_all)
    return asked


def test_a_start_resumes_the_session_the_glasses_are_on_and_leaves_the_others_until_asked(work_client, monkeypatch):
    """Every unanswered session of the last three hours was resumed at once: booklets nobody waits for ran again,
    the CLI paid for them again, and they held the one browser while the wearer's own booklet waited."""
    from app import main

    asked = _asked(monkeypatch)
    abandoned, current = _left_by_a_restart(work_client, "abandoned"), _left_by_a_restart(work_client, "current")
    _glasses_on(work_client, current)

    main._resume_all_answers()

    wait_for(lambda: asked and not main._background_solves)
    assert asked == [f"session:{current}"]
    # The other booklet is not lost: whoever asks for its answers starts it (the bundle request, the watcher's poll).
    assert work_client.get(f"/v1/exam-sessions/{abandoned}/answer-bundle").status_code == 409
    wait_for(lambda: len(asked) == 2 and not main._background_solves)
    assert asked == [f"session:{current}", f"session:{abandoned}"]


def test_a_start_reads_back_a_booklet_whose_message_left_whatever_the_glasses_are_on(work_client, monkeypatch):
    """A message that left before the restart is read back from its chat, as before: that costs nothing, and its
    reply is the wearer's."""
    from app import main

    asked = _asked(monkeypatch)
    sent, unsent = _left_by_a_restart(work_client, "sent"), _left_by_a_restart(work_client, "unsent")
    _journal_a_send(f"session:{sent}:{'c' * 64}")
    work_client.post("/v1/glasses/state", json={"device_id": "fixture-glasses", "session_id": None, "generation": 7,
                                                "sequence": 1, "phase": "chooser"})

    main._resume_all_answers()

    wait_for(lambda: asked and not main._background_solves)
    assert asked == [f"session:{sent}"] and unsent not in main._background_solves


def test_a_start_does_not_run_a_booklet_whose_wearer_has_finished(work_client, monkeypatch):
    from app import main

    asked = _asked(monkeypatch)
    ended = _left_by_a_restart(work_client, "ended")
    _glasses_on(work_client, ended, phase="closed")

    main._resume_all_answers()

    assert asked == [] and not main._background_solves


# --- The check before use ----------------------------------------------------------------------------------------

def test_a_shallow_check_does_not_put_off_the_daily_deep_check(tmp_path, monkeypatch):
    """Every check rewrote the one time the daily check was decided by. The glasses' chooser asks for a shallow
    check whenever the kept one is over thirty minutes old, so with the glasses used daily the deep check, the only
    one that sends through Chat, was never due again and "ok" stood with Chat only looked at."""
    from fastapi.testclient import TestClient

    from tests.test_route_check import HEADERS, _OneRound, _deep, _routes as _checks, _server

    main = _server(tmp_path, monkeypatch)
    _checks(monkeypatch, {"codex-cli": True})
    sent = _deep(monkeypatch)
    monkeypatch.setenv("ROKID_ROUTE_CHECK_DEEP", "1")
    api = TestClient(main.app)
    deep = api.post("/v1/route-check?deep=1", headers=HEADERS).json()
    assert deep["deep_checked_at"] == deep["checked_at"] and sent == ["chatgpt-web"]
    # Two days pass; then the chooser asks for its shallow check a moment before the daily thread looks.
    kept = tmp_path / "route-check.json"
    old = {**deep, "checked_at": deep["checked_at"] - 2 * 86400, "deep_checked_at": deep["checked_at"] - 2 * 86400}
    kept.write_text(json.dumps(old), encoding="utf-8")
    shallow = api.post("/v1/route-check", headers=HEADERS).json()
    assert shallow["checked_at"] >= deep["checked_at"] and shallow["deep_checked_at"] == old["deep_checked_at"]
    assert main.route_check_due(now=shallow["checked_at"] + 300, interval=86400) is False  # the shallow one is fresh
    assert main.route_check_due(now=shallow["checked_at"] + 300, interval=86400, deep=True) is True

    main._route_check_daily(_OneRound())

    assert sent == ["chatgpt-web", "chatgpt-web"]
    assert main.last_route_check()["deep_checked_at"] >= deep["checked_at"]


def test_a_check_that_was_never_deep_says_so_by_carrying_no_deep_time(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from tests.test_route_check import HEADERS, _routes as _checks, _server

    main = _server(tmp_path, monkeypatch)
    _checks(monkeypatch, {"codex-cli": True})
    shallow = TestClient(main.app).post("/v1/route-check", headers=HEADERS).json()
    assert "deep_checked_at" not in shallow
    assert main.route_check_due(now=shallow["checked_at"] + 1, interval=86400, deep=True) is True


# --- A reply that covers only part of the booklet ----------------------------------------------------------------

def _three_pages(client, monkeypatch, reply):
    from app import main

    _, session_id = _session_with(client, ["問1 2+2を求めよ。", "問2 3+3を求めよ。", "問3 4+4を求めよ。"])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")
    monkeypatch.setenv("ROKID_UNNAMED_PAGES_NOTICE", "1")
    monkeypatch.setattr(main, "PRESEND_RETRY_S", 0)
    monkeypatch.setattr(main, "_answer_all", lambda question: reply())
    return session_id


def test_captured_pages_that_no_answer_names_are_listed_to_be_checked(client, monkeypatch):
    """Valid JSON with fewer questions than the booklet has was stored as the whole answer: nothing compared the
    pages the items name with the pages captured, and the wearer could not tell a short booklet from a cut reply."""
    session_id = _three_pages(client, monkeypatch, lambda: _replies(("第1問", "問1", [1], "4")))
    bundle = _background_finalize_and_wait(client, session_id, lambda items: items[0]["status"] == "ready")
    assert [(item["question_label"], item["status"]) for item in bundle["items"]] == [
        ("問1", "ready"), ("答えのない頁", "needs_review")]
    notice = bundle["items"][-1]
    assert (notice["group_id"], notice["group_label"], notice["answer"]) == ("pages", "撮影の確認", "（解答なし）")
    assert notice["issue"] == "2、3頁の答えがありません。撮影範囲と照合してください"
    assert bundle["available_stage"] == "complete"


def test_the_notice_about_unnamed_pages_is_off_until_it_is_turned_on(client, monkeypatch):
    """With it, a booklet with a cover page is "not all ready" for the PC bench, and bundles that tests elsewhere
    pin get one more item: turning it on is a decision of its own (ROKID_UNNAMED_PAGES_NOTICE=1)."""
    session_id = _three_pages(client, monkeypatch, lambda: _replies(("第1問", "問1", [1], "4")))
    monkeypatch.delenv("ROKID_UNNAMED_PAGES_NOTICE")
    bundle = _background_finalize_and_wait(client, session_id, lambda items: items[0]["status"] == "ready")
    assert [item["question_label"] for item in bundle["items"]] == ["問1"]


def test_a_reply_that_names_every_captured_page_gets_no_notice(client, monkeypatch):
    session_id = _three_pages(client, monkeypatch, lambda: _replies(
        ("第1問", "問1", [1, 2], "4"), ("第1問", "問2", [3], "6")))
    bundle = _background_finalize_and_wait(client, session_id, lambda items: items[0]["status"] == "ready")
    assert [item["question_label"] for item in bundle["items"]] == ["問1", "問2"]


def test_a_booklet_without_any_answer_gets_no_notice_about_its_pages(client, monkeypatch):
    """A failed booklet says why it failed; which pages have no answer is all of them and tells nothing."""
    from app.solvers.chatgpt_web import ChatGptWebRateLimit

    session_id = _three_pages(client, monkeypatch, lambda: _raise(ChatGptWebRateLimit("usage limit")))
    bundle = _background_finalize_and_wait(client, session_id, lambda items: items[0]["status"] == "failed")
    assert len(bundle["items"]) == 1


# --- Work behind the CLI -----------------------------------------------------------------------------------------

def _cli_down():
    from app.solvers.chatgpt_web import ChatGptWebError

    return Cli(ChatGptWebError("the Codex CLI ended without a reply"))


def _closed(session):
    from app import main

    with main.db.connect() as conn:
        return main._closed_routes(main._deck_question_rows(conn, session))


def _work_error(kind):
    from app import work_bridge
    from app.solvers import chatgpt_web

    return getattr(work_bridge, kind, None) or getattr(chatgpt_web, kind)


@pytest.mark.parametrize("kind, message", [
    ("WorkPending", "model_resolution_before_queue"),  # the browser is held by another booklet
    ("WorkConflict", "the original browser package exceeds the bounded upload budget"),
    ("ChatGptWebBlocked", "another browser send is unconfirmed; inventory was not read"),
    ("ChatGptWebBusy", "browser is busy; inventory was not read"),
])
def test_work_behind_the_cli_that_cannot_take_the_booklet_hands_it_to_chat(work_client, monkeypatch, kind, message):
    """The CLI failed and the row named Work as the next route. Work then met a browser another booklet held, a
    send of another booklet left unconfirmed, or a job it could not make: nothing was recorded (or it was retried
    where it stood), the row stayed "retrying", and every poll started the thread again. Chat, which reads another
    booklet's unanswered send back and clears its mark, was never asked."""
    class Refusing(BrowserReply):
        def resolve_new_job_settings(self, **_):
            self.calls.append("settings")
            raise _work_error(kind)(message)

    cli, work, chat = _cli_down(), Refusing(), Chat()
    _, session = booklet(work_client, monkeypatch, cli, work, chat)
    assert answers(work_client, session) == [("ready", "4")]
    # Asked once: nothing of this booklet is with Work, so waiting there gains nothing.
    assert (cli.calls, work.calls, len(chat.questions)) == (1, ["settings"], 1)
    assert answered_by() == ["chatgpt-web"] and work_jobs(session) == []


def _journal_a_send(chat_key):
    """What the browser client writes before a booklet's message leaves (ChatGptWebClient._ask_locked)."""
    from app import main

    directory = main.config.DATA_DIR / "browser-state"
    directory.mkdir(parents=True, exist_ok=True)
    batch = {"id": "b" * 64, "number": 1, "final": True}
    (directory / "chats.json").write_text(json.dumps({"chats": {chat_key: {
        "url": "https://chatgpt.com/", "attached": [], "pending": "a" * 64,
        "transfer": {"completed": [], "pages": [], "final": None, "pending": batch}}}}), encoding="utf-8")


@pytest.mark.parametrize("kind", ["WorkPending", "WorkConflict", "ChatGptWebBlocked", "ChatGptWebBusy"])
def test_a_work_message_never_read_back_keeps_the_booklet_with_work(work_client, monkeypatch, kind):
    """A send whose outcome is unknown is never moved to another route: its reply may be in Work's chat."""
    from app import main

    monkeypatch.setattr(main, "PRESEND_TRIES", 2)

    class Sent(BrowserReply):
        def complete_json(self, **options):
            self.calls.append(options["booklet_stage"])
            _journal_a_send(options["chat_key"])  # journaled by a run a restart ended; this run cannot read it
            raise _work_error(kind)("the browser is held by another booklet")

    cli, work, chat = _cli_down(), Sent(), Chat()
    _, session = booklet(work_client, monkeypatch, cli, work, chat)
    assert work.calls and chat.questions == [] and answered_by() == []
    assert _closed(session) == {"codex-cli"}


def test_an_uncertain_work_send_is_not_moved_when_its_recovery_meets_a_held_browser(work_client, monkeypatch):
    from app import main
    from app.solvers.chatgpt_web import ChatGptWebUncertain
    from app.work_bridge import WorkPending

    class Unsure(BrowserReply):
        def complete_json(self, **options):
            self.calls.append(options["booklet_stage"])
            if len(self.calls) == 1:
                raise ChatGptWebUncertain("send outcome unknown; retained for inspection, no automatic resend")
            raise WorkPending("the browser is held by another booklet")

    cli, work, chat = _cli_down(), Unsure(), Chat()
    _, session = booklet(work_client, monkeypatch, cli, work, chat)
    work_client.get(f"/v1/exam-sessions/{session}/answer-bundle")  # the poll starts the read-only recovery
    wait_for(lambda: len(work.calls) >= 2 and session not in main._background_solves)
    assert chat.questions == [] and answered_by() == [] and _closed(session) == {"codex-cli"}


def test_an_uncertain_work_send_is_read_back_a_few_times_and_then_ends_with_its_sentence(work_client, monkeypatch):
    """It was read back without limit: the item stayed pending, the display stayed asleep, and nothing told the
    wearer. It is still never sent again and never moved to another route."""
    from app import main
    from app.solvers.chatgpt_web import ChatGptWebUncertain

    class Unsure(BrowserReply):
        def complete_json(self, **options):
            self.calls.append(options["booklet_stage"])
            raise ChatGptWebUncertain("send outcome unknown; retained for inspection, no automatic resend")

    cli, work, chat = _cli_down(), Unsure(), Chat()
    _, session = booklet(work_client, monkeypatch, cli, work, chat)
    url = f"/v1/exam-sessions/{session}/answer-bundle"
    assert work_client.get(url).json()["items"][0]["status"] == "pending"  # being read back: the glasses wait
    bundle = wait_for(lambda: (lambda body: body if body["items"][0]["status"] == "failed" else None)(
        work_client.get(url).json()))
    assert bundle["items"][0]["issue"] == "送信結果の確認待ち。自動再送は停止しています"
    assert bundle["available_stage"] == "complete"  # nothing pending: the glasses wake once and show it
    wait_for(lambda: session not in main._background_solves)
    work_client.get(url)  # a later poll reads nothing back
    assert len(work.calls) == 1 + main.RESUME_LIMIT and chat.questions == [] and answered_by() == []
    assert _closed(session) == {"codex-cli"}


def test_a_sealed_work_answer_is_taken_and_not_asked_for_again_elsewhere(work_client, monkeypatch):
    """Work's job was completed while this try was on its way: the try ends "pending" and the next one takes it."""
    from app import main
    from app.solvers.chatgpt_work import ChatGptWorkSolver
    from app.work_bridge import WorkPending

    class Raced(ChatGptWorkSolver):
        tries = 0

        def answer_all(self, *, question):
            replies = super().answer_all(question=question)
            self.tries += 1
            if self.tries == 1:
                raise WorkPending(replies[0][0]["_work_job_id"])
            return replies

    browser = BrowserReply()
    cli, chat = _cli_down(), Chat()
    _, session = booklet(work_client, monkeypatch, cli, Raced(client=browser), chat)
    assert chat.questions == [] and _closed(session) == {"codex-cli"}
    work_client.get(f"/v1/exam-sessions/{session}/answer-bundle")
    wait_for(lambda: answered_by() and session not in main._background_solves)
    assert answers(work_client, session) == [("ready", "4")]
    assert answered_by() == ["chatgpt-work"] and chat.questions == [] and len(browser.calls) == 1


def test_work_as_the_primary_still_waits_where_it_is(work_client, monkeypatch):
    """Only Work behind another primary gives its booklet up: as the primary it waits for its browser as before."""
    from app import main
    from app.solvers.chatgpt_work import ChatGptWorkSolver
    from app.work_bridge import WorkPending

    class Held(ChatGptWorkSolver):
        tries = 0

        def answer_all(self, *, question):
            self.tries += 1
            raise WorkPending("model_resolution_before_queue")

    work, chat = Held(client=BrowserReply()), Chat()
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-work")
    monkeypatch.delenv("ROKID_SOLVER_FALLBACKS", raising=False)
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    monkeypatch.setattr(main, "get_solver", lambda name=None: {"chatgpt-work": work, "chatgpt-web": chat}[
        name or "chatgpt-work"])
    doc = work_client.post("/v1/documents", json={"title": "primary Work"}).json()["document_id"]
    assert work_client.post(f"/v1/documents/{doc}/pages", data={"page_index": 0},
                            files={"image": ("page.png", picture(), "image/png")}).status_code == 201
    assert work_client.post(f"/v1/documents/{doc}/finalize").status_code == 200
    session = work_client.post("/v1/exam-sessions", json={"document_id": doc, "mode": "study",
                                                          "exam_type": "written"}).json()["session_id"]
    assert work_client.post(f"/v1/exam-sessions/{session}/finalize-reading?solve=background").status_code == 200
    wait_for(lambda: work.tries and session not in main._background_solves)
    assert chat.questions == [] and _closed(session) == set()
    with main.db.connect() as conn:
        assert main._deck_question_rows(conn, session) == []  # nothing recorded: the next poll asks Work again
