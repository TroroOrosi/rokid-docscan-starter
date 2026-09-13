"""Tests for the subscription-only ChatGPT web solver (no API key, no browser).

The page interaction is exercised against a stub page, so these run offline and
never touch chatgpt.com. What they can prove is the contract on our side of the
boundary: the prompt is placed without being sent early, a streaming reply is
waited out, a stalled one fails loudly, and the answer-only SolveResult shape is
the same one the API adapters produce. What they cannot prove is that OpenAI's
page still matches the selectors -- only a live run shows that.
"""

from __future__ import annotations

import json

import pytest

from app.solvers import Question
from app.solvers import chatgpt_web
from app.solvers.chatgpt_web import (
    ChatGptWebError,
    ChatGptWebSolver,
    ask_page,
    cdp_available,
    image_payload,
)


PNG = b"\x89PNG\r\n\x1a\n" + b"fake page image"
JPEG = b"\xff\xd8\xff" + b"fake page photo"


class _Locator:
    def __init__(self, page, selector):
        self._page = page
        self._selector = selector

    def wait_for(self, **kw):
        if self._selector in self._page.missing:
            raise TimeoutError(f"{self._selector} never appeared")
        self._page.events.append(("wait_for", self._selector))

    def click(self):
        self._page.events.append(("click", self._selector))

    def fill(self, text):
        self._page.events.append(("fill", text))

    def set_input_files(self, payload):
        self._page.events.append(("upload", payload))
        self._page.uploads.append(payload)

    def count(self):
        if self._selector == chatgpt_web.STOP_SEL:
            # Scripted per poll: 1 while the reply streams, 0 once it stops.
            frames = self._page.streaming
            if not frames:
                return 0
            value = frames[min(self._page.stop_poll, len(frames) - 1)]
            self._page.stop_poll += 1
            return 1 if value else 0
        if self._selector == chatgpt_web.ATTACHMENT_SEL:
            # A real chatgpt.com composer already matches the default selector
            # once with nothing attached, so the stub carries that baseline too.
            uploaded = len(self._page.uploads) if self._page.thumbnail_appears else 0
            return self._page.thumbnail_baseline + uploaded
        return len(self._page.replies)

    @property
    def last(self):
        return self

    def inner_text(self):
        # Each poll advances the stream by one scripted frame; the final frame
        # repeats so the reply reads as finished.
        frames = self._page.replies
        value = frames[min(self._page.poll, len(frames) - 1)] if frames else ""
        self._page.poll += 1
        return value


class _Keyboard:
    def __init__(self, page):
        self._page = page

    def press(self, key):
        self._page.events.append(("press", key))


class _StubPage:
    """Minimal stand-in for a Playwright page: the calls ask_page actually makes."""

    def __init__(self, reply_frames, *, thumbnail_appears=True, thumbnail_baseline=1,
                 missing=(), streaming=()):
        self.replies = reply_frames
        self.events = []
        self.uploads = []
        self.streaming = list(streaming)
        self.stop_poll = 0
        self.thumbnail_appears = thumbnail_appears
        self.thumbnail_baseline = thumbnail_baseline
        self.missing = set(missing)
        self.poll = 0
        self.keyboard = _Keyboard(self)

    def locator(self, selector):
        return _Locator(self, selector)

    # The retry path opens and closes a page per attempt.
    def goto(self, *args, **kwargs):
        self.events.append(("goto", args[0] if args else ""))

    def close(self):
        self.events.append(("close", None))


def _ask(page, text="問1 2x+3=7 を解け", **kw):
    kw.setdefault("sleep", lambda _s: None)
    return ask_page(page, text, poll_s=0, stable_polls=2, **kw)


def test_reply_is_returned_once_the_stream_stops_growing():
    page = _StubPage(["解", '{"status":"ready",', '{"status":"ready","answer":"x=2"}'])
    assert _ask(page) == ('{"status":"ready","answer":"x=2"}', None)


