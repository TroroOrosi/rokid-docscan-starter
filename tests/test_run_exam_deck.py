"""The deck bench's per-paper isolation.

The bench writes each run into a database directory. It used to write every
paper into ONE --data-dir, so a query issued after a later run read the
previous paper's rows (observed while diagnosing on 2026-09-14).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_exam_deck import deck_data_dir  # noqa: E402

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
