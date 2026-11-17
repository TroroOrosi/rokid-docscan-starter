"""Checks the glasses' logcat of a capture against five rules and prints every violation.

    py -3.12 scripts/capture_log_invariants.py <logcat.txt> [--since HH:MM:SS]

For desk-check logs and for worn logs. Reads only the app's own lines (tag DocScanGlassDoc) of a saved
`adb logcat -v threadtime` or `-v time`; reads nothing from a device. One line per violation, with the time of the
offending line(s). Exit code 1 when a rule is violated, 0 when none is, 2 when the file holds no line of the app
(a wrong file must not read as a clean capture).

What the rules rest on, each written by the app as it stands (android-relay/glassdoc):
  <STATE>: <diagnostic>               the controller, one line per update (DocScanGlassActivity.onUpdate)
  captured 4032x3024 in 817 ms        a page handed to the controller (DocScanGlassActivity); the still camera's own
                                      "captured 4032x3024 1830221B in 817ms gen=3" is the same photo and is not counted
  clip frames=66 counted=60 ... kept=true short=0     a clip that ended (ClipCamera); kept=true is followed by its
                                      "captured" line, kept=false by "preparation expired": one answer, two lines
  preview_status ... pending=false page_ready=true future=false ...     the still camera, once a second while it watches

R1  Five or more preview_status lines in a row with pending, page_ready and future all false, while the controller
    is in READY or READING, not paused and with no end asked for: automatic capture has stopped silently.
R2  After "Photo committed locally" the next controller line comes within 10 s and is an AIMING, a pause, a
    CAPTURE_REVIEW, a FINALIZING or another save; else nothing happens after a save. Ten quiet seconds are not a
    violation while the still camera says in them that it waits for a page (page_ready=true) or is busy: the wearer
    has not turned the page, or the paper on the desk has not changed. The clip camera writes no such line, so on
    that route the ten seconds stand alone. A line of the upload ("Network work paused") is not a line about the
    capture: here and in R5 it is passed over.
R3  Every "CAPTURING: Requesting" is answered exactly once before the next one: by a photo, by a clip, or by
    "preparation expired" / "Retake did not start". A request with no answer is not reported when an ERROR or a
    FINALIZING line follows it (the capture failed, or it was ended while the page was being asked for), or when
    the log ends within 60 s of it.
R4  Every diagnostic that holds "Finish rejected", "Finish ignored" or "Observed scene was not captured".
R5  A clip with fewer than 40 counted frames that became a page (kept=true) before the third short clip in a row
    (short under 2), unless the wearer cut it short: the controller line before it, within 12 s, says the capture
    was paused, or the capture ends with that page (a double tap during a recording writes no line of its own; it
    shows as a FINALIZING line with no further page asked for in between).
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

TAG = "DocScanGlassDoc"
_LINE = re.compile(
    r"^(?:(?:\d{4}-)?(\d\d)-(\d\d)\s+(\d\d):(\d\d):(\d\d)\.(\d{3}))?.*?\b" + TAG + r"\b(?:\s*\(\s*\d+\s*\))?\s*:\s?(.*)$"
)
_STATE = re.compile(
    r"^(DISCONNECTED|READY|AIMING|STABILIZING|CAPTURING|OCR|CAPTURE_REVIEW|UPLOADING|READING|LISTENING|FINALIZING"
    r"|REVIEW|ERROR): (.*)$"
)
_PHOTO = re.compile(r"^captured \d+x\d+ in \d+ ms$")
_WAITING = ("READY", "READING")
_SAVED = "Photo committed locally"
_PAUSED = "Capture paused by the wearer"
# No line of the app at this commit says that the wearer ended the capture; the second wording is for one that will.
_CUT_SHORT = ("paused by the wearer", "ended by the wearer")
_END_ASKED = ("Finish rejected", "Finish ignored", "before finishing", "Local capture finished")
_STATUS_WINDOW = 5
_AFTER_SAVE_S = 10.0
_REQUEST_GRACE_S = 60.0
_SHORT_CLIP_FRAMES = 40
_CUT_SHORT_S = 12.0


@dataclass(frozen=True)
class Entry:
    time: float  # seconds; a line without a time carries the time of the line before it
    stamp: str  # HH:MM:SS.mmm as written, "?" when the line has none
    text: str  # the app's message
    state: str | None  # the controller's state, for a controller line
    diagnostic: str


@dataclass(frozen=True)
class Violation:
    rule: str
    lines: tuple[Entry, ...]
    message: str

    def __str__(self) -> str:
        first, last = self.lines[0], self.lines[-1]
        when = first.stamp if first.stamp == last.stamp else f"{first.stamp}-{last.stamp}"
        return f"{self.rule} {when} {self.message} | {first.text}"


def parse(text: str, since: str | None = None) -> list[Entry]:
    """The app's lines in order; with `since`, from the first line at or after that time of day."""
    entries: list[Entry] = []
    time, started = 0.0, since is None
    for line in text.splitlines():
        match = _LINE.match(line.rstrip())
        if not match:
            continue
        month, day, hour, minute, second, millis, message = match.groups()
        stamp = "?"
        if month:
            # Year 2000 only places the day: logcat writes none, and a leap year takes 02-29.
            moment = datetime(2000, int(month), int(day), int(hour), int(minute), int(second))
            time = (moment - datetime(2000, 1, 1)).total_seconds() + int(millis) / 1000
            stamp = f"{hour}:{minute}:{second}.{millis}"
        if not started:
            if stamp == "?" or stamp[:8] < since:
                continue
            started = True
        state = _STATE.match(message)
        entries.append(Entry(time, stamp, message, state.group(1) if state else None, state.group(2) if state else ""))
    return entries


