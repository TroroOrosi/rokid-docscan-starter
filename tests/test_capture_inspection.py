"""Opt-in source-bound diagnostics; no device, account or model calls."""
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import threading
import zipfile

import pytest
from PIL import Image

from app.work_bridge import WorkStore
from tests.test_work_bridge import client as _client_fixture
from tests.test_capture_video_upload import setup as _video_setup_fixture
from tests.test_capture_video import movie as _movie_fixture
from tests.test_chatgpt_work_web import browser_page as _browser_page_fixture, page as _page_fixture

client = _client_fixture
video_setup = _video_setup_fixture
movie = _movie_fixture
browser_page = _browser_page_fixture
page = _page_fixture


def owner(generation=1, capture="capture-a"):
    return {"kind": "native_capture", "device_id": "glasses", "generation": generation,
            "document_id": 1, "local_session_id": "11111111-1111-4111-8111-111111111111",
            "capture_id": capture, "canonical_image_sha256": "a" * 64}


def enqueue(store, capture="capture-a", generation=1):
    return store.enqueue_capture_inspection(owner=owner(generation, capture),
        source={"kind": "native_capture", "path": str(Path("canonical.png")), "sha256": "a" * 64})


def test_diagnostic_store_does_not_allocate_answer_owner_and_replay_does_not_replace_current(tmp_path):
    store = WorkStore(tmp_path)
    first = enqueue(store)
    second = enqueue(store, "capture-b")
    assert enqueue(WorkStore(tmp_path)) == first
    assert store.current_capture_inspection(second["inspection_id"])
    assert not store.current_capture_inspection(first["inspection_id"])
    assert store.list_jobs()["jobs"] == []
    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM inspection_images").fetchone()[0] == 0


def test_diagnostic_queue_overflow_is_explicit_and_current_owner_still_advances(tmp_path):
    store = WorkStore(tmp_path)
    requests = [enqueue(store, f"capture-{index}") for index in range(4)]
    assert [request["status"] for request in requests] == ["queued"] * 3 + ["deferred_queue_full"]
    assert store.current_capture_inspection(requests[-1]["inspection_id"])
    assert not store.current_capture_inspection(requests[0]["inspection_id"])
    assert store.capture_inspection_counts("glasses")["overflow"] == 1
    assert enqueue(store, "capture-3") == requests[-1]
    assert store.capture_inspection_counts("glasses")["overflow"] == 1


def test_diagnostic_generation_budget_is_bounded_without_reopening_old_identity(tmp_path):
    store = WorkStore(tmp_path)
    for index in range(128):
        enqueue(store, f"capture-{index}")
    held = enqueue(store, "over-budget")
    assert held["status"] == "deferred_capacity" and held["inspection_id"] is None
    fresh = enqueue(store, "new-generation", generation=2)
    assert fresh["status"] == "queued"
    assert store.current_capture_inspection(fresh["inspection_id"])
    old = enqueue(store, "capture-0", generation=1)
    assert old["status"] == "stale_generation"
    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM capture_inspections").fetchone()[0] <= 129


def test_diagnostic_manifest_and_result_are_immutable_and_separate_from_quality(tmp_path):
    store = WorkStore(tmp_path)
    task = enqueue(store)
    request = {"manifest_sha256": hashlib.sha256(b"packet").hexdigest(), "images": []}
    store.prepare_capture_inspection(task["inspection_id"], request)
    store.finish_capture_inspection(task["inspection_id"], status="completed", result={"diagnostic": "only"})
    with pytest.raises(ValueError):
        store.prepare_capture_inspection(task["inspection_id"], {**request, "images": ["changed"]})
    with pytest.raises(ValueError):
        store.finish_capture_inspection(task["inspection_id"], status="completed", result={"diagnostic": "changed"})
    assert WorkStore(tmp_path).get_capture_inspection(task["inspection_id"])["result"] == {"diagnostic": "only"}


def test_origin_cannot_rebind_local_uuid_and_child_result_survives_restart(tmp_path):
    store = WorkStore(tmp_path)
    origin = {"device_id": "glasses", "generation": 1, "document_id": 1,
              "local_session_id": "11111111-1111-4111-8111-111111111111"}
    store.bind_capture_inspection_origin(origin)
    with pytest.raises(ValueError):
        store.bind_capture_inspection_origin({**origin, "generation": 2})
    task = enqueue(store)
    child_id = "b" * 64
    store.prepare_capture_inspection_part(task["inspection_id"], child_id, {"manifest_sha256": "c" * 64})
    store.finish_capture_inspection_part(child_id, {"status": "diagnostic_only"})
    restored = WorkStore(tmp_path).get_capture_inspection_part(child_id)
    assert restored["inspection_id"] == task["inspection_id"]
    assert restored["result"] == {"status": "diagnostic_only"}
    with pytest.raises(ValueError):
        store.finish_capture_inspection_part(child_id, {"status": "eligible"})


