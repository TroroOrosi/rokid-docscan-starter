"""The official Codex CLI as a booklet solver: ``ROKID_SOLVER=codex-cli``.

One ``codex exec`` request carries every page image and returns the whole answer list. It uses the operator's own
ChatGPT sign-in (``codex login --device-auth``, done once on the phone), no API key and no web page, so a change to
ChatGPT's page cannot stop it. Measured in the phone's Termux on 2026-11-14 (docs/hardware-measurements.md, M-21):
47 page images in one request, answered in 6 min 26 s with 8.7 MB sent.

Two things that phone needs, both handled here:

- Android has no ``/etc/resolv.conf`` and the CLI is a static binary, so it cannot resolve names. While it runs it is
  given ``HTTPS_PROXY`` pointing at a loopback CONNECT proxy in this process, which resolves through the system.
- It finds no certificate store; ``SSL_CERT_FILE`` is pointed at Termux's bundle when that exists.

Each photo goes twice. First a small view of every photo, at low effort, asks where the exam pages are and which way
their lines of text run; then each located page is cut out, enlarged and sent in parts cut along its lines, beside the
small view. Measured on the phone (M-22, M-23): the boxes were right on all 27 real photos, dark or bright desk, where
brightness and text-density rules each failed on some background. Characters of 15.8 px were read with 18% wrong as
photographed; at twice the size, six reads each, with 4.10% as one image and 1.59% as two strips along the lines. One
input read twice differs by up to 6.5 points. A photo with no page found, or a failed first request, is sent as the
Chat route sends it. A booklet too large for the model's context is enlarged less, not refused.

The CLI takes images only. A booklet with audio (listening, mixed English) is refused before anything runs, with the
error the server answers by handing the booklet to the next route.

Settings: ``ROKID_CODEX_BIN`` (default: the Termux npm install, else ``codex`` on PATH), ``ROKID_CODEX_MODEL``
(``gpt-6.1-sol``), ``ROKID_CODEX_EFFORT`` (``xhigh``), ``ROKID_CODEX_TIMEOUT_S`` (3600), ``ROKID_CODEX_LOCATE`` (``1``;
``0`` sends photos as the Chat route does), ``ROKID_CODEX_PAGE_LONG`` (the enlarged page's long side, 2540 px). Sending is gated by
``ROKID_CHATGPT_SEND_ENABLED`` like every other route that spends the operator's usage.

``check()`` is the proof before use: one request at low effort with a generated picture of three to seven black squares,
which the model counts. Measured on the phone on 2026-11-15 (M-23): 5 s, 14,834 input tokens of which 12,160 were cached.
It shows the CLI is signed in, the network and the image path work and no limit is in force at that moment. The CLI's
event stream (``--json``, 0.169.0) carries token counts only, so how much allowance is left cannot be read.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import random
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
from PIL import Image

from ..source_bundle import MAX_SCALE, _readable, page_tiles, source_images
from .base import Question, Solver, SolveResult
from .chatgpt_web import (_ALL_TASK, _booklet_chat_key, _booklet_replies, ChatGptWebAuthenticationRequired,
                          ChatGptWebError, ChatGptWebRateLimit, ChatGptWebReplyIncomplete, ChatGptWebSendNotAuthorized,
                          chatgpt_send_enabled)
from .llm_adapter import _ANSWER_ONLY_SYSTEM

_TERMUX_BINARY = ("lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-arm64/vendor/"
                  "aarch64-unknown-linux-musl/bin/codex")
_NO_TOOLS = " Do not run commands or use tools; read the images directly and reply once with the JSON object only."
_IMAGES_NOTE = "\n\nThe attached images are the booklet pages in capture order (page001.jpg is capture page 1)." + _NO_TOOLS
_TILES_NOTE = (
    "\n\nHow the attached images are named. overviewNNN.jpg is the whole photo of capture page NNN at low resolution: use it "
    "for layout and for anything outside the pages, never to read text. pageNNN-PT.jpg is from that same photo: printed page P "
    "in reading order within the photo (1 is read first), part T (a, b, c ...) of that one page, enlarged. A page is cut "
    "along its lines of text and its parts come in reading order: for vertical text, strips from the right edge leftwards; "
    "otherwise bands from the top down. Neighbouring parts overlap: text in an overlap appears twice and is one text. Read "
    "the parts of a page together as one page. pageNNN.jpg without P and T is a whole photo in which no separate page was "
    "found." + _NO_TOOLS)
_LOCATE_PROMPT = (
    "Each attached image is a photo, taken through smart glasses, of exam paper lying on a desk; other things are in view. "
    "For each image, in the order attached (photo001.jpg is index 1), return the regions that hold exam pages: one region per "
    "printed page. An open booklet shows two pages: return two regions, the page that is read first first. Give each region as "
    "left, top, right and bottom in thousandths of the image's width and height (0 to 1000), covering the whole sheet of that "
    "page with its margins as far as it is in the photo; where the page runs past the photo's edge, use the edge. For each "
    "region also give vertical_text: true when its main text is written vertically (lines running from top to bottom and "
    "read from the right, as in Japanese vertical writing), false when it is written in horizontal lines. Return an "
    "empty list for an image that shows no exam page. Do not run commands or use tools; look at the images and reply once.")
_INTEGER = {"type": "integer"}
_REGION = {"type": "object", "additionalProperties": False, "required": ["left", "top", "right", "bottom", "vertical_text"],
           "properties": {"left": _INTEGER, "top": _INTEGER, "right": _INTEGER, "bottom": _INTEGER,
                          "vertical_text": {"type": "boolean"}}}
_LOCATE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["images"], "properties": {"images": {
    "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["index", "pages"],
                               "properties": {"index": _INTEGER, "pages": {"type": "array", "items": _REGION}}}}}}
_REGION_MARGIN = 0.03  # of the region's own size on each side: the boxes sat on the sheet's edge, sometimes just inside
# What one request can carry, measured on the phone on 2026-11-15 (M-23).
_CONTEXT_TOKENS = 475_000  # 95% of the 500,000 the CLI's own model list gives gpt-6.1-sol
_FIXED_TOKENS = 115_000    # the CLI's own 15,000 (14,650 with no image) and 100,000 kept for reasoning and the reply
_TOKENS_PER_PATCH = 1.21   # an image's cost per 32-px patch, in proportion from 512x512 to 3000x3000


def _target_long(sizes: list[tuple[int, int]], views: int, wanted: int) -> int:
    """``wanted``, or the largest long side at which every page, enlarged and cut, still fits the model's context."""
    room = (_CONTEXT_TOKENS - _FIXED_TOKENS) / _TOKENS_PER_PATCH - views * 800  # a 1024-px view is 768 patches

    def patches(target: int) -> float:  # with a tenth more for the parts' overlap and their rounding up
        return sum(width * height * min(MAX_SCALE, max(1.0, target / max(width, height))) ** 2 for width, height in sizes) / 1024 * 1.1

    if patches(wanted) <= room:
        return wanted
    low, high = 1, wanted  # the cost never falls as the target grows
    while high - low > 16:
        middle = (low + high) // 2
        low, high = (middle, high) if patches(middle) <= room else (low, middle)
    return low


