"""Tests for /v1/explain-sessions endpoints.

Covers the full UX flow:
  1. Create document + add page + finalize
  2. Create explain session (status=scanning)
  3. Scan page(s) -> silent ack, scanned_pages updates
  4. Commit (double-long-press) -> status=ready
  5. GET explain -> glasses_view with stage/view_page nav
  6. GET explain history

All tests are offline (local placeholder explainer, no external credentials).
Uses the same conftest.py fixtures as the main test suite.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.db import init_db


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _png_bytes(color: tuple = (128, 128, 128), size: tuple = (64, 64)) -> bytes:
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Isolated client with a fresh temp DB and image dir."""
    db_file = tmp_path / "test.db"
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    monkeypatch.setattr("app.config.DB_PATH", db_file)
    monkeypatch.setattr("app.config.IMAGE_DIR", img_dir)
    init_db(db_file)
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# fixture: document with one page
# ---------------------------------------------------------------------------

@pytest.fixture()
def doc_with_page(client):
    """Return (document_id, page_index) after upload + finalize."""
    r = client.post("/v1/documents", json={"title": "テスト資料"})
    assert r.status_code == 201
    doc_id = r.json()["document_id"]

    r = client.post(
        f"/v1/documents/{doc_id}/pages",
        data={"page_index": 0},
        files={"image": ("p0.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 201

    r = client.post(f"/v1/documents/{doc_id}/finalize")
    assert r.status_code == 200

    return doc_id, 0


# ---------------------------------------------------------------------------
# 1. session creation
# ---------------------------------------------------------------------------

class TestCreateExplainSession:
    def test_create_returns_scanning(self, client, doc_with_page):
        doc_id, _ = doc_with_page
        r = client.post("/v1/explain-sessions", json={"document_id": doc_id})
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "scanning"
        assert body["scanned_pages"] == []
        assert body["total_pages"] == 1
        # operations contract advertised
        assert "operations" in body
        assert body["operations"]["commit_scan"] == "double_long_press"

    def test_create_doc_not_found(self, client):
        r = client.post("/v1/explain-sessions", json={"document_id": 9999})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# 2. scanning phase
# ---------------------------------------------------------------------------

class TestExplainScan:
    def test_scan_page_returns_ack(self, client, doc_with_page):
        doc_id, page_index = doc_with_page
        r = client.post("/v1/explain-sessions", json={"document_id": doc_id})
        session_id = r.json()["session_id"]

        r = client.post(
            f"/v1/explain-sessions/{session_id}/scan",
            files={"image": ("frame.png", _png_bytes(), "image/png")},
        )
        assert r.status_code == 200
        body = r.json()
        assert "scan_ack" in body
        assert "scanned_pages" in body
        # ack has 3 lines
        assert len(body["scan_ack"]["lines"]) == 3
        assert body["scan_ack"]["ttl_sec"] == 2

    def test_scan_after_commit_returns_409(self, client, doc_with_page):
        doc_id, _ = doc_with_page
        r = client.post("/v1/explain-sessions", json={"document_id": doc_id})
        session_id = r.json()["session_id"]
        client.post(f"/v1/explain-sessions/{session_id}/commit")

        r = client.post(
            f"/v1/explain-sessions/{session_id}/scan",
            files={"image": ("frame.png", _png_bytes(), "image/png")},
        )
        assert r.status_code == 409


# ---------------------------------------------------------------------------
# 3. commit (double-long-press)
# ---------------------------------------------------------------------------

class TestExplainCommit:
    def test_commit_transitions_to_ready(self, client, doc_with_page):
        doc_id, _ = doc_with_page
        r = client.post("/v1/explain-sessions", json={"document_id": doc_id})
        session_id = r.json()["session_id"]

        r = client.post(f"/v1/explain-sessions/{session_id}/commit")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ready"
        assert "commit_ack" in body
        assert body["commit_ack"]["lines"][0] == "読み取り完了"
        assert body["commit_ack"]["ttl_sec"] == 3

    def test_commit_idempotent(self, client, doc_with_page):
        """Double-long-press is safe to send twice (hardware bounce)."""
        doc_id, _ = doc_with_page
        r = client.post("/v1/explain-sessions", json={"document_id": doc_id})
        session_id = r.json()["session_id"]
        client.post(f"/v1/explain-sessions/{session_id}/commit")
        r = client.post(f"/v1/explain-sessions/{session_id}/commit")
        assert r.status_code == 200
        assert r.json()["status"] == "ready"


# ---------------------------------------------------------------------------
# 4. explain (tap -> HUD display)
# ---------------------------------------------------------------------------

class TestExplainPage:
    def _ready_session(self, client, doc_id) -> int:
        r = client.post("/v1/explain-sessions", json={"document_id": doc_id})
        sid = r.json()["session_id"]
        client.post(f"/v1/explain-sessions/{sid}/commit")
        return sid

    def test_explain_returns_glasses_view(self, client, doc_with_page):
        doc_id, page_index = doc_with_page
        sid = self._ready_session(client, doc_id)

        r = client.get(
            f"/v1/explain-sessions/{sid}/explain",
            params={"page_index": page_index},
        )
        assert r.status_code == 200
        body = r.json()
        assert "glasses_view" in body
        gv = body["glasses_view"]
        assert gv["stage"] == "overview"
        assert isinstance(gv["lines"], list)
        assert len(gv["lines"]) <= 3
        # page label present (P01/1)
        assert "P01" in gv["page_label"]
        # nav has operation contract
        assert "operations" in gv["nav"]
        assert gv["nav"]["operations"]["next_view_page"] == "swipe_left"
        assert gv["nav"]["operations"]["next_stage"] == "swipe_down"

    def test_explain_stage_detail(self, client, doc_with_page):
        doc_id, page_index = doc_with_page
        sid = self._ready_session(client, doc_id)
        r = client.get(
            f"/v1/explain-sessions/{sid}/explain",
            params={"page_index": page_index, "stage": "detail"},
        )
        assert r.status_code == 200
        assert r.json()["glasses_view"]["stage"] == "detail"

    def test_explain_stage_evidence(self, client, doc_with_page):
        doc_id, page_index = doc_with_page
        sid = self._ready_session(client, doc_id)
        r = client.get(
            f"/v1/explain-sessions/{sid}/explain",
            params={"page_index": page_index, "stage": "evidence"},
        )
        assert r.status_code == 200
        assert r.json()["glasses_view"]["stage"] == "evidence"

    def test_explain_invalid_stage_returns_400(self, client, doc_with_page):
        doc_id, _ = doc_with_page
        sid = self._ready_session(client, doc_id)
        r = client.get(
            f"/v1/explain-sessions/{sid}/explain",
            params={"page_index": 0, "stage": "bad_stage"},
        )
        assert r.status_code == 400

    def test_explain_before_commit_returns_409(self, client, doc_with_page):
        doc_id, _ = doc_with_page
        r = client.post("/v1/explain-sessions", json={"document_id": doc_id})
        sid = r.json()["session_id"]
        r = client.get(
            f"/v1/explain-sessions/{sid}/explain",
            params={"page_index": 0},
        )
        assert r.status_code == 409

    def test_explain_unknown_page_returns_404(self, client, doc_with_page):
        doc_id, _ = doc_with_page
        sid = self._ready_session(client, doc_id)
        r = client.get(
            f"/v1/explain-sessions/{sid}/explain",
            params={"page_index": 999},
        )
        assert r.status_code == 404

    def test_explain_status_transitions_to_explaining(self, client, doc_with_page):
        doc_id, page_index = doc_with_page
        sid = self._ready_session(client, doc_id)
        client.get(
            f"/v1/explain-sessions/{sid}/explain",
            params={"page_index": page_index},
        )
        r = client.get(f"/v1/explain-sessions/{sid}/history")
        assert r.json()["status"] == "explaining"


# ---------------------------------------------------------------------------
# 5. swipe-page (teleprompter) test
# ---------------------------------------------------------------------------

class TestExplainViewPage:
    def test_view_page_navigation(self, client, doc_with_page):
        """Check that view_page parameter is honoured and clamped."""
        doc_id, page_index = doc_with_page
        r = client.post("/v1/explain-sessions", json={"document_id": doc_id})
        sid = r.json()["session_id"]
        client.post(f"/v1/explain-sessions/{sid}/commit")

        r0 = client.get(
            f"/v1/explain-sessions/{sid}/explain",
            params={"page_index": page_index, "view_page": 0},
        )
        assert r0.status_code == 200
        gv0 = r0.json()["glasses_view"]
        assert gv0["view_page"] == 0

        # Requesting a very large view_page should be clamped to last page.
        r_big = client.get(
            f"/v1/explain-sessions/{sid}/explain",
            params={"page_index": page_index, "view_page": 9999},
        )
        assert r_big.status_code == 200
        gv_big = r_big.json()["glasses_view"]
        assert gv_big["view_page"] == gv_big["total_view_pages"] - 1


# ---------------------------------------------------------------------------
# 6. history
# ---------------------------------------------------------------------------

class TestExplainHistory:
    def test_history_returns_views(self, client, doc_with_page):
        doc_id, page_index = doc_with_page
        r = client.post("/v1/explain-sessions", json={"document_id": doc_id})
        sid = r.json()["session_id"]
        client.post(f"/v1/explain-sessions/{sid}/commit")
        client.get(
            f"/v1/explain-sessions/{sid}/explain",
            params={"page_index": page_index},
        )

        r = client.get(f"/v1/explain-sessions/{sid}/history")
        assert r.status_code == 200
        body = r.json()
        assert body["session_id"] == sid
        assert body["document_id"] == doc_id
        assert len(body["explained_views"]) == 1
        view = body["explained_views"][0]
        assert view["page_index"] == page_index
        assert view["verdict"] == "HIT"
        assert isinstance(view["hud_lines"], list)

    def test_history_empty_before_explain(self, client, doc_with_page):
        doc_id, _ = doc_with_page
        r = client.post("/v1/explain-sessions", json={"document_id": doc_id})
        sid = r.json()["session_id"]
        r = client.get(f"/v1/explain-sessions/{sid}/history")
        assert r.status_code == 200
        assert r.json()["explained_views"] == []


# ---------------------------------------------------------------------------
# 7. /v1/version includes explainers list
# ---------------------------------------------------------------------------

class TestVersionExplainers:
    def test_version_has_explainers(self, client):
        r = client.get("/v1/version")
        assert r.status_code == 200
        body = r.json()
        assert "explainers" in body
        assert isinstance(body["explainers"], list)
        assert len(body["explainers"]) >= 1
        # local placeholder is always present
        names = [e["name"] for e in body["explainers"]]
        assert "local" in names
        # offline flag
        local = next(e for e in body["explainers"] if e["name"] == "local")
        assert local["offline"] is True
