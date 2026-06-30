"""Rokid DocScan MVP — FastAPI server.

Server-side only. Runs locally with SQLite + local filesystem, no Rokid
hardware and no external credentials. See docs/implementation-notes.md for
where real Rokid CXR integration plugs in.
"""

from __future__ import annotations

import hashlib
import io
import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

from . import config, db
from .analyzers import get_analyzer
from .config import IMAGE_DIR, ensure_dirs
from .explainer import ExplainRequest
from .explainers import get_explainer, list_explainers
from .extractors import detect_media, get_extractor
from .glasses_view import (
    CAPTURE_CONTRACT,
    EXPLAIN_STAGES,
    OPERATION_CONTRACT,
    RENDER_CONTRACT,
    STAGES,
    build_capture_ack,
    build_explain_view,
    build_glasses_view,
    build_locked_view,
    build_scan_ack,
)
from .hud import build_hud
from .layout import parse_layout, primary_question
from .matching import Candidate, match, normalize_ocr_text, ocr_md5, phash_hex
from .overlay import build_overlay
from .retrieval import retrieve_context
from .solvers import Question
from .solvers.registry import solve_with_fallback
from .subjects import detect_subject
from .version import APP_VERSION, HUD_CONTRACT_VERSION, version_info


def _extract_media(ocr_text: str | None, image_path: str) -> list[dict]:
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


app = FastAPI(title="Rokid DocScan MVP", version=APP_VERSION, lifespan=lifespan)


# --- request/response models ------------------------------------------------

class CreateDocument(BaseModel):
    title: str
    capture_device: str | None = None
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


def _fallback_md5(omd5: str | None, raw: bytes) -> str:
    return omd5 if omd5 is not None else hashlib.md5(raw).hexdigest()


def _row_or_404(conn, table: str, row_id: int, detail: str):
    row = conn.execute(
        f"SELECT * FROM {table} WHERE id = ?", (row_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=detail)
    return row


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
    image: UploadFile = File(...),
    ocr_text: str | None = Form(None),
) -> dict:
    conn = db.connect()
    try:
        _doc_or_404(conn, document_id)
        raw = await image.read()
        img = _load_image(raw)

        ph = phash_hex(img)
        omd5 = _fallback_md5(ocr_md5(ocr_text), raw)

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
        q_md5 = _fallback_md5(ocr_md5(fast_ocr_text), raw)

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


# --- exam-solving mode ------------------------------------------------------

class CreateExamSession(BaseModel):
    mode: str = "study"
    voice_enabled: bool = False
    subject_hint: str | None = None


def _exam_session_or_404(conn, session_id: int):
    return _row_or_404(conn, "exam_sessions", session_id, "exam session not found")


def _question_or_404(conn, session_id: int, question_id: int):
    row = conn.execute(
        "SELECT * FROM questions WHERE id = ? AND session_id = ?",
        (question_id, session_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="question not found")
    return row


def _solution_from_row(row) -> "object":
    from .solvers import SolveResult

    return SolveResult(
        answer=row["answer"] or "",
        solution_steps=json.loads(row["solution_steps_json"] or "[]"),
        rationale=row["rationale"] or "",
        cautions=row["cautions"] or "",
        answer_confidence=row["answer_conf"] or 0.0,
        rationale_confidence=row["rationale_conf"] or 0.0,
        evidence_pages=json.loads(row["evidence_pages_json"] or "[]"),
        raw_reasoning=row["raw_reasoning"] or "",
    )


@app.post("/v1/exam-sessions", status_code=201)
def create_exam_session(payload: CreateExamSession) -> dict:
    if payload.mode not in {"study", "mock", "real"}:
        raise HTTPException(status_code=400, detail="invalid mode")
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO exam_sessions (mode, voice_enabled, subject_hint) "
            "VALUES (?, ?, ?)",
            (payload.mode, int(payload.voice_enabled), payload.subject_hint),
        )
        conn.commit()
        return {
            "session_id": cur.lastrowid,
            "mode": payload.mode,
            "voice_enabled": payload.voice_enabled,
            "subject_hint": payload.subject_hint,
            "status": "open",
            "api_version": version_info()["api_version"],
        }
    finally:
        conn.close()


