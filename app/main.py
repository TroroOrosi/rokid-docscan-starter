"""Rokid DocScan — FastAPI server.

Server-side. Runs locally with SQLite + local filesystem, offline by default
(no Rokid hardware and no external credentials required). Real cloud models
(OpenAI GPT / Google Gemini / Anthropic Claude) plug in via the provider
registries; see docs/implementation-notes.md and docs/cxr-l-integration.md.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

from . import config, db
from .analyzers import get_analyzer
from .config import IMAGE_DIR, ensure_dirs
from .explainer import ExplainRequest, ExplainResult
from .explainers import get_explainer, list_explainers
from .extractors import detect_media, get_extractor
from .glasses_view import (
    CAPTURE_CONTRACT,
    EXPLAIN_STAGES,
    OPERATION_CONTRACT,
    READING_OPERATIONS,
    RENDER_CONTRACT,
    REVIEW_OPERATIONS,
    STAGES,
    build_capture_ack,
    build_explain_view,
    build_glasses_view,
    build_input_contract,
    build_locked_view,
    build_page_nav_ack,
    build_reading_done_ack,
    build_review_view,
    build_scan_ack,
)
from .hud import build_hud
from .layout import parse_layout, primary_question, segment_problems
from .llm import clamp01
from .matching import (
    Candidate,
    normalize_ocr_text,
    ocr_md5,
    phash_hex,
    rank,
    score_candidate,
)
from .matching import verdict as match_verdict
from .overlay import build_overlay
from .retrieval import retrieve_context
from .solvers import Question
from .solvers.registry import solve_with_fallback
from .subjects import detect_subject
from .version import APP_VERSION, HUD_CONTRACT_VERSION, version_info


def _extract_media(ocr_text: str | None, image_path: str | None) -> list[dict]:
    """Run the active media extractor over any figure/table/graph/formula cues."""
    kinds = detect_media(ocr_text)
    if not kinds:
        return []
    extractor = get_extractor()
    items: list[dict] = []
    for kind in kinds:
        res = extractor.extract(kind=kind, ocr_text=ocr_text, image_path=image_path)
        items.append(
            {"kind": res.kind, "content": res.content, "confidence": res.confidence}
        )
    return items


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    db.init_db()
    yield


app = FastAPI(title="Rokid DocScan", version=APP_VERSION, lifespan=lifespan)


# --- optional bearer auth (off unless ROKID_API_KEY is set) ------------------

@app.middleware("http")
async def _auth_middleware(request: Request, call_next):
    """Require `Authorization: Bearer <ROKID_API_KEY>` when a key is configured.

    No key configured -> no auth (default; local dev + CI unaffected). Discovery
    endpoints (config.AUTH_EXEMPT_PATHS) stay open so a client can negotiate
    contracts before authenticating.
    """
    # Normalize a trailing slash so /v1/settings/ is as exempt as /v1/settings
    # (a client appending a slash to a discovery URL must not be locked out
    # before it can negotiate contracts).
    path = request.url.path.rstrip("/") or "/"
    if config.API_KEY and path not in config.AUTH_EXEMPT_PATHS:
        # Constant-time compare over bytes: str-compare leaks length/prefix
        # timing, and compare_digest rejects non-ASCII str inputs.
        expected = f"Bearer {config.API_KEY}".encode("utf-8")
        provided = request.headers.get("authorization", "").encode("utf-8")
        if not hmac.compare_digest(provided, expected):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


# --- request/response models ------------------------------------------------

class CreateDocument(BaseModel):
    title: str
    capture_device: str | None = None
    client_version: str | None = None
    sdk_hint: str | None = None


# --- helpers ----------------------------------------------------------------

_MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # generous for page photos / recordings
# The relay camera is 12 MP. Keep enough headroom for imported scans while
# bounding decoded memory independently of the compressed upload byte limit.
_MAX_IMAGE_PIXELS = 25_000_000
_SAFE_AUDIO_SUFFIXES = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpga",
    ".ogg",
    ".wav",
    ".webm",
}
_AUDIO_MIME_SUFFIXES = {
    "audio/aac": ".aac",
    "audio/flac": ".flac",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/webm": ".webm",
}


async def _read_upload_limited(upload: UploadFile) -> bytes:
    """Read an UploadFile with a hard size cap (memory-exhaustion guard)."""
    raw = await upload.read(_MAX_UPLOAD_BYTES + 1)
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="upload too large (max 15MB)")
    return raw


def _safe_audio_suffix(upload: UploadFile) -> str:
    """Keep user-supplied filenames out of persisted filesystem paths."""
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix in _SAFE_AUDIO_SUFFIXES:
        return suffix
    content_type = (upload.content_type or "").partition(";")[0].strip().lower()
    return _AUDIO_MIME_SUFFIXES.get(content_type, ".bin")


def _load_image(raw: bytes) -> Image.Image:
    img: Image.Image | None = None
    try:
        img = Image.open(io.BytesIO(raw))
        if img.width * img.height > _MAX_IMAGE_PIXELS:
            img.close()
            raise HTTPException(
                status_code=413,
                detail="image dimensions too large (max 25 megapixels)",
            )
        img.load()
        return img
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        if img is not None:
            img.close()
        raise HTTPException(status_code=400, detail="invalid image upload")


def _rotate_image_for_ocr(img: Image.Image, rotation: int) -> Image.Image:
    """Match the clockwise rotation ML Kit applies to the relay's raw JPEG."""
    transpose = {
        0: None,
        90: Image.Transpose.ROTATE_270,
        180: Image.Transpose.ROTATE_180,
        270: Image.Transpose.ROTATE_90,
    }[rotation]
    return img if transpose is None else img.transpose(transpose)


def _match_text(ocr_text: str | None, vision_text: str | None) -> str:
    """Combine body text and figure reading into one /match similarity string.

    Both signals matter: pages sharing identical printed text are told apart
    by their diagram readings (vision_text is a component, not a fallback).
    """
    parts = [t.strip() for t in (ocr_text, vision_text) if t and t.strip()]
    return normalize_ocr_text(" ".join(parts))


def _doc_or_404(conn, document_id: int):
    row = conn.execute(
        "SELECT * FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="document not found")
    return row


def _fallback_md5(omd5: str | None, raw: bytes) -> str:
    return omd5 if omd5 is not None else hashlib.md5(raw).hexdigest()


def _unlink_best_effort(path: str | Path | None) -> None:
    """Remove a superseded/rejected media file without masking the API result."""
    if not path:
        return
    try:
        Path(path).unlink()
    except OSError:
        pass


def _row_or_404(conn, table: str, row_id: int, detail: str):
    row = conn.execute(
        f"SELECT * FROM {table} WHERE id = ?", (row_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=detail)
    return row


def _page_material(ocr_text: str | None, vision_text: str | None) -> str:
    """Combine body transcription and a textual description of visual material.

    The phone normally supplies ``ocr_text``; an image-capable analyzer may
    correct it and add ``vision_text`` for figures, diagrams and tables.
    """
    parts: list[str] = []
    if ocr_text and ocr_text.strip():
        parts.append(ocr_text.strip())
    if vision_text and vision_text.strip():
        parts.append("【図・画像の読み取り】\n" + vision_text.strip())
    return "\n\n".join(parts)


def _require_dense_page_index_values(indexes: list[int]) -> int:
    expected = list(range(len(indexes)))
    if indexes != expected:
        missing = sorted(set(expected) - set(indexes))
        raise HTTPException(
            status_code=409,
            detail=(
                "page indexes must be contiguous from 0 before finalizing or "
                f"starting navigation (registered={indexes}, missing={missing}); "
                "review /scan-status and create a corrected document"
            ),
        )
    return len(indexes)


def _require_dense_page_indexes(conn, document_id: int) -> int:
    """Require the navigation invariant page_index == 0..N-1.

    Exam/explain navigation stores an integer cursor and performs exact page
    lookups, so a finalized document with a leading index or an internal gap
    would create a valid-looking session whose first/current page is 404.
    """
    indexes = [
        r["page_index"]
        for r in conn.execute(
            "SELECT page_index FROM pages WHERE document_id = ? ORDER BY page_index",
            (document_id,),
        ).fetchall()
    ]
    return _require_dense_page_index_values(indexes)


_FINALIZE_SNAPSHOT_FIELDS = (
    "id",
    "page_index",
    "image_path",
    "ocr_text",
    "vision_text",
    "summary",
)
_finalize_mutex_registry_guard = threading.Lock()
_finalize_mutex_registry: dict[int, tuple[threading.Lock, int]] = {}


@contextmanager
def _document_finalize_mutex(document_id: int):
    """Serialize finalizers for one document without blocking page writers."""
    with _finalize_mutex_registry_guard:
        entry = _finalize_mutex_registry.get(document_id)
        if entry is None:
            mutex, users = threading.Lock(), 0
        else:
            mutex, users = entry
        _finalize_mutex_registry[document_id] = (mutex, users + 1)
    try:
        with mutex:
            yield
    finally:
        with _finalize_mutex_registry_guard:
            current = _finalize_mutex_registry.get(document_id)
            if current is not None and current[0] is mutex:
                if current[1] == 1:
                    del _finalize_mutex_registry[document_id]
                else:
                    _finalize_mutex_registry[document_id] = (
                        mutex,
                        current[1] - 1,
                    )


def _finalize_snapshot_from_rows(rows) -> list[tuple]:
    return [
        tuple(row[field] for field in _FINALIZE_SNAPSHOT_FIELDS) for row in rows
    ]


def _require_finalize_snapshot(
    conn,
    document_id: int,
    original_snapshot: list[tuple],
    data_version: int,
    *,
    force: bool = False,
) -> int:
    """Reject page changes, scanning rows only after another connection commits."""
    current_data_version = conn.execute("PRAGMA data_version").fetchone()[0]
    if not force and current_data_version == data_version:
        return data_version
    current_pages = conn.execute(
        "SELECT id, page_index, image_path, ocr_text, vision_text, summary "
        "FROM pages WHERE document_id = ? ORDER BY page_index",
        (document_id,),
    ).fetchall()
    _require_dense_page_index_values(
        [page["page_index"] for page in current_pages]
    )
    if _finalize_snapshot_from_rows(current_pages) != original_snapshot:
        raise HTTPException(
            status_code=409,
            detail=(
                "document pages changed during finalization; retry finalize "
                "after reviewing /scan-status"
            ),
        )
    return current_data_version


# --- endpoints --------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {"status": "ok", "versions": version_info()}


@app.get("/v1/version")
def get_version() -> dict:
    """Discovery endpoint: clients negotiate contracts against this block."""
    from .analyzers import list_analyzers
    from .extractors import list_extractors
    from .solvers import list_solvers

    return {
        **version_info(),
        "analyzers": list_analyzers(),
        "solvers": list_solvers(),
        "extractors": list_extractors(),
        "explainers": list_explainers(),
    }


@app.get("/v1/settings")
def get_settings() -> dict:
    """Client-facing flags."""
    return {
        "voice_enabled_default": False,
        "allow_real_exam_solve": config.ALLOW_REAL_EXAM_SOLVE,
        "hud": dict(RENDER_CONTRACT),
        "capture": dict(CAPTURE_CONTRACT),
        "operations": dict(OPERATION_CONTRACT),
        "input": build_input_contract(),
        "versions": version_info(),
    }


@app.post("/v1/documents", status_code=201)
def create_document(payload: CreateDocument) -> dict:
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO documents (title, capture_device) VALUES (?, ?)",
            (payload.title, payload.capture_device),
        )
        conn.commit()
        return {
            "document_id": cur.lastrowid,
            "title": payload.title,
            "capture_device": payload.capture_device,
            "client_version": payload.client_version,
            "sdk_hint": payload.sdk_hint,
            "status": "open",
            "api_version": version_info()["api_version"],
        }
    finally:
        conn.close()


@app.post("/v1/documents/{document_id}/pages", status_code=201)
async def add_page(
    document_id: int,
    page_index: int = Form(...),
    image: UploadFile | None = File(None),
    image_rotation: int = Form(0),
    ocr_text: str | None = Form(None),
    vision_text: str | None = Form(None),
    total_pages: int | None = Form(None),
) -> dict:
    """Record one photographed page or a text-only compatibility page.

    The real-device Android relay sends the original Rokid JPEG plus bundled
    Japanese ML Kit OCR. A configured image-capable analyzer may correct that
    transcription and add a figure/table description during finalization.
    Text-only ``ocr_text`` / ``vision_text`` remains supported for API
    compatibility and imported documents.

    Returns a `scan_ack` HUD payload after every page. Re-sending an existing
    ``page_index`` replaces that page until a bound exam session has entered
    review. New page indexes are accepted only while the document is open.
    """
    has_image = image is not None and getattr(image, "filename", None)
    has_text = (ocr_text and ocr_text.strip()) or (vision_text and vision_text.strip())
    if not has_image and not has_text:
        raise HTTPException(
            status_code=400,
            detail="a page needs ocr_text/vision_text (recognized text) or an image",
        )
    if page_index < 0:
        raise HTTPException(status_code=400, detail="page_index must be >= 0")
    if image_rotation not in (0, 90, 180, 270):
        raise HTTPException(
            status_code=400,
            detail="image_rotation must be one of 0, 90, 180, or 270",
        )
    pending_image_path: Path | None = None
    image_persisted = False
    conn = db.connect()
    try:
        doc = _doc_or_404(conn, document_id)

        if has_image:
            raw = await _read_upload_limited(image)
            img = _rotate_image_for_ocr(_load_image(raw), image_rotation)
            ph = phash_hex(img)
            omd5 = _fallback_md5(ocr_md5(ocr_text), raw)
            fname = f"{document_id}_{page_index}_{uuid.uuid4().hex[:8]}.png"
            fpath: Path | None = IMAGE_DIR / fname
            pending_image_path = fpath
            img.convert("RGB").save(fpath, format="PNG")
            image_path = str(fpath)
        else:
            # Text-only compatibility input has no image/pHash. OCR-MD5 hashes
            # the full body + figure description for exact matching.
            ph = ""
            dedupe_src = _match_text(ocr_text, vision_text)
            omd5 = ocr_md5(dedupe_src) or hashlib.md5(dedupe_src.encode()).hexdigest()
            image_path = None

        existing = conn.execute(
            "SELECT id, image_path FROM pages "
            "WHERE document_id = ? AND page_index = ?",
            (document_id, page_index),
        ).fetchone()
        if existing is not None:
            # 再読取: replace this page's recognition. Frozen once a bound
            # exam session finished reading — its deck was segmented from
            # the OLD text and replacing underneath it would diverge them.
            review_conflict_detail = (
                f"page_index {page_index} belongs to an exam session that "
                "already finished reading; re-scan into a new document "
                "(POST /v1/documents)"
            )
            reviewing = conn.execute(
                "SELECT COUNT(*) FROM exam_sessions "
                "WHERE document_id = ? AND status = 'reviewing'",
                (document_id,),
            ).fetchone()[0]
            if reviewing:
                raise HTTPException(
                    status_code=409,
                    detail=review_conflict_detail,
                )
            updated = conn.execute(
                "UPDATE pages SET image_path = ?, phash = ?, ocr_text = ?, "
                "vision_text = ?, ocr_md5 = ?, summary = NULL WHERE id = ? "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM exam_sessions "
                "  WHERE document_id = ? AND status = 'reviewing'"
                ")",
                (
                    image_path,
                    ph,
                    ocr_text,
                    vision_text,
                    omd5,
                    existing["id"],
                    document_id,
                ),
            )
            if updated.rowcount != 1:
                # The session may have transitioned to reviewing after the
                # optimistic check above. Evaluate this predicate again in the
                # UPDATE itself, under SQLite's write lock, so either the new
                # page wins before segmentation or the finished deck wins.
                conn.rollback()
                raise HTTPException(
                    status_code=409,
                    detail=review_conflict_detail,
                )
            conn.commit()
            image_persisted = pending_image_path is not None
            if existing["image_path"] and existing["image_path"] != image_path:
                # The replaced photo must not linger on disk.
                _unlink_best_effort(existing["image_path"])
            page_id, replaced = existing["id"], True
        else:
            if doc["status"] != "open":
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"document {document_id} is finalized "
                        f"(status={doc['status']}); new pages cannot be added — "
                        "re-send an existing page_index to replace it, or create "
                        "a new document"
                    ),
                )
            try:
                cur = conn.execute(
                    """INSERT INTO pages
                       (document_id, page_index, image_path, phash, ocr_text,
                        vision_text, ocr_md5)
                       SELECT ?, ?, ?, ?, ?, ?, ?
                       WHERE EXISTS (
                           SELECT 1 FROM documents
                           WHERE id = ? AND status = 'open'
                       )""",
                    (
                        document_id,
                        page_index,
                        image_path,
                        ph,
                        ocr_text,
                        vision_text,
                        omd5,
                        document_id,
                    ),
                )
                if cur.rowcount != 1:
                    # The document may have finalized after the optimistic
                    # status read above while this INSERT waited for SQLite's
                    # writer lock. Re-check in the write statement itself so a
                    # new page can never land in a ready document.
                    current_doc = _doc_or_404(conn, document_id)
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"document {document_id} is finalized "
                            f"(status={current_doc['status']}); new pages cannot "
                            "be added — re-send an existing page_index to replace "
                            "it, or create a new document"
                        ),
                    )
                conn.commit()
                image_persisted = pending_image_path is not None
            except db.sqlite3.IntegrityError:
                # Two racing first-time adds of the same index: the loser keeps
                # the old (pre-upsert) conflict answer.
                raise HTTPException(
                    status_code=409,
                    detail=f"page_index {page_index} already exists",
                )
            page_id, replaced = cur.lastrowid, False

        # Count scanned pages so far (including the one just inserted).
        scanned_count = conn.execute(
            "SELECT COUNT(*) FROM pages WHERE document_id = ?", (document_id,)
        ).fetchone()[0]
        # No declared total -> the ack must not claim completion (None keeps
        # all_scanned false); an understated total is corrected upward so the
        # HUD never shows 5/3ページ完了.
        effective_total = (
            max(total_pages, scanned_count) if total_pages and total_pages > 0 else None
        )
        ack = build_scan_ack(
            page_index=page_index,
            scanned_count=scanned_count,
            total_pages=effective_total,
        )

        return {
            "page_id": page_id,
            "document_id": document_id,
            "page_index": page_index,
            "replaced": replaced,
            "phash": ph,
            "ocr_md5": omd5,
            "image_path": image_path,
            "image_rotation": image_rotation,
            "has_vision_text": bool(vision_text and vision_text.strip()),
            "scan_ack": ack,
        }
    finally:
        conn.close()
        # Image validation necessarily happens before the DB write. If a later
        # guard rejects the request (finalized document/reviewing session/race),
        # do not retain a photo that no database row owns.
        if pending_image_path is not None and not image_persisted:
            _unlink_best_effort(pending_image_path)


