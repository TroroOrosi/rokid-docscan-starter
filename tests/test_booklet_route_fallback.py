"""A usage limit or an unusable primary must not end the subject at a venue with no PC.

The booklet's one message moves to the next configured route only when the
primary's outcome is known: a received refusal, or a failure before any send.
"""

import pytest

from tests.test_answer_bundle_api import (
    _background_finalize_and_wait, _replies, _session_with, client as _client_fixture,
)

client = _client_fixture


def _routes(monkeypatch, primary, fallback):
    """Primary through the existing entry point; the fallback through its own."""
    from app import main

    monkeypatch.setattr(main, "PRESEND_RETRY_S", 0)
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")
    monkeypatch.setattr(main, "_booklet_routes", lambda: ["test-provider", "backup"])
    calls = {"primary": 0, "backup": 0}

    def answer_all(question):
        calls["primary"] += 1
        return primary(calls["primary"])

    def fallback_answer(conn, session_id, doc_id, question, route):
        assert route == "backup"
        calls["backup"] += 1
        return fallback(calls["backup"])

    monkeypatch.setattr(main, "_answer_all", answer_all)
    monkeypatch.setattr(main, "_fallback_answer", fallback_answer)
    return calls


def _raise(error):
    raise error


def test_a_usage_limit_on_the_primary_is_answered_by_the_next_route(client, monkeypatch):
    from app import main
    from app.solvers.chatgpt_web import ChatGptWebRateLimit

    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    calls = _routes(monkeypatch, lambda n: _raise(ChatGptWebRateLimit("usage limit")),
                    lambda n: _replies(("第1問", "問1", [1], "4")))
    bundle = _background_finalize_and_wait(
        client, session_id, lambda items: items and all(i["status"] == "ready" for i in items))
    assert bundle["items"][0]["answer"] == "4"
    # One refused message, one answered message: the limited route is never asked twice.
    assert calls == {"primary": 1, "backup": 1}
    conn = main.db.connect()
    try:
        assert {row["solver_name"] for row in conn.execute("SELECT solver_name FROM solutions")} == {"backup"}
    finally:
        conn.close()


def test_a_reply_cut_short_without_a_limit_notice_is_also_answered_by_the_next_route(client, monkeypatch):
    """The limit can end the output mid-way; its notice need not be in the message."""
    from app.solvers.chatgpt_web import ChatGptWebReplyIncomplete

    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    calls = _routes(monkeypatch, lambda n: _raise(ChatGptWebReplyIncomplete("ended without its answer")),
                    lambda n: _replies(("第1問", "問1", [1], "4")))
    bundle = _background_finalize_and_wait(
        client, session_id, lambda items: items and all(i["status"] == "ready" for i in items))
    assert bundle["items"][0]["answer"] == "4" and calls == {"primary": 1, "backup": 1}


def test_a_reply_cut_short_on_the_last_route_says_so(client, monkeypatch):
    from app.solvers.chatgpt_web import ChatGptWebRateLimit, ChatGptWebReplyIncomplete

    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    calls = _routes(monkeypatch, lambda n: _raise(ChatGptWebRateLimit("usage limit")),
                    lambda n: _raise(ChatGptWebReplyIncomplete("ended without its answer")))
    issue = "返答が途中で終わりました。資料は保持しています"
    bundle = _background_finalize_and_wait(client, session_id, lambda items: items[0]["issue"] == issue)
    assert bundle["items"][0]["status"] == "failed" and calls == {"primary": 1, "backup": 1}


def test_a_restart_after_the_limit_returns_to_the_next_route_not_the_limited_one(client, monkeypatch):
    """The fallback was busy when the batch ended; the resumed batch must not send to Work again."""
    from app import main
    from app.solvers.chatgpt_web import ChatGptWebBusy, ChatGptWebRateLimit

    monkeypatch.setattr(main, "PRESEND_TRIES", 1)
    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    calls = _routes(monkeypatch, lambda n: _raise(ChatGptWebRateLimit("usage limit")),
                    lambda n: _raise(ChatGptWebBusy("busy")) if n == 1 else _replies(("第1問", "問1", [1], "4")))
    # Each answer-bundle poll resumes a retrying deck, exactly as after a restart.
    bundle = _background_finalize_and_wait(
        client, session_id, lambda items: items and all(i["status"] == "ready" for i in items))
    assert bundle["items"][0]["answer"] == "4"
    assert calls == {"primary": 1, "backup": 2}


