#!/usr/bin/env python3
"""Play a booklet a wearer really recorded to a running server again, as the glasses sent it.

    py -3.12 scripts/replay_booklet.py --source-data <a server data folder> --document <id>
        --server http://host:port --key <api key or @file> [--pace recorded|fast|<seconds per page>]
        [--report out.json] [--timeout 1800] [--target-data <the target server's data folder>]
        [--gather-limit 200] [--new-capture-ids] [--real-solver]

A rehearsal of the server half of a use: the uploads, the gathering of the clips, the wait at the end, the hand-over to
the solver, the answers. After a use the server keeps each page's first frame and gathered image (data/images), each
page's clip (data/page-clips, three days) and when each arrived (docscan.db). This reads one document out of such a
folder, never writing there, and sends it to --server with the requests the glasses send (relaycore's DocScanApi and
DocScanController.queueLocalUpload), one at a time as their one network thread does:

    GET  /v1/settings                               which solver answers; refused unless it is the stand-in (below)
    POST /v1/glasses/state                          capturing; later analyzing with the session, reading, closed
    POST /v1/documents                              the title and device of the source's document
    POST /v1/documents/{id}/pages                   page_index, image_rotation, captured_at_ms, the JPEG, capture_provenance
    POST /v1/documents/{id}/pages/{index}/clip      capture_id, sha256, record, the MP4
    POST /v1/documents/{id}/finalize                right after the last upload; it waits for the gathering
    POST /v1/exam-sessions                          mode study, the document, exam_type, answer_format mark
    POST /v1/exam-sessions/{id}/finalize-reading?solve=background
    GET  /v1/exam-sessions/{id}/answer-bundle       once a second, until every item is answered or --timeout is over

and beside them, twice a second, GET /v1/documents/{id}/clips: how far each clip has come.

--pace recorded (the default) sends each request when it arrived at the source's server: a page at its row's time
(kept to the second), a clip when its upload was complete. fast sends them back to back in that order. A number sends a
page every so many seconds, its clip right behind it.

It prints, and writes to --report, counts, times, statuses and codes only: no text of a page or of an answer. Per
page: when it was sent and how long the upload took. Per clip: seconds from its arrival to gathered and the frames
used of those offered, beside the source's own. The wait inside finalize, the seconds from finalize to the answers, the
items by status, the pages the answers name as left one frame. With --target-data (the target's data folder, only
read) a clip's seconds are its row's own and the failure codes of unanswered questions are counted; without it the
seconds are what asking twice a second saw.

Four named checks end the report, PASS or FAIL, and the exit code is 1 when one of them fails: a clip not gathered, a
finalize that failed or waited to within a quarter of the server's limit, no answers, a failed item or a failure
code. A request the glasses would not get past either (a page refused, a failed finalize) stops the replay there and
fails the checks behind it. 2: the source could not be used, or the target was refused; nothing was judged.

The target's solver answers the booklet. With anything but the stand-in (ROKID_SOLVER=recorded) that spends the
operator's allowance, so such a target is refused unless --real-solver is given.

What it cannot play as it was:
- the moment the capture was ended: no record keeps it. Finalize is sent right after the last upload, the earliest the
  glasses can send it and the longest wait at the end;
- a page taken again: only its last capture is kept, and it is sent at the time the page first arrived;
- a clip whose file is gone (three days after it was gathered) or that never reached the source's server: the page goes
  out without it and the first check fails;
- a frame whose JPEG is gone: the stored page image is turned back, reduced to the frame's size and sent as a JPEG, and
  the report says so;
- phone OCR (the relay route), capture-inspection origins, a recording (a mixed or listening session is sent as a
  written one), the glasses' retries after a lost connection, and the hotspot: a clip arrives at this machine's speed;
- the watcher: the answers are asked for here, where at the venue the phone's watcher asks and wakes the glasses.

Nothing of the glasses is in it: the capture, the camera, the gestures, the display, what the wearer reads.

To the server a capture is its ID. A target that already holds this booklet (an earlier replay) refuses the same IDs
with a 409: --new-capture-ids gives every capture a new one.

Standard library only; Pillow, which the server has, only for the stand-in frame above.
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import http.client
import io
import itertools
import json
import re
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

FIRST_FRAME = "the frame the glasses sent"
STAND_IN_FRAME = "stand-in: the stored page image turned back and sent as a JPEG (the frame's own JPEG is not stored)"
STAND_IN_IMAGE = "stand-in: the stored page image as it is (the page has no capture record)"
NOT_SENT = "not sent: its file is gone from the source"
NO_CLIP = "not sent: the source holds no clip of this recorded page"

CHECKS = ("every clip gathered before the booklet went on",
          "the wait at finalize is under the server's limit with margin",
          "answers arrived",
          "no page left as one frame")
# The server's own limit (app/main.py, _GATHER_WAIT_S). --gather-limit for a server started with another ROKID_GATHER_WAIT_S.
GATHER_WAIT_S = 200.0
# The wait at finalize passes only up to three quarters of the limit. On 2026-11-18 a clip was gathered 165 s after the
# end against a limit of 150 s, a day after the wait had been noted as near it. And a rehearsal on a PC is not the
# phone: a 60-frame desk clip was gathered in 34-35 s there (M-26) and in 7-10 s on the development PC.
WAIT_MARGIN = 0.25
POLL_S = 0.5  # how often the clips' states are asked for: a clip's seconds to gathered are this coarse
# How long the glasses' own calls wait (DocScanApi): an ordinary one reads for four minutes, a clip may take ten,
# finalize-reading two.
CALL_S, CLIP_S, READING_S = 240.0, 600.0, 120.0
# The glasses let a clip refused with one of these go, and the booklet goes on without it (DocScanController).
CLIP_LET_GO = (400, 404, 409, 413, 422)


class SourceError(Exception):
    """The source folder cannot give this booklet."""


class Refused(Exception):
    """The target is not one this booklet may be sent to."""


class _Stopped(Exception):
    """A request the glasses would not get past either."""

    def __init__(self, step: str, status: int, answer: dict):
        super().__init__(step)
        self.at = {"step": step, "http": status, "detail": _said(answer)}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def _epoch(created_at) -> float:
    """pages.created_at is sqlite's datetime('now'): UTC, whole seconds. page_clips.created_at is time.time()."""
    if isinstance(created_at, (int, float)):
        return float(created_at)
    return datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()


