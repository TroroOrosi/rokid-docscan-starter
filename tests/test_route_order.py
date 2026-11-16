"""The booklet's routes in the operator's order (2026-11-16): the Codex CLI, then Work, then Chat.

Work stands in when the CLI cannot be used for some other cause. Chat stands in when the usage has run out: Work
draws on the allowance the CLI draws on, so a limit skips it. Work runs here behind another primary with its real
sealed job and guards; only the browser client and the other two routes are stand-ins.
"""

import json

from tests.test_chatgpt_work import BrowserReply
from tests.test_work_bridge import client as _client_fixture, picture, wait_for

client = _client_fixture


class Cli:
    name = "codex-cli"

    def __init__(self, error):
        self.error, self.calls = error, 0

    def answer_all(self, *, question):
        self.calls += 1
        raise self.error


class Chat:
    name = "chatgpt-web"

    def __init__(self):
        self.questions = []

    def answer_all(self, *, question):
        from app.solvers.base import SolveResult

        self.questions.append(question)
        return [({"group": "第1問", "label": "問1", "pages": [1], "answer_no": [1]}, SolveResult(answer="4"))]


def booklet(client, monkeypatch, cli, work, chat, *, wait=True):
    """One page, a bound wearer, the CLI as the primary and nothing said about fallbacks; then the capture ends."""
    from app import main
    from app.solvers.chatgpt_work import ChatGptWorkSolver

    monkeypatch.setenv("ROKID_SOLVER", "codex-cli")
    monkeypatch.delenv("ROKID_SOLVER_FALLBACKS", raising=False)
    monkeypatch.delenv("ROKID_WORK_SPEED", raising=False)
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    monkeypatch.setattr(main, "PRESEND_RETRY_S", 0)
    solvers = {"codex-cli": cli, "chatgpt-web": chat,
               "chatgpt-work": work if isinstance(work, ChatGptWorkSolver) else ChatGptWorkSolver(client=work)}
    monkeypatch.setattr(main, "get_solver", lambda name=None: solvers[name or "codex-cli"])
    doc = client.post("/v1/documents", json={"title": "route order"}).json()["document_id"]
    assert client.post(f"/v1/documents/{doc}/pages", data={"page_index": 0},
                       files={"image": ("page.png", picture(), "image/png")}).status_code == 201
    assert client.post(f"/v1/documents/{doc}/finalize").status_code == 200
    session = client.post("/v1/exam-sessions", json={"document_id": doc, "mode": "study",
                                                     "exam_type": "written"}).json()["session_id"]
    assert client.post("/v1/glasses/state", json={"device_id": "fixture-glasses", "session_id": session,
                       "generation": 7, "sequence": 1, "phase": "analyzing"}).json()["accepted"]
    assert client.post(f"/v1/exam-sessions/{session}/finalize-reading?solve=background").status_code == 200
    if wait:
        wait_for(lambda: session not in main._background_solves)
    return doc, session


def answers(client, session):
    bundle = client.get(f"/v1/exam-sessions/{session}/answer-bundle").json()
    return [(item["status"], item["answer"]) for item in bundle["items"]]


def answered_by():
    from app import main

    with main.db.connect() as conn:
        return [row[0] for row in conn.execute("SELECT solver_name FROM solutions")]


def work_jobs(session):
    from app.work_bridge import configured_work_store

    store = configured_work_store()
    return store.session_jobs(session) if store.path.is_file() else []


def test_the_cli_is_followed_by_work_and_then_chat_unless_the_order_is_given(monkeypatch):
    from app import main

    monkeypatch.delenv("ROKID_SOLVER_FALLBACKS", raising=False)
    monkeypatch.setenv("ROKID_SOLVER", "codex-cli")
    assert main._booklet_routes() == ["codex-cli", "chatgpt-work", "chatgpt-web"]
    monkeypatch.setenv("ROKID_SOLVER_FALLBACKS", "chatgpt-web")
    assert main._booklet_routes() == ["codex-cli", "chatgpt-web"]


def test_a_usage_limit_on_the_cli_goes_to_chat_and_work_is_never_asked(client, monkeypatch):
    from app.solvers.chatgpt_web import ChatGptWebRateLimit

    cli, work, chat = Cli(ChatGptWebRateLimit("the Codex CLI reported a usage limit")), BrowserReply(), Chat()
    _, session = booklet(client, monkeypatch, cli, work, chat)
    assert answers(client, session) == [("ready", "4")]
    # One refused request, one answered message. Work would meet the same limit: nothing is sealed or sent for it.
    assert (cli.calls, work.calls, len(chat.questions)) == (1, [], 1)
    assert answered_by() == ["chatgpt-web"] and work_jobs(session) == []


def test_a_cli_that_fails_for_another_cause_is_answered_by_work_under_its_sealed_job(client, monkeypatch):
    from app.solvers.chatgpt_web import ChatGptWebError
    from app.work_bridge import configured_work_store

    cli, work, chat = Cli(ChatGptWebError("the Codex CLI ended without a reply")), BrowserReply(), Chat()
    _, session = booklet(client, monkeypatch, cli, work, chat)
    assert answers(client, session) == [("ready", "4")]
    # One retry shows the failure is not a passing one; then Work takes the same booklet and Chat is not needed.
    assert (cli.calls, len(work.calls), chat.questions) == (2, 1, [])
    assert answered_by() == ["chatgpt-work"]
    jobs = work_jobs(session)
    assert len(jobs) == 1 and jobs[0]["status"] == "completed"
    assert configured_work_store().result(jobs[0]["job_id"]) is not None
    # Work answers in Fast mode unless a trial says otherwise.
    assert jobs[0]["requested_settings"]["speed"] == "fast"
    # A later poll or restart asks no route again.
    from app import main

    with main.db.connect() as conn:
        row = conn.execute("SELECT * FROM exam_sessions WHERE id=?", (session,)).fetchone()
        assert not main._resume_answers(conn, row)
    assert (cli.calls, len(work.calls), chat.questions) == (2, 1, [])