@pytest.fixture
def native_task(client, monkeypatch):
    from app import capture_inspection as inspection, config
    from tests.test_native_capture_upload import native_image, provenance, create_document, upload
    monkeypatch.setenv("ROKID_CAPTURE_INSPECTION", "1")
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    monkeypatch.setattr(inspection, "wake_worker", lambda: None)
    raw = native_image()
    meta = provenance(raw)
    document = create_document(client)
    state = {"device_id": "glasses", "generation": 4, "sequence": 1, "phase": "capturing"}
    response = client.post("/v1/glasses/state", json=state)
    assert response.status_code == 200
    receipt = upload(client, document, raw, meta).json()
    origin = {"schema": 1, "device_id": "glasses", "generation": 4, "document_id": document,
              "local_session_id": meta["local_session_id"], "capture_id": meta["capture_id"]}
    task = inspection.register_native(document, 0, json.dumps(origin), "testclient")
    return client, config, receipt, origin, task


def test_native_without_explicit_origin_never_guesses_owner(native_task):
    from app import capture_inspection as inspection
    _, _, receipt, origin, task = native_task
    assert task["status"] == "queued"
    assert task["owner"]["capture_id"] == receipt["capture_provenance"]["capture_id"]
    assert inspection.register_native(origin["document_id"], 0, None, "testclient")["status"] == "unbound"
    assert inspection.register_native(origin["document_id"], 0, json.dumps({**origin, "generation": 5}), "testclient")["status"] == "unbound"
    assert inspection.register_native(origin["document_id"], 0, json.dumps(origin), "untrusted-peer")["status"] == "unbound"


class DiagnosticClient:
    calls = 0

    def pending_inspection_owner(self):
        return None

    def complete_inspection(self, **kwargs):
        self.calls += 1
        kwargs["before_submit"]()
        request = json.loads(kwargs["prompt"].split("\nInspection request:\n")[1])
        files = list(kwargs["files"]())
        assert len(files) == 1 and len(files[0]["buffer"]) <= 16 * 1024 * 1024
        return {"inspection_id": kwargs["inspection_id"], "manifest_sha256": kwargs["manifest_sha256"],
                "inspection": {"observations": [{"image_id": image["image_id"],
                    "status": "no_issue_observed", "image_viewer_used": True, "reasons": []}
                    for image in request["images"]]}}


def test_native_worker_inspects_during_capture_and_result_is_never_quality_approval(native_task):
    from app import capture_inspection as inspection
    _, config, receipt, _, task = native_task
    checker = DiagnosticClient()
    service = inspection.InspectionService(WorkStore(config.DATA_DIR), client_factory=lambda: checker,
                                          answer_pending=lambda: False)
    assert service.process_one()
    saved = service.store.get_capture_inspection(task["inspection_id"])
    assert saved["status"] == "completed" and checker.calls == 1
    assert saved["result"]["all_pages_or_characters_verified"] is False
    assert saved["result"]["auto_registration_allowed"] is False
    assert Path(receipt["image_path"]).is_file()
    assert service.store.list_jobs()["jobs"] == []
    assert not service.process_one()


def test_native_diagnostic_zip_exposes_the_unchanged_original_in_one_call(native_task):
    from app import capture_inspection as inspection
    _, config, receipt, _, task = native_task
    raw = Path(receipt["image_path"]).read_bytes()

    class OriginalClient(DiagnosticClient):
        def complete_inspection(self, **kwargs):
            request = json.loads(kwargs["prompt"].split("\nInspection request:\n")[1])
            assert "source_original" in kwargs["prompt"]
            assert "zoom" in kwargs["prompt"]
            original = request["images"][0]
            assert original["role"] == "source_original"
            assert original["sha256"] == receipt["canonical_image_sha256"]
            files = list(kwargs["files"]())
            assert len(files) == 1
            assert len(files[0]["buffer"]) == request["package_bytes"]
            with zipfile.ZipFile(io.BytesIO(files[0]["buffer"])) as archive:
                assert archive.read(original["file"]) == raw
            return super().complete_inspection(**kwargs)

    checker = OriginalClient()
    service = inspection.InspectionService(WorkStore(config.DATA_DIR), client_factory=lambda: checker, answer_pending=lambda: False)
    assert service.process_one()
    result = service.store.get_capture_inspection(task["inspection_id"])
    assert checker.calls == 1 and result["status"] == "completed"
    assert result["result"]["all_pages_or_characters_verified"] is False
    assert service.store.list_jobs()["jobs"] == []
    assert Path(receipt["image_path"]).read_bytes() == raw


