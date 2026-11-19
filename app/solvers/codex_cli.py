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
An answer or a question only one read gave is shown and noted. When one read fails the other answers alone. When no
read gives a reply an answer list can be made of, or this host cannot carry the run out (an image, the working folder,
memory), the booklet leaves as after a run that did not finish in time: the server gives it to the next route.

From 2026-11-17 (unit tests only; none of it seen with the real CLI): a request for the pages that does not come back
in its time gives the booklet to the next route at once, with no read started behind it. Once one read is back with a
usable reply the other is given that read's time again, two minutes at least, and is then ended; the booklet is then
read once. A usage limit is taken from the CLI's own sentence, or from an error line at the end of what it wrote of
its failure, not from the service's bare words anywhere in its output. Where a paper prints neither answer numbers nor lettered boxes and the two reads name its questions
differently, they are compared in order within the pages they cite (``_compared``).

From 2026-11-18 (unit tests and the stand-in CLI only): the first read that is back with a usable reply is handed to
the caller at once (``Question.on_first_read``), with every answer marked ``read_once``, and the other read goes on
under the limits above. That reply is then the first of the two that are compared and kept, whichever request it came
from, and the compared answers stand on the same item objects: the server saves them over the questions it has shown.
Until then nothing left this module before the slower read ended; on the phone that day one read was back minutes
before the other was cut, and the wearer had given up. Each read that comes back logs its seconds (``codex_read_done``).

A read can be made in parts (``ROKID_CODEX_PARTS``, 1: off). One read of twelve pages with 47 questions took 515 s on
2026-11-18, most of it the model's reasoning and writing. With N over 1 and four pages or more, a small request beside
the one that locates the pages asks on which captures the booklet's major problems begin (``_outline``; from 1024-px
views at low effort it named the same captures twice over for four booklets of that day's use, those the full reads'
question lists begin on). The first read is then one request for each of at most N groups of major problems, at the
same time (``_section_spans``): each carries its own captures at full size, the capture the next group begins on
included, and every other capture as its small overview at most; ``_PART_NOTE`` after the whole request names the
captures whose major problems it answers. The second read is whole, as ever: it is what the first is compared with,
and it answers what a part could not for want of a page. A read's reply is its parts' question lists joined in order
(``_joined``), so everything behind the requests sees a read as before; a part that fails, or whose reply holds no
question list, fails its read. A booklet whose major problems are not told is read whole twice. Each part logs its
seconds (``codex_part_done``), the outline what it gave (``codex_outline``, numbers only); a setting that is no number
is ignored and said (``codex_parts_setting_ignored``). Until the night of 2026-11-18 every part of both reads carried
every image, shared out by page count: six times one whole read's bytes for twelve pages in three parts, tried on
Wi-Fi only, where the venue has the mobile network (M-44 (19)).

A booklet too long for one request at its own size (a common test is some forty pages; one request held nineteen
pages gathered from clips that fill the frame while such a page went out on the grid it is gathered on, and holds
forty-five since 2026-11-19, when a recorded page began to go at 0.63 of that grid, ``_wanted_scale``) was, until
that same night, read with every page reduced until all fitted, both times, and nothing said so. Now the outline is asked for whatever is set (``_might_not_fit``); the
first read is made in as many parts as it takes for each part's pages to go at their own size (``_sized``; four at
most); the whole booklet's request, the second read, is cut a second time at the size that fits and is the read
that has every page in view. What is for the whole exam (a cover with how to answer, a sheet of formulas, an answer
sheet) goes with every part at full size (the outline's ``shared``, four captures at most). Where the major problems
are not told, both reads are whole and reduced, and every answer carries ``pages_reduced`` for the server to say so
(as it does when even the parts had to be reduced). What reducing costs, measured that night (M-44 (20)): a gathered
page with a known text read the same at 0.72, 0.61, 0.45 and 0.35 of its own size as at its own (3.6 to 3.8% of
characters wrong, six reads each; its characters of 25 px down to 9) and worse at 0.25 (5.6%; 6 px). Body print is
therefore inside the margin at the sizes a long booklet is reduced to; what is small on the paper (exponents,
subscripts, ruby) is the reason the first read stays at full size. Photos are cut one at a time (``_cut``): forty
were held in memory twice over, the photo and its regions.

None of this waits for the answers to be asked for. Once the wearer has ended the capture the server names each page
whose image is final (``prepare``): it is located and cut then, beside the gathering of the last clips, and the
outline is asked for when the whole booklet is in hand; answering takes what is there and makes the same requests
for answers as before (``_find``, ``_taken``, ``_outline_ahead``). Until 2026-11-19 all of it began after the last
clip was gathered: 29 to 36 s between "answer this booklet" and the first request for answers on the phone, 9.8 s
with the pages prepared (one booklet of eight; ``codex_prepared`` logs it for every booklet from now on).

The CLI takes images only. A booklet with audio (listening, mixed English) is refused before anything runs, with the
error the server answers by handing the booklet to the next route.

Settings: ``ROKID_CODEX_BIN`` (default: the Termux npm install, else ``codex`` on PATH), ``ROKID_CODEX_MODEL``
(not set: the newest Sol the CLI's own model list offers, ``gpt-6.2-sol`` at least, see ``_model``), ``ROKID_CODEX_EFFORT`` (``high``), ``ROKID_CODEX_TIMEOUT_S`` (by the booklet's size, see ``_time_allowed``), ``ROKID_CODEX_LOCATE`` (``1``;
``0`` sends photos as the Chat route does), ``ROKID_CODEX_PAGE_SCALE`` (2: a region cut from a still photo is sent at
this many times its own pixels at least), ``ROKID_CODEX_PAGE_LONG`` (2540 px: the long side a smaller region of a still is
enlarged up to, at most two and a half times), ``ROKID_CODEX_CLIP_SCALE`` (0.63: the share of the grid it was
gathered on that a recorded page goes at, see ``_wanted_scale``), ``ROKID_CODEX_AHEAD`` (``1``; ``0`` prepares nothing
before the answers are asked for), ``ROKID_CODEX_READS`` (2), ``ROKID_CODEX_PARTS`` (1). Sending is gated by
``ROKID_CHATGPT_SEND_ENABLED`` like every other route that spends the operator's usage.

``check()`` is the proof before use: one request at low effort with a generated picture of three to seven black squares,
which the model counts. Measured on the phone on 2026-11-15 (M-23): 5 s, 14,834 input tokens of which 12,160 were cached.
It shows the CLI is signed in, the network and the image path work and no limit is in force at that moment. The CLI's
event stream (``--json``, 0.169.0) carries token counts only. The session record a request leaves does carry the
service's view of the limits (``rate_limits``: the share of the window used, the window's length, when it starts
anew; phone, 2026-11-16, 3.0% of a week), so the check keeps its record, where a booklet's request leaves none, and
returns those three numbers. Nothing is removed: on a PC the same folder holds the user's own Codex sessions.
"""
from __future__ import annotations

import concurrent.futures
import contextlib
import hashlib
import itertools
import json
import math
import os
import re
import select
import shutil
import socket
import socketserver
import subprocess
import tempfile
import time
import threading
import traceback
import unicodedata
from pathlib import Path

from .. import codex_update, config
from ..llm import extract_json
from PIL import Image

from ..source_bundle import MAX_SCALE, _readable, page_tiles, source_images
from .base import Question, Solver, SolveResult
from .chatgpt_web import (_ALL_TASK, _booklet_chat_key, _booklet_replies, ChatGptWebAuthenticationRequired,
                          ChatGptWebCheckFailed, ChatGptWebError, ChatGptWebModelMismatch, ChatGptWebRateLimit,
                          ChatGptWebReplyIncomplete, ChatGptWebSendNotAuthorized, chatgpt_send_enabled, check_picture,
                          clip_page, grey_note)
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
# Where the major problems begin, for a read in parts. Its own request, so that nothing about finding the pages
# changes: the views are the ones that request gets, under names of their own.
_OUTLINE_PROMPT = (
    "Each attached image is one capture of an exam, taken through smart glasses, in capture order (captureNNN.jpg is "
    "capture page NNN). An exam is made of major problems: its top-level numbered problems, each with its own passage, "
    "data or instructions and its own questions. Return starts: the capture page numbers on which a major problem "
    "begins, in ascending order. The first capture that shows exam matter is a start. A major problem may begin "
    "partway down a capture whose top still belongs to the one before: list that capture. Sub-questions inside a "
    "major problem are not starts. If you cannot tell where major problems begin, return an empty list. Also return "
    "shared: the capture page numbers of captures that show no major problem at all and only material for the whole "
    "exam (a cover with general instructions on how to answer, a sheet of formulas or constants, an answer sheet); an "
    "empty list when there is none. A capture that shows any part of a major problem is never listed, whatever else "
    "it shows. Do not run commands or use tools; look at the images and reply once.")
# More captures named for the whole exam than this are not believed, none of them: asked of thirty-two pages of three
# subjects (2026-11-18), an earlier wording returned eleven, problem pages among them, and every part would have
# carried them all. What a part then lacks, the read of the whole booklet has.
_SHARED_MOST = 4
_OUTLINE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["starts", "shared"],
                   "properties": {"starts": {"type": "array", "items": _INTEGER},
                                  "shared": {"type": "array", "items": _INTEGER}}}
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
# GPT-6.2 Sol since 2026-11-18: released the day before for Codex and Work; the operator's decision, without a
# comparison. The CLI has to be 0.170.0 or newer to know it (0.169.0 lists gpt-6.1-sol as its newest Sol).
MODEL = "gpt-6.2-sol"
_MODEL_WINDOW = 500_000    # the context the CLI's own model list gives gpt-6.2-sol, as it gave gpt-6.1-sol
_CONTEXT_TOKENS = 475_000  # 95% of it
_SOL = re.compile(r"gpt-(\d+(?:\.\d+)*)-sol")
_CLIP_SHARE = 0.63  # of the grid a recorded page is gathered on: the size it is sent at (``_wanted_scale``)


def _model() -> str:
    """The model a booklet is read with: ``ROKID_CODEX_MODEL`` when the operator names one; else the newest Sol the
    CLI's own model list offers, and ``MODEL`` when that list holds nothing newer.

    The operator, 2026-11-18: tools and models are to be kept at the latest. GPT-6.2 Sol had been out a day before
    anyone here looked, and the name was this constant. The CLI keeps the list the service offers its version in
    ``models_cache.json`` (fetched again by a run when it is older than five minutes, and keyed to the client's
    version: an old CLI is not told of a new model; codex-rs models-manager at rust-v0.170.0). Followed: a slug
    ``gpt-<number>-sol`` of a higher number than ``MODEL``'s that is shown (``visibility`` ``list``) and has at least
    the context a booklet is sized for here. Anything else about a newer model (how it reads this system's pages,
    how long it takes) is not known when it is first used; a model the service then refuses is not used
    (``_with_model``).
    """
    named = os.environ.get("ROKID_CODEX_MODEL")
    if named:
        return named

    def number(slug) -> tuple[int, ...] | None:
        sol = _SOL.fullmatch(slug) if isinstance(slug, str) else None
        return tuple(int(part) for part in sol[1].split(".")) if sol else None

    newest, model = number(MODEL), MODEL
    try:
        home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        for entry in json.loads((home / "models_cache.json").read_text(encoding="utf-8"))["models"]:
            found, window = number(entry.get("slug")), entry.get("context_window")
            if (found and found > newest and entry.get("visibility") == "list"
                    and type(window) is int and window >= _MODEL_WINDOW):
                newest, model = found, entry["slug"]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return model


def _with_model(run):
    """``run(model)`` with the model a booklet is read with. A model newer than ``MODEL`` that the service refuses
    gives way to ``MODEL`` once: a model that is not offered would hand the booklet to Work and Chat, neither of
    which answered a booklet inside a test's time on 2026-11-18. A model the operator named is never replaced."""
    model = _model()
    if model != MODEL:
        print(json.dumps({"event": "codex_model", "model": model, "built_on": MODEL}), flush=True)
    try:
        return run(model)
    except ChatGptWebModelMismatch:
        if model == MODEL or os.environ.get("ROKID_CODEX_MODEL"):
            raise
        print(json.dumps({"event": "codex_model_refused", "model": model}), flush=True)
        return run(MODEL)
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

    A page recorded as a clip: every region at one share of the grid it was gathered on, ``ROKID_CODEX_CLIP_SCALE``
    (``_CLIP_SHARE``, 0.63), whatever the region's size. That grid is twice as fine as the camera's pixels a side,
    and until 2026-11-19 a gathered page went out on it (and a small region of one was enlarged towards 2540 px):
    four times the pixels the camera took, with the lens's blur four to eight of them wide. Read against a known
    text, six reads a size, the rule fixed before the reads (M-44 (21), GPT-6.2 Sol at High): two worn pages found
    87.9% and 84.2% of it at their own size, 93.1% and 87.0% at 0.63, 92.0% and 89.2% at 0.5; the desk page read
    the same from its own size down to 0.35 and worse at 0.25. 0.63 and not 0.5, which read as well: what is small
    on the paper (exponents, subscripts, ruby, about 0.6 of body print) keeps eight to ten pixels.
    """
    if clip:
        try:
            share = float(os.environ.get("ROKID_CODEX_CLIP_SCALE") or _CLIP_SHARE)
        except ValueError:
            share = _CLIP_SHARE
        return share if 0.1 <= share <= MAX_SCALE else _CLIP_SHARE
    least = float(os.environ.get("ROKID_CODEX_PAGE_SCALE") or 2)
    return min(MAX_SCALE, max(least, float(os.environ.get("ROKID_CODEX_PAGE_LONG") or 2540) / max(size)))


def _target_long(regions: list[tuple[tuple[int, int], float]], spent: float) -> float:
    """The long side no region may be sent past for the booklet to fit the model's context: infinite when every
    region fits at the scale wanted for it, else the largest common one that fits.

    ``regions`` are (size, wanted scale); ``spent`` is what the other images of the request cost, in patches. The
    regions sent largest give way first, and a region is reduced below its own size only when the booklet does not
    fit otherwise. A page gathered from its clip is 3024x4032 and goes at 0.63 of that, about 7,800 tokens with its
    small view when the paper fills it: forty-five fit and forty-seven do not (on its grid, as until 2026-11-19, it
    was about 18,000 and nineteen fitted). A still's region at twice its size costs four times its own pixels: a sheet that fills a 4032x3024
    photo is about 58,000 tokens, and six such photos fill the context. How a reduced page reads was measured on
    2026-11-18 and 11-19 (``_wanted_scale``; M-44 (20) and (21)).
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