def test_prompt_is_filled_whole_so_a_newline_does_not_send_it_early():
    # A multi-line prompt typed key by key would submit at the first newline,
    # sending only the system preamble. It must arrive as one fill.
    page = _StubPage(["done", "done", "done"])
    text = "system line\n\n問題:\n次を解け"
    _ask(page, text)

    fills = [value for kind, value in page.events if kind == "fill"]
    assert fills == [text]
    # Exactly one send, and it comes after the text is in place.
    assert [kind for kind, _ in page.events] == ["wait_for", "click", "fill", "press"]


def test_a_reply_that_never_settles_raises_instead_of_returning_a_partial():
    # Every frame differs, so the text never stabilises: a truncated answer
    # must not be passed off as the finished one.
    page = _StubPage([f"partial {i}" for i in range(50)])
    ticks = iter([0.0, 1.0, 2.0, 3.0])
    with pytest.raises(ChatGptWebError, match="still streaming"):
        _ask(page, timeout_s=3, now=lambda: next(ticks, 99.0))


def test_no_reply_at_all_is_reported_differently_from_a_stalled_one():
    page = _StubPage([])
    ticks = iter([0.0, 1.0, 2.0, 3.0])
    with pytest.raises(ChatGptWebError, match="no reply appeared"):
        _ask(page, timeout_s=3, now=lambda: next(ticks, 99.0))


def test_image_is_attached_as_its_own_part_before_the_text_is_typed():
    # The figure must be a separate attachment, not merged into the prompt, and
    # it has to be uploading before a keypress can send the message.
    page = _StubPage(["done", "done", "done"])
    reply, attached = _ask(page, "問3 図の角度を求めよ", images=[PNG])

    assert attached is True
    assert reply == "done"
    kinds = [kind for kind, _ in page.events]
    assert kinds == ["wait_for", "upload", "click", "fill", "press"]
    # The text part carries no image bytes.
    fills = [value for kind, value in page.events if kind == "fill"]
    assert fills == ["問3 図の角度を求めよ"]


def test_no_image_means_no_upload_at_all():
    page = _StubPage(["done", "done", "done"])
    _, attached = _ask(page, images=None)

    assert attached is None
    assert [kind for kind, _ in page.events] == ["wait_for", "click", "fill", "press"]


def test_an_unconfirmed_upload_still_sends_but_is_reported():
    # The preview selector is OpenAI's and may move. Losing the answer over a
    # missing thumbnail would be worse than sending and recording the doubt.
    page = _StubPage(["done", "done", "done"], thumbnail_appears=False)
    ticks = iter([0.0, 1.0, 2.0, 3.0])
    reply, attached = _ask(page, images=[PNG], upload_timeout_s=2, now=lambda: next(ticks, 99.0))

    assert attached is False
    assert reply == "done"
    assert ("upload", page.uploads[0]) in page.events


def test_attachment_type_is_sniffed_from_the_bytes_not_the_name():
    # The server persists PNG but the relay uploads JPEG; a wrongly labelled
    # attachment is refused by the upload endpoint.
    assert image_payload(PNG)["mimeType"] == "image/png"
    assert image_payload(PNG)["name"].endswith(".png")
    assert image_payload(JPEG)["mimeType"] == "image/jpeg"
    assert image_payload(JPEG)["name"].endswith(".jpg")
    # The buffer is passed through, so no temporary file is written.
    assert image_payload(JPEG)["buffer"] is JPEG


def test_a_preexisting_thumbnail_match_is_not_mistaken_for_our_upload():
    # Measured on chatgpt.com (Chrome 152): the default ATTACHMENT_SEL already
    # matched one element on a composer with nothing attached. Confirming on a
    # non-zero count would have reported every upload as landed, including the
    # ones that never did.
    page = _StubPage(["done", "done", "done"], thumbnail_appears=False, thumbnail_baseline=1)
    ticks = iter([0.0, 1.0, 2.0, 3.0])
    _, attached = _ask(page, images=[PNG], upload_timeout_s=2, now=lambda: next(ticks, 99.0))

    assert attached is False


