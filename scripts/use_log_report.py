#!/usr/bin/env python3
"""Where the time of a use went, from the glasses' own record of it.

    adb exec-out cat /sdcard/Android/data/dev.rokid.docscanglass.doc/files/use-log.txt > use-log.txt
    py -3.12 scripts/use_log_report.py use-log.txt

From glassdoc 0.44.19 the app keeps its lines in a file a restart of the glasses does not lose (UseLog:
"<epoch ms> <ms since the glasses started> <tag> <message>"), and writes what logcat never held: every gesture,
every upload with its bytes and time, where each page's seconds went, the end, the wake and the answers. This reads
the last reading in such a file and prints it page by page, then the end and the answers, then what a reader of the
record must not miss (``notes``): a clip whose file took seconds to close, dropped frames, a page of too few still
frames, a clip sent while the next page was being recorded, a call sent again, a refused start, little room left.

Numbers, names and states only, as the file itself holds: nothing of a page or an answer is in it. Exit code 2 when
the file holds no reading. scripts/capture_log_invariants.py checks the same file against the capture's rules.

Runs on: this PC, on a file pulled from the glasses. It reads nothing from a device.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_LINE = re.compile(r"^(\d{12,14}) (\d+) (\S+) (.*)$")
_PAGE = re.compile(r"page index (\d+)")
SLOW_CLOSE_MS = 1000    # from the last frame to the clip's file closed; 140 ms on a desk, 3400 ms once in three
SLOW_RELEASE_MS = 1000  # an encoder let go after its page was handed on
LITTLE_ROOM_MB = 2000   # a booklet of ten-second clips that are not sent is about 1900 MB
ENOUGH_STILL = 40       # of 60: the app's own mark for a clip that is kept as it is


def _fields(message: str) -> dict[str, str]:
    return dict(part.split("=", 1) for part in message.split() if "=" in part)


def _number(fields: dict[str, str], name: str) -> int | None:
    try:
        return int(fields[name])
    except (KeyError, ValueError):
        return None


def last_reading(text: str) -> dict | None:
    """The last reading the file holds, from the app's start before it: its pages, uploads, end and answers."""
    lines = [(int(found[1]), found[3], found[4]) for found in map(_LINE.match, text.splitlines()) if found]
    begun = [at for at, (_, _, message) in enumerate(lines) if message.startswith("reading_start ")]
    if not begun:
        return None
    started = max((at for at in range(begun[-1]) if lines[at][2].startswith("start version=")), default=begun[-1])
    reading = {"version": None, "free_mb": None, "refused": [], "pages": [], "uploads": [], "releases": [],
               "end": {}, "answers": [], "began_ms": lines[begun[-1]][0]}
    pages: dict[int, dict] = {}
    armed = asked = current = None
    saved_at = lines[begun[-1]][0]
    for when, _, message in lines[started:]:
        fields = _fields(message)
        if message.startswith("start version="):
            reading["version"], reading["free_mb"] = fields.get("version"), _number(fields, "free_mb")
        elif message.startswith("start_refused "):
            reading["refused"].append(_number(fields, "free_mb"))
        elif message.startswith("AIMING: ") and armed is None:
            armed = when
        elif message.startswith("CAPTURING: Requesting"):
            index = _PAGE.search(message)
            current = pages.setdefault(int(index[1]) if index else len(pages), {"attempts": 0})
            current.update(index=int(index[1]) if index else len(pages) - 1, asked_ms=when,
                           armed_s=None if armed is None else round((when - armed) / 1000, 2))
            current["attempts"] += 1
            asked = when
        elif message.startswith("clip frames=") and current is not None:
            current.update({name: _number(fields, name) for name in (
                "frames", "counted", "dropped", "bytes", "first_ms", "back_ms", "boost", "open_ms", "idle_ms", "drain_ms",
                "page_ms", "closed_ms")}, kept=fields.get("kept") == "true", idle_timeout=fields.get("idle_timeout") == "true",
                recorded_ms=(asked, when))
        elif message.startswith("clip_release "):
            reading["releases"].append(_number(fields, "ms"))
        elif message.startswith("review_shown "):
            page = pages.get(_number(fields, "index"))
            if page is not None:
                page.update({name: _number(fields, name) for name in ("pending_ms", "decode_ms", "drawn_ms")})
        elif message.startswith("page_saved "):
            page = pages.setdefault(_number(fields, "index"), {"index": _number(fields, "index"), "attempts": 0})
            page.update(cycle_s=round((when - saved_at) / 1000, 2), saved_ms=when,
                        **{name: _number(fields, name) for name in ("record_ms", "hash_ms", "total_ms")})
            saved_at, armed = when, None
        elif message.startswith("upload_begin "):
            reading["uploads"].append({"kind": fields.get("kind"), "index": _number(fields, "index"),
                                       "bytes": _number(fields, "bytes"), "begun_ms": when, "tries": 1})
        elif message.startswith("upload_retry ") and reading["uploads"] is not None:
            reading.setdefault("retries", []).append((fields.get("kind"), _number(fields, "index"), _number(fields, "try")))
        elif message.startswith("upload_end "):
            open_calls = [call for call in reading["uploads"] if "ended_ms" not in call and call["kind"] == fields.get("kind")
                          and call["index"] == _number(fields, "index")]
            if open_calls:
                open_calls[-1].update(ended_ms=when, ms=_number(fields, "ms"), result=fields.get("result"))
            if fields.get("kind") == "finalize" and fields.get("result") == "ok":
                reading["end"]["finalize_call_ms"] = _number(fields, "ms")
        elif message.startswith("finalize_done "):
            reading["end"]["end_to_done_ms"] = _number(fields, "ms")
        elif message.startswith("answers_get "):
            reading["answers"].append({"revision": _number(fields, "revision"), "get_ms": _number(fields, "ms"),
                                       "saved_ms": None, "drawn_ms": None,
                                       **({} if fields.get("result") == "ok" else {"result": fields.get("result")})})
        elif message.startswith("answers_saved ") and reading["answers"]:
            reading["answers"][-1]["saved_ms"] = _number(fields, "ms")
        elif message.startswith("answers_drawn ") and reading["answers"]:
            reading["answers"][-1]["drawn_ms"] = _number(fields, "ms")
    reading["pages"] = [pages[index] for index in sorted(index for index in pages if index is not None)]
    return reading


