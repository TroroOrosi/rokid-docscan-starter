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

import io
import itertools

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


@pytest.fixture(autouse=True)
def _reset_throttle_streak(tmp_path, monkeypatch):
    """The slow-generation brake is process state; a test must not inherit it.

    Several tests drive the page with a jumping fake clock, which reads as a
    slow generation. Real runs use the real clock, so only here does the streak
    need clearing between cases.
    """
    from app import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    chatgpt_web._slow_streak = 0
    yield
    chatgpt_web._slow_streak = 0


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
        if self._selector == chatgpt_web.SEND_SEL:
            self._page.turns += 1
        if self._selector == chatgpt_web.NEW_CHAT_SEL:
            self._page.turns = 0

    def fill(self, text):
        self._page.events.append(("fill", text))

    def set_input_files(self, payload):
        self._page.events.append(("upload", payload))
        self._page.uploads.append(payload)
        self._page.upload_selectors.append(self._selector)
        # Scripted per attach, so a retry can behave differently from the
        # attempt before it: the retry reuses this same page now.
        if self._page.next_attach_succeeds():
            self._page.confirmed_files += len(payload) if isinstance(payload, list) else 1

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
            return self._page.thumbnail_baseline + self._page.confirmed_files
        if self._selector == chatgpt_web.NEW_CHAT_SEL:
            return 1
        if self._selector == chatgpt_web.SEND_SEL:
            # The real composer has one, and it is what submits: on the mobile
            # web layout Enter only inserts a newline.
            return 0 if self._selector in self._page.missing else 1
        if self._selector == chatgpt_web.ASSISTANT_SEL:
            return self._page.turns if self._page.replies else 0
        return len(self._page.replies)

    @property
    def last(self):
        return self

    @property
    def first(self):
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
        if key == "Enter":
            self._page.turns += 1


class _StubPage:
    """Minimal stand-in for a Playwright page: the calls ask_page actually makes."""

    url = "https://chatgpt.com/"

    def __init__(self, reply_frames, *, thumbnail_appears=True, thumbnail_baseline=1,
                 missing=(), streaming=()):
        self.replies = reply_frames
        self.turns = 0
        self.events = []
        self.uploads = []
        self.upload_selectors = []
        self.thumbnail_script = (
            list(thumbnail_appears) if isinstance(thumbnail_appears, (list, tuple)) else None
        )
        self.confirmed_files = 0
        self.streaming = list(streaming)
        self.stop_poll = 0
        self.thumbnail_appears = thumbnail_appears
        self.thumbnail_baseline = thumbnail_baseline
        self.missing = set(missing)
        self.poll = 0
        self.keyboard = _Keyboard(self)

    def next_attach_succeeds(self) -> bool:
        if self.thumbnail_script is None:
            return self.thumbnail_appears
        return self.thumbnail_script.pop(0) if self.thumbnail_script else False

    def goto(self, *args, **kwargs):
        self.events.append(("goto", args[0] if args else ""))

    def close(self):
        self.events.append(("close", None))

    def locator(self, selector):
        return _Locator(self, selector)


def _kinds(page):
    """Event kinds with the send click named as such, so a sequence reads."""
    return [
        "send" if (kind == "click" and value == chatgpt_web.SEND_SEL) else kind
        for kind, value in page.events
    ]


def _sends(page):
    """Every submitted message. The button is normal; Enter is the fallback."""
    return [k for k in _kinds(page) if k in ("send", "press")]


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
    assert _kinds(page) == ["wait_for", "click", "fill", "send"]


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
    assert _kinds(page) == ["wait_for", "upload", "click", "fill", "send"]
    # The text part carries no image bytes.
    fills = [value for kind, value in page.events if kind == "fill"]
    assert fills == ["問3 図の角度を求めよ"]


def test_no_image_means_no_upload_at_all():
    page = _StubPage(["done", "done", "done"])
    _, attached = _ask(page, images=None)

    assert attached is None
    assert _kinds(page) == ["wait_for", "click", "fill", "send"]


