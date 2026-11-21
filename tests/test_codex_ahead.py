"""What the Codex route prepares of a booklet before it is asked for the answers.

Until 2026-11-19 the first request about a booklet (where its pages lie) left only after the last clip had been
gathered, the booklet finalized and the glasses had asked for the answers. In the phone's records of 2026-11-18 that
is 32 to 76 s in which nine to eleven of twelve pages had their final image and nothing was done with them, and then
20 to 54 s of locating and 14 to 24 s of cutting with the wearer waiting. The solver now takes pages as they become
final (``prepare``): it locates them, cuts them and keeps the files; answering uses what is there and does for itself
only what is not. Nothing here changes what is sent: a booklet answered from prepared pages makes the same request.

A stand-in CLI as in tests/test_codex_cli_solver.py.
"""
from __future__ import annotations

import concurrent.futures
import json
import time

import pytest
from PIL import Image

from app.solvers import codex_cli
from app.solvers.chatgpt_web import ChatGptWebRateLimit
from tests.test_codex_cli_solver import (_AT_LIMIT, _SIX_REGIONS, _attached, _booklet, _events, _locates, _outlines,
                                         _own_sizes, _runs, _tiles, _too_long_for_one)
from tests.test_codex_cli_solver import codex as _codex_fixture

codex = _codex_fixture


def _settled(timeout: float = 30.0) -> None:
    """Wait for whatever is being prepared; what has not begun is taken back."""
    until = time.monotonic() + timeout
    with codex_cli._ahead_lock:
        waiting = [future for future, _ in (*codex_cli._ahead.values(), *codex_cli._ahead_outlines.values())]
    for future in waiting:
        if not future.running() and not future.done():
            time.sleep(0.2)  # a thread just started has not taken it up yet
        if future.cancel():
            continue
        future.result(timeout=max(0.1, until - time.monotonic()))


@pytest.fixture(autouse=True)
def _nothing_prepared():
    yield
    _settled()
    with codex_cli._ahead_lock:
        codex_cli._ahead.clear()
        codex_cli._ahead_outlines.clear()


def _answered_plainly(codex, tmp_path, monkeypatch, pages=3):
    """A booklet answered with nothing prepared: (the booklet, its answer requests, the calls made so far)."""
    monkeypatch.setenv("FAKE_CODEX_REGIONS", json.dumps(_SIX_REGIONS))
    question = _booklet(tmp_path, pages=pages)
    codex_cli.CodexCliSolver().answer_all(question=question)
    calls = codex()
    codex_cli.CodexCliSolver._kept(question).unlink()
    return question, _runs(calls), len(calls)


def _same(run, plain) -> bool:
    return (run["sizes"] == plain["sizes"] and _attached(run) == _attached(plain)
            and run["args"][-1] == plain["args"][-1])


def test_pages_prepared_ahead_are_neither_located_nor_cut_again_and_the_request_is_the_same(
        codex, tmp_path, monkeypatch, capsys):
    question, [plain], before = _answered_plainly(codex, tmp_path, monkeypatch)
    solver = codex_cli.CodexCliSolver()
    capsys.readouterr()
    solver.prepare(question.document_pages)
    _settled()

    [located] = _locates(codex()[before:])
    assert list(located["sizes"]) == ["photo001.jpg", "photo002.jpg", "photo003.jpg"]
    assert not _runs(codex()[before:]) and not _outlines(codex()[before:]), "nothing but where the pages lie is asked"
    [ahead] = _events(capsys.readouterr().out, "codex_ahead")
    assert (ahead["pages"], ahead["located"]) == (3, 3) and ahead["seconds"] >= 0

    def cut_again(*args, **kwargs):
        raise AssertionError("a page prepared ahead was cut again")

    monkeypatch.setattr(codex_cli, "page_tiles", cut_again)
    solver.answer_all(question=question)
    calls = codex()[before:]
    assert len(_locates(calls)) == 1, "the pages were located once, ahead"
    [run] = _runs(calls)
    assert _same(run, plain), "the request for the answers is the one a booklet not prepared makes"
    [prepared] = _events(capsys.readouterr().out, "codex_prepared")
    assert (prepared["pages"], prepared["ahead"]) == (3, 3) and prepared["seconds"] >= 0, "what the wait was, on record"


