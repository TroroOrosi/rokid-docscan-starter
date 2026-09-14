"""A Playwright-shaped client that speaks CDP directly.

The venue runs the server on the phone, and Playwright does not run there:
Termux has no wheel for it, and a manylinux wheel plus ``PLAYWRIGHT_NODEJS_PATH``
still fails because the driver reports ``Error: Unsupported platform: android``
(`docs/hardware-measurements.md` §F-5). The page automation itself is not the
problem -- Chrome for Android answers CDP perfectly well once an on-device
``adb forward`` exposes its abstract socket as ``127.0.0.1:9222``.

So this module reimplements the handful of Playwright calls
:mod:`app.solvers.chatgpt_web` actually makes, and nothing else. It is not a
Playwright replacement; it is the subset, with the same names and shapes so the
solver reads the same either way.

Typing and clicking go through the real CDP input domain rather than JavaScript
events, because ChatGPT's composer is a ProseMirror instance: it rebuilds its
model from input events, and a synthetic ``KeyboardEvent`` does not produce one.
``Input.insertText`` is what a keyboard does, in one call regardless of length.

File attachment cannot use ``DOM.setFileInputFiles``: that names paths on the
*browser's* filesystem, and Chrome for Android cannot read the server's files.
The bytes are handed to the page instead, as a ``DataTransfer``.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request

DEFAULT_TIMEOUT_S = 30.0

#: CDP carries the page bytes as base64 inside a JSON message, so a bundled
#: booklet PDF arrives as one multi-megabyte frame. `websockets` defaults to a
#: 1 MiB ceiling and would close the connection instead of delivering it.
MAX_MESSAGE_BYTES = 256 * 1024 * 1024


class CdpError(RuntimeError):
    """Any failure to drive the browser over CDP."""


#: The endpoint refuses or hangs on the first probes and then answers. Measured
#: on F-51F / Chrome 153.0.8010.36 through an `adb forward`: two 10s `curl`
#: timeouts, then the version JSON; and a `RemoteDisconnected` on another run.
#: Chrome's abstract socket is being reached, but the browser is not always
#: ready to serve it, so one refusal is not an absent endpoint.
PROBE_ATTEMPTS = 5
PROBE_PAUSE_S = 1.0


def _http_json(url: str, timeout_s: float, *, attempts: int = PROBE_ATTEMPTS):
    last: Exception | None = None
    per_attempt = max(2.0, timeout_s / attempts)
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=per_attempt) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(PROBE_PAUSE_S)
    raise CdpError(
        f"no CDP endpoint answered {url} in {attempts} attempts: {last}"
    ) from last


class _Connection:
    """One WebSocket to the browser, multiplexed over flattened sessions.

    ``Target.attachToTarget`` with ``flatten`` puts every page's traffic on this
    single socket, tagged by ``sessionId``. One connection, no per-page sockets.
    """

    def __init__(self, ws_url: str, *, timeout_s: float = DEFAULT_TIMEOUT_S):
        try:
            from websockets.sync.client import connect  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise CdpError(
                "the chatgpt-web solver needs `pip install websockets` to speak CDP"
            ) from exc
        try:
            self._ws = connect(
                ws_url, max_size=MAX_MESSAGE_BYTES, open_timeout=timeout_s
            )
        except Exception as exc:  # noqa: BLE001 - websockets raises broadly
            raise CdpError(f"could not open the CDP socket {ws_url}: {exc}") from exc
        self._next_id = 0
        self.timeout_s = timeout_s

    def send(self, method: str, params: dict | None = None, *, session_id: str | None = None):
        self._next_id += 1
        message_id = self._next_id
        message: dict = {"id": message_id, "method": method, "params": params or {}}
        if session_id:
            message["sessionId"] = session_id
        self._ws.send(json.dumps(message))
        return self._await(message_id)

    def _await(self, message_id: int) -> dict:
        """Read until this command's reply; events and other replies are dropped.

        Nothing here subscribes to events, so discarding them is the whole event
        handling. Waiting is done by polling the page state instead, which is
        what the solver's timeouts already assume.
        """
        deadline = time.monotonic() + self.timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CdpError(f"CDP command {message_id} timed out after {self.timeout_s:g}s")
            try:
                raw = self._ws.recv(timeout=remaining)
            except Exception as exc:  # noqa: BLE001 - websockets raises broadly
                raise CdpError(f"CDP socket failed while waiting: {exc}") from exc
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            if message.get("id") != message_id:
                continue
            if "error" in message:
                raise CdpError(f"CDP error from {message_id}: {message['error']}")
            return message.get("result", {})

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:  # noqa: BLE001 - closing must not mask a real failure
            pass


class Keyboard:
    """Only ``press``, and only because sending the message needs a real key."""

    _KEYS = {"Enter": (13, "\r")}

    def __init__(self, page: "Page"):
        self._page = page

    def press(self, key: str) -> None:
        code, text = self._KEYS.get(key, (0, ""))
        for event_type in ("keyDown", "keyUp"):
            params = {
                "type": event_type,
                "key": key,
                "code": key,
                "windowsVirtualKeyCode": code,
                "nativeVirtualKeyCode": code,
            }
            if event_type == "keyDown" and text:
                params["text"] = text
            self._page.send("Input.dispatchKeyEvent", params)


class Locator:
    """A selector plus which match to act on, resolved at every call.

    Playwright's locators are lazy in the same way: the page can replace the
    node between two calls and the next call still finds the current one.
    """

    def __init__(self, page: "Page", selector: str, index: int | None = None):
        self._page = page
        self._selector = selector
        self._index = index

    @property
    def first(self) -> "Locator":
        return Locator(self._page, self._selector, 0)

    @property
    def last(self) -> "Locator":
        return Locator(self._page, self._selector, -1)

    def count(self) -> int:
        return int(self._page.evaluate(f"document.querySelectorAll({self._selector!r}).length"))

    def _element_js(self) -> str:
        index = 0 if self._index is None else self._index
        return (
            f"(() => {{ const n = document.querySelectorAll({self._selector!r}); "
            f"return n[{index} < 0 ? n.length + {index} : {index}] || null; }})()"
        )

    def inner_text(self) -> str:
        return str(self._page.evaluate(f"({self._element_js()}?.innerText) ?? ''"))

    def is_visible(self) -> bool:
        return bool(
            self._page.evaluate(
                f"(() => {{ const e = {self._element_js()}; if (!e) return false; "
                "const r = e.getBoundingClientRect(); "
                "return !!(r.width || r.height || e.getClientRects().length); })()"
            )
        )

    def wait_for(self, *, state: str = "visible", timeout: float = 30000.0) -> "Locator":
        """``timeout`` is milliseconds, as in Playwright."""
        deadline = time.monotonic() + timeout / 1000.0
        while True:
            if self.is_visible() if state == "visible" else self.count():
                return self
            if time.monotonic() >= deadline:
                raise CdpError(
                    f"{self._selector!r} was not {state} within {timeout / 1000.0:g}s"
                )
            time.sleep(0.1)

    def click(self) -> None:
        """Click where the element is, not just dispatch a click event.

        A React tree reacts to both, but a real mouse event also moves focus and
        closes whatever popover is open, which a dispatched event does not.
        """
        box = self._page.evaluate(
            f"(() => {{ const e = {self._element_js()}; if (!e) return null; "
            "e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect(); "
            "return {x: r.x + r.width / 2, y: r.y + r.height / 2}; })()"
        )
        if not box:
            raise CdpError(f"cannot click {self._selector!r}: no element matched")
        for event_type in ("mousePressed", "mouseReleased"):
            self._page.send(
                "Input.dispatchMouseEvent",
                {
                    "type": event_type,
                    "x": box["x"],
                    "y": box["y"],
                    "button": "left",
                    "clickCount": 1,
                },
            )

    def fill(self, text: str) -> None:
        """Focus the element, clear it, and insert the text as typed input.

        ``Input.insertText`` is used rather than assigning ``innerText``: the
        composer is a ProseMirror contenteditable that rebuilds its document
        from input events, so an assignment leaves it looking filled and
        sending nothing.
        """
        cleared = self._page.evaluate(
            f"(() => {{ const e = {self._element_js()}; if (!e) return false; e.focus(); "
            "if ('value' in e) { e.value = ''; } "
            "else { const s = window.getSelection(); const r = document.createRange(); "
            "r.selectNodeContents(e); s.removeAllRanges(); s.addRange(r); } "
            "return true; })()"
        )
        if not cleared:
            raise CdpError(f"cannot fill {self._selector!r}: no element matched")
        self._page.send("Input.insertText", {"text": text})

    def set_input_files(self, payloads: list[dict]) -> None:
        """Hand file bytes to an ``<input type=file>`` without a shared filesystem.

        ``DOM.setFileInputFiles`` would need the paths to exist for the browser
        process. On the venue topology the browser is Chrome for Android and the
        files are the server's, so the bytes travel in the message instead.

        Each payload is Playwright's shape: ``{name, mimeType, buffer}``.
        """
        files = [
            {
                "name": payload["name"],
                "type": payload.get("mimeType", "application/octet-stream"),
                "data": base64.b64encode(payload["buffer"]).decode("ascii"),
            }
            for payload in payloads
        ]
        attached = self._page.evaluate(
            f"(() => {{ const e = {self._element_js()}; if (!e) return false; "
            f"const files = {json.dumps(files)}; const dt = new DataTransfer(); "
            "for (const f of files) { const bin = atob(f.data); "
            "const bytes = new Uint8Array(bin.length); "
            "for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i); "
            "dt.items.add(new File([bytes], f.name, {type: f.type})); } "
            "e.files = dt.files; "
            "e.dispatchEvent(new Event('change', {bubbles: true})); "
            "return true; })()"
        )
        if not attached:
            raise CdpError(f"cannot attach files to {self._selector!r}: no element matched")


class Page:
    def __init__(self, connection: _Connection, target_id: str, session_id: str):
        self._connection = connection
        self.target_id = target_id
        self.session_id = session_id
        self.keyboard = Keyboard(self)

    def send(self, method: str, params: dict | None = None):
        return self._connection.send(method, params, session_id=self.session_id)

    def evaluate(self, expression: str):
        result = self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        if result.get("exceptionDetails"):
            raise CdpError(f"page script failed: {result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    @property
    def url(self) -> str:
        return str(self.evaluate("document.location.href") or "")

    def goto(self, url: str, *, wait_until: str = "domcontentloaded", timeout_s: float = 30.0):
        self.send("Page.navigate", {"url": url})
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            state = self.evaluate("document.readyState")
            if state in ("interactive", "complete"):
                return
            time.sleep(0.1)
        raise CdpError(f"{url} did not reach {wait_until} within {timeout_s:g}s")

    def locator(self, selector: str) -> Locator:
        return Locator(self, selector)


class Context:
    """Every page target on the browser. Chrome for Android has one profile."""

    def __init__(self, browser: "Browser"):
        self._browser = browser

    @property
    def pages(self) -> list[Page]:
        return self._browser.attach_pages()

    def new_page(self) -> Page:
        return self._browser.new_page()


class Browser:
    def __init__(self, endpoint: str, *, timeout_s: float = DEFAULT_TIMEOUT_S):
        self.endpoint = endpoint.rstrip("/")
        version = _http_json(f"{self.endpoint}/json/version", timeout_s)
        ws_url = version.get("webSocketDebuggerUrl")
        if not ws_url:
            raise CdpError(f"{self.endpoint}/json/version carries no webSocketDebuggerUrl")
        self._connection = _Connection(ws_url, timeout_s=timeout_s)
        self._sessions: dict[str, str] = {}

    @property
    def contexts(self) -> list[Context]:
        return [Context(self)]

    def new_context(self) -> Context:
        return Context(self)

    def _attach(self, target_id: str) -> Page:
        session_id = self._sessions.get(target_id)
        if session_id is None:
            result = self._connection.send(
                "Target.attachToTarget", {"targetId": target_id, "flatten": True}
            )
            session_id = result["sessionId"]
            self._sessions[target_id] = session_id
        return Page(self._connection, target_id, session_id)

    def attach_pages(self) -> list[Page]:
        targets = self._connection.send("Target.getTargets").get("targetInfos", [])
        pages = []
        for target in targets:
            if target.get("type") != "page":
                continue
            try:
                pages.append(self._attach(target["targetId"]))
            except CdpError:
                continue
        return pages

    def new_page(self, url: str = "about:blank") -> Page:
        result = self._connection.send("Target.createTarget", {"url": url})
        return self._attach(result["targetId"])

    def close(self) -> None:
        """Drop this client's socket. It never closes the operator's browser.

        Playwright's ``connect_over_cdp`` browser handle behaves the same way,
        and the difference matters here: the browser is the operator's own
        signed-in Chrome, not one this process started.
        """
        self._connection.close()


def connect_over_cdp(endpoint: str, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> Browser:
    return Browser(endpoint, timeout_s=timeout_s)