def test_every_route_limited_ends_plainly_without_another_send(client, monkeypatch):
    from app.solvers.chatgpt_web import ChatGptWebRateLimit

    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    calls = _routes(monkeypatch, lambda n: _raise(ChatGptWebRateLimit("usage limit")),
                    lambda n: _raise(ChatGptWebRateLimit("usage limit")))
    issue = "ChatGPTの利用制限です。解除後に再開してください"
    bundle = _background_finalize_and_wait(client, session_id, lambda items: items[0]["issue"] == issue)
    assert bundle["items"][0]["status"] == "failed"
    client.get(f"/v1/exam-sessions/{session_id}/answer-bundle")  # A later poll starts nothing.
    assert calls == {"primary": 1, "backup": 1}


def test_an_unknown_send_outcome_never_moves_to_another_route(client, monkeypatch):
    """Another route would duplicate a booklet that may already be answered."""
    from app.solvers.chatgpt_web import ChatGptWebUncertain

    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    calls = _routes(monkeypatch, lambda n: _raise(ChatGptWebUncertain("send outcome unknown")),
                    lambda n: pytest.fail("an uncertain send must not be sent elsewhere"))
    _background_finalize_and_wait(client, session_id, lambda items: items[0]["status"] == "failed")
    assert calls == {"primary": 1, "backup": 0}


def test_a_primary_that_cannot_send_moves_on_after_one_retry(client, monkeypatch):
    """A limit may show as a disabled control before any send, not as a reply."""
    from app.solvers.chatgpt_web import ChatGptWebModelMismatch

    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    calls = _routes(monkeypatch, lambda n: _raise(ChatGptWebModelMismatch("Work is not selectable")),
                    lambda n: _replies(("第1問", "問1", [1], "4")))
    bundle = _background_finalize_and_wait(
        client, session_id, lambda items: items and all(i["status"] == "ready" for i in items))
    assert bundle["items"][0]["answer"] == "4"
    assert calls == {"primary": 2, "backup": 1}


@pytest.mark.parametrize("kind", ["ChatGptWebBrowserUnavailable", "ChatGptWebAuthenticationRequired",
                                  "ChatGptWebBusy", "ChatGptWebBlocked"])
def test_a_failure_the_next_route_shares_keeps_retrying_the_primary(client, monkeypatch, kind):
    """Same browser, same account, same send guard: switching cannot help."""
    from app import main
    from app.solvers import chatgpt_web

    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    calls = _routes(monkeypatch, lambda n: _raise(getattr(chatgpt_web, kind)("shared")) if n < 4
                    else _replies(("第1問", "問1", [1], "4")),
                    lambda n: pytest.fail("a shared failure must not switch routes"))
    bundle = _background_finalize_and_wait(
        client, session_id, lambda items: items and all(i["status"] == "ready" for i in items))
    assert bundle["items"][0]["answer"] == "4" and calls["primary"] == 4
    assert main.PRESEND_TRIES >= 4


def test_the_glasses_are_told_the_route_is_changing_not_that_the_subject_ended(client, monkeypatch):
    from app import main
    from app.solvers.chatgpt_web import ChatGptWebBusy, ChatGptWebRateLimit

    monkeypatch.setattr(main, "PRESEND_TRIES", 1)
    monkeypatch.setattr(main, "_resume_answers", lambda conn, session: False)  # Observe the state between routes.
    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    _routes(monkeypatch, lambda n: _raise(ChatGptWebRateLimit("usage limit")),
            lambda n: _raise(ChatGptWebBusy("busy")))
    monkeypatch.setattr(main, "_route_closed_count", lambda conn, session_id: 0)  # End the batch after the limit.
    issue = "利用制限のため別の経路へ切り替えます"
    bundle = _background_finalize_and_wait(client, session_id, lambda items: items[0]["issue"] == issue)
    assert bundle["items"][0]["status"] == "pending"