def test_an_unconfirmed_upload_never_sends():
    page = _StubPage(["done"], thumbnail_appears=False)
    ticks = iter([0.0, 1.0, 2.0, 3.0])
    with pytest.raises(ChatGptWebError, match="not confirmed"):
        _ask(page, images=[PNG], upload_timeout_s=2, now=lambda: next(ticks, 99.0))
    assert not _sends(page)


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
    with pytest.raises(ChatGptWebError, match="not confirmed"):
        _ask(page, images=[PNG], upload_timeout_s=2, now=lambda: next(ticks, 99.0))
    assert not _sends(page)


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

    def complete_json(self, *, system, prompt, image=None, images=None, audio=None,
                      bundle_pdf=None, chat_key=None, files=None):
        self.seen = {
            "system": system,
            "prompt": prompt,
            "image": image,
            "images": images,
            "audio": audio,
            "bundle_pdf": bundle_pdf,
            "chat_key": chat_key,
            "files": files() if callable(files) else files,
        }
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
            question_no="問3",
            image_path=str(page_png),
            subject="数学",
            answer_only=True,
        )
    )

    # Only the locator is typed; local OCR is not source material for GPT.
    assert client.seen["images"] == [PNG]
    assert "問3" in client.seen["prompt"]
    assert "図の角度を求めよ" not in client.seen["prompt"]
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


def test_an_unreadable_page_blocks_the_solve(tmp_path):
    good = tmp_path / "good.png"
    good.write_bytes(PNG)
    client = _FakeClient('{"status":"ready","answer":"70°"}', attached=True)

    with pytest.raises(ValueError, match="image"):
        ChatGptWebSolver(client=client).solve(
            question=Question(
                body_text="第2問",
                image_paths=[str(good), str(tmp_path / "gone.png")],
                answer_only=True,
            )
        )
    assert not client.seen


def test_a_partial_upload_is_not_reported_as_attached():
    # Three pages queued, only two thumbnails ever appear: some page did not
    # make it, and the result must not claim the figures were delivered.
    page = _StubPage(["done", "done", "done"], thumbnail_appears=False)
    ticks = iter([0.0, 1.0, 2.0, 3.0])
    with pytest.raises(ChatGptWebError, match="not confirmed"):
        _ask(page, images=[PNG, JPEG, PNG], upload_timeout_s=2, now=lambda: next(ticks, 99.0))
    assert not _sends(page)
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


class _OneTabContext:
    """A browser context holding exactly one reusable chatgpt.com tab."""

    def __init__(self, page):
        self.page = page
        self.pages = [page]
        self.opened = 0

    def new_page(self):
        self.opened += 1
        return self.page


def _clicks(page, selector):
    return [v for kind, v in page.events if kind == "click" and v == selector]


def test_a_question_reuses_the_open_tab_instead_of_loading_the_site_again():
    """Reloading chatgpt.com per question hammers the site for no benefit.

    It was also measured destabilising the browser partway through a run of
    subjects. A new chat is a click on the sidebar control; the only navigation
    is the one that opens the tab in the first place.
    """
    page = _StubPage(["70度", "70度", "70度"])
    ctx = _OneTabContext(page)

    chatgpt_web.ChatGptWebClient()._ask_with_retries(ctx, "第2問", [])

    assert ctx.opened == 0, "an already-open chatgpt.com tab must be reused"
    assert not [k for k, _ in page.events if k == "goto"], "no page load per question"
    assert _clicks(page, chatgpt_web.NEW_CHAT_SEL), "the next question needs its own chat"


def test_an_unconfirmed_upload_is_retried_in_a_new_chat_on_the_same_tab(monkeypatch):
    """Measured over 16 consecutive solves: one upload never confirmed in 60s.

    Sending without the figure does not raise -- it answers the wrong question
    or returns needs_input. That has to be retried, in a new chat but the SAME
    tab, and the retry must not reload the site either.
    """
    monkeypatch.setattr(chatgpt_web, "RETRY_BACKOFF_S", 0)
    monkeypatch.setattr(chatgpt_web, "UPLOAD_TIMEOUT_S", 0)
    monkeypatch.setattr(chatgpt_web, "POLL_S", 0)
    # The first attach never shows a thumbnail; the second one does.
    page = _StubPage(["70度", "70度", "70度"], thumbnail_appears=[False, True])
    client = chatgpt_web.ChatGptWebClient()

    reply = client._ask_with_retries(_OneTabContext(page), "第2問", [PNG])

    assert reply == "70度"
    assert client.last_image_attached is True
    assert len([k for k, _ in page.events if k == "upload"]) == 2
    assert len(_clicks(page, chatgpt_web.NEW_CHAT_SEL)) == 2
    assert not [k for k, _ in page.events if k == "goto"]


