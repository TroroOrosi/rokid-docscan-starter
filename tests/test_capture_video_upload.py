"""Phone-side original-video preservation. No camera, decoder or model is used."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import copy
import errno
import hashlib
import importlib
import json
import os
from pathlib import Path
import threading

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest


HEADERS = {"Authorization": "Bearer video-test-key"}
PEER = "10.0.0.12"
CLIP = "video-11111111-1111-4111-8111-111111111111"
MOVIE = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"original-video" * 10_000


def metadata(session_id, document_id, raw=MOVIE):
    """The exact public journal keys emitted by CaptureVideoRecording.persist()."""
    return {"schema": 1, "session_id": session_id, "document_id": document_id, "journal": {
        "schema": 1, "kind": "raw_video_evaluation", "state": "complete", "reason": "capture_end",
        "device_id": "glasses-test", "generation": 7, "clip_id": CLIP, "rotation": 270,
        "original": "original.mp4", "audio_enabled": False,
        "selected_profile": {"codec": "avc", "mime": "video/avc", "width": 4032, "height": 3024,
                             "fps": 30, "bitrate": 20_000_000},
        "profile_quality_calibrated": False, "max_jpeg_width": 4032, "max_jpeg_height": 3024,
        "app_version": "0.test", "app_version_code": 44, "producer_revision": "mediarecorder_hybrid_v1",
        "advertised_compatible_encoder": "fixture-advertised-encoder",
        "actual_encoder_name": "unknown_public_mediarecorder",
        "actual_file": {"mime": "video/avc", "width": 4032, "height": 3024, "rotation_metadata": 0,
                        "video_tracks": 1, "audio_tracks": 0, "duration_us": 2_000_000,
                        "bitrate_metadata": None, "frame_rate_metadata": None},
        "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
        "first_preview_sensor_ns": 100, "last_preview_sensor_ns": 200,
        "first_preview_frame_number": 1, "last_preview_frame_number": 2,
        "largest_preview_sensor_gap_ns": 100, "scene_clock": "camera_sensor_ns", "sensor_timestamp_source": 1,
        "latest_result_crop": {"left": 0, "top": 0, "right": 4032, "bottom": 3024},
        "latest_result_video_stabilization": 0, "latest_result_optical_stabilization": 0,
        "video_to_jpeg_field_of_view": "unknown_requires_physical_calibration",
        "scene_observation_source": "small_yuv_not_original_video_frame",
        "sensor_to_video_pts": "unknown_requires_decoded_pts",
        "capture_gap_status": "unknown_requires_decoded_frame_coverage",
        "exact_stream_support": "see_session_events", "all_pages_or_characters_verified": False,
        "auto_upload_allowed": False, "complete_scope": "sealed_local_video_container_only",
        "event_budget_exceeded": False, "evaluation_max_bytes": 128 * 1024 * 1024,
        "evaluation_max_duration_ms": 60_000,
        "events": [{"event": "recorder_started", "elapsed_realtime_ns": 10},
                   {"event": "exact_session_support", "elapsed_realtime_ns": 11, "support": "supported"},
                   {"event": "scene_observed", "elapsed_realtime_ns": 12,
                    "scene_sequence": 1, "sensor_timestamp_ns": 100, "observation_elapsed_ms": 1}],
    }}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("ROKID_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ROKID_API_KEY", "video-test-key")
    from app import config, db, main
    for module in (config, db, main):
        importlib.reload(module)
    main.ensure_dirs()
    db.init_db()
    application = main.app

    async def with_peer(scope, receive, send):
        if scope["type"] == "http":
            scope = {**scope, "client": (PEER, 54321)}
        await application(scope, receive, send)

    client = TestClient(with_peer)
    doc = client.post("/v1/documents", json={"title": "Video preservation"}, headers=HEADERS).json()["document_id"]
    session = client.post("/v1/exam-sessions", json={}, headers=HEADERS).json()["session_id"]
    # A capturing session is bound before document finalization, as in the
    # document-capture path; no synthetic page or solver is needed here.
    with db.connect() as conn:
        conn.execute("UPDATE exam_sessions SET document_id = ? WHERE id = ?", (doc, session))
        conn.commit()
    state = {"device_id": "glasses-test", "session_id": session, "generation": 7,
             "sequence": 1, "phase": "capturing"}
    assert client.post("/v1/glasses/state", json=state, headers=HEADERS).json()["accepted"] is True
    return client, metadata(session, doc), state, tmp_path


def upload(client, value, raw=MOVIE, *, headers=None, mime="video/mp4"):
    return client.post("/v1/capture-videos", data={"metadata": json.dumps(value)},
                       files={"video": ("../../untrusted-name.mp4", raw, mime)},
                       headers=HEADERS if headers is None else headers)


def public_files(root):
    return list((root / "capture-videos" / "receipts").glob("[a-f0-9]" * 64 + ".json"))


def test_preserves_original_and_complete_journal_without_quality_or_work_side_effects(setup):
    client, value, _, root = setup
    response = upload(client, value)
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt["kind"] == "raw_video_receipt"
    assert receipt["status"] == "stored" and receipt["quality_status"] == "unevaluated"
    assert receipt["all_pages_or_characters_verified"] is False
    assert receipt["auto_analysis_allowed"] is False
    assert receipt["source_ip"] == PEER
    assert {key: receipt[key] for key in ("session_id", "document_id")} == {
        key: value[key] for key in ("session_id", "document_id")}
    assert receipt["clip_id"] == CLIP and receipt["generation"] == 7
    assert receipt["sha256"] == value["journal"]["sha256"] and receipt["bytes"] == len(MOVIE)
    originals = list((root / "capture-videos" / "objects").glob("*/original.mp4"))
    assert len(originals) == len(public_files(root)) == 1
    assert originals[0].read_bytes() == MOVIE
    envelope = originals[0].with_name("metadata.json").read_bytes()
    assert envelope == json.dumps(value).encode("utf-8")
    assert hashlib.sha256(envelope).hexdigest() == receipt["metadata_sha256"]
    assert not (root / "work").exists()
    from app import db
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 0
        assert conn.execute("SELECT status FROM exam_sessions").fetchone()[0] == "open"
    if os.name == "posix":
        assert originals[0].stat().st_mode & 0o777 == 0o600
        assert originals[0].parent.stat().st_mode & 0o777 == 0o700


def test_video_endpoint_always_requires_a_configured_key(setup, monkeypatch):
    client, value, _, root = setup
    assert upload(client, value, headers={}).status_code == 401
    assert upload(client, value, headers={"Authorization": "Bearer wrong"}).status_code == 401
    from app import config
    monkeypatch.setattr(config, "API_KEY", "")
    assert upload(client, value, headers={}).status_code == 503
    assert not public_files(root)


@pytest.mark.parametrize("phase", ["chooser", "writing_done", "closed"])
def test_terminal_or_unbound_wearer_cannot_store_a_video(setup, phase):
    client, value, state, root = setup
    assert client.post("/v1/glasses/state", json={**state, "phase": phase, "sequence": 2}, headers=HEADERS).json()["accepted"]
    assert upload(client, value).status_code == 409
    assert not public_files(root)


@pytest.mark.parametrize("phase", ["analyzing", "waiting", "reading"])
def test_same_generation_can_preserve_a_late_clip_while_answers_are_being_read(setup, phase):
    client, value, state, _ = setup
    assert client.post("/v1/glasses/state", json={**state, "phase": phase, "sequence": 2}, headers=HEADERS).json()["accepted"]
    assert upload(client, value).status_code == 201


def test_identical_retry_is_the_same_receipt_without_new_files_or_mtime_changes(setup):
    client, value, _, root = setup
    first = upload(client, value)
    assert first.status_code == 201
    before = {str(p): (p.stat().st_mtime_ns, p.read_bytes()) for p in (root / "capture-videos").rglob("*") if p.is_file()}
    again = upload(client, value)
    assert again.status_code == 200 and again.json() == first.json()
    after = {str(p): (p.stat().st_mtime_ns, p.read_bytes()) for p in (root / "capture-videos").rglob("*") if p.is_file()}
    assert before == after


def test_same_clip_different_bytes_or_metadata_never_overwrites_first_original(setup):
    client, value, _, root = setup
    assert upload(client, value).status_code == 201
    before = {str(p): p.read_bytes() for p in (root / "capture-videos").rglob("*") if p.is_file()}
    changed = copy.deepcopy(value)
    changed["journal"]["rotation"] = 90
    assert upload(client, changed).status_code == 409
    assert upload(client, metadata(value["session_id"], value["document_id"], MOVIE + b"other"), MOVIE + b"other").status_code == 409
    assert before == {str(p): p.read_bytes() for p in (root / "capture-videos").rglob("*") if p.is_file()}


@pytest.mark.parametrize("fault", ["hash", "short", "long", "not_mp4", "wrong_mime"])
def test_streamed_bytes_must_match_the_sealed_mp4_claim_without_a_receipt(setup, fault):
    client, value, _, root = setup
    raw, mime = MOVIE, "video/mp4"
    if fault == "hash":
        value["journal"]["sha256"] = "0" * 64
    elif fault == "short":
        raw = MOVIE[:-1]
    elif fault == "long":
        raw = MOVIE + b"extra"
    elif fault == "not_mp4":
        raw = b"jpeg-content"
        value = metadata(value["session_id"], value["document_id"], raw)
    else:
        mime = "image/jpeg"
    assert upload(client, value, raw, mime=mime).status_code in (400, 413, 415)
    assert not public_files(root)


@pytest.mark.parametrize("path,bad", [
    (("schema",), True), (("session_id",), "1"), (("document_id",), 1.0),
    (("journal", "generation"), True), (("journal", "generation"), -1),
    (("journal", "generation"), 2**63), (("journal", "clip_id"), "../escape"),
    (("journal", "state"), "unknown"), (("journal", "bytes"), 0),
    (("journal", "bytes"), 128 * 1024 * 1024 + 1), (("journal", "sha256"), "A" * 64),
    (("journal", "audio_enabled"), True), (("journal", "all_pages_or_characters_verified"), True),
    (("journal", "event_budget_exceeded"), True), (("journal", "auto_upload_allowed"), True),
    (("journal", "selected_profile", "width"), 1920), (("journal", "selected_profile", "fps"), 61),
    (("journal", "actual_file", "width"), 640), (("journal", "actual_file", "mime"), "image/jpeg"),
    (("journal", "actual_file", "duration_us"), None), (("journal", "actual_file", "duration_us"), 60_000_001),
    (("journal", "actual_file", "audio_tracks"), 1), (("journal", "actual_file", "rotation_metadata"), 90),
    (("journal", "rotation"), 45), (("journal", "events"), [{}]),
])
def test_strict_journal_rejects_invalid_or_unsealed_metadata_before_storage(setup, path, bad):
    client, value, _, root = setup
    target = value
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = bad
    assert upload(client, value).status_code in (400, 409, 413)
    assert not (root / "capture-videos").exists()


@pytest.mark.parametrize("path", [(), ("journal",), ("journal", "actual_file"), ("journal", "selected_profile"), ("journal", "events", 0)])
def test_unknown_keys_are_not_silently_removed_from_the_provenance(setup, path):
    client, value, _, root = setup
    target = value
    for key in path:
        target = target[key]
    target["new_unverified_claim"] = True
    assert upload(client, value).status_code == 400
    assert not (root / "capture-videos").exists()


@pytest.mark.parametrize("fault", ["generation", "session", "document", "missing_session", "missing_document", "peer", "ambiguous"])
def test_actual_wearer_and_database_identity_are_required_before_any_file_creation(setup, fault):
    client, value, state, root = setup
    from app import db
    from app.glasses_state import GlassesState, record_state
    if fault == "generation":
        value["journal"]["generation"] += 1
    elif fault == "session":
        value["session_id"] += 1
    elif fault == "document":
        with db.connect() as conn:
            conn.execute("UPDATE exam_sessions SET document_id = NULL")
            conn.commit()
    elif fault == "missing_session":
        with db.connect() as conn:
            conn.execute("DELETE FROM exam_sessions")
            conn.commit()
    elif fault == "missing_document":
        value["document_id"] += 1
    elif fault == "peer":
        record_state(GlassesState(**{**state, "sequence": 2}), "10.0.0.99")
    else:
        record_state(GlassesState(**{**state, "device_id": "second-device"}), PEER)
    response = upload(client, value, headers={**HEADERS, "X-Forwarded-For": "10.0.0.99"})
    assert response.status_code in (404, 409)
    assert not (root / "capture-videos").exists()


class ChunkUpload:
    content_type = "video/mp4"

    def __init__(self, raw, hook=None, error=None):
        self.raw, self.hook, self.error = raw, hook, error
        self.offset, self.calls = 0, 0

    async def read(self, size):
        assert size == 64 * 1024
        self.calls += 1
        if self.calls == 2:
            if self.hook:
                self.hook()
            if self.error:
                raise self.error
        block = self.raw[self.offset:self.offset + size]
        self.offset += len(block)
        await asyncio.sleep(0)
        return block


@pytest.mark.parametrize("fault", ["generation", "terminal", "document"])
def test_notification_or_document_change_during_stream_retains_bytes_without_publishing(setup, fault):
    _, value, state, root = setup
    from app import capture_video_upload as video, db
    from app.glasses_state import GlassesState, record_state

    def change():
        if fault == "document":
            with db.connect() as conn:
                conn.execute("UPDATE exam_sessions SET document_id = NULL")
                conn.commit()
        else:
            update = {**state, "sequence": 2, "generation": 8} if fault == "generation" else {
                **state, "sequence": 2, "phase": "closed"}
            # A separate notification must be able to complete during reads.
            done = threading.Event()
            worker = threading.Thread(target=lambda: (record_state(GlassesState(**update), PEER), done.set()))
            worker.start()
            completed = done.wait(2)
            worker.join(2)
            assert completed

    incoming = ChunkUpload(MOVIE, hook=change)
    with pytest.raises(HTTPException) as raised:
        asyncio.run(video.receive_capture_video(incoming, json.dumps(value), PEER))
    assert raised.value.status_code == 409
    assert incoming.calls >= 3
    assert not public_files(root)
    assert next((root / "capture-videos" / "objects").glob("*/original.mp4")).read_bytes() == MOVIE


def test_read_failure_preserves_partial_original_and_has_no_successful_receipt(setup):
    _, value, _, root = setup
    from app import capture_video_upload as video
    incoming = ChunkUpload(MOVIE, error=OSError("injected read failure"))
    with pytest.raises(HTTPException) as raised:
        asyncio.run(video.receive_capture_video(incoming, json.dumps(value), PEER))
    assert raised.value.status_code == 503
    assert not public_files(root)
    assert next((root / "capture-videos" / "objects").glob("*/original.mp4")).read_bytes() == MOVIE[:64 * 1024]


@pytest.mark.parametrize("fault", ["original", "metadata", "receipt"])
def test_retry_verifies_saved_bytes_and_metadata_instead_of_trusting_a_receipt(setup, fault):
    client, value, _, root = setup
    assert upload(client, value).status_code == 201
    original = next((root / "capture-videos" / "objects").glob("*/original.mp4"))
    target = original if fault == "original" else original.with_name("metadata.json") if fault == "metadata" else public_files(root)[0]
    before = target.read_bytes()
    target.write_bytes(before[:-1] + (b"x" if before[-1:] != b"x" else b"y"))
    changed = target.read_bytes()
    assert upload(client, value).status_code == 503
    assert target.read_bytes() == changed


def test_late_termination_during_existing_original_hash_blocks_retry_acknowledgement(setup, monkeypatch):
    client, value, state, root = setup
    assert upload(client, value).status_code == 201
    from app import capture_video_upload as video
    from app.glasses_state import GlassesState, record_state
    read = video._read_verified

    def terminate_after_hash(path, *args, **kwargs):
        result = read(path, *args, **kwargs)
        if path.name == "original.mp4":
            done = threading.Event()
            worker = threading.Thread(target=lambda: (record_state(
                GlassesState(**{**state, "phase": "closed", "sequence": 2}), PEER), done.set()))
            worker.start()
            completed = done.wait(2)
            worker.join(2)
            assert completed
        return result

    monkeypatch.setattr(video, "_read_verified", terminate_after_hash)
    assert upload(client, value).status_code == 409
    assert len(public_files(root)) == 1


@pytest.mark.parametrize("fault", ["file_sync", "publish", "directory_sync"])
def test_atomic_failure_never_overwrites_originals_or_returns_a_receipt(setup, monkeypatch, fault):
    client, value, _, root = setup
    from app import capture_video_upload as video
    if fault == "file_sync":
        monkeypatch.setattr(video.os, "fsync", lambda _: (_ for _ in ()).throw(OSError("injected sync")))
    elif fault == "publish":
        monkeypatch.setattr(video, "_publish_noreplace", lambda *_: (_ for _ in ()).throw(OSError("injected publish")))
    else:
        monkeypatch.setattr(video, "_sync_directory", lambda _: (_ for _ in ()).throw(OSError("injected directory sync")))
    assert upload(client, value).status_code == 503
    assert not public_files(root)
    assert next((root / "capture-videos" / "objects").glob("*/original.mp4")).read_bytes() == MOVIE


def test_metadata_duplicate_keys_nonfinite_and_oversize_are_rejected_without_files(setup):
    client, value, _, root = setup
    valid = json.dumps(value)
    for raw in (valid.replace('"schema": 1', '"schema": 1, "schema": 1', 1),
                valid.replace('"generation": 7', '"generation": NaN'), " " * (512 * 1024 + 1), "["):
        response = client.post("/v1/capture-videos", data={"metadata": raw},
                               files={"video": ("original.mp4", MOVIE, "video/mp4")}, headers=HEADERS)
        assert response.status_code in (400, 413)
    assert not (root / "capture-videos").exists()


def test_server_restart_still_returns_the_immutable_receipt(setup):
    client, value, _, _ = setup
    first = upload(client, value)
    assert first.status_code == 201
    from app import capture_video_upload
    importlib.reload(capture_video_upload)
    again = upload(client, value)
    assert again.status_code == 200 and first.json() == again.json()


def test_semantically_identical_metadata_retry_returns_the_original_envelope_receipt(setup):
    client, value, _, root = setup
    value["journal"]["reason"] = "撮影終了"
    first = upload(client, value)
    assert first.status_code == 201
    original_envelope = next((root / "capture-videos" / "objects").glob("*/metadata.json")).read_bytes()
    response = client.post("/v1/capture-videos", data={"metadata": json.dumps(value, ensure_ascii=False, sort_keys=True)},
                           files={"video": ("original.mp4", MOVIE, "video/mp4")}, headers=HEADERS)
    assert response.status_code == 200 and response.json() == first.json()
    assert next((root / "capture-videos" / "objects").glob("*/metadata.json")).read_bytes() == original_envelope


def test_clip_id_cannot_be_rebound_to_a_different_document(setup):
    client, value, _, root = setup
    first = upload(client, value)
    assert first.status_code == 201
    second = client.post("/v1/documents", json={"title": "Other document"}, headers=HEADERS).json()["document_id"]
    from app import db
    with db.connect() as conn:
        conn.execute("UPDATE exam_sessions SET document_id = ? WHERE id = ?", (second, value["session_id"]))
        conn.commit()
    value["document_id"] = second
    assert upload(client, value).status_code == 409
    assert len(public_files(root)) == 1
    assert len(list((root / "capture-videos" / "objects").glob("*/original.mp4"))) == 1


def test_concurrent_identical_arrivals_publish_one_immutable_receipt(setup):
    client, value, _, root = setup
    with ThreadPoolExecutor(max_workers=2) as workers:
        responses = list(workers.map(lambda _: upload(client, value), range(2)))
    assert sorted(response.status_code for response in responses) == [200, 201]
    assert responses[0].json() == responses[1].json()
    assert len(public_files(root)) == 1
    assert all(path.read_bytes() == MOVIE for path in (root / "capture-videos" / "objects").glob("*/original.mp4"))


def test_uncertain_directory_sync_after_publication_is_not_acknowledged_until_verified_retry(setup, monkeypatch):
    client, value, _, root = setup
    from app import capture_video_upload as video
    sync = video._sync_directory
    failed = False

    def fail_once_after_publication(path):
        nonlocal failed
        if path.name == "receipts" and public_files(root) and not failed:
            failed = True
            raise OSError("injected publication durability failure")
        sync(path)

    monkeypatch.setattr(video, "_sync_directory", fail_once_after_publication)
    assert upload(client, value).status_code == 503
    assert len(public_files(root)) == 1
    before = {str(p): p.read_bytes() for p in (root / "capture-videos").rglob("*") if p.is_file()}
    retry = upload(client, value)
    assert retry.status_code == 200
    assert retry.json()["quality_status"] == "unevaluated"
    assert before == {str(p): p.read_bytes() for p in (root / "capture-videos").rglob("*") if p.is_file()}


def test_existing_incomplete_receipt_is_not_clobbered_or_treated_as_empty_success(setup):
    client, value, _, root = setup
    receipts = root / "capture-videos" / "receipts"
    receipts.mkdir(parents=True)
    marker = receipts / (hashlib.sha256(CLIP.encode()).hexdigest() + ".json")
    marker.write_bytes(b"")
    assert upload(client, value).status_code == 503
    assert marker.read_bytes() == b""
    assert not (root / "capture-videos" / "objects").exists()


@pytest.mark.parametrize("name", ["original.mp4", "metadata.json"])
def test_first_receipt_rechecks_the_closed_original_and_envelope(setup, monkeypatch, name):
    client, value, _, root = setup
    from app import capture_video_upload as video
    sync = video._sync_directory
    changed = []

    def change_after_close(path):
        target = path / name
        if target.is_file() and not changed:
            content = target.read_bytes()
            target.write_bytes(content[:-1] + b"X")
            changed.append(target)
        sync(path)

    monkeypatch.setattr(video, "_sync_directory", change_after_close)
    assert upload(client, value).status_code == 503
    assert changed
    assert not public_files(root)
    assert changed[0].read_bytes().endswith(b"X")


@pytest.mark.parametrize("retry", [False, True])
def test_object_parent_identity_cannot_change_after_the_stored_files_are_verified(setup, monkeypatch, retry):
    client, value, _, root = setup
    if retry:
        assert upload(client, value).status_code == 201
    from app import capture_video_upload as video
    verify = video._verify_existing
    moved = []

    def replace_parent_after_verification(storage_root, record, payload):
        verified = verify(storage_root, record, payload)
        if not moved:
            folder = storage_root / "objects" / record["object_id"]
            retained = folder.with_name("retained-" + folder.name)
            assert folder.resolve().is_relative_to(root.resolve())
            assert retained.resolve().is_relative_to(root.resolve())
            folder.rename(retained)
            folder.mkdir()
            # Preserve file inode/data through hard links, changing only their
            # containing directory's identity. No outside path is accessed.
            for path in retained.iterdir():
                os.link(path, folder / path.name)
            moved.append(retained)
        return verified

    monkeypatch.setattr(video, "_verify_existing", replace_parent_after_verification)
    assert upload(client, value).status_code == 503
    assert moved and (moved[0] / "original.mp4").read_bytes() == MOVIE
    assert len(public_files(root)) == (1 if retry else 0)


def test_changed_pending_receipt_is_not_published_after_object_verification(setup, monkeypatch):
    client, value, _, root = setup
    from app import capture_video_upload as video
    current = video._current
    entries = 0
    changed = []

    @contextmanager
    def change_at_final_guard(payload, peer):
        nonlocal entries
        with current(payload, peer):
            entries += 1
            if entries == 2:
                pending = next((root / "capture-videos" / "receipts").glob("pending-*.json"))
                pending.write_bytes(b"corrupt receipt")
                changed.append(pending)
            yield

    monkeypatch.setattr(video, "_current", change_at_final_guard)
    assert upload(client, value).status_code == 503
    assert changed and not public_files(root)
    assert next((root / "capture-videos" / "objects").glob("*/original.mp4")).read_bytes() == MOVIE


@pytest.mark.parametrize("fallback", [False, True])
def test_publication_uses_no_clobber_link_or_public_bionic_rename_only(tmp_path, monkeypatch, fallback):
    from app import capture_video_upload as video
    import ctypes
    source, target = tmp_path / "pending.json", tmp_path / "receipt.json"
    source.write_bytes(b"complete receipt")
    real_link = os.link
    calls = []

    class Rename:
        def __call__(self, old_dir, old, new_dir, new, flags):
            calls.append((old_dir, new_dir, flags))
            assert Path(os.fsdecode(old)).parent == Path(os.fsdecode(new)).parent
            assert (old_dir, new_dir, flags) == (-100, -100, 1)
            if target.exists():
                ctypes.set_errno(errno.EEXIST)
                return -1
            target.write_bytes(source.read_bytes())
            source.unlink()
            return 0

    class Libc:
        renameat2 = Rename()

    if fallback:
        monkeypatch.setattr(video.os, "link", lambda *_: (_ for _ in ()).throw(NotImplementedError()))
        monkeypatch.setattr(ctypes, "CDLL", lambda name, use_errno: Libc())
    else:
        monkeypatch.setattr(video.os, "link", real_link)
        monkeypatch.setattr(ctypes, "CDLL", lambda *_a, **_kw: pytest.fail("regular link must not need libc"))
    video._publish_noreplace(source, target)
    assert target.read_bytes() == b"complete receipt"
    if not source.exists():
        source.write_bytes(b"conflicting receipt")
    with pytest.raises(FileExistsError):
        video._publish_noreplace(source, target)
    assert target.read_bytes() == b"complete receipt"
    assert len(calls) == (2 if fallback else 0)
