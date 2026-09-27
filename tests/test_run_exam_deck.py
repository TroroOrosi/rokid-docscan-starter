"""The deck bench's per-paper isolation, spread rendering, photo input, and
server-route polling.

The bench writes each run into a database directory. It used to write every
paper into ONE --data-dir, so a query issued after a later run read the
previous paper's rows (observed while diagnosing on 2026-09-14).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.run_exam_deck as run_exam_deck  # noqa: E402
from scripts.run_exam_deck import (  # noqa: E402
    deck_data_dir,
    load_images,
    main,
    pair_spreads,
    render_spreads,
    wait_for_answers,
)

ROOT = Path("C:/rokid-exam-materials/rundata")


# -- per-paper isolation (existing) ------------------------------------------

def test_two_papers_never_share_a_database():
    a = deck_data_dir(ROOT, Path("C:/m/kyotsu/sugaku1A.pdf"))
    b = deck_data_dir(ROOT, Path("C:/m/kyotsu/butsuri_kiso.pdf"))
    assert a != b
    assert a.parent == ROOT and b.parent == ROOT


def test_the_same_paper_resolves_to_the_same_database():
    """A re-run of one paper resumes in place instead of starting a new dir."""
    first = deck_data_dir(ROOT, Path("C:/m/kyotsu/sugaku1A.pdf"))
    again = deck_data_dir(ROOT, "C:/elsewhere/sugaku1A.pdf")
    assert first == again


def test_a_japanese_paper_name_is_kept_but_made_path_safe():
    got = deck_data_dir(ROOT, Path('C:/m/todai/国語:文科?.pdf'))
    assert got.name == "国語_文科_"
    assert got.parent == ROOT


def test_a_blank_stem_still_yields_a_directory():
    assert deck_data_dir(ROOT, Path("C:/m/   .pdf")).name == "unnamed"


def test_two_glassdoc_runs_never_share_a_database(tmp_path):
    """Each run keeps its photos in <run>/originals; the run names the database."""
    a, b = tmp_path / "run-a" / "originals", tmp_path / "run-b" / "originals"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    assert deck_data_dir(ROOT, a).name == "run-a-originals"
    assert deck_data_dir(ROOT, a) != deck_data_dir(ROOT, b)


# -- spreads: pairing and PDF rendering ---------------------------------------

def _solid(width, height, color):
    from PIL import Image

    return Image.new("RGB", (width, height), color)


def test_pair_spreads_puts_the_earlier_page_on_the_left():
    red, blue, green = (
        _solid(100, 200, "red"), _solid(140, 200, "blue"), _solid(80, 150, "green"))
    spreads = pair_spreads([red, blue, green])
    assert len(spreads) == 2
    first = spreads[0]
    assert first.size == (240, 200)
    assert first.getpixel((0, 0)) == (255, 0, 0)
    assert first.getpixel((239, 0)) == (0, 0, 255)
    assert spreads[1] is green


def _pdf(path, pages, size=(515.9, 728.5)):
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(*size)
    doc.save(str(path))


def test_render_spreads_pairs_pdf_pages_at_glasses_density(tmp_path):
    import io

    from PIL import Image

    pdf = tmp_path / "paper.pdf"
    _pdf(pdf, 3)
    spreads = render_spreads(pdf, range(0, 10_000))  # clipped to the 3 pages
    assert len(spreads) == 2
    for jpeg, text in spreads:
        assert jpeg[:2] == b"\xff\xd8"
        assert text == ""
    first = Image.open(io.BytesIO(spreads[0][0]))
    second = Image.open(io.BytesIO(spreads[1][0]))
    assert abs(first.size[0] - 1820) <= 2 and abs(first.size[1] - 1285) <= 2
    assert abs(second.size[0] - 910) <= 2 and abs(second.size[1] - 1285) <= 2


# -- glassdoc originals: load_images ------------------------------------------

def test_photos_load_in_name_order_without_text(tmp_path):
    from PIL import Image

    Image.new("RGB", (200, 100), "red").save(tmp_path / "img-2.jpg")
    Image.new("RGB", (200, 100), "blue").save(tmp_path / "img-1.jpg")
    (tmp_path / "notes.txt").write_text("not a page")
    pages = load_images(tmp_path)
    assert [text for _, text in pages] == ["", ""]
    assert pages[0][0][:2] == b"\xff\xd8" and pages[1][0][:2] == b"\xff\xd8"


def test_a_portrait_photo_is_rejected_by_name(tmp_path):
    from PIL import Image

    Image.new("RGB", (100, 200), "red").save(tmp_path / "img-1.jpg")
    with pytest.raises(ValueError, match="img-1.jpg"):
        load_images(tmp_path)


# -- wait_for_answers: scripted fake client + fake clock ----------------------

class _Clock:
    """A monotonic clock driven only by `sleep`, so a test never really waits."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class _Response:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body