def test_a_signed_out_page_fails_with_the_reason_not_a_selector_timeout():
    # A signed-out chatgpt.com serves a placeholder shell with no composer at
    # all. That is a sign-in problem, and the error has to say so rather than
    # sending the operator to retune a selector that was never wrong.
    page = _StubPage(["done"], missing={chatgpt_web.COMPOSER_SEL})

    with pytest.raises(ChatGptWebError, match="signed-out"):
        _ask(page)

    # Nothing was typed or sent into a page that was not ready.
    assert page.events == []


def test_a_vanished_stop_button_ends_the_wait_before_text_stability_can():
    # Measured live: the stop button went at 7.89s and text stability would not
    # have confirmed until 8.92s. Ending on the button saves that second, so it
    # has to win over the stability count, not merely agree with it.
    page = _StubPage(["answer", "answer", "answer", "answer", "answer"],
                     streaming=[True, True, False])
    reply, _ = ask_page(page, "問1", poll_s=0, stable_polls=99, sleep=lambda _s: None)

    assert reply == "answer"


def test_a_missing_stop_button_still_falls_back_to_text_stability():
    # The selector is OpenAI's. If it moves, the reply must still be returned
    # rather than waiting out the full timeout.
    page = _StubPage(["answer", "answer", "answer"], streaming=[])
    reply, _ = ask_page(page, "問1", poll_s=0, stable_polls=2, sleep=lambda _s: None)

    assert reply == "answer"


def test_cdp_probe_reports_unavailable_rather_than_raising():
    # Closed port: ready() must answer False, not blow up a pre-flight.
    assert cdp_available("http://127.0.0.1:9", timeout=0.2) is None


class _FakeClient:
    """Stands in for the browser; records the prompt the solver would send."""

    model = "chatgpt-web"

    def __init__(self, payload, *, attached=None):
        self.payload = payload
        self.seen = {}
        self.last_image_attached = attached

    def complete_json(self, *, system, prompt, image=None, images=None):
        self.seen = {"system": system, "prompt": prompt, "image": image, "images": images}
        return json.loads(self.payload)


def test_answer_only_result_matches_the_api_adapter_shape():
    client = _FakeClient('{"status":"ready","answer":"③","missing_material":""}')
    solver = ChatGptWebSolver(client=client)

    result = solver.solve(
        question=Question(body_text="問1 正しいものを選べ", subject="国語", answer_only=True)
    )

    assert result.answer == "③"
    assert result.extras["answer_status"] == "ready"
    assert result.extras["source"] == "chatgpt-web"
    # The answer-sheet rule has to reach the chat, or it replies like a tutor.
    assert "only what belongs on" in client.seen["system"].lower()
    # No page on this question, so nothing to attach and nothing to report.
    assert client.seen["images"] == []
    assert "image_attached" not in result.extras


def test_the_page_image_reaches_the_browser_as_bytes_and_is_recorded(tmp_path):
    page_png = tmp_path / "p01.png"
    page_png.write_bytes(PNG)
    client = _FakeClient('{"status":"ready","answer":"60度"}', attached=True)
    solver = ChatGptWebSolver(client=client)

    result = solver.solve(
        question=Question(
            body_text="問3 図の角度を求めよ",
            image_path=str(page_png),
            subject="数学",
            answer_only=True,
        )
    )

    # Figure and OCR text travel as two parts, exactly as the API solvers send them.
    assert client.seen["images"] == [PNG]
    assert "問3" in client.seen["prompt"]
    assert result.extras["image_attached"] is True


