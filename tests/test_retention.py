"""What the phone keeps and will not read again is removed: the clip of a gathered page once its booklet went on, a
failed clip after a week, an upload cut off before its end after an hour. Nothing else, and nothing outside the clips'
directory. The clips here are bytes with an MP4 signature: nothing decodes them.
"""
import hashlib
import json
import os
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from tests.test_native_capture_upload import create_document
from tests.test_page_clips import MOVIE, kept
from tests.test_page_clips_queue import recorded_page
from tests.test_work_bridge import client as _client_fixture

client = _client_fixture

DAY = 86400.0
COUNTS = {"done_files": 0, "failed_files": 0, "part_files": 0, "bytes": 0, "errors": 0}


def counts(result):
    return {key: result[key] for key in COUNTS}


def everything_else():
    """Every row and every stored file that is not a clip: none of it is the sweep's to remove."""
    from app import config, db

    with closing(db.connect()) as conn:
        rows = [tuple(row) for table in ("documents", "pages") for row in conn.execute(f"SELECT * FROM {table} ORDER BY id")]
        clips = conn.execute("SELECT COUNT(*) FROM page_clips").fetchone()[0]
    return rows, clips, sorted(path for path in config.IMAGE_DIR.rglob("*") if path.is_file())


def settle(document, index, status):
    """Stands for the gathering: the clip is taken up and ends as ``status``."""
    from app import page_clips

    clip = page_clips.claim()
    assert (clip["document_id"], clip["page_index"]) == (document, index)
    if status == "done":
        page_clips.finish(document, index, clip["sha256"], used=5, total=6, level=40.0)
    else:
        page_clips.fail(document, index, clip["sha256"], "too dark")


def sweeps_ended():
    """A finalize starts a sweep on a thread of its own, and that sweep prints its one line whenever it gets there.
    On 2026-11-19 it got there after this test had emptied the captured output (once in four runs of the suite), and
    the test read two lines where it expected its own."""
    for thread in threading.enumerate():
        if thread.name == "retention":
            thread.join(30)


def test_the_clip_of_a_gathered_page_is_kept_three_days_and_then_goes(client, capsys, monkeypatch):
    """Not at once when its booklet goes on: a use is read from its clips afterwards (which frames counted, why a
    page was not placed; the morning of 2026-11-17 was read that way a day later)."""
    from app import page_clips, retention

    document = create_document(client)
    recorded_page(client, document)
    settle(document, 0, "done")
    done_at = time.time()
    assert counts(retention.sweep()) == COUNTS and len(kept()) == 1
    assert client.post(f"/v1/documents/{document}/finalize").status_code == 200
    sweeps_ended()
    assert counts(retention.sweep(now=done_at + 2.9 * DAY)) == COUNTS and len(kept()) == 1, "read after the use"
    monkeypatch.setenv("ROKID_KEEP_DONE_CLIP_DAYS", "30")
    assert counts(retention.sweep(now=done_at + 29 * DAY)) == COUNTS and len(kept()) == 1
    monkeypatch.delenv("ROKID_KEEP_DONE_CLIP_DAYS")
    before = everything_else()
    capsys.readouterr()
    result = retention.sweep(now=1_800_000_000.0)
    assert counts(result) == {**COUNTS, "done_files": 1, "bytes": len(MOVIE)}
    assert kept() == [] and everything_else() == before, "the row, the page and its image stay"
    row = page_clips.rows(document)[0]
    assert (row["status"], row["sha256"], row["bytes"]) == ("done", hashlib.sha256(MOVIE).hexdigest(), len(MOVIE))
    assert row["file_removed_at"] == 1_800_000_000.0, "the row says its file is gone"
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if '"retention"' in line]
    assert lines == [result] and result["event"] == "retention", "one line a sweep"
    assert all(type(value) in (int, float) for key, value in result.items() if key != "event"), "numbers only"
    assert counts(retention.sweep()) == COUNTS, "a second sweep finds nothing left"