def _bundle(*statuses, revision=1):
    return _Response(200, {"revision": revision, "items": [{"status": s} for s in statuses]})


class _Server:
    """answer-bundle as the background batch serves it, one response per poll."""

    def __init__(self, responses):
        self.responses = list(responses)

    def get(self, url):
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_wait_polls_through_a_listing_then_pending_then_ready():
    clock = _Clock()
    server = _Server([
        _Response(409, {"detail": "the question list is being made"}),
        _bundle("pending", "pending", revision=1),
        _bundle("ready", "pending", revision=2),
        _bundle("ready", "ready", revision=3),
    ])
    got, reason = wait_for_answers(server, 1, 60, interval=0, clock=clock, sleep=clock.sleep)
    assert got.status_code == 200 and reason is None and server.responses == []


def test_wait_stops_at_once_on_any_other_conflict():
    clock = _Clock()
    server = _Server([_Response(409, {"detail": "no problems were detected"})])
    got, reason = wait_for_answers(server, 1, 60, interval=0, clock=clock, sleep=clock.sleep)
    assert got.status_code == 409 and reason is None


def test_wait_reports_a_stall_only_after_the_bound_has_passed():
    clock = _Clock()
    # Every poll repeats the same revision; interval=1 lets the fake clock
    # advance, so the stall check can actually cross stall_s.
    server = _Server([_bundle("pending", revision=7) for _ in range(20)])
    got, reason = wait_for_answers(server, 1, 5, interval=1, clock=clock, sleep=clock.sleep)
    assert got.status_code == 200
    assert reason is not None and "unchanged" in reason
    assert clock.now >= 5  # not cut short before the bound passed


def test_wait_follows_a_changing_revision_well_past_the_stall_bound():
    clock = _Clock()
    responses = [_bundle("pending", "pending", revision=n) for n in range(1, 20)]
    responses.append(_bundle("ready", "ready", revision=20))
    server = _Server(responses)
    got, reason = wait_for_answers(server, 1, 2, interval=1, clock=clock, sleep=clock.sleep)
    assert got.status_code == 200 and reason is None
    assert clock.now > 2  # no overall ceiling


def test_a_long_listing_does_not_stop_the_wait():
    clock = _Clock()
    responses = [_Response(409, {"detail": "the question list is being made"}) for _ in range(10)]
    responses.append(_bundle("ready", revision=1))
    server = _Server(responses)
    got, reason = wait_for_answers(server, 1, 2, interval=1, clock=clock, sleep=clock.sleep)
    assert got.status_code == 200 and reason is None
    assert clock.now > 2


def test_a_transport_error_keeps_the_last_good_response_then_gives_up():
    import httpx

    clock = _Clock()
    good = _bundle("pending", revision=1)
    server = _Server([good] + [httpx.ConnectError("refused") for _ in range(10)])
    got, reason = wait_for_answers(server, 1, 5, interval=1, clock=clock, sleep=clock.sleep)
    assert got is good and reason is not None and "no response" in reason


# -- CLI validation ------------------------------------------------------------

