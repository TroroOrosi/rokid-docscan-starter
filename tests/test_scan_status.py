"""GET /v1/documents/{id}/scan-status — page-state and recovery report.

The report is read-only. It exposes whether the authoritative page image and
recognized text are present so a phone relay can resume safely.
"""

import importlib
import threading
from contextlib import contextmanager

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


def test_finalize_does_not_overwrite_concurrent_page_replacement(client, monkeypatch):
    """A replacement made during analysis remains authoritative."""
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
            return AnalyzerResult(text=ocr_text, summary="stale summary")

        def info(self):
            return {
                "name": self.name,
                "provider_version": self.provider_version,
                "offline": self.offline,
            }

    monkeypatch.setattr(main, "get_analyzer", lambda: BlockingAnalyzer())
    doc_id = _new_doc(client)
    _add_text_page(client, doc_id, 0, "置換前のページ")

    outcome = {}

    def run_finalize():
        outcome["response"] = client.post(f"/v1/documents/{doc_id}/finalize")

    worker = threading.Thread(target=run_finalize)
    worker.start()
    try:
        assert started.wait(timeout=2)
        _add_text_page(client, doc_id, 0, "置換後のページ")
    finally:
        release.set()
        worker.join(timeout=5)

    assert not worker.is_alive()
    response = outcome["response"]
    assert response.status_code == 409
    assert "changed during finalization" in response.json()["detail"]

    conn = main.db.connect()
    try:
        page = conn.execute(
            "SELECT ocr_text, summary FROM pages "
            "WHERE document_id = ? AND page_index = 0",
            (doc_id,),
        ).fetchone()
        document = conn.execute(
            "SELECT status FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
    finally:
        conn.close()

    assert page["ocr_text"] == "置換後のページ"
    assert page["summary"] is None
    assert document["status"] == "open"


def test_finalize_does_not_hold_writer_lock_during_second_analysis(
    client, monkeypatch
):
    """A replacement must finish while the second analyzer call is blocked."""
    import app.main as main
    from app.analyzers.base import AnalyzerResult

    second_started = threading.Event()
    release_second = threading.Event()
    replacement_completed = threading.Event()

    class SecondPageBlockingAnalyzer:
        name = "second-page-blocking-test"
        provider_version = "test-1"
        offline = True

        def __init__(self):
            self.calls = 0

        def analyze(self, *, image_path=None, ocr_text=None, max_summary_len=48):
            self.calls += 1
            if self.calls == 2:
                second_started.set()
                if not release_second.wait(timeout=5):
                    raise AssertionError("test analyzer was not released")
            return AnalyzerResult(
                text=ocr_text,
                summary=f"stale summary {self.calls}",
            )

        def info(self):
            return {
                "name": self.name,
                "provider_version": self.provider_version,
                "offline": self.offline,
            }

    analyzer = SecondPageBlockingAnalyzer()
    monkeypatch.setattr(main, "get_analyzer", lambda: analyzer)
    doc_id = _new_doc(client)
    _add_text_page(client, doc_id, 0, "置換前の1ページ目")
    _add_text_page(client, doc_id, 1, "解析待機する2ページ目")

    outcome = {}

    def run_finalize():
        outcome["finalize"] = client.post(
            f"/v1/documents/{doc_id}/finalize"
        )

    def run_replacement():
        try:
            outcome["replacement"] = client.post(
                f"/v1/documents/{doc_id}/pages",
                data={"page_index": 0, "ocr_text": "置換後の1ページ目"},
            )
        finally:
            replacement_completed.set()

    finalize_worker = threading.Thread(target=run_finalize)
    replacement_worker = threading.Thread(target=run_replacement)
    finalize_worker.start()
    try:
        assert second_started.wait(timeout=2)
        replacement_worker.start()
        assert replacement_completed.wait(timeout=2), (
            "page replacement remained blocked by finalize's writer lock"
        )
    finally:
        release_second.set()
        finalize_worker.join(timeout=5)
        if replacement_worker.ident is not None:
            replacement_worker.join(timeout=5)

    assert not finalize_worker.is_alive()
    assert not replacement_worker.is_alive()
    assert outcome["replacement"].status_code == 201
    response = outcome["finalize"]
    assert response.status_code == 409
    assert "changed during finalization" in response.json()["detail"]

    conn = main.db.connect()
    try:
        pages = conn.execute(
            "SELECT page_index, ocr_text, summary FROM pages "
            "WHERE document_id = ? ORDER BY page_index",
            (doc_id,),
        ).fetchall()
        document = conn.execute(
            "SELECT status FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
    finally:
        conn.close()

    assert [dict(page) for page in pages] == [
        {
            "page_index": 0,
            "ocr_text": "置換後の1ページ目",
            "summary": None,
        },
        {
            "page_index": 1,
            "ocr_text": "解析待機する2ページ目",
            "summary": None,
        },
    ]
    assert document["status"] == "open"


def test_finalize_stops_before_analyzing_more_pages_after_replacement(
    client, monkeypatch
):
    """Once its snapshot is stale, finalize must not bill later pages."""
    import app.main as main
    from app.analyzers.base import AnalyzerResult

    first_started = threading.Event()
    release_first = threading.Event()

    class FirstPageBlockingAnalyzer:
        name = "first-page-blocking-test"
        provider_version = "test-1"
        offline = False

        def __init__(self):
            self.calls = 0

        def analyze(self, *, image_path=None, ocr_text=None, max_summary_len=48):
            self.calls += 1
            if self.calls == 1:
                first_started.set()
                if not release_first.wait(timeout=5):
                    raise AssertionError("test analyzer was not released")
            return AnalyzerResult(text=ocr_text, summary=f"summary {self.calls}")

        def info(self):
            return {
                "name": self.name,
                "provider_version": self.provider_version,
                "offline": self.offline,
            }

    analyzer = FirstPageBlockingAnalyzer()
    monkeypatch.setattr(main, "get_analyzer", lambda: analyzer)
    doc_id = _new_doc(client)
    for page_index in range(3):
        _add_text_page(client, doc_id, page_index, f"元の{page_index + 1}ページ目")

    outcome = {}

    def run_finalize():
        outcome["response"] = client.post(f"/v1/documents/{doc_id}/finalize")

    worker = threading.Thread(target=run_finalize)
    worker.start()
    try:
        assert first_started.wait(timeout=2)
        _add_text_page(client, doc_id, 0, "置換後の1ページ目")
    finally:
        release_first.set()
        worker.join(timeout=5)

    assert not worker.is_alive()
    assert outcome["response"].status_code == 409
    assert "changed during finalization" in outcome["response"].json()["detail"]
    assert analyzer.calls == 1


def test_finalize_ignores_other_document_commits_during_analysis(
    client, monkeypatch
):
    """SQLite data-version changes are only conflicts for the same snapshot."""
    import app.main as main
    from app.analyzers.base import AnalyzerResult

    started = threading.Event()
    release = threading.Event()

    class BlockingAnalyzer:
        name = "other-document-write-test"
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
    finalized_doc_id = _new_doc(client, "解析対象")
    other_doc_id = _new_doc(client, "別文書")
    _add_text_page(client, finalized_doc_id, 0, "解析するページ")
    outcome = {}

    def run_finalize():
        outcome["response"] = client.post(
            f"/v1/documents/{finalized_doc_id}/finalize"
        )

    worker = threading.Thread(target=run_finalize)
    worker.start()
    try:
        assert started.wait(timeout=2)
        _add_text_page(client, other_doc_id, 0, "別文書のページ")
    finally:
        release.set()
        worker.join(timeout=5)

    assert not worker.is_alive()
    assert outcome["response"].status_code == 200
    assert outcome["response"].json()["status"] == "ready"


def test_finalize_page_change_wins_over_inflight_analyzer_failure(
    client, monkeypatch
):
    """A stale snapshot keeps its 409 even when the active analyzer fails."""
    import app.main as main
    from app.analyzers.base import AnalyzerResult

    second_started = threading.Event()
    release_second = threading.Event()

    class FailingBlockedSecondAnalyzer:
        name = "failing-blocked-second-test"
        provider_version = "test-1"
        offline = False

        def __init__(self):
            self.calls = 0

        def analyze(self, *, image_path=None, ocr_text=None, max_summary_len=48):
            self.calls += 1
            if self.calls == 2:
                second_started.set()
                if not release_second.wait(timeout=5):
                    raise AssertionError("test analyzer was not released")
                raise RuntimeError("second page analysis failed")
            return AnalyzerResult(text=ocr_text, summary="first summary")

        def info(self):
            return {
                "name": self.name,
                "provider_version": self.provider_version,
                "offline": self.offline,
            }

    analyzer = FailingBlockedSecondAnalyzer()
    monkeypatch.setattr(main, "get_analyzer", lambda: analyzer)
    doc_id = _new_doc(client)
    _add_text_page(client, doc_id, 0, "置換前の1ページ目")
    _add_text_page(client, doc_id, 1, "失敗する2ページ目")

    outcome = {}

    def run_finalize():
        try:
            outcome["response"] = client.post(
                f"/v1/documents/{doc_id}/finalize"
            )
        except Exception as exc:  # TestClient re-raises unhandled app errors.
            outcome["error"] = exc

    worker = threading.Thread(target=run_finalize)
    worker.start()
    try:
        assert second_started.wait(timeout=2)
        _add_text_page(client, doc_id, 0, "置換後の1ページ目")
    finally:
        release_second.set()
        worker.join(timeout=5)

    assert not worker.is_alive()
    assert "error" not in outcome
    response = outcome["response"]
    assert response.status_code == 409
    assert "changed during finalization" in response.json()["detail"]
    assert analyzer.calls == 2


def test_concurrent_document_finalizers_share_analyzer_work(client, monkeypatch):
    """A double-fired document finalize must not double-charge its analyzer."""
    import app.main as main
    from app.analyzers.base import AnalyzerResult

    first_started = threading.Event()
    release = threading.Event()
    duplicate_started = threading.Event()
    second_attempted = threading.Event()
    call_guard = threading.Lock()

    class BlockingAnalyzer:
        name = "concurrent-finalize-test"
        provider_version = "test-1"
        offline = False

        def __init__(self):
            self.calls = 0

        def analyze(self, *, image_path=None, ocr_text=None, max_summary_len=48):
            with call_guard:
                self.calls += 1
                call_number = self.calls
            if call_number == 1:
                first_started.set()
            elif not release.is_set():
                duplicate_started.set()
            if not release.wait(timeout=5):
                raise AssertionError("test analyzer was not released")
            return AnalyzerResult(
                text=ocr_text,
                summary=f"summary {call_number}",
            )

        def info(self):
            return {
                "name": self.name,
                "provider_version": self.provider_version,
                "offline": self.offline,
            }

    analyzer = BlockingAnalyzer()
    monkeypatch.setattr(main, "get_analyzer", lambda: analyzer)
    real_mutex = main._document_finalize_mutex
    attempts = 0
    attempt_guard = threading.Lock()

    @contextmanager
    def observed_mutex(document_id):
        nonlocal attempts
        with attempt_guard:
            attempts += 1
            if attempts == 2:
                second_attempted.set()
        with real_mutex(document_id):
            yield

    monkeypatch.setattr(main, "_document_finalize_mutex", observed_mutex)
    doc_id = _new_doc(client)
    _add_text_page(client, doc_id, 0, "1ページ目")
    _add_text_page(client, doc_id, 1, "2ページ目")
    outcome = {}

    def run_finalize(key):
        outcome[key] = client.post(f"/v1/documents/{doc_id}/finalize")

    first_worker = threading.Thread(target=run_finalize, args=("first",))
    second_worker = threading.Thread(target=run_finalize, args=("second",))
    first_worker.start()
    try:
        assert first_started.wait(timeout=2)
        second_worker.start()
        assert second_attempted.wait(timeout=2)
        assert not duplicate_started.wait(timeout=0.5), (
            "a concurrent finalize reached the paid analyzer"
        )
    finally:
        release.set()
        first_worker.join(timeout=5)
        if second_worker.ident is not None:
            second_worker.join(timeout=5)

    assert not first_worker.is_alive()
    assert not second_worker.is_alive()
    assert outcome["first"].status_code == outcome["second"].status_code == 200
    assert analyzer.calls == 2
    with main._finalize_mutex_registry_guard:
        assert doc_id not in main._finalize_mutex_registry


def test_finalize_analyzer_failure_does_not_commit_partial_page_updates(
    client, monkeypatch
):
    """A later analyzer failure must leave every page and status untouched."""
    import app.main as main
    from app.analyzers.base import AnalyzerResult

    class FailingSecondAnalyzer:
        name = "failing-second-test"
        provider_version = "test-1"
        offline = True

        def __init__(self):
            self.calls = 0

        def analyze(self, *, image_path=None, ocr_text=None, max_summary_len=48):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("second page analysis failed")
            return AnalyzerResult(
                text="rewritten first page",
                summary="partial summary",
                extras={"image_analyzed": True},
            )

        def info(self):
            return {
                "name": self.name,
                "provider_version": self.provider_version,
                "offline": self.offline,
            }

    analyzer = FailingSecondAnalyzer()
    monkeypatch.setattr(main, "get_analyzer", lambda: analyzer)
    doc_id = _new_doc(client)
    _add_text_page(client, doc_id, 0, "元の1ページ目")
    _add_text_page(client, doc_id, 1, "失敗する2ページ目")

    # Starlette/AnyIO versions wrap application exceptions differently.
    # The HTTP failure and complete database rollback are the public contract.
    with TestClient(main.app, raise_server_exceptions=False) as failing_client:
        response = failing_client.post(f"/v1/documents/{doc_id}/finalize")
    assert response.status_code == 500
    assert analyzer.calls == 2

    conn = main.db.connect()
    try:
        pages = conn.execute(
            "SELECT page_index, ocr_text, summary FROM pages "
            "WHERE document_id = ? ORDER BY page_index",
            (doc_id,),
        ).fetchall()
        document = conn.execute(
            "SELECT status FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
    finally:
        conn.close()

    assert [dict(page) for page in pages] == [
        {"page_index": 0, "ocr_text": "元の1ページ目", "summary": None},
        {"page_index": 1, "ocr_text": "失敗する2ページ目", "summary": None},
    ]
    assert document["status"] == "open"


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