def test_a_cli_whose_model_is_no_longer_offered_is_answered_by_work(client, monkeypatch, capsys):
    """It is no usage limit, so Work is the next route (after the one retry every such failure gets); the cause is
    logged by name."""
    from app.solvers.chatgpt_web import ChatGptWebModelMismatch

    cli, work, chat = Cli(ChatGptWebModelMismatch("the Codex CLI's model is not offered")), BrowserReply(), Chat()
    _, session = booklet(client, monkeypatch, cli, work, chat)
    assert answers(client, session) == [("ready", "4")]
    assert (cli.calls, len(work.calls), chat.questions) == (2, 1, []) and answered_by() == ["chatgpt-work"]
    failures = [json.loads(line) for line in capsys.readouterr().out.splitlines() if '"solve_failure"' in line]
    assert failures and {failure["code"] for failure in failures} == {"model_mismatch"}


def test_work_that_meets_the_limit_after_the_cli_failed_hands_the_booklet_to_chat(client, monkeypatch):
    from app.solvers.chatgpt_web import ChatGptWebError, ChatGptWebRateLimit

    class Limited(BrowserReply):
        def complete_json(self, **options):
            self.calls.append(options["booklet_stage"])
            raise ChatGptWebRateLimit("the recorded Work task received a usage limit")

    cli, work, chat = Cli(ChatGptWebError("the Codex CLI could not start")), Limited(), Chat()
    _, session = booklet(client, monkeypatch, cli, work, chat)
    assert answers(client, session) == [("ready", "4")]
    assert (cli.calls, len(work.calls), len(chat.questions)) == (2, 1, 1)
    assert answered_by() == ["chatgpt-web"]
    # Chat receives the canonical upright page, not a Work-sealed source reference.
    page = chat.questions[0].document_pages[0]
    assert page["image_path"].endswith(".png") and "_work_source_job_id" not in page


def test_a_session_work_cannot_bind_goes_from_the_cli_to_chat(client, monkeypatch):
    """Work needs the wearer's registered generation; without one it is not a route for this booklet."""
    from app import main
    from app.solvers.chatgpt_web import ChatGptWebError
    from app.work_bridge import WorkConflict

    def unbound(session_id):
        raise WorkConflict("the physical session has no authenticated glasses binding")

    monkeypatch.setattr(main, "work_binding", unbound)
    cli, work, chat = Cli(ChatGptWebError("the Codex CLI ended without a reply")), BrowserReply(), Chat()
    _, session = booklet(client, monkeypatch, cli, work, chat)
    assert answers(client, session) == [("ready", "4")]
    assert (cli.calls, work.calls, len(chat.questions)) == (2, [], 1)
    assert answered_by() == ["chatgpt-web"]


def new_wearer(client, session):
    assert client.post("/v1/glasses/state", json={"device_id": "fixture-glasses", "session_id": session,
                       "generation": 8, "sequence": 1, "phase": "analyzing"}).json()["accepted"]


def test_a_wearer_change_while_work_stands_in_does_not_record_its_failure(client, monkeypatch):
    """Work's fence holds when Work is not the primary: what failed for one wearer is not carried to the next."""
    from app import main
    from app.solvers.chatgpt_web import ChatGptWebAttachmentFailed, ChatGptWebError

    class Unusable(BrowserReply):
        def complete_json(self, **options):
            self.calls.append(options["booklet_stage"])
            if len(self.calls) == 2:  # the retry: the wearer changes while the last attempt is failing
                with main.db.connect() as conn:  # this test's only session
                    new_wearer(client, conn.execute("SELECT MAX(id) FROM exam_sessions").fetchone()[0])
            raise ChatGptWebAttachmentFailed("the attachment control is unusable")

    cli, work, chat = Cli(ChatGptWebError("the Codex CLI ended without a reply")), Unusable(), Chat()
    _, session = booklet(client, monkeypatch, cli, work, chat)
    assert len(work.calls) == 2 and chat.questions == [] and answered_by() == []
    with main.db.connect() as conn:
        closed = main._closed_routes(main._deck_question_rows(conn, session))
    assert closed == {"codex-cli"}


def test_a_wearer_change_after_works_reply_does_not_commit_it(client, monkeypatch):
    """The sealed-job guard holds when Work is not the primary: a reply for one wearer is not saved for the next."""
    from app.solvers.chatgpt_web import ChatGptWebError
    from app.solvers.chatgpt_work import ChatGptWorkSolver

    class Late(ChatGptWorkSolver):
        def answer_all(self, *, question):
            replies = super().answer_all(question=question)
            new_wearer(client, int(question.chat_key.split(":")[1]))
            return replies

    browser = BrowserReply()
    cli, chat = Cli(ChatGptWebError("the Codex CLI ended without a reply")), Chat()
    booklet(client, monkeypatch, cli, Late(client=browser), chat)
    assert len(browser.calls) == 1 and chat.questions == [] and answered_by() == []