def test_a_page_that_never_becomes_usable_is_retried_then_reported(monkeypatch):
    monkeypatch.setattr(chatgpt_web, "RETRY_BACKOFF_S", 0)
    monkeypatch.setattr(chatgpt_web, "ATTEMPTS", 2)
    monkeypatch.setattr(chatgpt_web, "READY_TIMEOUT_S", 0)
    page = _StubPage(["x"], missing={chatgpt_web.COMPOSER_SEL})

    with pytest.raises(ChatGptWebError, match="failed 2 times"):
        chatgpt_web.ChatGptWebClient()._ask_with_retries(_OneTabContext(page), "第2問", [])


def test_even_the_last_attempt_rejects_unconfirmed_sources(monkeypatch):
    monkeypatch.setattr(chatgpt_web, "RETRY_BACKOFF_S", 0)
    monkeypatch.setattr(chatgpt_web, "ATTEMPTS", 2)
    monkeypatch.setattr(chatgpt_web, "UPLOAD_TIMEOUT_S", 0)
    page = _StubPage(["answer"], thumbnail_appears=False)
    with pytest.raises(ChatGptWebError, match="not confirmed"):
        chatgpt_web.ChatGptWebClient()._ask_with_retries(_OneTabContext(page), "question", [PNG])
    assert not _sends(page)


def test_an_unconfirmed_upload_costs_no_generation(monkeypatch):
    """The retry must happen BEFORE the question is asked, not after.

    The first order attached, asked, threw the answer away and asked again, so
    a thumbnail selector that had moved cost three generations per question.
    That is the load that got the account rate-limited, so it is pinned here:
    two upload attempts, exactly one message sent.
    """
    monkeypatch.setattr(chatgpt_web, "RETRY_BACKOFF_S", 0)
    monkeypatch.setattr(chatgpt_web, "UPLOAD_TIMEOUT_S", 0)
    monkeypatch.setattr(chatgpt_web, "POLL_S", 0)
    page = _StubPage(["70度", "70度", "70度"], thumbnail_appears=[False, True])

    chatgpt_web.ChatGptWebClient()._ask_with_retries(_OneTabContext(page), "第2問", [PNG])

    assert len([k for k, _ in page.events if k == "upload"]) == 2
    assert len(_sends(page)) == 1, "one question, one message"


def test_a_usage_limit_reply_is_never_retried(monkeypatch):
    """A throttled account is refused in the message body, not by an exception.

    Retrying it opens another chat and asks again, which is how a slowdown
    turned into a block. It ends the question instead, still as a
    ChatGptWebError so solve_with_fallback drops to the next tier.
    """
    monkeypatch.setattr(chatgpt_web, "POLL_S", 0)
    monkeypatch.setattr(chatgpt_web, "STABLE_POLLS", 1)
    monkeypatch.setattr(chatgpt_web, "RETRY_BACKOFF_S", 0)
    limit = "使用制限に達しました。しばらくしてからもう一度お試しください。"
    page = _StubPage([limit, limit])

    with pytest.raises(chatgpt_web.ChatGptWebRateLimit):
        chatgpt_web.ChatGptWebClient()._ask_with_retries(_OneTabContext(page), "第2問", [])

    assert len(_sends(page)) == 1, "no retry after a limit"
    assert isinstance(chatgpt_web.ChatGptWebRateLimit("x"), ChatGptWebError)


def test_two_slow_generations_in_a_row_refuse_the_next_send(monkeypatch):
    """The documented throttle signal is the per-question time, so enforce it.

    Measured before the block: 7-13s clean, then 43s, 48s, 130s while the run
    kept going. The brake stops the third send rather than leaving it to the
    operator to notice.
    """
    monkeypatch.setattr(chatgpt_web, "SLOW_S", 1)
    monkeypatch.setattr(chatgpt_web, "SLOW_STREAK", 2)
    ticks = itertools.count(0, 10)

    def one_slow_solve():
        return chatgpt_web.send_and_read(
            _StubPage(["x=2", "x=2"]),
            "問1",
            poll_s=0,
            stable_polls=1,
            sleep=lambda _s: None,
            now=lambda: next(ticks),
        )

    assert one_slow_solve() == "x=2"
    assert one_slow_solve() == "x=2"
    with pytest.raises(chatgpt_web.ChatGptWebRateLimit, match="longer than"):
        one_slow_solve()