# Physical exams do not exceed this; the cap bounds the missing-index range
# expansion below (and the response payload) against absurd inputs.
MAX_EXPECTED_TOTAL_PAGES = 10_000


@app.get("/v1/documents/{document_id}/scan-status")
def get_document_scan_status(
    document_id: int, expected_total_pages: int | None = None
) -> dict:
    """Read-only page report used to resume an interrupted reading phase.

    The response reports registered indexes, recognition state and whether an
    authoritative page image exists. It never reads the camera or mutates data.
    """
    if expected_total_pages is not None:
        # Validate before any range expansion (unbounded set(range(N)) would
        # burn CPU/memory long before a sanity check downstream).
        if expected_total_pages <= 0:
            raise HTTPException(
                status_code=400, detail="expected_total_pages must be >= 1"
            )
        if expected_total_pages > MAX_EXPECTED_TOTAL_PAGES:
            raise HTTPException(
                status_code=400,
                detail=f"expected_total_pages must be <= {MAX_EXPECTED_TOTAL_PAGES}",
            )
    conn = db.connect()
    try:
        doc = _doc_or_404(conn, document_id)
        rows = conn.execute(
            "SELECT id, page_index, image_path, ocr_text, vision_text, summary FROM pages "
            "WHERE document_id = ? ORDER BY page_index",
            (document_id,),
        ).fetchall()
        sessions = conn.execute(
            "SELECT id, status FROM exam_sessions WHERE document_id = ? "
            "ORDER BY id",
            (document_id,),
        ).fetchall()
    finally:
        conn.close()

    def _has(value) -> bool:
        return bool(value and str(value).strip())

    pages = [
        {
            "page_id": r["id"],
            "page_index": r["page_index"],
            "has_ocr_text": _has(r["ocr_text"]),
            "has_vision_text": _has(r["vision_text"]),
            "has_image": _has(r["image_path"]),
            "summary_generated": _has(r["summary"]),
        }
        for r in rows
    ]
    registered = [p["page_index"] for p in pages]
    # A just-uploaded photo can have no phone OCR yet; finalization may still
    # recover it through a configured image-capable analyzer.
    pages_without_text = [
        p["page_index"] for p in pages
        if not (p["has_ocr_text"] or p["has_vision_text"])
    ]

    if expected_total_pages is not None:
        expected = set(range(expected_total_pages))
        got = set(registered)
        missing = sorted(expected - got)
        unexpected = sorted(got - expected)
        complete: bool | None = not missing and not unexpected
    else:
        # Never claim completeness without a declared total (same honesty
        # rule as build_scan_ack with total_pages=None).
        missing = None
        unexpected = None
        complete = None

    session_summaries = [
        {
            "session_id": s["id"],
            "status": s["status"],
            "phase": _session_phase(s),
        }
        for s in sessions
    ]
    # Mirrors add_page's freeze: once a bound session finished reading,
    # replacing a page underneath its deck is rejected with 409.
    reread_allowed = not any(s["status"] == "reviewing" for s in sessions)

    if not pages:
        recommended = "start_reading"
    elif unexpected:
        # Extras exist — checked BEFORE missing indexes: when both coexist
        # the stray index is likely the missing page mis-indexed, and blindly
        # rereading would leave the stray page in the document. The indexes
        # need review first — but index corrections are impossible once the
        # document is finalized (new indexes 409, strays cannot be removed),
        # so a ready document needs a fresh one.
        recommended = (
            "review_page_indexes" if doc["status"] != "ready"
            else "start_new_document"
        )
    elif missing:
        # NEW page indexes are rejected with 409 once the document is
        # finalized (add_page), so 再読取 of a missing index can only
        # succeed on a still-open document.
        recommended = (
            "reread_missing_pages" if doc["status"] != "ready"
            else "start_new_document"
        )
    elif expected_total_pages is None and sorted(registered) != list(
        range(len(registered))
    ):
        # No declared total, so we can't name specific missing pages — but the
        # registered indexes alone already break the 0..N-1 navigation invariant
        # that finalize and session creation enforce (_require_dense_page_indexes
        # would 409). Don't point at a dead finalize; send the user to index
        # review, or a fresh document once the doc is finalized.
        recommended = (
            "review_page_indexes" if doc["status"] != "ready"
            else "start_new_document"
        )
    elif pages_without_text and doc["status"] == "ready":
        # Legacy ready documents may predate image OCR persistence. Replacing an
        # existing index remains possible until a bound session enters review.
        recommended = (
            "reread_pages_without_text" if reread_allowed
            else "start_new_document"
        )
    elif doc["status"] != "ready" or not all(p["summary_generated"] for p in pages):
        recommended = "finalize"
    else:
        recommended = "continue"

    return {
        "document_id": document_id,
        "title": doc["title"],
        "status": doc["status"],
        "page_count": len(pages),
        "page_indexes": registered,
        "pages": pages,
        "expected_total_pages": expected_total_pages,
        "missing_page_indexes": missing,
        "unexpected_page_indexes": unexpected,
        "expected_pages_complete": complete,
        "pages_without_text": pages_without_text,
        "summaries_complete": bool(pages)
        and all(p["summary_generated"] for p in pages),
        "exam_sessions": session_summaries,
        "reread_allowed": reread_allowed,
        "reread": {
            "method": "POST /v1/documents/{document_id}/pages",
            "replaces_existing_page_index": True,
        },
        "recommended_action": recommended,
        "versions": version_info(),
    }


@app.post("/v1/documents/{document_id}/finalize")
def finalize_document(document_id: int) -> dict:
    with _document_finalize_mutex(document_id):
        return _finalize_document_once(document_id)


def _finalize_document_once(document_id: int) -> dict:
    conn = db.connect()
    try:
        snapshot_data_version = conn.execute("PRAGMA data_version").fetchone()[0]
        _doc_or_404(conn, document_id)
        pages = conn.execute(
            "SELECT id, page_index, image_path, ocr_text, vision_text, summary FROM pages "
            "WHERE document_id = ? ORDER BY page_index",
            (document_id,),
        ).fetchall()
        if not pages:
            raise HTTPException(status_code=400, detail="document has no pages")
        _require_dense_page_indexes(conn, document_id)

        analyzer = get_analyzer()
        original_snapshot = _finalize_snapshot_from_rows(pages)
        snapshot_data_version = _require_finalize_snapshot(
            conn,
            document_id,
            original_snapshot,
            snapshot_data_version,
        )
        pending_updates = []
        for p in pages:
            next_ocr = p["ocr_text"]
            next_vision = p["vision_text"]

            # Idempotent: an already-finalized page needs no repeated cloud call.
            # Replaced pages have summary=NULL and are analyzed again.
            if p["summary"] is not None:
                continue

            # A page may be replaced between any two provider calls. Check both
            # sides of each slow call so a stale request stops promptly without
            # billing later pages. If the provider itself fails after a
            # replacement completed, preserve the existing 409 conflict instead
            # of masking it with an unrelated provider error.
            snapshot_data_version = _require_finalize_snapshot(
                conn,
                document_id,
                original_snapshot,
                snapshot_data_version,
            )
            try:
                result = analyzer.analyze(
                    image_path=p["image_path"],
                    ocr_text=_page_material(next_ocr, next_vision) or next_ocr,
                )
                extras = result.extras if isinstance(result.extras, dict) else {}
                analyzed_text = (result.text or "").strip()
                if analyzed_text and (
                    not (next_ocr and next_ocr.strip())
                    or extras.get("image_analyzed")
                ):
                    # A successful image analyzer is authoritative over provisional
                    # phone OCR; a text-only/local analyzer preserves supplied OCR.
                    next_ocr = analyzed_text
                analyzed_vision = str(extras.get("vision_text") or "").strip()
                if analyzed_vision and not (next_vision and next_vision.strip()):
                    next_vision = analyzed_vision

                next_summary = (
                    result.summary or next_ocr or next_vision or ""
                )[:48]
            except Exception:
                _require_finalize_snapshot(
                    conn,
                    document_id,
                    original_snapshot,
                    snapshot_data_version,
                )
                raise
            snapshot_data_version = _require_finalize_snapshot(
                conn,
                document_id,
                original_snapshot,
                snapshot_data_version,
            )
            pending_updates.append(
                (
                    next_ocr,
                    next_vision,
                    next_summary,
                    p["id"],
                    p["page_index"],
                    p["image_path"],
                    p["ocr_text"],
                    p["vision_text"],
                    p["summary"],
                )
            )

        # The analyzer can be slow or remote, so every call and result
        # transformation above runs before the write transaction. Acquire the
        # writer lock only for the final snapshot check and atomic page/status
        # update. A queued new-page INSERT also re-checks document.status in its
        # write statement, so it cannot slip in after this commits ready.
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        _require_finalize_snapshot(
            conn,
            document_id,
            original_snapshot,
            snapshot_data_version,
            force=True,
        )
        for update_values in pending_updates:
            updated = conn.execute(
                "UPDATE pages SET ocr_text = ?, vision_text = ?, summary = ? "
                "WHERE id = ? AND page_index = ? "
                "AND image_path IS ? AND ocr_text IS ? "
                "AND vision_text IS ? AND summary IS ?",
                update_values,
            )
            if updated.rowcount != 1:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "document pages changed during finalization; retry finalize "
                        "after reviewing /scan-status"
                    ),
                )
        conn.execute(
            "UPDATE documents SET status = 'ready' WHERE id = ?", (document_id,)
        )
        conn.commit()

        summaries = conn.execute(
            "SELECT page_index, summary FROM pages "
            "WHERE document_id = ? ORDER BY page_index",
            (document_id,),
        ).fetchall()
        return {
            "document_id": document_id,
            "status": "ready",
            "page_count": len(pages),
            "summaries": [dict(s) for s in summaries],
            "analyzer": analyzer.info(),
            "api_version": version_info()["api_version"],
        }
    finally:
        conn.close()


