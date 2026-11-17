"""Which clip is gathered next, and what becomes of one that cannot be used or that the server died on.

The phone gathers three clips at a time and each takes a minute or more, so the order decides which pages of the booklet
in hand are still one frame when its capture ends. The clips here are bytes with an MP4 signature: nothing decodes them.
"""
import sqlite3
import uuid
from contextlib import closing

from tests.test_native_capture_upload import create_document, native_image, provenance, upload
from tests.test_page_clips import CAPTURE, MOVIE, RETAKE, page, send
from tests.test_work_bridge import client as _client_fixture

client = _client_fixture


def recorded_page(client, document, index=0, capture=None, movie=MOVIE):
    """One recorded page of a booklet: the frame it arrived as, and its clip waiting to be gathered. A capture belongs
    to one page of one booklet for good, so each page here gets a capture of its own unless one is named."""
    capture = capture or str(uuid.uuid4())
    raw = native_image()
    assert upload(client, document, raw, provenance(raw, source_kind="clip_frame", capture_id=capture, page_index=index),
                  page_index=index).status_code == 201
    assert send(client, document, movie, page_index=index, capture=capture).status_code == 201


def state(document):
    from app import page_clips

    return [(row["status"], row["reason"]) for row in page_clips.rows(document)]


def test_the_booklet_in_hand_is_gathered_before_an_earlier_one(client):
    # An earlier booklet that was left open (abandoned) must not stand between the workers and the booklet being taken.
    from app import page_clips

    earlier, in_hand = create_document(client), create_document(client)
    for document in (earlier, in_hand):
        recorded_page(client, document, 0)
        recorded_page(client, document, 1, movie=MOVIE + b"second page")
    order = [(clip["document_id"], clip["page_index"], clip["status"]) for clip in iter(page_clips.claim, None)]
    assert order == [(in_hand, 0, "gathering"), (in_hand, 1, "gathering"), (earlier, 0, "gathering"), (earlier, 1, "gathering")]


def test_a_clip_whose_booklet_went_on_is_given_up_and_not_gathered(client, monkeypatch):
    from app import page_clips

    monkeypatch.setenv("ROKID_GATHER_WAIT_S", "0")
    gone_on, in_hand = create_document(client), create_document(client)
    recorded_page(client, gone_on, 0)
    recorded_page(client, gone_on, 1, movie=MOVIE + b"second page")
    assert client.post(f"/v1/documents/{gone_on}/finalize").status_code == 200  # went on without its two clips
    recorded_page(client, in_hand)
    claimed = page_clips.claim()
    assert (claimed["document_id"], claimed["page_index"]) == (in_hand, 0)
    # In that same look, not one by one behind the booklet in hand: a finalize call sent again must not wait for them.
    assert state(gone_on) == [("failed", page_clips.STALE)] * 2 and page_clips.pending(gone_on) == 0
    assert page_clips.claim() is None
    assert state(in_hand) == [("gathering", None)]


def test_the_clip_of_a_page_taken_again_is_given_up_and_the_new_clip_is_taken(client):
    from app import page_clips

    document = create_document(client)
    recorded_page(client, document, capture=CAPTURE)
    page(client, document, capture=RETAKE)  # taken again; the clip of the new capture has not come yet
    assert page_clips.claim() is None
    assert state(document) == [("failed", page_clips.STALE)]
    assert send(client, document, MOVIE + b"taken again", capture=RETAKE).status_code == 201
    assert page_clips.claim()["capture_id"] == RETAKE


def test_a_clip_the_server_stopped_on_twice_is_given_up(client):
    # A clip that ends the server while it is gathered (memory, with three gathers running) would otherwise be taken up
    # at every start and end it again, with nobody at the phone.
    from app import page_clips

    document = create_document(client)
    recorded_page(client, document, 0)
    assert page_clips.rows(document)[0]["attempts"] == 0
    assert page_clips.claim()["attempts"] == 1  # the server stopped while this clip was being gathered
    page_clips.requeue_interrupted()
    assert state(document) == [("stored", None)], "once more"
    recorded_page(client, document, 1, movie=MOVIE + b"second page")
    assert [page_clips.claim()["attempts"], page_clips.claim()["attempts"]] == [2, 1]  # and stopped again, on both
    page_clips.requeue_interrupted()
    assert state(document) == [("failed", "interrupted twice"), ("stored", None)]
    assert page_clips.claim()["page_index"] == 1 and page_clips.claim() is None
    assert page_clips.pending(document) == 1


def test_a_database_from_before_the_count_keeps_working(tmp_path, monkeypatch):
    # The phone's database has the table without the count. Nobody is there to alter it by hand.
    from app import db, page_clips

    path = tmp_path / "before.db"
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("CREATE TABLE page_clips (document_id INTEGER, page_index INTEGER, capture_id TEXT, sha256 TEXT, "
                     "bytes INTEGER, record_json TEXT, status TEXT, reason TEXT, used INTEGER, total INTEGER, level REAL, "
                     "created_at REAL, updated_at REAL, PRIMARY KEY (document_id, page_index))")
        conn.execute("INSERT INTO page_clips (document_id, page_index, capture_id, sha256, status) VALUES (7, 0, 'c', 'h', 'gathering')")
    db.init_db(path)
    db.init_db(path)  # every start
    monkeypatch.setattr(db, "DB_PATH", path)
    page_clips.requeue_interrupted()
    with closing(db.connect(path)) as conn:
        assert tuple(conn.execute("SELECT status, reason, attempts FROM page_clips").fetchone()) == ("stored", None, 0)


def test_a_connection_waits_thirty_seconds_for_another_writer(tmp_path):
    # Three gathering workers, the uploads and the finalization write one database; sqlite's own five seconds were not
    # enough on the phone ("database is locked"). The journal mode stays: read-only connections look at the live file.
    from app import db

    with closing(db.connect(tmp_path / "wait.db")) as conn:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30_000
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
