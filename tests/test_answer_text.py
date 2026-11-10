"""The answer text an operator can actually write down.

FS-65 in tasks/todo.md: 指数/分数/場合分け/表/図 must reach the operator in full,
and an answer that lost an element must never be reported READY.
"""

import ast
import operator
import re
from fractions import Fraction

import pytest

from app.answer_text import to_display_answer

BS = chr(92)


def test_a_fraction_becomes_something_writable():
    assert to_display_answer(BS + "frac{1}{2}").text == "(1/2)"


def test_a_compound_fraction_keeps_its_grouping():
    """(a+b)/2c would read as ((a+b)/2)c, which is a different answer."""
    assert to_display_answer(BS + "frac{a+b}{2c}").text == "((a+b)/(2c))"


@pytest.mark.parametrize("source,expected", [
    (r"$\frac{2}{3}^{2}$", "(2/3)²"),
    (r"$\frac{a+b}{c}^{2}$", "((a+b)/c)²"),
    (r"$\frac{x}{y}^{-1}$", "(x/y)⁻¹"),
    (r"$\dfrac{x}{y}_1$", "(x/y)₁"),
    (r"$\tfrac{x}{y}_{i+1}$", "(x/y)_(i+1)"),
    (r"$\frac{x}{y}^2_1$", "(x/y)²₁"),
    (r"$\frac{x}{y}_1^2$", "(x/y)₁²"),
    (r"$\frac{2}{3} ^{2}$", "(2/3) ²"),
    (r"$-3+\frac{2}{3}^{2}z$", "-3+(2/3)²z"),
    (r"$\frac{1}{\frac{2}{3}}^{2}$", "(1/((2/3)))²"),
    (r"$\frac{\frac{1}{2}}{3}^{2}$", "(((1/2))/3)²"),
    (r"$\frac{1}{\frac{2}{3}^2}$", "(1/((2/3)²))"),
    (r"$\frac{x}{y}^{\frac{1}{2}}$", "(x/y)^((1/2))"),
    (r"\frac{2}{3}^{2}", "(2/3)^{2}"),
])
def test_fraction_scripts_apply_to_the_whole_fraction(source, expected):
    result = to_display_answer(source)
    assert result.text == expected
    assert result.complete


@pytest.mark.parametrize("source,expected", [
    (r"$\frac{2}{3}+x^2$", "(2/3)+x²"),
    (r"$\frac{a+b}{2c}$", "((a+b)/(2c))"),
    (r"$\frac{1}{\frac{2}{3}}$", "(1/((2/3)))"),
    (r"$\frac{2}{3}x^2$", "(2/3)x²"),
    (r"$2/\frac{2}{3}$", "2/(2/3)"),
    (r"$\frac{2}{3}/4$", "(2/3)/4"),
    (r"$2/\frac{2}{3}/4$", "2/(2/3)/4"),
    (r"$\frac{1}{2}\frac{3}{4}$", "(1/2)(3/4)"),
    (r"$\frac{1}{2}3$", "(1/2)3"),
    (r"$3\cdot\frac{1}{2}$", "3・(1/2)"),
    (r"$x\frac{1}{2}y$", "x(1/2)y"),
    (r"$(a+b)\frac{1}{2}(c+d)$", "(a+b)(1/2)(c+d)"),
    (r"$f(\frac{1}{2})$", "f((1/2))"),
    (r"$\sqrt{\frac{1}{2}}$", "√((1/2))"),
    (r"$\frac{-a}{+b}$", "((-a)/(+b))"),
    (r"$\frac{x}{y}^{+2}$", "(x/y)⁺²"),
])
def test_fraction_remains_one_atom_in_surrounding_arithmetic(source, expected):
    result = to_display_answer(source)
    assert result.text == expected
    assert result.complete


def _numeric_value(expression):
    operations = {ast.Add: operator.add, ast.Sub: operator.sub,
                  ast.Mult: operator.mul, ast.Div: operator.truediv}
    unary = {ast.UAdd: operator.pos, ast.USub: operator.neg}

    def evaluate(node):
        if isinstance(node, ast.Constant):
            return Fraction(node.value)
        if isinstance(node, ast.UnaryOp):
            return unary[type(node.op)](evaluate(node.operand))
        assert isinstance(node, ast.BinOp)
        return operations[type(node.op)](evaluate(node.left), evaluate(node.right))

    # Mathematical juxtaposition is multiplication, including 3(1/2) and
    # (1/2)(3/4). Keep division left-associative as a reader would.
    explicit = re.sub(r"(?<=[0-9)])(?=\()|(?<=\))(?=[0-9])", "*", expression.replace("・", "*"))
    return evaluate(ast.parse(explicit, mode="eval").body)


