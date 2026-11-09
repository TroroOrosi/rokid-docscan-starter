"""Native identity accompanies canonical PNGs through immutable Work handoff."""

import hashlib
import io
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from PIL import Image

from tests.test_native_capture_upload import create_document, native_image, provenance, upload
from tests.test_work_bridge import client as _client_fixture, picture, wait_for

client = _client_fixture


def native_job(client, source_kind="native_still", *, raw=None, rotation=270, legacy=False, exam_type="written"):
    from app import main

    document, raw = create_document(client), native_image() if raw is None else raw
    response = upload(client, document, raw, provenance(raw, source_kind=source_kind, rotation_degrees=rotation),
                      image_rotation=rotation)
    assert response.status_code == 201, response.text
    receipt = response.json()
    if legacy:
        Path(receipt["image_path"]).with_suffix(".jpg").unlink()
    assert client.post(f"/v1/documents/{document}/finalize").status_code == 200
    session = client.post("/v1/exam-sessions", json={"document_id": document, "mode": "study",
                                                   "exam_type": exam_type}).json()["session_id"]
    assert client.post("/v1/glasses/state", json={"device_id": "native-glasses", "session_id": session,
        "generation": 7, "sequence": 1, "phase": "analyzing"}).json()["accepted"]
    assert client.post(f"/v1/exam-sessions/{session}/finalize-reading?solve=background").status_code == 200
    job = wait_for(lambda: (client.get("/v1/work/jobs").json().get("jobs") or [None])[0])
    wait_for(lambda: session not in main._background_solves)
    return document, session, receipt, job


@pytest.mark.parametrize("source_kind", ["native_still", "zsl_reprocess"])
def test_native_identity_reaches_work_manifest_and_survives_solver_and_store_restart(client, source_kind):
    from app import main
    from app.solvers.base import Question
    from app.solvers.chatgpt_work import ChatGptWorkSolver
    from app.work_bridge import WorkPending, WorkStore

    document, session, receipt, job = native_job(client, source_kind)
    source = job["sources"][0]
    assert source["capture_provenance"] == receipt["capture_provenance"]
    assert source["canonical_image_sha256"] == source["sha256"] == receipt["canonical_image_sha256"]
    assert source["sha256"] != source["capture_provenance"]["jpeg_sha256"]
    with main.db.connect() as conn:
        pages = main._document_source_pages(conn, document, session)
    assert pages[0]["capture_provenance"] == source["capture_provenance"]
    question = Question(chat_key=f"session:{session}", document_pages=pages)
    with pytest.raises(WorkPending, match=job["job_id"]):
        ChatGptWorkSolver().answer_all(question=question)
    restarted = WorkStore(main.config.DATA_DIR)
    assert restarted.get(job["job_id"])["manifest_sha256"] == job["manifest_sha256"]
    assert restarted.get(job["job_id"])["sources"] == job["sources"]
    raw, _ = restarted.read_source(job["job_id"], "p1")
    assert raw == Path(receipt["image_path"]).read_bytes()


@pytest.mark.parametrize("changed_field", ["capture_id", "source_kind"])
@pytest.mark.parametrize("source_kind", ["native_still", "zsl_reprocess"])
@pytest.mark.parametrize("original_jpeg", [False, True])
def test_same_png_from_different_native_capture_rejects_late_work_result(
        client, monkeypatch, source_kind, changed_field, original_jpeg):
    from app import main

    monkeypatch.setenv("ROKID_WORK_ORIGINAL_JPEG", "1" if original_jpeg else "0")
    document, _, receipt, job = native_job(client, source_kind)
    assert main._work_current_job(job["job_id"])[1]["job_id"] == job["job_id"]
    replacement = {"capture_provenance": {**receipt["capture_provenance"],
                      "capture_id": "33333333-3333-4333-8333-333333333333"},
                   "canonical_image_sha256": receipt["canonical_image_sha256"]}
    if changed_field == "source_kind":
        replacement["capture_provenance"]["capture_id"] = receipt["capture_provenance"]["capture_id"]
        replacement["capture_provenance"]["source_kind"] = "native_still" if source_kind == "zsl_reprocess" else "zsl_reprocess"
    with main.db.connect() as conn:
        # Simulate restored/replaced input while an old Work reply was in flight.
        conn.execute("UPDATE pages SET capture_metadata_json=? WHERE document_id=?", (json.dumps(replacement), document))
        conn.commit()
    assert hashlib.sha256(Path(receipt["image_path"]).read_bytes()).hexdigest() == job["sources"][0]["canonical_image_sha256"]
    with pytest.raises(HTTPException) as error:
        main._work_current_job(job["job_id"])
    assert error.value.status_code == 409


