"""A recorded page's clip is gathered on the phone into the page's image; a clip that cannot be leaves the page as it came.

The page arrives as one frame of its clip, so it exists whatever happens to the clip afterwards
(docs/superpowers/specs/2026-11-15-gathered-capture-design.md, 6.5 to 6.7). The clips are generated scenes written by
ffmpeg, as in tests/test_gather.py; without numpy this module is skipped, without ffmpeg the tests that need a clip are.
"""
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tests.test_gather import clip, frames, np, scene
from tests.test_native_capture_upload import create_document, native_image, provenance, upload
from tests.test_page_clips import CAPTURE, MOVIE, RETAKE, page, send
from tests.test_recorded_route import REPLY
from tests.test_work_bridge import client as _client_fixture

client = _client_fixture


def sha(content):
    return hashlib.sha256(content).hexdigest()


def page_row(document, index=0):
    from app import db

    with closing(db.connect()) as conn:
        return dict(conn.execute("SELECT * FROM pages WHERE document_id = ? AND page_index = ?", (document, index)).fetchone())


def recorded(client, tmp_path, fs=None):
    """A booklet with one recorded page: the frame it arrived as, and its clip waiting to be gathered."""
    document = create_document(client)
    receipt = page(client, document)
    movie = MOVIE if fs is None else clip(tmp_path, fs).read_bytes()
    assert send(client, document, movie).status_code == 201
    return document, receipt, movie


def left_as_it_came(document, receipt):
    stored = page_row(document)
    return (stored["image_path"] == receipt["image_path"]
            and sha(Path(stored["image_path"]).read_bytes()) == receipt["canonical_image_sha256"]
            and json.loads(stored["capture_metadata_json"]) == {"capture_provenance": receipt["capture_provenance"],
                                                                "canonical_image_sha256": receipt["canonical_image_sha256"]})


def state(document):
    from app import page_clips

    return [(row["status"], row["reason"]) for row in page_clips.rows(document)]


def test_a_stored_clip_becomes_the_page(client, tmp_path):
    from app import main, page_clips

    document, receipt, movie = recorded(client, tmp_path, frames(scene(), [(0, 0)] * 30, 4.0))
    assert main.gather_service.process_one() is True
    row = page_clips.rows(document)[0]
    assert (row["status"], row["reason"], row["total"]) == ("done", None, 30 - 6)
    assert 0 < row["used"] <= row["total"] and row["level"] >= 8
    stored = page_row(document)
    image = Path(stored["image_path"])
    assert stored["image_path"] != receipt["image_path"] and not Path(receipt["image_path"]).exists()
    assert sha(image.read_bytes()) != receipt["canonical_image_sha256"]
    with Image.open(image) as gathered:
        # The scene is 384 rows of 512 and lies on its side, as the sensor sees a page; rotation 270 turns it upright.
        assert (gathered.format, gathered.mode, gathered.size) == ("PNG", "RGB", (384, 512))
    metadata = json.loads(stored["capture_metadata_json"])
    assert metadata == {"capture_provenance": receipt["capture_provenance"], "canonical_image_sha256": sha(image.read_bytes()),
                        "gathered": {"used": row["used"], "total": row["total"], "level_over_noise": row["level"],
                                     "clip_sha256": sha(movie)}}
    assert Path(receipt["image_path"]).with_suffix(".jpg").read_bytes() == native_image(), "the frame the page came as is kept"
    assert main.gather_service.process_one() is False
    # The page's own upload, sent again because its receipt was lost, is still that capture and changes nothing.
    raw = native_image()
    again = upload(client, document, raw, provenance(raw, source_kind="clip_frame"))
    assert again.status_code == 201, again.text
    assert again.json()["canonical_image_sha256"] == metadata["canonical_image_sha256"]
    assert page_row(document) == stored


def test_a_clip_that_cannot_be_placed_leaves_the_page(client, tmp_path):
    from app import main

    blank = [np.full((192, 256), 0.5, np.float32)] * 30  # nothing in the view to place one frame on another by
    document, receipt, _ = recorded(client, tmp_path, blank)
    assert main.gather_service.process_one() is True
    assert state(document) == [("failed", "not placed")]
    assert left_as_it_came(document, receipt)


