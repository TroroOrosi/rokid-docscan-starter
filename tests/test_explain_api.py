"""Tests for /v1/explain-sessions endpoints (v1.7 scan-free design).

Covers the full UX flow:
  1. Create document + add page(s) + finalize
  2. Create explain session (status=ready, current_page_index=0 — no scan phase)
  3. GET /explain -> glasses_view for current page (no page_index param)
  4. POST /next-page / /prev-page -> counter navigation, HUD ack
  5. Multi-page: register 3 pages, navigate through all, verify per-page explain
  6. GET /history -> explained_views list
  7. /v1/version includes explainers

All tests are offline (local placeholder explainer, no external credentials).
Uses the same conftest.py fixtures as the main test suite.
"""

from __future__ import annotations

import io

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
    # db/main import these constants by value; patch the actual endpoint
    # references too so this module is isolated and order-independent.
    monkeypatch.setattr("app.db.DB_PATH", db_file)
    monkeypatch.setattr("app.main.IMAGE_DIR", img_dir)
    init_db(db_file)
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# fixture helpers
# ---------------------------------------------------------------------------

def _create_doc_with_pages(client, n_pages: int = 1) -> int:
    """Create a document with n_pages pages and finalize it. Return document_id."""
    r = client.post("/v1/documents", json={"title": "テスト資料"})
    assert r.status_code == 201
    doc_id = r.json()["document_id"]

    colors = [(200, 100, 50), (50, 200, 100), (100, 50, 200), (200, 200, 50), (50, 200, 200)]
    for i in range(n_pages):
        color = colors[i % len(colors)]
        r = client.post(
            f"/v1/documents/{doc_id}/pages",
            data={"page_index": i, "ocr_text": f"第{i+1}ページ テスト問題 解説内容"},
            files={"image": (f"p{i}.png", _png_bytes(color=color), "image/png")},
        )
        assert r.status_code == 201, f"page {i} upload failed: {r.text}"

    r = client.post(f"/v1/documents/{doc_id}/finalize")
    assert r.status_code == 200
    return doc_id


@pytest.fixture()
def doc_1page(client):
    """Document with 1 page."""
    return _create_doc_with_pages(client, n_pages=1)


@pytest.fixture()
def doc_3pages(client):
    """Document with 3 pages."""
    return _create_doc_with_pages(client, n_pages=3)


def _create_session(client, doc_id: int) -> int:
    """Create an explain session and return session_id."""
    r = client.post("/v1/explain-sessions", json={"document_id": doc_id})
    assert r.status_code == 201
    return r.json()["session_id"]


# ---------------------------------------------------------------------------
# 1. session creation (v1.7: starts ready, no scan phase)
# ---------------------------------------------------------------------------

class TestCreateExplainSession:
    def test_create_returns_ready(self, client, doc_1page):
        r = client.post("/v1/explain-sessions", json={"document_id": doc_1page})
        assert r.status_code == 201
        body = r.json()
        # v1.7: no scanning phase; session is immediately ready
        assert body["status"] == "ready"
        assert body["current_page_index"] == 0
        assert body["total_pages"] == 1
        assert "operations" in body

    def test_create_multipage_total_pages(self, client, doc_3pages):
        r = client.post("/v1/explain-sessions", json={"document_id": doc_3pages})
        assert r.status_code == 201
        body = r.json()
        assert body["total_pages"] == 3
        assert body["current_page_index"] == 0

    def test_create_doc_not_found(self, client):
        r = client.post("/v1/explain-sessions", json={"document_id": 9999})
        assert r.status_code == 404

    def test_create_rejects_unfinalized_document(self, client):
        r = client.post("/v1/documents", json={"title": "未確定資料"})
        doc_id = r.json()["document_id"]
        r = client.post("/v1/explain-sessions", json={"document_id": doc_id})
        assert r.status_code == 400
        assert "finalized" in r.json()["detail"]


# ---------------------------------------------------------------------------
# 2. explain (tap -> HUD display, no page_index param)
# ---------------------------------------------------------------------------

