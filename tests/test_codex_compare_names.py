"""Two reads that name the same question differently still meet in one item (2026-11-21).

The operator's use of 2026-11-20, a booklet without printed answer numbers: for its first seven major problems one
read wrote the group as "1" and the other as "1." (the labels were the same, 問1). Nothing lined up there: fifteen
questions came out twice, all thirty marked as listed by one read only and moved behind the others on the glasses,
and three good captures were listed to be taken again. Both reads had given the same answers. It was the fourth
such form (2026-11-17 第1問 against nothing, 11-18 "(1)（Ⅰ）" against "（Ⅰ）", register 3-50 left open on 11-19).
Every example here is made up.
"""
import pytest

from app.solvers import codex_cli
from app.solvers.base import Question


def _item(group, label, answer, pages=(1,), status="ready"):
    return {"group": group, "label": label, "answer_no": [], "pages": list(pages), "status": status, "answer": answer,
            "missing_material": "" if status == "ready" else "不鮮明", "diagrams": []}


def _merged(first, second):
    question = Question(question_no=None, chat_key=None, document_pages=[], document_id="1")
    return codex_cli.CodexCliSolver._answers(
        [{"questions": first}, {"questions": second}], question, {"source": "codex-cli"})


def _notes(first, second):
    return [result.extras.get("review_note", "") for _, result in _merged(first, second)]


def _paper(group_form):
    """Seven major problems of one to three questions whose group is written as ``group_form``, and nine more that
    both reads name alike: more than half of the questions line up by name, as on the day, so the reads are not
    simply taken in order."""
    answers = iter(["光合成", "ア", "3.2 g", "イ", "酸化銅", "ウ", "12 cm", "エ", "0.5 A", "オ", "蒸散", "カ"])
    items = []
    for major, questions in ((1, 3), (2, 1), (3, 2), (4, 2), (5, 2), (6, 1), (7, 1)):
        for number in range(1, questions + 1):
            items.append(_item(group_form.format(major), f"問{number}" if questions > 1 else "", next(answers)))
    for major in range(8, 17):
        items += [_item(f"{major}.", "問1", f"答{major}a", pages=(2,)), _item(f"{major}.", "問2", f"答{major}b", pages=(2,))]
    return items


@pytest.mark.parametrize("one, other", [
    ("{}", "{}."),          # the day's form
    ("{}.", "{}"),
    ("{}", "{}．"),
    ("第{}問", "{}"),
    ("大問{}", "{}."),
    ("【{}】", "{}"),
    ("〔{}〕", "({})"),
])
def test_a_group_written_with_or_without_its_marks_is_one_group(one, other):
    first, second = _paper(one), _paper(other)
    merged = _merged(first, second)
    assert len(merged) == len(first), "each question once"
    assert not any(result.extras.get("review_note") for _, result in merged)


def test_a_label_with_or_without_a_closing_mark_is_one_label():
    first = [_item("1", "1.", "ア"), _item("1", "2.", "イ"), _item("1", "(3)", "ウ"), *_alike()]
    second = [_item("1", "1", "ア"), _item("1", "2", "イ"), _item("1", "（3）", "ウ"), *_alike()]
    assert _notes(first, second) == [""] * 9


def _alike(count=6):
    """Questions both reads name alike, on a capture of their own: enough of them that the reads go by name."""
    return [_item("共通", f"問{number}", f"共{number}", pages=(9,)) for number in range(1, count + 1)]


def test_questions_named_differently_that_both_reads_answer_alike_are_one_question():
    # Whatever the next difference of form is: the same captures, the same answer. One read has a question more
    # in between, so the stretch cannot be paired by counting.
    first = [_item("A", "い", "光合成"), _item("A", "ろ", "12 cm"), *_alike()]
    second = [_item("", "設問一", "光合成"), _item("", "設問一の補", "図を参照", status="needs_input"),
              _item("", "設問二", "12 cm"), *_alike()]
    merged = _merged(first, second)
    assert len(merged) == 9, "the two named differently once each, the one more of the second read, the six alike"
    notes = [bool(result.extras.get("review_note")) for _, result in merged]
    assert notes.count(True) == 0, "the second read's extra question has no answer to mark"
    assert [result.answer for _, result in merged][:1] == ["光合成"]


def test_what_one_read_alone_lists_is_still_told_apart():
    first = [_item("1", "問1", "ア"), _item("1", "問2", "イ")]
    second = [_item("1", "問1", "ア"), _item("1", "問2", "イ"), _item("2", "問1", "ウ", pages=(2,))]
    merged = _merged(first, second)
    assert len(merged) == 3
    assert [bool(result.extras.get("review_note")) for _, result in merged] == [False, False, True]


def test_the_same_answer_on_another_capture_is_another_question():
    first = [_item("A", "い", "ア", pages=(1,)), _item("A", "ろ", "イ", pages=(1,)), *_alike()]
    second = [_item("", "設問九", "ア", pages=(3,)), *_alike()]
    merged = _merged(first, second)
    assert len(merged) == 9
    assert sum(bool(result.extras.get("review_note")) for _, result in merged) == 3


def test_different_answers_under_different_names_are_not_one_question_by_their_answers():
    first = [_item("A", "い", "ア"), _item("A", "ろ", "イ"), *_alike()]
    second = [_item("", "設問一", "ウ"), *_alike()]
    merged = _merged(first, second)
    assert len(merged) == 9
    assert sum(bool(result.extras.get("review_note")) for _, result in merged) == 3


def test_written_answers_under_different_names_are_paired_in_order_between_questions_both_name():
    # Writing is not compared; the stretch between two questions both reads name is paired in order as before.
    long = "植物は光を受けて二酸化炭素と水からデンプンなどの養分をつくり、このとき酸素を出す。"
    first = [_item("1", "問1", "ア"), _item("2.", "(a)", long), _item("3", "問1", "イ")]
    second = [_item("1", "問1", "ア"), _item("2", "a", long + "これを光合成という。"), _item("3", "問1", "イ")]
    merged = _merged(first, second)
    assert len(merged) == 3
    assert not any(result.extras.get("review_note") for _, result in merged)
