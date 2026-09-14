"""The phone deployment's OpenAI-compatible HTTP client.

The server on the phone cannot install the openai SDK (Rust wheels), so the
solver reaches the local llama-server through app.llm_http instead. These tests
pin the surface app.llm._text_openai actually calls.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.llm import LLMClient
from app.llm_http import OpenAICompatibleSDK


class _Handler(BaseHTTPRequestHandler):
    received: dict = {}
    choices: list = [{"message": {"role": "assistant", "content": "13"}}]

    def do_POST(self):  # noqa: N802 - http.server's required name
        body = self.rfile.read(int(self.headers["Content-Length"]))
        _Handler.received = {
            "path": self.path,
            "auth": self.headers.get("Authorization"),
            "payload": json.loads(body),
        }
        reply = json.dumps({"choices": _Handler.choices}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, *args):  # keep pytest output clean
        return


@pytest.fixture
def server():
    _Handler.choices = [{"message": {"role": "assistant", "content": "13"}}]
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}/v1"
    httpd.shutdown()


def test_completion_reaches_the_endpoint_and_returns_the_text(server):
    sdk = OpenAICompatibleSDK(server, api_key="secret-local")
    resp = sdk.chat.completions.create(
        model="local",
        max_tokens=64,
        messages=[{"role": "user", "content": "a+b=5, ab=6 のとき a^2+b^2"}],
    )

    assert resp.choices[0].message.content == "13"
    assert _Handler.received["path"] == "/v1/chat/completions"
    assert _Handler.received["auth"] == "Bearer secret-local"
    assert _Handler.received["payload"]["model"] == "local"
    assert _Handler.received["payload"]["max_tokens"] == 64


def test_llm_client_drives_the_shim_like_the_real_sdk(server):
    """The shim is only useful if the existing openai path accepts it."""
    client = LLMClient(OpenAICompatibleSDK(server), provider="openai", model="local")

    assert client.complete(system="s", prompt="p") == "13"
    sent = _Handler.received["payload"]["messages"]
    assert [m["role"] for m in sent] == ["system", "user"]


def test_an_empty_choices_list_is_an_error_not_an_empty_answer(server):
    """A blank answer must fail the tier so the fallback runs, not look solved."""
    _Handler.choices = []
    sdk = OpenAICompatibleSDK(server)

    with pytest.raises(RuntimeError, match="no choices"):
        sdk.chat.completions.create(model="local", messages=[{"role": "user", "content": "x"}])