def _legacy_native_request(receipt, capture_owner):
    """Historical v1 shape: the tiny fixture's overview and sole ROI are identical."""
    from app import capture_inspection as inspection
    raw = Path(receipt["image_path"]).read_bytes()
    with Image.open(io.BytesIO(raw)) as source:
        assert max(source.size) < 1024 and source.mode == "RGB"
        size = list(source.size)
    images = [{"image_id": name, "file": name + ".png", "sha256": hashlib.sha256(raw).hexdigest(),
               "bytes": len(raw), "box_upright_pixels": [0, 0, *size] if name == "roi-1" else None,
               "scale": "source_pixels_1_to_1" if name == "roi-1" else "overview_only"}
              for name in ("overview", "roi-1")]
    request = {"schema": 1, "purpose": "capture_inspection", "owner": capture_owner,
               "source_sha256": receipt["canonical_image_sha256"], "rotation": 0, "upright_size": size,
               "images": images, "scope": "bounded_regions_only", "guarantees_all_content": False,
               "auto_registration_allowed": False,
               "requested_settings": {"model": "gpt-6-luna", "effort": "high", "speed": "fast"}}
    return {**request, "manifest_sha256": inspection._sha(request)}


def test_legacy_prepared_manifest_is_reproduced_without_inserting_an_original(native_task):
    from app import capture_inspection as inspection
    _, config, receipt, _, task = native_task
    store = WorkStore(config.DATA_DIR)
    old = _legacy_native_request(receipt, task["owner"])
    part_id = inspection._sha({"inspection_id": task["inspection_id"], "owner": task["owner"]})
    store.prepare_capture_inspection_part(task["inspection_id"], part_id, old)

    class LegacyClient(DiagnosticClient):
        def complete_inspection(self, **kwargs):
            request = json.loads(kwargs["prompt"].split("\nInspection request:\n")[1])
            assert request == old
            assert "ONLY the supplied overview and bounded native-pixel regions" in kwargs["prompt"]
            return super().complete_inspection(**kwargs)

    checker = LegacyClient()
    assert inspection.InspectionService(store, client_factory=lambda: checker, answer_pending=lambda: False).process_one()
    assert checker.calls == 1
    assert store.get_capture_inspection(task["inspection_id"])["status"] == "completed"
    assert store.get_capture_inspection_part(part_id)["request"] == old


def test_over_budget_original_is_unknown_without_sending_or_modifying_source(native_task, monkeypatch):
    from app import capture_inspection as inspection, capture_quality as quality
    _, config, receipt, _, task = native_task
    source = Path(receipt["image_path"])
    raw = source.read_bytes()
    monkeypatch.setattr(quality, "MAX_DIAGNOSTIC_BYTES", len(raw) + 22 + 76 + 2 * len("source_original.png") - 1)
    checker = DiagnosticClient()
    service = inspection.InspectionService(WorkStore(config.DATA_DIR), client_factory=lambda: checker, answer_pending=lambda: False)
    assert service.process_one()
    result = service.store.get_capture_inspection(task["inspection_id"])
    assert result["status"] == "unknown" and result["reason"] == "original_png_over_budget"
    assert checker.calls == 0 and source.read_bytes() == raw
    assert service.store.list_jobs()["jobs"] == []


