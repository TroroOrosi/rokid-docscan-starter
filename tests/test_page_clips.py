"""A page that was recorded keeps the clip it was cut from beside it, until the clip is gathered into the page's image.

The glasses send the page as one frame of the clip (the ordinary page upload, source kind ``clip_frame``) and then the
clip with the record written beside it (docs/superpowers/specs/2026-11-15-gathered-capture-design.md, 6.5 to 6.7).
The clips here are bytes with an MP4 signature: nothing decodes them.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from tests.test_native_capture_upload import create_document, native_image, provenance, upload
from tests.test_work_bridge import client as _client_fixture

client = _client_fixture

CAPTURE = "11111111-1111-4111-8111-111111111111"
RETAKE = "33333333-3333-4333-8333-333333333333"
MOVIE = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"one page of frames" * 4000
RECORD = {"schema": 1, "capture_id": CAPTURE, "width": 2016, "height": 1512, "rotation_degrees": 270,
          "frames": [{"t_ns": 1000 + k, "smear_px": 0.4} for k in range(8)], "dropped": 0, "settle": 6}


def page(client, document, capture=CAPTURE, kind="clip_frame"):
    raw = native_image()
    response = upload(client, document, raw, provenance(raw, source_kind=kind, capture_id=capture))
    assert response.status_code == 201, response.text
    return response.json()


def send(client, document, movie=MOVIE, *, page_index=0, capture=CAPTURE, sha256=None, record=None):
    return client.post(f"/v1/documents/{document}/pages/{page_index}/clip",
                       data={"capture_id": capture, "sha256": sha256 or hashlib.sha256(movie).hexdigest(),
                             "record": json.dumps(RECORD) if record is None else record},
                       files={"clip": ("page-1.mp4", movie, "video/mp4")})


def kept():
    """Every file under the clips' directory, whatever its name: a temporary file left behind is found too."""
    from app import config

    return sorted(path for path in (config.DATA_DIR / "page-clips").rglob("*") if path.is_file())


def test_a_clip_is_stored_beside_its_page(client):
    from app import config

    document = create_document(client)
    page(client, document)
    response = send(client, document)
    assert response.status_code == 201, response.text
    digest = hashlib.sha256(MOVIE).hexdigest()
    assert response.json() == {"status": "stored", "sha256": digest, "bytes": len(MOVIE)}
    target = config.DATA_DIR / "page-clips" / str(document) / "0" / f"{digest}.mp4"
    assert kept() == [target] and hashlib.sha256(target.read_bytes()).hexdigest() == digest
    listed = client.get(f"/v1/documents/{document}/clips")
    assert listed.status_code == 200
    assert listed.json() == {"clips": [{"page_index": 0, "status": "stored", "reason": None, "used": None,
                                        "total": None, "level": None, "bytes": len(MOVIE)}]}
    assert client.get("/v1/documents/999/clips").status_code == 404


def test_the_same_clip_again_is_a_replay(client):
    document = create_document(client)
    page(client, document)
    assert send(client, document).status_code == 201
    again = send(client, document)
    assert again.status_code == 200, again.text
    assert again.json() == {"status": "stored", "sha256": hashlib.sha256(MOVIE).hexdigest(), "bytes": len(MOVIE)}
    assert len(kept()) == 1
    assert len(client.get(f"/v1/documents/{document}/clips").json()["clips"]) == 1