@pytest.mark.parametrize("source_kind", ["native_still", "zsl_reprocess"])
@pytest.mark.parametrize("changed_field", ["capture_id", "frame_number", "source_kind", "legacy"])
@pytest.mark.parametrize("original_jpeg", [False, True])
def test_same_png_with_changed_native_identity_rejects_a_late_failed_work_attempt(
        client, monkeypatch, changed_field, source_kind, original_jpeg):
    from app import main
    from app.solvers.base import Question
    from app.work_bridge import WorkConflict

    monkeypatch.setenv("ROKID_WORK_ORIGINAL_JPEG", "1" if original_jpeg else "0")
    document, session, receipt, _ = native_job(client, source_kind)
    with main.db.connect() as conn:
        saved_session = main._exam_session_or_404(conn, session)
        pages = main._document_source_pages(conn, document, session)
        question = Question(document_id=str(document), booklet_stage=saved_session["analysis_stage"],
                            audio_path=saved_session["audio_path"], document_pages=pages)
        attempt = main._work_attempt_identity(session, question)
    with main._work_reply_commit_guard(session, [], failed_attempt=attempt):
        pass  # An unchanged pending input may still record its own failure.
    replacement = {"capture_provenance": dict(receipt["capture_provenance"]),
                   "canonical_image_sha256": receipt["canonical_image_sha256"]}
    if changed_field == "capture_id":
        replacement["capture_provenance"][changed_field] = "33333333-3333-4333-8333-333333333333"
    elif changed_field == "frame_number":
        replacement["capture_provenance"][changed_field] += 1
    elif changed_field == "source_kind":
        replacement["capture_provenance"][changed_field] = "native_still" if source_kind == "zsl_reprocess" else "zsl_reprocess"
    with main.db.connect() as conn:
        # Restored/replaced input may keep identical PNG bytes and path.
        conn.execute("UPDATE pages SET capture_metadata_json=? WHERE document_id=?",
                     (None if changed_field == "legacy" else json.dumps(replacement), document))
        conn.commit()
    assert hashlib.sha256(Path(receipt["image_path"]).read_bytes()).hexdigest() == receipt["canonical_image_sha256"]
    with pytest.raises(WorkConflict, match="failed Work input is no longer current"):
        with main._work_reply_commit_guard(session, [], failed_attempt=attempt):
            pass


@pytest.mark.parametrize("source_kind", ["native_still", "zsl_reprocess"])
def test_work_store_seals_native_metadata_and_rejects_same_png_with_changed_capture(tmp_path, source_kind):
    from app.work_bridge import WorkConflict, WorkStore

    raw = picture()
    source = {"source_id": "p1", "page_number": 1, "data": raw, "mime_type": "image/png",
              "capture_provenance": provenance(native_image(), rotation_degrees=0, source_kind=source_kind),
              "canonical_image_sha256": hashlib.sha256(raw).hexdigest()}
    store = WorkStore(tmp_path)
    options = {"session_id": 1, "conversation_key": "session:1", "stage": "single", "system": "s", "prompt": "p"}
    job = store.enqueue(sources=[source], **options)
    assert job["sources"][0]["capture_provenance"] == source["capture_provenance"]
    assert WorkStore(tmp_path).enqueue(sources=[source], **options)["job_id"] == job["job_id"]
    changed = {**source, "capture_provenance": {**source["capture_provenance"], "frame_number": 4}}
    with pytest.raises(WorkConflict):
        store.enqueue(sources=[changed], **options)


