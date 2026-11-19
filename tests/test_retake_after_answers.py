"""Pages taken again after the answers were read are read with the booklet, under the same questions (2026-11-19).

The operator: where the answers end with pages to take again, a double tap takes them, and what was taken before
stays with what is taken now. The phone asks by itself, before anything is sent, for what it can tell (a page that
could not be gathered, tests/test_capture_check.py); this is the last net, for what only the reading could tell.

The glasses ask for the booklet to take pages again (``POST /v1/exam-sessions/{id}/retake``), send the pages under
their own numbers, and finalize as at the first end. The booklet is then read again whole; the answers go over the
questions the wearer was shown, each keeping its identity, and an answer the wearer already had is marked ``seen``
so that the glasses show what is new first. The route here is a stand-in; questions and answers are made up.
"""
import threading

from tests.test_chatgpt_work import BrowserReply
from tests.test_first_read_out import answer, bundle, ids, once, question, shown, unreadable
from tests.test_route_order import Chat, booklet
from tests.test_work_bridge import client as _client_fixture
from tests.test_work_bridge import picture, wait_for

client = _client_fixture


class Rounds:
    """Each call is one reading of the booklet: (the first read's answers or None, the compared answers or a failure)."""
    name = "codex-cli"

    def __init__(self, *rounds, hold: threading.Event | None = None):
        self.rounds, self.calls, self.pages, self.hold = list(rounds), 0, [], hold

    def answer_all(self, *, question):
        first, final = self.rounds[self.calls]
        self.calls += 1
        self.pages.append([page["image_sha256"] for page in question.document_pages])
        if self.calls > 1 and self.hold is not None:
            assert self.hold.wait(10)
        if first is not None:
            question.on_first_read(first)
        if isinstance(final, Exception):
            raise final
        return final


def again(client, document, session, *, wait=True):
    """What the glasses do when the wearer takes page 1 again: reopen, the page under its own number, both finalizes."""
    from app import main

    assert client.post(f"/v1/exam-sessions/{session}/retake").status_code == 200
    replaced = client.post(f"/v1/documents/{document}/pages", data={"page_index": 0},
                           files={"image": ("page.png", picture(7), "image/png")})
    assert replaced.status_code in (200, 201), replaced.text
    assert client.post(f"/v1/documents/{document}/finalize").status_code == 200
    assert client.post(f"/v1/exam-sessions/{session}/finalize-reading?solve=background").status_code == 200
    if wait:
        wait_for(lambda: session not in main._background_solves)


def test_a_page_taken_again_is_read_with_the_booklet_and_the_answers_go_under_the_same_questions(client, monkeypatch):
    one, two = question("問1", 1), question("問2", 2)
    cli = Rounds((None, [(one, answer(one, "④")), (two, unreadable(two))]),
                 (None, [(one, answer(one, "④")), (two, answer(two, "②"))]))
    document, session = booklet(client, monkeypatch, cli, BrowserReply(), Chat())
    before = bundle(client, session)
    assert shown(before["items"]) == [("問1", "ready", "④"), ("問2", "needs_input", "")]
    assert before["retake"] == [1], "the page the unanswered question stands on"

    again(client, document, session)

    after = bundle(client, session)
    assert shown(after["items"]) == [("問1", "ready", "④"), ("問2", "ready", "②")]
    assert ids(after["items"]) == ids(before["items"]), "the same questions, so the glasses keep their places"
    assert after["revision"] > before["revision"], "a newer revision: the watcher notifies again"
    assert after["input_digest"] != before["input_digest"], "another booklet as far as its pictures go"
    assert [item.get("seen", False) for item in after["items"]] == [True, False], "the answer the wearer had; the new one"
    assert "retake" not in after
    assert cli.calls == 2 and cli.pages[0] != cli.pages[1], "read again, with the page that was taken again"


def test_while_the_booklet_is_read_again_the_answers_are_being_made(client, monkeypatch):
    from app import main

    one = question("問1", 1)
    hold = threading.Event()
    cli = Rounds((None, [(one, unreadable(one))]), (None, [(one, answer(one, "④"))]), hold=hold)
    document, session = booklet(client, monkeypatch, cli, BrowserReply(), Chat())
    try:
        again(client, document, session, wait=False)
        wait_for(lambda: cli.calls == 2)
        waiting = client.get(f"/v1/exam-sessions/{session}/answer-bundle")
        assert waiting.status_code == 409 and "being made" in waiting.json()["detail"], "not the answers from before"
        assert main.glasses_status("fixture-glasses")["answer_ready"] is False, "the watcher does not wake for them"
    finally:
        hold.set()
    wait_for(lambda: session not in main._background_solves)
    assert shown(bundle(client, session)["items"]) == [("問1", "ready", "④")]