def test_the_clip_of_a_gathered_page_goes_after_its_days_in_a_booklet_left_open_too(client):
    """The gathered image has taken the page's place; nothing on the server reads the clip again, whether the
    booklet went on or was left."""
    from app import retention

    document = create_document(client)
    recorded_page(client, document)
    settle(document, 0, "done")
    assert counts(retention.sweep(now=time.time() + 3.1 * DAY)) == {**COUNTS, "done_files": 1, "bytes": len(MOVIE)}
    assert kept() == []


def test_a_failed_clip_is_kept_a_week_and_a_waiting_one_for_good(client, monkeypatch):
    from app import page_clips, retention

    document = create_document(client)
    for index in range(4):
        recorded_page(client, document, index, movie=MOVIE + bytes([index]))
    settle(document, 0, "failed")
    settle(document, 1, "failed")
    assert page_clips.claim()["page_index"] == 2  # being gathered; page 4's clip still waits
    failed_at = time.time()
    assert counts(retention.sweep(now=failed_at + 6.9 * DAY)) == COUNTS and len(kept()) == 4, "evidence until then"
    with closing(page_clips.db.connect()) as conn, conn:  # the second one failed a day later
        conn.execute("UPDATE page_clips SET updated_at = updated_at + ? WHERE page_index = 1", (DAY,))
    assert counts(retention.sweep(now=failed_at + 7.1 * DAY)) == {**COUNTS, "failed_files": 1, "bytes": len(MOVIE) + 1}
    assert [path.parent.name for path in kept()] == ["1", "2", "3"]
    monkeypatch.setenv("ROKID_KEEP_FAILED_CLIP_DAYS", "1.5")
    assert counts(retention.sweep(now=failed_at + 2.4 * DAY)) == COUNTS
    assert counts(retention.sweep(now=failed_at + 2.6 * DAY)) == {**COUNTS, "failed_files": 1, "bytes": len(MOVIE) + 1}
    monkeypatch.setenv("ROKID_KEEP_FAILED_CLIP_DAYS", "a week")  # unreadable: the default
    assert counts(retention.sweep(now=failed_at + 365 * DAY)) == COUNTS
    assert [path.parent.name for path in kept()] == ["2", "3"], "a clip that waits or is being gathered is never removed"
    assert [(row["status"], row["reason"], row["file_removed_at"] is None) for row in page_clips.rows(document)] == [
        ("failed", "too dark", False), ("failed", "too dark", False), ("gathering", None, True), ("stored", None, True)]


def test_an_upload_cut_off_before_its_end_goes_after_an_hour(client):
    from app import config, retention

    document = create_document(client)
    recorded_page(client, document)
    left = kept()[0].with_name("0123456789abcdef0123456789abcdef.part")  # as store_clip names a clip that is arriving
    left.write_bytes(b"half a clip")
    elsewhere = config.IMAGE_DIR / "not-a-clip.part"
    elsewhere.write_bytes(b"not in the clips' directory")
    written = left.stat().st_mtime
    assert counts(retention.sweep(now=written + 3500)) == COUNTS and left.exists(), "it may still be arriving"
    assert counts(retention.sweep(now=written + 3700)) == {**COUNTS, "part_files": 1, "bytes": 11}
    assert not left.exists() and len(kept()) == 1 and elsewhere.exists()


