"""The server hands the solver each page of a booklet as soon as its image is final (2026-11-19).

The wearer has ended the capture and the booklet waits for its last clips (``_await_gathering``). The pages whose
clips are gathered, or that never had one, do not change any more: they go to the solver's ``prepare`` at once, each
later page when its clip is settled, and the whole booklet when nothing is left to wait for. Nothing is handed over
before the wearer has ended the capture. A solver without ``prepare`` is left alone, and whatever goes wrong here
costs the booklet nothing.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tests.test_gather import frames, scene
from tests.test_native_capture_upload import native_image, provenance, upload
from tests.test_page_gather import client as _client_fixture
from tests.test_page_gather import page_row, recorded, sha

client = _client_fixture
STILL = "33333333-3333-4333-8333-333333333333"


class Ahead:
    accepts_images = True

    def __init__(self, fails=False):
        self.calls, self.fails = [], fails

    def prepare(self, pages, *, booklet=False):
        self.calls.append(([dict(page) for page in pages], booklet))
        if self.fails:
            raise RuntimeError("no memory for this")


@pytest.fixture
def ahead(monkeypatch):
    from app import main

    solver = Ahead()
    real = main.get_solver
    monkeypatch.setenv("ROKID_SOLVER", "codex-cli")
    monkeypatch.setattr(main, "get_solver", lambda prefer=None: solver if prefer == "codex-cli" else real(prefer))
    return solver


def _a_still_beside(client, document):
    raw = native_image()
    response = upload(client, document, raw, provenance(raw, capture_id=STILL, page_index=1), page_index=1)
    assert response.status_code == 201, response.text


def _numbers(call):
    return [page["page_number"] for page in call[0]]


def test_finalize_hands_over_each_page_once_its_image_is_final_and_then_the_booklet(client, tmp_path, ahead):
    from app import main

    document, receipt, _ = recorded(client, tmp_path, frames(scene(), [(0, 0)] * 30, 4.0))
    _a_still_beside(client, document)
    assert ahead.calls == [], "nothing leaves before the wearer has ended the capture"
    with ThreadPoolExecutor(max_workers=1) as pool:  # no worker runs here: the test turns the gathering by hand
        finalizing = pool.submit(client.post, f"/v1/documents/{document}/finalize")
        time.sleep(0.4)
        assert not finalizing.done()
        assert [(_numbers(call), call[1]) for call in ahead.calls] == [([2], False)], "the still: its image is final"
        assert main.gather_service.process_one() is True
        assert finalizing.result(timeout=30).status_code == 200

    assert [(_numbers(call), call[1]) for call in ahead.calls] == [([2], False), ([1, 2], True)]
    last = {page["page_number"]: page for page in ahead.calls[-1][0]}
    for index in (0, 1):
        stored = page_row(document, index)
        assert last[index + 1]["image_path"] == stored["image_path"]
        assert last[index + 1]["image_sha256"] == sha(Path(stored["image_path"]).read_bytes())
    assert page_row(document)["image_path"] != receipt["image_path"], "the gathered page, not the frame it came as"
    assert last[1]["capture_provenance"]["source_kind"] == "clip_frame", "what makes it a recorded page goes along"
    assert last[2]["capture_provenance"]["source_kind"] == "native_still"


def test_a_booklet_with_nothing_to_wait_for_is_handed_over_whole_at_once(client, ahead):
    from tests.test_native_capture_upload import create_document

    document = create_document(client)
    raw = native_image()
    assert upload(client, document, raw, provenance(raw)).status_code == 201
    assert client.post(f"/v1/documents/{document}/finalize").status_code == 200
    assert [(_numbers(call), call[1]) for call in ahead.calls] == [([1], True)]

    assert client.post(f"/v1/documents/{document}/finalize").status_code == 200  # the call sent again
    assert len(ahead.calls) == 1, "a booklet that is already finalized is not handed over again"


def test_a_page_whose_clip_was_not_gathered_in_time_goes_as_the_frame_it_came_as(client, tmp_path, ahead, monkeypatch):
    monkeypatch.setenv("ROKID_GATHER_WAIT_S", "0.6")
    document, receipt, _ = recorded(client, tmp_path)
    assert client.post(f"/v1/documents/{document}/finalize").status_code == 200
    assert [(_numbers(call), call[1]) for call in ahead.calls] == [([1], True)]
    assert ahead.calls[0][0][0]["image_path"] == receipt["image_path"]


def test_trouble_with_the_handing_over_costs_the_booklet_nothing(client, tmp_path, monkeypatch):
    from app import main

    solver = Ahead(fails=True)
    real = main.get_solver
    monkeypatch.setenv("ROKID_SOLVER", "codex-cli")
    monkeypatch.setattr(main, "get_solver", lambda prefer=None: solver if prefer == "codex-cli" else real(prefer))
    document, _, _ = recorded(client, tmp_path, frames(scene(), [(0, 0)] * 30, 4.0))
    assert main.gather_service.process_one() is True
    assert client.post(f"/v1/documents/{document}/finalize").status_code == 200
    assert len(solver.calls) == 1


def test_a_route_that_cannot_be_set_up_costs_the_booklet_nothing(client, tmp_path, monkeypatch):
    from app import main

    real = main.get_solver

    def no_solver(prefer=None):
        if prefer == "codex-cli":
            raise RuntimeError("the route is not set up")
        return real(prefer)

    monkeypatch.setenv("ROKID_SOLVER", "codex-cli")
    monkeypatch.setattr(main, "get_solver", no_solver)
    document, _, _ = recorded(client, tmp_path, frames(scene(), [(0, 0)] * 30, 4.0))
    assert main.gather_service.process_one() is True
    assert client.post(f"/v1/documents/{document}/finalize").status_code == 200