def test_postcommit_queue_reaches_shared_work_writer_and_bound_get_on_local_dom(native_task, page, monkeypatch):
    from app import capture_inspection as inspection
    from app.solvers import cdp, chatgpt_web
    from tests.test_chatgpt_work_web import _Context, _VenueTab, _diagnostic_composer, _guard_state
    from tests.test_native_capture_upload import native_image, provenance, upload
    client, config, receipt, origin, task = native_task
    _diagnostic_composer(page)
    for name, value in (("POLL_S", 0.001), ("RETRY_BACKOFF_S", 0), ("TIMEOUT_S", 0.2), ("REPLY_START_S", 0.05)):
        monkeypatch.setattr(chatgpt_web, name, value)
    monkeypatch.setattr(cdp, "connect_over_cdp", lambda endpoint: type("LocalBrowser", (), {
        "contexts": [_Context(_VenueTab(page))], "close": lambda self: None})())
    response = upload(client, origin["document_id"], native_image(), provenance(native_image()),
                      inspection_origin=json.dumps(origin))
    assert response.status_code == 201
    assert response.json()["capture_inspection"]["inspection_id"] == task["inspection_id"]
    service = inspection.InspectionService(WorkStore(config.DATA_DIR), answer_pending=lambda: False)
    assert service.process_one()
    result = client.get(f"/v1/capture-inspections/{task['inspection_id']}", params={
        key: origin[key] for key in ("device_id", "generation", "capture_id")}).json()
    assert result["status"] == "completed" and result["applicable"] is True
    assert result["result"]["parts"][0]["owner"]["canonical_image_sha256"] == receipt["canonical_image_sha256"]
    assert result["can_authorize_capture"] is False
    assert page.evaluate("window.sent") == 1 and _guard_state() == "idle"
    assert not inspection.InspectionService(WorkStore(config.DATA_DIR), answer_pending=lambda: False).process_one()
    assert page.evaluate("window.sent") == 1 and service.store.list_jobs()["jobs"] == []


def test_pending_stale_inspection_retires_late_reply_without_another_local_send(native_task, page, monkeypatch):
    from app import capture_inspection as inspection
    from app.solvers import cdp, chatgpt_web
    from tests.test_chatgpt_work_web import _Context, _VenueTab, _diagnostic_composer, _guard_state
    client, config, _, _, task = native_task
    _diagnostic_composer(page)
    page.evaluate("window.suppressFinal=true")
    for name, value in (("POLL_S", 0.001), ("RETRY_BACKOFF_S", 0), ("TIMEOUT_S", 0.2), ("REPLY_START_S", 0.05)):
        monkeypatch.setattr(chatgpt_web, name, value)
    monkeypatch.setattr(cdp, "connect_over_cdp", lambda endpoint: type("LocalBrowser", (), {
        "contexts": [_Context(_VenueTab(page))], "close": lambda self: None})())
    service = inspection.InspectionService(WorkStore(config.DATA_DIR), answer_pending=lambda: False)
    assert service.process_one() is False
    assert service.store.get_capture_inspection(task["inspection_id"])["status"] == "uncertain"
    assert page.evaluate("window.sent") == 1 and _guard_state() == "uncertain"
    assert client.post("/v1/glasses/state", json={"device_id": "glasses", "generation": 5,
        "sequence": 1, "phase": "capturing"}).status_code == 200
    assert service.process_one() is False
    page.evaluate("window.finish()")
    assert service.process_one()
    saved = service.store.get_capture_inspection(task["inspection_id"])
    assert saved["status"] == "unknown" and saved["reason"] == "retired_read_only"
    assert page.evaluate("window.sent") == 1 and _guard_state() == "idle"


@pytest.mark.parametrize("legacy", [True, False])
def test_uncertain_diagnostic_replays_exact_prepared_manifest_without_another_send(native_task, page, monkeypatch, legacy):
    from app import capture_inspection as inspection
    from app.solvers import cdp, chatgpt_web
    from tests.test_chatgpt_work_web import _Context, _VenueTab, _diagnostic_composer, _guard_state
    _, config, receipt, _, task = native_task
    store = WorkStore(config.DATA_DIR)
    part_id = inspection._sha({"inspection_id": task["inspection_id"], "owner": task["owner"]})
    if legacy:
        store.prepare_capture_inspection_part(task["inspection_id"], part_id, _legacy_native_request(receipt, task["owner"]))
    _diagnostic_composer(page)
    page.evaluate("window.suppressFinal=true")
    for name, value in (("POLL_S", 0.001), ("RETRY_BACKOFF_S", 0), ("TIMEOUT_S", 0.2), ("REPLY_START_S", 0.05)):
        monkeypatch.setattr(chatgpt_web, name, value)
    monkeypatch.setattr(cdp, "connect_over_cdp", lambda endpoint: type("LocalBrowser", (), {
        "contexts": [_Context(_VenueTab(page))], "close": lambda self: None})())
    assert inspection.InspectionService(store, answer_pending=lambda: False).process_one() is False
    prepared = store.get_capture_inspection_part(part_id)["request"]
    assert ("packet_policy" not in prepared) is legacy
    assert store.get_capture_inspection(task["inspection_id"])["status"] == "uncertain"
    assert page.evaluate("window.sent") == 1 and _guard_state() == "uncertain"
    page.evaluate("window.finish()")
    assert inspection.InspectionService(store, answer_pending=lambda: False).process_one()
    assert store.get_capture_inspection(task["inspection_id"])["status"] == "completed"
    assert store.get_capture_inspection_part(part_id)["request"] == prepared
    assert page.evaluate("window.sent") == 1 and _guard_state() == "idle"


