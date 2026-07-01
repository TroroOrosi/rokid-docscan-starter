"""Tests for the camera-free document page-move型 exam (v0.7 / api 1.7.0).

Covers:
  * camera-free page ingestion (POST /pages with ocr_text and NO image),
  * document-bound exam session (create with document_id/exam_type/answer_format),
  * page navigation (next-page/prev-page/current, clamped),
  * solve-current (solves the current page's material; persists question+solution
    so /view and /reasoning keep working),
  * 筆記 ⇄ リスニング mode switch (/mode),
  * listening audio upload + provided-transcript fallback (/audio),
  * guardrails (real-mode lock, non-document session rejected).

All offline: the local placeholder solver answers, no external credentials.
"""

import importlib

import pytest
from fastapi.testclient import TestClient

from tests.conftest import image_bytes, make_image


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ROKID_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ROKID_ALLOW_REAL_EXAM_SOLVE", raising=False)
    monkeypatch.delenv("ROKID_TRANSCRIBER", raising=False)
    import app.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)
    import app.main as main
    importlib.reload(main)
    main.ensure_dirs()
    main.db.init_db()
    return TestClient(main.app)


# --- camera-free page ingestion ---------------------------------------------

def _new_doc(client, title="模試"):
    r = client.post("/v1/documents", json={"title": title})
    assert r.status_code == 201
    return r.json()["document_id"]


def _add_text_page(client, doc_id, page_index, ocr_text):
    """Camera-free page: no image, only ocr_text."""
    return client.post(
        f"/v1/documents/{doc_id}/pages",
        data={"page_index": page_index, "ocr_text": ocr_text},
    )


def test_add_page_without_image_records_text_only(client):
    doc_id = _new_doc(client)
    r = _add_text_page(client, doc_id, 0, "問1 次の英文を読み設問に答えよ")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["image_path"] is None
    assert body["phash"] == ""
    assert body["ocr_md5"]  # derived from text


def test_add_page_requires_image_or_text(client):
    doc_id = _new_doc(client)
    # No image AND no ocr_text -> 400
    r = client.post(f"/v1/documents/{doc_id}/pages", data={"page_index": 0})
    assert r.status_code == 400


def test_add_page_with_image_still_works(client):
    doc_id = _new_doc(client)
    files = {"image": ("p.png", image_bytes(make_image(seed=3)), "image/png")}
    r = client.post(
        f"/v1/documents/{doc_id}/pages",
        data={"page_index": 0, "ocr_text": "画像あり"},
        files=files,
    )
    assert r.status_code == 201
    assert r.json()["image_path"] is not None
    assert r.json()["phash"]  # pHash computed for the image


def _doc_with_text_pages(client, texts):
    doc_id = _new_doc(client)
    for i, t in enumerate(texts):
        assert _add_text_page(client, doc_id, i, t).status_code == 201
    assert client.post(f"/v1/documents/{doc_id}/finalize").status_code == 200
    return doc_id


# --- document-bound exam session --------------------------------------------

