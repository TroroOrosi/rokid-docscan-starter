"""The clip a recorded page was cut from, kept beside the page until it is gathered into the page's image.

At the venue's light one frame cannot be read; a few seconds of frames added together can (docs/hardware-measurements.md,
M-24 to M-29). The glasses therefore send a page twice: first one frame of its clip through the ordinary page upload
(source kind ``clip_frame``), so that the page exists whatever happens next, then the clip and the record written beside
it. This module keeps the clip and says how far it has come: ``stored``, ``gathering``, ``done``, or ``failed`` with its
reason. app/page_gather.py does the gathering. Design: docs/superpowers/specs/2026-11-15-gathered-capture-design.md, 6.5-6.7.

One clip a page. A page taken again gets another capture ID: the earlier clip is refused from then on (409), and the
new clip replaces the row and removes the earlier file.

A clip's row stays for good. Its file goes once nothing reads it any more (app/retention.py: a gathered page's clip
after three days, a failed one after a week), and the row then says so in ``file_removed_at``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from contextlib import closing
from pathlib import Path

from fastapi import HTTPException

from . import config, db
from .capture_video_upload import CHUNK_BYTES, _sync_directory

MAX_BYTES = 192 * 1024 * 1024  # one clip; ten seconds at the 95 Mbit/s the glasses ask for are about 119 MB
MAX_RECORD_BYTES = 512 * 1024
STALE = "gather error: the page was taken again or its booklet went on"  # the reason of a clip no page can take any more
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def provenance_of(metadata_json: str | None) -> dict:
    """The capture a page's image came from, as stored with the page; {} for a page that has none."""
    try:
        return json.loads(metadata_json or "{}").get("capture_provenance") or {}
    except (ValueError, AttributeError):
        return {}


def clip_path(document_id: int, page_index: int, sha256: str) -> Path:
    return config.DATA_DIR / "page-clips" / str(document_id) / str(page_index) / f"{sha256}.mp4"


def _refuse(status: int, detail: str):
    raise HTTPException(status_code=status, detail=detail)


_PAGE = ("SELECT p.id, p.image_path, p.capture_metadata_json, d.status FROM pages p JOIN documents d ON d.id = p.document_id "
         "WHERE p.document_id = ? AND p.page_index = ?")


def open_capture(conn, document_id: int, page_index: int) -> tuple[dict, object]:
    """(the capture the page holds now, the page's row) while its booklet still takes pages; ({}, None) otherwise.

    A clip of any other capture is stale: the page was taken again, or the booklet went on without it.
    """
    page = conn.execute(_PAGE, (document_id, page_index)).fetchone()
    if page is None or page["status"] != "open":
        return {}, None
    return provenance_of(page["capture_metadata_json"]), page


def _admit(conn, document_id: int, page_index: int, capture_id: str) -> None:
    """A clip belongs to the capture its page holds now, in a booklet that still takes pages."""
    page = conn.execute(_PAGE, (document_id, page_index)).fetchone()
    if page is None:
        _refuse(404, "page not found")
    if page["status"] != "open":
        _refuse(409, f"document {document_id} is finalized (status={page['status']}); its pages take no clip")
    if provenance_of(page["capture_metadata_json"]).get("capture_id") != capture_id:
        _refuse(409, "this page holds another capture than the clip's")


def _row(conn, document_id: int, page_index: int):
    return conn.execute("SELECT * FROM page_clips WHERE document_id = ? AND page_index = ?", (document_id, page_index)).fetchone()