def test_answer_priority_and_changed_source_never_send(native_task):
    from app import capture_inspection as inspection
    _, config, receipt, _, task = native_task
    checker = DiagnosticClient()
    service = inspection.InspectionService(WorkStore(config.DATA_DIR), client_factory=lambda: checker,
                                          answer_pending=lambda: True)
    service.process_one()
    assert service.store.get_capture_inspection(task["inspection_id"])["status"] == "deferred_answers"
    assert checker.calls == 0
    service.answer_pending = lambda: False
    Path(receipt["image_path"]).write_bytes(b"changed")
    service.process_one()
    assert service.store.get_capture_inspection(task["inspection_id"])["status"] == "unknown"
    assert checker.calls == 0


def test_answer_becoming_ready_at_submission_defers_inspection(native_task):
    from app import capture_inspection as inspection
    _, config, _, _, task = native_task
    waiting = False

    class PriorityClient(DiagnosticClient):
        def complete_inspection(self, **kwargs):
            nonlocal waiting
            waiting = True
            return super().complete_inspection(**kwargs)

    checker = PriorityClient()
    service = inspection.InspectionService(WorkStore(config.DATA_DIR), client_factory=lambda: checker,
                                          answer_pending=lambda: waiting)
    assert service.process_one() is False
    assert service.store.get_capture_inspection(task["inspection_id"])["status"] == "deferred_answers"


def test_postcommit_endpoint_and_read_only_bound_get(native_task, monkeypatch):
    from app import capture_inspection as inspection
    from tests.test_native_capture_upload import native_image, provenance, upload
    client, config, _, origin, task = native_task
    response = upload(client, origin["document_id"], native_image(), provenance(native_image()),
                      inspection_origin=json.dumps(origin))
    assert response.status_code == 201
    assert response.json()["capture_inspection"]["inspection_id"] == task["inspection_id"]
    path = WorkStore(config.DATA_DIR).path
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    monkeypatch.setattr(inspection, "wake_worker", lambda: pytest.fail("GET scheduled a worker"))
    route = f"/v1/capture-inspections/{task['inspection_id']}"
    query = {"device_id": origin["device_id"], "generation": origin["generation"], "capture_id": origin["capture_id"]}
    result = client.get(route, params=query)
    assert result.status_code == 200, result.text
    assert result.json()["owner"]["capture_id"] == origin["capture_id"]
    assert "source" not in result.json()
    assert result.json()["all_pages_or_characters_verified"] is False
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert client.get(route, params={**query, "generation": 5}).status_code == 409
    assert client.get(route, params={**query, "capture_id": "different"}).status_code == 409
    assert client.get(route, params=query, headers={"Authorization": "Bearer wrong"}).status_code == 401
    monkeypatch.setattr(config, "API_KEY", "")
    assert client.get(route, params=query).status_code == 503


def test_get_does_not_initialize_an_existing_legacy_work_database(client):
    from app import config
    path = WorkStore(config.DATA_DIR).path
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE legacy_marker (value TEXT)")
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    response = client.get("/v1/capture-inspections/" + "a" * 64,
        params={"device_id": "glasses", "generation": 4, "capture_id": "capture"})
    assert response.status_code in (404, 503)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_late_generation_or_bytes_change_keeps_diagnostic_historical(native_task):
    from app import capture_inspection as inspection
    client, config, _, origin, task = native_task

    class LateClient(DiagnosticClient):
        def complete_inspection(self, **kwargs):
            response = super().complete_inspection(**kwargs)
            client.post("/v1/glasses/state", json={"device_id": "glasses", "generation": 5,
                "sequence": 1, "phase": "capturing"})
            return response

    checker = LateClient()
    service = inspection.InspectionService(WorkStore(config.DATA_DIR), client_factory=lambda: checker, answer_pending=lambda: False)
    assert service.process_one()
    result = service.store.get_capture_inspection(task["inspection_id"])
    assert result["status"] == "unknown" and result["reason"] == "stale_capture"
    query = {"device_id": origin["device_id"], "generation": origin["generation"], "capture_id": origin["capture_id"]}
    response = client.get(f"/v1/capture-inspections/{task['inspection_id']}", params=query)
    assert response.status_code == 200 and response.json()["applicable"] is False