def _new_doc_exam(client, doc_id, exam_type="written", answer_format="mark", mode="study"):
    r = client.post(
        "/v1/exam-sessions",
        json={
            "mode": mode,
            "document_id": doc_id,
            "exam_type": exam_type,
            "answer_format": answer_format,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_create_document_exam_reports_pages(client):
    doc_id = _doc_with_text_pages(client, ["p1", "p2", "p3"])
    body = _new_doc_exam(client, doc_id)
    assert body["document_id"] == doc_id
    assert body["total_pages"] == 3
    assert body["current_page_index"] == 0
    assert body["exam_type"] == "written"
    assert body["answer_format"] == "mark"
    assert "operations" in body


def test_create_rejects_bad_exam_type_or_format(client):
    doc_id = _doc_with_text_pages(client, ["p1"])
    r1 = client.post(
        "/v1/exam-sessions", json={"document_id": doc_id, "exam_type": "bogus"}
    )
    assert r1.status_code == 400
    r2 = client.post(
        "/v1/exam-sessions", json={"document_id": doc_id, "answer_format": "bogus"}
    )
    assert r2.status_code == 400


def test_create_rejects_missing_document(client):
    r = client.post("/v1/exam-sessions", json={"document_id": 9999})
    assert r.status_code == 404


# --- page navigation --------------------------------------------------------

def test_navigation_next_prev_clamped(client):
    doc_id = _doc_with_text_pages(client, ["p1", "p2", "p3"])
    sid = _new_doc_exam(client, doc_id)["session_id"]

    r = client.post(f"/v1/exam-sessions/{sid}/next-page")
    assert r.json()["current_page_index"] == 1
    # clamp at last
    for _ in range(5):
        r = client.post(f"/v1/exam-sessions/{sid}/next-page")
    assert r.json()["current_page_index"] == 2
    assert r.json()["at_last"] is True
    # clamp at first
    for _ in range(5):
        r = client.post(f"/v1/exam-sessions/{sid}/prev-page")
    assert r.json()["current_page_index"] == 0
    assert r.json()["at_first"] is True


def test_current_reports_subject_and_preview(client):
    doc_id = _doc_with_text_pages(
        client, ["問1 次の計算をせよ 12+13", "問2 光合成について述べよ"]
    )
    sid = _new_doc_exam(client, doc_id)["session_id"]
    client.post(f"/v1/exam-sessions/{sid}/next-page")  # -> page 1
    body = client.get(f"/v1/exam-sessions/{sid}/current").json()
    assert body["current_page_index"] == 1
    assert body["subject"]
    assert body["has_image"] is False  # camera-free page
    assert "光合成" in body["preview"]


def test_navigation_requires_document_session(client):
    # A plain (non-document) exam session cannot use page-move endpoints.
    r = client.post("/v1/exam-sessions", json={"mode": "study"})
    sid = r.json()["session_id"]
    assert client.post(f"/v1/exam-sessions/{sid}/next-page").status_code == 400
    assert client.get(f"/v1/exam-sessions/{sid}/current").status_code == 400


# --- solve-current ----------------------------------------------------------

def test_solve_current_answers_and_persists(client):
    doc_id = _doc_with_text_pages(client, ["問1 2x+3=7 を解け", "問2 別ページ"])
    sid = _new_doc_exam(client, doc_id)["session_id"]
    r = client.post(f"/v1/exam-sessions/{sid}/solve-current")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["locked"] is False
    assert body["current_page_index"] == 0
    assert body["served_by"] == "local"
    gv = body["glasses_view"]
    assert gv["stage"] == "answer"
    assert len(gv["lines"]) <= 3
    qid = body["question_id"]

    # The persisted question is navigable via the staged /view endpoint.
    for stage in ("answer", "solution", "rationale", "caution"):
        v = client.get(
            f"/v1/exam-sessions/{sid}/questions/{qid}/view", params={"stage": stage}
        )
        assert v.status_code == 200
        assert v.json()["glasses_view"]["stage"] == stage
    # session detail lists it as solved
    detail = client.get(f"/v1/exam-sessions/{sid}").json()
    assert detail["total_pages"] == 2
    assert any(q["solved"] for q in detail["questions"])


def test_solve_current_real_mode_is_locked(client):
    doc_id = _doc_with_text_pages(client, ["問1"])
    sid = _new_doc_exam(client, doc_id, mode="real")["session_id"]
    body = client.post(f"/v1/exam-sessions/{sid}/solve-current").json()
    assert body["locked"] is True
    assert body["glasses_view"]["locked"] is True


# --- mode switch ------------------------------------------------------------

def test_mode_toggle_written_listening(client):
    doc_id = _doc_with_text_pages(client, ["p1"])
    sid = _new_doc_exam(client, doc_id)["session_id"]
    r = client.post(f"/v1/exam-sessions/{sid}/mode", json={"exam_type": "listening"})
    assert r.status_code == 200
    assert r.json()["exam_type"] == "listening"
    assert client.get(f"/v1/exam-sessions/{sid}").json()["exam_type"] == "listening"
    # bad value rejected
    assert client.post(
        f"/v1/exam-sessions/{sid}/mode", json={"exam_type": "nope"}
    ).status_code == 400


# --- listening audio --------------------------------------------------------

def test_audio_uses_provided_transcript_offline(client):
    doc_id = _doc_with_text_pages(client, ["Listening Part 1 Question 1"])
    sid = _new_doc_exam(client, doc_id, exam_type="listening")["session_id"]
    # No ROKID_TRANSCRIBER configured -> provided transcript is stored as-is.
    r = client.post(
        f"/v1/exam-sessions/{sid}/audio",
        data={"transcript": "Hello, this is the recording."},
        files={"audio": ("rec.wav", b"RIFF....WAVEfake", "audio/wav")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["audio_stored"] is True
    assert body["transcript"] == "Hello, this is the recording."
    assert client.get(f"/v1/exam-sessions/{sid}").json()["has_audio"] is True


def test_audio_requires_something(client):
    doc_id = _doc_with_text_pages(client, ["p1"])
    sid = _new_doc_exam(client, doc_id, exam_type="listening")["session_id"]
    r = client.post(f"/v1/exam-sessions/{sid}/audio", data={})
    assert r.status_code == 400


def test_listening_solve_current_folds_in_transcript(client):
    doc_id = _doc_with_text_pages(client, ["Question 1: What did the man buy?"])
    sid = _new_doc_exam(
        client, doc_id, exam_type="listening", answer_format="mark"
    )["session_id"]
    client.post(
        f"/v1/exam-sessions/{sid}/audio",
        data={"transcript": "The man bought two apples."},
    )
    r = client.post(f"/v1/exam-sessions/{sid}/solve-current")
    assert r.status_code == 200
    assert r.json()["exam_type"] == "listening"
    assert r.json()["locked"] is False
