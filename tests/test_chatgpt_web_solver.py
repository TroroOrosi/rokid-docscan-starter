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
    locator_prompt,
)


PNG = b"\x89PNG\r\n\x1a\n" + b"fake page image"
JPEG = b"\xff\xd8\xff" + b"fake page photo"


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Browser state under tmp_path, and no real sleep between page polls."""
    from app import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(chatgpt_web, "POLL_S", 0)


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
            self._page.sent()
        if self._selector == chatgpt_web.NEW_CHAT_SEL:
            self._page.turns = 0
            self._page.url = "https://chatgpt.com/"

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
            self._page.sent()


class _StubPage:
    """Minimal stand-in for a Playwright page: the calls ask_page actually makes."""

    url = "https://chatgpt.com/"
    #: False for a page whose chats never get a /c/ address.
    addresses = True

    def __init__(self, reply_frames, *, thumbnail_appears=True, thumbnail_baseline=1,
                 missing=(), streaming=(True, False)):
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
        self.chats = 0
        self.keyboard = _Keyboard(self)

    def sent(self):
        # chatgpt.com moves a new chat to /c/<id> once its first message is sent;
        # later messages in that chat leave the URL alone.
        self.turns += 1
        self.stop_poll = 0  # each reply runs its own stop-button script
        if self.addresses and "/c/" not in self.url:
            self.chats += 1
            self.url = f"https://chatgpt.com/c/chat-{self.chats}"

    def next_attach_succeeds(self) -> bool:
        if self.thumbnail_script is None:
            return self.thumbnail_appears
        return self.thumbnail_script.pop(0) if self.thumbnail_script else False

    def goto(self, *args, **kwargs):
        self.events.append(("goto", args[0] if args else ""))
        if args:
            self.url = args[0]

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
    return ask_page(page, text, poll_s=0, **kw)


def test_without_a_stop_button_only_the_whole_json_ends_the_wait():
    # A half-streamed reply already holds complete inner objects; only the
    # object with the expected top-level keys is the finished answer.
    page = _StubPage(["解", '{"status":"ready","diagrams":[{"alt":"a"}', '{"status":"ready",',
                      '{"status":"ready","answer":"x=2"}'], streaming=[])
    assert _ask(page, expect=("answer",)) == ('{"status":"ready","answer":"x=2"}', None)


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
    page = _StubPage([f"partial {i}" for i in range(50)], streaming=[True])
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


def test_a_stop_button_gone_for_good_returns_a_reply_that_is_not_the_json():
    # A refusal in prose is finished too. Returned once the button has stayed
    # gone, so the parse fails visibly instead of the wait running 150 minutes.
    page = _StubPage(["I cannot read the pages."], streaming=[True, False])
    reply, _ = ask_page(page, "全問", poll_s=0, expect=("questions",), sleep=lambda _s: None)

    assert reply == "I cannot read the pages."
    assert page.poll == 1 + chatgpt_web.SETTLE_POLLS


def test_a_blink_of_the_stop_button_does_not_return_half_the_json():
    # Between thinking and writing the button can vanish for a frame. The half
    # reply already holds a complete inner object; it must not be returned.
    page = _StubPage(['{"questions":[{"label":"問1"},', '{"questions":[{"label":"問1"},',
                      '{"questions":[{"label":"問1"},', '{"questions":[{"label":"問1"}]}'],
                     streaming=[True, False, True, False])
    reply, _ = ask_page(page, "全問", poll_s=0, expect=("questions",), sleep=lambda _s: None)

    assert reply == '{"questions":[{"label":"問1"}]}'


def test_a_send_that_starts_no_reply_is_reported_not_waited_out():
    # A limit banner or an error outside the reply: no turn, no stop button.
    page = _StubPage([], streaming=[])
    ticks = iter([0.0, 0.0, 60.0, chatgpt_web.REPLY_START_S + 1])
    with pytest.raises(ChatGptWebError, match="no reply started"):
        ask_page(page, "全問", poll_s=0, expect=("questions",), sleep=lambda _s: None,
                 now=lambda: next(ticks, 9999.0))


def test_a_held_thinking_placeholder_is_not_returned_without_a_stop_button():
    """9/29: the next message went out while replies were still being worked on.

    With the stop button missing (a moved selector), holding still for many
    polls says nothing; only the whole expected JSON ends the wait.
    """
    page = _StubPage(["思考中"] * 40 + ['{"questions":[]}'], streaming=[])
    reply, _ = ask_page(page, "全問", poll_s=0, expect=("questions",), sleep=lambda _s: None)

    assert reply == '{"questions":[]}'
    assert page.poll == 41


def test_cdp_probe_reports_unavailable_rather_than_raising():
    # Closed port: ready() must answer False, not blow up a pre-flight.
    assert cdp_available("http://127.0.0.1:9", timeout=0.2) is None


def test_locator_prompt_keeps_the_derivation_for_a_written_solution():
    """"説明・理由・見出し・前置きは含めません" would strip a 記述式 math
    proof's own derivation, which is the operator's decision -- it has to be
    on the answer sheet for credit. Same exception as _ANSWER_ONLY_SYSTEM.
    """
    prompt = locator_prompt(Question(question_no="問1"))

    assert "記述式" in prompt
    # Still excludes explanations/headings for everything else.
    assert "説明・理由" in prompt


class _FakeClient:
    """Stands in for the browser; records the prompt the solver would send."""

    model = "chatgpt-web"

    def __init__(self, payload, *, attached=None):
        self.payload = payload
        self.seen = {}
        self.last_image_attached = attached

    def complete_json(self, *, system, prompt, image=None, images=None, audio=None,
                      chat_key=None, files=None, expect=None):
        self.seen = {
            "expect": expect,
            "system": system,
            "prompt": prompt,
            "image": image,
            "images": images,
            "audio": audio,
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

    reply, _ = ask_page(page, "第1問", poll_s=0, sleep=lambda _s: None)

    assert reply == '{"status":"ready","answer":"70度"}'


def test_a_pause_inside_the_stream_does_not_end_the_wait():
    # Streaming stalls mid-answer. The partial text repeats, but the stop
    # button is still there, so it is not the answer yet.
    page = _StubPage(
        ["解答は", "解答は", "解答は", "解答は 70度"],
        streaming=[True, True, True, True, False],
    )

    reply, _ = ask_page(page, "第1問", poll_s=0, sleep=lambda _s: None)

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
    monkeypatch.setattr(chatgpt_web, "RETRY_BACKOFF_S", 0)
    limit = "使用制限に達しました。しばらくしてからもう一度お試しください。"
    page = _StubPage([limit, limit])

    with pytest.raises(chatgpt_web.ChatGptWebRateLimit):
        chatgpt_web.ChatGptWebClient()._ask_with_retries(_OneTabContext(page), "第2問", [])

    assert len(_sends(page)) == 1, "no retry after a limit"
    assert isinstance(chatgpt_web.ChatGptWebRateLimit("x"), ChatGptWebError)


def _real_png(colour: int) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (colour, colour, colour)).save(buffer, format="PNG")
    return buffer.getvalue()


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


def test_the_next_subject_gets_its_own_chat(monkeypatch, tmp_path):
    monkeypatch.setattr(chatgpt_web, "CHAT_SCOPE", "subject")
    monkeypatch.setattr(chatgpt_web, "POLL_S", 0)
    page = _StubPage(["答", "答"])
    client = chatgpt_web.ChatGptWebClient()
    ctx = _OneTabContext(page)

    client._ask_with_retries(ctx, "問1", [], chat_key="subject:数学")
    client._ask_with_retries(ctx, "問1", [], chat_key="subject:物理")

    assert len(_clicks(page, chatgpt_web.NEW_CHAT_SEL)) == 2
    assert not [k for k, _ in page.events if k == "goto"], "a new key is not sent back"
    # Both are kept: the new subject's chat does not replace the old one.
    record = json.loads((tmp_path / "browser-state" / "chats.json").read_text(encoding="utf-8"))
    assert list(record["chats"]) == ["subject:数学", "subject:物理"]


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
    assert len(files) == 15 and files[-2]["name"] == "page040.jpg", "shared pages cannot be lost"
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


def test_confirmed_booklet_is_not_encoded_again_until_the_key_changes(monkeypatch):
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
    # The tab wandering off does not change which chat holds the booklet: the
    # route goes back there, and the booklet is already in it.
    browser.url = "https://chatgpt.com/c/operator-changed-chat"
    client._ask_with_retries(context, "問3", [], files=prepare, chat_key="original-1")
    assert len(builds) == 1
    client._ask_with_retries(context, "問3", [], files=prepare, chat_key="retaken-page")
    assert len(builds) == 2


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


# --- one chat per 科目 survives failures, retries and restarts ------------------
# 9/14: every retry and every restart opened a new chat and re-attached every
# page. A subject's chat, once it exists, is the only place its questions go.


def _gotos(page):
    return [v for kind, v in page.events if kind == "goto"]


def _fast(monkeypatch):
    for name, value in (("POLL_S", 0), ("RETRY_BACKOFF_S", 0), ("UPLOAD_TIMEOUT_S", 0)):
        monkeypatch.setattr(chatgpt_web, name, value)


def _subject_chat(monkeypatch, page, key="subject:数学"):
    """Ask once under ``key`` so a chat exists; return the client and its URL."""
    _fast(monkeypatch)
    client = chatgpt_web.ChatGptWebClient()
    client._ask_with_retries(_OneTabContext(page), "問1", [PNG], chat_key=key)
    assert "/c/" in page.url
    return client, page.url


def test_a_tab_on_another_chat_is_taken_back_to_the_subject_chat(monkeypatch):
    page = _StubPage(["answer", "answer"])
    client, chat = _subject_chat(monkeypatch, page, key="same-input")
    page.url = "https://chatgpt.com/c/some-other-chat"

    client._ask_with_retries(_OneTabContext(page), "second", [PNG], chat_key="same-input")

    assert _gotos(page) == [chat], "navigated back, not a new chat"
    assert len(_clicks(page, chatgpt_web.NEW_CHAT_SEL)) == 1
    assert len(page.uploads) == 1, "the page is already in that chat"
    assert len(_sends(page)) == 2


def test_a_failure_after_the_chat_exists_retries_in_that_chat(monkeypatch):
    # q1 attaches PNG; q2's first write of JPEG never lands, its retry does.
    page = _StubPage(["70度", "70度"], thumbnail_appears=[True, False, True])
    client, chat = _subject_chat(monkeypatch, page)

    reply = client._ask_with_retries(_OneTabContext(page), "問2", [PNG, JPEG],
                                     chat_key="subject:数学")

    assert reply == "70度"
    assert len(_clicks(page, chatgpt_web.NEW_CHAT_SEL)) == 1, "only q1 opened a chat"
    # The retry reloads the chat so a half-attached composer is dropped.
    assert _gotos(page) == [chat]
    assert page.url == chat
    uploaded = [p["buffer"] for payload in page.uploads for p in payload]
    assert uploaded == [PNG, JPEG, JPEG], "the confirmed page is never uploaded again"


def test_a_restarted_server_returns_to_the_recorded_chat(monkeypatch, tmp_path):
    page = _StubPage(["答", "答"])
    _, chat = _subject_chat(monkeypatch, page)
    page.url = "https://chatgpt.com/"

    # A new process: nothing in memory, the same DATA_DIR.
    chatgpt_web.ChatGptWebClient()._ask_with_retries(
        _OneTabContext(page), "問2", [PNG], chat_key="subject:数学")

    assert _gotos(page) == [chat]
    assert len(_clicks(page, chatgpt_web.NEW_CHAT_SEL)) == 1
    assert len(page.uploads) == 1, "nothing already confirmed is uploaded again"
    record = json.loads((tmp_path / "browser-state" / "chats.json").read_text(encoding="utf-8"))
    kept = json.dumps(record, ensure_ascii=False)
    assert chat in kept and "問" not in kept and "答" not in kept, "no prompt or answer is kept"


@pytest.mark.parametrize("unreachable", ["redirected", "load fails", "no composer"])
def test_an_unreachable_subject_chat_fails_without_opening_another(monkeypatch, unreachable):
    page = _StubPage(["答", "答"])
    client, chat = _subject_chat(monkeypatch, page)
    monkeypatch.setattr(chatgpt_web, "ATTEMPTS", 2)
    monkeypatch.setattr(chatgpt_web, "READY_TIMEOUT_S", 0)
    page.url = "https://chatgpt.com/"
    loaded = []

    def goto(url, **_kw):
        loaded.append(url)
        if unreachable == "load fails":
            raise TimeoutError(f"{url} did not load")
        # A deleted chat lands on the home page instead.
        page.url = "https://chatgpt.com/" if unreachable == "redirected" else url

    page.goto = goto
    if unreachable == "no composer":
        page.missing.add(chatgpt_web.COMPOSER_SEL)

    with pytest.raises(chatgpt_web.ChatGptWebChatLost, match="no new chat was opened") as raised:
        client._ask_with_retries(_OneTabContext(page), "問2", [PNG], chat_key="subject:数学")

    assert chat not in str(raised.value), "the chat URL is never put in a message"
    assert loaded == [chat, chat], "every attempt tried the recorded chat"
    assert len(_clicks(page, chatgpt_web.NEW_CHAT_SEL)) == 1
    assert len(_sends(page)) == 1, "nothing sent anywhere else"


def test_a_key_with_no_chat_yet_still_opens_a_new_one_on_retry(monkeypatch):
    monkeypatch.setattr(chatgpt_web, "RETRY_BACKOFF_S", 0)
    monkeypatch.setattr(chatgpt_web, "UPLOAD_TIMEOUT_S", 0)
    monkeypatch.setattr(chatgpt_web, "POLL_S", 0)
    page = _StubPage(["答", "答"], thumbnail_appears=[False, True])

    chatgpt_web.ChatGptWebClient()._ask_with_retries(
        _OneTabContext(page), "問1", [PNG], chat_key="subject:数学")

    # Nothing was sent before the retry, so there was no conversation to lose.
    assert len(_clicks(page, chatgpt_web.NEW_CHAT_SEL)) == 2
    assert not _gotos(page)


@pytest.mark.parametrize("record", [
    "{not json",
    '{"key": "subject:数学", "url": "https://chatgpt.com.example/c/x", "attached": []}',
])
def test_a_record_that_is_not_a_chatgpt_chat_counts_as_none(monkeypatch, tmp_path, record):
    # Only an outside edit makes one. Blocking the subject over it would cost
    # the venue every answer; opening one chat costs one chat. Never go there.
    monkeypatch.setattr(chatgpt_web, "POLL_S", 0)
    (tmp_path / "browser-state").mkdir()
    (tmp_path / "browser-state" / "chats.json").write_text(record, encoding="utf-8")
    page = _StubPage(["答"])

    chatgpt_web.ChatGptWebClient()._ask_with_retries(
        _OneTabContext(page), "問1", [], chat_key="subject:数学")

    assert not _gotos(page)
    assert len(_clicks(page, chatgpt_web.NEW_CHAT_SEL)) == 1
    kept = json.loads((tmp_path / "browser-state" / "chats.json").read_text(encoding="utf-8"))
    assert kept["chats"]["subject:数学"]["url"] == page.url, "replaced by the chat that now exists"


@pytest.mark.parametrize("first", [True, False], ids=["first message", "later message"])
@pytest.mark.parametrize("outcome", ["uncertain", "rate limit"])
def test_an_unanswered_send_keeps_the_subject_chat(monkeypatch, tmp_path, outcome, first):
    """On a key's first message the unanswered send is what creates the chat."""
    from app.browser_guard import BrowserGuard

    page = _StubPage(["答", "答"])
    if first:
        _fast(monkeypatch)
        client = chatgpt_web.ChatGptWebClient()
    else:
        client, _ = _subject_chat(monkeypatch, page)
    real_submit = chatgpt_web.submit
    if outcome == "uncertain":
        def lost(p):
            real_submit(p)
            raise TimeoutError("submission reply lost")

        monkeypatch.setattr(chatgpt_web, "submit", lost)
        expected = chatgpt_web.ChatGptWebUncertain
    else:
        page.replies, page.poll = ["使用制限に達しました"], 0
        expected = chatgpt_web.ChatGptWebRateLimit

    with pytest.raises(expected):
        client._ask_with_retries(_OneTabContext(page), "問2", [JPEG], chat_key="subject:数学")
    chat = page.url
    assert "/c/" in chat

    monkeypatch.setattr(chatgpt_web, "submit", real_submit)
    if outcome == "uncertain":
        # Keeping the chat does not loosen the guard: nothing is sent until the
        # operator has reconciled the uncertain message.
        sends = len(_sends(page))
        with pytest.raises(chatgpt_web.ChatGptWebBlocked):
            client._ask_with_retries(_OneTabContext(page), "問3", [JPEG], chat_key="subject:数学")
        assert len(_sends(page)) == sends
    with BrowserGuard(tmp_path) as guard:
        if guard.status()["state"] == "uncertain":
            guard.acknowledge(guard.status()["request_id"])  # the operator reconciled
    page.replies, page.poll = ["答"], 0

    client._ask_with_retries(_OneTabContext(page), "問3", [JPEG], chat_key="subject:数学")

    # The tab never left the chat, and it is still loaded again first: the
    # composer of an unanswered message cannot be trusted.
    assert _gotos(page) == [chat], "the same chat after the limit or reconciliation"
    assert len(_clicks(page, chatgpt_web.NEW_CHAT_SEL)) == 1
    # An unanswered message does not vouch for its attachment, so JPEG goes again,
    # into the same chat.
    assert [p["buffer"] for payload in page.uploads for p in payload][-1] == JPEG


