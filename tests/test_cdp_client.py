"""The CDP client's own side of the boundary, without a browser.

What a stub can prove is that the right CDP call carries the right payload:
that ``last`` addresses the last match and not the first, that file bytes reach
the page as base64 with their real name and type, and that one refusal from the
endpoint is retried instead of reported as an absent browser.

What it cannot prove is that Chrome accepts any of it. That was measured
separately against F-51F / Chrome 153.0.8010.36 and is recorded in
``docs/hardware-measurements.md`` §F-6.
"""

from __future__ import annotations

import base64
import json

import pytest

from app.solvers import cdp


class FakePage(cdp.Page):
    """A page that records commands instead of sending them."""

    def __init__(self, values=None):
        self.sent: list[tuple[str, dict]] = []
        self.evaluated: list[str] = []
        self._values = list(values or [])
        self.keyboard = cdp.Keyboard(self)

    def send(self, method, params=None):
        self.sent.append((method, params or {}))
        return {}

    def evaluate(self, expression):
        self.evaluated.append(expression)
        return self._values.pop(0) if self._values else None


def test_last_addresses_the_final_match_and_first_the_opening_one():
    page = FakePage(values=["tail", "head"])
    assert page.locator("p").last.inner_text() == "tail"
    assert page.locator("p").first.inner_text() == "head"
    assert "n.length + -1" in page.evaluated[0]
    assert "[0 < 0 ? n.length + 0 : 0]" in page.evaluated[1]


def test_count_asks_for_the_selector_and_returns_an_int():
    page = FakePage(values=[3])
    assert page.locator(".x").count() == 3
    assert "document.querySelectorAll('.x').length" in page.evaluated[0]


def test_fill_focuses_then_types_rather_than_assigning_text():
    """ProseMirror rebuilds from input events; an assignment sends nothing."""
    page = FakePage(values=[True])
    page.locator("#prompt-textarea").fill("第2問 の答え")
    assert "e.focus()" in page.evaluated[0]
    assert page.sent == [("Input.insertText", {"text": "第2問 の答え"})]


def test_fill_refuses_when_no_element_matched():
    page = FakePage(values=[False])
    with pytest.raises(cdp.CdpError, match="cannot fill"):
        page.locator("#missing").fill("x")
    assert page.sent == []


def test_set_input_files_carries_the_bytes_name_and_type():
    page = FakePage(values=[True])
    page.locator("input#upload-files").set_input_files(
        [{"name": "pages.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4 body"}]
    )
    script = page.evaluated[0]
    payload = json.loads(script[script.index("[{") : script.index("}]") + 2])
    assert payload[0]["name"] == "pages.pdf"
    assert payload[0]["type"] == "application/pdf"
    assert base64.b64decode(payload[0]["data"]) == b"%PDF-1.4 body"
    assert "new DataTransfer()" in script and "e.files = dt.files" in script


def test_press_enter_sends_a_real_key_event_pair():
    page = FakePage()
    page.keyboard.press("Enter")
    assert [method for method, _ in page.sent] == [
        "Input.dispatchKeyEvent",
        "Input.dispatchKeyEvent",
    ]
    down, up = (params for _, params in page.sent)
    assert down["type"] == "keyDown" and down["text"] == "\r"
    assert up["type"] == "keyUp"


def test_click_calls_the_element_rather_than_aiming_at_coordinates():
    """A coordinate mouse event did not submit chatgpt.com's composer."""
    page = FakePage(values=[True])
    page.locator("#go").click()
    assert "e.click()" in page.evaluated[0]
    assert page.sent == []

    empty = FakePage(values=[False])
    with pytest.raises(cdp.CdpError, match="cannot click"):
        empty.locator("#gone").click()


def test_the_endpoint_probe_retries_before_calling_the_browser_absent(monkeypatch):
    """Measured: the endpoint refused twice, then served the version JSON."""
    calls = {"n": 0}

    class Response:
        def read(self):
            return b'{"Browser": "Chrome/153.0.8010.36"}'

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def flaky(url, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("Remote end closed connection without response")
        return Response()

    monkeypatch.setattr(cdp.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(cdp.time, "sleep", lambda _s: None)
    assert cdp._http_json("http://127.0.0.1:9222/json/version", 10.0)["Browser"].startswith(
        "Chrome/"
    )
    assert calls["n"] == 3


def test_the_probe_gives_up_with_the_endpoint_named(monkeypatch):
    monkeypatch.setattr(
        cdp.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("refused"))
    )
    monkeypatch.setattr(cdp.time, "sleep", lambda _s: None)
    with pytest.raises(cdp.CdpError, match="127.0.0.1:9222"):
        cdp._http_json("http://127.0.0.1:9222/json/version", 10.0)