@app.post("/v1/match")
async def match_page(
    document_id: int = Form(...),
    ocr_text: str | None = Form(None),
    vision_text: str | None = Form(None),
    fast_ocr_text: str | None = Form(None),
    image: UploadFile | None = File(None),
    client_version: str | None = Form(None),
    sdk_hint: str | None = Form(None),
) -> dict:
    """Match the page currently in view against the registered pages.

    撮影しない: the primary query is the on-glass AI's on-the-spot recognition
    (``ocr_text``, plus ``vision_text`` when only figures were readable) — no
    photo is taken. ``fast_ocr_text`` is the legacy alias for ``ocr_text``.
    ``image`` is an optional backward-compat input (非推奨): when attached, the
    historical pHash comparison is used for image-registered pages.
    """
    query_text = ocr_text if (ocr_text and ocr_text.strip()) else fast_ocr_text
    has_text = bool(query_text and query_text.strip()) or bool(
        vision_text and vision_text.strip()
    )
    has_image = image is not None and getattr(image, "filename", None)
    if not has_image and not has_text:
        raise HTTPException(
            status_code=400,
            detail="match needs ocr_text/vision_text (recognized text) "
            "or a legacy image",
        )
    conn = db.connect()
    try:
        _doc_or_404(conn, document_id)
        raw_q_md5: str | None = None
        if has_image:
            raw = await _read_upload_limited(image)
            img = _load_image(raw)
            q_phash: str | None = phash_hex(img)
            # Historical compat rule: body text MD5, falling back to the
            # image bytes.
            raw_q_md5 = _fallback_md5(ocr_md5(query_text), raw)
        else:
            q_phash = None

        # 撮影しない text comparison. The shape is aligned PER CANDIDATE on
        # the signals BOTH sides actually carry, so neither side is penalized
        # for information the other lacks:
        #   - body and figure reading on both sides -> the components are
        #     compared separately (equal weight — a long shared body cannot
        #     mask a mismatched figure reading) and the exact-MD5 shortcut
        #     hashes the FULL combined material on both sides, even for
        #     legacy image queries,
        #   - figure reading on both but a body missing on either -> compare
        #     the figure readings alone,
        #   - body on both but a figure reading missing on either -> compare
        #     the bodies alone (image queries/pages keep their historical
        #     body/raw-bytes MD5 compat),
        #   - no common text signal -> do not compare body text with a figure
        #     reading; only a shared visual signal, when present, may score.
        # Comparisons that had to ignore one of the query's signals get a
        # lower signal_coverage, so a full body+figure match outranks a
        # body-only fallback at equal confidence.
        q_body = normalize_ocr_text(query_text)
        q_vision = normalize_ocr_text(vision_text)
        q_combined = _match_text(query_text, vision_text)
        q_signals = int(bool(q_body)) + int(bool(q_vision))

        def _text_md5(src: str) -> str:
            return ocr_md5(src) or hashlib.md5(src.encode()).hexdigest()

        rows = conn.execute(
            "SELECT id, page_index, phash, ocr_md5, ocr_text, vision_text, "
            "summary FROM pages "
            "WHERE document_id = ? ORDER BY page_index",
            (document_id,),
        ).fetchall()
        scored = []
        for r in rows:
            c_body = normalize_ocr_text(r["ocr_text"])
            c_vision = normalize_ocr_text(r["vision_text"])
            common_body = bool(q_body and c_body)
            common_vision = bool(q_vision and c_vision)
            cand_vision: str | None = None
            q_vision_cmp: str | None = None
            if common_body and common_vision:
                cand_text: str | None = c_body
                cand_vision = c_vision
                q_text_cmp: str | None = q_body
                q_vision_cmp = q_vision
                q_md5_cmp = _text_md5(q_combined)
                cand_md5 = ocr_md5(_match_text(r["ocr_text"], r["vision_text"]))
                used_signals = 2
            elif common_vision:
                cand_text = c_vision
                q_text_cmp = q_vision
                q_md5_cmp = _text_md5(q_vision)
                cand_md5 = ocr_md5(c_vision)
                used_signals = 1
            elif common_body:
                cand_text = c_body
                q_text_cmp = q_body
                q_md5_cmp = (
                    raw_q_md5 if raw_q_md5 is not None else _text_md5(q_body)
                )
                cand_md5 = r["ocr_md5"] if r["phash"] else ocr_md5(c_body)
                used_signals = 1
            else:
                # Body OCR and figure readings describe different signal
                # types. Comparing them cross-type can turn an accidental
                # equal string into an exact text-only HIT even though no
                # supplied signal was verified. Leave the text inputs empty;
                # score_candidate may still use a shared legacy pHash.
                cand_text = None
                q_text_cmp = None
                q_md5_cmp = None
                cand_md5 = None
                # No signal type in common (e.g. a vision-only query vs a
                # body-only page): any comparison here is cross-type, so NO
                # supplied query signal was actually verified. Coverage is 0
                # so a merely-near pHash HIT cannot sit in the full-information
                # tier on the strength of an unmatched figure/body signal.
                used_signals = 0
            sc = score_candidate(
                q_phash,
                q_md5_cmp,
                Candidate(
                    page_id=r["id"],
                    page_index=r["page_index"],
                    phash=r["phash"],
                    ocr_md5=cand_md5,
                    ocr_text=cand_text,
                    vision_text=cand_vision,
                ),
                query_ocr_text=q_text_cmp,
                query_vision_text=q_vision_cmp,
            )
            sc.signal_coverage = (
                used_signals / q_signals if q_signals else 1.0
            )
            scored.append(sc)
        summaries = {r["id"]: r["summary"] for r in rows}

        scored = rank(scored)
        best = scored[0] if scored else None
        verdict = match_verdict(best.confidence if best else 0.0, bool(scored))
        hud = build_hud(
            verdict,
            best,
            total_pages=len(rows),
            summary=summaries.get(best.page_id) if best else None,
        )

        return {
            "document_id": document_id,
            "query_phash": q_phash,
            "query_signals": {"phash": q_phash is not None, "text": has_text},
            "verdict": verdict,
            "versions": {
                **version_info(),
                "hud_contract_version": HUD_CONTRACT_VERSION,
            },
            "client_version": client_version,
            "sdk_hint": sdk_hint,
            "best_page": (
                {
                    "page_id": best.page_id,
                    "page_index": best.page_index,
                    "hamming": best.hamming,
                    "ocr_match": best.ocr_match,
                    "ocr_similarity": best.ocr_similarity,
                    "confidence": best.confidence,
                }
                if best and verdict != "NO_PAGE"
                else None
            ),
            "confidence": best.confidence if best else 0.0,
            "hud": hud,
            "candidates": [
                {
                    "page_id": s.page_id,
                    "page_index": s.page_index,
                    "hamming": s.hamming,
                    "ocr_match": s.ocr_match,
                    "ocr_similarity": s.ocr_similarity,
                    "confidence": s.confidence,
                }
                for s in scored
            ],
        }
    finally:
        conn.close()


# --- exam-solving mode ------------------------------------------------------

class CreateExamSession(BaseModel):
    mode: str = "study"
    voice_enabled: bool = False
    subject_hint: str | None = None
    # Document page-move型 exam (scan-free): bind to a finalized document and
    # navigate its pages by button. exam_type 筆記(written) ⇄ リスニング(listening);
    # answer_format マーク式(mark) ⇄ 記述式(written).
    document_id: int | None = None
    exam_type: str = "written"
    answer_format: str = "mark"


# Valid enum values for the document page-move exam.
_EXAM_TYPES = {"written", "listening"}
_ANSWER_FORMATS = {"mark", "written"}

# Answer-format instruction folded into the solver context so a real model
# answers in the format the exam expects (offline placeholder ignores it).
_ANSWER_FORMAT_HINT = {
    "mark": "解答はマーク式（選択肢の記号）で選び、根拠を簡潔に示してください。",
    "written": "解答は記述式で、結論と要点の過程を簡潔に示してください。",
}


def _exam_session_or_404(conn, session_id: int):
    return _row_or_404(conn, "exam_sessions", session_id, "exam session not found")


def _session_phase(session) -> str:
    """3-phase lifecycle: 'reading' (camera ON, LED lit) → 'reviewing' (camera OFF).

    The legacy default status 'open' is a reading-phase alias, so pre-existing
    sessions keep working unchanged; finalize-reading sets status='reviewing'.
    """
    return "reviewing" if session["status"] == "reviewing" else "reading"


def _exam_total_pages(conn, doc_id: int | None) -> int:
    if not doc_id:
        return 0
    return conn.execute(
        "SELECT COUNT(*) FROM pages WHERE document_id = ?", (doc_id,)
    ).fetchone()[0]


def _document_material(conn, doc_id: int, current_index: int) -> str:
    """Return ALL pages of the document as labeled text, current page marked.

    A problem may continue across pages (e.g. a passage on one page, its
    questions on the next), so the solver is given every remembered page — not
    just the current one — as context, and can read the continuation accurately.
    """
    rows = conn.execute(
        "SELECT page_index, ocr_text, vision_text FROM pages "
        "WHERE document_id = ? ORDER BY page_index",
        (doc_id,),
    ).fetchall()
    blocks: list[str] = []
    for r in rows:
        mark = "◀現在ページ" if r["page_index"] == current_index else ""
        body = _page_material(r["ocr_text"], r["vision_text"]) or "(なし)"
        blocks.append(f"【P{r['page_index'] + 1:02d}{mark}】\n{body}")
    return "\n\n".join(blocks)


def _exam_prompt_context(
    session, document_material: str, retrieved_context: str = ""
) -> str | None:
    """Compose solver context for a document-page exam.

    Folds in the answer-format hint, the **whole document** (all remembered
    pages, so page-spanning problems are read correctly), and — in listening
    mode — the recorded audio's transcript. The current page stays the body_text.
    """
    parts: list[str] = []
    fmt_hint = _ANSWER_FORMAT_HINT.get(session["answer_format"], "")
    if fmt_hint:
        parts.append(fmt_hint)
    if session["exam_type"] == "listening":
        parts.append(
            "これは英語リスニング問題です。設問は目の前の資料から読み取り、"
            "下記の音声書き起こしを根拠に解答してください。"
        )
        transcript = (session["transcript"] or "").strip()
        if transcript:
            parts.append("【リスニング音声 書き起こし】\n" + transcript)
    if document_material:
        parts.append("【文書の全ページ（現在ページを含む）】\n" + document_material)
    if retrieved_context:
        parts.append("【参考資料（過去の学習資料）】\n" + retrieved_context)
    return "\n\n".join(p for p in parts if p) or None


def _question_or_404(conn, session_id: int, question_id: int):
    row = conn.execute(
        "SELECT * FROM questions WHERE id = ? AND session_id = ?",
        (question_id, session_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="question not found")
    return row


def _legacy_solution_evidence_page_base(row, question_row) -> int | None:
    """Identify legacy bare-page semantics without rewriting API v1 data.

    Before ``evidence_refs_json`` existed, solve/retrieval routes stored raw
    0-based retrieval indexes, while the onboard/deck paths stored user-facing
    1-based page numbers. The question metadata and the exact deck span let us
    distinguish the repository's historical writers at display time. Unknown
    custom non-deck solver rows follow the old SolveResult contract (indexes).
    """
    if row["evidence_refs_json"] is not None:
        return None
    try:
        pages = json.loads(row["evidence_pages_json"] or "[]")
    except (TypeError, ValueError):
        return None
    if not pages:
        return None
    if row["solver_name"] == "onboard" or row["served_by"] == "onboard":
        return 1
    try:
        meta = json.loads(question_row["structure_json"] or "null")
    except (TypeError, ValueError):
        meta = None
    if isinstance(meta, dict) and (meta.get("deck") or "page_indexes" in meta):
        span = meta.get("page_indexes") or []
        one_based_span = [index + 1 for index in span if isinstance(index, int)]
        if one_based_span and pages == one_based_span:
            return 1
        page_number = question_row["page_number"]
        if not one_based_span and page_number and pages == [page_number]:
            return 1
    return 0


def _solution_from_row(row, question_row=None) -> "object":
    from .solvers import SolveResult

    extras = {}
    if question_row is not None:
        page_base = _legacy_solution_evidence_page_base(row, question_row)
        if page_base is not None:
            extras["_evidence_pages_base"] = page_base
    return SolveResult(
        answer=row["answer"] or "",
        solution_steps=json.loads(row["solution_steps_json"] or "[]"),
        rationale=row["rationale"] or "",
        cautions=row["cautions"] or "",
        answer_confidence=row["answer_conf"] or 0.0,
        rationale_confidence=row["rationale_conf"] or 0.0,
        evidence_pages=json.loads(row["evidence_pages_json"] or "[]"),
        evidence_refs=json.loads(row["evidence_refs_json"] or "[]"),
        raw_reasoning=row["raw_reasoning"] or "",
        extras=extras,
    )


def _prepare_result_evidence(
    result,
    *,
    fallback_pages: list[int],
    fallback_refs: list[dict],
) -> tuple[list[int], list[dict]]:
    """Keep page-only legacy evidence separate from structured references.

    Solver API <1.2 and Explainer API <1.1 could select evidence only through
    the legacy 0-based evidence_pages list. Replacing that selection with every
    retriever ref changes its meaning; persisting [] as evidence_refs_json also
    makes later readers mistake P00 for a user-facing label. Preserve the
    selected list, mark its display base, and store SQL NULL for refs so cached
    readers can recover the same semantics. Only use retrieval fallback when
    the provider supplied neither evidence field.
    """
    if result.evidence_refs:
        evidence_pages = list(result.evidence_pages or [])
        evidence_refs = list(result.evidence_refs)
    elif result.evidence_pages:
        evidence_pages = list(result.evidence_pages)
        evidence_refs = []
        if not isinstance(result.extras, dict):
            result.extras = {}
        result.extras["_evidence_pages_base"] = 0
    else:
        evidence_pages = list(fallback_pages)
        evidence_refs = list(fallback_refs)

    result.evidence_pages = evidence_pages
    result.evidence_refs = evidence_refs
    return evidence_pages, evidence_refs


def _evidence_refs_storage_value(result) -> str | None:
    """Serialize refs while retaining the page-only legacy base marker."""
    extras = result.extras if isinstance(result.extras, dict) else {}
    if (
        result.evidence_pages
        and not result.evidence_refs
        and extras.get("_evidence_pages_base") == 0
    ):
        return None
    return json.dumps(result.evidence_refs, ensure_ascii=False)


@app.post("/v1/exam-sessions", status_code=201)
def create_exam_session(payload: CreateExamSession) -> dict:
    if payload.mode not in {"study", "mock", "real"}:
        raise HTTPException(status_code=400, detail="invalid mode")
    if payload.exam_type not in _EXAM_TYPES:
        raise HTTPException(status_code=400, detail=f"exam_type must be one of {_EXAM_TYPES}")
    if payload.answer_format not in _ANSWER_FORMATS:
        raise HTTPException(
            status_code=400, detail=f"answer_format must be one of {_ANSWER_FORMATS}"
        )
    conn = db.connect()
    try:
        if payload.document_id is not None:
            doc = _doc_or_404(conn, payload.document_id)
            # A page-move exam navigates a finalized document's pages, so it must
            # already be finalized (status='ready') with at least one page —
            # otherwise current/solve-current would 404 and nav would show P01/0.
            if doc["status"] != "ready" or _exam_total_pages(conn, payload.document_id) < 1:
                raise HTTPException(
                    status_code=400,
                    detail="document must be finalized with >=1 page "
                    "(POST /v1/documents/{id}/finalize) before a page-move exam",
                )
            _require_dense_page_indexes(conn, payload.document_id)
        cur = conn.execute(
            "INSERT INTO exam_sessions "
            "(mode, voice_enabled, subject_hint, document_id, exam_type, answer_format) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                payload.mode,
                int(payload.voice_enabled),
                payload.subject_hint,
                payload.document_id,
                payload.exam_type,
                payload.answer_format,
            ),
        )
        conn.commit()
        return {
            "session_id": cur.lastrowid,
            "mode": payload.mode,
            "voice_enabled": payload.voice_enabled,
            "subject_hint": payload.subject_hint,
            "document_id": payload.document_id,
            "exam_type": payload.exam_type,
            "answer_format": payload.answer_format,
            "current_page_index": 0,
            "total_pages": _exam_total_pages(conn, payload.document_id),
            "status": "open",
            # 3-phase lifecycle: reading (camera ON) until finalize-reading.
            "phase": "reading",
            "operations": OPERATION_CONTRACT,
            "api_version": version_info()["api_version"],
        }
    finally:
        conn.close()


