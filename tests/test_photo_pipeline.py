from __future__ import annotations

import io

from PIL import Image


def _jpeg() -> bytes:
    image = Image.new("RGB", (96, 128), "white")
    output = io.BytesIO()
    image.save(output, format="JPEG")
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


def test_photo_without_any_ocr_remains_open(client):
    document_id = _new_document(client)
    added = client.post(
        f"/v1/documents/{document_id}/pages",
        data={"page_index": "0"},
        files={"image": ("page.jpg", _jpeg(), "image/jpeg")},
    )
    assert added.status_code == 201

    finalized = client.post(f"/v1/documents/{document_id}/finalize")
    assert finalized.status_code == 409
    assert "OCR" in finalized.json()["detail"]


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