def test_a_retake_replaces_the_clip(client):
    from app import page_clips

    document = create_document(client)
    page(client, document)
    assert send(client, document).status_code == 201
    first = kept()
    row = page_clips.claim()  # the first clip was already being worked on when the page was taken again
    assert (row["document_id"], row["page_index"], row["sha256"]) == (document, 0, hashlib.sha256(MOVIE).hexdigest())
    page(client, document, capture=RETAKE)
    assert send(client, document).status_code == 409, "the first clip is not the clip of the page that is there now"
    other = MOVIE + b"taken again"
    response = send(client, document, other, capture=RETAKE)
    assert response.status_code == 201, response.text
    digest = hashlib.sha256(other).hexdigest()
    assert response.json() == {"status": "stored", "sha256": digest, "bytes": len(other)}
    assert [(clip["sha256"], clip["status"], clip["capture_id"]) for clip in page_clips.rows(document)] == [(digest, "stored", RETAKE)]
    assert not first[0].exists() and [path.name for path in kept()] == [f"{digest}.mp4"]
    # What the worker of the first clip reports afterwards belongs to no row: the new clip stays to be gathered.
    page_clips.finish(document, 0, row["sha256"], used=5, total=6, level=40.0)
    page_clips.fail(document, 0, row["sha256"], "not placed")
    assert [(clip["status"], clip["reason"], clip["used"]) for clip in page_clips.rows(document)] == [("stored", None, None)]
    assert page_clips.pending(document) == 1


def test_a_clip_of_another_capture_is_refused(client):
    document = create_document(client)
    page(client, document)
    response = send(client, document, capture=RETAKE)
    assert response.status_code == 409, response.text
    assert kept() == [] and client.get(f"/v1/documents/{document}/clips").json() == {"clips": []}
    still = create_document(client)
    raw = native_image()
    assert client.post(f"/v1/documents/{still}/pages", data={"page_index": 0},
                       files={"image": ("page.jpg", raw, "image/jpeg")}).status_code == 201
    assert send(client, still).status_code == 409, "a page uploaded without its capture's record has no clip"
    assert kept() == []


def test_a_clip_without_its_page_is_refused(client):
    document = create_document(client)
    assert send(client, document).status_code == 404
    page(client, document)
    assert send(client, document, page_index=1).status_code == 404
    assert send(client, 999).status_code == 404
    assert kept() == []


def test_a_clip_after_the_booklet_is_ready_is_refused(client):
    document = create_document(client)
    page(client, document)
    assert client.post(f"/v1/documents/{document}/finalize").status_code == 200
    response = send(client, document)
    assert response.status_code == 409, response.text
    assert kept() == []


def test_a_damaged_clip_is_refused(client, monkeypatch):
    from app import page_clips

    document = create_document(client)
    page(client, document)
    assert send(client, document, sha256="0" * 64).status_code == 400
    assert send(client, document, sha256="not a hash").status_code == 400
    assert send(client, document, b"\x00\x00\x00\x18moov" + MOVIE[8:]).status_code == 400, "no MP4 signature"
    assert send(client, document, b"ftyp").status_code == 400
    assert send(client, document, record="{not json").status_code == 400
    assert send(client, document, record="[]").status_code == 400
    monkeypatch.setattr(page_clips, "MAX_BYTES", len(MOVIE) - 1)
    assert send(client, document).status_code == 413
    assert kept() == [] and client.get(f"/v1/documents/{document}/clips").json() == {"clips": []}


def test_clip_frame_is_a_capture_kind(client):
    document = create_document(client)
    receipt = page(client, document)
    assert receipt["capture_provenance"]["source_kind"] == "clip_frame" and len(receipt["capture_provenance"]) == 16
    raw = native_image()
    unknown = upload(client, create_document(client), raw, provenance(raw, source_kind="clip"))
    assert unknown.status_code == 400