@app.post("/v1/exam-sessions/{session_id}/questions", status_code=201)
async def add_question(
    session_id: int,
    ocr_text: str | None = Form(None),
    vision_text: str | None = Form(None),
    image: UploadFile | None = File(None),
    bbox_hints: str | None = Form(None),
) -> dict:
    """Ingest one question. 撮影しない: the primary input is the on-glass
    AI's on-the-spot recognition — body text (``ocr_text``) plus the figure/
    diagram reading (``vision_text``); structure, subject, media and anchors
    are all derived from text. ``image`` is an optional backward-compat
    input (非推奨) kept for the legacy upload flow.
    """
    has_image = image is not None and getattr(image, "filename", None)
    # Same combination rule as page ingestion: body + 【図・画像の読み取り】.
    recognized = _page_material(ocr_text, vision_text) or None
    if not has_image and not recognized:
        raise HTTPException(
            status_code=400,
            detail="a question needs ocr_text/vision_text (recognized text) "
            "or an image",
        )
    conn = db.connect()
    try:
        _exam_session_or_404(conn, session_id)
        try:
            hints = json.loads(bbox_hints) if bbox_hints else None
        except ValueError:
            raise HTTPException(
                status_code=400, detail="bbox_hints must be valid JSON"
            )
        # Question boundaries come from the BODY text only — figure readings
        # can contain (1)/問N-shaped labels that must not split the question.
        # The vision block is appended to the stored body afterwards.
        parsed = parse_layout(ocr_text, bbox_hints=hints)
        q = primary_question(parsed)
        subject, subj_conf = detect_subject(recognized)

        read_conf = 0.0 if not normalize_ocr_text(recognized) else round(min(1.0, 0.5 + subj_conf / 2), 3)

        # Persist the compat image only after every parse step that can
        # reject the request — a failed request must not orphan a file in
        # IMAGE_DIR (no questions row would ever own it).
        fpath: Path | None = None
        if has_image:
            raw = await _read_upload_limited(image)
            img = _load_image(raw)
            fname = f"q_{session_id}_{uuid.uuid4().hex[:8]}.png"
            fpath = IMAGE_DIR / fname
            img.convert("RGB").save(fpath, format="PNG")

        answer_box = q.answer_box if q else parsed.get("answer_box")
        media = _extract_media(recognized, str(fpath) if fpath else None)
        cur = conn.execute(
            """INSERT INTO questions
               (session_id, question_no, body_text, choices_json, figure_refs,
                answer_box_json, structure_json, subject, read_conf,
                page_number, image_path, media_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                q.question_no if q else None,
                # Keep the figure reading with the question body (appended
                # after boundary detection, same combination rule as pages).
                _page_material(q.body_text if q else ocr_text, vision_text)
                or "",
                json.dumps(q.choices if q else [], ensure_ascii=False),
                json.dumps(q.figure_refs if q else [], ensure_ascii=False),
                json.dumps(answer_box, ensure_ascii=False) if answer_box else None,
                json.dumps(parsed.get("headings", []), ensure_ascii=False),
                subject,
                read_conf,
                parsed.get("page_number"),
                str(fpath) if fpath else None,
                json.dumps(media, ensure_ascii=False) if media else None,
            ),
        )
        conn.commit()

        result = {
            "question_id": cur.lastrowid,
            "session_id": session_id,
            "question_no": q.question_no if q else None,
            "subject": subject,
            "read_confidence": read_conf,
            "answer_box": answer_box,
            "page_number": parsed.get("page_number"),
            "media": media,
            "capture_ack": build_capture_ack(
                page_number=parsed.get("page_number"), question_id=cur.lastrowid
            ),
        }
        if read_conf < 0.3:
            result["hint"] = {
                "lines": ["読み取り不十分", "近づけて再読取", "してください"],
            }
        return result
    finally:
        conn.close()


@app.post("/v1/exam-sessions/{session_id}/questions/{question_id}/solve")
def solve_question(session_id: int, question_id: int) -> dict:
    conn = db.connect()
    try:
        session = _exam_session_or_404(conn, session_id)
        q = _question_or_404(conn, session_id, question_id)

        if session["mode"] == "real" and not config.ALLOW_REAL_EXAM_SOLVE:
            return {
                "session_id": session_id,
                "question_id": question_id,
                "locked": True,
                "glasses_view": build_locked_view(),
                "versions": version_info(),
            }

        retrieved = retrieve_context(conn, q["body_text"])
        question = Question(
            question_no=q["question_no"],
            body_text=q["body_text"],
            choices=json.loads(q["choices_json"] or "[]"),
            subject=q["subject"],
            context=retrieved["context"] or None,
            image_path=q["image_path"],
        )
        result, solver = solve_with_fallback(question=question)
        served_by = result.extras.get("served_by", solver.name)
        evidence_pages, evidence_refs = _prepare_result_evidence(
            result,
            fallback_pages=retrieved["evidence_pages"],
            fallback_refs=retrieved["evidence_refs"],
        )

        conn.execute(
            """INSERT INTO solutions
               (question_id, solver_name, answer, solution_steps_json, rationale,
                cautions, answer_conf, rationale_conf, evidence_pages_json,
                evidence_refs_json, raw_reasoning, served_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                question_id,
                solver.name,
                result.answer,
                json.dumps(result.solution_steps, ensure_ascii=False),
                result.rationale,
                result.cautions,
                result.answer_confidence,
                result.rationale_confidence,
                json.dumps(evidence_pages),
                _evidence_refs_storage_value(result),
                result.raw_reasoning,
                served_by,
            ),
        )
        conn.commit()

        answer_box = json.loads(q["answer_box_json"]) if q["answer_box_json"] else None
        view = build_glasses_view(
            result,
            stage="answer",
            question_no=q["question_no"],
            page_number=q["page_number"],
            answer_box=answer_box,
            voice_enabled=bool(session["voice_enabled"]),
        )
        return {
            "session_id": session_id,
            "question_id": question_id,
            "subject": result.subject or q["subject"],
            "solver": solver.info(),
            "served_by": served_by,
            "locked": False,
            "glasses_view": view,
            "overlay": build_overlay(
                result, answer_box=answer_box, page_number=q["page_number"]
            ),
            "evidence": retrieved["hits"],
            "evidence_pages": result.evidence_pages,
            "evidence_refs": result.evidence_refs,
            "versions": version_info(),
        }
    finally:
        conn.close()


@app.get("/v1/exam-sessions/{session_id}/questions/{question_id}/view")
def get_question_view(
    session_id: int,
    question_id: int,
    stage: str = "answer",
    page: int = 0,
) -> dict:
    if stage not in STAGES:
        raise HTTPException(status_code=400, detail=f"stage must be one of {STAGES}")
    conn = db.connect()
    try:
        session = _exam_session_or_404(conn, session_id)
        q = _question_or_404(conn, session_id, question_id)
        # Lock gate FIRST: a locked session must answer uniformly regardless
        # of solve state (the 409 would otherwise reveal it via status code).
        if session["mode"] == "real" and not config.ALLOW_REAL_EXAM_SOLVE:
            return {"glasses_view": build_locked_view(stage), "locked": True}
        sol = _latest_solution_row(conn, question_id)
        if sol is None:
            raise HTTPException(status_code=409, detail="question not solved yet")

        answer_box = json.loads(q["answer_box_json"]) if q["answer_box_json"] else None
        return {
            "glasses_view": build_glasses_view(
                _solution_from_row(sol, q),
                stage=stage,
                page=page,
                question_no=q["question_no"],
                page_number=q["page_number"],
                answer_box=answer_box,
                voice_enabled=bool(session["voice_enabled"]),
            ),
            "locked": False,
        }
    finally:
        conn.close()


@app.get("/v1/exam-sessions/{session_id}/questions/{question_id}/reasoning")
def get_question_reasoning(session_id: int, question_id: int) -> dict:
    conn = db.connect()
    try:
        session = _exam_session_or_404(conn, session_id)
        _question_or_404(conn, session_id, question_id)
        if session["mode"] == "real" and not config.ALLOW_REAL_EXAM_SOLVE:
            return {"question_id": question_id, "locked": True}
        sol = _latest_solution_row(conn, question_id)
        if sol is None:
            raise HTTPException(status_code=409, detail="question not solved yet")
        return {
            "session_id": session_id,
            "question_id": question_id,
            "locked": False,
            "solver_name": sol["solver_name"],
            "served_by": sol["served_by"],
            "raw_reasoning": sol["raw_reasoning"] or "",
            "solution_steps": json.loads(sol["solution_steps_json"] or "[]"),
            "rationale": sol["rationale"] or "",
            "evidence_pages": json.loads(sol["evidence_pages_json"] or "[]"),
            "evidence_refs": json.loads(sol["evidence_refs_json"] or "[]"),
            "versions": version_info(),
        }
    finally:
        conn.close()