def test_a_chat_without_an_address_is_still_one_chat_for_the_subject(monkeypatch, tmp_path):
    """c0acf40 kept asking in a chat whose URL never showed /c/, and so must this.

    Nothing can be recorded for a restart, but within one process the subject
    stays where it is: one chat, one upload, three messages.
    """
    _fast(monkeypatch)
    page = _StubPage(["答"] * 3)
    page.addresses = False
    client = chatgpt_web.ChatGptWebClient()

    for n in range(3):
        client._ask_with_retries(_OneTabContext(page), f"問{n + 1}", [PNG],
                                 chat_key="subject:数学")

    assert len(_clicks(page, chatgpt_web.NEW_CHAT_SEL)) == 1
    assert len(page.uploads) == 1
    assert len(_sends(page)) == 3
    assert not (tmp_path / "browser-state" / "chats.json").exists(), "no address to keep"


@pytest.mark.parametrize("lost", ["tab moved", "attempt failed"])
def test_a_chat_without_an_address_is_never_replaced(monkeypatch, lost):
    # Neither a reload nor a navigation can reach it again, and a new chat is 9/14.
    _fast(monkeypatch)
    page = _StubPage(["答"] * 3, thumbnail_appears=[True, False, True])
    page.addresses = False
    client = chatgpt_web.ChatGptWebClient()
    ctx = _OneTabContext(page)
    client._ask_with_retries(ctx, "問1", [PNG], chat_key="subject:数学")
    client._ask_with_retries(ctx, "問2", [PNG], chat_key="subject:数学")
    if lost == "tab moved":
        page.url = "https://chatgpt.com/g/some-gpt"

    # "attempt failed": JPEG's first write never lands, so the composer is dirty.
    with pytest.raises(chatgpt_web.ChatGptWebChatLost, match="no address") as raised:
        client._ask_with_retries(ctx, "問3", [JPEG], chat_key="subject:数学")

    assert "no new chat was opened" in str(raised.value)
    assert len(_clicks(page, chatgpt_web.NEW_CHAT_SEL)) == 1
    assert not _gotos(page)
    assert len(_sends(page)) == 2