class TestExplainPage:
    def test_explain_returns_glasses_view(self, client, doc_1page):
        sid = _create_session(client, doc_1page)
        # No page_index param — server uses current_page_index
        r = client.get(f"/v1/explain-sessions/{sid}/explain")
        assert r.status_code == 200
        body = r.json()
        assert "glasses_view" in body
        assert body["current_page_index"] == 0
        gv = body["glasses_view"]
        assert gv["stage"] == "overview"
        assert isinstance(gv["lines"], list)
        assert len(gv["lines"]) <= 3
        # page label present (P01/1)
        assert "P01" in gv["page_label"]
        # navigation operations
        assert "operations" in gv["nav"]
        ops = gv["nav"]["operations"]
        assert ops["next_view_page"] == "two_finger_swipe_down"
        assert ops["next_stage"] == "single_tap"
        assert ops["next_doc_page"] == "two_finger_swipe_left"
        assert ops["prev_doc_page"] == "two_finger_swipe_right"

    def test_explain_stage_detail(self, client, doc_1page):
        sid = _create_session(client, doc_1page)
        r = client.get(f"/v1/explain-sessions/{sid}/explain", params={"stage": "detail"})
        assert r.status_code == 200
        assert r.json()["glasses_view"]["stage"] == "detail"

    def test_explain_stage_evidence(self, client, doc_1page):
        sid = _create_session(client, doc_1page)
        r = client.get(f"/v1/explain-sessions/{sid}/explain", params={"stage": "evidence"})
        assert r.status_code == 200
        assert r.json()["glasses_view"]["stage"] == "evidence"

    def test_explain_invalid_stage_returns_400(self, client, doc_1page):
        sid = _create_session(client, doc_1page)
        r = client.get(f"/v1/explain-sessions/{sid}/explain", params={"stage": "bad_stage"})
        assert r.status_code == 400

    def test_explain_status_transitions_to_explaining(self, client, doc_1page):
        sid = _create_session(client, doc_1page)
        client.get(f"/v1/explain-sessions/{sid}/explain")
        r = client.get(f"/v1/explain-sessions/{sid}/history")
        assert r.json()["status"] == "explaining"

    def test_explain_session_not_found_returns_404(self, client):
        r = client.get("/v1/explain-sessions/9999/explain")
        assert r.status_code == 404

    def test_stage_and_scroll_reuse_one_provider_result(
        self, client, doc_1page, monkeypatch
    ):
        from app.explainer import ExplainResult, Explainer
        from app.explainers import register_explainer

        class CountingExplainer(Explainer):
            name = "counting-test"
            provider_version = "test-1"
            offline = False
            calls = 0

            def explain(self, req):
                type(self).calls += 1
                n = type(self).calls
                return ExplainResult(
                    lines=[f"overview-{n}", "", ""],
                    detail=f"detail-{n}",
                    confidence=0.8,
                    extras={"call": n},
                )

        CountingExplainer.calls = 0
        register_explainer(CountingExplainer(), replace=True)
        monkeypatch.setenv("ROKID_EXPLAINER", "counting-test")
        sid = _create_session(client, doc_1page)

        first = client.get(f"/v1/explain-sessions/{sid}/explain").json()
        scrolled = client.get(
            f"/v1/explain-sessions/{sid}/explain", params={"view_page": 999}
        ).json()
        detail = client.get(
            f"/v1/explain-sessions/{sid}/explain", params={"stage": "detail"}
        ).json()

        assert CountingExplainer.calls == 1
        assert first["cached"] is False
        assert scrolled["cached"] is detail["cached"] is True
        assert first["explainer"] == scrolled["explainer"] == detail["explainer"]
        assert first["evidence_pages"] and all(
            page == 1 for page in first["evidence_pages"]
        )
        assert all(
            set(ref) == {"document_id", "page_number"}
            and ref["page_number"] == 1
            for ref in first["evidence_refs"]
        )
        assert len({
            (ref["document_id"], ref["page_number"])
            for ref in first["evidence_refs"]
        }) == len(first["evidence_refs"])

        history = client.get(f"/v1/explain-sessions/{sid}/history").json()
        assert len(history["explained_views"]) == 1
        visit = history["explained_views"][0]
        assert visit["detail"] == "detail-1"
        assert visit["result_extras"] == {"call": 1}
        assert visit["explainer"]["name"] == "counting-test"

    def test_page_reread_refreshes_the_visit_cache(
        self, client, doc_1page, monkeypatch
    ):
        """Re-reading a page (same index, new text) must re-explain, not serve
        the pre-correction cache."""
        from app.explainer import ExplainResult, Explainer
        from app.explainers import register_explainer

        class CountingExplainer(Explainer):
            name = "reread-count-test"
            provider_version = "test-1"
            offline = False
            calls = 0

            def explain(self, req):
                type(self).calls += 1
                n = type(self).calls
                return ExplainResult(
                    lines=[f"overview-{n}", "", ""],
                    detail=f"detail-{n}",
                    confidence=0.8,
                    extras={"call": n},
                )

        CountingExplainer.calls = 0
        register_explainer(CountingExplainer(), replace=True)
        monkeypatch.setenv("ROKID_EXPLAINER", "reread-count-test")
        sid = _create_session(client, doc_1page)

        first = client.get(f"/v1/explain-sessions/{sid}/explain").json()
        assert first["cached"] is False and CountingExplainer.calls == 1

        # Correct the page in place (finalized doc, no reviewing exam session).
        r = client.post(
            f"/v1/documents/{doc_1page}/pages",
            data={"page_index": 0, "ocr_text": "訂正後の本文 まったく違う内容"},
            files={"image": ("p0.png", _png_bytes(color=(9, 9, 9)), "image/png")},
        )
        assert r.status_code == 201 and r.json()["replaced"] is True

        # Same page index, but its content changed -> refresh once.
        after = client.get(f"/v1/explain-sessions/{sid}/explain").json()
        assert after["cached"] is False
        assert CountingExplainer.calls == 2

        # Unchanged re-request of the corrected page is cached again (no churn).
        again = client.get(f"/v1/explain-sessions/{sid}/explain").json()
        assert again["cached"] is True
        assert CountingExplainer.calls == 2

        # The served/stored result is the post-correction one, not the stale row.
        history = client.get(f"/v1/explain-sessions/{sid}/history").json()
        assert history["explained_views"][-1]["detail"] == "detail-2"