def test_a_fast_generation_clears_the_slow_streak(monkeypatch):
    monkeypatch.setattr(chatgpt_web, "SLOW_S", 1)
    monkeypatch.setattr(chatgpt_web, "SLOW_STREAK", 2)
    chatgpt_web._slow_streak = 1
    ticks = itertools.count(0, 0)

    chatgpt_web.send_and_read(
        _StubPage(["x=2", "x=2"]), "問1", poll_s=0, stable_polls=1,
        sleep=lambda _s: None, now=lambda: next(ticks),
    )

    assert chatgpt_web._slow_streak == 0


def _real_png(colour: int) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (colour, colour, colour)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_the_pages_can_be_bundled_into_one_pdf_upload(monkeypatch):
    """Opt-in: one document instead of one upload per page.

    UNVERIFIED against the live page -- this pins our side only: one payload,
    a PDF through the file input rather than the image-only photo input.
    """
    monkeypatch.setattr(chatgpt_web, "BUNDLE_PDF", True)
    page = _StubPage(["70度"])

    assert chatgpt_web.attach_images(page, [_real_png(10), _real_png(200)]) is True

    (payload,) = page.uploads
    assert len(payload) == 1, "two pages, one upload"
    assert payload[0]["name"].endswith(".pdf")
    assert payload[0]["mimeType"] == "application/pdf"
    assert payload[0]["buffer"].startswith(b"%PDF")
    assert page.upload_selectors == [chatgpt_web.FILE_UPLOAD_SEL]


# --- one chat per 科目 (CHAT_SCOPE="subject") ---------------------------------


def test_a_subject_scoped_deck_opens_one_chat_not_one_per_question(monkeypatch):
    """The final-test shape: 16 subjects, one chat each, not one per 小問."""
    monkeypatch.setattr(chatgpt_web, "CHAT_SCOPE", "subject")
    monkeypatch.setattr(chatgpt_web, "POLL_S", 0)
    page = _StubPage(["70度", "70度"])
    client = chatgpt_web.ChatGptWebClient()
    ctx = _OneTabContext(page)

    client._ask_with_retries(ctx, "問1", [], chat_key="subject:数学")
    client._ask_with_retries(ctx, "問2", [], chat_key="subject:数学")

    assert len(_clicks(page, chatgpt_web.NEW_CHAT_SEL)) == 1, "one chat for the subject"
    assert len(_sends(page)) == 2, "both questions asked"


def test_the_next_subject_gets_its_own_chat(monkeypatch):
    monkeypatch.setattr(chatgpt_web, "CHAT_SCOPE", "subject")
    monkeypatch.setattr(chatgpt_web, "POLL_S", 0)
    page = _StubPage(["答", "答"])
    client = chatgpt_web.ChatGptWebClient()
    ctx = _OneTabContext(page)

    client._ask_with_retries(ctx, "問1", [], chat_key="subject:数学")
    client._ask_with_retries(ctx, "問1", [], chat_key="subject:物理")

    assert len(_clicks(page, chatgpt_web.NEW_CHAT_SEL)) == 2


def test_a_page_already_in_this_chat_is_not_uploaded_again(monkeypatch):
    """A 大問 is uploaded once per subject, not once per 小問 of it."""
    monkeypatch.setattr(chatgpt_web, "CHAT_SCOPE", "subject")
    monkeypatch.setattr(chatgpt_web, "POLL_S", 0)
    page = _StubPage(["70度", "70度"])
    client = chatgpt_web.ChatGptWebClient()
    ctx = _OneTabContext(page)

    client._ask_with_retries(ctx, "問1", [PNG], chat_key="subject:数学")
    client._ask_with_retries(ctx, "問2", [PNG], chat_key="subject:数学")

    assert len([k for k, _ in page.events if k == "upload"]) == 1, "uploaded once"
    assert client.last_image_attached is True, "still in the chat, so still attached"