def test_between_the_retake_and_the_end_of_its_capture_no_answers_are_given(client, monkeypatch):
    one = question("問1", 1)
    cli = Rounds((None, [(one, unreadable(one))]), (None, [(one, answer(one, "④"))]))
    document, session = booklet(client, monkeypatch, cli, BrowserReply(), Chat())
    assert client.post(f"/v1/exam-sessions/{session}/retake").status_code == 200
    assert client.post(f"/v1/exam-sessions/{session}/retake").json()["already"] is True, "asked twice: nothing more"
    assert client.get(f"/v1/exam-sessions/{session}/answer-bundle").status_code == 409
    assert cli.calls == 1


def test_the_first_read_of_the_new_reading_is_out_early_and_compared_as_at_the_first_end(client, monkeypatch):
    one, two = question("問1", 1), question("問2", 2)
    cli = Rounds((None, [(one, answer(one, "④")), (two, unreadable(two))]),
                 (once([(one, answer(one, "④")), (two, answer(two, "②"))]),
                  [(one, answer(one, "④")), (two, answer(two, "②", review_note="2回の読みで不一致。他方：③", other_answer="③"))]))
    document, session = booklet(client, monkeypatch, cli, BrowserReply(), Chat())
    before = bundle(client, session)

    again(client, document, session)

    after = bundle(client, session)
    assert shown(after["items"]) == [("問1", "ready", "④"), ("問2", "needs_review", "②")]
    assert after["items"][1]["other"] == "③" and ids(after["items"]) == ids(before["items"])
    assert after["retake"] == [1], "still not settled: its page stays to be taken again"


def test_a_question_only_the_new_reading_lists_is_added_behind_the_ones_shown(client, monkeypatch):
    one, two = question("問1", 1), question("問2", 2)
    cli = Rounds((None, [(one, answer(one, "④"))]), (None, [(one, answer(one, "④")), (two, answer(two, "②"))]))
    document, session = booklet(client, monkeypatch, cli, BrowserReply(), Chat())
    before = bundle(client, session)

    again(client, document, session)

    after = bundle(client, session)
    assert shown(after["items"]) == [("問1", "ready", "④"), ("問2", "ready", "②")]
    assert after["items"][0]["question_id"] == before["items"][0]["question_id"]
    assert [item.get("seen", False) for item in after["items"]] == [True, False]


def test_a_reading_that_fails_after_a_retake_gives_the_answers_from_before_back(client, monkeypatch):
    from app.solvers.chatgpt_web import ChatGptWebReplyIncomplete

    one, two = question("問1", 1), question("問2", 2)
    cli = Rounds((None, [(one, answer(one, "④")), (two, unreadable(two))]), (None, ChatGptWebReplyIncomplete("made up")))
    document, session = booklet(client, monkeypatch, cli, BrowserReply(), None)
    before = bundle(client, session)

    again(client, document, session)

    after = bundle(client, session)
    assert shown(after["items"]) == shown(before["items"]), "nothing is lost for having tried"
    assert after["revision"] > before["revision"], "and the glasses are told that the wait is over"
    assert after["retake"] == [1]


def test_pages_cannot_be_taken_again_for_a_booklet_that_has_no_answers(client, monkeypatch):
    document = client.post("/v1/documents", json={"title": "no answers"}).json()["document_id"]
    assert client.post(f"/v1/documents/{document}/pages", data={"page_index": 0},
                       files={"image": ("page.png", picture(), "image/png")}).status_code == 201
    assert client.post(f"/v1/documents/{document}/finalize").status_code == 200
    session = client.post("/v1/exam-sessions", json={"document_id": document, "mode": "study",
                                                     "exam_type": "written"}).json()["session_id"]
    assert client.post(f"/v1/exam-sessions/{session}/retake").status_code == 409
    assert client.post("/v1/exam-sessions/999999/retake").status_code == 404


def test_a_reading_again_that_a_restart_of_the_server_cut_off_is_taken_up_by_the_next_look(client, monkeypatch):
    """The batch that reads the booklet again runs in the server's memory. A restart in that time left the retake open
    with nothing reading: no answers were given, for good. The next look at the answers starts it again."""
    from app import main

    one = question("問1", 1)
    cli = Rounds((None, [(one, unreadable(one))]), (None, [(one, answer(one, "④"))]))
    document, session = booklet(client, monkeypatch, cli, BrowserReply(), Chat())
    assert client.post(f"/v1/exam-sessions/{session}/retake").status_code == 200
    assert client.post(f"/v1/documents/{document}/pages", data={"page_index": 0},
                       files={"image": ("page.png", picture(7), "image/png")}).status_code in (200, 201)
    assert client.post(f"/v1/documents/{document}/finalize").status_code == 200
    with main.db.connect() as conn:  # the reading was claimed and its batch then lost with the process
        conn.execute("UPDATE exam_sessions SET status = 'reviewing' WHERE id = ?", (session,))
        conn.commit()
    assert cli.calls == 1 and session not in main._background_solves
    assert client.get(f"/v1/exam-sessions/{session}/answer-bundle").status_code == 409
    wait_for(lambda: cli.calls == 2 and session not in main._background_solves)
    assert shown(bundle(client, session)["items"]) == [("問1", "ready", "④")]
