"""Solver that answers from an already-logged-in ChatGPT web session.

No API key and no per-question hand work: the server drives the operator's own
Chrome over the DevTools protocol, types the answer-only prompt into the web
UI and reads the reply back. That keeps a subscription-only setup on the same
``Solver`` port as the API adapters, so the HUD, answer bundle and review flow
are unchanged.

The operational cost of this route, stated plainly:

* Chrome must already be running with a debugging port open and signed in to
  ChatGPT. Start it once per session::

      chrome.exe --remote-debugging-port=9222 --user-data-dir=<your profile>

  Reusing the real profile is deliberate: a fresh automation profile is not
  signed in and draws bot checks.
* Automated access to the ChatGPT web UI is against OpenAI's terms of use. The
  account carries a suspension risk that the API route does not.
* The page structure belongs to OpenAI and changes without notice. Every
  selector and timeout below is env-overridable so a break is a config edit,
  not a code change.

The page image and the OCR text are sent as two separate parts, exactly as the
API solvers do it: the image is attached to the message, the text is typed into
it. Merging them is not an option -- a figure, graph or equation survives as an
attachment and does not survive OCR.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from ..llm import extract_json
from .llm_adapter import LLMSolver, _read_images

# DevTools endpoint of the operator's already-running browser.
CDP_ENDPOINT = os.environ.get("ROKID_CHATGPT_CDP", "http://127.0.0.1:9222")
# The page structure is OpenAI's, not ours. Override without editing code.
CHAT_URL = os.environ.get("ROKID_CHATGPT_URL", "https://chatgpt.com/")
COMPOSER_SEL = os.environ.get("ROKID_CHATGPT_COMPOSER_SEL", "#prompt-textarea")
ASSISTANT_SEL = os.environ.get(
    "ROKID_CHATGPT_ASSISTANT_SEL", '[data-message-author-role="assistant"]'
)
# The composer's hidden file input, and the thumbnail that confirms the upload
# finished. Sending before the upload lands would ask about a figure the model
# never received, so the thumbnail is waited for rather than assumed.
# Measured on the signed-in page: `input[type="file"]` matches FIVE inputs
# (upload-files, upload-photos, upload-media, upload-camera, upload-media-files)
# and Playwright refuses an ambiguous locator with a strict mode violation, so
# that selector failed every upload. This is the photo one, accept="image/*".
FILE_INPUT_SEL = os.environ.get(
    "ROKID_CHATGPT_FILE_INPUT_SEL", 'input[data-testid="upload-photos-input"]'
)
# Verified on the signed-in composer: 0 matches empty, 1 after an upload lands.
ATTACHMENT_SEL = os.environ.get(
    "ROKID_CHATGPT_ATTACHMENT_SEL", 'form img, [data-testid*="attachment"]'
)
# Present only while a reply streams. Its absence is the fastest honest signal
# that the answer is finished; text-stability below covers it going missing.
STOP_SEL = os.environ.get("ROKID_CHATGPT_STOP_SEL", '[data-testid="stop-button"]')
# Starting the next question is a CLICK, not a page load. Reloading chatgpt.com
# once per question (and again per retry) hammers the site for no benefit and
# was measured destabilising the browser partway through a run of subjects.
NEW_CHAT_SEL = os.environ.get(
    "ROKID_CHATGPT_NEW_CHAT_SEL", '[data-testid="create-new-chat-button"]'
)
# A reply is complete when its text stops growing. Streaming pauses mid-answer,
# so require several consecutive identical polls rather than a single one.
# 0.25s x 4 confirms after 1s of silence. The earlier 1.0s x 3 spent 3s waiting
# on every question -- measured at five times the whole browser attach cost, so
# it was the one worth cutting.
POLL_S = float(os.environ.get("ROKID_CHATGPT_POLL_S", "0.25"))
STABLE_POLLS = int(os.environ.get("ROKID_CHATGPT_STABLE_POLLS", "4"))
TIMEOUT_S = float(os.environ.get("ROKID_CHATGPT_TIMEOUT_S", "180"))
# A confirmed upload measured 0.11s. 60s was budgeted before there were
# retries; with ATTEMPTS on top it made one unattachable question cost 3
# minutes, which on a deck is worse than a fast retry in a fresh chat.
UPLOAD_TIMEOUT_S = float(os.environ.get("ROKID_CHATGPT_UPLOAD_S", "20"))
# chatgpt.com serves a signed-out "lightweight shell" whose DOM has none of the
# app's controls, and the real composer mounts after the document is loaded.
# Measured on Chrome 152: domcontentloaded returns ~0.2s, ~0.9s before the app.
# So the composer is waited for, never assumed to be there on arrival.
READY_TIMEOUT_S = float(os.environ.get("ROKID_CHATGPT_READY_S", "30"))
# A run of questions back to back is not as reliable as one. Measured over 16
# consecutive solves: one upload never confirmed inside 60s and one composer
# never became clickable inside 30s. A 大問 deck is dozens of solves, so a
# single flake would silently cost that question its answer.
ATTEMPTS = int(os.environ.get("ROKID_CHATGPT_ATTEMPTS", "3"))
RETRY_BACKOFF_S = float(os.environ.get("ROKID_CHATGPT_RETRY_S", "5"))


class ChatGptWebError(RuntimeError):
    """Raised when the browser route cannot produce an answer.

    ``solve_with_fallback`` catches this and drops to the next tier, so a
    closed browser or a changed page degrades instead of failing the session.
    """


def cdp_available(endpoint: str = CDP_ENDPOINT, *, timeout: float = 1.0) -> str | None:
    """Return the browser's version string if a DevTools endpoint answers.

    A cheap pre-flight over plain HTTP: it does not start Playwright and does
    not touch chatgpt.com, so ``ready()`` stays a probe rather than a page load.
    """
    try:
        with urllib.request.urlopen(f"{endpoint.rstrip('/')}/json/version", timeout=timeout) as r:
            return str(json.loads(r.read().decode("utf-8")).get("Browser", "unknown"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def image_payload(image: bytes, *, name: str = "page") -> dict:
    """Describe ``image`` for Playwright's ``set_input_files``.

    Passing the buffer straight through avoids a temporary file. The type is
    sniffed from the magic bytes rather than trusted from a path: the server
    persists a normalized PNG, but the relay uploads JPEG, and an attachment
    labelled with the wrong type is rejected by the upload endpoint.
    """
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        suffix, mime = "png", "image/png"
    elif image.startswith(b"\xff\xd8\xff"):
        suffix, mime = "jpg", "image/jpeg"
    else:
        suffix, mime = "png", "image/png"
    return {"name": f"{name}.{suffix}", "mimeType": mime, "buffer": image}


def attach_images(
    page,
    images: list[bytes],
    *,
    timeout_s: float | None = None,
    poll_s: float | None = None,
    sleep=time.sleep,
    now=time.monotonic,
) -> bool:
    """Attach every page of the question; return whether ALL uploads confirmed.

    A 大問 keeps its passage on one page and its figures on another, so the
    whole span is attached in reading order. The composer's photo input is
    `multiple`, so one call carries them all and the pages stay ordered.

    Confirmation is a *rise* of len(images) in the thumbnail count, not a
    non-zero one. A measured probe found the default selector already matching
    an element on a composer with nothing attached, which would have reported
    every upload as confirmed without checking anything, and a partial rise
    means some page never made it.

    Returns False instead of raising when the count never rises far enough. The
    attachments may well have landed and only the preview markup have moved,
    and losing the whole answer over an unconfirmed preview is worse than
    sending and recording that it was unconfirmed.
    """
    if not images:
        return False
    timeout_s = UPLOAD_TIMEOUT_S if timeout_s is None else timeout_s
    poll_s = POLL_S if poll_s is None else poll_s
    thumbnails = page.locator(ATTACHMENT_SEL)
    baseline = thumbnails.count()
    page.locator(FILE_INPUT_SEL).set_input_files(
        [image_payload(data, name=f"page{i + 1:02d}") for i, data in enumerate(images)]
    )
    # Check before waiting, so an upload that has already landed is never
    # reported unconfirmed just because the budget was small.
    deadline = now() + timeout_s
    while True:
        if thumbnails.count() >= baseline + len(images):
            return True
        if now() >= deadline:
            return False
        sleep(poll_s)


def reuse_page(context):
    """The tab this route works in: an existing chatgpt.com tab, else one new one.

    Opening a tab per question left dozens behind over a deck and reloaded the
    site every time. One tab is claimed and kept.
    """
    for page in context.pages:
        try:
            if page.url.startswith(CHAT_URL.rstrip("/")):
                return page
        except Exception:  # noqa: BLE001 - a closing page has no url
            continue
    page = context.new_page()
    page.goto(CHAT_URL, wait_until="domcontentloaded")
    return page


def start_new_chat(page, *, ready_timeout_s: float | None = None) -> None:
    """Clear the composer for the next question without reloading the page.

    A fresh thread per question is required -- earlier turns would become
    context the grader never saw -- but it does not require a navigation. The
    sidebar's new-chat control is a client-side route change. Only when the tab
    is not on chatgpt.com at all, or that control is missing, does this fall
    back to a real page load.
    """
    ready_timeout_s = READY_TIMEOUT_S if ready_timeout_s is None else ready_timeout_s
    new_chat = page.locator(NEW_CHAT_SEL)
    try:
        if page.url.startswith(CHAT_URL.rstrip("/")) and new_chat.count():
            new_chat.first.click()
        else:
            page.goto(CHAT_URL, wait_until="domcontentloaded")
    except Exception:  # noqa: BLE001 - any click failure is worth one reload
        page.goto(CHAT_URL, wait_until="domcontentloaded")
    page.locator(COMPOSER_SEL).wait_for(state="visible", timeout=ready_timeout_s * 1000)


def ask_page(
    page,
    text: str,
    *,
    images: list[bytes] | None = None,
    timeout_s: float | None = None,
    poll_s: float | None = None,
    stable_polls: int | None = None,
    upload_timeout_s: float | None = None,
    ready_timeout_s: float | None = None,
    sleep=time.sleep,
    now=time.monotonic,
) -> tuple[str, bool | None]:
    """Send ``text`` (and optionally ``images``) and return the reply and upload state.

    The images are attached first and the text typed into the same message, so
    the model receives the pages and the OCR text as separate parts of one
    question. Split out from the connection handling so the page interaction is
    testable against a stub, with no browser and no network call.

    Returns ``(reply_text, attached)``, where ``attached`` is None when there
    were no images and False when the uploads could not all be confirmed.
    """
    # Resolved here, not bound as defaults: the ROKID_CHATGPT_* knobs exist so a
    # changed page can be retuned, and a default bound at import cannot be.
    timeout_s = TIMEOUT_S if timeout_s is None else timeout_s
    poll_s = POLL_S if poll_s is None else poll_s
    stable_polls = STABLE_POLLS if stable_polls is None else stable_polls
    upload_timeout_s = UPLOAD_TIMEOUT_S if upload_timeout_s is None else upload_timeout_s
    ready_timeout_s = READY_TIMEOUT_S if ready_timeout_s is None else ready_timeout_s

    composer = page.locator(COMPOSER_SEL)
    try:
        composer.wait_for(state="visible", timeout=ready_timeout_s * 1000)
    except Exception as exc:  # noqa: BLE001 - playwright raises its own timeout
        raise ChatGptWebError(
            f"composer {COMPOSER_SEL!r} never appeared within {ready_timeout_s:g}s. "
            "A signed-out chatgpt.com serves a placeholder shell without it: "
            "check the browser profile is signed in, else retune "
            "ROKID_CHATGPT_COMPOSER_SEL"
        ) from exc

    attached: bool | None = None
    if images:
        # After the composer exists but before the text: the upload runs while
        # the prompt is placed, and a send cannot race an unfinished attachment.
        attached = attach_images(
            page, images, timeout_s=upload_timeout_s, poll_s=poll_s, sleep=sleep, now=now
        )

    composer.click()
    # ``fill`` sets a contenteditable's content in one step. Typing it key by
    # key would send the message at the prompt's first newline.
    composer.fill(text)
    page.keyboard.press("Enter")

    replies = page.locator(ASSISTANT_SEL)
    stop_button = page.locator(STOP_SEL)
    deadline = now() + timeout_s
    previous: str | None = None
    stable = 0
    seen = False
    streaming_started = False
    while now() < deadline:
        sleep(poll_s)
        # The stop button exists for the WHOLE generation, thinking phase
        # included. While it is there, nothing on screen is the answer: a
        # reasoning model shows a "思考中" placeholder that holds still for over
        # a second, and text-stability alone confirmed that placeholder as the
        # final answer on 4 of 5 measured long prompts. The assistant turn then
        # goes briefly EMPTY before the real text streams in.
        streaming = bool(stop_button.count())
        streaming_started = streaming_started or streaming
        current = replies.last.inner_text() if replies.count() else ""
        if streaming:
            # Anything visible mid-generation is provisional. Drop any
            # stability credit so a pause inside the stream cannot end the wait.
            seen = seen or bool(current.strip())
            stable = 0
            previous = current
            continue
        if current.strip():
            seen = True
            if streaming_started:
                # Seen streaming, now finished: this is the settled reply.
                return current.strip(), attached
            # The stop button never appeared at all, so it is missing or has
            # moved. Fall back to text-stability rather than waiting it out.
            stable = stable + 1 if current == previous else 0
            if stable >= stable_polls:
                return current.strip(), attached
        previous = current
    state = "still streaming" if seen else "no reply appeared"
    raise ChatGptWebError(f"ChatGPT web reply did not finish within {timeout_s:g}s ({state})")


class ChatGptWebClient:
    """An ``LLMClient``-shaped stand-in backed by the ChatGPT web UI.

    Exposes only what :class:`~app.solvers.llm_adapter.LLMSolver` calls, so the
    answer-only contract, status handling and ``SolveResult`` construction are
    inherited rather than restated here.
    """

    def __init__(self, *, endpoint: str = CDP_ENDPOINT, model: str = "chatgpt-web"):
        self.endpoint = endpoint
        self.model = model
        #: Whether the last call's image upload was confirmed: True, False when
        #: the thumbnail never appeared, None when there was no image. Read by
        #: the solver so an unconfirmed figure is recorded, not assumed.
        self.last_image_attached: bool | None = None

    def complete(
        self,
        *,
        system: str,
        prompt: str,
        image: bytes | None = None,
        images: list[bytes] | None = None,
    ) -> str:
        # `image` keeps the single-page LLMClient shape; `images` carries a 大問
        # that spans pages. Either way the pages travel as attachments and the
        # OCR text as the message body -- never merged into one part.
        pages = list(images) if images else ([image] if image else [])
        self.last_image_attached = None
        try:
            from playwright.sync_api import sync_playwright  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise ChatGptWebError("chatgpt-web solver needs `pip install playwright`") from exc

        with sync_playwright() as pw:
            try:
                browser = pw.chromium.connect_over_cdp(self.endpoint)
            except Exception as exc:  # noqa: BLE001 - playwright raises broadly
                raise ChatGptWebError(
                    f"no Chrome on {self.endpoint}; start it with --remote-debugging-port"
                ) from exc
            try:
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                return self._ask_with_retries(context, f"{system}\n\n{prompt}", pages)
            finally:
                browser.close()

    def _ask_with_retries(self, context, text: str, pages: list[bytes]) -> str:
        """One question, retried on a flake, each attempt in its own fresh chat.

        An unconfirmed upload counts as a failure worth retrying: sending the
        question without its figure does not error, it just answers the wrong
        question or returns needs_input, which is the expensive kind of wrong.
        The last attempt's reply is accepted either way, so a permanently moved
        thumbnail selector still yields an answer rather than nothing.
        """
        last_error: Exception | None = None
        page = reuse_page(context)
        for attempt in range(1, ATTEMPTS + 1):
            if attempt > 1:
                # Backing off at the top covers every way the previous attempt
                # ended. Retrying a throttled upload immediately is the case
                # that needs the wait most.
                time.sleep(RETRY_BACKOFF_S * (attempt - 1))
            try:
                start_new_chat(page)
                reply, attached = ask_page(page, text, images=pages)
                if pages and attached is not True and attempt < ATTEMPTS:
                    last_error = ChatGptWebError("page images never confirmed as attached")
                    continue
                self.last_image_attached = attached
                return reply
            except Exception as exc:  # noqa: BLE001 - playwright raises broadly
                last_error = exc
                if attempt >= ATTEMPTS:
                    raise ChatGptWebError(
                        f"ChatGPT web failed {ATTEMPTS} times; last: {exc}"
                    ) from exc
        raise ChatGptWebError(f"ChatGPT web failed {ATTEMPTS} times; last: {last_error}")

    def complete_json(
        self,
        *,
        system: str,
        prompt: str,
        image: bytes | None = None,
        images: list[bytes] | None = None,
    ) -> dict:
        return extract_json(
            self.complete(system=system, prompt=prompt, image=image, images=images)
        )


class ChatGptWebSolver(LLMSolver):
    """Answer-only solver routed as ``chatgpt-web`` (no API key)."""

    def __init__(self, client: ChatGptWebClient | None = None):
        super().__init__(name="chatgpt-web", provider="chatgpt-web", client=client)
        self._client = client if client is not None else ChatGptWebClient()
        self.provider_version = "web-ui"

    def _complete(self, client, *, system: str, prompt: str, question) -> dict:
        """Send EVERY page of the question's 大問, not just its starting page.

        The API adapters take a single image, so the shared implementation sends
        the primary page. A 大問 that spans pages keeps its passage on one page
        and its figures on another, and the question is usually about the figure.
        """
        return client.complete_json(
            system=system, prompt=prompt, images=_read_images(question)
        )

    def solve(self, *, question, max_answer_len: int = 64):
        """Inherit the answer-only contract, then record how the figures fared.

        Upload confirmation is browser-only, so it has no place in the shared
        adapter; surfacing it here keeps "the model saw the figure" a recorded
        fact rather than an assumption when a diagram-dependent answer is wrong.
        """
        result = super().solve(question=question, max_answer_len=max_answer_len)
        attached = getattr(self._client, "last_image_attached", None)
        if attached is not None:
            result.extras["image_attached"] = attached
        return result

    def ready(self) -> bool:
        """True when a debuggable Chrome is actually reachable.

        An injected client is a test double and counts as ready; otherwise the
        DevTools endpoint has to answer, so "selected" and "will run" stay
        different questions exactly as they are for the credentialed adapters.
        """
        if not isinstance(self._client, ChatGptWebClient):
            return True
        return cdp_available(self._client.endpoint) is not None


def _smoke(question_text: str = "2x+3=7 を解け", *image_paths: str) -> int:
    """Live check of this route against the real page. Run it before a session::

        py -3.12 -m app.solvers.chatgpt_web
        py -3.12 -m app.solvers.chatgpt_web "図の角度を求めよ" p01.png p02.png

    The unit tests use a stub page, so they prove our side of the boundary and
    nothing about OpenAI's current markup. This is the only check that shows the
    selectors still match. Pass page images to check the attachment path too:
    the text selectors can be fine while the file input has moved. Pass several
    to check a 大問 that spans pages, which is the case a single image loses.
    """
    from .base import Question  # noqa: PLC0415

    browser = cdp_available()
    if browser is None:
        print(f"FAIL  no debuggable Chrome on {CDP_ENDPOINT}")
        print("      start it with: chrome.exe --remote-debugging-port=9222 "
              "--user-data-dir=<your profile>")
        return 1
    print(f"ok    browser        {browser}")

    solver = ChatGptWebSolver()
    try:
        result = solver.solve(
            question=Question(
                body_text=question_text,
                image_path=image_paths[0] if image_paths else None,
                image_paths=list(image_paths),
                subject="数学",
                answer_only=True,
            )
        )
    except Exception as exc:  # noqa: BLE001 - a smoke check reports, never raises
        print(f"FAIL  {type(exc).__name__}: {exc}")
        print(f"      retune ROKID_CHATGPT_COMPOSER_SEL ({COMPOSER_SEL}) / "
              f"ROKID_CHATGPT_ASSISTANT_SEL ({ASSISTANT_SEL}) if the page changed")
        return 1

    attached = result.extras.get("image_attached")
    if image_paths and attached is not True:
        # Not a failure: the answer arrived. But the figure was not confirmed
        # to have landed, so the selector needs retuning before a real session.
        print(f"WARN  images         {len(image_paths)} queued, not all confirmed")
        print(f"      retune ROKID_CHATGPT_FILE_INPUT_SEL ({FILE_INPUT_SEL}) / "
              f"ROKID_CHATGPT_ATTACHMENT_SEL ({ATTACHMENT_SEL})")
    elif image_paths:
        print(f"ok    images         {len(image_paths)} attached")
    print(f"ok    status         {result.extras.get('answer_status')}")
    print(f"ok    answer         {result.answer!r}")
    return 0 if (not image_paths or attached is True) else 2


if __name__ == "__main__":  # pragma: no cover - operator-run live check
    import sys

    sys.exit(_smoke(*sys.argv[1:]))
