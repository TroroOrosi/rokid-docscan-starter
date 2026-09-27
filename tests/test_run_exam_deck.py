"""The deck bench's per-paper isolation, photo input and answer polling.

The bench writes each run into a database directory. It used to write every
paper into ONE --data-dir, so a query issued after a later run read the
previous paper's rows (observed while diagnosing on 2026-09-14).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_exam_deck import deck_data_dir, load_images, wait_for_answers  # noqa: E402

ROOT = Path("C:/rokid-exam-materials/rundata")


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


def test_photos_load_in_name_order_without_text(tmp_path):
    (tmp_path / "img-2.jpg").write_bytes(b"\xff\xd8two")
    (tmp_path / "img-1.JPG").write_bytes(b"\xff\xd8one")
    (tmp_path / "notes.txt").write_text("not a page")
    assert load_images(tmp_path) == [(b"\xff\xd8one", ""), (b"\xff\xd8two", "")]


class _Response:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body


def _bundle(*statuses):
    return _Response(200, {"items": [{"status": s} for s in statuses]})


class _Server:
    """answer-bundle as the background batch serves it, one response per poll."""

    def __init__(self, *responses):
        self.responses = list(responses)

    def get(self, url):
        return self.responses.pop(0)


def test_the_wait_polls_through_the_listing_until_nothing_is_pending():
    server = _Server(
        _Response(409, {"detail": "the question list is being made"}),
        _bundle("pending", "pending"),
        _bundle("ready", "pending"),
        _bundle("ready", "failed"),
    )
    got = wait_for_answers(server, 1, timeout=60, interval=0)
    assert got.status_code == 200 and server.responses == []


def test_the_wait_stops_on_any_other_conflict():
    server = _Server(
        _Response(409, {"detail": "no problems were detected in this document"}),
        _bundle("ready"),
    )
    assert wait_for_answers(server, 1, timeout=60, interval=0).status_code == 409
    assert len(server.responses) == 1


def test_the_wait_gives_up_at_the_timeout_with_answers_still_pending():
    server = _Server(_bundle("pending"), _bundle("ready"))
    got = wait_for_answers(server, 1, timeout=0, interval=0)
    assert got.json()["items"] == [{"status": "pending"}]
    assert len(server.responses) == 1
