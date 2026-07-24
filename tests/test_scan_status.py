"""GET /v1/documents/{id}/scan-status — page-state and recovery report.

The report is read-only. It exposes whether the authoritative page image and
recognized text are present so a phone relay can resume safely.
"""

import importlib
import threading

import pytest
from fastapi.testclient import TestClient

from tests.conftest import image_bytes, make_image


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ROKID_DATA_DIR", str(tmp_path))
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


def _new_doc(client, title="模試"):
    r = client.post("/v1/documents", json={"title": title})
    assert r.status_code == 201
    return r.json()["document_id"]


def _add_text_page(client, doc_id, idx, text):
    r = client.post(
        f"/v1/documents/{doc_id}/pages",
        data={"page_index": idx, "ocr_text": text},
    )
    assert r.status_code == 201, r.text


def _status(client, doc_id, expected=None):
    url = f"/v1/documents/{doc_id}/scan-status"
    if expected is not None:
        url += f"?expected_total_pages={expected}"
    return client.get(url)


def test_scan_status_empty_document_start_reading(client):
    doc_id = _new_doc(client)
    body = _status(client, doc_id, expected=3).json()
    assert body["page_count"] == 0
    assert body["missing_page_indexes"] == [0, 1, 2]
    assert body["expected_pages_complete"] is False
    assert body["recommended_action"] == "start_reading"


def test_scan_status_reports_registered_and_missing_indexes(client):
    doc_id = _new_doc(client)
    _add_text_page(client, doc_id, 0, "問1 本文")
    _add_text_page(client, doc_id, 2, "問3 本文")  # page 1 was interrupted
    body = _status(client, doc_id, expected=4).json()
    assert body["page_indexes"] == [0, 2]
    assert body["missing_page_indexes"] == [1, 3]
    assert body["unexpected_page_indexes"] == []
    assert body["expected_pages_complete"] is False
    assert body["recommended_action"] == "reread_missing_pages"
    # 再読取 guidance points at the page-replace behaviour of add_page
    assert body["reread"]["replaces_existing_page_index"] is True


def test_scan_status_unexpected_indexes_review_action(client):
    doc_id = _new_doc(client)
    _add_text_page(client, doc_id, 0, "p1")
    _add_text_page(client, doc_id, 5, "typo index")
    body = _status(client, doc_id, expected=1).json()
    assert body["missing_page_indexes"] == []
    assert body["unexpected_page_indexes"] == [5]
    assert body["expected_pages_complete"] is False
    assert body["recommended_action"] == "review_page_indexes"


def test_scan_status_without_expected_total_reports_null_completeness(client):
    # Same honesty rule as scan_ack: no declared total -> no completeness claim.
    doc_id = _new_doc(client)
    _add_text_page(client, doc_id, 0, "p1")
    body = _status(client, doc_id).json()
    assert body["expected_total_pages"] is None
    assert body["missing_page_indexes"] is None
    assert body["unexpected_page_indexes"] is None
    assert body["expected_pages_complete"] is None
    assert body["recommended_action"] == "finalize"


def test_scan_status_sparse_without_expected_total_avoids_dead_finalize(client):
    # Registered indexes [0, 2] break the 0..N-1 invariant that finalize
    # enforces. Without a declared total we can't name the missing page, but we
    # must not recommend a finalize that would immediately 409.
    doc_id = _new_doc(client)
    _add_text_page(client, doc_id, 0, "問1 本文")
    _add_text_page(client, doc_id, 2, "問3 本文")  # gap at index 1
    body = _status(client, doc_id).json()
    assert body["expected_total_pages"] is None
    assert body["page_indexes"] == [0, 2]
    assert body["recommended_action"] == "review_page_indexes"
    # The advice is honest: the finalize it steered away from really does 409.
    assert client.post(f"/v1/documents/{doc_id}/finalize").status_code == 409


def test_scan_status_dense_without_expected_total_still_finalizes(client):
    # A contiguous 0..N-1 document without a declared total is finalize-able,
    # so the sparse guard must not hijack the normal recommendation.
    doc_id = _new_doc(client)
    _add_text_page(client, doc_id, 0, "問1")
    _add_text_page(client, doc_id, 1, "問2")
    body = _status(client, doc_id).json()
    assert body["page_indexes"] == [0, 1]
    assert body["recommended_action"] == "finalize"