def test_a_chat_that_moved_is_not_assumed_to_hold_the_booklet(monkeypatch):
    _fast(monkeypatch)
    page = _StubPage(["答"] * 3)
    client = chatgpt_web.ChatGptWebClient()
    ctx = _OneTabContext(page)
    builds = []

    def booklet():
        builds.append(1)
        return [{"name": "page001.png", "mimeType": "image/png", "buffer": PNG}]

    client._ask_with_retries(ctx, "問1", [], files=booklet, chat_key="k")
    # The next message is answered in a different conversation, one that never
    # received the booklet.
    real_sent = page.sent

    def moved():
        real_sent()
        page.url = "https://chatgpt.com/c/elsewhere"

    page.sent = moved
    client._ask_with_retries(ctx, "問2", [], files=booklet, chat_key="k")
    page.sent = real_sent
    client._ask_with_retries(ctx, "問3", [], files=booklet, chat_key="k")

    assert len(builds) == 2, "the booklet is prepared again for the chat that lacks it"
    assert len(page.uploads) == 2
    assert page.url == "https://chatgpt.com/c/elsewhere"


def test_an_answer_survives_a_failed_record_write(monkeypatch, tmp_path):
    """The reply is kept, and the next send waits until the record is on disk."""
    _fast(monkeypatch)
    page = _StubPage(["答", "答"])
    client = chatgpt_web.ChatGptWebClient()
    ctx = _OneTabContext(page)
    real_save = chatgpt_web.ChatGptWebClient._save_chat

    def disk_full(self, guard):
        raise OSError("disk full")

    monkeypatch.setattr(chatgpt_web.ChatGptWebClient, "_save_chat", disk_full)
    assert client._ask_with_retries(ctx, "問1", [PNG], chat_key="subject:数学") == "答"

    with pytest.raises(chatgpt_web.ChatGptWebUncertain, match="could not be saved"):
        client._ask_with_retries(ctx, "問2", [PNG], chat_key="subject:数学")
    assert len(_sends(page)) == 1, "nothing sent while the chat is unrecorded"

    monkeypatch.setattr(chatgpt_web.ChatGptWebClient, "_save_chat", real_save)
    client._ask_with_retries(ctx, "問2", [PNG], chat_key="subject:数学")

    assert len(_clicks(page, chatgpt_web.NEW_CHAT_SEL)) == 1
    assert len(page.uploads) == 1 and len(_sends(page)) == 2
    record = json.loads((tmp_path / "browser-state" / "chats.json").read_text(encoding="utf-8"))
    assert record["chats"]["subject:数学"]["url"] == page.url