def _might_not_fit(sizes: list[tuple[tuple[int, int], bool]]) -> bool:
    """Whether a booklet of photos of these sizes (each with whether it is a page recorded as a clip) may be more
    than one request holds at the size wanted for it. Every photo is counted whole, which a located page is less
    than: this decides only whether the booklet's major problems are asked for (``_outline``), so that it need not
    be reduced. Nineteen pages gathered from clips fit; six stills at twice their size do not."""
    room = (_CONTEXT_TOKENS - _FIXED_TOKENS) / _TOKENS_PER_PATCH
    return sum(width * height * _wanted_scale((width, height), clip=clip) ** 2 / 1024 * 1.2 + 800
               for (width, height), clip in sizes) > room


def _letters(index: int) -> str:
    """a, b ... z, aa, ab ...: a region sent at twice its size can be more than 26 parts."""
    index, last = divmod(index, 26)
    return (_letters(index - 1) if index else "") + chr(97 + last)


_DIFFERENT = "2回の読みで不一致。他方：{other}"
_ONE_ANSWERED = "2回のうち1回は解答なし"
_ONE_LISTED = "2回のうち1回だけが挙げた設問"


def _plain(value) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split()) if isinstance(value, str) else ""


# Where an answer's working begins: the line the request asks for (llm_adapter._ANSWER_ONLY_SYSTEM).
_WORKING = re.compile(r"^[ \t\u3000]*式[ \t\u3000]*[:：]", re.MULTILINE)


def _result(answer: str) -> str:
    """What an answer gives as its result: what stands before its working, or all of it when it names none."""
    found = _WORKING.search(answer)
    head = answer[:found.start()] if found else answer
    return head if head.strip() else answer


# A choice's label with the words of its option after it, as the request asks for a short option ("⑫（光合成）", or
# "ア（光合成）" where the label stands alone): the label is what is compared. One read adds the words and the other
# does not, or writes them differently; on the phone on 2026-11-18 that marked 18 of 45 items. The label is a circled
# number or letter, or one katakana at the start of a line or after a colon; a value before a bracket ("2(x+1)",
# "f(a)") is no label, and its bracket stays.
_LABEL_WORDS = re.compile(
    r"([①-⑳㉑-㉟㊱-㊿⓪ⓐ-ⓩ]|(?<![^\s:：])[ァ-ヶ])[ \t　]*"
    r"[（(](?:[^（）()\n]|[（(][^（）()\n]*[）)])*[）)][ \t　]*$", re.MULTILINE)
# What differs between two reads in form alone (the operator, 2026-11-19: an answer was marked as differing where
# only a bracket did; of that day's 175 answers 41 carried a note). After NFKC:
# the printed name a box's result is written under, in whatever brackets, as "[name]";
_NAME = re.compile(r"^[\[(〔【]([^\[\]()〔〕【】:]{1,6})[\])〕】](?=:)")
# a separator before such a name is the end of the box before it ("(1):A、(2):B" is two boxes);
_NAMES_APART = re.compile(r"[、,;]\s*(?=[\[(〔【][^\[\]()〔〕【】:]{1,6}[\])〕】]:)")
# a value that stands in round brackets by itself is the value ("（C）", "図1：（C）"). A bracket behind a value
# ("2(x+1)") is part of it, and a square bracket is another thing than a round one (an interval);
_WRAPPED = re.compile(r"(?:(?<=:)|^)\(([^()]{1,12})\)$")
# the double hyphen inside a name in katakana is written or not.
_NAME_HYPHEN = re.compile(r"(?<=[ァ-ヶー])=(?=[ァ-ヶ])")
# The letters mark-sheet boxes are named by, in their order: a run of them at the heads of a question's lines
# ("ア：④ / イ：② / ウ：④") is the boxes' names, where two symbols at the head of two ratios are not.
_BOX_LETTERS = ("アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワ", "abcdefghijklmnopqrstuvwxyz")
_ROMAN = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x")


def _short(text: str) -> str:
    """One line of a result as it is compared: no spaces, no separators, without regard to case, a choice by its
    label alone, and without what is only another way of writing the same thing down (``_NAME`` and what follows)."""
    words = unicodedata.normalize("NFKC", _LABEL_WORDS.sub(r"\1", text))
    parts = [_WRAPPED.sub(r"\1", _NAME.sub(r"[\1]", part)) for part in _NAMES_APART.sub(" ", words).split()]
    joined = _NAME_HYPHEN.sub("", "".join(parts))
    return re.sub(r"[、,・;]+", "", joined).replace("\N{MINUS SIGN}", "-").casefold()


# The longest line that is still one box's result: a label and the words of its option.
_BOX_LINE = 40


def _mark(answer: str) -> str | None:
    """A short answer in the form two reads are compared in; None for writing, which is not compared.

    Of an answer with working only the result is compared, and it may be longer than a mark: several named boxes of
    one question (平均, 分散, 標準偏差) are still results. Until 2026-11-17 anything over 24 characters went
    uncompared, and a written mathematics answer is longer than that as soon as its working stands in it.
    """
    result = _result(answer)
    text = _short(result)
    return text if len(text) <= (24 if result is answer else 80) else None


# What stands around the box letters in a label: "(1) アイ", "(1)(ii) カ", "問2 ウ", "〔2〕 エ〜カ".
_AROUND_BOXES = re.compile(r"[\(\[〔【][0-9A-Za-z]+[\)\]〕】]|\d+|[問第\s・,、〜~\-–:：.．]")


def _boxes(item) -> list[str]:
    """The lettered answer boxes a question names in its label (ア, イ, ウ of a mark sheet whose boxes carry no
    number), one each; none when the label is anything but such letters and what numbers the question.

    Phone, 2026-11-17, forty pages of such a sheet: one read wrote "アイ" and the other "(1) アイ"; compared by the
    whole label not one of 199 items lined up."""
    label = item.get("label")
    rest = _AROUND_BOXES.sub("", unicodedata.normalize("NFKC", label)) if isinstance(label, str) else ""
    return list(rest) if re.fullmatch(r"[ァ-ヶ]+", rest) else []


def _major(item) -> str:
    """The question group a box belongs to, by its number: "第1問" and "第１問 〔2〕" are one."""
    group = _plain(item.get("group"))
    number = re.search(r"\d+", group)
    return number.group(0) if number else group


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
        boxes = [] if isinstance(numbers, list) and numbers else _boxes(item)
        bases = ([("number", str(number)) for number in numbers] if isinstance(numbers, list) and numbers
                 else [("box", _major(item), box) for box in boxes] if boxes
                 else [("labels", _plain(item.get("group")), _plain(item.get("label")))])
        keys = []
        for base in bases:
            seen[base] = seen.get(base, 0) + 1
            keys.append((*base, seen[base]))
        slots.append(keys)
    return slots


def _by_order(replies: list, slots: list) -> None:
    """Give each question that fills a label slot the slot of its place instead: the k-th such question of this read
    that cites the same capture pages."""
    seen: dict = {}
    for (item, _), keys in zip(replies, slots):
        if keys[0][0] == "labels":
            pages = str(item.get("pages"))
            seen[pages] = seen.get(pages, 0) + 1
            keys[:] = [("order", pages, seen[pages])]


def _between(first: list, second: list) -> None:
    """Where the reads' labels mostly line up: a stretch of questions between two that both reads name, named
    differently by each, is paired in order when both reads have as many there and all are of one group. The
    second read's questions take the first's slots.

    Phone, 2026-11-18: one read wrote "(1)（Ⅰ）" and the other "（Ⅰ）" for the parts of a question; each such part
    came out twice, marked as listed by one read only. A stretch the reads split differently (one item against
    three) is left alone: nothing says which belongs to which."""
    ours, theirs = [tuple(keys) for keys in first], [tuple(keys) for keys in second]
    common = set(ours) & set(theirs)

    def label(keys: tuple) -> bool:
        return len(keys) == 1 and keys[0][0] == "labels"

    i = j = 0
    while i < len(ours) or j < len(theirs):
        mine, other = [], []
        while i < len(ours) and ours[i] not in common:
            mine.append(i)
            i += 1
        while j < len(theirs) and theirs[j] not in common:
            other.append(j)
            j += 1
        if mine and len(mine) == len(other) and all(
                label(ours[a]) and label(theirs[b]) and ours[a][0][1] == theirs[b][0][1] for a, b in zip(mine, other)):
            for a, b in zip(mine, other):
                second[b][:] = first[a]
        if i < len(ours) and j < len(theirs) and ours[i] != theirs[j]:
            return  # the questions both name come in another order from here: no stretch can be told
        i, j = i + 1, j + 1