# ---------------------------------------------------------------------------
# 3. next-page / prev-page navigation
# ---------------------------------------------------------------------------

class TestNextPrevPage:
    def test_next_page_increments_index(self, client, doc_3pages):
        sid = _create_session(client, doc_3pages)
        r = client.post(f"/v1/explain-sessions/{sid}/next-page")
        assert r.status_code == 200
        body = r.json()
        assert body["current_page_index"] == 1
        assert body["total_pages"] == 3
        assert body["at_last"] is False
        assert "nav_ack" in body
        # HUD ack shows next arrow
        lines = body["nav_ack"]["lines"]
        assert any("P02" in line for line in lines)

    def test_prev_page_decrements_index(self, client, doc_3pages):
        sid = _create_session(client, doc_3pages)
        client.post(f"/v1/explain-sessions/{sid}/next-page")  # -> page 1
        r = client.post(f"/v1/explain-sessions/{sid}/prev-page")
        assert r.status_code == 200
        body = r.json()
        assert body["current_page_index"] == 0
        assert body["at_first"] is True

    def test_next_page_clamped_at_last(self, client, doc_3pages):
        """Pressing next at the last page stays at last page (no IndexError)."""
        sid = _create_session(client, doc_3pages)
        for _ in range(10):  # far beyond total_pages=3
            client.post(f"/v1/explain-sessions/{sid}/next-page")
        r = client.post(f"/v1/explain-sessions/{sid}/next-page")
        assert r.status_code == 200
        assert r.json()["current_page_index"] == 2  # last page is index 2
        assert r.json()["at_last"] is True

    def test_prev_page_clamped_at_first(self, client, doc_3pages):
        """Pressing prev at page 0 stays at 0."""
        sid = _create_session(client, doc_3pages)
        r = client.post(f"/v1/explain-sessions/{sid}/prev-page")
        assert r.status_code == 200
        assert r.json()["current_page_index"] == 0
        assert r.json()["at_first"] is True

    def test_full_navigation_sequence(self, client, doc_3pages):
        """Navigate 0 -> 1 -> 2 -> 1 -> 0 and verify each step."""
        sid = _create_session(client, doc_3pages)
        for expected in [1, 2]:
            r = client.post(f"/v1/explain-sessions/{sid}/next-page")
            assert r.json()["current_page_index"] == expected
        for expected in [1, 0]:
            r = client.post(f"/v1/explain-sessions/{sid}/prev-page")
            assert r.json()["current_page_index"] == expected


# ---------------------------------------------------------------------------
# 4. multi-page: register 3 pages, navigate and explain each
#    verify that each page's explain returns the correct page label
# ---------------------------------------------------------------------------