def test_work_falls_back_to_chat_by_default_and_other_primaries_have_no_fallback(monkeypatch):
    from app import main

    monkeypatch.delenv("ROKID_SOLVER_FALLBACKS", raising=False)
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-work")
    assert main._booklet_routes() == ["chatgpt-work", "chatgpt-web"]
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-web")
    assert main._booklet_routes() == ["chatgpt-web"]
    # Explicit order; unknown names and routes without a one-message answer are dropped.
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-work")
    monkeypatch.setenv("ROKID_SOLVER_FALLBACKS", "chatgpt-web, no-such-solver, local, chatgpt-work")
    assert main._booklet_routes() == ["chatgpt-work", "chatgpt-web"]
    monkeypatch.setenv("ROKID_SOLVER_FALLBACKS", "")
    assert main._booklet_routes() == ["chatgpt-work"]
    # Work's sealed jobs and commit guard exist only for the primary.
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-web")
    monkeypatch.setenv("ROKID_SOLVER_FALLBACKS", "chatgpt-work")
    assert main._booklet_routes() == ["chatgpt-web"]


def test_a_saved_stage_pins_its_route_even_after_the_fallback_is_disabled(client, monkeypatch):
    """The recording must go to the chat that holds the images, whatever the configuration says now."""
    from app import main
    from app.solvers.base import SolveResult

    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    client.post(f"/v1/exam-sessions/{session_id}/finalize-reading")
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-work")
    monkeypatch.setenv("ROKID_SOLVER_FALLBACKS", "")
    conn = main.db.connect()
    try:
        row = main._deck_question_rows(conn, session_id)[0]
        assert main._booklet_route(conn, session_id) == ("chatgpt-work", False)
        main._save_solution(conn, row, SolveResult(answer="4"), "chatgpt-web")
        assert main._booklet_route(conn, session_id) == ("chatgpt-web", False)
        # A damaged record cannot stop a failure from being written.
        conn.execute("UPDATE questions SET structure_json = ? WHERE id = ?",
                     ('{"deck": true, "closed_routes": 7}', row["id"]))
        assert main._closed_routes(main._deck_question_rows(conn, session_id)) == set()
    finally:
        conn.close()


class _Page:
    """Only what leave_work_mode reads: the Work entry's state, and one toggle."""

    def __init__(self, count, active, *, toggles=True, lost_clicks=0):
        self.count, self.active, self.toggles, self.clicks = count, active, toggles, 0
        self.lost_clicks = lost_clicks

    def evaluate(self, script):
        if "(true)" in script[-8:] and self.count == 1 and self.active:
            self.clicks += 1
            self.active = not self.toggles or self.clicks <= self.lost_clicks
            return {"count": self.count, "active": self.active, "acted": True}
        return {"count": self.count, "active": self.active, "acted": False}


def test_chat_leaves_work_mode_before_preparing_and_never_sends_inside_it(monkeypatch):
    from app.solvers import chatgpt_web as chat

    monkeypatch.setattr(chat, "READY_TIMEOUT_S", 0.2)
    plain = _Page(0, False)
    chat.leave_work_mode(plain, select=True)
    assert plain.clicks == 0  # No Work entry: ordinary Chat.
    active = _Page(1, True)
    chat.leave_work_mode(active, select=True)
    assert active.clicks == 1 and not active.active
    # Phone, 2026-11-10: a click right after the new-chat navigation was dropped.
    monkeypatch.setattr(chat, "READY_TIMEOUT_S", 5.0)
    busy = _Page(1, True, lost_clicks=1)
    chat.leave_work_mode(busy, select=True)
    assert busy.clicks == 2 and not busy.active
    monkeypatch.setattr(chat, "READY_TIMEOUT_S", 0.2)
    # Immediately before sending nothing is clicked: Work still active stops the send.
    with pytest.raises(chat.ChatGptWebModelMismatch):
        chat.leave_work_mode(_Page(1, True), select=False)
    with pytest.raises(chat.ChatGptWebModelMismatch):
        chat.leave_work_mode(_Page(1, True, toggles=False), select=True)
    with pytest.raises(chat.ChatGptWebModelMismatch):
        chat.leave_work_mode(_Page(2, False), select=True)