def test_only_the_pages_not_prepared_are_located_when_the_booklet_is_answered(codex, tmp_path, monkeypatch):
    question, [plain], before = _answered_plainly(codex, tmp_path, monkeypatch)
    solver = codex_cli.CodexCliSolver()
    solver.prepare(question.document_pages[:2])
    _settled()
    solver.answer_all(question=question)

    ahead, with_the_booklet = _locates(codex()[before:])
    assert list(ahead["sizes"]) == ["photo001.jpg", "photo002.jpg"]
    assert list(with_the_booklet["sizes"]) == ["photo001.jpg"], "the third page alone"
    [run] = _runs(codex()[before:])
    assert _same(run, plain)


def test_pages_that_arrive_one_at_a_time_are_each_prepared_once(codex, tmp_path, monkeypatch):
    question, [plain], before = _answered_plainly(codex, tmp_path, monkeypatch)
    solver = codex_cli.CodexCliSolver()
    for count in (1, 2, 2, 3):  # the pages final so far, as the server names them each time
        solver.prepare(question.document_pages[:count])
        _settled()
    assert [list(call["sizes"]) for call in _locates(codex()[before:])] == [["photo001.jpg"]] * 3

    solver.answer_all(question=question)
    assert len(_locates(codex()[before:])) == 3
    [run] = _runs(codex()[before:])
    assert _same(run, plain)


def test_a_page_whose_image_was_replaced_after_it_was_prepared_is_located_again(codex, tmp_path, monkeypatch):
    """A clip gathered late puts a new file in the page's place; what was prepared was of the frame it arrived as."""
    question, _, before = _answered_plainly(codex, tmp_path, monkeypatch)
    solver = codex_cli.CodexCliSolver()
    solver.prepare(question.document_pages)
    _settled()
    gathered = tmp_path / "page-2-gathered.png"
    Image.new("RGB", (300, 420), (120, 120, 120)).save(gathered)
    question.document_pages[1]["image_path"] = str(gathered)
    solver.answer_all(question=question)

    assert [len(call["sizes"]) for call in _locates(codex()[before:])] == [3, 1]
    [run] = _runs(codex()[before:])
    assert {name[:7] for name in run["sizes"] if name.startswith("page")} == {"page001", "page002", "page003"}


def test_a_page_is_known_by_its_file_and_the_hash_the_server_gives_with_it(tmp_path):
    path = tmp_path / "page.png"
    Image.new("RGB", (30, 40), (9, 9, 9)).save(path)
    hashed = {"page_number": 1, "image_path": str(path), "image_sha256": "a" * 64}
    assert codex_cli._page_key(hashed) == codex_cli._page_key(dict(hashed))
    assert codex_cli._page_key(hashed) != codex_cli._page_key({**hashed, "image_sha256": "b" * 64})
    bare = {"page_number": 1, "image_path": str(path)}
    before = codex_cli._page_key(bare)
    assert before == codex_cli._page_key(bare)
    Image.new("RGB", (300, 400), (9, 9, 9)).save(path)
    assert codex_cli._page_key(bare) != before, "without a hash, the file's size and time"


def test_a_preparation_that_fails_costs_nothing_but_itself(codex, tmp_path, monkeypatch, capsys):
    """Even at a usage limit: the booklet's own request meets it and says so, as it did before."""
    question, [plain], before = _answered_plainly(codex, tmp_path, monkeypatch)
    solver = codex_cli.CodexCliSolver()
    monkeypatch.setenv("FAKE_CODEX_LOCATE_FAIL", _AT_LIMIT)
    capsys.readouterr()
    solver.prepare(question.document_pages)
    _settled()
    [ahead] = _events(capsys.readouterr().out, "codex_ahead")
    assert (ahead["pages"], ahead["located"]) == (3, 0)
    with pytest.raises(ChatGptWebRateLimit):
        solver.answer_all(question=question)

    monkeypatch.delenv("FAKE_CODEX_LOCATE_FAIL")
    solver.answer_all(question=question)
    calls = codex()[before:]
    assert len(_locates(calls)) == 3, "ahead, at the limit, and with the booklet"
    [run] = _runs(calls)
    assert _same(run, plain)


@pytest.mark.parametrize("name, value", [("ROKID_CODEX_AHEAD", "0"), ("ROKID_CHATGPT_SEND_ENABLED", "0"),
                                         ("ROKID_CODEX_LOCATE", "0")])
