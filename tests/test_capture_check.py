"""The pages to take again are found by the phone, before anything is asked of the model (2026-11-19).

The operator, after two subjects that day: a page that has to be taken again has to be found before GPT asks for it.
Until then a recorded page that could not be gathered went out as the one frame it arrived as and was named in the
answers, minutes later. Read against what came of every recorded page on record (data/gather-stage2/scripts/
check_rule_1119.py, sessions of 11/17 to 11/19): of the 14 pages whose clip failed or was gathered from fewer than
40 frames, 12 had not been read. Nothing else the phone knows about a page told the read ones from the others, so
nothing else is asked again here; of the 73 pages this lets pass, 31 were not read all the same (a sheet larger than
the frame, print in the frame's blurred edge), which no check after the capture finds.

``POST /v1/documents/{id}/capture-check`` is what the glasses ask when the wearer has ended the capture, before they
ask for the booklet to be finalized: it waits for the clips as the finalize call does and names the pages to take
again, which the glasses then take in place under their own page numbers.
"""
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from tests.test_gather import frames, scene
from tests.test_native_capture_upload import native_image, provenance, upload
from tests.test_page_gather import client as _client_fixture
from tests.test_page_gather import recorded
from tests.test_prepare_ahead import Ahead

client = _client_fixture
STILL = "33333333-3333-4333-8333-333333333333"
BLANK = [np.full((192, 256), 0.5, np.float32)] * 30  # nothing in the view to place one frame on another by


def check(client, document):
    response = client.post(f"/v1/documents/{document}/capture-check")
    assert response.status_code == 200, response.text
    return response.json()


def test_a_page_whose_clip_could_not_be_placed_is_taken_again(client, tmp_path):
    from app import main

    document, _, _ = recorded(client, tmp_path, BLANK)
    assert main.gather_service.process_one() is True
    assert check(client, document) == {"document_id": document, "pages": 1, "retake": [1]}


def test_the_desk_checks_server_can_hold_the_answer_back_as_long_as_gathering_takes_in_use(client, tmp_path, monkeypatch):
    """On a PC the clips are gathered in seconds and the check answered while the glasses were still awake; in the
    use of 2026-11-20 it answered 83 s after the end, the glasses asleep, and their camera was refused. The stand-in
    server (and no other) holds its answer back for as long as it is told, so that the desk check meets that."""
    from app import main

    document, _, _ = recorded(client, tmp_path, BLANK)
    assert main.gather_service.process_one() is True
    monkeypatch.setenv("ROKID_CHECK_HOLD_S", "0.4")
    monkeypatch.setenv("ROKID_SOLVER", "codex-cli")
    began = time.monotonic()
    assert check(client, document)["retake"] == [1]
    assert time.monotonic() - began < 0.3, "the phone's own server never waits for it"
    monkeypatch.setenv("ROKID_SOLVER", "recorded")
    began = time.monotonic()
    assert check(client, document)["retake"] == [1]
    assert time.monotonic() - began >= 0.4


def test_a_page_gathered_from_few_frames_is_taken_again_and_one_from_enough_is_not(client, tmp_path, monkeypatch):
    from app import main, page_clips

    document, _, _ = recorded(client, tmp_path, frames(scene(), [(0, 0)] * 30, 4.0))
    assert main.gather_service.process_one() is True
    used = page_clips.rows(document)[0]["used"]
    assert 0 < used < 40, "24 frames behind the settling ones"
    assert check(client, document)["retake"] == [1], "under the 40 frames of the rule"
    monkeypatch.setenv("ROKID_CHECK_MIN_USED", str(used))
    assert check(client, document)["retake"] == []


def test_a_still_and_a_page_whose_clip_never_came(client, tmp_path, monkeypatch):
    """A still is whole as it is. A recorded page whose clip never reached the phone is the one frame it came as."""
    from app import main

    monkeypatch.setenv("ROKID_CHECK_MIN_USED", "1")
    document, _, _ = recorded(client, tmp_path, frames(scene(), [(0, 0)] * 30, 4.0))
    raw = native_image()
    assert upload(client, document, raw, provenance(raw, capture_id=STILL, page_index=1), page_index=1).status_code == 201
    lost = "44444444-4444-4444-8444-444444444444"
    assert upload(client, document, raw, provenance(raw, capture_id=lost, page_index=2, source_kind="clip_frame"),
                  page_index=2).status_code == 201
    assert main.gather_service.process_one() is True
    assert check(client, document) == {"document_id": document, "pages": 3, "retake": [3]}


def test_the_check_waits_for_the_clips_as_the_finalize_call_does(client, tmp_path):
    from app import main

    document, _, _ = recorded(client, tmp_path, BLANK)
    with ThreadPoolExecutor(max_workers=1) as pool:  # no worker runs here: the test turns the gathering by hand
        asking = pool.submit(check, client, document)
        time.sleep(0.4)
        assert not asking.done(), "the clip is still to be gathered: nothing can be said of its page yet"
        assert main.gather_service.process_one() is True
        assert asking.result(timeout=30)["retake"] == [1]


def test_a_booklet_that_takes_no_more_pages_asks_for_nothing(client, tmp_path):
    from app import main

    document, _, _ = recorded(client, tmp_path, BLANK)
    assert main.gather_service.process_one() is True
    assert client.post(f"/v1/documents/{document}/finalize").status_code == 200
    assert check(client, document)["retake"] == [], "nothing can be taken again any more"
    assert client.post("/v1/documents/999999/capture-check").status_code == 404


@pytest.fixture
def ahead(monkeypatch):
    from app import main

    solver = Ahead()
    real = main.get_solver
    monkeypatch.setenv("ROKID_SOLVER", "codex-cli")
    monkeypatch.setattr(main, "get_solver", lambda prefer=None: solver if prefer == "codex-cli" else real(prefer))
    return solver


def test_the_booklet_is_handed_over_whole_only_when_no_page_is_to_be_taken_again(client, tmp_path, ahead, monkeypatch):
    """The wearer has ended the capture: the pages that are final go to the solver as they do at the finalize call.
    The booklet as a whole (which asks where its major problems begin) only when no page of it is about to change."""
    from app import main

    document, _, _ = recorded(client, tmp_path, frames(scene(), [(0, 0)] * 30, 4.0))
    assert main.gather_service.process_one() is True
    assert check(client, document)["retake"] == [1]
    assert [booklet for _, booklet in ahead.calls] == [False]
    monkeypatch.setenv("ROKID_CHECK_MIN_USED", "1")
    assert check(client, document)["retake"] == []
    assert [booklet for _, booklet in ahead.calls][-1] is True