def _slot_marks(replies: list, slots: list) -> dict:
    """{slot: what this read says there}: a mark, None for writing (not compared), or ``_UNANSWERED``.

    A question of several answer numbers gives each number its own mark when its answer has as many lines as numbers
    ("[21]：②" and so on, each under its printed name) or as many parts ("④、②、①", "④ ② ①"); otherwise the whole
    answer stands for each of them. Until 2026-11-18 the lines were compared only while all of them together were no
    longer than one mark: the seven boxes of a word bank went uncompared and looked agreed on."""
    marks: dict = {}
    for (_, result), keys in zip(replies, slots):
        if not _answered(result):
            marks.update(dict.fromkeys(keys, _UNANSWERED))
            continue
        names = [key[2] if key[0] == "box" else key[1] if key[0] == "number" else "" for key in keys]
        whole = _mark(result.answer)
        if whole is not None and len(keys) == 1:
            whole = _unnamed(whole, names[0])  # "[7]：①" for answer number 7 is ①
        text = unicodedata.normalize("NFKC", _result(result.answer))
        # From the answer as written: normalised first, a circled label is digits and is no longer told from a value.
        lines = [_short(line) for line in _result(result.answer).splitlines() if line.strip()]
        if len(keys) > 1 and len(lines) == len(keys) and max(map(len, lines)) <= _BOX_LINE:
            marks.update(zip(keys, _values(lines, names)))
            continue
        # The model separates the marks of one question by spaces as often as by commas ("④ ④ ① ② ②", phone).
        parts = [part for part in re.split(r"[\s、,・;]+", text) if part]
        apart = whole is not None and len(keys) > 1 and len(parts) == len(keys)
        # A lettered box holds one character: "-45" fills three of them.
        each = whole is not None and not apart and len(keys) > 1 and keys[0][0] == "box" and len(whole) == len(keys)
        for index, key in enumerate(keys):
            marks[key] = parts[index] if apart else whole[index] if each else whole
    return marks


def _unnamed(mark: str, name: str) -> str:
    """A box's mark without the printed name it was written under: its own answer number or letter ("[4]:11" and
    "4:11" for box 4 are 11), or whatever the paper prints in brackets beside it ("[a]:11"). A number that is not
    the box's own stays: "1:2" is a ratio."""
    head, colon, value = mark.partition(":")
    if not colon or not value:
        return mark
    return value if (name and head in (name, f"[{name}]")) or re.fullmatch(r"\[[^\[\]]{1,6}\]", head) else mark


def _values(lines: list[str], names: list[str]) -> list[str]:
    """The marks of a question's boxes, a line each, without the names they were written under (``_unnamed``).
    Lines headed by a run of box letters (ア, イ, ウ; a, b, c; i, ii, iii) are boxes named by their letters, where
    the other read may go by their answer numbers."""
    heads = [line.partition(":")[0] if ":" in line else None for line in lines]
    run = len(lines) > 1 and all(heads) and (
        any("".join(heads) in letters for letters in _BOX_LETTERS if all(len(head) == 1 for head in heads))
        or any(tuple(heads) == _ROMAN[at:at + len(heads)] for at in range(len(_ROMAN))))
    return [line.partition(":")[2] if run and line.partition(":")[2] else _unnamed(line, name)
            for line, name in zip(lines, names)]


def _compared(first: list, second: list) -> list:
    """The first read's answers, each checked against the second read's; what only the second read has is added.

    A ready answer the reads do not agree on gets ``review_note`` in its extras and stays ready with the first
    read's answer: the server turns the note into an answer to review.
    """
    first_slots, second_slots = _slots(first), _slots(second)
    # Where neither answer numbers nor lettered boxes are printed a slot is the group and label as the read wrote
    # them, and one read writes 第1問 / (1) where the other writes nothing / 1 (1): nothing lined up, both lists were
    # shown whole and every item marked as listed by one read only (found 2026-11-17). When fewer than half of the
    # shorter read's label slots have a partner, the reads are taken in order within each set of cited pages; what
    # one read has more of there is what is left over. A question one read split shifts the pairs after it on
    # that page: they are then marked as differing, not lost.
    named = [{key for keys in slots for key in keys if key[0] == "labels"} for slots in (first_slots, second_slots)]
    if 2 * len(named[0] & named[1]) < min(map(len, named)):
        _by_order(first, first_slots)
        _by_order(second, second_slots)
    else:
        _between(first_slots, second_slots)
    mine, theirs = _slot_marks(first, first_slots), _slot_marks(second, second_slots)
    same_question = {tuple(keys): pair for keys, pair in zip(second_slots, second)}
    merged = []
    for keys, (item, result) in zip(first_slots, first):
        match = same_question.get(tuple(keys))
        note = ""
        if _answered(result):
            different = [(key, theirs[key]) for key in keys
                         if key in theirs and theirs[key] is not _UNANSWERED and theirs[key] != mine[key]]
            if different and len(keys) == 1 and match is not None and _answered(match[1]):
                other = " ".join(_result(match[1].answer).split())
                note = _DIFFERENT.format(other=other[:24])
            elif different:
                # Several numbers, or the other read grouped them differently: name the ones it differs on. Until
                # 2026-11-18 a question of several boxes showed the other read's whole answer cut at 24 characters,
                # its first boxes and not the one that differs.
                other = "、".join(
                    f"{name}は{'記述' if mark is None else _unnamed(mark, name)}"
                    for name, mark in ((key[2] if key[0] == "box" else key[1], mark) for key, mark in different))
                note = _DIFFERENT.format(other=other[:40])
            if different:
                # By itself too, for the glasses to show beside this answer without a sentence around it.
                result.extras["other_answer"] = other[:120]
            elif any(theirs.get(key) is _UNANSWERED for key in keys):
                note = _ONE_ANSWERED
            elif any(key not in theirs for key in keys):
                note = _ONE_LISTED
        elif match is not None and _answered(match[1]):
            # Under the first read's item: its answers may be out already, shown under the questions as it named
            # them (``answer_all``). Until 2026-11-18 the second read's item came along with its answer.
            result, note = match[1], _ONE_ANSWERED
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


# A run that ended at a usage limit, in one line of what the CLI says of its own failure. Its own sentence ("You’ve
# hit your usage limit. Visit ... to purchase more credits or try again at 10:16 AM.", phone, 2026-11-16, M-34; in the
# binary of codex 0.167.0 with a typographic apostrophe and, after the first sentence, an upgrade, a visit or another
# model to switch to), or the service's words on a line that begins as an error.
_LIMIT = re.compile(r"(?:hit|reached) your usage limit"
                    r"|^\W*(?:\w+ )?error\b.*?(?:usage limit|quota|out of credits|hit your spend cap)",
                    re.IGNORECASE | re.DOTALL)  # an event's message may be more than one line
# A request refused for its rate, which is not the allowance (codex-rs at rust-v0.170.0, read 2026-11-18): an HTTP
# 429 of another kind ("exceeded retry limit, last status: 429 Too Many Requests", which the CLI sends again only when
# the service names a wait), a rate limit inside the stream ("rate limit exceeded: ...", sent again five times in
# about six seconds) and "Selected model is at capacity." Until 2026-11-18 the words "rate limit" were a usage limit:
# the booklet left the CLI and Work for Chat, which that evening did not answer a booklet in an hour.
_RATE = re.compile(r"^\W*(?:\w+ )?error\b.*?(?:last status: 429|rate limit|too many requests|at capacity)",
                   re.IGNORECASE | re.DOTALL)
# How long after such a refusal the same request goes again, each time. What the service does with several requests
# of one account at once is not documented and was not met in four runs of six: these are a guess to be corrected
# from the log (``codex_rate_refused``). After the last, the request fails as a send that did not happen.
_RATE_WAITS = (5.0, 20.0)
# The CLI's own sentence alone. No page says it, so it is taken anywhere on stderr: how many lines the CLI writes
# after it at a real limit is not on record, and a limit not recognised sends the booklet to Work, which draws on the
# same allowance, before Chat.
_OWN_LIMIT = re.compile(r"(?:hit|reached) your usage limit", re.IGNORECASE)
# Of stderr, from its end: the error and, after it, what the CLI says of the reply it could not write ("Warning: no
# last agent message; wrote empty content to ...", its binary's words) and of the tokens used. Not measured at a limit.
_LIMIT_LINES = 8


def _said(stdout: str, stderr: str) -> list[str]:
    """What the CLI says of its own failure: the last lines of stderr and, when its events are on stdout as lines
    of JSON (``--json``, which the requests here do not ask for), the message of an ``error`` or ``turn.failed``
    event as an error line."""
    said = [re.sub(r"\x1b\[[0-9;]*m", "", line).strip() for line in stderr.splitlines() if line.strip()][-_LIMIT_LINES:]
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
            kind = event["type"]
        except (ValueError, KeyError, TypeError):
            continue
        if kind in ("error", "turn.failed"):
            detail = event.get("error") if kind == "turn.failed" else event
            said.append(f"error: {detail.get('message') if isinstance(detail, dict) else detail}")
    return said


def _rate_reported(stdout: str, stderr: str) -> bool:
    """Whether a run that failed says the service refused it for the rate of requests (``_RATE``). Asked only of a
    run that did not report a usage limit."""
    return any(_RATE.search(line) for line in _said(stdout, stderr))


def _limit_reported(stdout: str, stderr: str) -> bool:
    """Whether a run that failed says of itself that a usage limit ended it.

    Until 2026-11-17 the words were looked for anywhere in what the run had written, and a limit closes the CLI and
    Work for the booklet: a run that failed for another cause with "quota" in a passage it had read out went
    straight to Chat. What is read now: the CLI's own sentence wherever it stands on stderr; the service's words only
    on an error line among the last lines of stderr, where the CLI ends with its error; and, when its
    events are on stdout as lines of JSON (``--json``, which the requests here do not ask for), the message of an
    ``error`` or ``turn.failed`` event. How the limit reads on stderr without ``--json`` is not on record.
    """
    return bool(_OWN_LIMIT.search(stderr)) or any(_LIMIT.search(line) for line in _said(stdout, stderr))


# A run that ended because the service no longer offers the model. The CLI warns "Model metadata for `<model>` not
# found. Defaulting to fallback metadata; ..." (its own words, read from the binary of codex 0.153.2 on 2026-11-16)
# and the service's error code is model_not_found; the service's sentence is not ours to fix, so its likely forms
# are taken too, on a line that says "error" first: a run that failed for another cause may have written an exam's
# own words about a model. Looked for only in a run that failed: a CLI older than a model that still answers warns
# and works.
_NO_MODEL = re.compile(
    r"model metadata for .{0,200}?not found|model[_ ]not[_ ]found"
    r"|error\b.{0,300}?(?:unknown model|invalid model|not an? (?:valid|supported|available) model"
    r"|model\b.{0,200}?(?:is not supported|does not exist|is not available|no longer (?:available|supported)))",
    re.IGNORECASE)


