"""Two reads that say the same thing in different forms agree (2026-11-19).

The operator, after two subjects that day: an answer was marked as differing between the two reads where only its
form differed, the presence of a bracket for one. Of the day's three booklets 41 of 175 answers carried a note; read
again from the kept replies, some were one read writing each box under its printed name ("［7］：①") and the other
the bare values, a value in brackets against the same value without, and one read naming boxes by their letters
where the other went by answer numbers. Every example here is made up.
"""
import pytest

from app.solvers import codex_cli
from app.solvers.base import Question


def _item(numbers, answer, label="問1", status="ready"):
    return {"group": "第1問", "label": label, "answer_no": numbers, "pages": [1], "status": status, "answer": answer,
            "missing_material": "" if status == "ready" else "不鮮明", "diagrams": []}


def _notes(first, second):
    question = Question(question_no=None, chat_key=None, document_pages=[], document_id="1")
    replies = codex_cli.CodexCliSolver._answers(
        [{"questions": first}, {"questions": second}], question, {"source": "codex-cli"})
    return [result.extras.get("review_note", "") for _, result in replies]


@pytest.mark.parametrize("named", [
    "［7］：①\n［8］：③\n［9］：④",   # each box under its printed answer number
    "〔7〕：①\n〔8〕：③\n〔9〕：④",
    "(7) ①\n(8) ③\n(9) ④".replace(") ", ")："),
    "ア：①\nイ：③\nウ：④",         # the boxes' own letters, where the other read goes by answer numbers
    "a：①\nb：③\nc：④",
    "Ⅰ：①\nⅡ：③\nⅢ：④",
])
@pytest.mark.parametrize("bare", [
    [_item([7], "①", "問1"), _item([8], "③", "問2"), _item([9], "④", "問3")],  # a question for each number
    [_item([7, 8, 9], "① ③ ④")],                                              # one line, a mark for each
    [_item([7, 8, 9], "1、3、4")],                                             # digits where the other circles them
])
def test_boxes_written_under_their_printed_names_agree_with_the_bare_values(named, bare):
    assert _notes([_item([7, 8, 9], named)], bare) == [""]
    assert not any(_notes(bare, [_item([7, 8, 9], named)]))


def test_a_box_that_really_differs_is_still_found_under_its_name():
    [note] = _notes([_item([7, 8, 9], "ア：①\nイ：③\nウ：④")], [_item([7, 8, 9], "① ② ④")])
    assert note and "8" in note, "the second box, by its answer number"
    [note] = _notes([_item([7, 8, 9], "［7］：①\n［8］：③\n［9］：④")], [_item([7, 8, 9], "［7］：①\n［8］：③\n［9］：②")])
    assert note


@pytest.mark.parametrize("first, second", [
    ("図1：（C）\n図2：（A）", "図1：C 図2：A"),   # a value in brackets against the value
    ("（C）", "C"),
    ("（イ）", "イ"),
    ("ジャン＝ジャック", "ジャンジャック"),       # the double hyphen of a name in katakana
    ("〔1〕：光合成\n〔2〕：蒸散", "(1):光合成、(2):蒸散"),
])
def test_the_same_answer_in_another_form_is_no_difference(first, second):
    assert _notes([_item([1], first)], [_item([1], second)]) == [""]
    assert _notes([_item([1], second)], [_item([1], first)]) == [""]


@pytest.mark.parametrize("first, second", [
    ("2(x+1)", "2x+1"),        # a bracket that belongs to the value
    ("(0,1)", "[0,1]"),        # an open and a closed interval
    ("1:2", "5:2"),            # a ratio is no box under the name 1
    ("A=B", "AB"),
    ("（C）", "（D）"),
    ("図1：（C）\n図2：（A）", "図1：C 図2：B"),
])
def test_what_differs_in_more_than_form_is_still_a_difference(first, second):
    assert all(_notes([_item([1], first)], [_item([1], second)]))


def test_two_boxes_of_ratios_are_compared_whole():
    assert all(_notes([_item([3, 4], "1:2\n3:4")], [_item([3, 4], "5:2\n7:4")]))
    assert _notes([_item([3, 4], "1:2\n3:4")], [_item([3, 4], "1:2\n3:4")]) == [""]


def test_a_two_digit_label_both_reads_agree_on_carries_no_note():
    """Until 2026-11-19 such an answer always asked to be checked on the paper. The option's words stand beside the
    label for that, and the operator asked for answers without explanations."""
    assert _notes([_item([1], "⑫（光合成）")], [_item([1], "⑫（光合成）")]) == [""]
