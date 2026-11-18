"""A booklet a wearer recorded is played to a server again from that server's kept data, as the glasses sent it.

scripts/replay_booklet.py reads one document out of a server's data folder (its pages, the frame each arrived as, its
clips, when each arrived) and sends it to a running server in the same order with the same requests, so that what the
server half of a use does with a real booklet is seen before a wearer sees it. Here the source folder is made by hand
with the server's own schema, and the clips are generated scenes written by ffmpeg, as in tests/test_page_gather.py:
no photograph, no page of a paper.
"""
import datetime
import email
import hashlib
import http.server
import importlib
import io
import json
import sqlite3
import sys
import threading
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tests.test_recorded_route import REPLY

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.replay_booklet as replay_booklet  # noqa: E402

T0 = 1794949625.0  # 2026-11-17 21:07:05 UTC, a whole second: a page's arrival is kept to the second
# What the server of another machine wrote as a page's path: the phone's, and a PC's. Neither exists here.
PHONE_IMAGES = "/data/data/com.termux/files/home/rokid-server/data/images"
PC_IMAGES = "C:\\Users\\someone\\rokid\\data\\images"
NOT_A_VIDEO = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"frames no decoder reads" * 500


def sha(content):
    return hashlib.sha256(content).hexdigest()


def stamp(seconds):
    """A time as sqlite's datetime('now') writes it: UTC, whole seconds."""
    return datetime.datetime.fromtimestamp(T0 + seconds, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def picture(kind, size, shade):
    """A grey image with a white patch in its top left corner, so that a turn can be told."""
    out = io.BytesIO()
    image = Image.new("RGB", size, (shade,) * 3)
    image.paste((255, 255, 255), (0, 0, size[0] // 4, size[1] // 4))
    image.save(out, kind)
    return out.getvalue()


def make_source(root, movies, *, images=PHONE_IMAGES):
    """A server's data folder after one use: document 1, one recorded page a movie, each gathered, one session.

    Page k arrived k seconds after the first; its clip 0.4 s (page 1) or 0.5 s (the others) after it.
    """
    from app import db

    data = root / "source"
    (data / "images").mkdir(parents=True)
    db.init_db(data / "docscan.db")
    conn = sqlite3.connect(data / "docscan.db")
    conn.execute("INSERT INTO documents (id, title, capture_device, status, created_at) VALUES (1, 'Rokid scan', "
                 "'rokid-glasses-camera2', 'ready', ?)", (stamp(0),))
    for index, movie in enumerate(movies):
        frame = picture("JPEG", (256, 192), 90 + 40 * index)  # the sensor's view: an upright page lies on its side
        gathered = picture("PNG", (384, 512), 200 - 10 * index)
        capture = f"{index + 1:08d}-1111-4111-8111-111111111111"
        source = {"schema": 1, "source_kind": "clip_frame", "capture_id": capture,
                  "local_session_id": "22222222-2222-4222-8222-222222222222", "jpeg_sha256": sha(frame), "width": 256,
                  "height": 192, "page_index": index, "rotation_degrees": 270, "image_timestamp_ns": 100 + index,
                  "result_timestamp_ns": 100 + index, "frame_number": 3, "exposure_ns": 30_000_000,
                  "sensitivity_iso": 800, "af_state": 0, "ae_state": 0}
        # The frame keeps the name the page first had; the gathered image has another (main.replace_page_image).
        (data / "images" / f"1_{index}_aaaa000{index}.jpg").write_bytes(frame)
        (data / "images" / f"1_{index}_bbbb000{index}.png").write_bytes(gathered)
        clip = data / "page-clips" / "1" / str(index) / f"{sha(movie)}.mp4"
        clip.parent.mkdir(parents=True)
        clip.write_bytes(movie)
        note = {"clip_sha256": sha(movie), "level_over_noise": 30.0, "total": 24, "used": 20}
        separator = "\\" if images == PC_IMAGES else "/"
        conn.execute("INSERT INTO pages (document_id, page_index, image_path, capture_metadata_json, created_at, "
                     "captured_at_ms) VALUES (1, ?, ?, ?, ?, ?)",
                     (index, f"{images}{separator}1_{index}_bbbb000{index}.png", json.dumps(
                         {"capture_provenance": source, "canonical_image_sha256": sha(gathered), "gathered": note}),
                      stamp(index), int((T0 + index - 5) * 1000)))
        arrived = T0 + index + (0.4 if index == 0 else 0.5)
        conn.execute("INSERT INTO page_clips (document_id, page_index, capture_id, sha256, bytes, record_json, status, "
                     "used, total, level, created_at, updated_at, attempts) VALUES (1, ?, ?, ?, ?, ?, 'done', 20, 24, "
                     "30.0, ?, ?, 1)", (index, capture, sha(movie), len(movie),
                                        json.dumps({"schema": 1, "capture_id": capture, "settle": 6}), arrived, arrived + 2.0))
    conn.execute("INSERT INTO exam_sessions (mode, status, document_id, exam_type, answer_format, created_at) VALUES "
                 "('study', 'reviewing', 1, 'written', 'mark', ?)", (stamp(len(movies) + 3),))
    conn.commit()
    conn.close()
    return data


def kept(folder):
    """Every file of a folder with its content's hash: what must be the same after the folder was only read."""
    return {path.relative_to(folder).as_posix(): sha(path.read_bytes()) for path in sorted(folder.rglob("*")) if path.is_file()}


def test_the_source_is_read_and_left_as_it_was(tmp_path):
    for machine, images in (("phone", PHONE_IMAGES), ("pc", PC_IMAGES)):
        data = make_source(tmp_path / machine, [NOT_A_VIDEO, NOT_A_VIDEO + b"2"], images=images)
        before = kept(data)
        booklet = replay_booklet.load_booklet(data, 1)
        assert kept(data) == before, "nothing is written beside the database, and nothing in it"
        assert (booklet["title"], booklet["capture_device"], booklet["exam_type"]) == ("Rokid scan", "rokid-glasses-camera2", "written")
        assert [(page["index"], page["frame"].name, page["kind"]) for page in booklet["pages"]] == [
            (0, "1_0_aaaa0000.jpg", replay_booklet.FIRST_FRAME), (1, "1_1_aaaa0001.jpg", replay_booklet.FIRST_FRAME)]
        assert [page["provenance"]["source_kind"] for page in booklet["pages"]] == ["clip_frame", "clip_frame"]
        assert [(clip["index"], clip["path"].name, clip["bytes"]) for clip in booklet["clips"]] == [
            (0, sha(NOT_A_VIDEO) + ".mp4", len(NOT_A_VIDEO)), (1, sha(NOT_A_VIDEO + b"2") + ".mp4", len(NOT_A_VIDEO) + 1)]
        assert booklet["clips"][0]["source"] == {"status": "done", "used": 20, "total": 24, "gather_s": 2.0}


def test_the_requests_go_out_in_the_order_and_at_the_gaps_they_arrived(tmp_path):
    booklet = replay_booklet.load_booklet(make_source(tmp_path, [NOT_A_VIDEO, NOT_A_VIDEO + b"2", NOT_A_VIDEO + b"3"]), 1)
    # A clip that took long to arrive lands behind the next page, as on the hotspot (page 3 at +2 s, clip 2 at +2.5 s).
    booklet["clips"][1]["arrived"] = T0 + 2.5

    def plan(pace):
        return [(round(at, 1), kind, entry["index"]) for at, kind, entry in replay_booklet.timeline(booklet, pace)]

    assert plan("recorded") == [(0.0, "page", 0), (0.4, "clip", 0), (1.0, "page", 1), (2.0, "page", 2), (2.5, "clip", 1),
                                (2.5, "clip", 2)]
    assert plan("fast") == [(0.0, kind, index) for _, kind, index in plan("recorded")]
    assert plan("7.5") == [(0.0, "page", 0), (0.0, "clip", 0), (7.5, "page", 1), (7.5, "clip", 1), (15.0, "page", 2),
                           (15.0, "clip", 2)]


# The whole replay, in this process: a server of its own with the stand-in solver, reached through its TestClient.

KEY = "replay-test-key"


def movies(tmp_path, count):
    """Clips the server can gather: a generated scene, thirty noisy frames each (tests/test_gather.py)."""
    from tests.test_gather import clip, frames, scene

    return [clip(tmp_path, frames(scene(), [(0, 0)] * 30, 4.0, seed=2 + index), name=f"c{index}.mp4").read_bytes()
            for index in range(count)]


@pytest.fixture
def target(tmp_path, monkeypatch):
    """(a way to send to it, its app.main): a started server with an empty data folder and the stand-in solver."""
    reply = tmp_path / "reply.json"
    reply.write_text(json.dumps(REPLY, ensure_ascii=False), encoding="utf-8")
    for name, value in {"ROKID_DATA_DIR": str(tmp_path / "target"), "ROKID_API_KEY": KEY, "ROKID_SOLVER": "recorded",
                        "ROKID_SOLVER_FALLBACKS": "", "ROKID_CHATGPT_SEND_ENABLED": "0", "ROKID_RECORDED_REPLY": str(reply),
                        "ROKID_RECORDED_DELAY_S": "0", "ROKID_CAPTURE_INSPECTION": "0"}.items():
        monkeypatch.setenv(name, value)
    for name in ("ROKID_REAL_MODE", "ROKID_GATHER_WAIT_S", "ROKID_ANALYZER"):
        monkeypatch.delenv(name, raising=False)
    import app.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)
    import app.main as main
    importlib.reload(main)
    with TestClient(main.app, headers={"Authorization": f"Bearer {KEY}"}) as client:  # started: the gathering runs

        def send(method, path, headers, body, timeout):
            response = client.request(method, path, headers=headers, content=body)
            return response.status_code, response.content

        yield send, main


def stored(main, table, document=1):
    with closing(main.db.connect()) as conn:
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table} WHERE document_id = ? ORDER BY page_index", (document,))]


def test_a_recorded_booklet_is_played_again_and_reported(tmp_path, target, monkeypatch, capsys):
    send, main = target
    data = make_source(tmp_path, movies(tmp_path, 2))
    before = kept(data)
    (tmp_path / "key").write_text(KEY + "\n", encoding="utf-8")
    asked = []
    monkeypatch.setattr(replay_booklet, "http_sender", lambda server, key: asked.append((server, key)) or send)
    code = replay_booklet.main(["--source-data", str(data), "--document", "1", "--server", "http://target:8000",
                                "--key", "@" + str(tmp_path / "key"), "--report", str(tmp_path / "out" / "report.json"),
                                "--timeout", "60"])
    printed = capsys.readouterr().out
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert asked == [("http://target:8000", KEY)], "the key is read from the file, without its line end"
    assert code == 0 and report["exit_code"] == 0, printed
    assert kept(data) == before, "the source is only read"
    assert [(check["name"], check["result"]) for check in report["checks"]] == [(name, "PASS") for name in replay_booklet.CHECKS]
    assert len(replay_booklet.CHECKS) == 4 and all(f"PASS  {name}" in printed for name in replay_booklet.CHECKS)
    assert (report["pace"], report["target"]["solver"], report["target"]["document_id"]) == ("recorded", "recorded", 1)

    # Sent at the gaps they arrived at: page 2 a second after page 1, each clip behind its page.
    assert [(page["page"], page["http"], page["frame"]) for page in report["pages"]] == [
        (1, 201, replay_booklet.FIRST_FRAME), (2, 201, replay_booklet.FIRST_FRAME)]
    assert [page["planned_s"] for page in report["pages"]] == [0.0, 1.0] and report["pages"][1]["sent_s"] >= 1.0
    assert [clip["planned_s"] for clip in report["clips"]] == [0.4, 1.5] and report["clips"][1]["sent_s"] >= 1.5
    for clip in report["clips"]:
        assert (clip["http"], clip["status"], clip["reason"], clip["total"]) == (201, "done", None, 24)
        assert 0 < clip["used"] <= 24 and 0 <= clip["gather_s"] < 30
        assert clip["source"] == {"status": "done", "used": 20, "total": 24, "gather_s": 2.0}
    finalize = report["finalize"]
    assert finalize["http"] == 200 and 0 <= finalize["gather_wait_s"] <= finalize["call_s"] < 30
    assert finalize["limit_s"] == main._GATHER_WAIT_S, "the limit the wait is judged by is the server's own"
    answers = report["answers"]
    assert answers["items"] == {"ready": 1, "needs_input": 1} and answers["pages_left_as_one_frame"] == []
    assert 0 <= answers["first_s"] <= answers["complete_s"] < 60

    # As the glasses sent it: the same captures under the same IDs, the same frames and clips, the booklet gone on.
    source_pages = replay_booklet.load_booklet(data, 1)["pages"]
    for page, row in zip(source_pages, stored(main, "pages"), strict=True):
        metadata = json.loads(row["capture_metadata_json"])
        assert metadata["capture_provenance"] == page["provenance"] and "gathered" in metadata
        assert row["captured_at_ms"] == page["captured_at_ms"]
    assert [(row["sha256"], row["status"]) for row in stored(main, "page_clips")] == [
        (path.stem, "done") for path in sorted((data / "page-clips" / "1").rglob("*.mp4"), key=lambda path: path.parent.name)]
    with closing(main.db.connect()) as conn:
        assert tuple(conn.execute("SELECT title, capture_device, status FROM documents").fetchone()) == (
            "Rokid scan", "rokid-glasses-camera2", "ready")
        assert tuple(conn.execute("SELECT mode, exam_type, answer_format, status FROM exam_sessions").fetchone()) == (
            "study", "written", "mark", "reviewing")
    states = main.list_states()
    assert len(states) == 1 and (states[0]["phase"], states[0]["session_id"]) == ("closed", report["target"]["session_id"])

    # Counts, times, statuses and codes only: nothing an answer says.
    everything = printed + json.dumps(report, ensure_ascii=False)
    for item in REPLY["questions"]:
        assert all(text not in everything for text in (item["answer"], item["missing_material"], item["group"]) if text)


def results(report):
    return [check["result"] for check in report["checks"]]


def test_a_clip_that_is_gone_from_the_source_fails_the_first_check(tmp_path, target, capsys):
    send, _ = target
    data = make_source(tmp_path, movies(tmp_path, 2))
    next((data / "page-clips" / "1" / "1").iterdir()).unlink()  # kept three days, then removed (app/retention.py)
    report = replay_booklet.replay(replay_booklet.load_booklet(data, 1), replay_booklet.Server(send), pace="fast", timeout=60)
    printed = capsys.readouterr().out
    assert report["exit_code"] == 1
    assert results(report) == ["FAIL", "PASS", "PASS", "FAIL"], report["checks"]
    assert "page 2" in report["checks"][0]["detail"] and "page 1" not in report["checks"][0]["detail"]
    assert f"FAIL  {replay_booklet.CHECKS[0]}" in printed and "exit 1" in printed
    assert report["source"] == {"pages": 2, "clips": 2, "clip_files": 1, "arrivals_span_s": 1.5,
                                "session_made_after_last_arrival_s": 3.5}
    first, second = report["clips"]
    assert (first["http"], first["status"]) == (201, "done")
    assert (second["page"], second["http"], second["status"]) == (2, None, replay_booklet.NOT_SENT)
    assert [page["http"] for page in report["pages"]] == [201, 201], "the page itself is sent: it exists whatever its clip does"
    assert report["answers"]["pages_left_as_one_frame"] == [2], "and the server's answers name it"
    assert report["answers"]["items"] == {"ready": 1, "needs_input": 1, "needs_review": 1}


def test_a_gathering_that_does_not_finish_in_the_wait_fails(tmp_path, target, monkeypatch):
    send, main = target
    monkeypatch.setenv("ROKID_GATHER_WAIT_S", "0.3")
    gather, released = main.gather_service._gather, threading.Event()
    # A phone that does not get to the clips in time: every worker stands still until the replay is over.
    monkeypatch.setattr(main.gather_service, "_gather", lambda clip: released.wait(120) and gather(clip))
    data = make_source(tmp_path, movies(tmp_path, 2))
    try:
        report = replay_booklet.replay(replay_booklet.load_booklet(data, 1), replay_booklet.Server(send), pace="fast",
                                       timeout=60, gather_limit=0.3)
    finally:
        released.set()
    assert report["exit_code"] == 1
    assert results(report) == ["FAIL", "FAIL", "PASS", "FAIL"], report["checks"]
    finalize = report["finalize"]
    assert (finalize["http"], finalize["clips_waited_for"], finalize["clips_left"], finalize["limit_s"]) == (200, 2, 2, 0.3)
    assert finalize["gather_wait_s"] >= 0.3, "the server went on at its limit"
    assert all(clip["status"] in ("stored", "gathering") and clip["gather_s"] is None for clip in report["clips"])
    assert report["answers"]["pages_left_as_one_frame"] == [1, 2], "the booklet was answered from single frames, and says so"


def test_a_page_whose_frame_is_gone_is_sent_as_a_stand_in_and_the_report_says_so(tmp_path, target, capsys):
    send, main = target
    data = make_source(tmp_path, movies(tmp_path, 2))
    (data / "images" / "1_1_aaaa0001.jpg").unlink()
    booklet = replay_booklet.load_booklet(data, 1)
    report = replay_booklet.replay(booklet, replay_booklet.Server(send), pace="fast", timeout=60)
    printed = capsys.readouterr().out
    assert report["exit_code"] == 0, report["checks"]
    assert [page["frame"] for page in report["pages"]] == [replay_booklet.FIRST_FRAME, replay_booklet.STAND_IN_FRAME]
    assert replay_booklet.STAND_IN_FRAME.startswith("stand-in: ") and replay_booklet.STAND_IN_FRAME in printed
    # The capture is the recorded one in everything but the bytes that stand for its frame.
    recorded = booklet["pages"][1]["provenance"]
    taken = json.loads(stored(main, "pages")[1]["capture_metadata_json"])["capture_provenance"]
    assert taken["jpeg_sha256"] != recorded["jpeg_sha256"] and {**taken, "jpeg_sha256": recorded["jpeg_sha256"]} == recorded
    # It is the stored page turned back to how the sensor saw it: the frame's size, the page's top left at its top right.
    with Image.open(next(main.IMAGE_DIR.glob("1_1_*.jpg"))) as sent:
        assert (sent.format, sent.size) == ("JPEG", (256, 192))
        assert min(sent.getpixel((250, 5))) > 240 and max(sent.getpixel((5, 5))) < 240 and max(sent.getpixel((250, 186))) < 240


def test_a_page_without_a_capture_record_goes_out_as_its_stored_image(tmp_path, target):
    """A booklet sent from a PC (scripts/run_exam_deck.py) lies in the same database: stored images and nothing else."""
    send, main = target
    data = make_source(tmp_path, [NOT_A_VIDEO])
    with closing(sqlite3.connect(data / "docscan.db")) as conn, conn:
        conn.execute("UPDATE pages SET capture_metadata_json = NULL")
        conn.execute("DELETE FROM page_clips")
    report = replay_booklet.replay(replay_booklet.load_booklet(data, 1), replay_booklet.Server(send), pace="fast", timeout=60)
    assert report["exit_code"] == 0 and results(report) == ["PASS"] * 4, report["checks"]
    assert report["clips"] == [] and [page["frame"] for page in report["pages"]] == [replay_booklet.STAND_IN_IMAGE]
    (row,) = stored(main, "pages")
    assert row["capture_metadata_json"] is None
    with Image.open(row["image_path"]) as taken:
        assert taken.size == (384, 512), "upright as it was stored: not turned a second time"


def test_a_target_that_holds_the_booklet_already_takes_it_again_only_under_new_capture_ids(tmp_path, target):
    send, main = target
    booklet = replay_booklet.load_booklet(make_source(tmp_path, movies(tmp_path, 1)), 1)
    server = replay_booklet.Server(send)
    assert replay_booklet.replay(booklet, server, pace="fast", timeout=60)["exit_code"] == 0
    # To the server a capture is its ID, and this one belongs to the first replay's page.
    again = replay_booklet.replay(booklet, server, pace="fast", timeout=60)
    assert again["exit_code"] == 1 and results(again) == ["FAIL"] * 4
    assert again["stopped_at"] == {"step": "page 1", "http": 409, "detail": "native capture identity is already bound differently"}
    assert any("--new-capture-ids" in note for note in again["notes"])
    renamed = replay_booklet.replay(booklet, server, pace="fast", timeout=60, new_capture_ids=True)
    assert renamed["exit_code"] == 0, renamed["checks"]
    recorded = booklet["pages"][0]["provenance"]
    (page,), (clip,) = stored(main, "pages", renamed["target"]["document_id"]), stored(main, "page_clips", renamed["target"]["document_id"])
    taken = json.loads(page["capture_metadata_json"])["capture_provenance"]
    assert taken["capture_id"] != recorded["capture_id"] and {**taken, "capture_id": recorded["capture_id"]} == recorded
    assert clip["capture_id"] == taken["capture_id"] and json.loads(clip["record_json"])["capture_id"] == taken["capture_id"]
    assert clip["sha256"] == booklet["clips"][0]["sha256"], "the clip itself is the recorded one"


def test_a_target_with_another_solver_is_refused_and_a_failed_booklet_is_reported_with_the_servers_code(tmp_path, target):
    send, main = target
    booklet = replay_booklet.load_booklet(make_source(tmp_path, movies(tmp_path, 1)), 1)
    server = replay_booklet.Server(send)
    (tmp_path / "reply.json").unlink()  # the stand-in is not armed any more: whoever answers now, it is not it
    with pytest.raises(replay_booklet.Refused):
        replay_booklet.replay(booklet, server, pace="fast", timeout=60)
    with closing(main.db.connect()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0, "refused before anything was sent"
    report = replay_booklet.replay(booklet, server, pace="fast", timeout=60, real_solver=True, target_data=tmp_path / "target")
    assert report["exit_code"] == 1 and results(report) == ["PASS", "PASS", "FAIL", "PASS"], report["checks"]
    assert report["answers"]["items"] == {"failed": 1} and report["answers"]["failure_codes"] == {"solver_failed": 1}
    assert "solver_failed" in report["checks"][2]["detail"]
    # With the target's own data at hand a clip's seconds are its row's, not what asking twice a second saw.
    (row,) = stored(main, "page_clips")
    assert report["clips"][0]["gather_s"] == round(row["updated_at"] - row["created_at"], 1)


def test_the_sender_speaks_http_with_the_standard_library_and_never_holds_a_clip_whole(tmp_path):
    """The tests above reach the app through its own client. On the phone there is the standard library and a socket."""
    seen = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen.update(path=self.path, key=self.headers["Authorization"], kind=self.headers["Content-Type"],
                        body=self.rfile.read(int(self.headers["Content-Length"])))
            refused = self.path == "/v1/refused"
            answer = json.dumps({"detail": "no"} if refused else {"taken": True}).encode()
            self.send_response(409 if refused else 201)
            self.send_header("Content-Length", str(len(answer)))
            self.end_headers()
            self.wfile.write(answer)

        def log_message(self, *args):
            pass

    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\x00" * (3 << 20) + b"the end")  # three reads of a megabyte and a rest
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler) as listening:
        threading.Thread(target=listening.serve_forever, daemon=True).start()
        server = replay_booklet.Server(replay_booklet.http_sender(f"http://127.0.0.1:{listening.server_port}/", "the-key"))
        headers, body = replay_booklet.multipart([("sha256", "abc"), ("clip", "page-1.mp4", "video/mp4", clip)])
        assert max(len(block) for block in body) == 1 << 20 and int(headers["Content-Length"]) > clip.stat().st_size
        assert server.call("POST", "/v1/taken", parts=[("sha256", "abc"), ("clip", "page-1.mp4", "video/mp4", clip)]) == (
            201, {"taken": True})
        assert (seen["path"], seen["key"]) == ("/v1/taken", "Bearer the-key")
        message = email.message_from_bytes(b"Content-Type: " + seen["kind"].encode() + b"\r\n\r\n" + seen["body"])
        assert {part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
                for part in message.get_payload()} == {"sha256": b"abc", "clip": clip.read_bytes()}
        assert server.call("POST", "/v1/refused") == (409, {"detail": "no"}), "a refusal is an answer, not an exception"
        listening.shutdown()
    assert server.call("GET", "/v1/taken") == (0, {"detail": "URLError"}), "nobody listens: no status, the error's type"


def test_a_wait_within_a_quarter_of_the_limit_fails_although_the_clips_were_gathered():
    """2026-11-18: the last clip was gathered 165 s after the end and the limit was 150 s. The day before, the wait had
    been noted as near its limit and left."""
    def second_check(waited):
        report = {"clips": [], "stopped_at": None, "answers": None,
                  "finalize": {"http": 200, "gather_wait_s": waited, "limit_s": 200.0}}
        return replay_booklet._judge(report)[1]["result"]

    assert [second_check(waited) for waited in (0.0, 149.9, 150.1, 165.0, 200.5)] == ["PASS", "PASS", "FAIL", "FAIL", "FAIL"]
