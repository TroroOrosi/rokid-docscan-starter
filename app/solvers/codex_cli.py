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

From 2026-11-16 the first request asks for every sheet or part of a sheet that carries exam matter, not for the pages
of a booklet: an answer sheet, a resource card or a narrow strip beside the page is a region too, down to one line of
print high. Only what is in a region is sent at reading size, so when something returned is left out (a box that makes
no sense, a speck, a ninth region) the whole photo goes at its own size beside its regions. No real photo has been
located with this wording yet: the 27 above were located with the earlier one.

The booklet is read twice, by two requests at the same time over the same images, and the two answer lists are
compared (``ROKID_CODEX_READS``, 2; 1 reads once). Measured on the phone on 2026-11-15 (M-23): of 72 answers to kanji
questions read once from a worn photo 5 were wrong, each as confidently as a right one; over every pair of the 18
reads both were wrong in the same way in 1.6% and disagreed in 10.6%. A short answer (a mark, a number, a word) the
reads disagree on keeps the first read's answer and carries a note with the other one; the server shows it as an
answer to review, which the glasses already render. Writing is not compared: two writings of one solution differ.
An answer or a question only one read gave is shown and noted. When one read fails the other answers alone.

The CLI takes images only. A booklet with audio (listening, mixed English) is refused before anything runs, with the
error the server answers by handing the booklet to the next route.

Settings: ``ROKID_CODEX_BIN`` (default: the Termux npm install, else ``codex`` on PATH), ``ROKID_CODEX_MODEL``
(``gpt-6.1-sol``), ``ROKID_CODEX_EFFORT`` (``xhigh``), ``ROKID_CODEX_TIMEOUT_S`` (by the booklet's size, see ``_time_allowed``), ``ROKID_CODEX_LOCATE`` (``1``;
``0`` sends photos as the Chat route does), ``ROKID_CODEX_PAGE_SCALE`` (2: a region cut from a still photo is sent at
this many times its own pixels at least), ``ROKID_CODEX_PAGE_LONG`` (2540 px: the long side a smaller region is
enlarged up to, at most two and a half times; a page recorded as a clip follows this alone, see ``_wanted_scale``),
``ROKID_CODEX_READS`` (2). Sending is gated by
``ROKID_CHATGPT_SEND_ENABLED`` like every other route that spends the operator's usage.