def _time_allowed(pages: int) -> tuple[float, float]:
    """(seconds for the answers, seconds for finding the pages) before this route gives the booklet to the next.

    Until 2026-11-16 a run that hung was held 3600 s, longer than a 50-minute test, with Work and Chat waiting.
    The slowest on record: 12.5 s a page for the answers (47 pages, two reads, M-23) and 27.8 s a page through Work
    on hard written mathematics (twenty pages, once); finding the pages took 20 s for 14 and 40 s for 31. Allowed
    until 2026-11-18: four minutes and half a minute a page, ten minutes at least. That day twelve gathered pages of
    vertical Japanese took a read more than fifty seconds a page: one booklet was given up at 600 s with both reads
    running, and the routes behind it failed. Allowed now: five minutes and fifty seconds a page, fifteen minutes
    at least. ROKID_CODEX_TIMEOUT_S names another limit.
    """
    named = os.environ.get("ROKID_CODEX_TIMEOUT_S")
    # A backstop from 0.88.0 (the same day): no run on record ever hung. The two that were ended as hung (fourteen
    # dark pages on 2026-11-16, twelve of vertical Japanese on 2026-11-18) were slow, their work was thrown away, and
    # nothing behind this route answers such a booklet sooner (Chat thought for over half an hour on the same twelve
    # pages). 45 minutes, or the old measure where that is longer. What ends a run that really stalls is not built:
    # it needs the CLI's events (--json) and how often they come during a long read, which is not on record.
    answers = float(named) if named else max(2700.0, 300.0 + 50.0 * pages)
    return answers, min(answers, max(120.0, 60.0 + 6.0 * pages))


# Once one read is back with a usable reply the other is given that read's time again: this long at least and that
# long at most. Two runs of one booklet of 47 pages ended at 366 s and 586 s (phone, 2026-11-15), so two healthy reads
# lie that far apart; how far apart the two reads of one run end has not been measured. A read cut here might have
# answered, and its booklet is then read once, with nothing compared. The ceiling is for a first read that was slow
# itself (nine minutes for twelve dense pages, 2026-11-18): as long again is most of what a 50-minute test has left.
_SECOND_READ_LEAST_S = 120.0
# 240 s until the first read's answers went out at once (0.88.0): from then on the wait costs the wearer nothing,
# and a read cut is a booklet nothing was compared for.
_SECOND_READ_MOST_S = 900.0

# What one part of the first read is told after the whole request (ROKID_CODEX_PARTS). The request above it still
# says to answer every question, so this says first that it narrows that. A part owns the major problems that begin
# on its captures: the capture the next part begins on is sent to both, and each lists only what is its own.
_PART_NOTE = (
    "\n\nThis request is one of {parts} sent at the same time, each for some of the booklet's major problems (its "
    "top-level numbered problems); here the instruction to answer every question holds for the major problems that "
    "begin on capture pages {first} to {own_last} only. A major problem that more than one capture shows begins on "
    "the lowest-numbered capture page that shows its beginning. Their captures are attached at full size: capture "
    "pages {first} to {last}. Every other capture page is attached as its small overview at most, and another "
    "request answers what begins there: list nothing of a major problem that begins before capture page {first} or "
    "after capture page {own_last}, even where a full-size image shows part of it. If a question of yours cannot be "
    "answered without reading a capture page that is not attached at full size here, give it the status needs_input "
    "and name those capture pages in missing_material; never read text from an overview. Report what the captures "
    "leave out only for capture pages {first} to {own_last}; a gap in the printed page numbers is reported with the "
    "capture page before the gap, or with the one after it when none is before. If no major problem begins on "
    "capture pages {first} to {own_last} and nothing is to be reported for them, reply "
    '{{"questions":[]}}.')
# Captures that hold what is for the whole exam and lie outside a part's own (``_outline``'s ``shared``): how to answer
# stands on the first pages of a common test and tables at its end, and a part that had them as overviews only would
# answer in the wrong form.
_SHARED_NOTE = (" Capture page {pages} holds what is for the whole exam (how to answer, tables, an answer sheet) and is "
                "attached at full size as well: use it, and list nothing from it that is not a question of yours.",
                " Capture pages {pages} hold what is for the whole exam (how to answer, tables, an answer sheet) and are "
                "attached at full size as well: use them, and list nothing from them that is not a question of yours.")
_PARTS_MOST = 4  # of one read, whatever is set: every way of grouping the major problems is tried
# The photos of a booklet kept in memory between finding their pages and cutting them, in bytes of pixels: past it a
# photo is opened again when it is cut. A page gathered from a clip is 36.6 MB; forty were held twice over (the photo
# and its cut-out regions), about 2.9 GB on a phone with 4.5 GB free, and no booklet of that size had been through.
_PHOTOS_KEPT = 600_000_000
_PAGE_FILE = re.compile(r"page(\d{3})")

# What was prepared of a booklet before its answers were asked for (``CodexCliSolver.prepare``). By a page's file
# (``_page_key``): a Future of what was made of that page, {"folder", "size", "regions", "partial", "boxes", "names"}
# or None when nothing could be, and the time it was asked. By all of a booklet's files in order: a Future of what
# ``_outline`` returns. In memory only: after a restart nothing is prepared and a booklet is answered as it was until
# 2026-11-19, with every request made when the answers are asked for.
_AHEAD_KEPT_S = 6 * 3600.0         # after which the files are removed and the entry forgotten
_AHEAD_PHOTOS_KEPT = 150_000_000   # as ``_PHOTOS_KEPT``, for pages prepared while clips are still being gathered
_ahead_lock = threading.Lock()
_ahead: dict[tuple, tuple[concurrent.futures.Future, float]] = {}
_ahead_outlines: dict[tuple, tuple[concurrent.futures.Future, float]] = {}
_ahead_turn = threading.BoundedSemaphore(2)  # requests that locate pages ahead, at once


def _parts_set() -> int | None:
    """``ROKID_CODEX_PARTS``: the requests the first read is made in (1 when not set); None when it is no number."""
    try:
        return int(os.environ.get("ROKID_CODEX_PARTS") or 1)
    except ValueError:
        return None


def _page_key(page: dict) -> tuple:
    """What a prepared page is known by: its file and the hash the server gives with it; without a hash, the file's
    size and time. A clip gathered later puts another file in the page's place, and what was prepared of the frame
    the page arrived as is then not used."""
    path = str(page["image_path"])
    if page.get("image_sha256"):
        return path, page["image_sha256"]
    stat = os.stat(path)
    return path, stat.st_size, stat.st_mtime_ns


def _ahead_sweep() -> None:
    """Forget what was prepared more than ``_AHEAD_KEPT_S`` ago and remove its files, and those a server that has
    since been restarted left behind."""
    now = time.time()
    with _ahead_lock:
        for store in (_ahead, _ahead_outlines):
            for key, (future, asked) in list(store.items()):
                if future.done() and now - asked >= _AHEAD_KEPT_S:
                    del store[key]
    root = Path(config.DATA_DIR) / "codex-ahead"
    try:
        folders = list(root.iterdir())
    except OSError:
        return
    for folder in folders:
        try:
            if now - folder.stat().st_mtime >= _AHEAD_KEPT_S:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            continue


def _taken(ordered: list[dict], wait: float) -> dict[int, dict]:
    """What was prepared ahead of these pages, by each page's place among them. A page being prepared is waited for,
    ``wait`` seconds for all of them; one whose turn has not come is taken back, and whoever asks does it."""
    held = {}
    with _ahead_lock:
        for number, page in enumerate(ordered, 1):
            try:
                kept = _ahead.get(_page_key(page))
            except (OSError, KeyError, TypeError):
                continue
            if kept is not None:
                held[number] = kept[0]
    taken, until = {}, time.monotonic() + wait
    for number, future in held.items():
        if future.cancel():
            continue
        try:
            made = future.result(timeout=max(0.0, until - time.monotonic()))
        except Exception:  # noqa: BLE001 - whatever became of it, the page is located with the booklet
            continue
        if made is not None and made["folder"].is_dir():
            taken[number] = made
    return taken


def _ahead_view(page: dict) -> Path | None:
    """The small view of this page that was made when it was prepared, when that is done; never waited for."""
    try:
        with _ahead_lock:
            kept = _ahead.get(_page_key(page))
        made = kept[0].result(timeout=0) if kept is not None and kept[0].done() and not kept[0].cancelled() else None
        view = made["folder"] / made["names"][0] if made else None
        return view if view is not None and view.is_file() else None
    except Exception:  # noqa: BLE001 - the view is then made again
        return None


def _outline_ahead(pages: list[dict]) -> concurrent.futures.Future | None:
    """The request for this booklet's major problems that was made ahead: still running, or back with something
    told. None when there is none, when its turn had not come (it is taken back), or when it told nothing: the
    booklet's own request then asks, as before."""
    try:
        key = tuple(_page_key(page) for page in sorted(pages, key=lambda page: page["page_number"]))
    except (OSError, KeyError, TypeError):
        return None
    with _ahead_lock:
        kept = _ahead_outlines.get(key)
    if kept is None or kept[0].cancel():
        return None
    if kept[0].done():
        try:
            if not kept[0].result(timeout=0)[0]:
                return None
        except Exception:  # noqa: BLE001
            return None
    return kept[0]


def _section_spans(numbers: list[int], starts, parts: int) -> list[tuple[int, int, int]]:
    """The parts of a read by the booklet's major problems, each (first capture page, last capture page whose major
    problems it answers, last capture page it is sent at full size); empty when there are not to be parts.

    ``numbers`` are the booklet's capture page numbers in order, ``starts`` what the model returned as the captures
    on which major problems begin; the first capture is one whatever it said. A major problem runs from its start
    to the next start, on which it may end partway down: that capture is sent with both. More major problems than
    ``parts``: neighbours share a part, so that the most captures any part answers for are as few as can be, then
    the next most; of equal ways, the one that cuts earliest. Fewer than two starts, or one part asked for: no
    parts. Captures shared out by their count alone would part a passage from its questions.
    """
    if not numbers or not isinstance(starts, list):
        return []
    begins = sorted({numbers[0], *(start for start in starts if type(start) is int and start in numbers)})
    count = min(parts, len(begins), _PARTS_MOST)
    if count < 2:
        return []
    at = [*(numbers.index(start) for start in begins), len(numbers)]

    def groups(cuts: tuple[int, ...]):
        return zip((0, *cuts), (*cuts, len(begins)))

    # ponytail: every way of cutting is tried (forty captures in four parts are 9,139 ways); a search when
    # _PARTS_MOST has to grow.
    cuts = min(itertools.combinations(range(1, len(begins)), count - 1),
               key=lambda cuts: (sorted((at[end] - at[start] for start, end in groups(cuts)), reverse=True), cuts))
    return [(begins[start], numbers[at[end] - 1], numbers[min(at[end], len(numbers) - 1)]) for start, end in groups(cuts)]


def _attached(name: str, first: int, last: int, shared=()) -> bool:
    """Whether a part that is sent capture pages ``first`` to ``last`` at full size is sent this image: every
    overview, the files of its own captures (pageNNN..., whatever follows the number) and those of the captures
    that hold what is for the whole exam."""
    numbered = _PAGE_FILE.match(name)
    return numbered is None or first <= int(numbered[1]) <= last or int(numbered[1]) in shared


def _listed(pages: list[int]) -> str:
    """1 / 1 and 6 / 1, 2 and 6."""
    return str(pages[0]) if len(pages) == 1 else ", ".join(map(str, pages[:-1])) + f" and {pages[-1]}"


def _layout_cost(layout: dict, inside: set[int] | None) -> tuple[list[tuple[tuple[int, int], float]], int]:
    """What a request costs that carries the regions of these photos (``inside``: their places in the booklet; None
    is all) at full size and every located photo's overview: (regions as (size, wanted scale), patches spent on
    what is not reduced). For ``_target_long``."""
    regions = [((box[2] - box[0], box[3] - box[1]), wanted) for (number, _), (box, _, wanted) in layout["boxes"].items()
               if inside is None or number in inside]
    # A 1024-px view is 768 patches. A photo that goes whole is counted at its own size: until 2026-11-16 it was
    # not counted at all, and forty photos with no page found are more than the model's context.
    whole = [size for number, size in enumerate(layout["sizes"], 1)
             if (number not in layout["found"] or number in layout["partial"]) and (inside is None or number in inside)]
    return regions, len(layout["found"]) * 800 + sum(math.ceil(width / 32) * math.ceil(height / 32) for width, height in whole)