def _regions(reply: str, photos: int) -> dict[int, list[tuple[float, float, float, float, bool | None]]]:
    """{photo number: its pages in the order given, each (left, top, right, bottom as fractions, vertical text or
    None when not said)}. Anything that makes no sense is left out."""
    try:
        images = extract_json(reply)["images"]
    except (ValueError, KeyError, TypeError):
        return {}
    found: dict[int, list[tuple[float, float, float, float, bool | None]]] = {}
    for image in images if isinstance(images, list) else []:
        try:
            index, pages = image["index"], image["pages"]
            boxes = [(page["left"] / 1000, page["top"] / 1000, page["right"] / 1000, page["bottom"] / 1000,
                      page.get("vertical_text") if isinstance(page.get("vertical_text"), bool) else None) for page in pages]
        except (KeyError, TypeError, AttributeError):
            continue
        if type(index) is not int or not 1 <= index <= photos or index in found:
            continue
        boxes = [box for box in boxes if all(isinstance(v, float) and 0 <= v <= 1 for v in box[:4])
                 and box[2] - box[0] >= 0.05 and box[3] - box[1] >= 0.05]
        if boxes and len(boxes) <= 8:
            found[index] = boxes
    return found
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
    def _exec(directory: Path, environment: dict, *, model: str, effort: str, images: list[str], prompt: str,
              timeout: float, schema: dict | None = None) -> str:
        """Run the CLI once in ``directory`` on the image files named there; its reply text."""
        reply = directory / "reply.json"
        reply.unlink(missing_ok=True)
        command = [*_command(), "exec", "-m", model, "-c", f"model_reasoning_effort={effort}", "-s", "read-only",
                   "--skip-git-repo-check", "--ephemeral", *(part for name in images for part in ("-i", name))]
        if schema is not None:
            (directory / "schema.json").write_text(json.dumps(schema), encoding="utf-8")
            command += ["--output-schema", "schema.json"]
        command += ["-o", str(reply), prompt]
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

    @classmethod
    def _located(cls, directory: Path, environment: dict, pages: list[dict], *, model: str, timeout: float) -> list[str] | None:
        """Write the enlarged page tiles and small views into ``directory``; their names in sending order.

        None when the pages could not be located at all (the caller sends the photos as before). A usage limit is raised.
        """
        ordered = sorted(pages, key=lambda page: page["page_number"])
        photos = []
        for page in ordered:
            with Image.open(page["image_path"]) as source:
                photos.append(_readable(source.convert("RGB")))
        views = []
        for number, photo in enumerate(photos, 1):
            view = photo.copy()
            view.thumbnail((1024, 1024))
            view.save(directory / f"photo{number:03d}.jpg", quality=85)
            views.append(f"photo{number:03d}.jpg")
        try:
            reply = cls._exec(directory, environment, model=model, effort="low", images=views, prompt=_LOCATE_PROMPT,
                              timeout=min(timeout, 900), schema=_LOCATE_SCHEMA)
        except ChatGptWebRateLimit:
            raise
        except ChatGptWebError:
            return None
        found = _regions(reply, len(photos))
        if not found:
            return None
        crops: dict[tuple[int, int], tuple[Image.Image, bool | None]] = {}
        for number, photo in enumerate(photos, 1):
            for printed, (left, top, right, bottom, vertical) in enumerate(found.get(number, ()), 1):
                pad_x, pad_y = (right - left) * _REGION_MARGIN, (bottom - top) * _REGION_MARGIN
                box = (max(0, round((left - pad_x) * photo.width)), max(0, round((top - pad_y) * photo.height)),
                       min(photo.width, round((right + pad_x) * photo.width)), min(photo.height, round((bottom + pad_y) * photo.height)))
                crops[number, printed] = (photo.crop(box), vertical)
        target = _target_long([crop.size for crop, _ in crops.values()], len(found),
                              int(os.environ.get("ROKID_CODEX_PAGE_LONG") or 2540))
        names = []
        for number, (page, photo) in enumerate(zip(ordered, photos), 1):
            label = f"{page['page_number']:03d}"
            if number not in found:
                # No separate page here: this photo as the Chat route prepares it (paper crop, fold split), at its own size.
                for payload in source_images([page]):
                    (directory / payload["name"]).write_bytes(payload["buffer"])
                    names.append(payload["name"])
                continue
            overview = f"overview{label}.jpg"
            (directory / f"photo{number:03d}.jpg").replace(directory / overview)
            names.append(overview)
            for printed in range(1, len(found[number]) + 1):
                crop, vertical = crops[number, printed]
                for tile_number, (tile, _) in enumerate(page_tiles(crop, vertical_text=vertical, target_long=target)):
                    name = f"page{label}-{printed}{chr(97 + tile_number)}.jpg"
                    tile.save(directory / name, format="JPEG", quality=92, subsampling=0)
                    names.append(name)
        return names

    @staticmethod
    @contextlib.contextmanager
    def _workplace():
        """A directory of its own and the environment the CLI needs on this host, for as long as one request takes."""
        environment = dict(os.environ)
        bundle = Path(os.environ.get("PREFIX", "")) / "etc/tls/cert.pem"
        if os.environ.get("PREFIX") and bundle.is_file():
            environment.setdefault("SSL_CERT_FILE", str(bundle))
        with tempfile.TemporaryDirectory(prefix="rokid-codex-") as folder, contextlib.ExitStack() as stack:
            if _needs_proxy():
                environment["HTTPS_PROXY"] = f"http://127.0.0.1:{stack.enter_context(name_resolving_proxy())}"
            yield Path(folder), environment

    check_sends = True

    def check(self) -> None:
        if not chatgpt_send_enabled():
            raise ChatGptWebSendNotAuthorized("sending is not authorized")
        if not self._signed_in():
            raise ChatGptWebAuthenticationRequired("the Codex CLI is missing or not signed in; nothing sent")
        squares = random.randint(3, 7)  # a different picture each time: the reply has to come from the picture
        picture = Image.new("RGB", (512, 256), "white")
        for index in range(squares):
            picture.paste((0, 0, 0), (24 + index * 68, 100, 72 + index * 68, 148))
        with self._workplace() as (directory, environment):
            picture.save(directory / "canary.jpg", quality=85)
            reply = self._exec(directory, environment, model=os.environ.get("ROKID_CODEX_MODEL") or "gpt-6.1-sol",
                               effort="low", images=["canary.jpg"], timeout=120,
                               prompt="How many black squares are in the attached image? Do not run commands or use "
                                      "tools. Reply with the number only.")
        if re.sub(r"\D", "", reply) != str(squares):
            raise ChatGptWebError("the check's reply was not the count the picture shows")

    @classmethod
    def _run(cls, question: Question, model: str) -> str:
        effort = os.environ.get("ROKID_CODEX_EFFORT") or "xhigh"
        timeout = float(os.environ.get("ROKID_CODEX_TIMEOUT_S") or 3600)
        with cls._workplace() as (directory, environment):
            names = None
            if (os.environ.get("ROKID_CODEX_LOCATE") or "1") != "0":
                names = cls._located(directory, environment, question.document_pages, model=model, timeout=timeout)
            note = _TILES_NOTE
            if names is None:
                names, note = [], _IMAGES_NOTE
                for payload in source_images(question.document_pages):
                    (directory / payload["name"]).write_bytes(payload["buffer"])
                    names.append(payload["name"])
            return cls._exec(directory, environment, model=model, effort=effort, images=names,
                             prompt=_ANSWER_ONLY_SYSTEM + "\n\n" + _ALL_TASK + note, timeout=timeout)

    def solve(self, *, question: Question, max_answer_len: int = 64) -> SolveResult:
        raise ValueError("codex-cli answers a whole booklet only")
