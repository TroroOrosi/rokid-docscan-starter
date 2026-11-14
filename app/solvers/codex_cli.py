"""The official Codex CLI as a booklet solver: ``ROKID_SOLVER=codex-cli``.

One ``codex exec`` request carries every page image and returns the whole answer list. It uses the operator's own
ChatGPT sign-in (``codex login --device-auth``, done once on the phone), no API key and no web page, so a change to
ChatGPT's page cannot stop it. Measured in the phone's Termux on 2026-11-14 (docs/hardware-measurements.md, M-21):
47 page images in one request, answered in 6 min 26 s with 8.7 MB sent.

Two things that phone needs, both handled here:

- Android has no ``/etc/resolv.conf`` and the CLI is a static binary, so it cannot resolve names. While it runs it is
  given ``HTTPS_PROXY`` pointing at a loopback CONNECT proxy in this process, which resolves through the system.
- It finds no certificate store; ``SSL_CERT_FILE`` is pointed at Termux's bundle when that exists.

The CLI takes images only. A booklet with audio (listening, mixed English) is refused before anything runs, with the
error the server answers by handing the booklet to the next route.

Settings: ``ROKID_CODEX_BIN`` (default: the Termux npm install, else ``codex`` on PATH), ``ROKID_CODEX_MODEL``
(``gpt-6.1-sol``), ``ROKID_CODEX_EFFORT`` (``xhigh``), ``ROKID_CODEX_TIMEOUT_S`` (3600). Sending is gated by
``ROKID_CHATGPT_SEND_ENABLED`` like every other route that spends the operator's usage.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import select
import shutil
import socket
import socketserver
import subprocess
import tempfile
import threading
from pathlib import Path

from .. import config
from ..llm import extract_json
from ..source_bundle import source_images
from .base import Question, Solver, SolveResult
from .chatgpt_web import (_ALL_TASK, _booklet_chat_key, _booklet_replies, ChatGptWebAuthenticationRequired,
                          ChatGptWebError, ChatGptWebRateLimit, ChatGptWebReplyIncomplete, ChatGptWebSendNotAuthorized,
                          chatgpt_send_enabled)
from .llm_adapter import _ANSWER_ONLY_SYSTEM

_TERMUX_BINARY = ("lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-arm64/vendor/"
                  "aarch64-unknown-linux-musl/bin/codex")
_IMAGES_NOTE = ("\n\nThe attached images are the booklet pages in capture order (page001.jpg is capture page 1). "
                "Do not run commands or use tools; read the images directly and reply once with the JSON object only.")
_LIMIT = re.compile(r"usage limit|rate limit|quota", re.IGNORECASE)


def _command() -> list[str]:
    """The CLI's own binary. The npm launcher needs /usr/bin/env, which Termux does not have."""
    named = os.environ.get("ROKID_CODEX_BIN", "")
    if named:
        return [named] if Path(named).is_file() else []
    termux = Path(os.environ.get("PREFIX", "")) / _TERMUX_BINARY
    if os.environ.get("PREFIX") and termux.is_file():
        return [str(termux)]
    found = shutil.which("codex")
    return [found] if found else []


def _needs_proxy() -> bool:
    return not Path("/etc/resolv.conf").exists()


def _connect_upstream(address, timeout=None):
    return socket.create_connection(address, timeout=timeout)


class _Tunnel(socketserver.BaseRequestHandler):
    """CONNECT to port 443 only. Nothing in the tunnel is read; the name is resolved here, by the system."""

    def handle(self):
        client = self.request
        client.settimeout(15)
        head = b""
        try:
            while b"\r\n\r\n" not in head and len(head) < 8192:
                chunk = client.recv(4096)
                if not chunk:
                    return
                head += chunk
            method, target, _ = head.split(b"\r\n", 1)[0].decode("ascii").split(" ", 2)
            host, _, port = target.rpartition(":")
            if method != "CONNECT" or port != "443" or not host:
                client.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
                return
            upstream = _connect_upstream((host, 443), timeout=20)
        except (OSError, ValueError):
            with contextlib.suppress(OSError):
                client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            return
        with upstream:
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            client.settimeout(None)
            sockets = [client, upstream]
            while True:
                readable, _, _ = select.select(sockets, [], [], 600)
                if not readable:
                    return
                for source in readable:
                    try:
                        data = source.recv(65536)
                        if not data:
                            return
                        (upstream if source is client else client).sendall(data)
                    except OSError:
                        return