def _decisive(failures: list) -> BaseException:
    """Of the failures of requests that ran side by side, the one that leaves. A usage limit first: it closes Work as
    well. Then a run that did not finish in time, which the server answers with the next route at once; a bare
    failure costs one more whole attempt before."""
    return next((error for kind in (ChatGptWebRateLimit, ChatGptWebReplyIncomplete)
                 for error in failures if isinstance(error, kind)), failures[0])


def _named(item: dict) -> tuple | None:
    """What two parts of a read may know one question by: its group and label as they are compared and its printed
    answer numbers. None when it prints no answer number, or neither group nor label: such an item is never taken
    for another part's (a "(1)" stands under every 大問, and what the captures leave out names nothing)."""
    numbers, names = item.get("answer_no"), (_plain(item.get("group")), _plain(item.get("label")))
    return (*names, *map(str, numbers)) if isinstance(numbers, list) and numbers and any(names) else None


def _cited(item: dict) -> list[int]:
    pages = item.get("pages")
    return [page for page in pages if type(page) is int] if isinstance(pages, list) else []


def _joined(number: int, spans: list[tuple[int, int]], texts: list[str]) -> str:
    """One reply for read ``number`` out of its parts' replies: their question lists one after the other, in the
    order of their capture pages. A ValueError when a part's reply holds no question list (the read fails); an empty
    list is a part on whose pages no question begins.

    A question at a boundary may be listed by both its parts. The same question: the same name (``_named``) and a
    capture page cited by both. It stays once, from the part whose pages hold the first page it cites, else from
    the earlier part; how many were dropped is logged (``codex_parts_duplicate``), never what. The cited page in
    common is asked for because "printed answer numbers may restart in another section or question, even under the
    same labels" (the request's own words): a question dropped for its name alone is lost with nothing said, and one
    listed twice is seen. So a question two parts cite no common page for stays twice, and so does every question
    without a printed answer number.
    """
    reply: dict = {}
    questions: list = []
    earlier: dict = {}  # name -> [(place in ``questions``, whether its own part's pages hold its first page)]
    dropped = 0
    for (first, last), text in zip(spans, texts):
        data = extract_json(text)
        listed = data.get("questions") if isinstance(data, dict) else None
        if not isinstance(listed, list) or any(not isinstance(item, dict) for item in listed):
            raise ValueError("a part's reply holds no question list")
        reply.update(data)  # anything else a part said stays, for the check of a whole reply to refuse as ever
        here = []
        for item in listed:
            name, cited = _named(item), _cited(item)
            home = bool(cited) and first <= cited[0] <= last
            known = earlier.get(name, [])
            twin = next((entry for entry in known if set(cited) & set(_cited(questions[entry[0]]))), None)
            if twin is not None:
                dropped += 1
                if twin[1] or not home:
                    continue
                questions[twin[0]] = None  # the earlier part listed a question of these pages: this one stays
                known.remove(twin)
            if name:
                here.append((name, len(questions), home))
            questions.append(item)
        for name, place, home in here:  # only now: within one part a name twice is two questions, as in a whole read
            earlier.setdefault(name, []).append((place, home))
    if dropped:
        print(json.dumps({"event": "codex_parts_duplicate", "read": number, "count": dropped}), flush=True)
    reply["questions"] = [item for item in questions if item is not None]
    return json.dumps(reply, ensure_ascii=False)


def _command() -> list[str]:
    """The CLI's own binary. The npm launcher needs /usr/bin/env, which Termux does not have."""
    named = os.environ.get("ROKID_CODEX_BIN", "")
    if named:
        return [named] if Path(named).is_file() else []
    updated = codex_update.chosen()  # a newer release that was installed beside and answered (app/codex_update.py)
    if updated:
        return [updated]
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
        sent, busy, last = 0, 0.0, None
        try:
            with upstream:
                client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                client.settimeout(None)
                sockets = [client, upstream]
                while True:
                    readable, _, _ = select.select(sockets, [], [], self.server.idle_s)
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
                        if source is client:
                            # The time between pieces that follow one another at once is the time the network took
                            # to carry them (a full send waits); a longer silence is the request being thought about.
                            now = time.monotonic()
                            busy += now - last if last is not None and now - last < 1.0 else 0.0
                            sent, last = sent + len(data), now
        finally:
            if sent >= 1_000_000:
                # What a request uploaded and how fast, so that the venue's network is on record: bytes, never content.
                print(json.dumps({"event": "codex_upload", "mb": round(sent / 1e6, 1), "seconds": round(busy, 1),
                                  "mbit_s": round(sent * 8 / 1e6 / busy, 1) if busy > 0 else None}), flush=True)