def store_clip(document_id: int, page_index: int, capture_id: str, sha256: str, record_text: str, stream) -> dict:
    """Keep one page's clip and its record: {"status", "sha256", "bytes", "created"}.

    ``stream`` is a binary file object, read to its end. ``created`` is False for the clip this page already has: its
    present status is returned and nothing is written. Raises HTTPException: 404 no such page; 409 the booklet takes
    no more pages, or the page holds another capture (the clip of a page taken again); 400 the bytes are not the clip
    that was named, are not an MP4, or the record is not a JSON object; 413 over MAX_BYTES.
    """
    if _SHA256.match(sha256) is None:
        _refuse(400, "sha256 must be 64 lowercase hexadecimal digits")
    try:
        if len(record_text.encode("utf-8")) > MAX_RECORD_BYTES or type(json.loads(record_text)) is not dict:
            raise ValueError("not a record")
    except (ValueError, RecursionError):
        _refuse(400, "record must be a JSON object of at most 512 KiB")
    target = clip_path(document_id, page_index, sha256)
    arriving: Path | None = None

    def kept(row) -> bool:
        return row is not None and (row["sha256"], row["capture_id"]) == (sha256, capture_id)

    conn = db.connect()
    try:
        _admit(conn, document_id, page_index, capture_id)
        if not kept(_row(conn, document_id, page_index)):
            # Beside its final name: taking that name is then one rename inside one directory.
            target.parent.mkdir(parents=True, exist_ok=True)
            arriving = target.with_name(f"{uuid.uuid4().hex}.part")
        digest, count, head = hashlib.sha256(), 0, b""
        with open(arriving or os.devnull, "xb" if arriving else "wb") as saved:  # the clip already kept is only checked
            while block := stream.read(CHUNK_BYTES):
                count += len(block)
                if count > MAX_BYTES:
                    _refuse(413, f"clip too large (max {MAX_BYTES} bytes)")
                digest.update(block)
                head += block[:8 - len(head)]
                saved.write(block)
            saved.flush()
            if arriving:
                os.fsync(saved.fileno())
        if digest.hexdigest() != sha256:
            _refuse(400, "the clip's bytes do not match its sha256")
        if head[4:8] != b"ftyp":  # an MP4 signature only: nothing about its codec or frames is checked here
            _refuse(400, "the clip is not an MP4 file")
        # The page may have been taken again, or the booklet finalized, while the clip came in.
        conn.execute("BEGIN IMMEDIATE")
        _admit(conn, document_id, page_index, capture_id)
        known = _row(conn, document_id, page_index)
        if kept(known):
            return {"status": known["status"], "sha256": sha256, "bytes": known["bytes"], "created": False}
        if arriving is None:
            _refuse(409, "the page's clip changed while this one came in")
        # Never over a file that is there: the name is the content's hash, so one that is there holds these bytes (an
        # upload that stopped before its row was written left it). The write lock makes the look and the rename one step
        # among uploads. A plain rename, not a hard link: whether the phone's storage allows links is not known.
        if not target.exists():
            os.replace(arriving, target)
            _sync_directory(target.parent)
        now = time.time()
        conn.execute("INSERT OR REPLACE INTO page_clips (document_id, page_index, capture_id, sha256, bytes, record_json, "
                     "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'stored', ?, ?)",
                     (document_id, page_index, capture_id, sha256, count, record_text, now, now))
        conn.commit()
        if known is not None and known["sha256"] != sha256:
            # A reader that still holds the earlier file (Windows) keeps it; on the phone the name goes at once.
            try:
                clip_path(document_id, page_index, known["sha256"]).unlink()
            except OSError:
                pass
        return {"status": "stored", "sha256": sha256, "bytes": count, "created": True}
    finally:
        conn.close()
        if arriving is not None:
            arriving.unlink(missing_ok=True)


def pending(document_id: int) -> int:
    """Clips of this booklet that are still to be gathered or are being gathered."""
    with closing(db.connect()) as conn:
        return conn.execute("SELECT COUNT(*) FROM page_clips WHERE document_id = ? AND status IN ('stored', 'gathering')",
                            (document_id,)).fetchone()[0]


def rows(document_id: int) -> list[dict]:
    with closing(db.connect()) as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM page_clips WHERE document_id = ? ORDER BY page_index", (document_id,))]


def claim() -> dict | None:
    """The next stored clip whose page can still take it, marked as being gathered; None when none waits.

    The newest booklet first (the one being taken; an earlier one left open does not stand before it), the oldest clip
    within it. Every stored clip whose page can no longer take it (``open_capture``) is given up in this same look,
    with STALE as its reason and without being gathered: a finalize call sent again then has nothing to wait for.
    """
    with closing(db.connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        claimed, now = None, time.time()
        for row in conn.execute("SELECT * FROM page_clips WHERE status = 'stored' "
                                "ORDER BY document_id DESC, created_at, rowid").fetchall():
            usable = open_capture(conn, row["document_id"], row["page_index"])[0].get("capture_id") == row["capture_id"]
            if usable and claimed is not None:
                continue  # waits for its turn
            conn.execute("UPDATE page_clips SET status = ?, reason = ?, attempts = attempts + ?, updated_at = ? "
                         "WHERE document_id = ? AND page_index = ?",
                         ("gathering" if usable else "failed", None if usable else STALE, int(usable), now,
                          row["document_id"], row["page_index"]))
            if usable:
                claimed = {**dict(row), "status": "gathering", "attempts": row["attempts"] + 1}
        conn.commit()
        return claimed


def _settle(document_id: int, page_index: int, sha256: str, status: str, reason: str | None = None,
            used: int | None = None, total: int | None = None, level: float | None = None) -> None:
    """Only the clip that was worked on: after a retake another clip holds the row, and that one is left as it is."""
    with closing(db.connect()) as conn, conn:
        conn.execute("UPDATE page_clips SET status = ?, reason = ?, used = ?, total = ?, level = ?, updated_at = ? "
                     "WHERE document_id = ? AND page_index = ? AND sha256 = ?",
                     (status, reason, used, total, level, time.time(), document_id, page_index, sha256))


def finish(document_id: int, page_index: int, sha256: str, *, used: int, total: int, level: float) -> None:
    _settle(document_id, page_index, sha256, "done", used=used, total=total, level=level)


def fail(document_id: int, page_index: int, sha256: str, reason: str) -> None:
    _settle(document_id, page_index, sha256, "failed", reason=reason[:500])


def requeue_interrupted() -> None:
    """At start: a clip that was being gathered when the server stopped is gathered once more.

    One the server stopped on twice is given up instead: it may be what stops the server (memory, with three gathers
    running), and taken up at every start it would stop it every time, with nobody at the phone.
    """
    with closing(db.connect()) as conn, conn:
        now = time.time()
        conn.execute("UPDATE page_clips SET status = 'failed', reason = 'interrupted twice', updated_at = ? "
                     "WHERE status = 'gathering' AND attempts >= 2", (now,))
        conn.execute("UPDATE page_clips SET status = 'stored', updated_at = ? WHERE status = 'gathering'", (now,))