class _PowerPage:
    """Chat's Power slider as read on the phone: five labelled positions, one step per key event."""

    LABELS = ["Light", "Medium", "High", "Extra High", "Pro"]

    def __init__(self, value, *, labels=None, count=1, enabled=True, stuck=False):
        self.labels = self.LABELS if labels is None else labels
        self.value, self.count, self.enabled, self.stuck, self.steps = value, count, enabled, stuck, 0

    def evaluate(self, script):
        if self.count != 1:
            return {"count": self.count}
        step = 1 if script.endswith("(1)") else -1 if script.endswith("(-1)") else 0
        if step and self.enabled and 0 <= self.value + step < len(self.labels):
            self.steps += 1
            self.value += 0 if self.stuck else step
        return {"count": 1, "value": self.value, "min": 0, "max": len(self.labels) - 1,
                "enabled": self.enabled, "label": self.labels[self.value]}


def test_chat_moves_its_power_slider_to_extra_high_not_to_the_locked_top_position():
    """Phone, 2026-11-10: saved at Medium; the maximum is Pro, locked with a usage-limit notice."""
    from app.solvers import chatgpt_web as chat

    medium = _PowerPage(1)
    chat._select_extra_high_power(medium)
    assert (medium.labels[medium.value], medium.steps) == ("Extra High", 2)
    pro = _PowerPage(4)
    chat._select_extra_high_power(pro)
    assert (pro.labels[pro.value], pro.steps) == ("Extra High", 1)
    already = _PowerPage(3)
    chat._select_extra_high_power(already)
    assert already.steps == 0
    # No Extra High position, or a control that cannot be read or moved: left for the check to refuse.
    for page in (_PowerPage(1, labels=["Light", "Medium", "High", "Pro"]), _PowerPage(1, count=0),
                 _PowerPage(1, count=2), _PowerPage(1, enabled=False), _PowerPage(1, stuck=True),
                 _PowerPage(1, labels=["", "", "", "", ""])):
        chat._select_extra_high_power(page)
        assert chat._power_rank(page.labels[page.value] if page.count == 1 else "") != 3


@pytest.mark.parametrize("label, accepted", [("Extra High", True), ("extra-high", True), ("極高", True),
                                             ("Pro", False), ("High", False), ("Medium", False), ("Max", False)])
def test_a_readable_power_position_other_than_extra_high_never_sends(monkeypatch, label, accepted):
    """Pro matched no effort word, so the old check read it as no effort and let the send through."""
    from app.solvers import chatgpt_web as chat

    monkeypatch.setattr(chat, "leave_work_mode", lambda page, select=False: None)
    monkeypatch.setattr(chat, "_selected_model_in_effort_menu",
                        lambda page, select=False: {"models": ["GPT-6"], "power": label, "efforts": [label]})

    class Page:
        url = "https://chatgpt.com/"

    if accepted:
        assert chat.verify_selected_model(Page()) == "GPT-6"
    else:
        with pytest.raises(chat.ChatGptWebModelMismatch):
            chat.verify_selected_model(Page())


@pytest.mark.parametrize("rendered_late", [False, True])
def test_a_new_chat_leaves_work_mode_before_waiting_for_the_chat_composer(monkeypatch, rendered_late):
    """Phone, 2026-11-10: in Work mode Chat's composer is absent, so the wait alone can only time out."""
    from app.solvers import chatgpt_web as chat

    monkeypatch.setattr(chat, "READY_TIMEOUT_S", 0.2)
    page = _Page(0 if rendered_late else 1, not rendered_late)
    waits = []

    def wait_for_composer(target, *, ready_timeout_s=None):
        waits.append(target.active)
        if target.active or (rendered_late and len(waits) == 1):
            target.count, target.active = 1, True  # The toggle appears while Chat's composer never does.
            raise chat.ChatGptWebError("composer did not appear; nothing sent")
        return "chat composer"

    monkeypatch.setattr(chat, "wait_for_composer", wait_for_composer)
    assert chat.wait_for_chat_composer(page) == "chat composer"
    assert page.clicks == 1 and not page.active
    assert waits == ([False, False] if rendered_late else [False])


def test_a_missing_chat_composer_outside_work_mode_is_still_an_error(monkeypatch):
    from app.solvers import chatgpt_web as chat

    def absent(target, *, ready_timeout_s=None):
        raise chat.ChatGptWebError("composer did not appear; nothing sent")

    monkeypatch.setattr(chat, "wait_for_composer", absent)
    page = _Page(0, False)
    with pytest.raises(chat.ChatGptWebError):
        chat.wait_for_chat_composer(page)
    assert page.clicks == 0