def _chats(tmp_path):
    return json.loads((tmp_path / "browser-state" / "chats.json").read_text(encoding="utf-8"))["chats"]


def test_interleaved_sessions_each_go_back_to_their_own_chat(monkeypatch, tmp_path):
    """Two sessions answered in turn: one chat and one booklet each, not one per question.

    With one recorded key, each switch replaced the other session's record, so
    the next question of that session opened another chat and built its
    booklet again: 6 chats for 6 questions in the reviewer's probe.
    """
    _fast(monkeypatch)
    page = _StubPage(["答"] * 6)
    client = chatgpt_web.ChatGptWebClient()
    ctx = _OneTabContext(page)
    builds = []

    def booklet():
        builds.append(1)
        return [{"name": "page001.png", "mimeType": "image/png", "buffer": PNG}]

    for n in range(3):
        for key in ("session:1", "session:2"):
            client._ask_with_retries(ctx, f"問{n + 1}", [], files=booklet, chat_key=key)

    assert len(_clicks(page, chatgpt_web.NEW_CHAT_SEL)) == 2
    assert len(builds) == 2
    assert len(_sends(page)) == 6
    assert set(_chats(tmp_path)) == {"session:1", "session:2"}


def test_the_record_keeps_the_eight_most_recently_used_chats(monkeypatch, tmp_path):
    _fast(monkeypatch)
    page = _StubPage(["答"] * 10)
    client = chatgpt_web.ChatGptWebClient()
    ctx = _OneTabContext(page)
    keys = [f"session:{n}" for n in range(9)]
    for key in keys[:8]:
        client._ask_with_retries(ctx, "問1", [], chat_key=key)
    # session:0 is the oldest written, but it is used again, so session:1 is
    # now the least recently used one.
    client._ask_with_retries(ctx, "問2", [], chat_key=keys[0])
    client._ask_with_retries(ctx, "問1", [], chat_key=keys[8])

    assert list(_chats(tmp_path)) == keys[2:8] + [keys[0], keys[8]]
    assert len(_clicks(page, chatgpt_web.NEW_CHAT_SEL)) == 9


