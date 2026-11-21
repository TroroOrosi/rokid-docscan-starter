"""The first of two reads is shown as soon as it is back; the comparison with the second follows as an update.

The operator's use of 2026-11-18: one read of a booklet was back minutes before the other, which was ended at its
limit. The answers were held for the slower read and reached the server ten and a half minutes after the capture
ended; the wearer had given up.

The route here is a stand-in that does what the Codex CLI route does: it hands its first read's answers over
(``Question.on_first_read``), something looks at what the glasses would be given at that moment, and the compared
answers come back on the same items. The questions and answers are made up.
"""

from app.solvers.base import SolveResult
from tests.test_chatgpt_work import BrowserReply
from tests.test_route_order import Chat, booklet
from tests.test_work_bridge import client as _client_fixture

client = _client_fixture


def question(label, number=None, group="第1問"):
    return {"group": group, "label": label, "pages": [1], "answer_no": [] if number is None else [number]}


def answer(item, text, **extras):
    return SolveResult(answer=text, extras={"answer_status": "ready", "answer_no": list(item["answer_no"]),
                                            "missing_material": "", **extras})


def unreadable(item, **extras):
    return SolveResult(answer="", extras={"answer_status": "needs_input", "answer_no": list(item["answer_no"]),
                                          "missing_material": "不鮮明", **extras})


def once(pairs):
    """A read's answers as they go out before anything is compared (codex_cli marks each ``read_once``)."""
    for _, result in pairs:
        if isinstance(result, SolveResult):
            result.extras["read_once"] = True
    return pairs


class Cli:
    name = "codex-cli"

    def __init__(self, first, final):
        self.first, self.final, self.calls, self.early, self.state = first, final, 0, None, None

    def answer_all(self, *, question):
        from app import main

        self.calls += 1
        question.on_first_read(self.first)
        # What the glasses and the phone's watcher are given while the other read is still running.
        session = int(question.chat_key.split(":")[1])
        self.early = main._answer_snapshot(session, identify=False)
        self.state = main.glasses_status("fixture-glasses")
        if isinstance(self.final, Exception):
            raise self.final
        return self.final


def bundle(client, session):
    return client.get(f"/v1/exam-sessions/{session}/answer-bundle").json()


def shown(items):
    return [(item["question_label"], item["status"], item["answer"]) for item in items]


def ids(items):
    return [item["question_id"] for item in items]


def test_the_first_reads_answers_are_out_while_the_other_read_runs_and_the_bundle_says_that_it_compares(client, monkeypatch):
    one, two = question("問1", 1), question("問2", 2)
    cli = Cli(once([(one, answer(one, "④")), (two, answer(two, "②"))]), [(one, answer(one, "④")), (two, answer(two, "②"))])
    booklet(client, monkeypatch, cli, BrowserReply(), Chat())

    # Nothing but the answers: until 2026-11-19 an item 照合中 stood behind them, and the operator asked for answers
    # without explanations. That the comparison is to come is a mark of the bundle (the glasses show "…").
    assert shown(cli.early["items"]) == [("問1", "ready", "④"), ("問2", "ready", "②")]
    assert cli.early["comparing"] is True
    # The watcher wakes the glasses for it exactly as for a finished booklet.
    assert cli.early["available_stage"] == "complete"
    assert cli.state["answer_ready"] is True and cli.state["answer_revision"] == cli.early["revision"]


def test_the_compared_answers_replace_them_under_the_same_questions_and_the_mark_goes(client, monkeypatch):
    one, two = question("問1", 1), question("問2", 2)
    cli = Cli(once([(one, answer(one, "④")), (two, answer(two, "②"))]),
              [(one, answer(one, "④")), (two, answer(two, "②", review_note="2回の読みで不一致。他方：③", other_answer="③"))])
    _, session = booklet(client, monkeypatch, cli, BrowserReply(), Chat())

    late = bundle(client, session)
    assert shown(late["items"]) == [("問1", "ready", "④"), ("問2", "needs_review", "②")]
    assert late["items"][1]["other"] == "③", "the other read's answer, kept in the bundle"
    assert "other" not in late["items"][0] and "comparing" not in late
    # The glasses show no such answer: its capture is among those to take again (the operator, 2026-11-19 and, after
    # a ？ before thirty answers, 2026-11-21). The bundle says which answers the two reads do not settle.
    assert late["items"][1]["uncertain"] is True and "uncertain" not in late["items"][0]
    assert ids(late["items"]) == ids(cli.early["items"]), "the same questions: the glasses update in place"
    assert late["revision"] > cli.early["revision"], "a newer revision: the watcher notifies again"
    assert cli.calls == 1


def test_a_question_only_the_second_read_listed_is_added_where_the_comparison_put_it(client, monkeypatch):
    one, two, three = question("問1", 1), question("問2", 2), question("問3", 3)
    cli = Cli(once([(one, answer(one, "④")), (three, answer(three, "①"))]),
              [(one, answer(one, "④")), (two, answer(two, "②", review_note="2回のうち1回だけが挙げた設問")),
               (three, answer(three, "①"))])
    _, session = booklet(client, monkeypatch, cli, BrowserReply(), Chat())

    late = bundle(client, session)
    assert shown(late["items"]) == [("問1", "ready", "④"), ("問2", "needs_review", "②"), ("問3", "ready", "①")]
    before = ids(cli.early["items"])
    assert [late["items"][0]["question_id"], late["items"][2]["question_id"]] == before
    assert late["items"][1]["question_id"] not in before
    assert {item["group_label"] for item in late["items"]} == {"第1問"}


