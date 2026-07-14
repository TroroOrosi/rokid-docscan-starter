"""GET /v1/documents/{id}/scan-status — 読取状態の確認・復旧（撮影しない）.

The report answers "which page readings are registered, which are missing,
and what should the client do next" so an interrupted reading phase can be
resumed by re-reading only the missing pages. It is read-only, text-vocabulary
only (no image/pHash/capture fields), and never claims completeness without a
declared expected_total_pages.
"""

import importlib

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
    # Only the legacy image-compat path can register a page without any
    # recognized text; the report flags it for 再読取.
    doc_id = _new_doc(client)
    files = {"image": ("p.png", image_bytes(make_image(seed=3)), "image/png")}
    r = client.post(
        f"/v1/documents/{doc_id}/pages", data={"page_index": 0}, files=files
    )
    assert r.status_code == 201
    body = _status(client, doc_id, expected=1).json()
    assert body["pages_without_text"] == [0]
    assert body["recommended_action"] == "reread_pages_without_text"


def test_scan_status_404_unknown_document(client):
    assert _status(client, 9999).status_code == 404


def test_scan_status_vocabulary_has_no_image_phash_capture_keys(client):
    # 撮影しない: the recovery report must not speak in capture terms at all.
    doc_id = _new_doc(client)
    _add_text_page(client, doc_id, 0, "p1")
    body = _status(client, doc_id, expected=2).json()

    banned = ("image", "phash", "capture", "photo")

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                assert not any(b in k.lower() for b in banned), k
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(body)