def _flags(text: str) -> dict[str, str]:
    return dict(part.split("=", 1) for part in text.split() if "=" in part)


def _about_capture(entry: Entry) -> bool:
    """A controller line other than the upload's own, which comes whenever the phone cannot be reached."""
    return entry.state is not None and not entry.diagnostic.startswith("Network work paused")


def _is_status(entry: Entry) -> bool:
    return entry.text.startswith("preview_status ")


def _camera_idle(entry: Entry) -> bool:
    flags = _flags(entry.text)
    return all(flags.get(name) == "false" for name in ("pending", "page_ready", "future"))


def r1(entries: list[Entry]) -> list[Violation]:
    found: list[Violation] = []
    run: list[Entry] = []
    state, paused, ending, manual = None, False, False, False

    def close() -> None:
        if len(run) >= _STATUS_WINDOW:
            found.append(Violation(
                "R1", tuple(run),
                f"automatic capture has stopped silently: {len(run)} preview_status lines with no page waited for",
            ))
        run.clear()

    for entry in entries:
        if entry.state:
            state, text = entry.state, entry.diagnostic
            if "Started local capture session" in text:
                paused = ending = manual = False
            if text.startswith(_PAUSED):
                paused = True
            elif text.startswith(("Capture resumed by the wearer", "Tap dropped")):
                paused = False
            if any(mark in text for mark in _END_ASKED):
                ending = True
            elif "Finish not taken" in text:
                ending = False
            if text.startswith("Manual capture:"):
                manual = True
            if state not in _WAITING or paused or ending or manual:
                close()
        elif _is_status(entry):
            if _camera_idle(entry) and state in _WAITING and not (paused or ending or manual):
                run.append(entry)
            else:
                close()
    close()
    return found


def r2(entries: list[Entry]) -> list[Violation]:
    found: list[Violation] = []
    for index, entry in enumerate(entries):
        if not (entry.state and entry.diagnostic.startswith(_SAVED)):
            continue
        after = entries[index + 1:]
        following = next((later for later in after if _about_capture(later)), None)
        if following is not None and following.time - entry.time <= _AFTER_SAVE_S:
            allowed = following.state in ("AIMING", "CAPTURE_REVIEW", "FINALIZING") or following.diagnostic.startswith(
                (_PAUSED, _SAVED)
            )
            if not allowed:
                found.append(Violation("R2", (entry, following), "after a save the controller goes on with neither "
                                       "a page, a pause, a review, the end nor another save"))
            continue
        if entries[-1].time - entry.time < _AFTER_SAVE_S:
            continue  # the log ends before the ten seconds are over
        window = [later for later in after if later.time - entry.time <= _AFTER_SAVE_S]
        if any(_is_status(later) and not _camera_idle(later) for later in window):
            continue  # the still camera waits for the next page, or is taking one
        found.append(Violation("R2", (entry,), f"nothing happens within {_AFTER_SAVE_S:.0f} s of a save"))
    return found