def test_a_question_scoped_run_still_opens_a_chat_per_question(monkeypatch):
    # The default has to stay the measured behaviour: no answer of an earlier
    # question becomes context the grader never saw.
    monkeypatch.setattr(chatgpt_web, "CHAT_SCOPE", "question")
    monkeypatch.setattr(chatgpt_web, "POLL_S", 0)
    page = _StubPage(["答", "答"])
    client = chatgpt_web.ChatGptWebClient()
    ctx = _OneTabContext(page)

    client._ask_with_retries(ctx, "問1", [], chat_key=None)
    client._ask_with_retries(ctx, "問2", [], chat_key=None)

    assert len(_clicks(page, chatgpt_web.NEW_CHAT_SEL)) == 2


def test_the_chat_key_comes_from_the_server_never_from_the_detected_subject(monkeypatch):
    """One paper is one chat, and `subject` cannot decide that.

    `subject` is a per-row heuristic. A single 物理基礎 paper was measured
    producing 現代文/物理/化学/数学/地学 across its rows, which keyed five chats
    and re-uploaded the same pages into every one of them.
    """
    scattered = [
        Question(body_text="問1", subject="現代文", chat_key="session:7"),
        Question(body_text="問2", subject="化学", chat_key="session:7"),
        Question(body_text="問3", subject="地学", chat_key="session:7"),
    ]
    monkeypatch.setattr(chatgpt_web, "CHAT_SCOPE", "subject")

    assert {chatgpt_web.chat_key_for(q) for q in scattered} == {"session:7"}

    monkeypatch.setattr(chatgpt_web, "CHAT_SCOPE", "question")
    assert all(chatgpt_web.chat_key_for(q) is None for q in scattered)


# --- listening: the recording travels with the pages -------------------------


def test_a_listening_recording_is_attached_alongside_the_pages():
    """A listening 大問 is the audio AND the question booklet, in one message.

    The transcript alone flattens speaker turns and numbers, so the recording
    goes too. It cannot use the photo input (accept="image/*"), so it takes the
    general file input while the pages keep theirs.
    """
    page = _StubPage(["答"])

    assert chatgpt_web.attach_images(page, [PNG], audio=("rec.mp3", b"ID3rec")) is True

    assert page.upload_selectors == [chatgpt_web.FILE_INPUT_SEL, chatgpt_web.FILE_UPLOAD_SEL]
    assert page.uploads[1][0]["mimeType"] == "audio/mpeg"
    assert page.uploads[1][0]["name"] == "rec.mp3"


def test_an_audio_only_question_still_attaches():
    page = _StubPage(["答"])

    assert chatgpt_web.attach_images(page, [], audio=("rec.m4a", b"m4a")) is True

    assert page.upload_selectors == [chatgpt_web.FILE_UPLOAD_SEL]
    assert page.uploads[0][0]["mimeType"] == "audio/mp4"


def test_the_recording_reaches_the_solver_from_the_question(tmp_path):
    recording = tmp_path / "listening.mp3"
    recording.write_bytes(b"ID3 recorded")
    client = _FakeClient('{"status":"ready","answer":"②"}', attached=True)

    ChatGptWebSolver(client=client).solve(
        question=Question(
            body_text="問1 放送を聞いて答えよ",
            subject="英語",
            audio_path=str(recording),
            answer_only=True,
        )
    )

    assert client.seen["audio"] == ("listening.mp3", b"ID3 recorded")