def test_an_added_question_never_takes_the_answer_of_a_section_answered_whole_out_of_view(client, monkeypatch):
    """A 大問 answered whole is its own heading row; a row put behind it would turn it into a mere heading. The added
    question goes before it, with its 大問 in its own label."""
    one, whole, more = question("問1"), question("", group="第2問"), question("問2", group="第2問")
    cli = Cli(once([(one, answer(one, "ア")), (whole, answer(whole, "全体の答え"))]),
              [(one, answer(one, "ア")), (whole, answer(whole, "全体の答え")),
               (more, answer(more, "イ", review_note="2回のうち1回だけが挙げた設問"))])
    _, session = booklet(client, monkeypatch, cli, BrowserReply(), Chat())

    late = bundle(client, session)
    assert [(item["group_label"], *row) for item, row in zip(late["items"], shown(late["items"]))] == [
        ("第1問", "問1", "ready", "ア"), ("第1問", "問2（第2問）", "needs_review", "イ"), ("第2問", "全問", "ready", "全体の答え")]
    before = ids(cli.early["items"])
    assert [item["question_id"] for item in late["items"] if item["question_id"] in before] == before


def test_an_answer_only_the_second_read_gave_goes_under_the_question_the_first_read_left_open(client, monkeypatch):
    one, two = question("問1", 1), question("問2", 2)
    cli = Cli(once([(one, unreadable(one)), (two, ValueError("a made-up malformed item"))]),
              [(one, answer(one, "④", review_note="2回のうち1回は解答なし")),
               (two, answer(two, "②", review_note="2回のうち1回は解答なし"))])
    _, session = booklet(client, monkeypatch, cli, BrowserReply(), Chat())

    assert [(item["status"], item["answer"]) for item in cli.early["items"]] == [("needs_input", ""), ("failed", "")]
    late = bundle(client, session)
    assert [(item["status"], item["answer"]) for item in late["items"]] == [("needs_review", "④"), ("needs_review", "②")]
    assert ids(late["items"]) == ids(cli.early["items"])
    # The glasses refuse a question whose printed answer numbers change: each keeps what it was first shown with.
    assert [item.get("answer_no") for item in late["items"]] == [item.get("answer_no") for item in cli.early["items"]]


def test_when_the_second_read_gave_nothing_the_mark_goes_under_a_revision_of_its_own(client, monkeypatch):
    one = question("問1", 1)
    first = once([(one, answer(one, "④"))])
    cli = Cli(first, once([(one, answer(one, "④"))]))
    _, session = booklet(client, monkeypatch, cli, BrowserReply(), Chat())

    late = bundle(client, session)
    assert shown(late["items"]) == [("問1", "ready", "④")] and "comparing" not in late
    assert ids(late["items"]) == ids(cli.early["items"]) and late["revision"] > cli.early["revision"]


def test_a_route_that_fails_after_its_first_read_is_out_has_answered_and_no_other_route_is_asked(client, monkeypatch):
    from app.solvers.chatgpt_web import ChatGptWebReplyIncomplete

    one = question("問1", 1)
    cli, work, chat = Cli(once([(one, answer(one, "④"))]), ChatGptWebReplyIncomplete("the other read broke")), BrowserReply(), Chat()
    _, session = booklet(client, monkeypatch, cli, work, chat)

    late = bundle(client, session)
    assert shown(late["items"]) == [("問1", "ready", "④")]
    assert "comparing" not in late, "the comparison will not come: the mark goes, it is not waited for"
    assert late["revision"] > cli.early["revision"], "nothing was saved again, and the glasses still have to be told"
    assert (cli.calls, work.calls, chat.questions) == (1, [], [])


def test_a_first_read_that_cannot_be_saved_leaves_nothing_behind_and_the_answers_are_saved_in_one_piece(client, monkeypatch):
    import sqlite3

    from app import main

    one = question("問1", 1)
    real_save, failures = main._save_solution, []

    def save(*args, **kwargs):
        if not failures:
            failures.append(1)
            raise sqlite3.OperationalError("database is locked")
        return real_save(*args, **kwargs)

    class Refused:
        name = "codex-cli"
        refused = False

        def answer_all(self, *, question):
            try:
                question.on_first_read(once([(one, answer(one, "④"))]))
            except sqlite3.OperationalError:
                self.refused = True  # codex_cli logs it and goes on (test_a_hand_over_that_fails_costs_neither_read)
            return [(one, answer(one, "④"))]

    cli = Refused()
    monkeypatch.setattr(main, "_save_solution", save)
    _, session = booklet(client, monkeypatch, cli, BrowserReply(), Chat())

    assert cli.refused and shown(bundle(client, session)["items"]) == [("問1", "ready", "④")]
    with main.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM questions WHERE session_id = ?", (session,)).fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM solutions").fetchone()[0] == 1


def test_a_route_that_hands_nothing_over_is_saved_as_before(client, monkeypatch):
    chat = Chat()

    class Limited:
        name = "codex-cli"

        def answer_all(self, *, question):
            from app.solvers.chatgpt_web import ChatGptWebRateLimit

            raise ChatGptWebRateLimit("the Codex CLI reported a usage limit")

    _, session = booklet(client, monkeypatch, Limited(), BrowserReply(), chat)
    assert shown(bundle(client, session)["items"]) == [("問1", "ready", "4")] and len(chat.questions) == 1