``check()`` is the proof before use: one request at low effort with a generated picture of three to seven black squares,
which the model counts. Measured on the phone on 2026-11-15 (M-23): 5 s, 14,834 input tokens of which 12,160 were cached.
It shows the CLI is signed in, the network and the image path work and no limit is in force at that moment. The CLI's
event stream (``--json``, 0.169.0) carries token counts only, so how much allowance is left cannot be read.
"""
from __future__ import annotations

import concurrent.futures
import contextlib
import hashlib
import json
import math
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
import unicodedata
from pathlib import Path

from .. import config
from ..llm import extract_json
from PIL import Image

from ..source_bundle import MAX_SCALE, _readable, page_tiles, source_images
from .base import Question, Solver, SolveResult
from .chatgpt_web import (_ALL_TASK, _booklet_chat_key, _booklet_replies, ChatGptWebAuthenticationRequired,
                          ChatGptWebError, ChatGptWebRateLimit, ChatGptWebReplyIncomplete, ChatGptWebSendNotAuthorized,
                          chatgpt_send_enabled, clip_page, grey_note)
from .llm_adapter import _ANSWER_ONLY_SYSTEM

_TERMUX_BINARY = ("lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-arm64/vendor/"
                  "aarch64-unknown-linux-musl/bin/codex")
_NO_TOOLS = " Do not run commands or use tools; read the images directly and reply once with the JSON object only."
_IMAGES_NOTE = "\n\nThe attached images are the booklet pages in capture order (page001.jpg is capture page 1)." + _NO_TOOLS
_TILES_NOTE = (
    "\n\nHow the attached images are named. overviewNNN.jpg is the whole photo of capture page NNN at low resolution: use it "
    "for layout and to see where each region lies, never to read text. pageNNN-ST.jpg is from that same photo: region S, a "
    "sheet or a part of a sheet that carries exam matter (a problem page, an answer sheet, a resource sheet, a card, a "
    "strip), numbered in reading order within the photo (1 is read first); part T (a, b, c ...) of that one region, "
    "enlarged. A region is cut along its lines of text and its parts come in reading order: for vertical text, strips from "
    "the right edge leftwards; "
    "otherwise bands from the top down. A part too long for one image is cut again across its lines and its pieces take "
    "the next letters: a band's from left to right, a strip's from top to bottom; a line that crosses that cut goes on "
    "in the next piece. Neighbouring parts overlap: text in an overlap appears twice and is one text. Read "
    "the parts of a region together as one sheet. pageNNN.jpg without S and T (or pageNNNR.jpg and pageNNNL.jpg, its right "
    "and left half) is a whole photo at its own size: no region was found in it, or its regions may not cover everything "
    "in it; read from it whatever no region shows. S and T only name files: in the answers, pages are capture page numbers "
    "NNN. The edge of a part or of a region is a cut made here, not where the capture ends: what a capture leaves out is "
    "judged at the photo's own edge, which overviewNNN.jpg shows." + _NO_TOOLS)
# Until 2026-11-16 this asked for "exam pages", "one region per printed page", of "an open booklet": an answer sheet, a
# resource card or a strip beside the page was not asked for, and what is not boxed goes out only as the small view.
_LOCATE_PROMPT = (
    "Each attached image is a photo, taken through smart glasses, of exam papers on a desk; other things are in view. "
    "For each image, in the order attached (photo001.jpg is index 1), return a region for every sheet, or part of a sheet, "
    "that carries exam matter: problem pages, answer sheets, resource or data sheets, cards and narrow strips alike, "
    "however small in the photo. Give each printed page or separate sheet its own region where they can be told apart (an "
    "open booklet or a folded sheet shows two pages: two regions); one large sheet with no such division is one region. "
    "List an image's regions in the order they are read. Give each region as "
    "left, top, right and bottom in thousandths of the image's width and height (0 to 1000), covering that sheet or page "
    "with its margins as far as it is in the photo; where it runs past the photo's edge, use the edge. For each "
    "region also give vertical_text: true when its main text is written vertically (lines running from top to bottom and "
    "read from the right, as in Japanese vertical writing), false when it is written in horizontal lines. Return an "
    "empty list for an image that shows no exam matter. Do not run commands or use tools; look at the images and reply once.")
_INTEGER = {"type": "integer"}
_REGION = {"type": "object", "additionalProperties": False, "required": ["left", "top", "right", "bottom", "vertical_text"],
           "properties": {"left": _INTEGER, "top": _INTEGER, "right": _INTEGER, "bottom": _INTEGER,
                          "vertical_text": {"type": "boolean"}}}
_LOCATE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["images"], "properties": {"images": {
    "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["index", "regions"],
                               "properties": {"index": _INTEGER, "regions": {"type": "array", "items": _REGION}}}}}}
_REGION_MARGIN = 0.03  # of the region's own size on each side: the boxes sat on the sheet's edge, sometimes just inside
# ... and at least this share of the photo's side (15 to 20 px of 4032x3024). 3% of a strip one line high is under a
# pixel, and a box comes in thousandths read off a view where one pixel is four of the photo's.
_REGION_MARGIN_LEAST = 0.005
# A region's sides as shares of the photo's. The shorter at least 1%: 30 px of a 4032x3024 photo, one line of the
# smallest print the worn photos show (characters of 14 to 16 px) with a little room, and ten steps of the thousandths
# the boxes come in. The longer at least 5%, as both had to be until 2026-11-16: 150 to 200 px, about ten such
# characters. A strip one line high is a region; a box a few characters each way is a speck. No strip has been located
# on a real photo yet: both numbers are from the size of print, not from the model's boxes.
_REGION_SHORT, _REGION_LONG = 0.01, 0.05
_REGIONS_MOST = 8  # of one photo; past it the first are cut out and the photo also goes whole
# What one request can carry, measured on the phone on 2026-11-15 (M-23).
_CONTEXT_TOKENS = 475_000  # 95% of the 500,000 the CLI's own model list gives gpt-6.1-sol
_FIXED_TOKENS = 115_000    # the CLI's own 15,000 (14,650 with no image) and 100,000 kept for reasoning and the reply
_TOKENS_PER_PATCH = 1.21   # an image's cost per 32-px patch, in proportion from 512x512 to 3000x3000


def _wanted_scale(size: tuple[int, int], *, clip: bool) -> float:
    """How many times its own pixels a cut-out region is sent at, when the booklet fits the model's context.

    A region cut from a still photo: ``ROKID_CODEX_PAGE_SCALE`` times (2). Characters of about 16 px were read with
    18% wrong as photographed and with 1.6 to 4% at twice the size in strips, and larger did no better (M-22, M-23).
    Until 2026-11-16 the aim was a long side alone, ``ROKID_CODEX_PAGE_LONG`` (2540 px, twice a B5 page as a spread
    photo shows it), so a large sheet that fills the photo, 3000 px with characters of 14 to 20 px, went out at its own
    size. That long side is still what a smaller region is brought up to, never past ``MAX_SCALE``: every region of
    1270 px and less is sent as it was.

    A page recorded as a clip keeps the long side alone: the image gathered from a clip is already on a grid twice as
    fine as the camera's frame, and what was read of it was read at its own size (M-28, M-29).
    """
    least = 1.0 if clip else float(os.environ.get("ROKID_CODEX_PAGE_SCALE") or 2)
    return min(MAX_SCALE, max(least, float(os.environ.get("ROKID_CODEX_PAGE_LONG") or 2540) / max(size)))


def _target_long(regions: list[tuple[tuple[int, int], float]], spent: float) -> float:
    """The long side no region may be sent past for the booklet to fit the model's context: infinite when every
    region fits at the scale wanted for it, else the largest common one that fits.

    ``regions`` are (size, wanted scale); ``spent`` is what the other images of the request cost, in patches. The
    regions sent largest give way first, and a region is reduced below its own size only when the booklet does not
    fit otherwise. A page gathered from its clip is 3024x4032, about 15,000 tokens when the paper fills it: twenty fit
    at their own size and forty do not. A still's region at twice its size costs four times its own pixels: a sheet
    that fills a 4032x3024 photo is about 58,000 tokens, and six such photos fill the context. A reduced page's
    reading is not measured.
    """
    room = (_CONTEXT_TOKENS - _FIXED_TOKENS) / _TOKENS_PER_PATCH - spent

    def patches(limit: float) -> float:
        # A fifth more than the region's own area: neighbouring parts share 8%, and each part counts in whole patches,
        # up to 7% more for the narrowest (a strip 6000 px long is at most 15 patches wide). A tenth, until
        # 2026-11-16, was 0.4% short for six such strips.
        return sum(width * height * min(wanted, limit / max(width, height)) ** 2
                   for (width, height), wanted in regions) / 1024 * 1.2

    if patches(math.inf) <= room:
        return math.inf
    # The cost never falls as the limit grows. Never under 256 px: with no room at all (whole photos are counted and
    # not reduced, and 25 of 4032x3024 use up the request) a region is still an image, and the CLI's refusal of a
    # request that is too large hands the booklet to the next route, as before.
    low, high = 256.0, max(256.0, *(max(size) * wanted for size, wanted in regions))
    while high - low > 16:
        middle = (low + high) / 2
        low, high = (middle, high) if patches(middle) <= room else (low, middle)
    return low


def _letters(index: int) -> str:
    """a, b ... z, aa, ab ...: a region sent at twice its size can be more than 26 parts."""
    index, last = divmod(index, 26)
    return (_letters(index - 1) if index else "") + chr(97 + last)


_DIFFERENT = "2回の読みで不一致。他方：{other}"
_ONE_ANSWERED = "2回のうち1回は解答なし"
_ONE_LISTED = "2回のうち1回だけが挙げた設問"


def _plain(value) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split()) if isinstance(value, str) else ""


def _mark(answer: str) -> str | None:
    """A short answer in the form two reads are compared in; None for writing, which is not compared."""
    text = re.sub(r"[、,・;]+", "", _plain(answer))
    return text if len(text) <= 24 else None


def _answered(result) -> bool:
    return isinstance(result, SolveResult) and result.extras.get("answer_status") == "ready"


_UNANSWERED = object()


def _slots(replies: list) -> list[list[tuple]]:
    """For each question of one read, the answer slots it fills: each of its printed answer numbers, or, when none
    is printed, its labels as one slot. A repeat (numbers restart in another section) is the next of its kind.

    The reads are compared slot by slot, not question by question: on the phone (2026-11-15, 47 pages) one read gave
    answer numbers 1 to 5 as one question and the other as five."""
    seen: dict = {}
    slots = []
    for item, _ in replies:
        numbers = item.get("answer_no")
        bases = [("number", str(number)) for number in numbers] if isinstance(numbers, list) and numbers else [
            ("labels", _plain(item.get("group")), _plain(item.get("label")))]
        keys = []
        for base in bases:
            seen[base] = seen.get(base, 0) + 1
            keys.append((*base, seen[base]))
        slots.append(keys)
    return slots


def _slot_marks(replies: list, slots: list) -> dict:
    """{slot: what this read says there}: a mark, None for writing (not compared), or ``_UNANSWERED``.

    A question of several answer numbers gives each number its own mark when its answer has as many parts as numbers
    ("④、②、①", "④ ② ①"); otherwise the whole answer stands for each of them."""
    marks: dict = {}
    for (_, result), keys in zip(replies, slots):
        if not _answered(result):
            marks.update(dict.fromkeys(keys, _UNANSWERED))
            continue
        whole = _mark(result.answer)
        # The model separates the marks of one question by spaces as often as by commas ("④ ④ ① ② ②", phone).
        parts = [part for part in re.split(r"[\s、,・;]+", unicodedata.normalize("NFKC", result.answer)) if part]
        apart = whole is not None and len(keys) > 1 and len(parts) == len(keys)
        for index, key in enumerate(keys):
            marks[key] = parts[index] if apart else whole
    return marks


def _compared(first: list, second: list) -> list:
    """The first read's answers, each checked against the second read's; what only the second read has is added.

    A ready answer the reads do not agree on gets ``review_note`` in its extras and stays ready with the first
    read's answer: the server turns the note into an answer to review.
    """
    first_slots, second_slots = _slots(first), _slots(second)
    mine, theirs = _slot_marks(first, first_slots), _slot_marks(second, second_slots)
    same_question = {tuple(keys): pair for keys, pair in zip(second_slots, second)}
    merged = []
    for keys, (item, result) in zip(first_slots, first):
        match = same_question.get(tuple(keys))
        note = ""
        if _answered(result):
            different = [(key, theirs[key]) for key in keys
                         if key in theirs and theirs[key] is not _UNANSWERED and theirs[key] != mine[key]]
            if different and match is not None and _answered(match[1]):
                note = _DIFFERENT.format(other=match[1].answer.strip()[:24])
            elif different:  # the other read grouped these numbers differently: name the numbers it differs on
                note = _DIFFERENT.format(other="、".join(
                    f"{key[1]}は{'記述' if mark is None else mark}" for key, mark in different)[:40])
            elif any(theirs.get(key) is _UNANSWERED for key in keys):
                note = _ONE_ANSWERED
            elif any(key not in theirs for key in keys):
                note = _ONE_LISTED
        elif match is not None and _answered(match[1]):
            (item, result), note = match, _ONE_ANSWERED
        if note:
            result.extras["review_note"] = note
        merged.append((item, result))
    place = {key: index for index, keys in enumerate(first_slots) for key in keys}
    extra, last = [], -1
    for order, (keys, pair) in enumerate(zip(second_slots, second)):
        known = [place[key] for key in keys if key in place]
        if known:
            last = max(known)
            continue
        if _answered(pair[1]):
            pair[1].extras["review_note"] = _ONE_LISTED
        extra.append((last, order, pair))
    for after, _, pair in sorted(extra, key=lambda entry: entry[:2], reverse=True):
        merged.insert(after + 1, pair)  # where the second read had it: after the question before it there
    return merged


def _regions(reply: str, photos: int) -> tuple[dict[int, list[tuple[float, float, float, float, bool | None]]], set[int]]:
    """({photo number: its regions in the order given, each (left, top, right, bottom as fractions, vertical text or
    None when not said)}, {the photos of which something returned was left out}).

    A box that makes no sense, a speck and whatever comes after the eighth region are left out. Their photo is in
    the second value, and goes whole beside its regions: until 2026-11-16 a box left out was only in the small view,
    and a ninth region made the whole photo go out unenlarged.
    """
    try:
        images = extract_json(reply)["images"]
    except (ValueError, KeyError, TypeError):
        return {}, set()
    found: dict[int, list[tuple[float, float, float, float, bool | None]]] = {}
    partial: set[int] = set()
    for image in images if isinstance(images, list) else []:
        try:
            index, regions = image["index"], image["regions"]
            boxes = [(region["left"] / 1000, region["top"] / 1000, region["right"] / 1000, region["bottom"] / 1000,
                      region.get("vertical_text") if isinstance(region.get("vertical_text"), bool) else None)
                     for region in regions]
        except (KeyError, TypeError, AttributeError):
            continue
        if type(index) is not int or not 1 <= index <= photos:
            continue
        kept = [box for box in boxes if all(isinstance(v, float) and 0 <= v <= 1 for v in box[:4])
                and min(box[2] - box[0], box[3] - box[1]) >= _REGION_SHORT - 1e-9
                and max(box[2] - box[0], box[3] - box[1]) >= _REGION_LONG - 1e-9]
        if index in found or len(kept) < len(boxes) or len(kept) > _REGIONS_MOST:
            partial.add(index)
        if kept and index not in found:
            found[index] = kept[:_REGIONS_MOST]
    return found, partial & set(found)
_LIMIT = re.compile(r"usage limit|rate limit|quota", re.IGNORECASE)


def _time_allowed(pages: int) -> tuple[float, float]:
    """(seconds for the answers, seconds for finding the pages) before this route gives the booklet to the next.

    Until 2026-11-16 a run that hung was held 3600 s, longer than a 50-minute test, with Work and Chat waiting.
    The slowest on record: 12.5 s a page for the answers (47 pages, two reads, M-23) and 27.8 s a page through Work
    on hard written mathematics (twenty pages, once); finding the pages took 20 s for 14 and 40 s for 31. Allowed:
    four minutes and half a minute a page, ten minutes at least. ROKID_CODEX_TIMEOUT_S names another limit.
    """
    named = os.environ.get("ROKID_CODEX_TIMEOUT_S")
    answers = float(named) if named else max(600.0, 240.0 + 30.0 * pages)
    return answers, min(answers, max(120.0, 60.0 + 6.0 * pages))


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
                # Both reads are kept since 2026-11-15; before that, the one reply itself.
                stored = json.loads(kept.read_text(encoding="utf-8"))
                reads = stored["reads"] if isinstance(stored, dict) and "reads" in stored else [stored]
                return self._answers(reads, question, extras)
            except (ValueError, TypeError, IndexError):
                pass
        if not self._signed_in():
            raise ChatGptWebAuthenticationRequired("the Codex CLI is missing or not signed in; nothing sent")
        reads, unusable = [], None
        for text in self._run(question, model):
            try:
                data = extract_json(text)
                _booklet_replies(data, subject=question.subject, extras=extras)
            except ValueError as error:
                unusable = error
                continue
            reads.append(data)
        if not reads:
            raise unusable or ValueError("the Codex CLI returned no reply")
        replies = self._answers(reads, question, extras)
        if kept is not None:
            kept.parent.mkdir(parents=True, exist_ok=True)
            temporary = kept.with_suffix(".tmp")
            temporary.write_text(json.dumps({"reads": reads}, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, kept)
        return replies

    @staticmethod
    def _answers(reads: list, question: Question, extras: dict) -> list:
        first = _booklet_replies(reads[0], subject=question.subject, extras=extras)
        if len(reads) < 2:
            return first
        return _compared(first, _booklet_replies(reads[1], subject=question.subject, extras=extras))

    @staticmethod
    def _exec(directory: Path, environment: dict, *, model: str, effort: str, images: list[str], prompt: str,
              timeout: float, schema: dict | None = None, reply_name: str = "reply.json") -> str:
        """Run the CLI once in ``directory`` on the image files named there; its reply text."""
        reply = directory / reply_name
        reply.unlink(missing_ok=True)
        # Fast unless a trial says standard (the operator, 2026-11-16 and 11/10). `priority` is the CLI's Fast tier;
        # `default` asks for standard routing even where a model's own default is Fast.
        tier = "default" if (os.environ.get("ROKID_CODEX_SPEED") or "").strip().lower() == "standard" else "priority"
        command = [*_command(), "exec", "-m", model, "-c", f"model_reasoning_effort={effort}",
                   "-c", f"service_tier={tier}", "-s", "read-only",
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
        """Write each photo's small view and its regions, enlarged and cut, into ``directory``; their names in sending
        order. A photo with no region goes as the Chat route sends it; one of which something returned was left out
        goes whole beside its regions.

        None when nothing could be located at all (the caller sends the photos as before). A usage limit is raised.
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
        found, partial = _regions(reply, len(photos))
        if not found:
            return None
        crops: dict[tuple[int, int], tuple[Image.Image, bool | None, float]] = {}
        for number, (page, photo) in enumerate(zip(ordered, photos), 1):
            for printed, (left, top, right, bottom, vertical) in enumerate(found.get(number, ()), 1):
                pad_x = max((right - left) * _REGION_MARGIN, _REGION_MARGIN_LEAST)
                pad_y = max((bottom - top) * _REGION_MARGIN, _REGION_MARGIN_LEAST)
                box = (max(0, round((left - pad_x) * photo.width)), max(0, round((top - pad_y) * photo.height)),
                       min(photo.width, round((right + pad_x) * photo.width)), min(photo.height, round((bottom + pad_y) * photo.height)))
                crop = photo.crop(box)
                crops[number, printed] = (crop, vertical, _wanted_scale(crop.size, clip=clip_page(page)))
        # A 1024-px view is 768 patches. A photo that goes whole is counted at its own size: until 2026-11-16 it was
        # not counted at all, and forty photos with no page found are more than the model's context.
        whole = [photo for number, photo in enumerate(photos, 1) if number not in found or number in partial]
        limit = _target_long([(crop.size, wanted) for crop, _, wanted in crops.values()], len(found) * 800 + sum(
            math.ceil(photo.width / 32) * math.ceil(photo.height / 32) for photo in whole))
        names = []
        for number, (page, photo) in enumerate(zip(ordered, photos), 1):
            label = f"{page['page_number']:03d}"
            if number not in found:
                # No region here: this photo as the Chat route prepares it (paper crop, fold split), at its own size.
                for payload in source_images([page]):
                    (directory / payload["name"]).write_bytes(payload["buffer"])
                    names.append(payload["name"])
                continue
            overview = f"overview{label}.jpg"
            (directory / f"photo{number:03d}.jpg").replace(directory / overview)
            names.append(overview)
            for printed in range(1, len(found[number]) + 1):
                crop, vertical, wanted = crops[number, printed]
                scale = min(wanted, limit / max(crop.size))
                for tile_number, (tile, _) in enumerate(page_tiles(crop, vertical_text=vertical, min_scale=scale,
                                                                   max_scale=scale)):
                    name = f"page{label}-{printed}{_letters(tile_number)}.jpg"
                    tile.save(directory / name, format="JPEG", quality=92, subsampling=0)
                    names.append(name)
            if number in partial:
                # Something returned for this photo was left out. The whole frame goes too, uncropped (the paper crop
                # could cut off just what was left out), so that what no region shows is more than the small view.
                photo.save(directory / f"page{label}.jpg", format="JPEG", quality=92, subsampling=0)
                names.append(f"page{label}.jpg")
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
    def _run(cls, question: Question, model: str) -> list[str]:
        effort = os.environ.get("ROKID_CODEX_EFFORT") or "xhigh"
        timeout, locating = _time_allowed(len(question.document_pages))
        with cls._workplace() as (directory, environment):
            names = None
            if (os.environ.get("ROKID_CODEX_LOCATE") or "1") != "0":
                names = cls._located(directory, environment, question.document_pages, model=model, timeout=locating)
            note = _TILES_NOTE
            if names is None:
                names, note = [], _IMAGES_NOTE
                for payload in source_images(question.document_pages):
                    (directory / payload["name"]).write_bytes(payload["buffer"])
                    names.append(payload["name"])
            request = {"model": model, "effort": effort, "images": names, "timeout": timeout,
                       "prompt": _ANSWER_ONLY_SYSTEM + "\n\n" + grey_note(question.document_pages) + _ALL_TASK + note}
            if (os.environ.get("ROKID_CODEX_READS") or "2").strip() == "1":
                return [cls._exec(directory, environment, **request)]
            # Two independent reads of the same images at the same time: the second costs no more waiting.
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                pending = [pool.submit(cls._exec, directory, environment, reply_name=f"reply-{number}.json", **request)
                           for number in (1, 2)]
            replies, failures = [], []
            for read in pending:
                try:
                    replies.append(read.result())
                except ChatGptWebError as error:
                    failures.append(error)
            if not replies:
                raise next((error for error in failures if isinstance(error, ChatGptWebRateLimit)), failures[0])
            for error in failures:
                # The other read answers alone; which kind of failure it was is logged, never its text.
                print(json.dumps({"event": "codex_read_failed", "type": type(error).__name__}), flush=True)
            return replies

    def solve(self, *, question: Question, max_answer_len: int = 64) -> SolveResult:
        raise ValueError("codex-cli answers a whole booklet only")