def test_without_numpy_the_page_stays(client, tmp_path, monkeypatch):
    from app import main, page_gather

    def missing():
        raise ImportError("No module named 'numpy'")

    monkeypatch.setattr(page_gather, "_gather_module", missing)
    document, receipt, _ = recorded(client, tmp_path)
    assert main.gather_service.process_one() is True
    assert state(document) == [("failed", "numpy unavailable")]
    assert left_as_it_came(document, receipt)


def test_without_ffmpeg_the_page_stays(client, tmp_path, monkeypatch):
    from app import main

    monkeypatch.setenv("ROKID_FFMPEG", str(tmp_path / "no-such-ffmpeg"))
    document, receipt, _ = recorded(client, tmp_path)
    assert main.gather_service.process_one() is True
    assert state(document) == [("failed", "ffmpeg unavailable")]
    assert left_as_it_came(document, receipt)


def test_whatever_stops_a_clip_is_its_reason_and_the_next_clip_is_taken(client, tmp_path, monkeypatch):
    from app import main, page_gather

    document, receipt, _ = recorded(client, tmp_path)  # bytes with an MP4 signature that no decoder can read
    raw = native_image()
    assert upload(client, document, raw, provenance(raw, source_kind="clip_frame", capture_id=RETAKE, page_index=1),
                  page_index=1).status_code == 201
    good = clip(tmp_path, frames(scene(), [(0, 0)] * 20, 4.0)).read_bytes()
    assert send(client, document, good, page_index=1, capture=RETAKE).status_code == 201
    monkeypatch.setattr(page_gather, "CLIP_SECONDS", -1.0)  # the second clip is out of time at its first frame
    assert main.gather_service.process_one() is True and main.gather_service.process_one() is True
    first, second = state(document)
    assert first[0] == "failed" and first[1].startswith("gather error: ")
    assert second == ("failed", "timeout")
    assert left_as_it_came(document, receipt)
    assert main.gather_service.process_one() is False


def test_interrupted_work_is_taken_up_again(client, tmp_path, monkeypatch):
    from app import main, page_clips, page_gather

    def missing():
        raise ImportError("No module named 'numpy'")

    monkeypatch.setattr(page_gather, "_gather_module", missing)  # this test is about who takes the clip, not the gathering
    document, _, _ = recorded(client, tmp_path)
    assert page_clips.claim()["status"] == "gathering"  # the server stopped while this clip was being gathered
    assert page_clips.claim() is None
    page_clips.requeue_interrupted()
    assert state(document) == [("stored", None)]
    assert page_clips.claim() is not None

    def settled():
        until = time.monotonic() + 4  # under the workers' own five-second look: they were woken
        while time.monotonic() < until and page_clips.pending(document):
            time.sleep(0.05)
        return state(document)

    with TestClient(main.app, headers={"Authorization": "Bearer local-test-key"}) as running:  # the server starts again
        assert settled() == [("failed", "numpy unavailable")], "the started workers took the interrupted clip"
        raw = native_image()
        assert upload(running, document, raw, provenance(raw, source_kind="clip_frame", capture_id=RETAKE, page_index=1),
                      page_index=1).status_code == 201
        assert send(running, document, MOVIE + b"next page", page_index=1, capture=RETAKE).status_code == 201
        assert settled()[1] == ("failed", "numpy unavailable"), "a clip that arrives wakes a worker"


def test_the_page_image_is_upright():
    from app import page_gather
    from app.gather import Gathered

    lying = np.full((30, 40), 0.2, np.float32)  # as the sensor sees an upright page: wider than tall
    lying[:6, -8:] = 0.8  # the page's top left corner is at the sensor's top right
    png = page_gather.page_image(Gathered(lying, 12, 12, 40.0, True, "none"), 270)
    with Image.open(io.BytesIO(png)) as upright:
        assert (upright.format, upright.mode, upright.size) == ("PNG", "RGB", (30, 40))
        assert upright.getpixel((2, 2)) == (255, 255, 255), "the brightest half percent is white"
        assert max(upright.getpixel((27, 37))) < 160 and max(upright.getpixel((27, 2))) < 160