def test_the_work_entry_reader_runs_in_a_real_dom():
    """The script itself, in local Chromium, on the control shape read from the phone."""
    import html
    import json
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    from app.solvers import chatgpt_web as chat

    browser = next((p for p in [shutil.which("google-chrome"), shutil.which("chromium"),
                    "C:/Program Files/Google/Chrome/Application/chrome.exe"] if p and Path(p).is_file()), None)
    if browser is None:
        pytest.skip("local Chromium is not installed; no browser is downloaded")
    # The real control (phone, 2026-11-10): two buttons, exactly one pressed.
    pick = ("[...this.parentNode.children].forEach(e => e.setAttribute(e.hasAttribute('aria-pressed') ? "
            "'aria-pressed' : 'aria-selected', String(e === this)))")
    fixtures = [
        '<button aria-pressed="false">Search</button><div id="prompt-textarea"></div>',
        f'<div><button aria-pressed="false" onclick="{pick}">Chat</button>'
        f'<button aria-pressed="true" onclick="{pick}">Work</button></div>',
        f'<div><button aria-pressed="true" onclick="{pick}">Chat</button>'
        f'<button aria-pressed="false" onclick="{pick}">Work</button></div>',
        f'<div role="tablist"><div role="tab" aria-selected="false" onclick="{pick}">Chat</div>'
        f'<div role="tab" aria-selected="true" onclick="{pick}">ChatGPT Work</div></div>',
        '<button aria-pressed="true">Work</button>',
        f'<div><button aria-pressed="false" onclick="{pick}">Chat</button>'
        f'<button aria-pressed="true" onclick="{pick}">Work</button><button aria-pressed="true">ワーク</button></div>',
        f'<div><button aria-pressed="false" disabled onclick="{pick}">Chat</button>'
        f'<button aria-pressed="true" onclick="{pick}">Work</button></div>',
        f'<div><button aria-pressed="false" onclick="{pick}">Chat</button>'
        f'<button aria-pressed="true" onclick="{pick}">Work</button>'
        '<button aria-pressed="false">Filter chats and work</button></div>',
    ]
    script = ("const states = " + json.dumps(fixtures) + ".map(source => { document.body.innerHTML = source; "
              f"const before = {chat._WORK_MODE_JS}(false); const click = {chat._WORK_MODE_JS}(true); "
              f"return [before, click.acted, {chat._WORK_MODE_JS}(false)]; }}); "
              "document.body.innerHTML = '<pre id=states></pre>';"
              "document.getElementById('states').textContent = JSON.stringify(states);")
    with tempfile.TemporaryDirectory(prefix="rokid-work-mode-dom-") as directory:
        fixture = Path(directory) / "fixture.html"
        fixture.write_text('<meta charset="utf-8"><body><script>' + script + "</script>", encoding="utf-8")
        result = subprocess.run([
            browser, "--headless", "--dump-dom", "--disable-background-networking", "--disable-component-update",
            "--disable-sync", "--no-first-run", "--no-default-browser-check", "--host-resolver-rules=MAP * ~NOTFOUND",
            "--user-data-dir=" + str(Path(directory) / "profile"), fixture.as_uri(),
        ], capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
    assert result.returncode == 0, f"{browser} exited {result.returncode}: {result.stderr}"
    states = json.loads(html.unescape(result.stdout.split('<pre id="states">', 1)[1].split("</pre>", 1)[0]))
    summary = [((before["count"], before["active"]), acted, after["active"]) for before, acted, after in states]
    assert summary == [
        ((0, False), False, False),  # Plain Chat: nothing to leave.
        ((1, True), True, False),    # The real control: its Chat sibling leaves Work.
        ((1, False), False, False),  # Already Chat: nothing is clicked.
        ((1, True), True, False),    # The same pair as tabs.
        ((1, True), False, True),    # A lone Work toggle has no known way out: the caller stops.
        ((2, False), False, False),  # Ambiguous Work entries: count 2 stops the caller.
        ((1, True), False, True),    # Chat disabled: not clicked, the caller stops.
        ((1, True), True, False),    # An unrelated filter button is not a mode entry.
    ]