def test_nothing_is_prepared_where_it_is_switched_off_or_nothing_may_be_sent(codex, tmp_path, monkeypatch, name, value):
    question = _booklet(tmp_path, pages=4)
    monkeypatch.setenv(name, value)
    codex_cli.CodexCliSolver().prepare(question.document_pages)
    _settled()
    assert not [call for call in codex() if call["args"][:1] == ["exec"]]


def test_the_major_problems_are_asked_for_ahead_once_the_whole_booklet_is_in_hand(codex, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_REGIONS", json.dumps(_SIX_REGIONS))
    monkeypatch.setenv("ROKID_CODEX_PARTS", "3")
    monkeypatch.setenv("FAKE_CODEX_OUTLINE", json.dumps({"starts": [1, 3]}))
    question = _booklet(tmp_path, pages=4)
    solver = codex_cli.CodexCliSolver()
    solver.answer_all(question=question)
    plain = codex()
    assert (len(_outlines(plain)), len(_locates(plain)), len(_runs(plain))) == (1, 1, 2)
    solver._kept(question).unlink()

    solver.prepare(question.document_pages[:3])  # as the pages come: the booklet is not whole yet
    _settled()
    assert not _outlines(codex()[len(plain):])
    solver.prepare(question.document_pages, booklet=True)
    solver.prepare(question.document_pages, booklet=True)  # named twice, asked once
    _settled()
    [outline] = _outlines(codex()[len(plain):])
    assert outline["sizes"] == _outlines(plain)[0]["sizes"], "the same small views, those of the prepared pages reused"
    assert [len(call["sizes"]) for call in _locates(codex()[len(plain):])] == [3, 1]

    asked = len(codex())
    solver.answer_all(question=question)
    after = codex()[asked:]
    assert not _outlines(after) and not _locates(after)

    def requests(calls):
        return sorted((call["reply_file"], sorted(call["sizes"].items()), call["args"][-1]) for call in _runs(calls))

    assert requests(after) == requests(plain), "the same two parts, with the same images"


def test_no_outline_is_asked_for_ahead_where_answering_would_ask_for_none(codex, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_REGIONS", json.dumps(_SIX_REGIONS))
    four = _booklet(tmp_path, pages=4)  # no parts set, and one request holds it
    codex_cli.CodexCliSolver().prepare(four.document_pages, booklet=True)
    _settled()
    monkeypatch.setenv("ROKID_CODEX_PARTS", "3")
    (tmp_path / "three").mkdir()
    three = _booklet(tmp_path / "three", pages=3)  # too few captures to part
    codex_cli.CodexCliSolver().prepare(three.document_pages, booklet=True)
    _settled()
    assert not _outlines(codex()) and len(_locates(codex())) == 2


def test_an_outline_asked_ahead_that_told_nothing_is_asked_for_again_with_the_booklet(codex, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_REGIONS", json.dumps(_SIX_REGIONS))
    monkeypatch.setenv("ROKID_CODEX_PARTS", "3")
    monkeypatch.setenv("FAKE_CODEX_OUTLINE_FAIL", "error: stream disconnected before completion")
    question = _booklet(tmp_path, pages=4)
    solver = codex_cli.CodexCliSolver()
    solver.prepare(question.document_pages, booklet=True)
    _settled()
    monkeypatch.delenv("FAKE_CODEX_OUTLINE_FAIL")
    monkeypatch.setenv("FAKE_CODEX_OUTLINE", json.dumps({"starts": [1, 3]}))
    solver.answer_all(question=question)

    assert len(_outlines(codex())) == 2
    assert sorted(call["reply_file"] for call in _runs(codex())) == ["reply-1-1.json", "reply-1-2.json"]


def test_a_booklet_asked_for_while_its_pages_are_being_prepared_waits_for_them(codex, tmp_path, monkeypatch):
    question, [plain], before = _answered_plainly(codex, tmp_path, monkeypatch)
    solver = codex_cli.CodexCliSolver()
    monkeypatch.setenv("FAKE_CODEX_LOCATE_SLEEP", "1.5")
    solver.prepare(question.document_pages)
    until = time.monotonic() + 10
    while time.monotonic() < until and not all(future.running() for future, _ in codex_cli._ahead.values()):
        time.sleep(0.02)
    solver.answer_all(question=question)

    assert len(_locates(codex()[before:])) == 1
    [run] = _runs(codex()[before:])
    assert _same(run, plain)


def test_a_page_whose_preparation_has_not_begun_is_located_with_the_booklet(codex, tmp_path, monkeypatch):
    question, [plain], before = _answered_plainly(codex, tmp_path, monkeypatch)
    waiting = concurrent.futures.Future()
    with codex_cli._ahead_lock:
        codex_cli._ahead[codex_cli._page_key(question.document_pages[0])] = (waiting, time.time())
    codex_cli.CodexCliSolver().answer_all(question=question)

    assert waiting.cancelled(), "it does not begin behind the booklet's own request"
    [located] = _locates(codex()[before:])
    assert len(located["sizes"]) == 3
    [run] = _runs(codex()[before:])
    assert _same(run, plain)


def test_a_long_booklet_prepared_ahead_is_read_in_parts_from_what_was_prepared_and_cut_smaller_for_the_whole_read(
        codex, tmp_path, monkeypatch):
    question, own, before = _own_sizes(codex, tmp_path, monkeypatch)
    _too_long_for_one(monkeypatch, starts=[1, 4])
    solver = codex_cli.CodexCliSolver()
    solver.prepare(question.document_pages, booklet=True)
    _settled()
    assert (len(_locates(codex()[before:])), len(_outlines(codex()[before:]))) == (1, 1)

    asked = len(codex())
    solver.answer_all(question=question)
    after = codex()[asked:]
    assert not _locates(after) and not _outlines(after)
    runs = {call["reply_file"]: call for call in _runs(after)}
    assert sorted(runs) == ["reply-1-1.json", "reply-1-2.json", "reply-2.json"]
    for name, pages in (("reply-1-1.json", {1, 2, 3, 4}), ("reply-1-2.json", {4, 5, 6})):
        assert {int(image[4:7]) for image, _ in _tiles(runs[name])} == pages
        assert all(size == own[image] for image, size in runs[name]["sizes"].items()), "every image at its own size"
    whole = _tiles(runs["reply-2.json"])
    assert {int(image[4:7]) for image, _ in whole} == {1, 2, 3, 4, 5, 6}
    assert all(max(size) <= 300 < max(own[image]) for image, size in whole), "the whole booklet at the size that fits"


@pytest.mark.parametrize("gone", ["a strip", "the view", "everything"])
def test_a_prepared_page_whose_files_have_gone_is_cut_when_the_booklet_is_answered(codex, tmp_path, monkeypatch, gone):
    """What was prepared is removed after its time, and a booklet may be answered again later than that. Whatever
    is missing then, the booklet's own request is made as if the page had not been prepared: as an OSError the
    missing file would hand the booklet to the routes behind this one."""
    question, [plain], before = _answered_plainly(codex, tmp_path, monkeypatch)
    solver = codex_cli.CodexCliSolver()
    solver.prepare(question.document_pages)
    _settled()
    [folder] = list((tmp_path / "data" / "codex-ahead").iterdir())
    if gone == "everything":
        for path in folder.iterdir():
            path.unlink()
    else:
        (folder / ("page002-1a.jpg" if gone == "a strip" else "overview002.jpg")).unlink()
    solver.answer_all(question=question)

    assert len(_locates(codex()[before:])) == 1, "where the pages lie is still known"
    [run] = _runs(codex()[before:])
    assert _same(run, plain)


def test_what_was_prepared_is_removed_after_its_time(codex, tmp_path, monkeypatch):
    question, _, _ = _answered_plainly(codex, tmp_path, monkeypatch)
    solver = codex_cli.CodexCliSolver()
    solver.prepare(question.document_pages[:1])
    _settled()
    root = tmp_path / "data" / "codex-ahead"
    [folder] = list(root.iterdir())
    assert sorted(path.name for path in folder.glob("*.jpg"))[0] == "overview001.jpg"

    monkeypatch.setattr(codex_cli, "_AHEAD_KEPT_S", 0.0)
    time.sleep(0.05)
    solver.prepare(question.document_pages[1:2])
    _settled()
    assert not folder.exists() and len(list(root.iterdir())) == 1
    with codex_cli._ahead_lock:
        assert codex_cli._page_key(question.document_pages[0]) not in codex_cli._ahead