def test_new_unbound_page_invalidates_older_bound_result_without_guessing_an_origin(native_task):
    from app import capture_inspection as inspection
    from tests.test_native_capture_upload import native_image
    client, config, _, origin, task = native_task

    class LatePageClient(DiagnosticClient):
        def complete_inspection(self, **kwargs):
            response = super().complete_inspection(**kwargs)
            added = client.post(f"/v1/documents/{origin['document_id']}/pages", data={"page_index": 1},
                                files={"image": ("unbound.jpg", native_image(), "image/jpeg")})
            assert added.status_code == 201 and added.json()["capture_inspection"]["status"] == "unbound"
            return response

    service = inspection.InspectionService(WorkStore(config.DATA_DIR), client_factory=LatePageClient, answer_pending=lambda: False)
    assert service.process_one()
    assert service.store.get_capture_inspection(task["inspection_id"])["status"] == "unknown"
    assert not service.store.current_capture_inspection(task["inspection_id"])


def test_video_postcommit_uses_sealed_origin_and_diagnostic_pts_without_changing_receipt(video_setup, movie, monkeypatch):
    from app import capture_inspection as inspection, config
    from tests.test_capture_video_upload import HEADERS, metadata, upload
    source, _, _ = movie
    raw = source.read_bytes()
    client, template, state, _ = video_setup
    value = metadata(template["session_id"], template["document_id"], raw)
    for profile in (value["journal"]["selected_profile"], value["journal"]["actual_file"]):
        profile.update(width=160, height=120)
    monkeypatch.setenv("ROKID_CAPTURE_INSPECTION", "1")
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    monkeypatch.setattr(inspection, "wake_worker", lambda: None)
    response = upload(client, value, raw)
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert "capture_inspection" not in receipt and receipt["auto_analysis_allowed"] is False
    query = {"device_id": state["device_id"], "generation": state["generation"], "capture_id": receipt["clip_id"]}
    queued = client.get("/v1/capture-inspections", params=query, headers=HEADERS)
    assert queued.status_code == 200, queued.text
    assert queued.json()["status"] == "queued"
    checker = DiagnosticClient()
    service = inspection.InspectionService(WorkStore(config.DATA_DIR), client_factory=lambda: checker, answer_pending=lambda: False)
    assert service.process_one()
    result = client.get("/v1/capture-inspections", params=query, headers=HEADERS).json()
    assert result["status"] == "completed", result
    assert 1 <= checker.calls <= 12
    assert result["result"]["sensor_to_video_pts"] == "unknown"
    assert result["all_pages_or_characters_verified"] is False
    for part in result["result"]["parts"]:
        frame = part["owner"]["video_frame"]
        assert type(frame["pts"]) is int and type(frame["decoded_index"]) is int
    assert list((config.DATA_DIR / "capture-videos" / "objects").glob("*/original.mp4"))[0].read_bytes() == raw