def notes(reading: dict) -> list[str]:
    """What must not be passed over in a reading, one sentence each; empty when nothing is."""
    said = []
    if reading["free_mb"] is not None and reading["free_mb"] < LITTLE_ROOM_MB:
        said.append(f"{reading['free_mb']} MB free at the start: a booklet of long clips that are not sent needs about that much")
    for room in reading["refused"]:
        said.append(f"a start was refused for want of room ({room} MB free)")
    for page in reading["pages"]:
        name = f"page {page['index'] + 1}"
        if (page.get("drain_ms") or 0) > SLOW_CLOSE_MS:
            said.append(f"{name}: {page['drain_ms']} ms from the last frame to the clip's file closed")
        if page.get("dropped"):
            said.append(f"{name}: {page['dropped']} frame(s) dropped while it was recorded")
        if page.get("kept") and page.get("counted") is not None and page["counted"] < ENOUGH_STILL:
            said.append(f"{name}: the page is a clip of {page['counted']} of 60 still frames")
        if page.get("idle_timeout"):
            said.append(f"{name}: the watch session did not end in its time before the clip")
        if page.get("attempts", 1) > 1:
            said.append(f"{name}: asked for {page['attempts']} times (a clip not kept, a retake or a failed camera)")
        for call in reading["uploads"]:
            span = page.get("recorded_ms")
            if (call["kind"] == "clip" and call["index"] != page["index"] and span and span[0] is not None
                    and call["begun_ms"] < span[1] and call.get("ended_ms", span[1]) > span[0]):
                said.append(f"clip {call['index'] + 1} was being sent while {name} was being recorded "
                            "(the one loss of frames on record was in such an overlap)")
    for kind, index, attempt in reading.get("retries", []):
        said.append((f"{kind} {index + 1}" if index is not None and index >= 0 else str(kind)) + f": sent again (try {attempt})")
    for took in reading["releases"]:
        if took is not None and took > SLOW_RELEASE_MS:
            said.append(f"an encoder took {took} ms to be let go after its page")
    for answer in reading["answers"]:
        if "result" in answer:
            said.append(f"the answers could not be fetched once ({answer['result']})")
    return said


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__.split("\n\n")[1])
        return 2
    raw = Path(argv[0]).read_bytes()
    reading = last_reading(raw.decode("utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8", "replace"))
    if reading is None:
        print("no reading in this file")
        return 2
    print(f"glassdoc {reading['version']}, {reading['free_mb']} MB free at the start, {len(reading['pages'])} page(s)")
    print("page  cycle_s  armed_s  first_ms  frames/still  MB    drain_ms  page_ms  decode_ms  save_ms  hash_ms")
    for page in reading["pages"]:
        megabytes = "-" if page.get("bytes") is None else f"{page['bytes'] / 1e6:.0f}"
        print(f"{page['index'] + 1:>4}  {page.get('cycle_s', '-')!s:>7}  {page.get('armed_s', '-')!s:>7}  "
              f"{page.get('first_ms', '-')!s:>8}  {page.get('frames', '-')!s:>6}/{page.get('counted', '-')!s:<5}  {megabytes:>4}  "
              f"{page.get('drain_ms', '-')!s:>8}  {page.get('page_ms', '-')!s:>7}  {page.get('decode_ms', '-')!s:>9}  "
              f"{page.get('total_ms', '-')!s:>7}  {page.get('hash_ms', '-')!s:>7}")
    cycles = sorted(page["cycle_s"] for page in reading["pages"] if "cycle_s" in page)
    if cycles:
        print(f"a page every {cycles[len(cycles) // 2]} s (median), {cycles[0]} to {cycles[-1]}")
    sent = [call for call in reading["uploads"] if call.get("ms") is not None and call["kind"] in ("page", "clip")]
    for kind in ("page", "clip"):
        calls = [call for call in sent if call["kind"] == kind]
        if calls:
            megabytes = sum(call["bytes"] or 0 for call in calls) / 1e6
            seconds = sum(call["ms"] for call in calls) / 1000
            print(f"{kind}s sent: {len(calls)}, {megabytes:.0f} MB in {seconds:.1f} s"
                  + (f" ({megabytes / seconds:.1f} MB/s)" if seconds else ""))
    if reading["end"]:
        print("the end:", ", ".join(f"{name} {value}" for name, value in reading["end"].items()))
    for answer in reading["answers"]:
        print("answers:", ", ".join(f"{name} {value}" for name, value in answer.items()))
    noted = notes(reading)
    print("to note:" if noted else "nothing to note")
    for line in noted:
        print("  -", line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