class _Proxy(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True
    idle_s = 600.0  # a tunnel through which nothing passes for this long is closed


@contextlib.contextmanager
def name_resolving_proxy(idle_s: float = 600.0):
    """A loopback CONNECT proxy for the life of one run; yields its port.

    ``idle_s`` is how long the run may take: a silent tunnel is kept that long, and 600 s at least. Until 2026-11-17
    it was 600 s whatever the run was allowed, and the answers of more than twelve pages may take longer; a stream
    cut while the model works ends the run as a bare failure."""
    server = _Proxy(("127.0.0.1", 0), _Tunnel)
    server.idle_s = max(600.0, idle_s)
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


def _log_cause(event: str, error: BaseException) -> None:
    """Which kind of failure and where it was raised. Never its message: that can carry reply or page text."""
    raised = traceback.extract_tb(error.__traceback__)[-1] if error.__traceback__ else None
    print(json.dumps({"event": event, "type": type(error).__name__,
                      "at": f"{Path(raised.filename).name}:{raised.lineno}:{raised.name}" if raised else None}), flush=True)


class CodexCliSolver(Solver):
    name = "codex-cli"
    provider_version = "codex-exec-v1"
    offline = False
    placeholder = False
    accepts_images = True

    @staticmethod
    def _signed_in(command: list[str] | None = None) -> bool:
        command = command or _command()
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
        extras = {"source": self.name, "provider": "codex", "model": _model()}
        kept = self._kept(question)
        if kept is not None and kept.is_file():
            try:
                # Already answered and paid for: a repeated finalize or a restart reads it, as the Chat route reads its chat.
                # Both reads are kept since 2026-11-15; before that, the one reply itself.
                stored = json.loads(kept.read_text(encoding="utf-8"))
                reads = stored["reads"] if isinstance(stored, dict) and "reads" in stored else [stored]
                if isinstance(stored, dict) and stored.get("pages_reduced") is True:
                    extras["pages_reduced"] = True
                return self._answers(reads, question, extras)
            except (ValueError, TypeError, IndexError):
                pass
        if not self._signed_in():
            raise ChatGptWebAuthenticationRequired("the Codex CLI is missing or not signed in; nothing sent")
        # A reply no answer list can be made of, or a run this host could not carry out (an image, the working folder,
        # memory), leaves as what a run that did not finish in time leaves as: the server gives the booklet to the
        # next route. As a ValueError or OSError it was recorded as solver_failed and the booklet ended there, with
        # Work and Chat never asked (found 2026-11-17). A usage limit and the CLI's own failures pass as they are.
        handed: list = []  # the reply whose answers went out while the other read was still running

        def hand_over(text: str) -> None:
            data = extract_json(text)
            question.on_first_read(self._answers([data], question, extras))
            handed.append(data)

        def run(model: str) -> list[str]:
            extras["model"] = model  # the one that answers, whichever was tried first
            return self._run(question, model, hand_over if question.on_first_read else None, said=extras)

        try:
            texts = _with_model(run)
        except (OSError, MemoryError, ValueError) as error:
            _log_cause("codex_run_failed", error)
            raise ChatGptWebReplyIncomplete("the Codex CLI's run could not be carried out on this host") from error
        # The reply handed over comes first (``_run``) and is taken as it was parsed then: the compared answers
        # stand on the same item objects, which is how the caller finds the questions it has already shown.
        reads, unusable = handed[:], None
        for text in texts[len(handed):]:
            try:
                data = extract_json(text)
                _booklet_replies(data, subject=question.subject, extras=extras)
            except ValueError as error:
                unusable = error
                _log_cause("codex_reply_unusable", error)
                continue
            reads.append(data)
        if not reads:
            raise ChatGptWebReplyIncomplete("no read by the Codex CLI gave a usable reply") from unusable
        replies = self._answers(reads, question, extras)
        if kept is not None:
            kept.parent.mkdir(parents=True, exist_ok=True)
            temporary = kept.with_suffix(".tmp")
            temporary.write_text(json.dumps({"reads": reads, **({"pages_reduced": True} if extras.get("pages_reduced") else {})},
                                            ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, kept)
        return replies

    @staticmethod
    def _answers(reads: list, question: Question, extras: dict) -> list:
        first = _booklet_replies(reads[0], subject=question.subject, extras=extras)
        if len(reads) < 2:
            if (os.environ.get("ROKID_CODEX_READS") or "2").strip() != "1":
                # Asked for twice and answered once (the other read failed, gave nothing usable or was ended):
                # nothing was compared, and an unmarked answer otherwise means that two reads agree. The server says
                # so once behind the answers.
                for _, result in first:
                    result.extras["read_once"] = True
            replies = first
        else:
            replies = _compared(first, _booklet_replies(reads[1], subject=question.subject, extras=extras))
        # Until 2026-11-19 an answer that named a choice by a circled number of two digits always asked to be checked
        # on the paper, both reads agreeing or not (a word bank's soft labels were once read wrongly by both alike,
        # M-44 (17)). The option's words stand beside the label for that check, and the operator asked for answers
        # without explanations.
        return replies

    @staticmethod
    def _exec(directory: Path, environment: dict, *, model: str, effort: str, images: list[str], prompt: str,
              timeout: float, schema: dict | None = None, reply_name: str = "reply.json",
              ephemeral: bool = True, running: list | None = None, cli: list[str] | None = None) -> str:
        """Run the CLI (``cli``: another binary than the one in use, to try it) once in ``directory`` on the image
        files named there; its reply text.

        The process is added to ``running`` for the caller to end from another thread; a run ended that way fails
        here as any run that ends without a reply."""
        reply = directory / reply_name
        reply.unlink(missing_ok=True)
        # Fast unless a trial says standard (the operator, 2026-11-16 and 11/10). `priority` is the CLI's Fast tier;
        # `default` asks for standard routing even where a model's own default is Fast.
        tier = "default" if (os.environ.get("ROKID_CODEX_SPEED") or "").strip().lower() == "standard" else "priority"
        command = [*(cli or _command()), "exec", "-m", model, "-c", f"model_reasoning_effort={effort}",
                   "-c", f"service_tier={tier}", "-s", "read-only",
                   "--skip-git-repo-check", *(["--ephemeral"] if ephemeral else []),
                   *(part for name in images for part in ("-i", name))]
        if schema is not None:
            (directory / "schema.json").write_text(json.dumps(schema), encoding="utf-8")
            command += ["--output-schema", "schema.json"]
        command += ["-o", str(reply), prompt]
        for again_in in (*_RATE_WAITS, None):
            try:
                process = subprocess.Popen(command, cwd=directory, env=environment, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                           stdin=subprocess.DEVNULL)
            except OSError as error:
                raise ChatGptWebError(f"the Codex CLI could not start: {type(error).__name__}") from error
            if running is not None:
                running.append(process)
            with process:  # as subprocess.run does it, which gives no hold on the process
                try:
                    stdout, stderr = process.communicate(timeout=timeout)
                except subprocess.TimeoutExpired as error:
                    process.kill()
                    if os.name == "nt":
                        process.communicate()  # Windows reads the pipes on threads of its own: let them end
                    raise ChatGptWebReplyIncomplete("the Codex CLI did not finish in time") from error
                except BaseException:
                    process.kill()  # nothing is left running behind another error either
                    raise
            if process.returncode == 0 and reply.is_file():
                # The CLI's own last word on a run ("tokens used" and a number): what this request cost, on record.
                used = re.findall(r"tokens used\s*:?\s*([\d,]+)", stdout + "\n" + stderr)
                if used:
                    print(json.dumps({"event": "codex_tokens", "tokens": int(used[-1].replace(",", "")),
                                      "images": len(images)}), flush=True)
                return reply.read_text(encoding="utf-8")
            if _limit_reported(stdout, stderr):
                raise ChatGptWebRateLimit("the Codex CLI reported a usage limit")
            if _NO_MODEL.search(stdout + "\n" + stderr):
                # Named, so the check before use says why and the booklet goes to the next route. No other model
                # is tried: which one answers a booklet is the operator's choice (ROKID_CODEX_MODEL).
                raise ChatGptWebModelMismatch("the Codex CLI's model is not offered; nothing answered")
            if again_in is None or not _rate_reported(stdout, stderr):
                break
            # Refused for the rate of requests, not for the allowance: the same request once more after a wait.
            print(json.dumps({"event": "codex_rate_refused", "again_in_s": again_in}), flush=True)
            time.sleep(again_in)
            reply.unlink(missing_ok=True)
        # The CLI's own last line is the only record of why; it names no page content.
        raise ChatGptWebError(f"the Codex CLI ended without a reply: {_last_line(stderr) or _last_line(stdout)}")

    @classmethod
    def _find(cls, directory: Path, environment: dict, pages: list[dict], *, model: str, timeout: float) -> dict | None:
        """Where the pages of these photos are (``_find_batch``), taking what was prepared ahead of each photo
        (``prepare``) and asking only about the others. The same layout either way; None when nothing at all could
        be located.

        A photo not prepared whose request then fails without saying why goes as a photo with no page found; what
        that request raises (a usage limit, a model not offered, no reply in its time) is raised here."""
        ordered = sorted(pages, key=lambda page: page["page_number"])
        taken = _taken(ordered, min(timeout, 900))
        if not taken:
            return cls._find_batch(directory, environment, ordered, model=model, timeout=timeout)
        rest = [number for number in range(1, len(ordered) + 1) if number not in taken]
        asked = (cls._find_batch(directory, environment, [ordered[number - 1] for number in rest], model=model,
                                 timeout=timeout) if rest else None)
        layout = {"ordered": ordered, "sizes": [], "found": {}, "partial": set(), "boxes": {}, "photos": {},
                  "views": {}, "ahead": taken}
        for number, page in enumerate(ordered, 1):
            made = taken.get(number)
            if made is not None:
                layout["sizes"].append(made["size"])
                layout["found"][number] = made["regions"]
                if made["partial"]:
                    layout["partial"].add(number)
                for printed, box in enumerate(made["boxes"], 1):
                    layout["boxes"][number, printed] = box
                continue
            if asked is None:
                with Image.open(page["image_path"]) as source:
                    layout["sizes"].append(source.size)
                continue
            local = rest.index(number) + 1
            layout["sizes"].append(asked["sizes"][local - 1])
            layout["views"][number] = asked["views"][local]
            if local in asked["found"]:
                layout["found"][number] = asked["found"][local]
                for printed in range(1, len(asked["found"][local]) + 1):
                    layout["boxes"][number, printed] = asked["boxes"][local, printed]
            if local in asked["partial"]:
                layout["partial"].add(number)
            if local in asked["photos"]:
                layout["photos"][number] = asked["photos"][local]
        return layout

    @classmethod
    def _find_batch(cls, directory: Path, environment: dict, pages: list[dict], *, model: str, timeout: float,
                    keep: int | None = None) -> dict | None:
        """Write each photo's small view into ``directory`` and ask where its pages are: the photos in order, their
        sizes, the regions found (``_regions``), each region's box in pixels with the way its lines run and the scale
        wanted for it, the photos still in memory (``keep`` bytes of pixels, ``_PHOTOS_KEPT``), each photo's view
        and, of what was prepared ahead, nothing.

        None when nothing could be located at all (the caller sends the photos as before). A usage limit is raised,
        and so is a model that is not offered: the request for the answers would end the same way. So is a request
        that did not come back in its time (20 s for 14 photos, 40 s for 31 on record): the CLI or the service is
        stalling, and until 2026-11-17 the reads then ran their full time behind it with the wearer waiting.
        """
        ordered = sorted(pages, key=lambda page: page["page_number"])
        sizes, views, photos, kept = [], [], {}, 0
        keep = _PHOTOS_KEPT if keep is None else keep
        for number, page in enumerate(ordered, 1):
            with Image.open(page["image_path"]) as source:
                photo = _readable(source.convert("RGB"))
            sizes.append(photo.size)
            view = photo
            if kept + photo.width * photo.height * 3 <= keep:
                kept += photo.width * photo.height * 3
                photos[number], view = photo, photo.copy()
            view.thumbnail((1024, 1024))
            view.save(directory / f"photo{number:03d}.jpg", quality=85)
            views.append(f"photo{number:03d}.jpg")
        try:
            reply = cls._exec(directory, environment, model=model, effort="low", images=views, prompt=_LOCATE_PROMPT,
                              timeout=min(timeout, 900), schema=_LOCATE_SCHEMA)
        except (ChatGptWebRateLimit, ChatGptWebModelMismatch, ChatGptWebReplyIncomplete):
            raise
        except ChatGptWebError:
            return None
        found, partial = _regions(reply, len(ordered))
        if not found:
            return None
        boxes: dict[tuple[int, int], tuple[tuple[int, int, int, int], bool | None, float]] = {}
        for number, page in enumerate(ordered, 1):
            width, height = sizes[number - 1]
            for printed, (left, top, right, bottom, vertical) in enumerate(found.get(number, ()), 1):
                pad_x = max((right - left) * _REGION_MARGIN, _REGION_MARGIN_LEAST)
                pad_y = max((bottom - top) * _REGION_MARGIN, _REGION_MARGIN_LEAST)
                box = (max(0, round((left - pad_x) * width)), max(0, round((top - pad_y) * height)),
                       min(width, round((right + pad_x) * width)), min(height, round((bottom + pad_y) * height)))
                boxes[number, printed] = (box, vertical, _wanted_scale((box[2] - box[0], box[3] - box[1]), clip=clip_page(page)))
        return {"ordered": ordered, "sizes": sizes, "found": found, "partial": partial, "boxes": boxes, "photos": photos,
                "views": {number: directory / name for number, name in enumerate(views, 1)}, "ahead": {}}

    @classmethod
    def _cut(cls, directory: Path, layout: dict, limit_of, folder: Path | None = None) -> list[str]:
        """Write each located photo's regions, enlarged and cut, and their names in sending order. A photo with no
        region goes as the Chat route sends it; one of which something returned was left out goes whole beside its
        regions. ``limit_of(place)`` is the long side that photo's regions may be sent at (``_target_long``).

        Into ``directory``, where the small views become the overviews; or into ``folder``, a second set at another
        size, to which the overviews are copied. One photo is in memory at a time."""
        (folder or directory).mkdir(exist_ok=True)
        names = []
        for number in range(1, len(layout["ordered"]) + 1):
            names += cls._cut_page(directory, layout, number, limit_of(number), folder)
        return names

    @staticmethod
    def _cut_page(directory: Path, layout: dict, number: int, limit: float, folder: Path | None = None) -> list[str]:
        """The files of one photo (``_cut``), written, and their names in sending order: its overview first when
        pages were found on it. A photo prepared ahead whose regions go at their own size is not opened: its files
        are copied as they were made."""
        target = folder or directory
        page, found, boxes = layout["ordered"][number - 1], layout["found"], layout["boxes"]
        label = f"{page['page_number']:03d}"
        if number not in found:
            # No region here: this photo as the Chat route prepares it (paper crop, fold split), at its own size.
            names = []
            for payload in source_images([page]):
                (target / payload["name"]).write_bytes(payload["buffer"])
                names.append(payload["name"])
            return names
        overview, made = f"overview{label}.jpg", layout["ahead"].get(number)
        if made is not None and not all((made["folder"] / name).is_file() for name in made["names"]):
            # What was prepared has since been removed (it is kept ``_AHEAD_KEPT_S``, and a booklet may be answered
            # again later than that): where its pages lie is still known, and the photo is cut here.
            made = None
        photo = layout["photos"].pop(number, None)
        if folder is not None:
            shutil.copyfile(directory / overview, folder / overview)
        elif made is not None:
            shutil.copyfile(made["folder"] / overview, directory / overview)
        elif number in layout["views"]:
            layout["views"][number].replace(directory / overview)
        else:
            with Image.open(page["image_path"]) as source:
                photo = _readable(source.convert("RGB"))
            view = photo.copy()
            view.thumbnail((1024, 1024))
            view.save(directory / overview, quality=85)
        regions = [boxes[number, printed] for printed in range(1, len(found[number]) + 1)]
        if made is not None and all(limit >= wanted * max(box[2] - box[0], box[3] - box[1]) for box, _, wanted in regions):
            for name in made["names"][1:]:
                shutil.copyfile(made["folder"] / name, target / name)
            return list(made["names"])
        names = [overview]
        if photo is None:
            with Image.open(page["image_path"]) as source:
                photo = _readable(source.convert("RGB"))
        for printed, (box, vertical, wanted) in enumerate(regions, 1):
            crop = photo.crop(box)
            scale = min(wanted, limit / max(crop.size))
            for tile_number, (tile, _) in enumerate(page_tiles(crop, vertical_text=vertical, min_scale=scale,
                                                               max_scale=scale)):
                name = f"page{label}-{printed}{_letters(tile_number)}.jpg"
                tile.save(target / name, format="JPEG", quality=92, subsampling=0)
                names.append(name)
        if number in layout["partial"]:
            # Something returned for this photo was left out. The whole frame goes too, uncropped (the paper crop
            # could cut off just what was left out), so that what no region shows is more than the small view.
            photo.save(target / f"page{label}.jpg", format="JPEG", quality=92, subsampling=0)
            names.append(f"page{label}.jpg")
        return names

    def prepare(self, pages: list[dict], *, booklet: bool = False) -> None:
        """Take pages whose images are final and do with them, on threads of their own, what a booklet's answers
        wait for: find where the paper's pages lie on each and cut them (kept by the page's file, ``_page_key``),
        and, when ``booklet`` says these are all of a booklet's pages, ask where its major problems begin. Returns
        at once; a page named again is not prepared twice. Answering takes what is there (``_find``, ``_outline``,
        ``_run``) and does itself what is not, so whatever fails here costs one small request and nothing else.

        Until 2026-11-19 the first request about a booklet left only when its answers were asked for, after the
        last clip had been gathered: on the phone, 32 to 76 s in which most pages were final and untouched, then 20
        to 54 s of locating and 14 to 24 s of cutting with the wearer waiting (records of 2026-11-18).
        """
        if (os.environ.get("ROKID_CODEX_AHEAD") or "1") == "0" or not chatgpt_send_enabled() or not pages:
            return
        try:
            _ahead_sweep()
            fresh, outline, now = [], None, time.time()
            ordered = sorted(pages, key=lambda page: page["page_number"])
            keys = [_page_key(page) for page in ordered]
            locate = (os.environ.get("ROKID_CODEX_LOCATE") or "1") != "0"
            whole = tuple(keys) if booklet and self._outline_wanted(ordered, _parts_set() or 1) else None
            with _ahead_lock:
                for page, key in zip(ordered, keys) if locate else ():
                    if key not in _ahead:
                        _ahead[key] = (concurrent.futures.Future(), now)
                        fresh.append((page, _ahead[key][0]))
                if whole is not None and whole not in _ahead_outlines:
                    _ahead_outlines[whole] = (concurrent.futures.Future(), now)
                    outline = _ahead_outlines[whole][0]
            if fresh:
                threading.Thread(target=self._prepare_pages, args=(fresh,), name="codex-ahead", daemon=True).start()
            if outline is not None:
                threading.Thread(target=self._prepare_outline, args=(list(pages), outline), name="codex-ahead-outline",
                                 daemon=True).start()
        except Exception as error:  # noqa: BLE001 - nothing prepared is the booklet as it was answered before
            _log_cause("codex_ahead_failed", error)

    @classmethod
    def _prepare_pages(cls, fresh: list[tuple[dict, concurrent.futures.Future]]) -> None:
        """One request for where these photos' pages lie, and their files, into a folder that is kept."""
        with _ahead_turn:
            live = [(page, future) for page, future in fresh if future.set_running_or_notify_cancel()]
            made, began = {}, time.monotonic()
            try:
                if live:
                    pages = [page for page, _ in live]
                    root = Path(config.DATA_DIR) / "codex-ahead"
                    root.mkdir(parents=True, exist_ok=True)
                    folder = Path(tempfile.mkdtemp(prefix="pages-", dir=root))
                    _, locating = _time_allowed(len(pages))
                    with cls._workplace(locating) as (_, environment):
                        layout = _with_model(lambda model: cls._find_batch(
                            folder, environment, pages, model=model, timeout=locating, keep=_AHEAD_PHOTOS_KEPT))
                    for number, page in enumerate(layout["ordered"] if layout else [], 1):
                        if number not in layout["found"]:
                            continue
                        names = cls._cut_page(folder, layout, number, math.inf)
                        made[id(page)] = {
                            "folder": folder, "size": layout["sizes"][number - 1], "regions": layout["found"][number],
                            "partial": number in layout["partial"], "names": names,
                            "boxes": [layout["boxes"][number, printed]
                                      for printed in range(1, len(layout["found"][number]) + 1)]}
            except BaseException as error:  # noqa: BLE001 - a usage limit too: the booklet's own request says so
                made = {}
                _log_cause("codex_ahead_failed", error)
            finally:
                for page, future in live:
                    future.set_result(made.get(id(page)))
                if live:
                    print(json.dumps({"event": "codex_ahead", "pages": len(live), "located": len(made),
                                      "seconds": round(time.monotonic() - began, 1)}), flush=True)

    @classmethod
    def _prepare_outline(cls, pages: list[dict], future: concurrent.futures.Future) -> None:
        if not future.set_running_or_notify_cancel():
            return
        told: tuple[list, list[int]] = ([], [])
        folder = None
        try:
            root = Path(config.DATA_DIR) / "codex-ahead"
            root.mkdir(parents=True, exist_ok=True)
            folder = Path(tempfile.mkdtemp(prefix="outline-", dir=root))
            _, locating = _time_allowed(len(pages))
            with cls._workplace(locating) as (_, environment):
                told = cls._outline(folder / "outline", environment, pages, model=_model(), timeout=locating, running=[])
        except BaseException as error:  # noqa: BLE001
            _log_cause("codex_ahead_failed", error)
        finally:
            future.set_result(told)
            if folder is not None:
                shutil.rmtree(folder, ignore_errors=True)

    @classmethod
    def _outline_wanted(cls, pages: list[dict], parts: int) -> bool:
        """Whether a booklet of these pages is asked where its major problems begin: four captures at least, and
        either the first read is set to be made in parts or the booklet may be more than one request holds (it is
        then read in parts so that no page has to be reduced, ``_sized``)."""
        return len(pages) >= 4 and (parts > 1 or _might_not_fit(cls._photo_sizes(pages)))

    @classmethod
    def _located(cls, directory: Path, environment: dict, pages: list[dict], *, model: str, timeout: float) -> list[str] | None:
        """The names, in sending order, of the booklet's images for one request that carries all of it (``_find``,
        then ``_cut`` at the size that fits); None when nothing could be located."""
        layout = cls._find(directory, environment, pages, model=model, timeout=timeout)
        if layout is None:
            return None
        limit = _target_long(*_layout_cost(layout, None))
        return cls._cut(directory, layout, lambda number: limit)

    @staticmethod
    def _sized(layout: dict, numbers: list[int], told, parts: int):
        """How a booklet whose pages were located is sent: (the long side each photo's regions may be sent at in a
        part or in the one request, the parts the first read is made in whatever is set, the long side the pages of
        those parts are held to, the long side the pages of the whole booklet's request are held to). The last two
        are None for "its own size".

        A booklet that fits one request: nothing is held back and nothing decided here (the first read's parts are
        the caller's, by the setting). One that does not, a common test of some forty pages: the first read is made
        in parts by the major problems, in as many as it takes for every part's pages to go at their own size (from
        what is set, two at least, to ``_PARTS_MOST``), and the whole booklet's request is cut a second time at the
        size that fits. Major problems not told: one set, at the size that fits, for both reads.
        """
        whole = _target_long(*_layout_cost(layout, None))
        if whole == math.inf:
            return (lambda number: math.inf), [], None, None
        starts, shared = told()
        place = {page["page_number"]: number for number, page in enumerate(layout["ordered"], 1)}
        chosen = None
        for count in range(max(parts, 2), _PARTS_MOST + 1):
            spans = _section_spans(numbers, starts, count)
            if not spans or (chosen is not None and len(spans) == len(chosen[0])):
                break  # no major problems told, or no more of them to share out
            limits = [_target_long(*_layout_cost(layout, {place[page] for page in numbers
                                                          if first <= page <= last or page in shared}))
                      for first, _, last in spans]
            chosen = (spans, limits)
            if all(limit == math.inf for limit in limits):
                break
        if chosen is None:
            return (lambda number: whole), [], None, whole
        spans, limits = chosen
        page_at = {number: page for page, number in place.items()}

        def limit_of(number: int) -> float:
            page = page_at[number]
            return min((limit for (first, _, last), limit in zip(spans, limits) if first <= page <= last or page in shared),
                       default=math.inf)

        held = [limit for limit in limits if limit != math.inf]
        return limit_of, spans, (min(held) if held else None), whole

    @classmethod
    def _outline(cls, directory: Path, environment: dict, pages: list[dict], *, model: str, timeout: float,
                 running: list) -> tuple[list, list[int]]:
        """(the captures on which the booklet's major problems begin, as the model returned them; the captures that
        hold what is for the whole exam, those the booklet has). Both empty when it could not be told.

        One request at low effort with a small view of every capture, in a folder of its own beside the request
        that locates the pages. Whatever goes wrong here leaves the booklet to the whole reads, which say for
        themselves what is wrong with the route; only the kind of failure is logged."""
        began, starts, shared = time.monotonic(), [], []
        ordered = sorted(pages, key=lambda page: page["page_number"])
        try:
            directory.mkdir()
            views = []
            for page in ordered:
                views.append(f"capture{page['page_number']:03d}.jpg")
                made = _ahead_view(page)
                if made is not None:
                    # The same small view was made when the page was prepared (``_find_batch``): not decoded again.
                    shutil.copyfile(made, directory / views[-1])
                    continue
                with Image.open(page["image_path"]) as source:
                    view = _readable(source.convert("RGB"))
                view.thumbnail((1024, 1024))
                view.save(directory / views[-1], quality=85)
            reply = cls._exec(directory, environment, model=model, effort="low", images=views, prompt=_OUTLINE_PROMPT,
                              timeout=min(timeout, 900), schema=_OUTLINE_SCHEMA, running=running)
            data = extract_json(reply)
            numbers = {page["page_number"] for page in ordered}
            starts = [start for start in data["starts"] if type(start) is int]
            shared = sorted({page for page in data.get("shared") or [] if type(page) is int and page in numbers})
            if len(shared) > _SHARED_MOST:
                shared = []
        except (ChatGptWebError, OSError, MemoryError, ValueError, KeyError, TypeError, AttributeError) as error:
            _log_cause("codex_outline_failed", error)
        print(json.dumps({"event": "codex_outline", "starts": len(set(starts)), "shared": len(shared),
                          "seconds": round(time.monotonic() - began, 1)}), flush=True)
        return starts, shared

    @staticmethod
    @contextlib.contextmanager
    def _workplace(timeout: float = 600.0):
        """A directory of its own and the environment the CLI needs on this host, for as long as one request takes
        (``timeout``: the longest a request made here may take, for the proxy's silent tunnels)."""
        environment = dict(os.environ)
        bundle = Path(os.environ.get("PREFIX", "")) / "etc/tls/cert.pem"
        if os.environ.get("PREFIX") and bundle.is_file():
            environment.setdefault("SSL_CERT_FILE", str(bundle))
        with tempfile.TemporaryDirectory(prefix="rokid-codex-") as folder, contextlib.ExitStack() as stack:
            if _needs_proxy():
                environment["HTTPS_PROXY"] = f"http://127.0.0.1:{stack.enter_context(name_resolving_proxy(timeout))}"
            yield Path(folder), environment

    check_sends = True

    @staticmethod
    def _usage(environment: dict, since: float) -> dict | None:
        """The allowance used, from the session record a request made after ``since`` left; None when it says nothing.

        Of the windows the service names (a week; on some plans five hours as well, and allowance has to remain in
        both), the one nearer its limit: that is the one that stops a booklet."""
        home = Path(environment.get("CODEX_HOME") or Path.home() / ".codex")
        try:
            records = [path for path in (home / "sessions").rglob("rollout-*.jsonl") if path.stat().st_mtime >= since]
            newest = max(records, key=lambda path: path.stat().st_mtime, default=None)
            lines = newest.read_text(encoding="utf-8", errors="replace").splitlines() if newest else []
        except OSError:
            return None
        found = None
        def used(window) -> float:
            share = window.get("used_percent") if isinstance(window, dict) else None
            return share if isinstance(share, (int, float)) and not isinstance(share, bool) else -1.0

        for line in lines:
            try:
                limits = json.loads(line)["payload"]["rate_limits"]
                nearest = max((limits.get("primary"), limits.get("secondary")), key=used)
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
            if used(nearest) >= 0:
                found = nearest
        numbers = {key: found[key] for key in ("used_percent", "window_minutes", "resets_at")
                   if found and isinstance(found.get(key), (int, float)) and not isinstance(found.get(key), bool)}
        return numbers if "used_percent" in numbers else None

    def check(self) -> dict | None:
        if not chatgpt_send_enabled():
            raise ChatGptWebSendNotAuthorized("sending is not authorized")
        if not self._signed_in():
            raise ChatGptWebAuthenticationRequired("the Codex CLI is missing or not signed in; nothing sent")
        squares, picture = check_picture()  # a different picture each time: the reply has to come from the picture
        with self._workplace() as (directory, environment):
            (directory / "canary.jpg").write_bytes(picture)
            asked = time.time() - 2  # a file's time is coarser than the clock on some hosts
            reply = _with_model(lambda model: self._exec(
                directory, environment, model=model, effort="low", images=["canary.jpg"], timeout=120, ephemeral=False,
                prompt="How many black squares are in the attached image? Do not run commands or use tools. Reply "
                       "with the number only."))
            usage = self._usage(environment, asked)
        if re.sub(r"\D", "", reply) != str(squares):
            raise ChatGptWebCheckFailed("the check's reply was not the count the picture shows")
        return {"usage": usage} if usage else None

    @classmethod
    def verify(cls, cli: list[str]) -> None:
        """Raises unless this CLI is signed in and answers one request made with every flag a booklet's requests
        use: a model, the effort and the tier, the sandbox, an image, a reply schema, a reply file, no session
        kept. What a newly installed release is tried with before the route runs it (app/codex_update.py); how it
        reads this system's pages is not what this shows."""
        if not chatgpt_send_enabled():
            raise ChatGptWebSendNotAuthorized("sending is not authorized")
        if not cls._signed_in(cli):
            raise ChatGptWebAuthenticationRequired("the Codex CLI to be tried is not signed in; nothing sent")
        squares, picture = check_picture()
        schema = {"type": "object", "additionalProperties": False, "required": ["squares"],
                  "properties": {"squares": _INTEGER}}
        with cls._workplace() as (directory, environment):
            (directory / "canary.jpg").write_bytes(picture)
            reply = _with_model(lambda model: cls._exec(
                directory, environment, cli=cli, model=model, effort="low", images=["canary.jpg"], timeout=120,
                schema=schema, prompt="How many black squares are in the attached image? Do not run commands or use "
                                      "tools; look at the image and reply once."))
        try:
            counted = extract_json(reply)["squares"]
        except (ValueError, KeyError, TypeError):
            counted = None
        if counted != squares:
            raise ChatGptWebCheckFailed("the reply of the CLI to be tried was not the count the picture shows")

    @staticmethod
    def _photo_sizes(pages: list[dict]) -> list[tuple[tuple[int, int], bool]]:
        """Each photo's size and whether it is a page recorded as a clip, read from the files' headers."""
        sizes = []
        for page in pages:
            with Image.open(page["image_path"]) as source:
                sizes.append((source.size, clip_page(page)))
        return sizes

    @staticmethod
    def _usable(read: concurrent.futures.Future, question: Question) -> bool:
        """Whether this finished read gave a reply an answer list can be made of, as ``answer_all`` judges it."""
        try:
            _booklet_replies(extract_json(read.result()), subject=question.subject, extras={})
        except (ChatGptWebError, OSError, MemoryError, ValueError):
            return False
        return True

    @classmethod
    def _run(cls, question: Question, model: str, on_first=None, said: dict | None = None) -> list[str]:
        """The replies of the reads that answered. ``on_first`` is called with the first reply that is back and
        usable while the other read is still running, and that reply then comes first in what is returned. Until
        2026-11-18 nothing left this call before the slower read ended: on the phone that day one read was back
        minutes before the other was cut at its limit, and the wearer gave up before the answers came."""
        # High: on this system's own pages it read as Extra High did (3.3% of characters wrong against 3.1% on a dark
        # page, 2.5% against 2.0% on a bright one, twelve reads each) and gave the same results on 21 items of hard
        # written mathematics, in 0.66 to 0.78 of the time (2026-11-16, M-36 and M-37; the operator's decision).
        effort = os.environ.get("ROKID_CODEX_EFFORT") or "high"
        entered = time.monotonic()
        timeout, locating = _time_allowed(len(question.document_pages))
        parts = _parts_set()
        if parts is None:
            # A setting that is no number is the read as it was, and said: as an error it would give every booklet
            # to the routes behind this one for the sake of an option.
            parts = 1
            print(json.dumps({"event": "codex_parts_setting_ignored"}), flush=True)
        beside = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        running: list = []
        with cls._workplace(timeout) as (directory, environment), contextlib.ExitStack() as leaving:
            # Whatever ends this call ends what it started: a request left running would hold the folder, and the
            # thread beside would hold the call until that request's own time ran out.
            leaving.callback(beside.shutdown)
            leaving.callback(lambda: [process.kill() for process in running])  # nothing happens to one that has ended
            numbers = sorted(page["page_number"] for page in question.document_pages)
            outline = None
            if cls._outline_wanted(question.document_pages, parts):
                # Asked for whatever is set when the booklet may be more than one request holds: it is then read
                # in parts so that no page has to be reduced (``_sized``). The request made ahead, if one was.
                outline = _outline_ahead(question.document_pages) or beside.submit(
                    cls._outline, directory / "outline", environment, question.document_pages,
                    model=model, timeout=locating, running=running)

            def told() -> tuple[list, list[int]]:
                """Where the major problems begin and what is for the whole exam, once the request beside has said;
                nothing when it could not, or was not asked."""
                try:
                    return outline.result() if outline is not None else ([], [])
                except Exception as error:  # noqa: BLE001 - the outline serves speed and size: its trouble costs no read
                    _log_cause("codex_outline_failed", error)
                    return [], []

            layout = None
            if (os.environ.get("ROKID_CODEX_LOCATE") or "1") != "0":
                layout = cls._find(directory, environment, question.document_pages, model=model, timeout=locating)
            note, forced, parts_long, whole_long, whole_at = _TILES_NOTE, [], None, None, None
            if layout is None:
                names, note = [], _IMAGES_NOTE
                for payload in source_images(question.document_pages):
                    (directory / payload["name"]).write_bytes(payload["buffer"])
                    names.append(payload["name"])
            else:
                limit_of, forced, parts_long, whole_long = cls._sized(layout, numbers, told, parts)
                names = cls._cut(directory, layout, limit_of)
                whole_at = whole_long if forced else None
            if said is not None and whole_long is not None and (not forced or parts_long is not None):
                said["pages_reduced"] = True  # no read sees every page at its own size: the answers say so
            request = {"model": model, "effort": effort, "images": names, "timeout": timeout,
                       "prompt": _ANSWER_ONLY_SYSTEM + "\n\n" + grey_note(question.document_pages) + _ALL_TASK + note}
            began = time.monotonic()
            # What stood between "answer this booklet" and the first request for answers, and how many of its
            # photos had been prepared ahead (``prepare``): the part of the wait that is not the model's reading.
            print(json.dumps({"event": "codex_prepared", "seconds": round(began - entered, 1),
                              "pages": len(numbers), "ahead": len(layout["ahead"]) if layout else 0}), flush=True)

            def part(number: int, index: int, count: int, first: int, own_last: int, last: int) -> str:
                shared = told()[1]
                beside_own = [page for page in shared if not first <= page <= last]
                reply = cls._exec(directory, environment, reply_name=f"reply-{number}-{index}.json", running=running,
                                  **{**request, "images": [name for name in names if _attached(name, first, last, shared)],
                                     "prompt": request["prompt"] + _PART_NOTE.format(
                                         parts=count, first=first, own_last=own_last, last=last) + (
                                         _SHARED_NOTE[len(beside_own) > 1].format(pages=_listed(beside_own))
                                         if beside_own else "")})
                print(json.dumps({"event": "codex_part_done", "read": number, "part": index,
                                  "pages": f"{first}-{own_last}", "seconds": round(time.monotonic() - began, 1)}),
                      flush=True)
                return reply

            def in_parts(number: int, spans: list[tuple[int, int, int]]) -> str:
                """One read as a request for each span, all at once; every one has to come back for the read to."""
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(spans)) as pool:
                    asked = [pool.submit(part, number, index, len(spans), *span) for index, span in enumerate(spans, 1)]
                texts, failures = [], []
                for one in asked:
                    try:
                        texts.append(one.result())
                    except (ChatGptWebError, OSError, MemoryError, ValueError) as error:
                        failures.append(error)
                # ponytail: a part that fails leaves the read's other parts running to their end for nothing. End
                # them (a list of processes for each read) once a trial shows requests wasted that way.
                if failures:
                    raise _decisive(failures)
                return _joined(number, [(first, own_last) for first, own_last, _ in spans], texts)

            def spans_of(number: int) -> list[tuple[int, int, int]]:
                """The parts of the first read: those a booklet too long for one request has to be read in, else
                those the setting asks for, where the major problems are told. The second read is whole."""
                if number != 1:
                    return []
                return forced or (_section_spans(numbers, told()[0], parts) if parts > 1 else [])

            def whole(reply_name: str) -> str:
                """The request that carries the whole booklet. One too long for it at full size is cut a second
                time, into a folder of its own, at the size that fits."""
                if whole_at is None:
                    return cls._exec(directory, environment, reply_name=reply_name, running=running, **request)
                reduced = cls._cut(directory, layout, lambda number: whole_at, folder=directory / "whole")
                return cls._exec(directory / "whole", environment, reply_name=reply_name, running=running,
                                 **{**request, "images": reduced})

            def read(number: int, reply_name: str) -> str:
                # The first read in parts where the major problems are told; the second whole, whatever the first is:
                # it is what a part's answers are compared with, and it has every page for what a part lacked.
                spans = spans_of(number)
                if number == 1:
                    print(json.dumps({"event": "codex_plan", "pages": len(numbers), "parts": len(spans),
                                      "parts_long": None if parts_long is None else round(parts_long),
                                      "whole_long": None if whole_long is None else round(whole_long)}), flush=True)
                reply = in_parts(number, spans) if spans else whole(reply_name)
                # How long each read took, and so how far apart the two of one run end; never what it said.
                print(json.dumps({"event": "codex_read_done", "read": number,
                                  "seconds": round(time.monotonic() - began, 1)}), flush=True)
                return reply

            if (os.environ.get("ROKID_CODEX_READS") or "2").strip() == "1":
                return [read(1, "reply.json")]
            # Two independent reads of the same images at the same time. Until 2026-11-17 the call returned when the
            # slower one ended: one read back at 150 s and the other hung held the wearer to the whole limit.
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                pending = [pool.submit(read, number, f"reply-{number}.json") for number in (1, 2)]
                back, late = concurrent.futures.wait(pending, return_when=concurrent.futures.FIRST_COMPLETED)
                first_s = time.monotonic() - began
                more = min(max(_SECOND_READ_LEAST_S, first_s), _SECOND_READ_MOST_S)
                if outline is not None and outline.done() and spans_of(1):
                    # A read in parts is back in a fraction of the time the whole read takes: waited for only as
                    # long again, the whole read would be ended every time and nothing would ever be compared.
                    more = _SECOND_READ_MOST_S
                # A first read that failed, or whose reply no answer list can be made of, is waited behind as before.
                usable = next((done for done in back if cls._usable(done, question)), None) if late else None
                if usable is not None and on_first is not None:
                    pending.sort(key=lambda done: done is not usable)
                    try:
                        on_first(usable.result())
                    except Exception as error:  # noqa: BLE001 - the caller's trouble with the answers costs neither read
                        _log_cause("codex_first_read_not_handed", error)
                if usable is not None and concurrent.futures.wait(late, timeout=more).not_done:
                    for process in running:
                        process.kill()  # nothing happens to the one that has ended
                    print(json.dumps({"event": "codex_read_cut", "first_s": round(first_s, 1),
                                      "waited_s": round(more, 1)}), flush=True)
            replies, failures = [], []
            for read in pending:
                try:
                    replies.append(read.result())
                # Its own reply file unreadable or not UTF-8 fails this read, not the booklet (until 2026-11-17 it
                # left as a run this host could not carry out, with the other read's reply in hand).
                except (ChatGptWebError, OSError, MemoryError, ValueError) as error:
                    failures.append(error)
            if not replies:
                raise _decisive(failures)
            for error in failures:
                # The other read answers alone; which kind of failure it was is logged, never its text.
                _log_cause("codex_read_failed", error)
            return replies

    def solve(self, *, question: Question, max_answer_len: int = 64) -> SolveResult:
        raise ValueError("codex-cli answers a whole booklet only")