def test_a_single_record_file_is_read_as_one_chat(monkeypatch, tmp_path):
    """The file written before the map existed still sends its subject back."""
    _fast(monkeypatch)
    chat = "https://chatgpt.com/c/recorded"
    (tmp_path / "browser-state").mkdir()
    (tmp_path / "browser-state" / "chats.json").write_text(json.dumps({
        "key": "subject:数学", "url": chat,
        "attached": [chatgpt_web._digest(PNG)], "source_attached": False,
    }), encoding="utf-8")
    page = _StubPage(["答"])

    chatgpt_web.ChatGptWebClient()._ask_with_retries(
        _OneTabContext(page), "問2", [PNG], chat_key="subject:数学")

    assert _gotos(page) == [chat]
    assert not _clicks(page, chatgpt_web.NEW_CHAT_SEL)
    assert not page.uploads, "the recorded attachment is still in that chat"
    assert _chats(tmp_path)["subject:数学"]["url"] == chat


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
        chatgpt_web.send_and_read(page, "next question", poll_s=0, timeout_s=2,
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


def test_one_message_lists_and_answers_the_booklet_in_the_answer_chat(tmp_path):
    """The model names the 小問 from the originals AND answers them in one reply."""
    page_path = tmp_path / "page.png"
    page_path.write_bytes(_real_png(80))
    pages = [{"page_number": 1, "image_path": str(page_path), "ocr_text": ""}]
    fake = _FakeClient(json.dumps({"questions": [
        {"group": "第1問", "label": "問1", "pages": [1], "status": "ready", "answer": "④"},
        {"group": "第1問", "label": "問2", "pages": [1], "status": "ready", "answer": ""},
        "bad"]}), attached=True)
    question = Question(question_no=None, question_id="booklet", answer_only=True,
                        document_pages=pages, document_id="1", page_numbers=[1],
                        chat_key="session:1")

    replies = ChatGptWebSolver(client=fake).answer_all(question=question)

    (first, answered), (second, broken) = replies
    assert (first["label"], answered.answer, answered.extras["image_attached"]) == ("問1", "④", True)
    assert second["label"] == "問2" and isinstance(broken, ValueError)
    assert "Answer EVERY question" in fake.seen["prompt"] and fake.seen["files"]
    assert "ONLY what belongs on" in fake.seen["system"]
    assert fake.seen["expect"] == ("questions",)
    booklet_key = fake.seen["chat_key"]
    fake.payload = '{"status":"ready","answer":"2"}'
    ChatGptWebSolver(client=fake).solve(question=Question(
        question_no="第1問 問1", question_id="q1", answer_only=True, document_pages=pages,
        document_id="1", page_numbers=[1], chat_key="session:1"))
    assert fake.seen["chat_key"] == booklet_key and fake.seen["expect"] == ("answer",)
    with pytest.raises(ValueError):
        ChatGptWebSolver(client=fake).answer_all(question=question)


def _uncertain_chat(tmp_path, key="session:1:x", url="https://chatgpt.com/c/abc",
                    pending="a" * 64):
    """A pending send recorded in the guard, and the chat recorded for ``key``."""
    from app.browser_guard import BrowserGuard

    with BrowserGuard(tmp_path) as guard:
        guard.mark_sending("a" * 64)
        (guard.directory / chatgpt_web.CHATS_FILE).write_text(json.dumps(
            {"chats": {key: {"url": url, "attached": [], "source_attached": True,
                             "pending": pending}}}))
    return key


class _Browser:
    def __init__(self, page):
        self.contexts = [_OneTabContext(page)]

    def close(self):
        pass


class _Tick:
    """A clock that moves one second per read, so a read-only wait ends in tests."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 1.0
        return self.now


def _recover(monkeypatch, page, key, turns=1):
    from app.solvers import cdp

    page.turns = turns
    monkeypatch.setattr(cdp, "connect_over_cdp", lambda endpoint: _Browser(page))
    return chatgpt_web.ChatGptWebClient().recover(
        chat_key=key, expect=("questions",), sleep=lambda _s: None, now=_Tick())


def _guard_state(tmp_path):
    from app.browser_guard import BrowserGuard

    with BrowserGuard(tmp_path) as guard:
        return guard.status()["state"]


def test_an_uncertain_send_whose_reply_finished_is_read_back_not_resent(monkeypatch, tmp_path):
    key = _uncertain_chat(tmp_path)
    page = _StubPage(['{"questions":[{"label":"問1","answer":"4"}]}'], streaming=[])

    text = _recover(monkeypatch, page, key)

    assert json.loads(text)["questions"][0]["answer"] == "4"
    assert _guard_state(tmp_path) == "idle"
    assert not _sends(page) and page.url == "https://chatgpt.com/c/abc"


def test_a_reply_still_generating_is_waited_for_read_only(monkeypatch, tmp_path):
    key = _uncertain_chat(tmp_path)
    page = _StubPage(['{"questions":[{"label":"問1","answer":"4"}]}'],
                     streaming=[True] * 30 + [False])

    assert _recover(monkeypatch, page, key) is not None
    assert page.stop_poll > 30 and not _sends(page)


def test_another_sessions_pending_send_is_never_acknowledged(monkeypatch, tmp_path):
    key = _uncertain_chat(tmp_path, pending="b" * 64)
    page = _StubPage(['{"questions":[]}'], streaming=[])

    assert _recover(monkeypatch, page, key) == '{"questions":[]}'
    assert _guard_state(tmp_path) == "uncertain"


@pytest.mark.parametrize("frames, streaming", [
    (['{"questions":[{"label":"問1"}'], []),  # cut off
    (['{"questions":[]}'], [True]),  # generating past the session
])
def test_an_unfinished_reply_leaves_the_send_uncertain(monkeypatch, tmp_path, frames, streaming):
    monkeypatch.setattr(chatgpt_web, "TIMEOUT_S", 20)
    key = _uncertain_chat(tmp_path)
    page = _StubPage(frames, streaming=streaming)

    assert _recover(monkeypatch, page, key) is None
    assert _guard_state(tmp_path) == "uncertain"
    assert not _sends(page)


def test_answer_all_reads_the_booklet_chat_back_after_an_uncertain_send(tmp_path):
    from app.solvers.chatgpt_web import ChatGptWebUncertain

    page_path = tmp_path / "page.png"
    page_path.write_bytes(_real_png(80))
    pages = [{"page_number": 1, "image_path": str(page_path), "ocr_text": ""}]
    asked = []

    class Client(_FakeClient):
        def complete_json(self, **kw):
            raise ChatGptWebUncertain("send outcome unknown")

        def recover(self, *, chat_key, expect):
            asked.append((chat_key, expect))
            return '{"questions":[{"group":"第1問","label":"問1","status":"ready","answer":"④"}]}'

    question = Question(question_no=None, question_id="booklet", answer_only=True,
                        document_pages=pages, document_id="1", page_numbers=[1],
                        chat_key="session:1")
    ((item, result),) = ChatGptWebSolver(client=Client("{}")).answer_all(question=question)

    assert result.answer == "④"
    assert asked[0][0].startswith("session:1:") and asked[0][1] == ("questions",)


def test_an_answer_that_quotes_a_limit_phrase_is_still_the_answer():
    reply = '{"questions":[{"label":"問1","answer":"上限に達した時刻は3時"}]}'
    page = _StubPage([reply], streaming=[])
    assert ask_page(page, "全問", poll_s=0, expect=("questions",), sleep=lambda _s: None)[0] == reply


def test_a_limit_notice_instead_of_the_json_still_stops():
    page = _StubPage(["使用制限に達しました"], streaming=[])
    with pytest.raises(chatgpt_web.ChatGptWebRateLimit):
        ask_page(page, "全問", poll_s=0, expect=("questions",), sleep=lambda _s: None)


def test_a_chat_with_no_turns_rendered_is_not_judged(monkeypatch, tmp_path):
    """Right after a load the turns may not exist yet; nothing is read until they do."""
    key = _uncertain_chat(tmp_path)
    page = _StubPage([], streaming=[])

    assert _recover(monkeypatch, page, key, turns=0) is None
    assert _guard_state(tmp_path) == "uncertain"


def test_a_booklet_with_a_recorded_chat_is_read_back_never_sent_again(tmp_path):
    """A repeated finalize or a restart after the answer: the booklet is not sent twice."""
    page_path = tmp_path / "page.png"
    page_path.write_bytes(_real_png(80))
    pages = [{"page_number": 1, "image_path": str(page_path), "ocr_text": ""}]
    sent, read = [], []

    class Client(_FakeClient):
        def complete_json(self, **kw):
            sent.append(kw)
            return {}

        def recorded(self, chat_key):
            return True

        def recover(self, *, chat_key, expect):
            read.append(chat_key)
            return '{"questions":[{"group":"第1問","label":"問1","status":"ready","answer":"④"}]}'

    question = Question(question_no=None, question_id="booklet", answer_only=True,
                        document_pages=pages, document_id="1", page_numbers=[1],
                        chat_key="session:1")
    ((_, result),) = ChatGptWebSolver(client=Client("{}")).answer_all(question=question)

    assert result.answer == "④" and sent == [] and read[0].startswith("session:1:")

    class Unreadable(Client):
        def recover(self, *, chat_key, expect):
            return None

    with pytest.raises(chatgpt_web.ChatGptWebUncertain, match="nothing is sent again"):
        ChatGptWebSolver(client=Unreadable("{}")).answer_all(question=question)
    assert sent == []


def test_the_chat_address_is_recorded_while_the_reply_is_still_coming(monkeypatch, tmp_path):
    """A restart mid-reply must find the chat: it is written before the reply ends."""
    from app.browser_guard import BrowserGuard

    writes = []
    real_save = chatgpt_web.ChatGptWebClient._save_chat

    def save(self, guard):
        writes.append((self._chat_url, self._pending, page.stop_poll))
        real_save(self, guard)

    monkeypatch.setattr(chatgpt_web.ChatGptWebClient, "_save_chat", save)
    page = _StubPage(['{"status":"ready","answer":"4"}'], streaming=[True, True, True, False])
    chatgpt_web.ChatGptWebClient()._ask_with_retries(
        _OneTabContext(page), "問1", [], chat_key="session:9", expect=("answer",))

    (url, pending, polls), last = writes[0], writes[-1]
    assert url == "https://chatgpt.com/c/chat-1" and pending and polls < 3, "written mid-reply"
    assert last[1] is None
    assert chatgpt_web._read_chats(BrowserGuard(tmp_path).directory)["session:9"]["pending"] is None


def test_another_sessions_pending_send_blocks_without_being_read_back(monkeypatch, tmp_path):
    from app.browser_guard import BrowserGuard

    with BrowserGuard(tmp_path) as guard:
        guard.mark_sending("c" * 64)
    page = _StubPage(["x"])
    with pytest.raises(chatgpt_web.ChatGptWebBlocked):
        chatgpt_web.ChatGptWebClient()._ask_with_retries(_OneTabContext(page), "問1", [])
    assert page.events == []


def test_a_reply_that_stops_with_no_text_fails_instead_of_waiting_the_session(monkeypatch):
    page = _StubPage([""], streaming=[True, False])
    with pytest.raises(ChatGptWebError, match="without any text"):
        ask_page(page, "全問", poll_s=0, expect=("questions",), sleep=lambda _s: None)
    assert page.stop_poll == 1 + chatgpt_web.SETTLE_POLLS


def test_a_limit_phrase_seen_in_a_blink_is_not_a_limit():
    page = _StubPage(["上限に達し", '{"questions":[{"answer":"上限に達した"}]}'],
                     streaming=[True, False, True, False])
    reply, _ = ask_page(page, "全問", poll_s=0, expect=("questions",), sleep=lambda _s: None)
    assert reply == '{"questions":[{"answer":"上限に達した"}]}'