@pytest.mark.parametrize("transition", ["new_generation", "closed"])
def test_stale_video_pending_reply_retires_its_writer_without_resending(video_setup, movie, page, monkeypatch, transition):
    from app import capture_inspection as inspection, config
    from app.solvers import cdp, chatgpt_web
    from tests.test_capture_video_upload import HEADERS, metadata, upload
    from tests.test_chatgpt_work_web import _Context, _VenueTab, _diagnostic_composer, _guard_state
    client, template, state, _ = video_setup
    raw = movie[0].read_bytes()
    value = metadata(template["session_id"], template["document_id"], raw)
    for profile in (value["journal"]["selected_profile"], value["journal"]["actual_file"]):
        profile.update(width=160, height=120)
    monkeypatch.setenv("ROKID_CAPTURE_INSPECTION", "1")
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    monkeypatch.setattr(inspection, "wake_worker", lambda: None)
    _diagnostic_composer(page)
    page.evaluate("window.suppressFinal=true")
    for name, setting in (("POLL_S", 0.001), ("RETRY_BACKOFF_S", 0), ("TIMEOUT_S", 0.2), ("REPLY_START_S", 0.05)):
        monkeypatch.setattr(chatgpt_web, name, setting)
    monkeypatch.setattr(cdp, "connect_over_cdp", lambda endpoint: type("LocalBrowser", (), {
        "contexts": [_Context(_VenueTab(page))], "close": lambda self: None})())
    response = upload(client, value, raw)
    assert response.status_code == 201, response.text
    receipt = response.json()
    query = {"device_id": state["device_id"], "generation": state["generation"], "capture_id": receipt["clip_id"]}
    identity = client.get("/v1/capture-inspections", params=query, headers=HEADERS).json()["inspection_id"]
    service = inspection.InspectionService(WorkStore(config.DATA_DIR), answer_pending=lambda: False)
    assert service.process_one() is False
    assert service.store.get_capture_inspection(identity)["status"] == "uncertain"
    assert page.evaluate("window.sent") == 1 and _guard_state() == "uncertain"
    replacement = {**state, "sequence": 2, "phase": "closed"}
    if transition == "new_generation":
        replacement = {**state, "generation": state["generation"] + 1, "sequence": 1}
    changed = client.post("/v1/glasses/state", json=replacement, headers=HEADERS)
    assert changed.status_code == 200 and changed.json()["accepted"]
    # No matching final yet: keep the same pending owner recoverable.
    assert service.process_one() is False
    assert service.store.get_capture_inspection(identity)["status"] == "uncertain"
    assert page.evaluate("window.sent") == 1 and _guard_state() == "uncertain"
    page.evaluate("window.finish()")
    assert inspection.InspectionService(service.store, answer_pending=lambda: False).process_one()
    saved = service.store.get_capture_inspection(identity)
    assert saved["status"] == "unknown" and saved["reason"] == "retired_read_only"
    assert page.evaluate("window.sent") == 1 and _guard_state() == "idle"
    assert service.client_factory().pending_inspection_owner() is None
    result = client.get("/v1/capture-inspections", params=query, headers=HEADERS)
    assert result.status_code == 200 and result.json()["applicable"] is False
    assert list((config.DATA_DIR / "capture-videos" / "objects").glob("*/original.mp4"))[0].read_bytes() == raw


@pytest.mark.parametrize("status,detail,stale", [
    (409, "stale_video_capture", True), (409, "stale_video_document", True),
    (503, "video_state_unavailable", False), (404, "video_session_or_document_not_found", False),
    (409, "ambiguous_video_owner", False), (503, "stale_video_capture", False),
    (409, "unrecognized_video_conflict", False),
])
def test_video_currentness_normalizes_only_explicit_stale_conflicts(tmp_path, monkeypatch, status, detail, stale):
    from contextlib import contextmanager
    from fastapi import HTTPException
    from app import capture_inspection as inspection
    from app.work_bridge import WorkConflict
    store = WorkStore(tmp_path)
    capture_owner = {**owner(), "kind": "raw_video", "source_ip": "testclient"}
    source = {"receipt_id": "a" * 64}
    task = store.enqueue_capture_inspection(owner=capture_owner, source=source)
    task["source"] = source
    monkeypatch.setattr(inspection, "_clip_reference", lambda *args, **kwargs: (capture_owner, source, {}, (), {}))
    injected = HTTPException(status_code=status, detail=detail)

    @contextmanager
    def unavailable_state(*args):
        raise injected
        yield

    monkeypatch.setattr(inspection, "_video_state", unavailable_state)
    with pytest.raises(WorkConflict if stale else HTTPException) as raised:
        inspection._current(store, task)
    if stale:
        assert raised.value.__cause__ is injected
    else:
        assert raised.value is injected


@pytest.mark.parametrize("field,value", [("schema", True), ("generation", "4"), ("generation", 4.0),
    ("generation", False), ("document_id", 0), ("capture_id", "unrelated"), ("extra", 1)])
def test_explicit_origin_is_strict_and_never_guessed(native_task, field, value):
    from app import capture_inspection as inspection
    _, _, _, origin, _ = native_task
    result = inspection.register_native(origin["document_id"], 0, json.dumps({**origin, field: value}), "testclient")
    assert result["status"] == "unbound"