def test_an_unconfirmed_upload_is_visible_on_the_result(tmp_path):
    # A diagram answer that turns out wrong must be diagnosable: this says
    # whether the figure was confirmed to have reached the model.
    page_png = tmp_path / "p02.png"
    page_png.write_bytes(PNG)
    solver = ChatGptWebSolver(
        client=_FakeClient('{"status":"ready","answer":"60度"}', attached=False)
    )

    result = solver.solve(
        question=Question(body_text="問4", image_path=str(page_png), answer_only=True)
    )

    assert result.extras["image_attached"] is False


def test_unreadable_material_returns_needs_input_with_an_empty_answer():
    client = _FakeClient(
        '{"status":"needs_input","answer":"","missing_material":"図1が読めない"}'
    )
    solver = ChatGptWebSolver(client=client)

    result = solver.solve(question=Question(body_text="問2", answer_only=True))

    assert result.answer == ""
    assert result.extras["answer_status"] == "needs_input"
    assert "図1" in result.extras["missing_material"]


def test_every_page_of_a_multi_page_daimon_is_attached(tmp_path):
    # The defect this guards: a 大問 spanning pages was sent with only its
    # starting-page image, so a question about a figure on a later page was
    # asked about a diagram the model never received.
    pages = []
    for i, data in enumerate((PNG, JPEG, PNG)):
        f = tmp_path / f"p{i:02d}.png"
        f.write_bytes(data)
        pages.append(str(f))
    client = _FakeClient('{"status":"ready","answer":"70°"}', attached=True)

    ChatGptWebSolver(client=client).solve(
        question=Question(
            body_text="第2問 図2の角を求めよ",
            image_path=pages[0],
            image_paths=pages,
            answer_only=True,
        )
    )

    assert client.seen["images"] == [PNG, JPEG, PNG]


def test_a_single_image_path_still_works_without_image_paths(tmp_path):
    # Back-compat: questions built the old way carry their one page.
    f = tmp_path / "only.png"
    f.write_bytes(PNG)
    client = _FakeClient('{"status":"ready","answer":"x=2"}', attached=True)

    ChatGptWebSolver(client=client).solve(
        question=Question(body_text="問1", image_path=str(f), answer_only=True)
    )

    assert client.seen["images"] == [PNG]


def test_an_unreadable_page_is_skipped_rather_than_failing_the_solve(tmp_path):
    good = tmp_path / "good.png"
    good.write_bytes(PNG)
    client = _FakeClient('{"status":"ready","answer":"70°"}', attached=True)

    ChatGptWebSolver(client=client).solve(
        question=Question(
            body_text="第2問",
            image_paths=[str(good), str(tmp_path / "gone.png")],
            answer_only=True,
        )
    )

    assert client.seen["images"] == [PNG]


def test_a_partial_upload_is_not_reported_as_attached():
    # Three pages queued, only two thumbnails ever appear: some page did not
    # make it, and the result must not claim the figures were delivered.
    page = _StubPage(["done", "done", "done"], thumbnail_appears=False)
    ticks = iter([0.0, 1.0, 2.0, 3.0])
    _, attached = _ask(
        page, images=[PNG, JPEG, PNG], upload_timeout_s=2, now=lambda: next(ticks, 99.0)
    )

    assert attached is False
    # All three went out in ONE set_input_files call, so page order is kept.
    uploads = [payload for kind, payload in page.events if kind == "upload"]
    assert len(uploads) == 1


def test_a_thinking_placeholder_is_never_returned_as_the_answer():
    """Measured failure: 4 of 5 long prompts came back as the literal '思考中'.

    A reasoning model shows that placeholder while the stop button is still
    present, and it holds still for over a second -- long enough for the
    text-stability rule to confirm it. Then the turn goes briefly EMPTY before
    the real answer streams in. Nothing visible while the stop button exists
    may end the wait.
    """
    page = _StubPage(
        # Exactly the observed sequence: placeholder, blank, then the answer.
        ["思考中", "思考中", "思考中", "", "", '{"status":"ready","answer":"70度"}'],
        streaming=[True, True, True, True, True, True, False],
    )

    reply, _ = ask_page(page, "第1問", poll_s=0, stable_polls=2, sleep=lambda _s: None)

    assert reply == '{"status":"ready","answer":"70度"}'