def test_document_route_counts_audio_and_reuses_confirmed_files(tmp_path, monkeypatch):
    monkeypatch.setattr(chatgpt_web, "POLL_S", 0)
    page_path = tmp_path / "page.png"
    page_path.write_bytes(_real_png(80))
    recording = tmp_path / "original.wav"
    recording.write_bytes(b"RIFF original")
    pages = [{"page_number": i+1, "image_path": str(page_path), "ocr_text": f"Question {i+1}"}
             for i in range(40)]
    fake = _FakeClient('{"status":"ready","answer":"2"}', attached=True)
    question = Question(body_text="Question two", question_no="問2", question_id="q9", answer_only=True,
                        document_pages=pages, document_id="1", page_numbers=[2],
                        audio_path=str(recording), audio_transcript="[30000..31000ms] Question two", chat_key="session:1")
    ChatGptWebSolver(client=fake).solve(question=question)
    files, first_key = fake.seen["files"], fake.seen["chat_key"]
    assert len(files) <= 20
    assert len(files) == 15 and files[-2]["name"] == "page040.png", "shared pages cannot be lost"
    assert files[0]["mimeType"].startswith("image/") and files[-1]["name"] == "original.wav"
    assert all(f["name"] != "document.md" for f in files)
    assert "Question two" not in fake.seen["prompt"] and "q9" in fake.seen["prompt"]
    question.body_text = "corrected OCR"
    question.audio_transcript = "corrected ASR"
    pages[0]["ocr_text"] = "corrected page OCR"
    ChatGptWebSolver(client=fake).solve(question=question)
    assert fake.seen["chat_key"] == first_key, "local text cannot reset original evidence"
    page_path.write_bytes(_real_png(81))
    ChatGptWebSolver(client=fake).solve(question=question)
    assert fake.seen["chat_key"] != first_key, "retake changes evidence even at the same path"
    first_key = fake.seen["chat_key"]
    recording.write_bytes(b"RIFF corrected original")
    ChatGptWebSolver(client=fake).solve(question=question)
    assert fake.seen["chat_key"] != first_key
    browser = _StubPage(["2", "2"])
    client = chatgpt_web.ChatGptWebClient()
    ctx = _OneTabContext(browser)
    client._ask_with_retries(ctx, "問2", [], files=files, chat_key=first_key)
    count = len([k for k, _ in browser.events if k == "upload"])
    client._ask_with_retries(ctx, "問3", [], files=files, chat_key=first_key)
    assert len([k for k, _ in browser.events if k == "upload"]) == count


def test_confirmed_booklet_is_not_encoded_again_until_chat_changes(monkeypatch):
    monkeypatch.setattr(chatgpt_web, "POLL_S", 0)
    browser = _StubPage(["2", "2"])
    client = chatgpt_web.ChatGptWebClient()
    context = _OneTabContext(browser)
    builds = []

    def prepare():
        builds.append(1)
        return [{"name": "page001.png", "mimeType": "image/png", "buffer": PNG}]

    client._ask_with_retries(context, "問1", [], files=prepare, chat_key="original-1")
    client._ask_with_retries(context, "問2", [], files=prepare, chat_key="original-1")
    assert len(builds) == 1
    browser.url = "https://chatgpt.com/c/operator-changed-chat"
    client._ask_with_retries(context, "問3", [], files=prepare, chat_key="original-1")
    assert len(builds) == 2
    client._ask_with_retries(context, "問3", [], files=prepare, chat_key="retaken-page")
    assert len(builds) == 3


def test_unconfirmed_document_files_never_send_a_question(monkeypatch):
    monkeypatch.setattr(chatgpt_web, "RETRY_BACKOFF_S", 0)
    monkeypatch.setattr(chatgpt_web, "UPLOAD_TIMEOUT_S", 0)
    monkeypatch.setattr(chatgpt_web, "POLL_S", 0)
    page = _StubPage(["answer"], thumbnail_appears=[False] * 20, thumbnail_baseline=0)
    with pytest.raises(chatgpt_web.ChatGptWebError):
        chatgpt_web.ChatGptWebClient()._ask_with_retries(_OneTabContext(page), "question", [],
                files=lambda: [{"name": "page001.png", "mimeType": "image/png", "buffer": PNG}])
    assert not _sends(page)


def test_an_unreadable_recording_blocks_the_solve(tmp_path):
    client = _FakeClient('{"status":"ready","answer":"②"}')

    with pytest.raises(ValueError, match="audio"):
        ChatGptWebSolver(client=client).solve(
            question=Question(
                body_text="問1", subject="英語", audio_path=str(tmp_path / "gone.mp3"),
                answer_only=True,
            )
        )
    assert not client.seen


def test_the_send_button_submits_and_enter_is_only_the_fallback():
    """Enter is a NEWLINE on the mobile web composer, not a submit.

    Measured 2026-09-15 on F-51F: three attempts pressed Enter, each left
    another blank line in the composer, and none of them sent the question.
    """
    page = _StubPage(["done", "done", "done"])
    assert chatgpt_web.submit(page) == "button"
    assert _kinds(page) == ["send"]

    moved = _StubPage(["done", "done", "done"], missing=(chatgpt_web.SEND_SEL,))
    assert chatgpt_web.submit(moved) == "enter"
    assert [value for kind, value in moved.events if kind == "press"] == ["Enter"]