@app.post("/v1/exam-sessions/{session_id}/questions", status_code=201)
async def add_question(
    session_id: int,
    image: UploadFile = File(...),
    ocr_text: str | None = Form(None),
    bbox_hints: str | None = Form(None),
) -> dict:
    conn = db.connect()
    try:
        _exam_session_or_404(conn, session_id)
        raw = await image.read()
        img = _load_image(raw)

        hints = json.loads(bbox_hints) if bbox_hints else None
        parsed = parse_layout(ocr_text, bbox_hints=hints)
        q = primary_question(parsed)
        subject, subj_conf = detect_subject(ocr_text)

        read_conf = 0.0 if not normalize_ocr_text(ocr_text) else round(min(1.0, 0.5 + subj_conf / 2), 3)

        fname = f"q_{session_id}_{uuid.uuid4().hex[:8]}.png"
        fpath: Path = IMAGE_DIR / fname
        img.convert("RGB").save(fpath, format="PNG")

        answer_box = q.answer_box if q else parsed.get("answer_box")
        media = _extract_media(ocr_text, str(fpath))
        cur = conn.execute(
            """INSERT INTO questions
               (session_id, question_no, body_text, choices_json, figure_refs,
                answer_box_json, structure_json, subject, read_conf,
                page_number, image_path, media_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                q.question_no if q else None,
                q.body_text if q else (ocr_text or ""),
                json.dumps(q.choices if q else [], ensure_ascii=False),
                json.dumps(q.figure_refs if q else [], ensure_ascii=False),
                json.dumps(answer_box, ensure_ascii=False) if answer_box else None,
                json.dumps(parsed.get("headings", []), ensure_ascii=False),
                subject,
                read_conf,
                parsed.get("page_number"),
                str(fpath),
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
                "lines": ["読み取り不十分", "近づけて再撮影", "してください"],
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
        )
        result, solver = solve_with_fallback(question=question)
        served_by = result.extras.get("served_by", solver.name)
        evidence_pages = result.evidence_pages or retrieved["evidence_pages"]
        result.evidence_pages = evidence_pages

        conn.execute(
            """INSERT INTO solutions
               (question_id, solver_name, answer, solution_steps_json, rationale,
                cautions, answer_conf, rationale_conf, evidence_pages_json,
                raw_reasoning, served_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
        sol = conn.execute(
            "SELECT * FROM solutions WHERE question_id = ? ORDER BY id DESC LIMIT 1",
            (question_id,),
        ).fetchone()
        if sol is None:
            raise HTTPException(status_code=409, detail="question not solved yet")
        if session["mode"] == "real" and not config.ALLOW_REAL_EXAM_SOLVE:
            return {"glasses_view": build_locked_view(stage), "locked": True}

        answer_box = json.loads(q["answer_box_json"]) if q["answer_box_json"] else None
        return {
            "glasses_view": build_glasses_view(
                _solution_from_row(sol),
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
        sol = conn.execute(
            "SELECT * FROM solutions WHERE question_id = ? ORDER BY id DESC LIMIT 1",
            (question_id,),
        ).fetchone()
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
        solved = {
            r["question_id"]
            for r in conn.execute(
                "SELECT DISTINCT question_id FROM solutions "
                "WHERE question_id IN "
                "(SELECT id FROM questions WHERE session_id = ?)",
                (session_id,),
            ).fetchall()
        }
        return {
            "session_id": session_id,
            "mode": session["mode"],
            "voice_enabled": bool(session["voice_enabled"]),
            "status": session["status"],
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
# Explain-sessions: live multi-page document explanation
#
# UX flow (button-only, silent, glasses-standalone):
#   1. POST /v1/explain-sessions          → create, status=scanning
#   2. POST …/{id}/scan  (per page)       → pHash match, silent ack (P02 読取済 ✓)
#   3. POST …/{id}/commit                 → double-long-press; status=ready
#   4. GET  …/{id}/explain?page_index=N   → explanation HUD, status→explaining
#      GET  …/{id}/explain?…&stage=detail&view_page=1  → swipe to next slice
#   5. GET  …/{id}/history                → scanned page list
# ---------------------------------------------------------------------------

class CreateExplainSession(BaseModel):
    document_id: int
    voice_enabled: bool = False


def _explain_session_or_404(conn, session_id: int):
    return _row_or_404(conn, "explain_sessions", session_id, "explain session not found")


@app.post("/v1/explain-sessions", status_code=201)
def create_explain_session(payload: CreateExplainSession) -> dict:
    """Create an explain session bound to a finalized document.

    The document must already exist (need not be finalized, but finalized
    documents have summaries which improve explanation quality).
    Status starts as 'scanning'.
    """
    conn = db.connect()
    try:
        _doc_or_404(conn, payload.document_id)
        cur = conn.execute(
            "INSERT INTO explain_sessions (document_id, voice_enabled) VALUES (?, ?)",
            (payload.document_id, int(payload.voice_enabled)),
        )
        conn.commit()
        # Total pages in the document (may be 0 for an empty doc).
        total_pages = conn.execute(
            "SELECT COUNT(*) FROM pages WHERE document_id = ?",
            (payload.document_id,),
        ).fetchone()[0]
        return {
            "session_id": cur.lastrowid,
            "document_id": payload.document_id,
            "voice_enabled": payload.voice_enabled,
            "status": "scanning",
            "scanned_pages": [],
            "total_pages": total_pages,
            "operations": OPERATION_CONTRACT,
            "api_version": version_info()["api_version"],
        }
    finally:
        conn.close()


@app.post("/v1/explain-sessions/{session_id}/scan")
async def explain_scan(
    session_id: int,
    image: UploadFile = File(...),
    fast_ocr_text: str | None = Form(None),
) -> dict:
    """Silently match one page frame during the scanning phase.

    The glasses user presses the button once per page while reading through
    the document. The server records which page was matched; the HUD shows
    only a quiet 'P02 読取済 ✓' ack (no explanation yet).

    Returns 409 if the session is not in 'scanning' status.
    """
    conn = db.connect()
    try:
        session = _explain_session_or_404(conn, session_id)
        if session["status"] != "scanning":
            raise HTTPException(
                status_code=409,
                detail=f"session status is '{session['status']}'; expected 'scanning'",
            )

        doc_id = session["document_id"]
        raw = await image.read()
        img = _load_image(raw)
        q_phash = phash_hex(img)
        q_md5 = _fallback_md5(ocr_md5(fast_ocr_text), raw)

        rows = conn.execute(
            "SELECT id, page_index, phash, ocr_md5, ocr_text FROM pages "
            "WHERE document_id = ? ORDER BY page_index",
            (doc_id,),
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
        total_pages = len(candidates)

        best, verdict, _ = match(q_phash, q_md5, candidates, query_ocr_text=fast_ocr_text)

        # Update scanned_pages list (deduplicated, sorted).
        scanned: list[int] = json.loads(session["scanned_pages_json"] or "[]")
        if verdict in ("HIT", "LOW_CONF") and best is not None:
            matched_index = best.page_index
            if matched_index not in scanned:
                scanned.append(matched_index)
                scanned.sort()
            conn.execute(
                "UPDATE explain_sessions SET scanned_pages_json = ? WHERE id = ?",
                (json.dumps(scanned), session_id),
            )
            conn.commit()
        else:
            matched_index = None

        scan_ack = build_scan_ack(
            page_index=matched_index if matched_index is not None else 0,
            scanned_count=len(scanned),
            total_pages=total_pages,
        )
        return {
            "session_id": session_id,
            "verdict": verdict,
            "matched_page_index": matched_index,
            "scanned_pages": scanned,
            "total_pages": total_pages,
            "scan_ack": scan_ack,
            "versions": version_info(),
        }
    finally:
        conn.close()


@app.post("/v1/explain-sessions/{session_id}/commit")
def explain_commit(session_id: int) -> dict:
    """Transition session from 'scanning' to 'ready'.

    Triggered by the user's double-long-press gesture after all pages have
    been scanned. From this point onward, explanation is available via GET
    /explain. Scanning is no longer accepted (returns 409).
    """
    conn = db.connect()
    try:
        session = _explain_session_or_404(conn, session_id)
        if session["status"] not in ("scanning", "ready"):
            raise HTTPException(
                status_code=409,
                detail=f"cannot commit from status '{session['status']}'",
            )
        conn.execute(
            "UPDATE explain_sessions SET status = 'ready' WHERE id = ?",
            (session_id,),
        )
        conn.commit()

        scanned: list[int] = json.loads(session["scanned_pages_json"] or "[]")
        total_pages = conn.execute(
            "SELECT COUNT(*) FROM pages WHERE document_id = ?",
            (session["document_id"],),
        ).fetchone()[0]
        return {
            "session_id": session_id,
            "status": "ready",
            "scanned_pages": scanned,
            "total_pages": total_pages,
            # HUD confirmation: silent, 2-second display.
            "commit_ack": {
                "lines": ["読み取り完了", f"{len(scanned)}/{total_pages}ページ", "タップで解説開始"],
                "ttl_sec": 3,
            },
            "versions": version_info(),
        }
    finally:
        conn.close()


@app.get("/v1/explain-sessions/{session_id}/explain")
def explain_page(
    session_id: int,
    page_index: int,
    stage: str = "overview",
    view_page: int = 0,
) -> dict:
    """Return the explanation HUD for a specific document page.

    Available only when session status is 'ready' or 'explaining'.
    Triggered by a tap gesture on the glasses after commit.

    Navigation:
      - stage     : overview | detail | evidence  (swipe_down / swipe_up)
      - view_page : 0-based teleprompter slice    (swipe_left / swipe_right)

    The response includes `nav` with prev/next pointers so the client knows
    whether a swipe will produce more content.
    """
    if stage not in EXPLAIN_STAGES:
        raise HTTPException(
            status_code=400,
            detail=f"stage must be one of {EXPLAIN_STAGES}",
        )
    conn = db.connect()
    try:
        session = _explain_session_or_404(conn, session_id)
        if session["status"] not in ("ready", "explaining"):
            raise HTTPException(
                status_code=409,
                detail=f"session status is '{session['status']}'; commit first",
            )

        doc_id = session["document_id"]

        # Fetch the matched page row.
        page_row = conn.execute(
            "SELECT * FROM pages WHERE document_id = ? AND page_index = ?",
            (doc_id, page_index),
        ).fetchone()
        if page_row is None:
            raise HTTPException(
                status_code=404,
                detail=f"page_index {page_index} not found in document",
            )

        total_doc_pages = conn.execute(
            "SELECT COUNT(*) FROM pages WHERE document_id = ?", (doc_id,)
        ).fetchone()[0]

        # RAG: pull context from other pages in the same document.
        retrieved = retrieve_context(conn, page_row["ocr_text"])

        # Build ExplainRequest and call the active Explainer adapter.
        req = ExplainRequest(
            page_index=page_index,
            page_ocr_text=page_row["ocr_text"],
            page_summary=page_row["summary"],
            context_pages=retrieved["hits"],
            document_title=conn.execute(
                "SELECT title FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()["title"],
        )
        explainer = get_explainer()
        result = explainer.explain(req)

        # Persist to explain_views for history.
        conn.execute(
            """INSERT INTO explain_views
               (session_id, page_index, verdict, hud_lines_json,
                detail, evidence_pages_json, confidence)
               VALUES (?, ?, 'HIT', ?, ?, ?, ?)""",
            (
                session_id,
                page_index,
                json.dumps(result.lines, ensure_ascii=False),
                result.detail,
                json.dumps(result.evidence_pages),
                result.confidence,
            ),
        )
        # Advance status to explaining on first tap.
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
            "page_index": page_index,
            "total_doc_pages": total_doc_pages,
            "explainer": explainer.info(),
            "glasses_view": view,
            "evidence": retrieved["hits"],
            "versions": version_info(),
        }
    finally:
        conn.close()


@app.get("/v1/explain-sessions/{session_id}/history")
def explain_history(session_id: int) -> dict:
    """Return the list of pages viewed during this explain session.

    Each entry includes the page_index, verdict, HUD lines, and timestamp.
    Useful for review after the session, and for the glasses client to
    determine which pages have already been explained.
    """
    conn = db.connect()
    try:
        session = _explain_session_or_404(conn, session_id)
        scanned: list[int] = json.loads(session["scanned_pages_json"] or "[]")
        views = conn.execute(
            "SELECT page_index, verdict, hud_lines_json, detail, "
            "evidence_pages_json, confidence, viewed_at "
            "FROM explain_views WHERE session_id = ? ORDER BY viewed_at",
            (session_id,),
        ).fetchall()
        return {
            "session_id": session_id,
            "document_id": session["document_id"],
            "status": session["status"],
            "voice_enabled": bool(session["voice_enabled"]),
            "scanned_pages": scanned,
            "explained_views": [
                {
                    "page_index": v["page_index"],
                    "verdict": v["verdict"],
                    "hud_lines": json.loads(v["hud_lines_json"] or "[]"),
                    "evidence_pages": json.loads(v["evidence_pages_json"] or "[]"),
                    "confidence": v["confidence"],
                    "viewed_at": v["viewed_at"],
                }
                for v in views
            ],
            "versions": version_info(),
        }
    finally:
        conn.close()
