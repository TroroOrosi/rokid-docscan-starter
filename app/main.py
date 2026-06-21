"""Rokid DocScan MVP — FastAPI server.

Server-side only. Runs locally with SQLite + local filesystem, no Rokid
hardware and no external credentials. See docs/implementation-notes.md for
where real Rokid CXR integration plugs in.
"""

from __future__ import annotations

import io
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

from . import db
from .analyzers import get_analyzer
from .config import IMAGE_DIR, ensure_dirs
from .hud import build_hud
from .matching import Candidate, match, normalize_ocr_text, ocr_md5, phash_hex
from .version import APP_VERSION, HUD_CONTRACT_VERSION, version_info


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    db.init_db()
    yield


app = FastAPI(title="Rokid DocScan MVP", version=APP_VERSION, lifespan=lifespan)


# --- request/response models -----------------------------------------------

class CreateDocument(BaseModel):
    title: str
    capture_device: str | None = None
    # Optional client/device hints for diagnostics & future routing. Stored as
    # response echoes only; not persisted to keep the schema simple.
    client_version: str | None = None
    sdk_hint: str | None = None


# --- helpers ----------------------------------------------------------------

def _load_image(raw: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
        return img
    except (UnidentifiedImageError, OSError):
        raise HTTPException(status_code=400, detail="invalid image upload")


def _doc_or_404(conn, document_id: int):
    row = conn.execute(
        "SELECT * FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="document not found")
    return row


# --- endpoints --------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {"status": "ok", "versions": version_info()}


@app.get("/v1/version")
def get_version() -> dict:
    """Discovery endpoint: clients negotiate contracts against this block."""
    from .analyzers import list_analyzers

    return {**version_info(), "analyzers": list_analyzers()}


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
    image: UploadFile = File(...),
    ocr_text: str | None = Form(None),
) -> dict:
    conn = db.connect()
    try:
        _doc_or_404(conn, document_id)
        raw = await image.read()
        img = _load_image(raw)

        ph = phash_hex(img)
        omd5 = ocr_md5(ocr_text)
        # Placeholder when no OCR text: identify page by image content MD5.
        if omd5 is None:
            import hashlib

            omd5 = hashlib.md5(raw).hexdigest()

        fname = f"{document_id}_{page_index}_{uuid.uuid4().hex[:8]}.png"
        fpath: Path = IMAGE_DIR / fname
        img.convert("RGB").save(fpath, format="PNG")

        try:
            cur = conn.execute(
                """INSERT INTO pages
                   (document_id, page_index, image_path, phash, ocr_text, ocr_md5)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (document_id, page_index, str(fpath), ph, ocr_text, omd5),
            )
            conn.commit()
        except db.sqlite3.IntegrityError:
            raise HTTPException(
                status_code=409,
                detail=f"page_index {page_index} already exists",
            )

        return {
            "page_id": cur.lastrowid,
            "document_id": document_id,
            "page_index": page_index,
            "phash": ph,
            "ocr_md5": omd5,
            "image_path": str(fpath),
        }
    finally:
        conn.close()


@app.post("/v1/documents/{document_id}/finalize")
def finalize_document(document_id: int) -> dict:
    conn = db.connect()
    try:
        _doc_or_404(conn, document_id)
        pages = conn.execute(
            "SELECT id, image_path, ocr_text FROM pages WHERE document_id = ?",
            (document_id,),
        ).fetchall()
        if not pages:
            raise HTTPException(status_code=400, detail="document has no pages")

        analyzer = get_analyzer()
        for p in pages:
            result = analyzer.analyze(
                image_path=p["image_path"], ocr_text=p["ocr_text"]
            )
            conn.execute(
                "UPDATE pages SET summary = ? WHERE id = ?",
                (result.summary, p["id"]),
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
    image: UploadFile = File(...),
    fast_ocr_text: str | None = Form(None),
    client_version: str | None = Form(None),
    sdk_hint: str | None = Form(None),
) -> dict:
    conn = db.connect()
    try:
        _doc_or_404(conn, document_id)
        raw = await image.read()
        img = _load_image(raw)

        q_phash = phash_hex(img)
        q_md5 = ocr_md5(fast_ocr_text)
        if q_md5 is None:
            import hashlib

            q_md5 = hashlib.md5(raw).hexdigest()

        rows = conn.execute(
            "SELECT id, page_index, phash, ocr_md5, ocr_text, summary FROM pages "
            "WHERE document_id = ? ORDER BY page_index",
            (document_id,),
        ).fetchall()
        candidates = [
            Candidate(
                page_id=r["id"],
                page_index=r["page_index"],
                phash=r["phash"],
                ocr_md5=r["ocr_md5"],
                ocr_text=normalize_ocr_text(r["ocr_text"]),
            )
            for r in rows
        ]
        summaries = {r["id"]: r["summary"] for r in rows}

        best, verdict, scored = match(
            q_phash, q_md5, candidates, query_ocr_text=fast_ocr_text
        )
        hud = build_hud(
            verdict,
            best,
            total_pages=len(candidates),
            summary=summaries.get(best.page_id) if best else None,
        )

        return {
            "document_id": document_id,
            "query_phash": q_phash,
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