def test_a_write_that_lands_on_nothing_is_written_again():
    """React replaces the file input under us on the mobile composer.

    Measured 2026-09-15 on F-51F: a node marked the instant `start_new_chat`
    returned was REPLACED 0.5s later, and the bytes written to it disappeared
    with no error. Retrying the write costs no generation.
    """
    page = _StubPage(["done"], thumbnail_appears=[False, True], thumbnail_baseline=0)
    assert chatgpt_web.attach_images(page, [PNG], sleep=lambda _s: None, now=_ticks()) is True
    assert len([k for k in _kinds(page) if k == "upload"]) == 2, "wrote twice"


def test_a_slow_upload_that_landed_is_never_written_twice():
    """A second write would attach the same page again and ask about a duplicate."""
    page = _StubPage(["done"], thumbnail_appears=[True], thumbnail_baseline=0)
    page.confirmed_files = 0
    chatgpt_web.attach_images(page, [PNG, PNG], sleep=lambda _s: None, now=_ticks())
    assert len([k for k in _kinds(page) if k == "upload"]) == 1, "one write, then wait"


def _ticks():
    """A monotonic clock that always advances, so each window closes."""
    state = {"t": 0.0}

    def now():
        state["t"] += 1.0
        return state["t"]

    return now


def test_uncertain_submit_is_never_retried_even_by_a_new_client(monkeypatch, tmp_path):
    from app import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(chatgpt_web, "RETRY_BACKOFF_S", 0)
    calls = []
    def uncertain(page):
        calls.append(1)
        raise TimeoutError("submission reply lost")
    monkeypatch.setattr(chatgpt_web, "submit", uncertain)
    ctx = _OneTabContext(_StubPage(["answer"]))
    for _ in range(2):
        with pytest.raises(ChatGptWebError):
            chatgpt_web.ChatGptWebClient()._ask_with_retries(ctx, "question", [])
    assert len(calls) == 1, "a send with unknown outcome must not spend another generation"


def test_other_browser_client_is_rejected_before_any_page_operation(monkeypatch, tmp_path):
    from app import config
    from app.browser_guard import BrowserGuard
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    page = _StubPage(["answer"])
    with BrowserGuard(tmp_path):
        with pytest.raises(ChatGptWebError):
            chatgpt_web.ChatGptWebClient()._ask_with_retries(_OneTabContext(page), "question", [])
    assert page.events == []


def test_navigation_invalidates_attachment_reuse(monkeypatch):
    monkeypatch.setattr(chatgpt_web, "POLL_S", 0)
    page = _StubPage(["answer"])
    ctx = _OneTabContext(page)
    client = chatgpt_web.ChatGptWebClient()
    client._ask_with_retries(ctx, "first", [PNG], chat_key="same-input")
    page.url = "https://chatgpt.com/c/some-other-chat"
    client._ask_with_retries(ctx, "second", [PNG], chat_key="same-input")
    assert len(page.uploads) == 2


def test_previous_assistant_reply_is_not_the_new_answer(monkeypatch):
    page = _StubPage(["previous answer"])
    original_count = _Locator.count
    def fixed_count(locator):
        if locator._selector == chatgpt_web.ASSISTANT_SEL:
            return 1  # The old assistant turn remains; no new turn ever arrives.
        return original_count(locator)
    monkeypatch.setattr(_Locator, "count", fixed_count)
    ticks = itertools.count(0, 0.1)
    with pytest.raises(ChatGptWebError):
        chatgpt_web.send_and_read(page, "next question", poll_s=0,
                                 stable_polls=1, timeout_s=2,
                                 now=lambda: next(ticks), sleep=lambda _: None)


def test_a_later_identical_submission_gets_a_distinct_reconciliation_id(monkeypatch, tmp_path):
    from app import config
    from app.browser_guard import BrowserGuard
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(chatgpt_web, "submit", lambda page: (_ for _ in ()).throw(TimeoutError()))
    ids = []
    for _ in range(2):
        with pytest.raises(ChatGptWebError):
            chatgpt_web.ChatGptWebClient()._ask_with_retries(_OneTabContext(_StubPage(["a"])), "same", [])
        with BrowserGuard(tmp_path) as guard:
            ids.append(guard.status()["request_id"])
            guard.acknowledge(ids[-1])
    assert ids[0] != ids[1], "an old acknowledgment must not clear a later submission"