WITHOUT_NUMPY = r'''
import sys
sys.modules["numpy"] = None  # importing numpy fails from here on, as on a phone without the package
import hashlib, io, json
from fastapi.testclient import TestClient
from PIL import Image
from app import main

with TestClient(main.app) as client:  # the server's own start, with its gathering workers
    doc = client.post("/v1/documents", json={"title": "no numpy"}).json()["document_id"]
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (90, 90, 90)).save(buffer, "JPEG")
    raw = buffer.getvalue()
    capture = "11111111-1111-4111-8111-111111111111"
    source = {"schema": 1, "source_kind": "clip_frame", "capture_id": capture,
              "local_session_id": "22222222-2222-4222-8222-222222222222", "jpeg_sha256": hashlib.sha256(raw).hexdigest(),
              "width": 64, "height": 48, "page_index": 0, "rotation_degrees": 270, "image_timestamp_ns": 100,
              "result_timestamp_ns": 100, "frame_number": 3, "exposure_ns": 30000000, "sensitivity_iso": 800,
              "af_state": 0, "ae_state": 2}
    page = client.post(f"/v1/documents/{doc}/pages", files={"image": ("page.jpg", raw, "image/jpeg")},
                       data={"page_index": "0", "image_rotation": "270", "capture_provenance": json.dumps(source)})
    movie = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"one page of frames" * 1000
    clip = client.post(f"/v1/documents/{doc}/pages/0/clip", files={"clip": ("page.mp4", movie, "video/mp4")},
                       data={"capture_id": capture, "record": "{}", "sha256": hashlib.sha256(movie).hexdigest()})
    finalized = client.post(f"/v1/documents/{doc}/finalize")  # waits for the worker to give the clip up
    clips = client.get(f"/v1/documents/{doc}/clips").json()["clips"]
print("RESULT " + json.dumps({"page": page.status_code, "clip": clip.status_code, "finalize": finalized.status_code,
                              "clips": [(row["status"], row["reason"]) for row in clips],
                              "page_kept": finalized.json().get("page_count")}))
'''


def test_the_server_starts_and_keeps_the_page_without_numpy(tmp_path):
    # app/gather.py imports numpy when it is imported. The server must start, take the clip and go on without it.
    environment = {key: value for key, value in os.environ.items() if not key.startswith("ROKID_")}
    done = subprocess.run([sys.executable, "-X", "utf8", "-c", WITHOUT_NUMPY], capture_output=True, text=True, encoding="utf-8",
                          env=dict(environment, ROKID_DATA_DIR=str(tmp_path), PYTHONIOENCODING="utf-8"),
                          cwd=Path(__file__).resolve().parents[1], timeout=120)
    lines = [line for line in done.stdout.splitlines() if line.startswith("RESULT ")]
    assert lines, done.stderr[-2000:]
    assert json.loads(lines[-1][7:]) == {"page": 201, "clip": 201, "finalize": 200, "page_kept": 1,
                                         "clips": [["failed", "numpy unavailable"]]}


def test_work_is_claimed_oldest_first_and_taken_up_again_after_a_restart(client):
    from app import page_clips

    document = create_document(client)
    for index, capture in enumerate((CAPTURE, RETAKE)):
        raw = native_image()
        assert upload(client, document, raw, provenance(raw, source_kind="clip_frame", capture_id=capture, page_index=index),
                      page_index=index).status_code == 201
        assert send(client, document, MOVIE + bytes([index]), page_index=index, capture=capture).status_code == 201
    assert page_clips.pending(document) == 2
    first = page_clips.claim()
    assert (first["page_index"], first["status"], json.loads(first["record_json"])) == (0, "gathering", RECORD)
    assert page_clips.claim()["page_index"] == 1 and page_clips.claim() is None
    assert page_clips.pending(document) == 2, "a clip being gathered is not finished"
    page_clips.finish(document, 0, first["sha256"], used=54, total=60, level=41.5)
    page_clips.fail(document, 1, hashlib.sha256(MOVIE + b"\x01").hexdigest(), "too dark")
    assert page_clips.pending(document) == 0
    assert [(clip["status"], clip["reason"], clip["used"], clip["total"], clip["level"]) for clip in page_clips.rows(document)] == [
        ("done", None, 54, 60, 41.5), ("failed", "too dark", None, None, None)]
    with page_clips.db.connect() as conn:
        conn.execute("UPDATE page_clips SET status = 'gathering' WHERE page_index = 1")
        conn.commit()
    page_clips.requeue_interrupted()  # the server stopped while that clip was being gathered
    assert [clip["status"] for clip in page_clips.rows(document)] == ["done", "stored"]