def load_booklet(source: Path, document: int) -> dict:
    """One document of a server's data folder, as far as it can be sent again. The folder is only read.

    {"title", "capture_device", "exam_type", "session_made" (None: the booklet never went on), "pages": [{"index",
    "arrived", "captured_at_ms", "provenance", "frame", "kind"}], "clips": [{"index", "capture_id", "sha256", "record",
    "path" (None: the file is gone), "bytes", "arrived", "source": {"status", "used", "total", "gather_s"}}]}. Times
    are seconds since the epoch on the source's server.
    """
    database = Path(source) / "docscan.db"
    if not database.is_file():
        raise SourceError(f"no docscan.db in {source}")
    conn = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        described = conn.execute("SELECT title, capture_device FROM documents WHERE id = ?", (document,)).fetchone()
        pages = conn.execute("SELECT page_index, image_path, captured_at_ms, capture_metadata_json, created_at FROM pages "
                             "WHERE document_id = ? ORDER BY page_index", (document,)).fetchall()
        clips = conn.execute("SELECT * FROM page_clips WHERE document_id = ? ORDER BY page_index", (document,)).fetchall()
        session = conn.execute("SELECT exam_type, created_at FROM exam_sessions WHERE document_id = ? ORDER BY id LIMIT 1",
                               (document,)).fetchone()
    finally:
        conn.close()
    if described is None or not pages:
        raise SourceError(f"document {document} has no pages in {database}")
    images = Path(source) / "images"
    booklet = {"title": described["title"], "capture_device": described["capture_device"],
               "exam_type": session["exam_type"] if session else "written",
               "session_made": _epoch(session["created_at"]) if session else None, "pages": [], "clips": []}
    for row in pages:
        index = row["page_index"]
        provenance = json.loads(row["capture_metadata_json"] or "{}").get("capture_provenance")
        # The path is the source server's own (the phone's, another PC's): only its last part means anything here.
        stored = images / re.split(r"[\\/]", row["image_path"])[-1] if row["image_path"] else None
        frame = next((candidate for candidate in sorted(images.glob(f"{document}_{index}_*.jpg"))
                      if provenance and _sha256(candidate) == provenance.get("jpeg_sha256")), None)
        if frame is None and (stored is None or not stored.is_file()):
            raise SourceError(f"page {index + 1} has neither its frame nor its image in {images}")
        booklet["pages"].append({
            "index": index, "arrived": _epoch(row["created_at"]), "captured_at_ms": row["captured_at_ms"] or 0,
            "provenance": provenance, "frame": frame or stored,
            "kind": FIRST_FRAME if frame else STAND_IN_FRAME if provenance else STAND_IN_IMAGE})
    for row in clips:
        path = Path(source) / "page-clips" / str(document) / str(row["page_index"]) / f"{row['sha256']}.mp4"
        settled = row["status"] in ("done", "failed") and row["updated_at"] is not None
        booklet["clips"].append({
            "index": row["page_index"], "capture_id": row["capture_id"], "sha256": row["sha256"],
            "record": row["record_json"], "path": path if path.is_file() else None, "bytes": row["bytes"],
            "arrived": _epoch(row["created_at"]),
            "source": {"status": row["status"], "used": row["used"], "total": row["total"],
                       "gather_s": round(row["updated_at"] - row["created_at"], 1) if settled else None}})
    return booklet


