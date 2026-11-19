"""The watcher's poll costs nothing while a booklet's answers are settled (2026-11-19).

The phone's watcher asks for the glasses' state twice a second, and for as long as the wearer waits or reads (130
minutes of a use) each answer built the whole answer bundle again: every question row, its answer and its notes. On
the phone at rest that was the server's 6% of a core. Once a booklet's answers are complete the answer is kept, by
what it hangs on (the newest answer, the reading's status and stage, a retake, a comparison under way), and built
again only when one of those has moved. A booklet still being answered is built every time, as before: that poll is
also what takes a stopped batch up again.
"""
from tests.test_chatgpt_work import BrowserReply
from tests.test_first_read_out import answer, question
from tests.test_retake_after_answers import Rounds, again
from tests.test_route_order import Chat, booklet
from tests.test_work_bridge import client as _client_fixture

client = _client_fixture


def counted(monkeypatch):
    from app import main

    calls, real = [], main._answer_snapshot

    def snapshot(session_id, *, identify):
        calls.append(identify)
        return real(session_id, identify=identify)

    monkeypatch.setattr(main, "_answer_snapshot", snapshot)
    return calls


def test_a_settled_booklet_is_built_once_for_any_number_of_polls(client, monkeypatch):
    from app import main

    one = question("問1", 1)
    cli = Rounds((None, [(one, answer(one, "④"))]))
    booklet(client, monkeypatch, cli, BrowserReply(), Chat())
    calls = counted(monkeypatch)
    first = main.glasses_status("fixture-glasses")
    assert first["answer_ready"] is True and first["available_stage"] == "complete" and len(calls) == 1
    for _ in range(5):
        assert main.glasses_status("fixture-glasses") == first
    assert len(calls) == 1, "nothing moved: the bundle is not built again"


def test_new_answers_and_a_retake_are_seen_by_the_next_poll(client, monkeypatch):
    from app import main

    one = question("問1", 1)
    cli = Rounds((None, [(one, answer(one, "④"))]), (None, [(one, answer(one, "②"))]))
    document, session = booklet(client, monkeypatch, cli, BrowserReply(), Chat())
    first = main.glasses_status("fixture-glasses")
    assert main.glasses_status("fixture-glasses") == first

    assert client.post(f"/v1/exam-sessions/{session}/retake").status_code == 200
    assert main.glasses_status("fixture-glasses")["answer_ready"] is False, "pages are being taken again: no answers"

    again(client, document, session)
    later = main.glasses_status("fixture-glasses")
    assert later["answer_ready"] is True and later["answer_revision"] > first["answer_revision"]