def test_only_the_page_the_clip_was_cut_from_is_replaced(client, tmp_path, monkeypatch):
    from app import main, page_clips

    monkeypatch.setenv("ROKID_GATHER_WAIT_S", "0")
    picture = io.BytesIO()
    Image.new("RGB", (48, 64), (200, 200, 200)).save(picture, "PNG")
    document, receipt, movie = recorded(client, tmp_path)
    note = {"used": 5, "total": 6, "level_over_noise": 40.0, "clip_sha256": sha(movie)}
    page(client, document, capture=RETAKE)  # taken again while the first clip was being gathered
    taken_again = page_row(document)
    files = sorted(main.IMAGE_DIR.iterdir())
    assert main.replace_page_image(document, 0, picture.getvalue(), note) is False
    assert main.gather_service.process_one() is True
    assert state(document)[0][0] == "failed" and state(document)[0][1].startswith("gather error: ")
    assert page_row(document) == taken_again and sorted(main.IMAGE_DIR.iterdir()) == files

    other, receipt, movie = recorded(client, tmp_path)
    assert page_clips.claim() is not None
    assert client.post(f"/v1/documents/{other}/finalize").status_code == 200  # went on without this clip
    files = sorted(main.IMAGE_DIR.iterdir())
    assert main.replace_page_image(other, 0, picture.getvalue(), {**note, "clip_sha256": sha(movie)}) is False
    assert page_row(other)["image_path"] == receipt["image_path"] and sorted(main.IMAGE_DIR.iterdir()) == files
    assert CAPTURE in page_row(other)["capture_metadata_json"]


def test_a_page_does_not_change_under_a_finalization_that_is_reading_the_pages(client, tmp_path):
    # A page whose image changes while its booklet is being finalized ends the finalization with a 409, and the glasses
    # stop on that answer. A clip that is gathered late therefore waits for the finalizer's lock, and then finds the
    # booklet closed.
    from app import db, main, page_clips

    picture = io.BytesIO()
    Image.new("RGB", (48, 64), (200, 200, 200)).save(picture, "PNG")
    document, receipt, movie = recorded(client, tmp_path)
    assert page_clips.claim() is not None
    note = {"used": 5, "total": 6, "level_over_noise": 40.0, "clip_sha256": sha(movie)}
    with ThreadPoolExecutor(max_workers=1) as pool:
        with main._document_finalize_mutex(document):  # a finalization that stopped waiting for this clip
            replacing = pool.submit(main.replace_page_image, document, 0, picture.getvalue(), note)
            time.sleep(0.3)
            assert not replacing.done()
            with closing(db.connect()) as conn, conn:
                conn.execute("UPDATE documents SET status = 'ready' WHERE id = ?", (document,))
        assert replacing.result(timeout=10) is False
    assert left_as_it_came(document, receipt)


# The booklet waits for its clips, and the answers name the recorded pages that stayed one frame.


def test_finalize_waits_for_the_gathering(client, tmp_path):
    from app import main

    document, receipt, _ = recorded(client, tmp_path, frames(scene(), [(0, 0)] * 30, 4.0))
    with ThreadPoolExecutor(max_workers=1) as pool:  # no worker runs here: the test turns the gathering by hand
        finalizing = pool.submit(client.post, f"/v1/documents/{document}/finalize")
        time.sleep(0.3)
        assert not finalizing.done(), "finalization waits while the clip is still to be gathered"
        assert main.gather_service.process_one() is True
        response = finalizing.result(timeout=30)
    assert response.status_code == 200, response.text
    assert state(document) == [("done", None)]
    stored = page_row(document)
    assert stored["image_path"] != receipt["image_path"] and "gathered" in json.loads(stored["capture_metadata_json"])
    assert stored["summary"] is not None, "the booklet was finalized on the gathered page"