@pytest.mark.parametrize("mutation", ["hash", "page", "dimension", "partial", "null"])
def test_work_store_rejects_native_metadata_not_bound_to_canonical_original(tmp_path, mutation):
    from app.work_bridge import WorkStore

    raw = picture()
    source = {"source_id": "p1", "page_number": 1, "data": raw, "mime_type": "image/png",
              "capture_provenance": provenance(native_image(), rotation_degrees=0),
              "canonical_image_sha256": hashlib.sha256(raw).hexdigest()}
    if mutation == "hash":
        source["canonical_image_sha256"] = "0" * 64
    elif mutation == "page":
        source["capture_provenance"]["page_index"] = 1
    elif mutation == "dimension":
        source["capture_provenance"]["width"] = 25
    elif mutation == "partial":
        del source["canonical_image_sha256"]
    else:
        source["capture_provenance"] = None
    with pytest.raises(ValueError):
        WorkStore(tmp_path).enqueue(session_id=1, conversation_key="session:1", stage="single", sources=[source],
                                    system="s", prompt="p")


def test_legacy_work_source_manifest_keeps_its_exact_old_identity(tmp_path):
    from app.work_bridge import WorkStore

    raw = picture()
    source = {"source_id": "p1", "page_number": 1, "mime_type": "image/png", "data": raw}
    job = WorkStore(tmp_path).enqueue(session_id=1, conversation_key="session:1", stage="single", sources=[source],
                                     system="s", prompt="p")
    assert job["sources"] == [{"source_id": "p1", "page_number": 1, "mime_type": "image/png",
                               "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}]


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("exif_orientation", [1, 6])
def test_opt_in_work_jpeg_preserves_original_bytes_explicit_rotation_and_ignores_exif(
        client, monkeypatch, rotation, exif_orientation):
    from app import main
    from app.solvers.chatgpt_work import ChatGptWorkSolver
    from app.work_bridge import configured_work_store
    from tests.test_chatgpt_work import BrowserReply, question_for

    output = io.BytesIO()
    image = Image.new("RGB", (24, 32), "white")
    for y in range(32):
        for x in range(24):
            image.putpixel((x, y), (x * 10, y * 7, (x + y) * 4))
    exif = image.getexif()
    exif[274] = exif_orientation
    image.save(output, "JPEG", exif=exif)
    raw = output.getvalue()
    monkeypatch.setenv("ROKID_WORK_ORIGINAL_JPEG", "1")
    document, session, receipt, job = native_job(client, raw=raw, rotation=rotation)
    source = job["sources"][0]
    assert source["mime_type"] == "image/jpeg"
    assert source["sha256"] == hashlib.sha256(raw).hexdigest() == source["capture_provenance"]["jpeg_sha256"]
    assert source["canonical_image_sha256"] == receipt["canonical_image_sha256"]
    with Image.open(io.BytesIO(raw)) as opened:
        expected = opened.convert("RGB").rotate(-rotation, expand=True)
    assert (source["width"], source["height"]) == (24, 32)
    assert (source["upright_width"], source["upright_height"]) == expected.size
    assert source["upright_rgb_sha256"] == hashlib.sha256(expected.tobytes()).hexdigest()
    assert configured_work_store().read_source(job["job_id"], "p1")[0] == raw
    # Recovery reads sealed bytes even after local sidecar loss and flag reversal.
    Path(receipt["image_path"]).with_suffix(".jpg").unlink()
    monkeypatch.setenv("ROKID_WORK_ORIGINAL_JPEG", "0")
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-web")
    assert main._work_current_job(job["job_id"])[1]["sources"] == job["sources"]
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-work")
    fake = BrowserReply()
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    answer = ChatGptWorkSolver(client=fake).answer_all(question=question_for(document, session))
    assert answer[0][1].answer == "4" and len(fake.calls) == 1
    assert "Do not apply EXIF orientation" in fake.calls[0]["prompt"]
    assert source["upright_rgb_sha256"] not in fake.calls[0]["prompt"]
    saved = configured_work_store().get(job["job_id"])
    assert saved["sources"] == job["sources"]
    assert saved["browser_review"]["images"][0]["source_sha256"] == source["sha256"]


@pytest.mark.parametrize("legacy", [False, True])
def test_work_jpeg_switch_keeps_preexisting_png_job_or_missing_legacy_original(client, monkeypatch, legacy):
    from app import main
    from app.solvers.chatgpt_work import ChatGptWorkSolver
    from app.work_bridge import WorkPending, configured_work_store
    from tests.test_chatgpt_work import question_for

    monkeypatch.setenv("ROKID_WORK_ORIGINAL_JPEG", "1" if legacy else "0")
    document, session, receipt, job = native_job(client, legacy=legacy)
    assert job["sources"][0]["mime_type"] == "image/png"
    monkeypatch.setenv("ROKID_WORK_ORIGINAL_JPEG", "1")
    with pytest.raises(WorkPending, match=job["job_id"]):
        ChatGptWorkSolver().answer_all(question=question_for(document, session))
    assert main._work_current_job(job["job_id"])[1]["sources"] == job["sources"]
    assert configured_work_store().read_source(job["job_id"], "p1")[0] == Path(receipt["image_path"]).read_bytes()


@pytest.mark.parametrize("missing_jpeg", [False, True])
def test_non_work_consumer_keeps_upright_png_after_jpeg_job_is_sealed(client, monkeypatch, missing_jpeg):
    from app import main
    from app.source_bundle import source_images

    monkeypatch.setenv("ROKID_WORK_ORIGINAL_JPEG", "1")
    document, session, receipt, job = native_job(client)
    canonical = Path(receipt["image_path"])
    if missing_jpeg:
        canonical.with_suffix(".jpg").unlink()
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-web")
    with main.db.connect() as conn:
        pages = main._document_source_pages(conn, document, session)
    assert pages[0]["image_path"] == str(canonical)
    assert "_work_source_job_id" not in pages[0]
    attached = list(source_images(pages))
    with Image.open(io.BytesIO(attached[0]["buffer"])) as image:
        assert image.size == (32, 24)
    assert main._work_current_job(job["job_id"])[1]["sources"] == job["sources"]
    with pytest.raises(main.WorkConflict, match="still current"):
        with main._expired_work_job_guard(job["job_id"]):
            pytest.fail("a representation switch cannot expire the original")


def test_sealed_jpeg_reuses_bound_pixel_evidence_without_decoding_again(client, monkeypatch):
    from app import main, work_bridge
    from app.solvers.chatgpt_work import ChatGptWorkSolver
    from tests.test_chatgpt_work import BrowserReply, question_for

    monkeypatch.setenv("ROKID_WORK_ORIGINAL_JPEG", "1")
    document, session, _, job = native_job(client)

    def unexpected_decode(*args):
        pytest.fail("immutable original pixel evidence was recomputed")

    monkeypatch.setattr(main, "jpeg_pixel_evidence", unexpected_decode)
    monkeypatch.setattr(work_bridge, "jpeg_pixel_evidence", unexpected_decode)
    assert main._work_current_job(job["job_id"])[1]["sources"] == job["sources"]
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    answers = ChatGptWorkSolver(client=BrowserReply()).answer_all(question=question_for(document, session))
    assert answers[0][1].answer == "4"
    assert work_bridge.configured_work_store().get(job["job_id"])["status"] == "completed"


@pytest.mark.parametrize("mutation", ["canonical_bytes", "canonical_binding", "jpeg_blob"])
def test_reusing_sealed_jpeg_evidence_still_rejects_changed_bytes_or_binding(client, monkeypatch, mutation):
    from app import main

    monkeypatch.setenv("ROKID_WORK_ORIGINAL_JPEG", "1")
    document, _, receipt, job = native_job(client)
    canonical = Path(receipt["image_path"])
    if mutation == "jpeg_blob":
        with main.configured_work_store()._connect() as conn:
            conn.execute("UPDATE sources SET data=? WHERE job_id=? AND source_id='p1'", (b"changed", job["job_id"]))
    elif mutation == "canonical_bytes":
        canonical.write_bytes(canonical.read_bytes() + b"changed")
    else:
        Image.new("RGB", (32, 24), "red").save(canonical, "PNG")
        metadata = {"capture_provenance": receipt["capture_provenance"],
                    "canonical_image_sha256": hashlib.sha256(canonical.read_bytes()).hexdigest()}
        with main.db.connect() as conn:
            conn.execute("UPDATE pages SET capture_metadata_json=? WHERE document_id=?", (json.dumps(metadata), document))
            conn.commit()
    with pytest.raises(HTTPException) as rejected:
        main._work_current_job(job["job_id"])
    assert rejected.value.status_code == 409
    assert main.configured_work_store().result(job["job_id"]) is None


def test_expired_native_jpeg_job_can_retire_after_public_page_replace(client, monkeypatch):
    from app import main

    monkeypatch.delenv("ROKID_ANALYZER", raising=False)
    monkeypatch.setenv("ROKID_WORK_ORIGINAL_JPEG", "1")
    document, session, _, job = native_job(client)
    owner = main.list_states()
    repeated = client.post(f"/v1/exam-sessions/{session}/finalize-reading")
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["status"] == "reading" and repeated.json()["problem_count"] == 0

    replacement = io.BytesIO()
    Image.new("RGB", (24, 32), "red").save(replacement, "JPEG")
    raw = replacement.getvalue()
    response = upload(client, document, raw, provenance(
        raw, capture_id="33333333-3333-4333-8333-333333333333"))
    assert response.status_code == 201 and response.json()["replaced"] is True
    assert main.list_states() == owner
    assert main.configured_work_store().result(job["job_id"]) is None
    with main._expired_work_job_guard(job["job_id"]) as retired:
        assert retired["job_id"] == job["job_id"]


@pytest.mark.parametrize("mutation", ["jpeg_bytes", "canonical_pixels"])
def test_new_work_jpeg_rejects_changed_original_or_different_canonical_pixels(client, monkeypatch, mutation):
    from app import main

    monkeypatch.setenv("ROKID_WORK_ORIGINAL_JPEG", "1")
    raw, document = native_image(), create_document(client)
    receipt = upload(client, document, raw, provenance(raw)).json()
    canonical = Path(receipt["image_path"])
    if mutation == "jpeg_bytes":
        canonical.with_suffix(".jpg").write_bytes(b"changed JPEG")
    else:
        Image.new("RGB", (32, 24), "red").save(canonical, "PNG")
        metadata = {"capture_provenance": receipt["capture_provenance"],
                    "canonical_image_sha256": hashlib.sha256(canonical.read_bytes()).hexdigest()}
        with main.db.connect() as conn:
            conn.execute("UPDATE pages SET capture_metadata_json=? WHERE document_id=?", (json.dumps(metadata), document))
            conn.commit()
    with main.db.connect() as conn, pytest.raises(ValueError, match="does not match|pixels do not match"):
        main._document_source_pages(conn, document, 123)
    assert main.configured_work_store().session_jobs(123) == []


@pytest.mark.parametrize(("field", "value"), [("rotation_degrees", 90), ("rotation_degrees", 270.0),
    ("upright_width", 31), ("upright_height", 23), ("upright_rgb_sha256", "0" * 64)])
def test_browser_jpeg_rejects_wrong_rotation_or_native_pixel_evidence_before_result_commit(
        client, monkeypatch, field, value):
    from app.solvers.chatgpt_work import ChatGptWorkSolver
    from app.work_bridge import WorkBrowserResultRejected, configured_work_store
    from tests.test_chatgpt_work import BrowserReply, question_for

    monkeypatch.setenv("ROKID_WORK_ORIGINAL_JPEG", "1")
    document, session, _, job = native_job(client)

    class WrongEvidence(BrowserReply):
        def complete_json(self, **options):
            result = super().complete_json(**options)
            result["extraction"]["files"][0][field] = value
            return result

    fake = WrongEvidence()
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    with pytest.raises(WorkBrowserResultRejected, match="extraction"):
        ChatGptWorkSolver(client=fake).answer_all(question=question_for(document, session))
    assert len(fake.calls) == 1
    assert configured_work_store().result(job["job_id"]) is None
    assert configured_work_store().get(job["job_id"])["status"] == "pending"