def test_nothing_outside_the_clip_directory_is_touched(client):
    from app import config, db, retention

    create_document(client)
    outside = config.DATA_DIR / "elsewhere" / "kept.mp4"
    outside.parent.mkdir()
    outside.write_bytes(b"not a clip of this server")
    with closing(db.connect()) as conn, conn:  # a row whose names lead out of the directory, whoever wrote it
        conn.execute("INSERT INTO page_clips (document_id, page_index, capture_id, sha256, status, updated_at) "
                     "VALUES (99, 0, 'c', '../../../elsewhere/kept', 'done', 0)")
        conn.execute("INSERT INTO page_clips (document_id, page_index, capture_id, sha256, status, updated_at) "
                     "VALUES ('../../elsewhere', 'kept', 'c', 'kept', 'failed', 0)")
    result = retention.sweep()
    assert counts(result) == {**COUNTS, "errors": 2}
    assert outside.read_bytes() == b"not a clip of this server"
    with closing(db.connect()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM page_clips WHERE file_removed_at IS NOT NULL").fetchone()[0] == 0


def test_a_sweep_never_raises(client, monkeypatch, tmp_path):
    from app import config, db, retention

    assert counts(retention.sweep()) == COUNTS, "a server that never took a clip has no clips' directory"
    assert not (config.DATA_DIR / "page-clips").exists()
    document = create_document(client)
    recorded_page(client, document)
    settle(document, 0, "failed")
    left = kept()[0].with_name("0123456789abcdef0123456789abcdef.part")
    left.write_bytes(b"half a clip")
    os.utime(left, (0, 0))

    def refused(path, *args, **kwargs):
        raise PermissionError("held by a reader")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", refused)
        assert counts(retention.sweep(now=time.time() + 8 * DAY)) == {**COUNTS, "errors": 2}, "what could not go is counted"
    with closing(db.connect()) as conn:  # and is still to go: a row is marked only once its file is gone
        assert conn.execute("SELECT file_removed_at FROM page_clips").fetchone()[0] is None

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    with monkeypatch.context() as patch:
        patch.setattr(db, "connect", locked)
        assert counts(retention.sweep(now=time.time() + 8 * DAY)) == {**COUNTS, "part_files": 1, "bytes": 11, "errors": 1}
    assert counts(retention.sweep(now=time.time() + 8 * DAY)) == {**COUNTS, "failed_files": 1, "bytes": len(MOVIE)}
    assert kept() == []


def test_a_database_from_before_the_mark_keeps_working(tmp_path):
    from app import db

    path = tmp_path / "before.db"
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("CREATE TABLE page_clips (document_id INTEGER, page_index INTEGER, capture_id TEXT, sha256 TEXT, "
                     "bytes INTEGER, record_json TEXT, status TEXT, reason TEXT, used INTEGER, total INTEGER, level REAL, "
                     "created_at REAL, updated_at REAL, PRIMARY KEY (document_id, page_index))")
        conn.execute("INSERT INTO page_clips (document_id, page_index, capture_id, sha256, status) VALUES (7, 0, 'c', 'h', 'done')")
    db.init_db(path)
    db.init_db(path)
    with closing(db.connect(path)) as conn:
        assert tuple(conn.execute("SELECT status, file_removed_at FROM page_clips").fetchone()) == ("done", None)


def test_free_space_is_reported_with_every_sweep(client, monkeypatch, capsys):
    # A full phone answers every upload with 500 and nobody is there to see it: the space left is in each sweep's line.
    from app import config, retention

    assert retention.free_bytes() > 0, "the storage the tests run on"
    asked = []

    def usage(path):
        asked.append(Path(path))
        return SimpleNamespace(total=100, used=60, free=40)

    monkeypatch.setattr(retention.shutil, "disk_usage", usage)
    assert retention.free_bytes() == 40 and asked == [config.DATA_DIR]
    sweeps_ended()  # the one the server's start began
    capsys.readouterr()
    result = retention.sweep()
    assert result["free_bytes"] == 40 and counts(result) == COUNTS
    assert [json.loads(line) for line in capsys.readouterr().out.splitlines() if '"retention"' in line] == [result]

    def unreadable(path):
        raise OSError("no such storage")

    monkeypatch.setattr(retention.shutil, "disk_usage", unreadable)
    result = retention.sweep()
    assert result["free_bytes"] == -1 and counts(result) == {**COUNTS, "errors": 1}, "a sweep never raises"