def test_finalize_goes_on_after_the_limit(client, tmp_path, monkeypatch, capsys):
    from app import main

    monkeypatch.setenv("ROKID_GATHER_WAIT_S", "1")
    document, receipt, _ = recorded(client, tmp_path)
    started = time.monotonic()
    response = client.post(f"/v1/documents/{document}/finalize")
    elapsed = time.monotonic() - started
    assert response.status_code == 200, response.text
    assert 1 <= elapsed < 3
    assert state(document) == [("stored", None)] and left_as_it_came(document, receipt)
    waited = [json.loads(line) for line in capsys.readouterr().out.splitlines() if '"gather_wait"' in line]
    assert len(waited) == 1 and waited[0]["document_id"] == document and waited[0]["left"] == 1 and waited[0]["seconds"] >= 1
    assert main.gather_service.process_one() is True  # the worker comes to the clip after the booklet went on
    assert state(document)[0][0] == "failed" and left_as_it_came(document, receipt)
    started = time.monotonic()
    assert client.post(f"/v1/documents/{document}/finalize").status_code == 200
    assert time.monotonic() - started < 1, "nothing is left to wait for a second time"


BOOKLET = r'''
import hashlib, io, json, time
from fastapi.testclient import TestClient
from PIL import Image
from app import main

auth = {"Authorization": "Bearer route-key"}
out = {}
with TestClient(main.app) as client:
    doc = client.post("/v1/documents", json={"title": "recorded pages"}, headers=auth).json()["document_id"]
    kinds = ("clip_frame", "clip_frame", "native_still", "clip_frame")
    for index, kind in enumerate(kinds):
        buffer = io.BytesIO()
        Image.new("RGB", (64, 48), (60 + 40 * index,) * 3).save(buffer, "JPEG")
        raw = buffer.getvalue()
        source = {"schema": 1, "source_kind": kind, "capture_id": str(index + 1) * 8 + "-1111-4111-8111-111111111111",
                  "local_session_id": "22222222-2222-4222-8222-222222222222", "jpeg_sha256": hashlib.sha256(raw).hexdigest(),
                  "width": 64, "height": 48, "page_index": index, "rotation_degrees": 270, "image_timestamp_ns": 100,
                  "result_timestamp_ns": 100, "frame_number": 3, "exposure_ns": 30000000, "sensitivity_iso": 800,
                  "af_state": 0, "ae_state": 2}
        page = client.post(f"/v1/documents/{doc}/pages", headers=auth, files={"image": ("page.jpg", raw, "image/jpeg")},
                           data={"page_index": str(index), "image_rotation": "270", "capture_provenance": json.dumps(source)})
        assert page.status_code == 201, page.text
    # Page 1: a clip no decoder can read. Page 2: its clip never came. Page 3: a still. Page 4: its clip was gathered.
    movie = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"not a video" * 2000
    for index in (0, 3):
        clip = client.post(f"/v1/documents/{doc}/pages/{index}/clip", headers=auth,
                           files={"clip": ("page.mp4", movie + bytes([index]), "video/mp4")},
                           data={"capture_id": str(index + 1) * 8 + "-1111-4111-8111-111111111111", "record": "{}",
                                 "sha256": hashlib.sha256(movie + bytes([index])).hexdigest()})
        assert clip.status_code == 201, clip.text
    started = time.monotonic()
    assert client.post(f"/v1/documents/{doc}/finalize", headers=auth).status_code == 200  # waits for the workers
    out["finalize_s"] = time.monotonic() - started
    with main.db.connect() as conn:  # stands for a clip that was gathered: the workers here cannot make one from bytes
        conn.execute("UPDATE page_clips SET status = 'done', reason = NULL WHERE document_id = ? AND page_index = 3", (doc,))
        conn.commit()
    out["clips"] = client.get(f"/v1/documents/{doc}/clips", headers=auth).json()["clips"]
    sid = client.post("/v1/exam-sessions", headers=auth, json={
        "mode": "study", "document_id": doc, "exam_type": "written", "answer_format": "mark"}).json()["session_id"]
    assert client.post(f"/v1/exam-sessions/{sid}/finalize-reading?solve=background", headers=auth).status_code == 200
    deadline = time.time() + 30
    while time.time() < deadline and "bundle" not in out:
        answered = client.get(f"/v1/exam-sessions/{sid}/answer-bundle", headers=auth)
        if answered.status_code == 200 and answered.json()["available_stage"] == "complete":
            out["bundle"] = answered.json()
        time.sleep(0.2)
print("RESULT " + json.dumps(out, ensure_ascii=False))
'''


