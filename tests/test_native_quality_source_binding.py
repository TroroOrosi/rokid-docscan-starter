"""Chosen native originals reach Work unchanged; no Android or quality claim."""

import hashlib
import io
import json
import sqlite3
from pathlib import Path

from PIL import Image, ImageDraw

from tests.test_native_capture_upload import create_document, native_image, provenance, upload
from tests.test_work_bridge import client as _client_fixture, wait_for

client = _client_fixture


def test_selected_B_original_is_bound_through_upload_to_work_source_bytes(client):
    from app import main
    from app.capture_provenance import validate_capture_provenance
    from app.work_bridge import WorkStore

    original_a = native_image()
    image_b = Image.new("RGB", (24, 32), (220, 70, 30))
    ImageDraw.Draw(image_b).rectangle((3, 7, 18, 25), fill="black")
    buffer = io.BytesIO()
    image_b.save(buffer, "JPEG")
    original_b = buffer.getvalue()
    metadata_a = provenance(original_a)
    metadata_b = provenance(original_b, capture_id="33333333-3333-4333-8333-333333333333",
                            image_timestamp_ns=200, result_timestamp_ns=200, frame_number=4)
    assert len(metadata_a) == len(metadata_b) == 16
    assert validate_capture_provenance(metadata_a) == metadata_a
    assert validate_capture_provenance(metadata_b) == metadata_b
    assert metadata_a["jpeg_sha256"] != metadata_b["jpeg_sha256"]

    # Android's decision is an input here: only its chosen B crosses the API.
    document = create_document(client)
    response = upload(client, document, original_b, metadata_b)
    assert response.status_code == 201, response.text
    receipt = response.json()
    canonical_path = Path(receipt["image_path"])
    canonical_b = canonical_path.read_bytes()
    canonical_hash = hashlib.sha256(canonical_b).hexdigest()
    assert receipt["capture_provenance"] == metadata_b
    assert receipt["canonical_image_sha256"] == canonical_hash
    with Image.open(io.BytesIO(original_b)) as decoded_b, Image.open(io.BytesIO(original_a)) as decoded_a:
        expected_b = decoded_b.convert("RGB").transpose(Image.Transpose.ROTATE_90)
        expected_a = decoded_a.convert("RGB").transpose(Image.Transpose.ROTATE_90)
    with Image.open(io.BytesIO(canonical_b)) as saved:
        assert saved.format == "PNG" and saved.size == (32, 24)
        assert saved.tobytes() == expected_b.tobytes()
        assert saved.tobytes() != expected_a.tobytes()
    assert list(main.IMAGE_DIR.iterdir()) == [canonical_path]
    with main.db.connect() as conn:
        pages = conn.execute("SELECT capture_metadata_json FROM pages WHERE document_id=?", (document,)).fetchall()
    assert [json.loads(row[0]) for row in pages] == [{"capture_provenance": metadata_b,
                                                   "canonical_image_sha256": canonical_hash}]

    assert client.post(f"/v1/documents/{document}/finalize").status_code == 200
    session = client.post("/v1/exam-sessions", json={"document_id": document, "mode": "study"}).json()["session_id"]
    assert client.post("/v1/glasses/state", json={"device_id": "selected-native-fixture",
        "session_id": session, "generation": 9, "sequence": 1, "phase": "analyzing"}).json()["accepted"]
    assert client.post(f"/v1/exam-sessions/{session}/finalize-reading?solve=background").status_code == 200
    job = wait_for(lambda: (client.get("/v1/work/jobs").json().get("jobs") or [None])[0])
    wait_for(lambda: session not in main._background_solves)
    assert job["sources"][0]["capture_provenance"] == metadata_b
    assert job["sources"][0]["canonical_image_sha256"] == job["sources"][0]["sha256"] == canonical_hash

    # Inspect the real durable enqueue, rather than substituting a solver result.
    store = WorkStore(main.config.DATA_DIR)
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT source_id,data,sha256 FROM sources WHERE job_id=?", (job["job_id"],)).fetchall() == [
            ("p1", canonical_b, canonical_hash)]
    sealed, manifest = store.read_source(job["job_id"], "p1")
    assert sealed == canonical_b
    assert manifest["capture_provenance"] == metadata_b
    assert manifest["capture_provenance"]["capture_id"] != metadata_a["capture_id"]
    assert manifest["capture_provenance"]["jpeg_sha256"] != metadata_a["jpeg_sha256"]