def test_scan_status_expected_total_pages_bounds(client):
    doc_id = _new_doc(client)
    for bad in (0, -1, 10_001):
        r = _status(client, doc_id, expected=bad)
        assert r.status_code == 400, bad
    assert _status(client, doc_id, expected=10_000).status_code == 200


def test_scan_status_finalize_then_continue_actions(client):
    doc_id = _new_doc(client)
    _add_text_page(client, doc_id, 0, "問1 本文")
    body = _status(client, doc_id, expected=1).json()
    assert body["expected_pages_complete"] is True
    assert body["summaries_complete"] is False
    assert body["recommended_action"] == "finalize"

    assert client.post(f"/v1/documents/{doc_id}/finalize").status_code == 200
    body = _status(client, doc_id, expected=1).json()
    assert body["status"] == "ready"
    assert body["summaries_complete"] is True
    assert body["recommended_action"] == "continue"


def test_scan_status_misindexed_page_prioritizes_index_review(client):
    # Missing AND unexpected coexist (e.g. page 1 was submitted as index 3):
    # blindly rereading the gap would leave the stray page in the document,
    # so index review must come first.
    doc_id = _new_doc(client)
    _add_text_page(client, doc_id, 0, "p1")
    _add_text_page(client, doc_id, 2, "p3")
    _add_text_page(client, doc_id, 3, "p2 誤ってindex 3で登録")
    body = _status(client, doc_id, expected=3).json()
    assert body["missing_page_indexes"] == [1]
    assert body["unexpected_page_indexes"] == [3]
    assert body["recommended_action"] == "review_page_indexes"


def test_finalize_rejects_gap_and_extra_before_document_is_frozen(client):
    # Navigation uses exact 0..N-1 indexes. A sparse document must remain open
    # and actionable instead of finalizing successfully and later returning a
    # 404 from current/explain.
    doc_id = _new_doc(client)
    _add_text_page(client, doc_id, 0, "p1")
    _add_text_page(client, doc_id, 2, "p3")
    _add_text_page(client, doc_id, 3, "p2 誤ってindex 3で登録")
    finalize = client.post(f"/v1/documents/{doc_id}/finalize")
    assert finalize.status_code == 409
    assert "contiguous from 0" in finalize.json()["detail"]
    body = _status(client, doc_id, expected=3).json()
    assert body["status"] == "open"
    assert body["missing_page_indexes"] == [1]
    assert body["unexpected_page_indexes"] == [3]
    assert body["recommended_action"] == "review_page_indexes"


def test_finalize_rejects_leading_sparse_index(client):
    doc_id = _new_doc(client)
    _add_text_page(client, doc_id, 2, "誤って3ページ目から登録")
    r = client.post(f"/v1/documents/{doc_id}/finalize")
    assert r.status_code == 409
    assert "registered=[2]" in r.json()["detail"]


def test_finalize_rechecks_pages_after_slow_analysis(client, monkeypatch):
    """A page added while a slow analyzer runs must prevent ready status."""
    import app.main as main
    from app.analyzers.base import AnalyzerResult

    started = threading.Event()
    release = threading.Event()

    class BlockingAnalyzer:
        name = "blocking-test"
        provider_version = "test-1"
        offline = True

        def analyze(self, *, image_path=None, ocr_text=None, max_summary_len=48):
            started.set()
            if not release.wait(timeout=5):
                raise AssertionError("test analyzer was not released")
            return AnalyzerResult(text=ocr_text, summary="summary")

        def info(self):
            return {
                "name": self.name,
                "provider_version": self.provider_version,
                "offline": self.offline,
            }

    monkeypatch.setattr(main, "get_analyzer", lambda: BlockingAnalyzer())
    doc_id = _new_doc(client)
    _add_text_page(client, doc_id, 0, "解析前のページ")

    outcome = {}

    def run_finalize():
        outcome["response"] = client.post(f"/v1/documents/{doc_id}/finalize")

    worker = threading.Thread(target=run_finalize)
    worker.start()
    try:
        assert started.wait(timeout=2)
        _add_text_page(client, doc_id, 2, "解析中に追加された疎なページ")
    finally:
        release.set()
        worker.join(timeout=5)

    assert not worker.is_alive()
    response = outcome["response"]
    assert response.status_code == 409
    assert "contiguous from 0" in response.json()["detail"]

    body = _status(client, doc_id).json()
    assert body["status"] == "open"
    assert body["page_indexes"] == [0, 2]
    assert body["recommended_action"] == "review_page_indexes"