def test_queue_overflow_resumes_latest_source_without_discarding_earlier_images(native_task):
    from app import capture_inspection as inspection
    from tests.test_native_capture_upload import native_image, provenance, upload
    client, config, receipt, origin, _ = native_task
    receipts = [receipt]
    last = None
    for index in range(1, 4):
        capture = f"11111111-1111-4111-8111-{index:012d}"
        meta = provenance(native_image(), capture_id=capture, page_index=index)
        response = upload(client, origin["document_id"], native_image(), meta, page_index=index,
            inspection_origin=json.dumps({**origin, "capture_id": capture}))
        assert response.status_code == 201, response.text
        receipts.append(response.json())
        last = response.json()["capture_inspection"]
    assert last["status"] == "deferred_queue_full"
    checker = DiagnosticClient()
    service = inspection.InspectionService(WorkStore(config.DATA_DIR), client_factory=lambda: checker, answer_pending=lambda: False)
    assert service.process_one()
    assert checker.calls == 1
    assert service.store.get_capture_inspection(last["inspection_id"])["status"] == "completed"
    assert all(Path(item["image_path"]).is_file() for item in receipts)


def test_one_inflight_inspection_and_no_send_when_disabled(native_task, monkeypatch):
    from app import capture_inspection as inspection
    _, config, _, _, task = native_task
    entered, release = threading.Event(), threading.Event()

    class Blocking(DiagnosticClient):
        def complete_inspection(self, **kwargs):
            entered.set()
            assert release.wait(5)
            return super().complete_inspection(**kwargs)

    checker = Blocking()
    service = inspection.InspectionService(WorkStore(config.DATA_DIR), client_factory=lambda: checker, answer_pending=lambda: False)
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "0")
    assert not service.process_one()
    assert service.store.get_capture_inspection(task["inspection_id"])["status"] == "deferred_send_disabled"
    assert checker.calls == 0
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    worker = threading.Thread(target=service.process_one)
    worker.start()
    try:
        assert entered.wait(5)
        assert not service.process_one()
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive() and checker.calls == 1
    assert service.store.get_capture_inspection(task["inspection_id"])["status"] == "completed"


@pytest.mark.parametrize("fault", ["bytes", "metadata", "closed"])
def test_change_while_inspection_runs_cannot_become_current(native_task, fault):
    from app import capture_inspection as inspection, db
    client, config, receipt, _, task = native_task

    class Changed(DiagnosticClient):
        def complete_inspection(self, **kwargs):
            response = super().complete_inspection(**kwargs)
            if fault == "bytes":
                Path(receipt["image_path"]).write_bytes(b"changed")
            elif fault == "metadata":
                with db.connect() as conn:
                    row = conn.execute("SELECT capture_metadata_json FROM pages WHERE id=?", (receipt["page_id"],)).fetchone()
                    meta = json.loads(row[0])
                    meta["capture_provenance"]["capture_id"] = "33333333-3333-4333-8333-333333333333"
                    conn.execute("UPDATE pages SET capture_metadata_json=? WHERE id=?", (json.dumps(meta), receipt["page_id"]))
                    conn.commit()
            else:
                client.post("/v1/glasses/state", json={"device_id": "glasses", "generation": 4, "sequence": 2, "phase": "closed"})
            return response

    service = inspection.InspectionService(WorkStore(config.DATA_DIR), client_factory=Changed, answer_pending=lambda: False)
    assert service.process_one()
    assert service.store.get_capture_inspection(task["inspection_id"])["status"] == "unknown"


@pytest.mark.parametrize("fault", ["identity", "missing_region", "inferred_approval", "fake_viewer"])
def test_bad_ai_claim_is_unknown_and_never_destroys_original(native_task, fault):
    from app import capture_inspection as inspection
    _, config, receipt, _, task = native_task

    class Invalid(DiagnosticClient):
        def complete_inspection(self, **kwargs):
            response = super().complete_inspection(**kwargs)
            if fault == "identity":
                response["inspection_id"] = "f" * 64
            elif fault == "missing_region":
                response["inspection"]["observations"].pop()
            elif fault == "inferred_approval":
                response["inspection"]["eligible"] = True
            else:
                response["inspection"]["observations"][0]["image_viewer_used"] = "true"
            return response

    service = inspection.InspectionService(WorkStore(config.DATA_DIR), client_factory=Invalid, answer_pending=lambda: False)
    service.process_one()
    assert service.store.get_capture_inspection(task["inspection_id"])["status"] == "unknown"
    assert Path(receipt["image_path"]).is_file()