@pytest.mark.parametrize("source,value", [
    (r"$2/\frac{2}{3}$", Fraction(3)),
    (r"$\frac{1}{2}\frac{3}{4}$", Fraction(3, 8)),
    (r"$\frac{1}{2}3$", Fraction(3, 2)),
    (r"$3\cdot\frac{1}{2}$", Fraction(3, 2)),
    (r"$\frac{1}{2}/3$", Fraction(1, 6)),
    (r"$\frac{1}{\frac{2}{3}}$", Fraction(3, 2)),
    (r"$\frac{-1}{2}$", Fraction(-1, 2)),
    (r"$\frac{\frac{1}{2}}{\frac{3}{4}}$", Fraction(2, 3)),
])
def test_fraction_rendering_preserves_numeric_value(source, value):
    result = to_display_answer(source)
    assert result.complete
    assert _numeric_value(result.text) == value


def test_fraction_juxtaposed_with_variables_preserves_value_after_substitution():
    result = to_display_answer(r"$x\frac{1}{2}y$")
    assert result.complete
    assert _numeric_value(result.text.replace("x", "2").replace("y", "3")) == Fraction(3)


@pytest.mark.parametrize("source,expected", [
    (r"$3\frac{1}{2}$", r"3\frac{1}{2}"),
    (r"$3 \frac{1}{2}$", r"3 \frac{1}{2}"),
])
def test_ambiguous_mixed_number_or_product_keeps_original_fraction_and_requires_review(source, expected):
    result = to_display_answer(source)
    assert result.text == expected
    assert not result.complete
    assert result.unsupported == ("未対応の記法: " + BS + "frac",)


def test_fraction_with_unhandled_nested_script_groups_remains_explicitly_unsupported():
    result = to_display_answer(r"$\frac{1}{\frac{2}{3}^{2}}$")
    assert result.text == r"\frac{1}{(2/3)²}"
    assert not result.complete
    assert result.unsupported == ("未対応の記法: " + BS + "frac",)


def test_powers_and_indices_become_single_glyphs():
    assert to_display_answer("$x^{2}+y_{1}$").text == "x²+y₁"


def test_an_unrenderable_exponent_stays_readable_instead_of_vanishing():
    got = to_display_answer("$e^{n+1}$").text
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


def test_plain_program_and_aligned_text_keep_all_significant_characters():
    for answer in (
        "for i in range(3):\n    total_cost += i\n    x_1 = i ^ 2",
        "価格は $5、値は x_1。\nA    B\n1    2",
        "0010 ^ 0011 = 0001",
        "価格は$5と$10です。比率は$5/$10。",
        'print("$x_1$", "total_cost", "\\\\n")',
        'result = {1, 2} ^ {2, 3}',
        '    result = source ^ {1, 2}',
        'x^{2}',
    ):
        result = to_display_answer(answer)
        assert result.text == answer
        assert result.complete


def test_fenced_and_inline_code_are_not_mathematical_notation():
    answer = '```python\nfor i in range(3):\n    total_cost += i\n    print("$x_1$", "\\\\n")\n```'
    result = to_display_answer(answer)
    assert result.text == 'for i in range(3):\n    total_cost += i\n    print("$x_1$", "\\\\n")'
    assert result.complete
    assert to_display_answer('変数 `total_cost` と `x^2`').text == '変数 total_cost と x^2'


def test_explicit_math_is_converted_without_changing_surrounding_plain_text():
    result = to_display_answer('変数 total_cost。式: $x^2+y_1$\n    続き')
    assert result.text == '変数 total_cost。式: x²+y₁\n    続き'
    assert result.complete


def test_unclosed_code_fence_is_not_silently_rewritten_or_accepted():
    source = '```python\n    total_cost = x_1 ^ 2\n    quoted = "$x_1$"\n    x^{2}'
    result = to_display_answer(source)
    assert result.text == source
    assert not result.complete


def test_mixed_supported_and_unsupported_script_characters_keep_the_whole_group():
    for source, expected in (("x^{2k}", "x^(2k)"), ("x_{i+1}", "x_(i+1)"),
                             ("x^{a2}", "x^(a2)"), ("x^{n+1}", "xⁿ⁺¹")):
        result = to_display_answer('$' + source + '$')
        assert result.text == expected
        assert result.complete
