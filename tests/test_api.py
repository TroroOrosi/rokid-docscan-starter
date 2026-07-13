import importlib

import pytest
from fastapi.testclient import TestClient

from tests.conftest import image_bytes, make_image


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Point all storage at a temp dir, then reload modules that captured paths.
    monkeypatch.setenv("ROKID_DATA_DIR", str(tmp_path))
    import app.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)
    import app.main as main
    importlib.reload(main)
    main.ensure_dirs()
    main.db.init_db()
    return TestClient(main.app)


def _create_doc(client, title="Spec v1"):
    r = client.post("/v1/documents", json={"title": title, "capture_device": "CXR-S"})
    assert r.status_code == 201
    return r.json()["document_id"]


def _add_page(client, doc_id, idx, seed, ocr_text=None):
    files = {"image": (f"p{idx}.png", image_bytes(make_image(seed=seed)), "image/png")}
    data = {"page_index": str(idx)}
    if ocr_text is not None:
        data["ocr_text"] = ocr_text
    return client.post(f"/v1/documents/{doc_id}/pages", data=data, files=files)


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert "versions" in body
    assert "api_version" in body["versions"]


def test_version_endpoint(client):
    body = client.get("/v1/version").json()
    assert "matcher_version" in body
    assert "hud_contract_version" in body
    assert any(a["name"] == "local" for a in body["analyzers"])


def test_match_response_carries_versions_and_hints(client):
    doc_id = _create_doc(client)
    _add_page(client, doc_id, 0, seed=10, ocr_text="page one")
    client.post(f"/v1/documents/{doc_id}/finalize")
    files = {"image": ("q.png", image_bytes(make_image(seed=10)), "image/png")}
    r = client.post(
        "/v1/match",
        data={
            "document_id": str(doc_id),
            "client_version": "android-0.9.1",
            "sdk_hint": "cxr-l",
        },
        files=files,
    )
    body = r.json()
    assert body["versions"]["hud_contract_version"]
    assert body["client_version"] == "android-0.9.1"
    assert body["sdk_hint"] == "cxr-l"


def test_full_flow_hit(client):
    doc_id = _create_doc(client)
    assert _add_page(client, doc_id, 0, seed=10, ocr_text="page one").status_code == 201
    assert _add_page(client, doc_id, 1, seed=200, ocr_text="page two").status_code == 201

    fin = client.post(f"/v1/documents/{doc_id}/finalize").json()
    assert fin["status"] == "ready"
    assert fin["page_count"] == 2
    assert len(fin["summaries"]) == 2

    # query with the same image as page 0 -> HIT on page_index 0
    files = {"image": ("q.png", image_bytes(make_image(seed=10)), "image/png")}
    r = client.post("/v1/match", data={"document_id": str(doc_id)}, files=files)
    body = r.json()
    assert body["verdict"] == "HIT"
    assert body["best_page"]["page_index"] == 0
    assert len(body["hud"]["lines"]) == 3
    assert body["hud"]["lines"][0].startswith("PAGE")


def test_match_no_page(client):
    doc_id = _create_doc(client)
    _add_page(client, doc_id, 0, seed=10)
    client.post(f"/v1/documents/{doc_id}/finalize")

    files = {"image": ("q.png", image_bytes(make_image(seed=777)), "image/png")}
    r = client.post("/v1/match", data={"document_id": str(doc_id)}, files=files)
    body = r.json()
    assert body["verdict"] in {"NO_PAGE", "LOW_CONF"}
    assert len(body["hud"]["lines"]) == 3


def test_match_hud_counts_text_only_pages_in_mixed_document(client):
    doc_id = _create_doc(client)
    # Page 0 follows the primary no-photography path and is not a /match
    # candidate. Page 1 keeps the optional compatibility image.
    assert client.post(
        f"/v1/documents/{doc_id}/pages",
        data={"page_index": 0, "ocr_text": "text-only page"},
    ).status_code == 201
    assert _add_page(client, doc_id, 1, seed=20, ocr_text="image page").status_code == 201
    assert client.post(f"/v1/documents/{doc_id}/finalize").status_code == 200

    files = {"image": ("q.png", image_bytes(make_image(seed=20)), "image/png")}
    body = client.post(
        "/v1/match", data={"document_id": str(doc_id)}, files=files
    ).json()
    assert body["verdict"] == "HIT"
    assert body["best_page"]["page_index"] == 1
    assert body["hud"]["lines"][0] == "PAGE 2/2"


def test_resending_page_index_replaces_the_page(client):
    # 再読取: re-sending an index replaces the page (fix a bad read), it does
    # not 409 and does not grow the document.
    doc_id = _create_doc(client)
    first = _add_page(client, doc_id, 0, seed=10, ocr_text="bad read")
    assert first.status_code == 201 and first.json()["replaced"] is False
    second = _add_page(client, doc_id, 0, seed=11, ocr_text="good read")
    assert second.status_code == 201
    body = second.json()
    assert body["replaced"] is True
    assert body["page_id"] == first.json()["page_id"]
    assert body["phash"] != first.json()["phash"]

    fin = client.post(f"/v1/documents/{doc_id}/finalize").json()
    assert fin["page_count"] == 1
    assert fin["summaries"][0]["summary"] == "good read"