def test_images_without_server_exits_2(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        main(["--images", str(tmp_path)])
    assert excinfo.value.code == 2


@pytest.mark.parametrize("flag,value", [
    ("--daimon", "1,7"),
    ("--solver", "local"),
    ("--scale", "3.0"),
    ("--data-dir", "C:/somewhere"),
    ("--audio", "a.mp3"),
])
def test_server_incompatible_flags_exit_2(flag, value):
    with pytest.raises(SystemExit) as excinfo:
        main(["--pdf", "paper.pdf", "--server", "http://phone:8000", flag, value])
    assert excinfo.value.code == 2


# -- plumbing through the real FastAPI app, model replaced --------------------
# No network, no phone, no ChatGPT: ROKID_SOLVER=test-provider and
# main._list_questions/main.solve_with_fallback are monkeypatched (the pattern
# in tests/test_answer_bundle_api.py::test_model_question_list_defines_the_deck);
# run_exam_deck.remote_client returns the in-process TestClient instead of
# reaching an actual host.

@pytest.fixture
def server_app(tmp_path, monkeypatch):
    """The real FastAPI app, in-process, standing in for the phone's server."""
    import importlib

    monkeypatch.setenv("ROKID_DATA_DIR", str(tmp_path / "serverdata"))
    monkeypatch.delenv("ROKID_ALLOW_REAL_EXAM_SOLVE", raising=False)
    import app.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)
    import app.main as main
    importlib.reload(main)
    main.ensure_dirs()
    main.db.init_db()
    from fastapi.testclient import TestClient
    return main, TestClient(main.app)


def test_server_route_uploads_two_spreads_with_no_ocr_text(server_app, tmp_path, monkeypatch):
    """Plumbing check with the model replaced: no network, no phone, no ChatGPT."""
    main, client = server_app
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")
    monkeypatch.setattr(run_exam_deck, "remote_client", lambda server, key: client)
    monkeypatch.setattr(run_exam_deck, "POLL_S", 0)

    received = []

    def list_questions(question):
        received.append(question.document_pages)
        return [{"group": "第1問", "label": "問1", "pages": [1]},
                {"group": "第1問", "label": "問2", "pages": [2]}]

    class _Solver:
        name = "test-provider"

    def solve(*, question, **_kw):
        from app.solvers.base import SolveResult

        return SolveResult(answer="x"), _Solver()

    monkeypatch.setattr(main, "_list_questions", list_questions)
    monkeypatch.setattr(main, "solve_with_fallback", solve)

    pdf = tmp_path / "butsuri.pdf"
    _pdf(pdf, 4)
    out = tmp_path / "reports" / "butsuri-server.json"

    code = run_exam_deck.main(
        ["--pdf", str(pdf), "--server", "http://phone.example:8000", "--out", str(out)])

    assert code == 0
    assert len(received) == 1 and len(received[0]) == 2
    assert all(page["ocr_text"] == "" for page in received[0])
    assert out.exists()


def test_server_route_stops_before_polling_when_the_phone_solver_is_local(
        server_app, tmp_path, monkeypatch, capsys):
    main, client = server_app
    monkeypatch.setenv("ROKID_SOLVER", "local")
    monkeypatch.setattr(run_exam_deck, "remote_client", lambda server, key: client)
    monkeypatch.setattr(run_exam_deck, "POLL_S", 0)

    def must_not_poll(*_a, **_k):
        raise AssertionError("answer-bundle must not be polled: no background solve started")

    monkeypatch.setattr(run_exam_deck, "wait_for_answers", must_not_poll)

    pdf = tmp_path / "kokugo.pdf"
    _pdf(pdf, 2)
    out = tmp_path / "reports" / "kokugo-server.json"

    code = run_exam_deck.main(
        ["--pdf", str(pdf), "--server", "http://phone.example:8000", "--out", str(out)])

    assert code == 1
    assert "background solve" in capsys.readouterr().out
    assert not out.exists()
