"""Native identity accompanies canonical PNGs through immutable Work handoff."""

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from tests.test_native_capture_upload import create_document, native_image, provenance, upload
from tests.test_work_bridge import client as _client_fixture, picture, wait_for

client = _client_fixture


def native_job(client, source_kind="native_still"):
    from app import main

    document, raw = create_document(client), native_image()
    response = upload(client, document, raw, provenance(raw, source_kind=source_kind))
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert client.post(f"/v1/documents/{document}/finalize").status_code == 200
    session = client.post("/v1/exam-sessions", json={"document_id": document, "mode": "study"}).json()["session_id"]
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
def test_same_png_from_different_native_capture_rejects_late_work_result(client, source_kind, changed_field):
    from app import main

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
    assert hashlib.sha256(Path(receipt["image_path"]).read_bytes()).hexdigest() == job["sources"][0]["sha256"]
    with pytest.raises(HTTPException) as error:
        main._work_current_job(job["job_id"])
    assert error.value.status_code == 409


@pytest.mark.parametrize("source_kind", ["native_still", "zsl_reprocess"])
@pytest.mark.parametrize("changed_field", ["capture_id", "frame_number", "source_kind", "legacy"])
def test_same_png_with_changed_native_identity_rejects_a_late_failed_work_attempt(client, changed_field, source_kind):
    from app import main
    from app.solvers.base import Question
    from app.work_bridge import WorkConflict

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