def test_legacy_ready_sparse_document_cannot_start_navigation(client):
    # Defense in depth for databases created before finalize enforced this
    # invariant: new sessions fail early with 409 instead of current/explain
    # returning a surprising page-0 404.
    import app.main as main

    doc_id = _new_doc(client)
    _add_text_page(client, doc_id, 2, "旧DBの疎なページ")
    conn = main.db.connect()
    try:
        conn.execute("UPDATE documents SET status = 'ready' WHERE id = ?", (doc_id,))
        conn.commit()
    finally:
        conn.close()

    exam = client.post("/v1/exam-sessions", json={"document_id": doc_id})
    explain = client.post("/v1/explain-sessions", json={"document_id": doc_id})
    assert exam.status_code == explain.status_code == 409


def test_scan_status_missing_after_finalize_recommends_new_document(client):
    # add_page rejects NEW page indexes once the document is finalized, so
    # rereading a missing index cannot succeed there — the only recovery is
    # a fresh document.
    doc_id = _new_doc(client)
    _add_text_page(client, doc_id, 0, "問1 本文")
    assert client.post(f"/v1/documents/{doc_id}/finalize").status_code == 200
    body = _status(client, doc_id, expected=2).json()
    assert body["missing_page_indexes"] == [1]
    assert body["recommended_action"] == "start_new_document"


def test_scan_status_reread_allowed_false_when_session_reviewing(client):
    doc_id = _new_doc(client)
    _add_text_page(client, doc_id, 0, "問1 二次方程式を解け")
    assert client.post(f"/v1/documents/{doc_id}/finalize").status_code == 200
    r = client.post("/v1/exam-sessions", json={"document_id": doc_id})
    assert r.status_code == 201
    sid = r.json()["session_id"]

    body = _status(client, doc_id).json()
    assert body["reread_allowed"] is True
    assert body["exam_sessions"] == [
        {"session_id": sid, "status": "open", "phase": "reading"}
    ]

    assert client.post(
        f"/v1/exam-sessions/{sid}/finalize-reading"
    ).status_code == 200
    body = _status(client, doc_id).json()
    assert body["reread_allowed"] is False
    assert body["exam_sessions"][0]["phase"] == "reviewing"


def test_scan_status_image_only_page_reports_pages_without_text(client):
    # A real photo may arrive before any OCR. An open document is allowed to
    # proceed to finalization where an image-capable analyzer can recover it.
    doc_id = _new_doc(client)
    files = {"image": ("p.png", image_bytes(make_image(seed=3)), "image/png")}
    r = client.post(
        f"/v1/documents/{doc_id}/pages", data={"page_index": 0}, files=files
    )
    assert r.status_code == 201
    body = _status(client, doc_id, expected=1).json()
    assert body["pages_without_text"] == [0]
    assert body["pages"][0]["has_image"] is True
    assert body["recommended_action"] == "finalize"


def test_scan_status_404_unknown_document(client):
    assert _status(client, 9999).status_code == 404


def test_scan_status_reports_image_presence_without_leaking_a_path(client):
    doc_id = _new_doc(client)
    files = {"image": ("p.png", image_bytes(make_image(seed=4)), "image/png")}
    assert client.post(
        f"/v1/documents/{doc_id}/pages",
        data={"page_index": 0, "ocr_text": "問1"},
        files=files,
    ).status_code == 201

    body = _status(client, doc_id, expected=1).json()
    assert body["pages"][0]["has_image"] is True
    assert "image_path" not in body["pages"][0]
    assert "phash" not in body["pages"][0]
