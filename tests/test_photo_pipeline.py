from __future__ import annotations

import importlib
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ROKID_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ROKID_ANALYZER", raising=False)
    monkeypatch.delenv("ROKID_SOLVER", raising=False)
    import app.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)
    import app.main as main
    importlib.reload(main)
    main.ensure_dirs()
    main.db.init_db()
    return TestClient(main.app)


def _jpeg() -> bytes:
    image = Image.new("RGB", (96, 128), "white")
    output = io.BytesIO()
    image.save(output, format="JPEG")
    return output.getvalue()


def _orientation_png() -> bytes:
    image = Image.new("RGB", (2, 3), "black")
    image.putpixel((0, 0), (255, 0, 0))
    image.putpixel((1, 2), (0, 0, 255))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _new_document(client) -> int:
    response = client.post("/v1/documents", json={"title": "photo exam"})
    assert response.status_code == 201
    return response.json()["document_id"]


def test_scan_status_reports_real_photo(client):
    document_id = _new_document(client)
    response = client.post(
        f"/v1/documents/{document_id}/pages",
        data={"page_index": "0", "ocr_text": "問1 1+1を答えよ"},
        files={"image": ("page.jpg", _jpeg(), "image/jpeg")},
    )
    assert response.status_code == 201

    status = client.get(f"/v1/documents/{document_id}/scan-status")
    assert status.status_code == 200
    assert status.json()["pages"][0]["has_image"] is True


def test_photo_rotation_matches_local_ocr_orientation(client):
    document_id = _new_document(client)
    response = client.post(
        f"/v1/documents/{document_id}/pages",
        data={
            "page_index": "0",
            "ocr_text": "問1",
            "image_rotation": "90",
        },
        files={"image": ("page.png", _orientation_png(), "image/png")},
    )
    assert response.status_code == 201
    assert response.json()["image_rotation"] == 90

    with Image.open(response.json()["image_path"]) as saved:
        assert saved.size == (3, 2)
        assert saved.getpixel((2, 0)) == (255, 0, 0)
        assert saved.getpixel((0, 1)) == (0, 0, 255)


def test_photo_rotation_rejects_unsupported_angle(client):
    document_id = _new_document(client)
    response = client.post(
        f"/v1/documents/{document_id}/pages",
        data={"page_index": "0", "ocr_text": "問1", "image_rotation": "45"},
        files={"image": ("page.jpg", _jpeg(), "image/jpeg")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == (
        "image_rotation must be one of 0, 90, 180, or 270"
    )


def test_finalize_persists_analyzer_ocr_for_photo(client, monkeypatch):
    import app.main as main
    from app.analyzers.base import AnalyzerResult

    class VisionAnalyzer:
        name = "vision-test"
        provider_version = "test"
        offline = False

        def analyze(self, *, image_path=None, ocr_text=None, max_summary_len=48):
            assert image_path
            return AnalyzerResult(
                text="問1 1+1を答えよ",
                summary="問1",
                extras={"vision_text": "数式 1+1"},
            )

        def info(self):
            return {
                "name": self.name,
                "provider_version": self.provider_version,
                "offline": self.offline,
            }

    monkeypatch.setattr(main, "get_analyzer", lambda: VisionAnalyzer())
    document_id = _new_document(client)
    added = client.post(
        f"/v1/documents/{document_id}/pages",
        data={"page_index": "0"},
        files={"image": ("page.jpg", _jpeg(), "image/jpeg")},
    )
    assert added.status_code == 201

    finalized = client.post(f"/v1/documents/{document_id}/finalize")
    assert finalized.status_code == 200

    conn = main.db.connect()
    try:
        row = conn.execute(
            "SELECT ocr_text, vision_text, summary FROM pages WHERE document_id = ?",
            (document_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row["ocr_text"] == "問1 1+1を答えよ"
    assert row["vision_text"] == "数式 1+1"
    assert row["summary"] == "問1"


def test_photo_without_any_ocr_stays_recoverable(client):
    document_id = _new_document(client)
    added = client.post(
        f"/v1/documents/{document_id}/pages",
        data={"page_index": "0"},
        files={"image": ("page.jpg", _jpeg(), "image/jpeg")},
    )
    assert added.status_code == 201

    finalized = client.post(f"/v1/documents/{document_id}/finalize")
    assert finalized.status_code == 200

    session = client.post(
        "/v1/exam-sessions",
        json={"mode": "study", "document_id": document_id},
    ).json()
    reading = client.post(
        f"/v1/exam-sessions/{session['session_id']}/finalize-reading"
    )
    assert reading.status_code == 200
    assert reading.json()["status"] == "reading"
    assert reading.json()["problem_count"] == 0


def test_finalize_reading_passes_primary_page_photo_to_solver(client, monkeypatch):
    import app.main as main
    from app.solvers.base import SolveResult

    captured = {}

    class Solver:
        name = "capture-test"

    def fake_solve(*, question):
        captured["image_path"] = question.image_path
        return (
            SolveResult(
                answer="2",
                solution_steps=["1+1=2"],
                rationale="加法",
                cautions="",
                answer_confidence=1.0,
                rationale_confidence=1.0,
            ),
            Solver(),
        )

    monkeypatch.setattr(main, "solve_with_fallback", fake_solve)
    monkeypatch.setenv("ROKID_SOLVER", "capture-test")

    document_id = _new_document(client)
    added = client.post(
        f"/v1/documents/{document_id}/pages",
        data={"page_index": "0", "ocr_text": "問1 1+1を答えよ"},
        files={"image": ("page.jpg", _jpeg(), "image/jpeg")},
    )
    assert added.status_code == 201
    assert client.post(f"/v1/documents/{document_id}/finalize").status_code == 200
    session = client.post(
        "/v1/exam-sessions",
        json={"mode": "study", "document_id": document_id},
    ).json()

    response = client.post(
        f"/v1/exam-sessions/{session['session_id']}/finalize-reading"
    )
    assert response.status_code == 200
    assert captured["image_path"]
