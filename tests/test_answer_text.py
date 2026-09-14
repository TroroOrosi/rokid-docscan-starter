"""The answer text an operator can actually write down.

FS-65 in tasks/todo.md: 指数/分数/場合分け/表/図 must reach the operator in full,
and an answer that lost an element must never be reported READY.
"""

from app.answer_text import to_display_answer

BS = chr(92)


def test_a_fraction_becomes_something_writable():
    assert to_display_answer(BS + "frac{1}{2}").text == "1/2"


def test_a_compound_fraction_keeps_its_grouping():
    """(a+b)/2c would read as ((a+b)/2)c, which is a different answer."""
    assert to_display_answer(BS + "frac{a+b}{2c}").text == "(a+b)/(2c)"


def test_powers_and_indices_become_single_glyphs():
    assert to_display_answer("x^{2}+y_{1}").text == "x²+y₁"


def test_an_unrenderable_exponent_stays_readable_instead_of_vanishing():
    got = to_display_answer("e^{n+1}").text
    assert got == "e^(n+1)" or got == "eⁿ⁺¹"
    assert "{" not in got


def test_roots_operators_and_greek_letters_convert():
    assert to_display_answer(BS + "sqrt{2}" + BS + "times" + BS + "pi").text == "√(2)×π"


def test_a_case_split_becomes_one_line_per_case():
    source = (
        BS + "begin{cases}2x & x>0 " + BS + BS + " -x & x<0 " + BS + "end{cases}"
    )
    assert to_display_answer(source).text == "2x x>0\n-x x<0"


def test_an_answer_that_needs_no_conversion_is_untouched():
    answer = "④: ρ(1−α)Vg"
    result = to_display_answer(answer)
    assert result.text == answer
    assert result.complete


def test_a_table_is_named_rather_than_silently_shown_as_pipes():
    result = to_display_answer("| a | b |\n|---|---|\n| 1 | 2 |")
    assert not result.complete
    assert result.unsupported == ("表",)


def test_an_image_reference_is_named_and_removed():
    result = to_display_answer("答: ![図](fig.png)")
    assert not result.complete
    assert result.unsupported == ("図（画像）",)
    assert "fig.png" not in result.text


def test_unknown_notation_is_named_by_its_own_command():
    """The report must name \\begin, not the run-together text around it."""
    result = to_display_answer(BS + "begin{array}{c}1" + BS + "end{array}")
    assert not result.complete
    assert result.unsupported == ("未対応の記法: " + BS + "begin " + BS + "end",)


def test_an_empty_answer_is_complete_and_empty():
    result = to_display_answer("  ")
    assert result.text == ""
    assert result.complete