def test_a_pause_inside_the_stream_does_not_end_the_wait():
    # Streaming stalls mid-answer. The partial text repeats, but the stop
    # button is still there, so it is not the answer yet.
    page = _StubPage(
        ["解答は", "解答は", "解答は", "解答は 70度"],
        streaming=[True, True, True, True, False],
    )

    reply, _ = ask_page(page, "第1問", poll_s=0, stable_polls=2, sleep=lambda _s: None)

    assert reply == "解答は 70度"


class _FlakyContext:
    """Hands out stub pages: the scripted ones first, then a good one."""

    def __init__(self, pages):
        self.queue = list(pages)
        self.handed = []

    def new_page(self):
        page = self.queue.pop(0) if self.queue else _StubPage(["ok", "ok", "ok"])
        self.handed.append(page)
        return page


def test_an_unconfirmed_upload_is_retried_in_a_fresh_chat(monkeypatch):
    """Measured over 16 consecutive solves: one upload never confirmed in 60s.

    Sending without the figure does not raise -- it answers the wrong question
    or returns needs_input. That has to be retried, not accepted.
    """
    monkeypatch.setattr(chatgpt_web, "RETRY_BACKOFF_S", 0)
    monkeypatch.setattr(chatgpt_web, "UPLOAD_TIMEOUT_S", 0)
    monkeypatch.setattr(chatgpt_web, "POLL_S", 0)
    bad = (_StubPage(["nope", "nope", "nope"], thumbnail_appears=False))
    good = (_StubPage(["70度", "70度", "70度"]))
    ctx = _FlakyContext([bad, good])
    client = chatgpt_web.ChatGptWebClient()

    reply = client._ask_with_retries(ctx, "第2問", [PNG])

    assert reply == "70度"
    assert client.last_image_attached is True
    assert len(ctx.handed) == 2, "the retry must use a fresh chat, not the same one"


def test_a_page_that_never_becomes_usable_is_retried_then_reported(monkeypatch):
    monkeypatch.setattr(chatgpt_web, "RETRY_BACKOFF_S", 0)
    monkeypatch.setattr(chatgpt_web, "ATTEMPTS", 2)
    monkeypatch.setattr(chatgpt_web, "READY_TIMEOUT_S", 0)
    dead = [(_StubPage(["x"], missing={chatgpt_web.COMPOSER_SEL})) for _ in range(2)]
    ctx = _FlakyContext(dead)

    with pytest.raises(ChatGptWebError, match="failed 2 times"):
        chatgpt_web.ChatGptWebClient()._ask_with_retries(ctx, "第2問", [])

    assert len(ctx.handed) == 2


def test_the_last_attempt_accepts_an_unconfirmed_upload_rather_than_losing_the_answer(
    monkeypatch,
):
    # If the thumbnail selector has moved for good, retrying forever helps
    # nobody. The final attempt returns the reply and records the doubt.
    monkeypatch.setattr(chatgpt_web, "RETRY_BACKOFF_S", 0)
    monkeypatch.setattr(chatgpt_web, "ATTEMPTS", 2)
    monkeypatch.setattr(chatgpt_web, "UPLOAD_TIMEOUT_S", 0)
    monkeypatch.setattr(chatgpt_web, "POLL_S", 0)
    pages = [
        (_StubPage(["70度", "70度", "70度"], thumbnail_appears=False))
        for _ in range(2)
    ]
    client = chatgpt_web.ChatGptWebClient()

    reply = client._ask_with_retries(_FlakyContext(pages), "第2問", [PNG])

    assert reply == "70度"
    assert client.last_image_attached is False