def r3(entries: list[Entry]) -> list[Violation]:
    found: list[Violation] = []
    requests = [
        index for index, entry in enumerate(entries)
        if entry.state == "CAPTURING" and entry.diagnostic.startswith("Requesting")
    ]
    for number, start in enumerate(requests):
        stop = requests[number + 1] if number + 1 < len(requests) else len(entries)
        span = entries[start + 1:stop]
        photos = [entry for entry in span if _PHOTO.match(entry.text)]
        unstarted = [
            entry for entry in span
            if entry.state and ("preparation expired" in entry.diagnostic or "Retake did not start" in entry.diagnostic)
        ]
        clips = [entry for entry in span if entry.text.startswith("clip frames=")]
        # A clip and the line that follows it (its photo, or "preparation expired") are one answer.
        answers = max(len(photos) + len(unstarted), len(clips))
        if answers == 1:
            continue
        request = entries[start]
        if answers > 1:
            found.append(Violation("R3", (request, *photos, *unstarted, *clips),
                                   f"a camera request is answered {answers} times"))
        elif not any(entry.state in ("ERROR", "FINALIZING") for entry in span) and not (
            stop == len(entries) and entries[-1].time - request.time <= _REQUEST_GRACE_S
        ):
            found.append(Violation("R3", (request,), "a camera request is never answered"))
    return found


def r4(entries: list[Entry]) -> list[Violation]:
    marks = ("Finish rejected", "Finish ignored", "Observed scene was not captured")
    return [
        Violation("R4", (entry,), next(mark for mark in marks if mark in entry.diagnostic))
        for entry in entries
        if any(mark in entry.diagnostic for mark in marks)
    ]


def r5(entries: list[Entry]) -> list[Violation]:
    found: list[Violation] = []
    for index, entry in enumerate(entries):
        if not entry.text.startswith("clip frames="):
            continue
        flags = _flags(entry.text)
        try:
            counted, short = int(flags["counted"]), int(flags["short"])
        except (KeyError, ValueError):
            continue  # a build before kept= and short=: its line cannot be judged
        if counted >= _SHORT_CLIP_FRAMES or flags.get("kept") != "true" or short >= 2:
            continue
        before = next((earlier for earlier in reversed(entries[:index]) if _about_capture(earlier)), None)
        if before is not None and entry.time - before.time <= _CUT_SHORT_S and any(
            mark in before.diagnostic for mark in _CUT_SHORT
        ):
            continue
        onward = next((later for later in entries[index + 1:] if later.state in ("AIMING", "CAPTURING", "FINALIZING")), None)
        if onward is not None and onward.state == "FINALIZING":
            continue  # the wearer ended the capture during this recording
        found.append(Violation("R5", (entry,), f"a short clip was saved as a page: {counted} counted frames"))
    return found


RULES = (r1, r2, r3, r4, r5)


def violations_of(entries: list[Entry]) -> list[Violation]:
    return [violation for rule in RULES for violation in rule(entries)]


def check(text: str, since: str | None = None) -> list[Violation]:
    return violations_of(parse(text, since))


def _read(path: Path) -> str:
    data = path.read_bytes()
    # Windows PowerShell 5 writes a redirected `adb logcat` as UTF-16; read as UTF-8 it would hold no line of the app.
    return data.decode("utf-16" if data[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a glasses capture logcat against rules R1-R5.")
    parser.add_argument("log", type=Path, help="saved `adb logcat -v threadtime` (or -v time) text")
    parser.add_argument("--since", metavar="HH:MM:SS", help="leave out everything before this time of day")
    arguments = parser.parse_args(argv)
    if arguments.since and not re.fullmatch(r"\d\d:\d\d:\d\d", arguments.since):
        parser.error("--since takes HH:MM:SS")
    entries = parse(_read(arguments.log), arguments.since)
    if not entries:
        print(f"no {TAG} line in {arguments.log}" + (f" since {arguments.since}" if arguments.since else ""),
              file=sys.stderr)
        return 2
    violations = violations_of(entries)
    for violation in violations:
        print(violation)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