def test_missing_document_404(client):
    files = {"image": ("q.png", image_bytes(make_image(seed=1)), "image/png")}
    r = client.post("/v1/match", data={"document_id": "9999"}, files=files)
    assert r.status_code == 404


def test_finalize_is_idempotent_per_page(client, monkeypatch):
    # Re-finalizing (gesture double-fire / resume) must not re-run the analyzer
    # over already-summarized pages — with a cloud ROKID_ANALYZER that would be
    # a full re-bill of the document.
    from app.analyzers import Analyzer, AnalyzerResult, register_analyzer

    calls = []

    class CountingAnalyzer(Analyzer):
        name = "counting-test"
        provider_version = "t-1"
        offline = True

        def analyze(self, *, image_path=None, ocr_text=None, max_summary_len=48):
            calls.append(ocr_text)
            return AnalyzerResult(text=ocr_text, summary="COUNTED")

    register_analyzer(CountingAnalyzer(), replace=True)
    monkeypatch.setenv("ROKID_ANALYZER", "counting-test")

    doc_id = _create_doc(client)
    _add_page(client, doc_id, 0, seed=10, ocr_text="page one")
    _add_page(client, doc_id, 1, seed=11, ocr_text="page two")
    assert client.post(f"/v1/documents/{doc_id}/finalize").status_code == 200
    assert client.post(f"/v1/documents/{doc_id}/finalize").status_code == 200
    assert len(calls) == 2


def test_reading_status_restores_persisted_pages_without_camera(client):
    doc_id = _create_doc(client)

    # Primary path: recognized text only, including the on-glass figure reading.
    text_page = client.post(
        f"/v1/documents/{doc_id}/pages",
        data={
            "page_index": "0",
            "ocr_text": "問1  次の図を説明せよ",
            "vision_text": "図1: 右上がりのグラフ",
        },
    )
    assert text_page.status_code == 201

    # Compatibility path: an image-backed page can coexist in the same document.
    assert _add_page(
        client, doc_id, 2, seed=30, ocr_text="問3 最後の問題"
    ).status_code == 201

    response = client.get(
        f"/v1/documents/{doc_id}/reading-status",
        params={"expected_total_pages": 3},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "open"
    assert body["page_indexes"] == [0, 2]
    assert body["expected_pages_complete"] is False
    assert body["missing_page_indexes"] == [1]
    assert body["unexpected_page_indexes"] == []
    assert body["recommended_action"] == "read_missing_pages"
    assert body["finalize_required"] is True
    assert body["ready_for_use"] is False
    assert body["camera"] == {"required": False, "expected_state": "off"}

    first, third = body["pages"]
    assert first["storage_kind"] == "text_only"
    assert first["has_image"] is False
    assert first["has_ocr_text"] is True
    assert first["has_vision_text"] is True
    assert first["summary_generated"] is False
    assert "図1: 右上がりのグラフ" in first["preview"]
    assert third["storage_kind"] == "image_backed"
    assert third["has_image"] is True
    assert third["has_ocr_text"] is True
    assert third["has_vision_text"] is False


def test_reading_status_distinguishes_unknown_count_and_finalized_state(client):
    doc_id = _create_doc(client)
    assert client.post(
        f"/v1/documents/{doc_id}/pages",
        data={"page_index": "0", "ocr_text": "問1 本文"},
    ).status_code == 201

    # Without the physical page count the API must not claim completeness.
    unknown = client.get(
        f"/v1/documents/{doc_id}/reading-status"
    ).json()
    assert unknown["expected_total_pages"] is None
    assert unknown["expected_pages_complete"] is None
    assert unknown["missing_page_indexes"] is None
    assert unknown["recommended_action"] == "finalize"

    assert client.post(f"/v1/documents/{doc_id}/finalize").status_code == 200
    finalized = client.get(
        f"/v1/documents/{doc_id}/reading-status",
        params={"expected_total_pages": 1},
    ).json()
    assert finalized["status"] == "ready"
    assert finalized["expected_pages_complete"] is True
    assert finalized["summary_generated_count"] == 1
    assert finalized["summaries_complete"] is True
    assert finalized["finalize_required"] is False
    assert finalized["ready_for_use"] is True
    assert finalized["recommended_action"] == "continue"
    assert finalized["pages"][0]["summary_generated"] is True


@pytest.mark.parametrize("expected", [0, -1])
def test_reading_status_rejects_invalid_expected_page_count(client, expected):
    doc_id = _create_doc(client)
    response = client.get(
        f"/v1/documents/{doc_id}/reading-status",
        params={"expected_total_pages": expected},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "expected_total_pages must be >= 1"


def test_reading_status_missing_document_404(client):
    response = client.get("/v1/documents/9999/reading-status")
    assert response.status_code == 404