class _Proxy(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


@contextlib.contextmanager
def name_resolving_proxy():
    """A loopback CONNECT proxy for the life of one run; yields its port."""
    server = _Proxy(("127.0.0.1", 0), _Tunnel)
    thread = threading.Thread(target=server.serve_forever, name="codex-name-proxy", daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return re.sub(r"\x1b\[[0-9;]*m", "", lines[-1])[:300] if lines else ""


class CodexCliSolver(Solver):
    name = "codex-cli"
    provider_version = "codex-exec-v1"
    offline = False
    placeholder = False
    accepts_images = True

    @staticmethod
    def _signed_in() -> bool:
        command = _command()
        if not command:
            return False
        try:
            status = subprocess.run([*command, "login", "status"], capture_output=True, text=True, timeout=30,
                                    stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return (status.stdout + status.stderr).strip().startswith("Logged in")

    def ready(self) -> bool:
        return self._signed_in()

    @staticmethod
    def _kept(question: Question) -> Path | None:
        """Where this exact booklet's reply is kept: its session's key and the hash of its original pages."""
        key = _booklet_chat_key(question, None)
        if not key:
            return None
        return Path(config.DATA_DIR) / "codex-cli" / (hashlib.sha256(key.encode()).hexdigest() + ".json")

    def answer_all(self, *, question: Question) -> list:
        if not chatgpt_send_enabled():
            raise ChatGptWebSendNotAuthorized("sending is not authorized")
        if question.audio_path or question.booklet_stage != "single":
            raise ChatGptWebError("codex-cli takes images only; this booklet needs audio")
        if not question.document_pages:
            raise ValueError("answering the booklet needs the original pages")
        model = os.environ.get("ROKID_CODEX_MODEL") or "gpt-6.1-sol"
        extras = {"source": self.name, "provider": "codex", "model": model}
        kept = self._kept(question)
        if kept is not None and kept.is_file():
            try:
                # Already answered and paid for: a repeated finalize or a restart reads it, as the Chat route reads its chat.
                return _booklet_replies(json.loads(kept.read_text(encoding="utf-8")), subject=question.subject, extras=extras)
            except ValueError:
                pass
        if not self._signed_in():
            raise ChatGptWebAuthenticationRequired("the Codex CLI is missing or not signed in; nothing sent")
        data = extract_json(self._run(question, model))
        replies = _booklet_replies(data, subject=question.subject, extras=extras)
        if kept is not None:
            kept.parent.mkdir(parents=True, exist_ok=True)
            temporary = kept.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, kept)
        return replies

    @staticmethod
    def _run(question: Question, model: str) -> str:
        effort = os.environ.get("ROKID_CODEX_EFFORT") or "xhigh"
        timeout = float(os.environ.get("ROKID_CODEX_TIMEOUT_S") or 3600)
        environment = dict(os.environ)
        bundle = Path(os.environ.get("PREFIX", "")) / "etc/tls/cert.pem"
        if os.environ.get("PREFIX") and bundle.is_file():
            environment.setdefault("SSL_CERT_FILE", str(bundle))
        with tempfile.TemporaryDirectory(prefix="rokid-codex-") as directory, contextlib.ExitStack() as stack:
            names = []
            for payload in source_images(question.document_pages):
                (Path(directory) / payload["name"]).write_bytes(payload["buffer"])
                names.append(payload["name"])
            if _needs_proxy():
                environment["HTTPS_PROXY"] = f"http://127.0.0.1:{stack.enter_context(name_resolving_proxy())}"
            reply = Path(directory) / "reply.json"
            command = [*_command(), "exec", "-m", model, "-c", f"model_reasoning_effort={effort}", "-s", "read-only",
                       "--skip-git-repo-check", "--ephemeral", *(part for name in names for part in ("-i", name)),
                       "-o", str(reply), _ANSWER_ONLY_SYSTEM + "\n\n" + _ALL_TASK + _IMAGES_NOTE]
            try:
                done = subprocess.run(command, cwd=directory, env=environment, capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
            except subprocess.TimeoutExpired as error:
                raise ChatGptWebReplyIncomplete("the Codex CLI did not finish in time") from error
            except OSError as error:
                raise ChatGptWebError(f"the Codex CLI could not start: {type(error).__name__}") from error
            output = done.stdout + "\n" + done.stderr
            if done.returncode != 0 or not reply.is_file():
                if _LIMIT.search(output):
                    raise ChatGptWebRateLimit("the Codex CLI reported a usage limit")
                # The CLI's own last line is the only record of why; it names no page content.
                raise ChatGptWebError(f"the Codex CLI ended without a reply: {_last_line(done.stderr) or _last_line(done.stdout)}")
            return reply.read_text(encoding="utf-8")

    def solve(self, *, question: Question, max_answer_len: int = 64) -> SolveResult:
        raise ValueError("codex-cli answers a whole booklet only")