@app.get("/v1/exam-sessions/{session_id}")
def get_exam_session(session_id: int) -> dict:
    conn = db.connect()
    try:
        session = _exam_session_or_404(conn, session_id)
        rows = conn.execute(
            "SELECT id, question_no, subject, read_conf, page_number "
            "FROM questions WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        # Same invariant as GET /solutions and finalize-reading: a locked
        # real-mode session must not leak solution-derived signals (answers
        # may exist from a temporary unlock). An empty solved set masks
        # solved_count and every questions[].solved below.
        locked = session["mode"] == "real" and not config.ALLOW_REAL_EXAM_SOLVE
        solved = (
            set()
            if locked
            else {
                r["question_id"]
                for r in conn.execute(
                    "SELECT DISTINCT question_id FROM solutions "
                    "WHERE question_id IN "
                    "(SELECT id FROM questions WHERE session_id = ?)",
                    (session_id,),
                ).fetchall()
            }
        )
        deck_ids = {r["id"] for r in _deck_question_rows(conn, session_id)}
        return {
            "session_id": session_id,
            "locked": locked,
            "mode": session["mode"],
            "voice_enabled": bool(session["voice_enabled"]),
            "status": session["status"],
            "phase": _session_phase(session),
            "document_id": session["document_id"],
            "exam_type": session["exam_type"],
            "answer_format": session["answer_format"],
            "current_page_index": session["current_page_index"],
            "total_pages": _exam_total_pages(conn, session["document_id"]),
            "has_audio": bool(session["audio_path"]),
            # Deck-scoped counts: compat rows (solve-current / uploads) are
            # listed under "questions" but are not review-deck problems.
            "problem_count": len(deck_ids),
            "solved_count": len(solved & deck_ids),
            "questions": [
                {
                    "question_id": r["id"],
                    "question_no": r["question_no"],
                    "subject": r["subject"],
                    "read_confidence": r["read_conf"],
                    "page_number": r["page_number"],
                    "solved": r["id"] in solved,
                }
                for r in rows
            ],
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Document exam — 3-phase flow (primary path), designed to minimize the time
# the camera is on (= the privacy LED is lit):
#
#   Phase 1 読取 (camera ON, LED lit — keep it short):
#     register every page once (POST /documents/{id}/pages + finalize), then
#     POST .../{id}/finalize-reading      declare 読取完了 (double tap) →
#                                         segment into problems, camera OFF
#   Phase 2 解答 (camera OFF): all problems solved in one batch
#     POST .../{id}/solutions             ingest the onboard AI's per-problem
#                                         answers (primary), or — with
#                                         ROKID_SOLVER=openai|gemini|claude —
#                                         finalize-reading solves server-side
#   Phase 3 閲覧 (camera OFF, LED off): per-problem review deck
#     GET  .../{id}/solutions             deck listing (solved flags)
#     GET  .../{id}/review?index=k        one problem, 答え+解法+根拠+注意 in
#                                         one stream (view_page teleprompter)
#
# Secondary/compat (solve-current型): navigate pages and solve the current one.
#   POST .../{id}/next-page | prev-page   move current_page_index (±1, clamped)
#   GET  .../{id}/current                 inspect current page (no solve)
#   POST .../{id}/solve-current           solve the current page's material
# Listening / mode (both flows):
#   POST .../{id}/audio                   listening: upload recording (+transcript)
#   POST .../{id}/mode                    toggle 筆記(written) ⇄ リスニング(listening)
# ---------------------------------------------------------------------------

def _exam_page_row(conn, doc_id: int, page_index: int):
    row = conn.execute(
        "SELECT * FROM pages WHERE document_id = ? AND page_index = ?",
        (doc_id, page_index),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"page_index {page_index} not found in document"
        )
    return row


def _require_document_exam(session):
    if not session["document_id"]:
        raise HTTPException(
            status_code=400,
            detail="this exam session is not bound to a document; "
            "create it with a document_id to use page-move型 endpoints",
        )
    return session["document_id"]


@app.post("/v1/exam-sessions/{session_id}/next-page")
def exam_next_page(session_id: int) -> dict:
    """Advance the current page index by 1 (two_finger_swipe_left). Clamped at last."""
    conn = db.connect()
    try:
        session = _exam_session_or_404(conn, session_id)
        doc_id = _require_document_exam(session)
        total = _exam_total_pages(conn, doc_id)
        new_idx = min(session["current_page_index"] + 1, max(total - 1, 0))
        conn.execute(
            "UPDATE exam_sessions SET current_page_index = ? WHERE id = ?",
            (new_idx, session_id),
        )
        conn.commit()
        return {
            "session_id": session_id,
            "current_page_index": new_idx,
            "total_pages": total,
            "at_last": new_idx >= total - 1,
            "nav_ack": build_page_nav_ack(
                page_index=new_idx, total_pages=total, direction="next"
            ),
        }
    finally:
        conn.close()


@app.post("/v1/exam-sessions/{session_id}/prev-page")
def exam_prev_page(session_id: int) -> dict:
    """Move the current page index back by 1 (two_finger_swipe_right). Clamped at 0."""
    conn = db.connect()
    try:
        session = _exam_session_or_404(conn, session_id)
        doc_id = _require_document_exam(session)
        total = _exam_total_pages(conn, doc_id)
        new_idx = max(session["current_page_index"] - 1, 0)
        conn.execute(
            "UPDATE exam_sessions SET current_page_index = ? WHERE id = ?",
            (new_idx, session_id),
        )
        conn.commit()
        return {
            "session_id": session_id,
            "current_page_index": new_idx,
            "total_pages": total,
            "at_first": new_idx == 0,
            "nav_ack": build_page_nav_ack(
                page_index=new_idx, total_pages=total, direction="prev"
            ),
        }
    finally:
        conn.close()


@app.get("/v1/exam-sessions/{session_id}/current")
def exam_current_page(session_id: int) -> dict:
    """Report the current page (subject + a short preview) without solving."""
    conn = db.connect()
    try:
        session = _exam_session_or_404(conn, session_id)
        doc_id = _require_document_exam(session)
        page_index = session["current_page_index"]
        page_row = _exam_page_row(conn, doc_id, page_index)
        material = _page_material(page_row["ocr_text"], page_row["vision_text"])
        subject, subj_conf = detect_subject(material or page_row["ocr_text"])
        preview = (material or page_row["summary"] or "").strip()[:80]
        return {
            "session_id": session_id,
            "document_id": doc_id,
            "current_page_index": page_index,
            "total_pages": _exam_total_pages(conn, doc_id),
            "exam_type": session["exam_type"],
            "answer_format": session["answer_format"],
            "subject": subject,
            "subject_confidence": subj_conf,
            "has_image": bool(page_row["image_path"]),
            "has_vision_text": bool(page_row["vision_text"] and page_row["vision_text"].strip()),
            "preview": preview,
        }
    finally:
        conn.close()


@app.post("/v1/exam-sessions/{session_id}/solve-current")
def exam_solve_current(session_id: int) -> dict:
    """Solve the CURRENT page — secondary/compat path (solve-current型).

    The primary path is the 3-phase flow (finalize-reading → POST/GET
    /solutions → GET /review), which keeps the camera off after one reading
    pass.  This endpoint remains for per-page interactive solving: the current
    page's recognized text (OCR + the on-glass AI's figure reading
    ``vision_text``) is the question; the **whole document** (every remembered
    page) is passed as context so a problem continuing across pages is read
    accurately. In listening mode the recorded audio's transcript is folded in.
    Persists a question + solution so the staged /view and /reasoning endpoints
    work exactly as for the upload flow. No image is sent or required.
    """
    conn = db.connect()
    try:
        session = _exam_session_or_404(conn, session_id)
        doc_id = _require_document_exam(session)
        page_index = session["current_page_index"]
        page_row = _exam_page_row(conn, doc_id, page_index)

        if session["mode"] == "real" and not config.ALLOW_REAL_EXAM_SOLVE:
            return {
                "session_id": session_id,
                "current_page_index": page_index,
                "locked": True,
                "glasses_view": build_locked_view(),
                "versions": version_info(),
            }

        # Current page = the question; whole document = context (page-spanning).
        material = _page_material(page_row["ocr_text"], page_row["vision_text"])
        subject, subj_conf = detect_subject(material or page_row["ocr_text"])
        doc_material = _document_material(conn, doc_id, page_index)
        retrieved = retrieve_context(conn, material or page_row["ocr_text"])
        context = _exam_prompt_context(session, doc_material, retrieved["context"])

        # Persist a question row for this page so /view and /reasoning work.
        page_number = page_index + 1
        qcur = conn.execute(
            """INSERT INTO questions
               (session_id, question_no, body_text, choices_json, subject,
                read_conf, page_number, image_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                None,
                material,
                json.dumps([], ensure_ascii=False),
                subject,
                round(min(1.0, 0.5 + subj_conf / 2), 3) if normalize_ocr_text(material) else 0.0,
                page_number,
                page_row["image_path"],
            ),
        )
        question_id = qcur.lastrowid

        question = Question(
            body_text=material,
            subject=subject,
            context=context,
            image_path=page_row["image_path"],
        )
        result, solver = solve_with_fallback(question=question)
        served_by = result.extras.get("served_by", solver.name)
        evidence_pages, evidence_refs = _prepare_result_evidence(
            result,
            fallback_pages=retrieved["evidence_pages"],
            fallback_refs=retrieved["evidence_refs"],
        )

        conn.execute(
            """INSERT INTO solutions
               (question_id, solver_name, answer, solution_steps_json, rationale,
                cautions, answer_conf, rationale_conf, evidence_pages_json,
                evidence_refs_json, raw_reasoning, served_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                question_id,
                solver.name,
                result.answer,
                json.dumps(result.solution_steps, ensure_ascii=False),
                result.rationale,
                result.cautions,
                result.answer_confidence,
                result.rationale_confidence,
                json.dumps(evidence_pages),
                _evidence_refs_storage_value(result),
                result.raw_reasoning,
                served_by,
            ),
        )
        conn.commit()

        view = build_glasses_view(
            result,
            stage="answer",
            page_number=page_number,
            voice_enabled=bool(session["voice_enabled"]),
        )
        return {
            "session_id": session_id,
            "question_id": question_id,
            "document_id": doc_id,
            "current_page_index": page_index,
            "exam_type": session["exam_type"],
            "answer_format": session["answer_format"],
            "subject": result.subject or subject,
            "solver": solver.info(),
            "served_by": served_by,
            "locked": False,
            "glasses_view": view,
            "overlay": build_overlay(result, answer_box=None, page_number=page_number),
            "evidence": retrieved["hits"],
            "evidence_pages": result.evidence_pages,
            "evidence_refs": result.evidence_refs,
            "versions": version_info(),
        }
    finally:
        conn.close()


class ExamMode(BaseModel):
    exam_type: str


@app.post("/v1/exam-sessions/{session_id}/mode")
def exam_set_mode(session_id: int, payload: ExamMode) -> dict:
    """Switch 筆記(written) ⇄ リスニング(listening). Doable from glasses or phone."""
    if payload.exam_type not in _EXAM_TYPES:
        raise HTTPException(status_code=400, detail=f"exam_type must be one of {_EXAM_TYPES}")
    conn = db.connect()
    try:
        session = _exam_session_or_404(conn, session_id)
        conn.execute(
            "UPDATE exam_sessions SET exam_type = ? WHERE id = ?",
            (payload.exam_type, session_id),
        )
        conn.commit()
        return {
            "session_id": session_id,
            "exam_type": payload.exam_type,
            "answer_format": session["answer_format"],
            "mode_ack": {
                "lines": [
                    "モード切替",
                    "リスニング" if payload.exam_type == "listening" else "筆記",
                ],
                "ttl_sec": 1.5,
            },
        }
    finally:
        conn.close()


@app.post("/v1/exam-sessions/{session_id}/audio")
async def exam_upload_audio(
    session_id: int,
    audio: UploadFile | None = File(None),
    transcript: str | None = Form(None),
) -> dict:
    """Listening mode: record the audio on the spot and store its transcript.

    Saves the uploaded recording to data/audio/ and transcribes it via the
    configured ROKID_TRANSCRIBER (openai|gemini). With no transcriber (or on
    failure/offline) the client-provided ``transcript`` is stored as-is, so
    listening works without any ASR credential. Either ``audio`` or
    ``transcript`` must be supplied.
    """
    from .transcribe import transcribe_audio

    if (audio is None or not getattr(audio, "filename", None)) and not (
        transcript and transcript.strip()
    ):
        raise HTTPException(status_code=400, detail="provide audio and/or transcript")
    pending_audio_path: Path | None = None
    audio_persisted = False
    conn = db.connect()
    try:
        session = _exam_session_or_404(conn, session_id)

        old_audio_path: str | None = session["audio_path"]
        audio_path: str | None = None
        if audio is not None and getattr(audio, "filename", None):
            raw = await _read_upload_limited(audio)
            ext = _safe_audio_suffix(audio)
            fname = f"audio_{session_id}_{uuid.uuid4().hex[:8]}{ext}"
            config.AUDIO_DIR.mkdir(parents=True, exist_ok=True)
            fpath = config.AUDIO_DIR / fname
            pending_audio_path = fpath
            fpath.write_bytes(raw)
            audio_path = str(fpath)

        text = transcribe_audio(audio_path, provided_transcript=transcript)
        conn.execute(
            "UPDATE exam_sessions SET audio_path = ?, transcript = ? WHERE id = ?",
            (audio_path, text, session_id),
        )
        conn.commit()
        audio_persisted = pending_audio_path is not None
        if old_audio_path and old_audio_path != audio_path:
            # A new recording (or transcript-only replacement) supersedes the
            # old DB reference; remove the now-unreachable recording as well.
            _unlink_best_effort(old_audio_path)
        return {
            "session_id": session_id,
            "exam_type": session["exam_type"],
            "audio_stored": audio_path is not None,
            "transcript": text,
            "transcript_chars": len(text),
        }
    finally:
        conn.close()
        if pending_audio_path is not None and not audio_persisted:
            _unlink_best_effort(pending_audio_path)


# --- 3-phase flow endpoints: finalize-reading / solutions ingest / review ----

def _deck_question_rows(conn, session_id: int) -> list:
    """The session's review-deck problem rows, in insertion (document) order.

    Deck membership is marked in ``structure_json``: finalize-reading rows
    carry ``{"page_indexes": [...], "deck": true}`` and ingest-created rows
    ``{"deck": true}``.  Compat rows — solve-current (structure_json NULL) and
    the upload flow (a JSON *list* of headings) — are excluded so per-page or
    uploaded questions never pollute the deck counts/navigation.
    """
    rows = conn.execute(
        # Insertion order (= segmentation/document order), deliberately NOT
        # re-sorted by page: a problem's deck index must stay stable once
        # assigned, or problem_index addressing would silently shift when the
        # onboard ingest appends a problem the heuristic missed. Late
        # additions therefore go to the end of the deck.
        "SELECT * FROM questions WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    deck_rows = []
    for r in rows:
        try:
            meta = json.loads(r["structure_json"] or "null")
        except (ValueError, TypeError):
            meta = None
        if isinstance(meta, dict) and (meta.get("deck") or "page_indexes" in meta):
            deck_rows.append(r)
    return deck_rows


def _latest_solution_row(conn, question_id: int):
    return conn.execute(
        "SELECT * FROM solutions WHERE question_id = ? ORDER BY id DESC LIMIT 1",
        (question_id,),
    ).fetchone()


def _exam_deck(conn, session_id: int) -> list[dict]:
    """Review-deck listing: deck problems in document order + solved state.

    Deck index k = the k-th deck row (see _deck_question_rows); the latest
    solutions row per question wins (re-ingest appends a newer row).
    """
    deck: list[dict] = []
    for i, r in enumerate(_deck_question_rows(conn, session_id)):
        sol = _latest_solution_row(conn, r["id"])
        deck.append(
            {
                "index": i,
                "question_id": r["id"],
                "problem_no": r["question_no"],
                "subject": r["subject"],
                "page_number": r["page_number"],
                "solved": sol is not None,
                "served_by": sol["served_by"] if sol else None,
                "answer_confidence": sol["answer_conf"] if sol else None,
            }
        )
    return deck


def _review_operations() -> dict:
    """The review-phase gesture bindings (same source as the view payloads)."""
    return dict(REVIEW_OPERATIONS)


def _question_evidence_refs(conn, question_id: int) -> list[dict]:
    """Structured default evidence for a deck problem's document/page span."""
    row = conn.execute(
        "SELECT q.structure_json, q.page_number, s.document_id "
        "FROM questions q JOIN exam_sessions s ON s.id = q.session_id "
        "WHERE q.id = ?",
        (question_id,),
    ).fetchone()
    if row is None or row["document_id"] is None:
        return []
    try:
        span = json.loads(row["structure_json"] or "{}").get("page_indexes") or []
    except (ValueError, TypeError):
        span = []
    if span:
        pages = [i + 1 for i in span]
    else:
        pages = [row["page_number"]] if row["page_number"] else []
    return [
        {"document_id": row["document_id"], "page_number": page}
        for page in pages
    ]


def _question_evidence_pages(conn, question_id: int) -> list[int]:
    """Backward-compatible 1-based page-number list."""
    return [r["page_number"] for r in _question_evidence_refs(conn, question_id)]


_SERVER_SOLVE_CLAIM_TTL = "-15 minutes"
_CLAIM_HEARTBEAT_SECONDS = 30.0


@contextmanager
def _claim_heartbeat(renew, *, name: str):
    """Renew a SQLite claim while its optional paid provider call is live."""
    stopped = threading.Event()

    def _run() -> None:
        while not stopped.wait(_CLAIM_HEARTBEAT_SECONDS):
            try:
                if not renew():
                    return
            except sqlite3.OperationalError:
                # A transient SQLite writer lock is safe to retry on the next
                # heartbeat; one missed renewal is far shorter than the TTL.
                continue

    thread = threading.Thread(target=_run, name=name, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=1.0)


def _renew_server_solve_claim(question_id: int, owner_token: str) -> bool:
    heartbeat_conn = db.connect()
    try:
        cur = heartbeat_conn.execute(
            "UPDATE solution_claims SET claimed_at = datetime('now') "
            "WHERE question_id = ? AND owner_token = ?",
            (question_id, owner_token),
        )
        heartbeat_conn.commit()
        return cur.rowcount == 1
    finally:
        heartbeat_conn.close()


def _claim_server_solve(conn, question_id: int) -> str | None:
    """Atomically claim one paid server solve, reclaiming a stale crash row.

    Returns a per-claim owner token on success, else None. The token lets the
    winner release only ITS OWN claim: once the TTL reclaim below hands the slot
    to a retry, an original request that is still legitimately running must not
    delete the retry's fresh claim when it finally finishes (release-by-token,
    not by question_id).
    """
    conn.execute(
        "DELETE FROM solution_claims "
        "WHERE question_id = ? AND (owner_token IS NULL "
        "OR claimed_at < datetime('now', ?))",
        (question_id, _SERVER_SOLVE_CLAIM_TTL),
    )
    token = uuid.uuid4().hex
    cur = conn.execute(
        "INSERT OR IGNORE INTO solution_claims (question_id, owner_token) "
        "SELECT ?, ? WHERE NOT EXISTS "
        "(SELECT 1 FROM solutions WHERE question_id = ?)",
        (question_id, token, question_id),
    )
    conn.commit()  # publish the claim before any slow/paid network request
    return token if cur.rowcount == 1 else None


def _release_server_solve(conn, question_id: int, owner_token: str) -> None:
    """Release only this owner's claim (a TTL reclaim may have reassigned it)."""
    conn.execute(
        "DELETE FROM solution_claims WHERE question_id = ? AND owner_token = ?",
        (question_id, owner_token),
    )
    conn.commit()


@app.post("/v1/exam-sessions/{session_id}/finalize-reading")
def exam_finalize_reading(session_id: int) -> dict:
    """Declare 読取完了 (finish_reading = double tap): the reading phase is over.

    From here the camera stays closed, so the privacy LED is dark for the
    whole answer and review phases.  The document is segmented into problems
    (segment_problems over every remembered page, so page-spanning problems
    stay whole) and one questions row is created per problem — the review
    deck.  If a non-local server solver is configured (ROKID_SOLVER=
    openai|gemini|claude), every problem is solved in one synchronous batch
    right away; otherwise the deck waits for the onboard AI's answers via
    POST /solutions (primary path).

    Idempotent AND race-safe: the reading→reviewing transition is claimed
    with a guarded UPDATE (serialized by SQLite's write lock), so a gesture
    double-fire — even two near-simultaneous requests — segments exactly
    once.  Server-side solving is RESUMABLE: every call solves whichever deck
    problems still lack a solution, so a transient failure mid-batch can be
    retried by double-tapping again.  mode=real: the segmentation and phase
    transition still happen (they reveal nothing), but server-side solving is
    skipped and the response carries locked=true.

    0 problems (nothing readable on any page): the claim is reverted in the
    same transaction and the session stays in the reading phase (response
    status "reading"), so the ack's 再読取 guidance is actionable — replace
    the badly-read pages via POST /pages and double-tap again.
    """
    conn = db.connect()
    try:
        session = _exam_session_or_404(conn, session_id)
        doc_id = _require_document_exam(session)
        total_pages = _exam_total_pages(conn, doc_id)
        locked = session["mode"] == "real" and not config.ALLOW_REAL_EXAM_SOLVE

        # Atomically claim the transition: the guarded UPDATE takes SQLite's
        # write lock, so of two racing requests exactly one sees rowcount==1
        # and segments; the other lands in the already-finalized branch.
        # A reviewing session WITHOUT deck rows is claimable again: that is
        # the recoverable 0-problem state (nothing was segmented), including
        # legacy DBs that got stuck there before the revert below existed.
        # The deck predicate must mirror _deck_question_rows: legacy deck rows
        # carry only {"page_indexes": ...} (no "deck" key) and still count —
        # missing them here would re-segment a finalized session's deck.
        claim = conn.execute(
            "UPDATE exam_sessions SET status = 'reviewing' "
            "WHERE id = ? AND (status != 'reviewing' "
            "  OR NOT EXISTS (SELECT 1 FROM questions q "
            "                 WHERE q.session_id = exam_sessions.id "
            "                 AND (q.structure_json LIKE '%\"deck\"%' "
            "                      OR q.structure_json LIKE '%\"page_indexes\"%')))",
            (session_id,),
        )
        already_finalized = claim.rowcount == 0
        reverted = False

        if already_finalized:
            conn.rollback()  # nothing claimed; end the implicit transaction
        else:
            # Segment and insert the deck in the SAME transaction as the claim.
            page_rows = conn.execute(
                "SELECT page_index, ocr_text, vision_text FROM pages "
                "WHERE document_id = ? ORDER BY page_index",
                (doc_id,),
            ).fetchall()
            problems = segment_problems(
                [
                    # Body drives boundaries; the figure reading is appended
                    # to the owning problem so its labels don't split it.
                    (r["page_index"], r["ocr_text"] or "", r["vision_text"])
                    for r in page_rows
                ]
            )
            if not problems:
                # Nothing recognizable was read: give the claim back in the
                # SAME transaction so the session stays in the reading phase —
                # the ack's 再読取 guidance is then actually possible (re-scan
                # the pages, double-tap again). Racing double-fires serialize
                # on the write lock and revert identically (idempotent).
                conn.execute(
                    "UPDATE exam_sessions SET status = 'open' WHERE id = ?",
                    (session_id,),
                )
                reverted = True
            for prob in problems:
                subject, subj_conf = detect_subject(prob.body_text)
                primary_page = conn.execute(
                    "SELECT image_path FROM pages "
                    "WHERE document_id = ? AND page_index = ?",
                    (doc_id, prob.start_page_index),
                ).fetchone()
                primary_image_path = (
                    primary_page["image_path"] if primary_page is not None else None
                )
                conn.execute(
                    """INSERT INTO questions
                       (session_id, question_no, body_text, choices_json, subject,
                        read_conf, page_number, structure_json, image_path)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        session_id,
                        # The boundary-less fallback problem gets a stable
                        # synthesized id so the onboard ingest can address it
                        # (a NULL problem_no would be unreachable by name).
                        prob.question_no or "全体",
                        prob.body_text,
                        json.dumps(prob.choices, ensure_ascii=False),
                        subject,
                        round(min(1.0, 0.5 + subj_conf / 2), 3)
                        if normalize_ocr_text(prob.body_text)
                        else 0.0,
                        prob.start_page_index + 1,
                        json.dumps(
                            {"page_indexes": prob.page_indexes, "deck": True}
                        ),
                        primary_image_path,
                    ),
                )
            conn.commit()

        # Optional server-side solve-all — resumable: solve every deck problem
        # that has no solution yet (covers both the first call and retries
        # after a mid-batch failure). Deliberately skipped when ROKID_SOLVER is
        # unset or 'local': the placeholder does not really solve, and junk
        # rows would mark problems "solved" and shadow the onboard ingest.
        server_solved = 0
        solver_env = (os.environ.get("ROKID_SOLVER") or "").strip()
        if not locked and solver_env and solver_env != "local":
            for row in _deck_question_rows(conn, session_id):
                if _latest_solution_row(conn, row["id"]) is not None:
                    continue
                claim_token = _claim_server_solve(conn, row["id"])
                if not claim_token:
                    continue
                try:
                    with _claim_heartbeat(
                        lambda: _renew_server_solve_claim(row["id"], claim_token),
                        name=f"solve-claim-{row['id']}",
                    ):
                        start_index = (row["page_number"] or 1) - 1
                        doc_material = _document_material(conn, doc_id, start_index)
                        retrieved = retrieve_context(conn, row["body_text"])
                        context = _exam_prompt_context(
                            session, doc_material, retrieved["context"]
                        )
                        question = Question(
                            question_no=row["question_no"],
                            body_text=row["body_text"],
                            choices=json.loads(row["choices_json"] or "[]"),
                            subject=row["subject"],
                            context=context,
                            image_path=row["image_path"],
                        )
                        result, solver = solve_with_fallback(question=question)
                    served_by = result.extras.get("served_by", solver.name)
                    if served_by == "local":
                        # A failed/missing cloud adapter fell back to the
                        # placeholder. Release the claim for a future retry,
                        # but never mark placeholder output as solved.
                        continue
                    evidence_pages, evidence_refs = _prepare_result_evidence(
                        result,
                        fallback_pages=_question_evidence_pages(conn, row["id"]),
                        fallback_refs=_question_evidence_refs(conn, row["id"]),
                    )
                    # Onboard ingest may answer while the paid call is in
                    # flight. The conditional insert preserves that earlier
                    # answer; the DB claim above already prevented a second
                    # server request (and its duplicate charge).
                    cur = conn.execute(
                        """INSERT INTO solutions
                           (question_id, solver_name, answer, solution_steps_json,
                            rationale, cautions, answer_conf, rationale_conf,
                            evidence_pages_json, evidence_refs_json,
                            raw_reasoning, served_by)
                           SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                           WHERE NOT EXISTS
                               (SELECT 1 FROM solutions WHERE question_id = ?)""",
                        (
                            row["id"],
                            solver.name,
                            result.answer,
                            json.dumps(result.solution_steps, ensure_ascii=False),
                            result.rationale,
                            result.cautions,
                            result.answer_confidence,
                            result.rationale_confidence,
                            json.dumps(evidence_pages),
                            _evidence_refs_storage_value(result),
                            result.raw_reasoning,
                            served_by,
                            row["id"],
                        ),
                    )
                    conn.commit()
                    if cur.rowcount:
                        server_solved += 1
                finally:
                    _release_server_solve(conn, row["id"], claim_token)

        deck = _exam_deck(conn, session_id)
        if locked:
            # Consistent with GET /solutions: a locked session must not leak
            # solution-derived fields (e.g. answers stored while the unlock
            # flag was temporarily on).
            deck = [
                {**d, "solved": False, "served_by": None, "answer_confidence": None}
                for d in deck
            ]
        body = {
            "session_id": session_id,
            # 0 problems segmented -> the claim was reverted and the session
            # is still in the reading phase (re-scan + finalize again works).
            "status": "reading" if reverted else "reviewing",
            "already_finalized": already_finalized,
            "document_id": doc_id,
            "total_pages": total_pages,
            "problem_count": len(deck),
            "server_solved": server_solved,
            "locked": locked,
            "problems": deck,
            # The camera is off either way at this instant (the double tap
            # closed it); after a revert it only re-opens on the user's next
            # two-finger tap (capture_read), keeping LED time minimal.
            "camera": {"expected_state": "off", "privacy_led": "off"},
            # Reverted -> the client must keep READING controls (double_tap =
            # finish_reading again), not the review bindings where the same
            # gesture means close — that would strand the re-scan loop.
            "operations": dict(READING_OPERATIONS) if reverted else _review_operations(),
            "versions": version_info(),
        }
        if not already_finalized:
            body["reading_ack"] = build_reading_done_ack(len(deck), total_pages)
        return body
    finally:
        conn.close()


class IngestSolution(BaseModel):
    problem_no: str
    answer: str
    subject: str | None = None
    solution_steps: list[str] = []
    rationale: str = ""
    cautions: str = ""
    # Unknown confidence defaults to the middle tier (★★☆ on the HUD).
    answer_confidence: float = 0.5
    page_number: int | None = None
    # Optional deck index (GET /solutions "index"). Takes precedence over
    # problem_no matching — the unambiguous way to address problems whose
    # base numbers repeat across 大問 (the server disambiguates those as
    # 問1(2), which the onboard AI cannot know).
    problem_index: int | None = None


class IngestSolutions(BaseModel):
    solutions: list[IngestSolution]
    served_by: str = "onboard"


# layout.segment_problems disambiguates repeated numbers as 問1(2), 問1(3)…;
# stripping that suffix recovers the base name the onboard AI actually sees.
_PROBLEM_NO_SUFFIX_RE = re.compile(r"\(\d+\)$")


def _base_problem_no(no: str | None) -> str:
    return _PROBLEM_NO_SUFFIX_RE.sub("", no or "")


@app.post("/v1/exam-sessions/{session_id}/solutions")
def exam_ingest_solutions(session_id: int, payload: IngestSolutions) -> dict:
    """Ingest the onboard AI's per-problem answers (primary path, phase 2).

    The glasses' onboard GPT solves every problem with the whole document in
    view; this endpoint stores its results as solutions rows (served_by=
    "onboard") addressed by deck index (``problem_index``, unambiguous) or by
    ``problem_no`` as listed by GET /solutions.  An unknown problem_no appends
    a new problem to the deck (the heuristic missed it, the onboard AI found
    it).  Re-ingesting a problem adds a newer solutions row — latest wins.
    Validation is all-or-nothing.  mode=real: nothing is stored (locked
    response).

    problem_no guardrails (the onboard AI cannot know server-synthesized
    names): a name whose base collides with several disambiguated deck rows
    (問1 vs 問1/問1(2)) is a 400 pointing at problem_index — silently routing
    both answers onto the first 問1 would misplace one. And a SINGLE-item
    payload against a SINGLE-problem deck (e.g. the synthesized 全体) maps to
    that problem instead of appending a duplicate; multi-item payloads keep
    the append semantics (collapsing them onto one problem would destroy all
    but the last answer via latest-wins).
    """
    conn = db.connect()
    try:
        session = _exam_session_or_404(conn, session_id)
        _require_document_exam(session)
        if _session_phase(session) == "reading":
            raise HTTPException(status_code=409, detail="call finalize-reading first")
        if session["mode"] == "real" and not config.ALLOW_REAL_EXAM_SOLVE:
            return {
                "session_id": session_id,
                "locked": True,
                "ingested": 0,
                "glasses_view": build_locked_view(),
                "versions": version_info(),
            }
        deck_rows = _deck_question_rows(conn, session_id)
        if not payload.solutions:
            raise HTTPException(status_code=400, detail="solutions must be non-empty")
        for item in payload.solutions:
            if not item.answer.strip():
                raise HTTPException(
                    status_code=400,
                    detail=f"empty answer for problem {item.problem_no!r}",
                )
            if item.problem_index is not None and not (
                0 <= item.problem_index < len(deck_rows)
            ):
                raise HTTPException(
                    status_code=400,
                    detail=f"problem_index {item.problem_index} out of range "
                    f"(deck has {len(deck_rows)} problems)",
                )
            if item.problem_index is None:
                hits = [
                    i
                    for i, r in enumerate(deck_rows)
                    if _base_problem_no(r["question_no"]) == item.problem_no
                ]
                if len(hits) > 1:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"problem_no {item.problem_no!r} matches multiple deck "
                            f"problems (deck indexes {hits}); address it with "
                            "problem_index (see GET /solutions)"
                        ),
                    )

        created = 0
        created_ids: dict[str, int] = {}  # problem_no -> question_id (this payload)
        for item in payload.solutions:
            if item.problem_index is not None:
                question_id = deck_rows[item.problem_index]["id"]
            else:
                row = next(
                    (r for r in deck_rows if r["question_no"] == item.problem_no),
                    None,
                )
                if (
                    row is None
                    and len(deck_rows) == 1
                    and len(payload.solutions) == 1
                ):
                    # Single-problem deck (e.g. the synthesized 全体, unknowable
                    # to the onboard AI): a lone answer under any name means
                    # this problem. Single-item payloads only — see docstring.
                    row = deck_rows[0]
                question_id = row["id"] if row else created_ids.get(item.problem_no)
            if question_id is None:
                qcur = conn.execute(
                    """INSERT INTO questions
                       (session_id, question_no, body_text, choices_json,
                        subject, read_conf, page_number, structure_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        session_id,
                        item.problem_no,
                        "",
                        json.dumps([], ensure_ascii=False),
                        item.subject,
                        0.0,
                        item.page_number,
                        json.dumps({"deck": True}),
                    ),
                )
                question_id = qcur.lastrowid
                created_ids[item.problem_no] = question_id
                created += 1
            evidence_refs = (
                [
                    {
                        "document_id": session["document_id"],
                        "page_number": item.page_number,
                    }
                ]
                if item.page_number and session["document_id"] is not None
                else _question_evidence_refs(conn, question_id)
            )
            evidence = [ref["page_number"] for ref in evidence_refs]
            # Clamp: an out-of-scale confidence (e.g. a 0-100 client) must not
            # inflate the deck values or the HUD ★ symbols.
            confidence = clamp01(item.answer_confidence, default=0.5)
            conn.execute(
                """INSERT INTO solutions
                   (question_id, solver_name, answer, solution_steps_json,
                    rationale, cautions, answer_conf, rationale_conf,
                    evidence_pages_json, evidence_refs_json, raw_reasoning,
                    served_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    question_id,
                    "onboard",
                    item.answer.strip(),
                    json.dumps(item.solution_steps, ensure_ascii=False),
                    item.rationale,
                    item.cautions,
                    confidence,
                    confidence,
                    json.dumps(evidence),
                    json.dumps(evidence_refs),
                    "",
                    payload.served_by,
                ),
            )
        conn.commit()

        deck = _exam_deck(conn, session_id)
        solved_count = sum(1 for d in deck if d["solved"])
        return {
            "session_id": session_id,
            "ingested": len(payload.solutions),
            "created_problems": created,
            "problem_count": len(deck),
            "solved_count": solved_count,
            "deck": deck,
            "locked": False,
            "ingest_ack": {
                "lines": [
                    "解答受信",
                    f"{solved_count}/{len(deck)}問 解答済",
                    "横スワイプで閲覧",
                ],
                "ttl_sec": 2,
            },
            "versions": version_info(),
        }
    finally:
        conn.close()


@app.get("/v1/exam-sessions/{session_id}/solutions")
def exam_list_solutions(session_id: int) -> dict:
    """Review-deck listing (phase 3 閲覧). Camera off, LED off, no paper needed.

    Always 200: during the reading phase it returns an empty deck with
    status="reading" so a client can poll for readiness.
    """
    conn = db.connect()
    try:
        session = _exam_session_or_404(conn, session_id)
        if session["mode"] == "real" and not config.ALLOW_REAL_EXAM_SOLVE:
            return {
                "session_id": session_id,
                "locked": True,
                "deck": [],
                "glasses_view": build_locked_view(),
                "versions": version_info(),
            }
        deck = _exam_deck(conn, session_id)
        return {
            "session_id": session_id,
            "status": _session_phase(session),
            "document_id": session["document_id"],
            "locked": False,
            "problem_count": len(deck),
            "solved_count": sum(1 for d in deck if d["solved"]),
            "deck": deck,
            "operations": _review_operations(),
            "versions": version_info(),
        }
    finally:
        conn.close()


@app.get("/v1/exam-sessions/{session_id}/review")
def exam_review(session_id: int, index: int = 0, view_page: int = 0) -> dict:
    """One problem of the review deck (phase 3 閲覧): 一括表示 HUD.

    答え+解法+根拠+注意 come merged in one teleprompter stream (no stages);
    scroll with two-finger vertical swipes (view_page), move between problems
    with two-finger horizontal swipes (index).  Both parameters clamp.  An
    unsolved problem renders a 未解答 placeholder (not an error) so the deck
    is fully navigable before/while the onboard answers arrive.
    """
    conn = db.connect()
    try:
        session = _exam_session_or_404(conn, session_id)
        if _session_phase(session) == "reading":
            # A document-less (upload/solve-current型) session can never leave
            # the reading phase, so give it the actionable "bind a document"
            # 400 instead of an unsatisfiable "finalize first" 409.
            if not session["document_id"]:
                _require_document_exam(session)
            raise HTTPException(status_code=409, detail="call finalize-reading first")
        if session["mode"] == "real" and not config.ALLOW_REAL_EXAM_SOLVE:
            return {
                "session_id": session_id,
                "locked": True,
                "glasses_view": build_locked_view(),
                "versions": version_info(),
            }
        rows = _deck_question_rows(conn, session_id)
        if not rows:
            raise HTTPException(
                status_code=409,
                detail="no problems were detected in this document; "
                "re-run the reading phase (再読取)",
            )
        index = max(0, min(index, len(rows) - 1))
        qrow = rows[index]
        srow = _latest_solution_row(conn, qrow["id"])
        solution = _solution_from_row(srow, qrow) if srow else None
        view = build_review_view(
            solution,
            index=index,
            problem_count=len(rows),
            problem_no=qrow["question_no"],
            page_number=qrow["page_number"],
            view_page=view_page,
            solved=srow is not None,
            voice_enabled=bool(session["voice_enabled"]),
        )
        return {
            "session_id": session_id,
            "index": index,
            "problem_count": len(rows),
            "question_id": qrow["id"],
            "problem_no": qrow["question_no"],
            "subject": qrow["subject"],
            "page_number": qrow["page_number"],
            "solved": srow is not None,
            "served_by": srow["served_by"] if srow else None,
            "evidence_pages": solution.evidence_pages if solution else [],
            "evidence_refs": solution.evidence_refs if solution else [],
            "locked": False,
            "glasses_view": view,
            "versions": version_info(),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Explain-sessions: scan-free live document explanation
#
# Design principle: NO camera image is sent during explain-sessions.
# The glasses user navigates by button only; the server tracks which page
# is currently being viewed via current_page_index.
#
# UX flow (button-only, silent, no-camera, glasses-standalone):
#   1. POST /v1/explain-sessions           -> create, status=ready, page=0
#   2. GET  .../{id}/explain               -> explanation for current page
#      POST .../{id}/next-page             -> advance page counter (+1)
#      POST .../{id}/prev-page             -> go back one page (-1)
#      GET  .../{id}/explain?stage=detail  -> detail stage for same page
#      GET  .../{id}/explain?view_page=1   -> teleprompter next slice
#   3. GET  .../{id}/history               -> viewed page list
# ---------------------------------------------------------------------------

class CreateExplainSession(BaseModel):
    document_id: int
    voice_enabled: bool = False


def _explain_session_or_404(conn, session_id: int):
    return _row_or_404(conn, "explain_sessions", session_id, "explain session not found")


def _explain_total_pages(conn, doc_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM pages WHERE document_id = ?", (doc_id,)
    ).fetchone()[0]


@app.post("/v1/explain-sessions", status_code=201)
def create_explain_session(payload: CreateExplainSession) -> dict:
    """Create an explain session bound to a finalized document.

    No camera image is required at any point in this session.
    The session starts immediately in 'ready' status at page 0.
    Use POST /next-page and /prev-page to navigate; GET /explain to view.
    """
    conn = db.connect()
    try:
        doc = _doc_or_404(conn, payload.document_id)
        total_pages = _explain_total_pages(conn, payload.document_id)
        if doc["status"] != "ready" or total_pages < 1:
            raise HTTPException(
                status_code=400,
                detail="document must be finalized with >=1 page "
                "(POST /v1/documents/{id}/finalize) before explanation",
            )
        _require_dense_page_indexes(conn, payload.document_id)
        cur = conn.execute(
            "INSERT INTO explain_sessions (document_id, voice_enabled) VALUES (?, ?)",
            (payload.document_id, int(payload.voice_enabled)),
        )
        conn.commit()
        return {
            "session_id": cur.lastrowid,
            "document_id": payload.document_id,
            "voice_enabled": payload.voice_enabled,
            "status": "ready",
            "current_page_index": 0,
            "total_pages": total_pages,
            "operations": OPERATION_CONTRACT,
            "api_version": version_info()["api_version"],
        }
    finally:
        conn.close()


@app.post("/v1/explain-sessions/{session_id}/next-page")
def explain_next_page(session_id: int) -> dict:
    """Advance the current page index by 1.

    Triggered by the user pressing the 'next page' button (two_finger_swipe_left /
    KEYCODE_DPAD_UP) on the glasses.  Clamped at the last page.
    Returns the new current_page_index and a brief HUD ack.
    """
    conn = db.connect()
    try:
        session = _explain_session_or_404(conn, session_id)
        total = _explain_total_pages(conn, session["document_id"])
        new_idx = min(session["current_page_index"] + 1, max(total - 1, 0))
        conn.execute(
            "UPDATE explain_sessions SET current_page_index = ? WHERE id = ?",
            (new_idx, session_id),
        )
        conn.commit()
        ack = build_page_nav_ack(page_index=new_idx, total_pages=total, direction="next")
        return {
            "session_id": session_id,
            "current_page_index": new_idx,
            "total_pages": total,
            "at_last": new_idx >= total - 1,
            "nav_ack": ack,
        }
    finally:
        conn.close()


@app.post("/v1/explain-sessions/{session_id}/prev-page")
def explain_prev_page(session_id: int) -> dict:
    """Move the current page index back by 1.

    Triggered by two_finger_swipe_right / KEYCODE_DPAD_RIGHT (unverified).  Clamped at page 0.
    """
    conn = db.connect()
    try:
        session = _explain_session_or_404(conn, session_id)
        total = _explain_total_pages(conn, session["document_id"])
        new_idx = max(session["current_page_index"] - 1, 0)
        conn.execute(
            "UPDATE explain_sessions SET current_page_index = ? WHERE id = ?",
            (new_idx, session_id),
        )
        conn.commit()
        ack = build_page_nav_ack(page_index=new_idx, total_pages=total, direction="prev")
        return {
            "session_id": session_id,
            "current_page_index": new_idx,
            "total_pages": total,
            "at_first": new_idx == 0,
            "nav_ack": ack,
        }
    finally:
        conn.close()


def _page_signature(page_row) -> str:
    """Content fingerprint of the page material an explanation is built from.

    A finalized page can be re-read (POST /pages replaces it in place, keeping
    the same page_index) while an explain session is live. The visit cache keys
    on page_index alone, so without this a corrected page keeps serving the
    stale provider result and evidence until the user navigates away and back.
    Hashing the exact inputs the explainer consumes — body OCR, figure reading,
    and summary — refreshes the cache only when the page actually changed, while
    stage/scroll churn on unchanged content still reuses the one stored result.
    """
    payload = "\x00".join(
        (
            page_row["ocr_text"] or "",
            page_row["vision_text"] or "",
            page_row["summary"] or "",
        )
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


_EXPLAIN_CLAIM_TTL = "-15 minutes"
_EXPLAIN_WAIT_SECONDS = 30.0
_EXPLAIN_POLL_SECONDS = 0.05


def _find_explain_visit(
    conn,
    *,
    session_id: int,
    page_index: int,
    page_signature: str,
    after_id: int,
):
    return conn.execute(
        "SELECT * FROM explain_views WHERE session_id = ? AND page_index = ? "
        "AND page_signature = ? AND id > ? ORDER BY id DESC LIMIT 1",
        (session_id, page_index, page_signature, after_id),
    ).fetchone()


def _claim_explain(
    conn, *, session_id: int, page_index: int, page_signature: str
) -> str | None:
    # A crashed worker must not block this page forever.
    conn.execute(
        "DELETE FROM explain_claims WHERE session_id = ? AND page_index = ? "
        "AND page_signature = ? AND (owner_token IS NULL "
        "OR claimed_at < datetime('now', ?))",
        (session_id, page_index, page_signature, _EXPLAIN_CLAIM_TTL),
    )
    token = uuid.uuid4().hex
    cur = conn.execute(
        "INSERT OR IGNORE INTO explain_claims "
        "(session_id, page_index, page_signature, owner_token) "
        "VALUES (?, ?, ?, ?)",
        (session_id, page_index, page_signature, token),
    )
    # Publish ownership before an optional paid provider is invoked.
    conn.commit()
    return token if cur.rowcount == 1 else None


def _release_explain_claim(
    conn, *, session_id: int, page_index: int, page_signature: str,
    owner_token: str,
) -> None:
    conn.execute(
        "DELETE FROM explain_claims WHERE session_id = ? AND page_index = ? "
        "AND page_signature = ? AND owner_token = ?",
        (session_id, page_index, page_signature, owner_token),
    )
    # Also publishes the winner's explain_views row.
    conn.commit()


def _renew_explain_claim(
    session_id: int, page_index: int, page_signature: str, owner_token: str
) -> bool:
    heartbeat_conn = db.connect()
    try:
        cur = heartbeat_conn.execute(
            "UPDATE explain_claims SET claimed_at = datetime('now') "
            "WHERE session_id = ? AND page_index = ? AND page_signature = ? "
            "AND owner_token = ?",
            (session_id, page_index, page_signature, owner_token),
        )
        heartbeat_conn.commit()
        return cur.rowcount == 1
    finally:
        heartbeat_conn.close()


def _explain_wait_timeout() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="explanation is still being generated; retry shortly",
        headers={"Retry-After": "1"},
    )


def _acquire_or_wait_for_explain(
    conn,
    *,
    session_id: int,
    page_index: int,
    page_signature: str,
    after_id: int,
    timeout_seconds: float = _EXPLAIN_WAIT_SECONDS,
) -> tuple[str | None, object | None]:
    """Return an owner token, or wait for and return the winner's row."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        # Check the result before claiming. A winner may have committed and
        # released between the caller's cache snapshot and this function.
        row = _find_explain_visit(
            conn,
            session_id=session_id,
            page_index=page_index,
            page_signature=page_signature,
            after_id=after_id,
        )
        if row is not None:
            return None, row
        if time.monotonic() >= deadline:
            raise _explain_wait_timeout()

        claim_token = _claim_explain(
            conn,
            session_id=session_id,
            page_index=page_index,
            page_signature=page_signature,
        )
        if claim_token is not None:
            # Close the race where a previous winner committed/released after
            # our first result lookup but before this claim was acquired.
            row = _find_explain_visit(
                conn,
                session_id=session_id,
                page_index=page_index,
                page_signature=page_signature,
                after_id=after_id,
            )
            if row is not None:
                _release_explain_claim(
                    conn,
                    session_id=session_id,
                    page_index=page_index,
                    page_signature=page_signature,
                    owner_token=claim_token,
                )
                return None, row
            return claim_token, None

        while True:
            row = _find_explain_visit(
                conn,
                session_id=session_id,
                page_index=page_index,
                page_signature=page_signature,
                after_id=after_id,
            )
            if row is not None:
                return None, row
            if time.monotonic() >= deadline:
                raise _explain_wait_timeout()
            claim = conn.execute(
                "SELECT 1 FROM explain_claims WHERE session_id = ? "
                "AND page_index = ? AND page_signature = ?",
                (session_id, page_index, page_signature),
            ).fetchone()
            if claim is None:
                # The owner failed and released without a result. Loop and
                # compete for ownership so this request can retry the call.
                break
            time.sleep(_EXPLAIN_POLL_SECONDS)


def _explain_result_from_row(row) -> ExplainResult:
    extras = json.loads(row["result_extras_json"] or "{}")
    if not isinstance(extras, dict):
        extras = {}
    evidence_pages = json.loads(row["evidence_pages_json"] or "[]")
    if row["evidence_refs_json"] is None and evidence_pages:
        # Pre-1.11 explainers persisted raw retrieval page_index values. Mark
        # the display base without changing the legacy API v1 list itself.
        extras["_evidence_pages_base"] = 0
    return ExplainResult(
        lines=json.loads(row["hud_lines_json"] or "[]"),
        detail=row["detail"] or "",
        evidence_pages=evidence_pages,
        evidence_refs=json.loads(row["evidence_refs_json"] or "[]"),
        confidence=row["confidence"] if row["confidence"] is not None else 1.0,
        extras=extras,
    )


def _persist_explain_visit(
    conn,
    *,
    session_id: int,
    page_index: int,
    page_signature: str,
    last_id: int,
    result: ExplainResult,
    retrieved_hits: list,
    explainer_info: dict,
) -> tuple[bool, object]:
    """Record this page visit after the caller has claimed provider work.

    The committed explain_claim is acquired before the optional paid call, so
    normal concurrent callers wait for this row instead of invoking a second
    provider. The conditional INSERT remains defense-in-depth. ``id > last_id``
    scopes the guard to rows created after the caller's visit snapshot, so a
    genuine revisit still records a new history entry.

    Returns ``(inserted, row)``; when ``inserted`` is False, ``row`` is the
    canonical winner result to serve.
    """
    cur = conn.execute(
        """INSERT INTO explain_views
           (session_id, page_index, verdict, hud_lines_json, detail,
            evidence_pages_json, evidence_refs_json, context_hits_json,
            explainer_json, result_extras_json, confidence, page_signature)
           SELECT ?, ?, 'HIT', ?, ?, ?, ?, ?, ?, ?, ?, ?
           WHERE NOT EXISTS (
               SELECT 1 FROM explain_views
               WHERE session_id = ? AND page_index = ? AND page_signature = ?
                 AND id > ?
           )""",
        (
            session_id,
            page_index,
            json.dumps(result.lines, ensure_ascii=False),
            result.detail,
            json.dumps(result.evidence_pages),
            _evidence_refs_storage_value(result),
            json.dumps(retrieved_hits, ensure_ascii=False),
            json.dumps(explainer_info, ensure_ascii=False),
            json.dumps(result.extras, ensure_ascii=False, default=str),
            result.confidence,
            page_signature,
            session_id,
            page_index,
            page_signature,
            last_id,
        ),
    )
    inserted = cur.rowcount == 1
    row = conn.execute(
        "SELECT * FROM explain_views WHERE session_id = ? AND page_index = ? "
        "AND page_signature = ? AND id > ? ORDER BY id DESC LIMIT 1",
        (session_id, page_index, page_signature, last_id),
    ).fetchone()
    return inserted, row


@app.get("/v1/explain-sessions/{session_id}/explain")
def explain_page(
    session_id: int,
    stage: str = "overview",
    view_page: int = 0,
) -> dict:
    """Return the explanation HUD for the session's current page.

    No page_index parameter — the server uses current_page_index, which is
    updated by POST /next-page and /prev-page.

    Navigation within a page:
      - stage     : overview | detail | evidence  (long-press)
      - view_page : 0-based teleprompter slice    (two_finger_swipe_down / up)
    """
    if stage not in EXPLAIN_STAGES:
        raise HTTPException(
            status_code=400,
            detail=f"stage must be one of {EXPLAIN_STAGES}",
        )
    conn = db.connect()
    try:
        session = _explain_session_or_404(conn, session_id)
        doc_id = session["document_id"]
        page_index = session["current_page_index"]

        page_row = conn.execute(
            "SELECT * FROM pages WHERE document_id = ? AND page_index = ?",
            (doc_id, page_index),
        ).fetchone()
        if page_row is None:
            raise HTTPException(
                status_code=404,
                detail=f"page_index {page_index} not found in document",
            )

        total_doc_pages = _explain_total_pages(conn, doc_id)
        page_signature = _page_signature(page_row)

        # History records page VISITS, not every scroll. The saved result is
        # also the visit cache: stage/view_page churn must render the exact same
        # explanation without another paid/provider request. Returning after a
        # different page was explained creates a new visit and refreshes once.
        # The cache also keys on the page content signature, so re-reading (and
        # replacing) the page mid-session refreshes the explanation instead of
        # serving the pre-correction result. Legacy rows have no signature and
        # therefore refresh once on next view.
        last = conn.execute(
            "SELECT * FROM explain_views WHERE session_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        last_id = last["id"] if last is not None else 0
        cached = (
            last is not None
            and last["page_index"] == page_index
            and last["page_signature"] == page_signature
        )
        if cached:
            result = _explain_result_from_row(last)
            retrieved_hits = json.loads(last["context_hits_json"] or "[]")
            explainer_info = json.loads(last["explainer_json"] or "{}")
            if not explainer_info:
                # Legacy rows predate provider metadata. This only reads the
                # active adapter identity; it does not invoke the provider.
                explainer_info = get_explainer().info()
        else:
            # Include the on-glass AI's figure/image reading (vision_text) so
            # the explanation covers diagrams, not just the OCR text.
            page_material = _page_material(
                page_row["ocr_text"], page_row["vision_text"]
            )
            retrieved = retrieve_context(
                conn, page_material or page_row["ocr_text"]
            )
            req = ExplainRequest(
                page_index=page_index,
                page_ocr_text=page_material or page_row["ocr_text"],
                page_summary=page_row["summary"],
                context_pages=retrieved["hits"],
                document_title=conn.execute(
                    "SELECT title FROM documents WHERE id = ?", (doc_id,)
                ).fetchone()["title"],
            )
            retrieved_hits = retrieved["hits"]
            explainer_info = {}
            claim_token, won_row = _acquire_or_wait_for_explain(
                conn,
                session_id=session_id,
                page_index=page_index,
                page_signature=page_signature,
                after_id=last_id,
            )
            if claim_token is None:
                result = _explain_result_from_row(won_row)
                retrieved_hits = json.loads(won_row["context_hits_json"] or "[]")
                explainer_info = json.loads(won_row["explainer_json"] or "{}")
                if not explainer_info:
                    # Metadata-only adapter lookup; it does not call a provider.
                    explainer_info = get_explainer().info()
                cached = True
            else:
                try:
                    explainer = get_explainer()
                    with _claim_heartbeat(
                        lambda: _renew_explain_claim(
                            session_id, page_index, page_signature, claim_token
                        ),
                        name=f"explain-claim-{session_id}-{page_index}",
                    ):
                        result = explainer.explain(req)
                    _prepare_result_evidence(
                        result,
                        fallback_pages=retrieved["evidence_pages"],
                        fallback_refs=retrieved["evidence_refs"],
                    )
                    explainer_info = explainer.info()
                    inserted, won_row = _persist_explain_visit(
                        conn,
                        session_id=session_id,
                        page_index=page_index,
                        page_signature=page_signature,
                        last_id=last_id,
                        result=result,
                        retrieved_hits=retrieved_hits,
                        explainer_info=explainer_info,
                    )
                    if not inserted:
                        if won_row is None:
                            raise _explain_wait_timeout()
                        result = _explain_result_from_row(won_row)
                        retrieved_hits = json.loads(won_row["context_hits_json"] or "[]")
                        explainer_info = json.loads(won_row["explainer_json"] or "{}") or explainer_info
                        cached = True
                finally:
                    _release_explain_claim(
                        conn,
                        session_id=session_id,
                        page_index=page_index,
                        page_signature=page_signature,
                        owner_token=claim_token,
                    )
        if session["status"] == "ready":
            conn.execute(
                "UPDATE explain_sessions SET status = 'explaining' WHERE id = ?",
                (session_id,),
            )
        conn.commit()

        view = build_explain_view(
            result,
            stage=stage,
            view_page=view_page,
            page_index=page_index,
            total_doc_pages=total_doc_pages,
            voice_enabled=bool(session["voice_enabled"]),
        )
        return {
            "session_id": session_id,
            "document_id": doc_id,
            "current_page_index": page_index,
            "total_doc_pages": total_doc_pages,
            "explainer": explainer_info,
            "cached": cached,
            "glasses_view": view,
            "evidence": retrieved_hits,
            "evidence_pages": result.evidence_pages,
            "evidence_refs": result.evidence_refs,
            "versions": version_info(),
        }
    finally:
        conn.close()


@app.get("/v1/explain-sessions/{session_id}/history")
def explain_history(session_id: int) -> dict:
    """Return the list of pages viewed during this explain session."""
    conn = db.connect()
    try:
        session = _explain_session_or_404(conn, session_id)
        views = conn.execute(
            "SELECT page_index, verdict, hud_lines_json, detail, "
            "evidence_pages_json, evidence_refs_json, context_hits_json, "
            "explainer_json, result_extras_json, confidence, viewed_at "
            "FROM explain_views WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        return {
            "session_id": session_id,
            "document_id": session["document_id"],
            "status": session["status"],
            "voice_enabled": bool(session["voice_enabled"]),
            "current_page_index": session["current_page_index"],
            "explained_views": [
                {
                    "page_index": v["page_index"],
                    "verdict": v["verdict"],
                    "hud_lines": json.loads(v["hud_lines_json"] or "[]"),
                    "detail": v["detail"] or "",
                    "evidence_pages": json.loads(v["evidence_pages_json"] or "[]"),
                    "evidence_refs": json.loads(v["evidence_refs_json"] or "[]"),
                    "evidence": json.loads(v["context_hits_json"] or "[]"),
                    "explainer": json.loads(v["explainer_json"] or "{}"),
                    "result_extras": json.loads(v["result_extras_json"] or "{}"),
                    "confidence": v["confidence"],
                    "viewed_at": v["viewed_at"],
                }
                for v in views
            ],
            "versions": version_info(),
        }
    finally:
        conn.close()