@pytest.fixture(scope="module")
def booklet(tmp_path_factory):
    """The server half run once with the stand-in solver, as tests/test_recorded_route.py runs it: in a fresh interpreter,
    with the server's own start, workers and finalization. Four pages; what became of each is in the script above."""
    root = tmp_path_factory.mktemp("recorded-booklet")
    reply = root / "reply.json"
    reply.write_text(json.dumps(REPLY, ensure_ascii=False), encoding="utf-8")
    (root / "data").mkdir()
    environment = dict(os.environ, ROKID_DATA_DIR=str(root / "data"), ROKID_API_KEY="route-key", ROKID_REAL_MODE="1",
                       ROKID_ANALYZER="client-ocr", ROKID_SOLVER="recorded", ROKID_SOLVER_FALLBACKS="",
                       ROKID_CHATGPT_SEND_ENABLED="0", ROKID_RECORDED_REPLY=str(reply), ROKID_RECORDED_DELAY_S="0",
                       ROKID_CAPTURE_INSPECTION="0", PYTHONIOENCODING="utf-8")
    done = subprocess.run([sys.executable, "-X", "utf8", "-c", BOOKLET], capture_output=True, text=True, encoding="utf-8",
                          env=environment, cwd=Path(__file__).resolve().parents[1], timeout=180)
    lines = [line for line in done.stdout.splitlines() if line.startswith("RESULT ")]
    assert lines, done.stderr[-2000:]
    result = json.loads(lines[-1][7:])
    assert "bundle" in result, result
    return result


def named(bundle):
    """The items the server added for pages, by page number."""
    return {int(item["question_id"][4:]): item for item in bundle["items"] if item["question_id"].startswith("page")}


def test_a_page_that_was_not_gathered_is_named_in_the_answers(booklet):
    assert [(clip["page_index"], clip["status"]) for clip in booklet["clips"]] == [(0, "failed"), (3, "done")]
    assert booklet["clips"][0]["reason"], "the clip's row says why"
    assert booklet["finalize_s"] < 30, "finalization waited for the workers, not for its limit"
    items = booklet["bundle"]["items"]
    assert [(item["status"], item["answer"][:6]) for item in items[:2]] == [("ready", "経路検査の録"), ("needs_input", "")]
    item = named(booklet["bundle"])[1]
    assert item is items[2], "after the answers, at the end of the bundle"
    assert item["status"] == "needs_review"
    assert item["issue"] == "1頁目は重ねられませんでした（1枚の画像で解析）。必要なら録り直してください"
    assert sorted(named(booklet["bundle"])) == [1, 2], "not the still (page 3), not the gathered page (page 4)"


def test_a_clip_frame_page_whose_clip_never_came_is_named_in_the_answers(booklet):
    assert all(clip["page_index"] != 1 for clip in booklet["clips"]), "no clip of page 2 ever reached the server"
    item = named(booklet["bundle"])[2]
    assert item["status"] == "needs_review"
    assert item["issue"] == "2頁目は重ねられませんでした（1枚の画像で解析）。必要なら録り直してください"


def test_the_glasses_can_read_a_bundle_that_names_pages(booklet):
    # AnswerItem.java (relaycore, study) rejects the whole bundle on one item it cannot hold. Its rule, lines 44 to 51: an
    # item that carries an answer (ready, needs_review) has a non-blank one or a figure; every other item has neither; a
    # needs_review item says why; ids are [A-Za-z0-9_.-]{1,120} and unique; a group's label is the same on all its items.
    items = booklet["bundle"]["items"]
    for item in items:
        carries = item["status"] in ("ready", "needs_review")
        assert bool(item["answer"].strip() or item.get("diagrams")) is carries, item
        assert item["status"] != "needs_review" or item["issue"].strip()
        assert len(item["issue"]) <= 1000 and item["group_label"].strip() and item["question_label"].strip()
        assert re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", item["group_id"]) and re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", item["question_id"])
    assert len({item["question_id"] for item in items}) == len(items)
    assert len({(item["group_id"], item["group_label"]) for item in items}) == len({item["group_id"] for item in items})