def timeline(booklet: dict, pace: str) -> list[tuple[float, str, dict]]:
    """(seconds after the first request, "page" or "clip", the entry) in the order the requests go out.

    A clip whose file is gone is not in it. At equal times a page goes first, as the glasses send every waiting page
    before a clip, so a clip never stands before its own page.
    """
    events = [(page["arrived"], 0, page["index"], "page", page) for page in booklet["pages"]]
    events += [(clip["arrived"], 1, clip["index"], "clip", clip) for clip in booklet["clips"] if clip["path"]]
    if pace in ("recorded", "fast"):
        events.sort(key=lambda event: event[:3])
        start = events[0][0]
        return [(0.0 if pace == "fast" else at - start, kind, entry) for at, _, _, kind, entry in events]
    events.sort(key=lambda event: (event[2], event[1]))
    return [(index * float(pace), kind, entry) for _, _, index, kind, entry in events]


# ---- the target ----------------------------------------------------------------------------------------------------

def multipart(parts: list[tuple]) -> tuple[dict, object]:
    """A multipart/form-data body with its parts in the order given, as (headers, an iterable of bytes).

    A part is (name, text) or (name, file name, content type, bytes or Path). A Path is read a megabyte at a time, so a
    clip of a hundred megabytes is never held whole.
    """
    boundary = uuid.uuid4().hex
    pieces: list[bytes | Path] = []
    for part in parts:
        if len(part) == 2:
            pieces.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{part[0]}"\r\n\r\n{part[1]}\r\n'.encode())
        else:
            name, filename, kind, content = part
            pieces += [(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                        f"Content-Type: {kind}\r\n\r\n").encode(), content, b"\r\n"]
    pieces.append(f"--{boundary}--\r\n".encode())
    length = sum(piece.stat().st_size if isinstance(piece, Path) else len(piece) for piece in pieces)

    def body():
        for piece in pieces:
            if isinstance(piece, Path):
                with piece.open("rb") as source:
                    while block := source.read(1 << 20):
                        yield block
            else:
                yield piece

    return {"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(length)}, body()


def http_sender(server: str, key: str):
    """`send(method, path, headers, body, timeout) -> (status, bytes)` over HTTP, straight to the server: whatever proxy
    the environment names is not used."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = server.rstrip("/")

    def send(method, path, headers, body, timeout):
        request = urllib.request.Request(base + path, data=body, method=method, headers={
            **headers, "Accept": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})})
        try:
            with opener.open(request, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.read()

    return send


def _said(answer: dict) -> str | None:
    """The server's own word for a refusal, kept only while it is plain ASCII: nothing of a paper rides in the report."""
    detail = answer.get("detail")
    return detail[:160] if isinstance(detail, str) and detail.isascii() else None


class Server:
    """The target, behind a `send` as http_sender makes one (the tests hand in the app's own client)."""

    def __init__(self, send):
        self._send = send

    def call(self, method: str, path: str, *, payload: dict | None = None, parts: list | None = None,
             timeout: float = CALL_S) -> tuple[int, dict]:
        """(HTTP status, the JSON object answered). Status 0: no answer came, and "detail" names the error's type."""
        headers, body = {}, b"" if method == "POST" else None
        if payload is not None:
            headers, body = {"Content-Type": "application/json"}, json.dumps(payload).encode()
        elif parts is not None:
            headers, body = multipart(parts)
        try:
            status, raw = self._send(method, path, headers, body, timeout)
        except (OSError, http.client.HTTPException) as error:
            return 0, {"detail": type(error).__name__}
        try:
            answer = json.loads(raw)
        except ValueError:
            answer = None
        return status, answer if isinstance(answer, dict) else {}


class ClipWatch:
    """Asks the server twice a second how far each clip has come, and keeps when each was first seen done or failed."""

    def __init__(self, server: Server, document: int):
        self._server, self._document = server, document
        self.rows: dict[int, dict] = {}  # page index -> the clip's row as last seen
        self.settled: dict[int, float] = {}  # page index -> time.monotonic() when it was first seen done or failed
        self._over = threading.Event()
        self._thread = threading.Thread(target=self._run, name="clip-watch", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        while not self._over.wait(POLL_S):
            self.look()

    def look(self) -> None:
        status, answer = self._server.call("GET", f"/v1/documents/{self._document}/clips", timeout=10)
        now = time.monotonic()
        for row in answer.get("clips", []) if status == 200 else []:
            self.rows[row["page_index"]] = row
            if row["status"] in ("done", "failed"):
                self.settled.setdefault(row["page_index"], now)

    def stop(self) -> None:
        """Ends the asking; one last look is taken, so the rows are those of this moment."""
        if not self._over.is_set():
            self._over.set()
            self._thread.join()
            self.look()


# ---- the replay ----------------------------------------------------------------------------------------------------

def _frame(page: dict) -> tuple[bytes, dict | None, int]:
    """(the image to send as the page, the capture record to send with it, image_rotation)."""
    provenance = page["provenance"]
    if page["kind"] == STAND_IN_FRAME:
        from PIL import Image  # noqa: PLC0415 - only this stand-in needs Pillow

        # The server turned the frame clockwise by rotation_degrees to make the page upright; a gathered page is also
        # twice the frame's size. Back to how the sensor saw it, at the frame's size, under the recorded capture.
        with Image.open(page["frame"]) as upright:
            lying = upright.convert("RGB").rotate(provenance["rotation_degrees"], expand=True).resize(
                (provenance["width"], provenance["height"]))
        encoded = io.BytesIO()
        lying.save(encoded, "JPEG", quality=95)
        raw = encoded.getvalue()
        return raw, {**provenance, "jpeg_sha256": hashlib.sha256(raw).hexdigest()}, provenance["rotation_degrees"]
    return page["frame"].read_bytes(), provenance, provenance["rotation_degrees"] if provenance else 0


def _await_answers(server: Server, session: int, since: float, timeout: float) -> dict:
    """Ask for the answer bundle once a second until no item is pending, a call is refused for good or the time is over.

    A 409 says the answers are still being made, and a call without an answer is asked again. Only counts leave here.
    """
    found = {"http": None, "detail": None, "first_s": None, "complete_s": None, "items": {}, "answered": 0,
             "pages_left_as_one_frame": [], "revision": None}
    deadline = time.monotonic() + timeout
    while True:
        status, bundle = server.call("GET", f"/v1/exam-sessions/{session}/answer-bundle")
        found["http"], found["detail"] = status, None if status == 200 else _said(bundle)
        if status == 200:
            items = bundle.get("items") or []
            found["items"] = dict(Counter(str(item.get("status")) for item in items))
            # The server's own notices stand in the group "pages"; "page3" is a recorded page that stayed one frame.
            found["pages_left_as_one_frame"] = sorted(
                int(named[1]) for item in items if (named := re.fullmatch(r"page(\d+)", str(item.get("question_id")))))
            found["answered"] = sum(1 for item in items
                                    if item.get("group_id") != "pages" and item.get("status") in ("ready", "needs_review"))
            now = round(time.monotonic() - since, 1)
            if found["answered"] and found["first_s"] is None:
                found["first_s"] = now
            if items and not found["items"].get("pending"):
                found["complete_s"], found["revision"] = now, bundle.get("revision")
                return found
        elif status not in (0, 409):
            return found
        if time.monotonic() >= deadline:
            return found
        time.sleep(1.0)


def _target_facts(target_data: Path, document: int, session: int | None) -> tuple[dict[int, float], dict[str, int]]:
    """What only the target's own database says, read as the source is: each settled clip's seconds from arrival to
    gathered (page index -> seconds), and the failure codes of the session's questions that have no answer."""
    conn = sqlite3.connect((target_data / "docscan.db").resolve().as_uri() + "?mode=ro", uri=True)
    try:
        seconds = {index: round(settled - arrived, 1) for index, arrived, settled in conn.execute(
            "SELECT page_index, created_at, updated_at FROM page_clips WHERE document_id = ? AND status IN ('done', 'failed')",
            (document,))}
        codes: Counter = Counter()
        for (structure,) in conn.execute(
                "SELECT structure_json FROM questions q WHERE session_id = ? AND NOT EXISTS "
                "(SELECT 1 FROM solutions s WHERE s.question_id = q.id)", (session,)):
            try:
                codes[json.loads(structure or "{}")["solve_failure"]["code"]] += 1
            except (ValueError, KeyError, TypeError):
                pass
    finally:
        conn.close()
    return seconds, dict(codes)


def replay(booklet: dict, server: Server, *, pace: str = "recorded", timeout: float = 1800.0,
           gather_limit: float = GATHER_WAIT_S, new_capture_ids: bool = False, real_solver: bool = False,
           target_data: Path | None = None, say=functools.partial(print, flush=True)) -> dict:
    """Send the booklet as the glasses did and return the report (the module's text says what is in it).

    Each line is said as it happens (flushed: a replay at the recorded pace runs for as long as the capture did).
    """
    status, settings = server.call("GET", "/v1/settings", timeout=30)
    solver = (settings.get("providers") or {}).get("solver") or {}
    if status != 200:
        raise Refused(f"the target does not answer /v1/settings (HTTP {status}, {_said(settings)})")
    if not real_solver and (solver.get("name"), solver.get("ready")) != ("recorded", True):
        raise Refused(f"the target answers with the solver {solver.get('name')!r} (ready: {solver.get('ready')}), not the "
                      "armed stand-in: a replay would be answered at the operator's cost. --real-solver sends it all the same")
    arrivals = [entry["arrived"] for entry in booklet["pages"] + booklet["clips"]]
    report = {
        "pace": pace,
        "source": {"pages": len(booklet["pages"]), "clips": len(booklet["clips"]),
                   "clip_files": sum(1 for clip in booklet["clips"] if clip["path"]),
                   "arrivals_span_s": round(max(arrivals) - min(arrivals), 1),
                   "session_made_after_last_arrival_s": (round(booklet["session_made"] - max(arrivals), 1)
                                                         if booklet["session_made"] else None)},
        "target": {"app_version": (settings.get("versions") or {}).get("app_version"), "solver": solver.get("name"),
                   "document_id": None, "session_id": None},
        "pages": [], "clips": [], "finalize": None, "answers": None, "stopped_at": None, "notes": []}
    if booklet["exam_type"] != "written":
        report["notes"].append(f"the source's session is {booklet['exam_type']}: sent as written, without its recording")
    # A recorded page whose clip cannot be sent goes out as the one frame it is, and is counted as not gathered.
    clips = {clip["index"]: clip for clip in booklet["clips"]}
    for page in booklet["pages"]:
        clip = clips.get(page["index"])
        if (page["provenance"] or {}).get("source_kind") == "clip_frame" and not (clip and clip["path"]):
            report["clips"].append({"page": page["index"] + 1, "bytes": clip and clip["bytes"], "source": clip and clip["source"],
                                    "planned_s": None, "sent_s": None, "upload_s": None, "http": None,
                                    "status": NOT_SENT if clip else NO_CLIP})
    renamed: dict[str, str] = {}

    def capture_id(recorded: str) -> str:
        return renamed.setdefault(recorded, str(uuid.uuid4())) if new_capture_ids else recorded

    device, generation, sequence = "replay-booklet", time.time_ns() // 1_000_000, itertools.count(1)
    session = None

    def state(phase: str, display: str | None = None, ack: int | None = None) -> None:
        # What the glasses post as they go (DocScanGlassActivity.notifyPhase): Work, and a restart, look for it.
        taken, _ = server.call("POST", "/v1/glasses/state", timeout=10, payload={
            "device_id": device, "session_id": session, "generation": generation, "sequence": next(sequence),
            "phase": phase, "display_request": display, "entry_request": None, "ack_answer_revision": ack})
        if taken != 200 and not any(note.startswith("glasses state") for note in report["notes"]):
            report["notes"].append(f"glasses state not taken (HTTP {taken}): the session has no registered wearer")

    def shown(seconds: float) -> float:
        return round(seconds, 1)

    watch = None
    arrived: dict[int, float] = {}  # page index -> when the server had taken its clip
    try:
        state("capturing", "wake")
        status, made = server.call("POST", "/v1/documents", payload={
            "title": booklet["title"], "capture_device": booklet["capture_device"], "client_version": "replay_booklet",
            "sdk_hint": "camera2/no-cxr"})
        if status != 201:
            raise _Stopped("document", status, made)
        document = report["target"]["document_id"] = made["document_id"]
        watch = ClipWatch(server, document)
        watch.start()
        start = time.monotonic()
        for planned, kind, entry in timeline(booklet, pace):
            if (ahead := start + planned - time.monotonic()) > 0:
                time.sleep(ahead)
            index, sent = entry["index"], time.monotonic()
            if kind == "page":
                raw, provenance, rotation = _frame(entry)
                if provenance:
                    provenance = {**provenance, "capture_id": capture_id(provenance["capture_id"])}
                status, answer = server.call("POST", f"/v1/documents/{document}/pages", parts=[
                    ("page_index", index), ("image_rotation", rotation), ("captured_at_ms", entry["captured_at_ms"]),
                    ("image", f"page-{index + 1}.jpg", "image/jpeg", raw),
                    *([("capture_provenance", json.dumps(provenance, separators=(",", ":")))] if provenance else [])])
                row = {"page": index + 1, "frame": entry["kind"], "bytes": len(raw)}
                # The glasses take a page as sent only with their capture record echoed (DocScanApi.uploadPage).
                passed = status == 201 and (provenance is None or answer.get("capture_provenance") == provenance)
            else:
                status, answer = server.call("POST", f"/v1/documents/{document}/pages/{index}/clip", timeout=CLIP_S, parts=[
                    ("capture_id", capture_id(entry["capture_id"])), ("sha256", entry["sha256"]),
                    ("record", entry["record"].replace(entry["capture_id"], capture_id(entry["capture_id"]))),
                    ("clip", f"page-{index + 1}.mp4", "video/mp4", entry["path"])])
                row = {"page": index + 1, "bytes": entry["bytes"], "source": entry["source"]}
                passed = status in (200, 201, *CLIP_LET_GO)
                if status in (200, 201):
                    arrived[index] = time.monotonic()
            row.update(planned_s=shown(planned), sent_s=shown(sent - start), upload_s=shown(time.monotonic() - sent), http=status)
            report[kind + "s"].append(row)
            say(f"{kind} {index + 1}: sent +{row['sent_s']} s (planned +{row['planned_s']}), {row['bytes']} bytes in "
                f"{row['upload_s']} s, HTTP {status}" + (f", {entry['kind']}" if kind == "page" and entry["kind"] != FIRST_FRAME else ""))
            if not passed:
                raise _Stopped(f"{kind} {index + 1}", status, answer)

        # The glasses finalize as soon as the capture is ended and nothing is unsent. No record keeps when it was
        # ended, so this is the earliest they can: right behind the last upload.
        called = time.monotonic()
        status, answer = server.call("POST", f"/v1/documents/{document}/finalize")
        returned = time.monotonic()
        watch.stop()
        waited_for = [index for index in arrived if watch.settled.get(index, returned) > called]
        left = [index for index in arrived if watch.rows.get(index, {}).get("status") not in ("done", "failed")]
        wait = 0.0 if not waited_for else returned - called if left else min(
            max(watch.settled[index] for index in waited_for), returned) - called
        report["finalize"] = {"sent_s": shown(called - start), "call_s": shown(returned - called), "http": status,
                              "gather_wait_s": shown(wait), "limit_s": gather_limit, "clips_waited_for": len(waited_for),
                              "clips_left": len(left)}
        say(f"finalize: sent +{report['finalize']['sent_s']} s, HTTP {status} after {report['finalize']['call_s']} s; "
            f"waited {report['finalize']['gather_wait_s']} s for {len(waited_for)} clip(s), {len(left)} left")
        if status != 200:
            raise _Stopped("finalize", status, answer)

        status, answer = server.call("POST", "/v1/exam-sessions", payload={
            "mode": "study", "document_id": document, "exam_type": "written", "answer_format": "mark"})
        if status != 201:
            raise _Stopped("session", status, answer)
        session = report["target"]["session_id"] = answer["session_id"]
        state("analyzing")
        status, answer = server.call("POST", f"/v1/exam-sessions/{session}/finalize-reading?solve=background", timeout=READING_S)
        if status != 200:
            raise _Stopped("finalize-reading", status, answer)
        answers = report["answers"] = _await_answers(server, session, called, timeout)
        if answers["complete_s"] is not None:
            state("reading", "wake", answers["revision"])
    except _Stopped as stopped:
        report["stopped_at"] = stopped.at
        if stopped.at["http"] == 409 and stopped.at["step"].startswith("page"):
            report["notes"].append("a target that already holds this booklet refuses its capture IDs: --new-capture-ids")
    finally:
        if watch is not None:
            watch.stop()
        state("closed")  # the replay's wearer is gone: a restart of the target does not take its session up for them
    # Each clip as the server held it when the booklet went on (the watch's last look was right behind finalize).
    for row in report["clips"]:
        index = row["page"] - 1
        seen = watch.rows.get(index, {}) if index in arrived else {"status": row.get("status", "refused")}
        row.update(status=seen.get("status"), reason=seen.get("reason"), used=seen.get("used"), total=seen.get("total"),
                   gather_s=shown(watch.settled[index] - arrived[index]) if index in arrived and index in watch.settled else None)
    report["clips"].sort(key=lambda row: row["page"])
    if target_data is not None and report["target"]["document_id"] is not None:
        seconds, codes = _target_facts(Path(target_data), report["target"]["document_id"], session)
        for row in report["clips"]:
            row["gather_s"] = seconds.get(row["page"] - 1, row["gather_s"])
        if report["answers"] is not None:
            report["answers"]["failure_codes"] = codes
    report["checks"] = _judge(report)
    report["exit_code"] = int(any(check["result"] == "FAIL" for check in report["checks"]))
    _show(report, say)
    return report


def _judge(report: dict) -> list[dict]:
    """The four named checks, each PASS or FAIL with what it saw."""
    finalize, answers, stopped = report["finalize"], report["answers"], report["stopped_at"]
    most = round((1 - WAIT_MARGIN) * finalize["limit_s"], 1) if finalize else None
    halt = f"the replay stopped at {stopped['step']} (HTTP {stopped['http']})" if stopped else None
    not_done = [f"page {row['page']}: {row.get('status')}" + (f" ({row['reason']})" if row.get("reason") else "")
                for row in report["clips"] if row.get("status") != "done"]
    named = answers["pages_left_as_one_frame"] if answers else []
    items = answers["items"] if answers else {}
    verdicts = [
        (finalize is not None and not not_done,
         halt if finalize is None else "; ".join(not_done) or f"all {len(report['clips'])} recorded pages"),
        (finalize is not None and finalize["http"] == 200 and finalize["gather_wait_s"] <= most,
         halt if finalize is None else f"waited {finalize['gather_wait_s']} s of the limit's {finalize['limit_s']} s "
                                       f"(passes up to {most} s), HTTP {finalize['http']}"),
        (answers is not None and answers["complete_s"] is not None and answers["answered"] > 0
         and not items.get("failed") and not answers.get("failure_codes"),
         halt if answers is None else f"{answers['answered']} answered, items by status {items}, last HTTP {answers['http']}"
         + (f" ({answers['detail']})" if answers["detail"] else "")
         + (f", failure codes {answers['failure_codes']}" if answers.get("failure_codes") else "")),
        (finalize is not None and not not_done and not named,
         halt if finalize is None else f"named in the answers: {named or 'none'}; clips not gathered: {len(not_done)}"),
    ]
    return [{"name": name, "result": "PASS" if passed else "FAIL", "detail": detail}
            for name, (passed, detail) in zip(CHECKS, verdicts, strict=True)]


def _show(report: dict, say) -> None:
    for clip in report["clips"]:
        source = clip["source"]
        say(f"clip {clip['page']}: {clip.get('status')}" + (f" ({clip['reason']})" if clip.get("reason") else "")
            + f", {clip.get('used')} of {clip.get('total')} frames, {clip.get('gather_s')} s from arrival to gathered"
            + (f" (source: {source['status']}, {source['used']} of {source['total']}, {source['gather_s']} s)" if source else ""))
    answers = report["answers"]
    if answers:
        say(f"answers: first {answers['first_s']} s and all {answers['complete_s']} s after finalize was sent; "
            f"items by status {answers['items']}; pages named as left one frame: {answers['pages_left_as_one_frame'] or 'none'}")
    for note in report["notes"]:
        say(f"note: {note}")
    for check in report["checks"]:
        say(f"{check['result']}  {check['name']}: {check['detail']}")
    say(f"exit {report['exit_code']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Play a recorded booklet to a running server as the glasses sent it.")
    parser.add_argument("--source-data", type=Path, required=True, help="a server data folder (docscan.db, images, page-clips); only read")
    parser.add_argument("--document", type=int, required=True, help="the document's id in the source")
    parser.add_argument("--server", required=True, help="the target, http://host:port")
    parser.add_argument("--key", default="", help="the target's API key, or @file holding it")
    parser.add_argument("--pace", default="recorded", help="recorded (default), fast, or seconds a page")
    parser.add_argument("--timeout", type=float, default=1800.0, help="seconds to wait for the answers (1800)")
    parser.add_argument("--report", type=Path, help="write the report here as JSON")
    parser.add_argument("--target-data", type=Path, help="the target's data folder, only read: exact clip times, failure codes")
    parser.add_argument("--gather-limit", type=float, default=GATHER_WAIT_S, help="the target's ROKID_GATHER_WAIT_S (200)")
    parser.add_argument("--new-capture-ids", action="store_true", help="for a target that already holds this booklet")
    parser.add_argument("--real-solver", action="store_true", help="send although the target's solver is not the stand-in")
    asked = parser.parse_args(argv)
    if asked.pace not in ("recorded", "fast"):
        try:
            if not float(asked.pace) >= 0:
                raise ValueError
        except ValueError:
            parser.error("--pace is recorded, fast, or a number of seconds a page")
    key = Path(asked.key[1:]).read_text(encoding="utf-8").strip() if asked.key.startswith("@") else asked.key
    try:
        booklet = load_booklet(asked.source_data, asked.document)
        print(f"replay_booklet: document {asked.document} of {asked.source_data} ({len(booklet['pages'])} pages, "
              f"{len(booklet['clips'])} clips) to {asked.server}, pace {asked.pace}", flush=True)
        report = replay(booklet, Server(http_sender(asked.server, key)), pace=asked.pace, timeout=asked.timeout,
                        gather_limit=asked.gather_limit, new_capture_ids=asked.new_capture_ids, real_solver=asked.real_solver,
                        target_data=asked.target_data)
    except (SourceError, Refused) as error:
        print(f"replay_booklet: {error}", file=sys.stderr)
        return 2
    if asked.report:
        asked.report.parent.mkdir(parents=True, exist_ok=True)
        asked.report.write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