class TestMultiPageExplain:
    def test_explain_each_page_has_correct_label(self, client, doc_3pages):
        """Navigate to each page and verify page label in glasses_view."""
        sid = _create_session(client, doc_3pages)

        for page_num in [1, 2, 3]:  # P01, P02, P03
            r = client.get(f"/v1/explain-sessions/{sid}/explain")
            assert r.status_code == 200
            body = r.json()
            assert body["current_page_index"] == page_num - 1
            gv = body["glasses_view"]
            assert f"P0{page_num}" in gv["page_label"], (
                f"Expected P0{page_num} in page_label, got: {gv['page_label']}"
            )
            if page_num < 3:
                client.post(f"/v1/explain-sessions/{sid}/next-page")

    def test_all_pages_appear_in_history(self, client, doc_3pages):
        """After explaining all 3 pages, history should record all 3."""
        sid = _create_session(client, doc_3pages)

        for i in range(3):
            r = client.get(f"/v1/explain-sessions/{sid}/explain")
            assert r.status_code == 200
            if i < 2:
                client.post(f"/v1/explain-sessions/{sid}/next-page")

        r = client.get(f"/v1/explain-sessions/{sid}/history")
        assert r.status_code == 200
        body = r.json()
        explained_indices = [v["page_index"] for v in body["explained_views"]]
        assert 0 in explained_indices, "Page 0 missing from history"
        assert 1 in explained_indices, "Page 1 missing from history"
        assert 2 in explained_indices, "Page 2 missing from history"

    def test_explain_returns_total_doc_pages(self, client, doc_3pages):
        """total_doc_pages in response must equal registered page count."""
        sid = _create_session(client, doc_3pages)
        r = client.get(f"/v1/explain-sessions/{sid}/explain")
        assert r.status_code == 200
        assert r.json()["total_doc_pages"] == 3

    def test_navigate_then_explain_shows_correct_page(self, client, doc_3pages):
        """next-page then explain must show P02, not P01."""
        sid = _create_session(client, doc_3pages)
        client.post(f"/v1/explain-sessions/{sid}/next-page")  # -> page 1
        r = client.get(f"/v1/explain-sessions/{sid}/explain")
        assert r.status_code == 200
        body = r.json()
        assert body["current_page_index"] == 1
        assert "P02" in body["glasses_view"]["page_label"]


# ---------------------------------------------------------------------------
# 5. teleprompter view_page navigation
# ---------------------------------------------------------------------------

class TestExplainViewPage:
    def test_view_page_navigation(self, client, doc_1page):
        """view_page parameter is honoured and large values are clamped."""
        sid = _create_session(client, doc_1page)

        r0 = client.get(f"/v1/explain-sessions/{sid}/explain", params={"view_page": 0})
        assert r0.status_code == 200
        assert r0.json()["glasses_view"]["view_page"] == 0

        r_big = client.get(
            f"/v1/explain-sessions/{sid}/explain",
            params={"view_page": 9999},
        )
        assert r_big.status_code == 200
        gv_big = r_big.json()["glasses_view"]
        assert gv_big["view_page"] == gv_big["total_view_pages"] - 1


# ---------------------------------------------------------------------------
# 6. history
# ---------------------------------------------------------------------------

class TestExplainHistory:
    def test_history_empty_before_explain(self, client, doc_1page):
        sid = _create_session(client, doc_1page)
        r = client.get(f"/v1/explain-sessions/{sid}/history")
        assert r.status_code == 200
        assert r.json()["explained_views"] == []

    def test_history_records_after_explain(self, client, doc_1page):
        sid = _create_session(client, doc_1page)
        client.get(f"/v1/explain-sessions/{sid}/explain")

        r = client.get(f"/v1/explain-sessions/{sid}/history")
        assert r.status_code == 200
        body = r.json()
        assert body["session_id"] == sid
        assert body["document_id"] == doc_1page
        assert len(body["explained_views"]) == 1
        view = body["explained_views"][0]
        assert view["page_index"] == 0
        assert isinstance(view["hud_lines"], list)
        assert isinstance(view["detail"], str)

    def test_history_includes_current_page_index(self, client, doc_3pages):
        sid = _create_session(client, doc_3pages)
        client.post(f"/v1/explain-sessions/{sid}/next-page")  # -> page 1
        client.get(f"/v1/explain-sessions/{sid}/explain")

        r = client.get(f"/v1/explain-sessions/{sid}/history")
        assert r.status_code == 200
        body = r.json()
        assert body["current_page_index"] == 1
        assert body["explained_views"][0]["page_index"] == 1

    def test_history_dedupes_same_page_rereads(self, client, doc_1page):
        # Scroll/stage churn on one page is one visit, not three.
        sid = _create_session(client, doc_1page)
        client.get(f"/v1/explain-sessions/{sid}/explain")
        client.get(f"/v1/explain-sessions/{sid}/explain", params={"view_page": 1})
        client.get(f"/v1/explain-sessions/{sid}/explain", params={"stage": "detail"})

        r = client.get(f"/v1/explain-sessions/{sid}/history")
        assert len(r.json()["explained_views"]) == 1

    def test_history_keeps_revisits_as_new_entries(self, client, doc_3pages):
        # p0 -> p1 -> back to p0: the return visit is a NEW history entry.
        sid = _create_session(client, doc_3pages)
        client.get(f"/v1/explain-sessions/{sid}/explain")
        client.post(f"/v1/explain-sessions/{sid}/next-page")
        client.get(f"/v1/explain-sessions/{sid}/explain")
        client.post(f"/v1/explain-sessions/{sid}/prev-page")
        client.get(f"/v1/explain-sessions/{sid}/explain")

        r = client.get(f"/v1/explain-sessions/{sid}/history")
        indices = [v["page_index"] for v in r.json()["explained_views"]]
        assert indices.count(0) == 2 and indices.count(1) == 1


# ---------------------------------------------------------------------------
# 6b. concurrency guard on the visit insert (unit-level, deterministic)
# ---------------------------------------------------------------------------

def test_persist_explain_visit_dedups_race_keeps_revisits(tmp_path, monkeypatch):
    from app.explainer import ExplainResult
    from app.main import _persist_explain_visit
    import app.db as db

    db_file = tmp_path / "visits.db"
    monkeypatch.setattr("app.db.DB_PATH", db_file)
    db.init_db(db_file)
    conn = db.connect(db_file)
    conn.execute("INSERT INTO documents (title) VALUES ('d')")
    doc_id = conn.execute("SELECT id FROM documents").fetchone()["id"]
    conn.execute("INSERT INTO explain_sessions (document_id) VALUES (?)", (doc_id,))
    sid = conn.execute("SELECT id FROM explain_sessions").fetchone()["id"]
    conn.commit()

    def _res(tag):
        return ExplainResult(lines=[tag, "", ""], detail=tag, confidence=0.9, extras={})

    sig = "sig-A"
    # Winner records the fresh-page visit (snapshot last_id=0).
    inserted, row = _persist_explain_visit(
        conn, session_id=sid, page_index=0, page_signature=sig, last_id=0,
        result=_res("first"), retrieved_hits=[], explainer_info={"name": "x"},
    )
    conn.commit()
    assert inserted is True and row["detail"] == "first"
    first_id = row["id"]

    # Concurrent loser: same pre-compute snapshot -> guard sees the winner row,
    # inserts nothing, and returns the winner's row to serve.
    inserted2, row2 = _persist_explain_visit(
        conn, session_id=sid, page_index=0, page_signature=sig, last_id=0,
        result=_res("dup"), retrieved_hits=[], explainer_info={"name": "x"},
    )
    conn.commit()
    assert inserted2 is False
    assert row2["id"] == first_id and row2["detail"] == "first"
    assert conn.execute("SELECT COUNT(*) c FROM explain_views").fetchone()["c"] == 1

    # Genuine revisit (snapshot taken after the prior same-page row) still
    # records a new visit — the guard must not collapse history.
    inserted3, row3 = _persist_explain_visit(
        conn, session_id=sid, page_index=0, page_signature=sig, last_id=first_id,
        result=_res("revisit"), retrieved_hits=[], explainer_info={"name": "x"},
    )
    conn.commit()
    assert inserted3 is True and row3["detail"] == "revisit" and row3["id"] != first_id
    assert conn.execute("SELECT COUNT(*) c FROM explain_views").fetchone()["c"] == 2
    conn.close()


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
        names = [e["name"] for e in body["explainers"]]
        assert "local" in names
        local = next(e for e in body["explainers"] if e["name"] == "local")
        assert local["offline"] is True
