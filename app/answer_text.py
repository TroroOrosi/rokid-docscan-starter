"""Turn a solver's answer into the text the operator writes on the answer sheet.

A model writes for a screen with a font. The glasses have neither: the HUD is
monochrome green, at most three lines, and renders exactly the characters it is
given (`app/glasses_view.py`). LaTeX, markdown tables and image references
therefore reach the operator as literal backslashes and pipes.

Two jobs, in this order:

1. **Convert** the notation models actually emit into characters the display
   renders: fractions, powers, indices, roots, greek letters, operators.
2. **Refuse to hide the rest.** Anything left that the answer sheet cannot carry
   as text is named in `unsupported`, and a caller must not report that answer
   as ready (`tasks/todo.md` FS-65, 未対応要素を落としたREADYを禁止).

The stored solver output is never rewritten; this runs while a payload is built,
so the persisted answer stays auditable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Superscript and subscript characters the display renders as one glyph each.
_SUPERSCRIPT = str.maketrans("0123456789+-=()n", "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079\u207a\u207b\u207c\u207d\u207e\u207f")
_SUBSCRIPT = str.maketrans("0123456789+-=()", "\u2080\u2081\u2082\u2083\u2084\u2085\u2086\u2087\u2088\u2089\u208a\u208b\u208c\u208d\u208e")

# A LaTeX command mapped to the character an operator would write by hand.
# Only commands that have a faithful single-character rendering belong here; an
# unknown command must survive to `unsupported` rather than be dropped.
_COMMANDS = {
    "times": "\u00d7", "div": "\u00f7", "cdot": "\u30fb", "pm": "\u00b1", "mp": "\u2213",
    "leq": "\u2266", "le": "\u2266", "geq": "\u2267", "ge": "\u2267", "neq": "\u2260",
    "approx": "\u2252", "infty": "\u221e", "rightarrow": "\u2192", "to": "\u2192",
    "alpha": "\u03b1", "beta": "\u03b2", "gamma": "\u03b3", "delta": "\u03b4",
    "epsilon": "\u03b5", "theta": "\u03b8", "lambda": "\u03bb", "mu": "\u03bc",
    "pi": "\u03c0", "rho": "\u03c1", "sigma": "\u03c3", "tau": "\u03c4",
    "phi": "\u03c6", "omega": "\u03c9", "Omega": "\u03a9", "Delta": "\u0394",
    "Sigma": "\u03a3", "circ": "\u00b0", "degree": "\u00b0",
    # Layout-only commands carry no answer content.
    "left": "", "right": "", "displaystyle": "", "text": "", "mathrm": "",
    "quad": " ", "qquad": " ",
}

_CASES = re.compile(r"\\begin\{cases\}(.*?)\\end\{cases\}", re.DOTALL)
_FRAC = re.compile(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
_SQRT = re.compile(r"\\sqrt\s*\{([^{}]*)\}")
_POWER = re.compile(r"\^\s*\{([^{}]*)\}|\^(\w)")
_INDEX = re.compile(r"_\s*\{([^{}]*)\}|_(\w)")
_COMMAND = re.compile(r"\\([A-Za-z]+)\s*")
_MATH_DELIMITERS = ("\\(", "\\)", "\\[", "\\]", "$$", "$")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_TABLE_RULE = re.compile(r"^\s*\|[\s:|-]+\|\s*$", re.MULTILINE)
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_CODE_FENCE = re.compile(r"```")
_LEFTOVER = re.compile(r"\\[A-Za-z]+|\\\\")

_TABLE_LABEL = "\u8868"  # 表
_IMAGE_LABEL = "\u56f3\uff08\u753b\u50cf\uff09"  # 図（画像）
_FENCE_LABEL = "\u30b3\u30fc\u30c9\u30d6\u30ed\u30c3\u30af"  # コードブロック
_NOTATION_LABEL = "\u672a\u5bfe\u5fdc\u306e\u8a18\u6cd5: "  # 未対応の記法:


@dataclass(frozen=True)
class DisplayAnswer:
    """What the operator can be shown, and what could not be shown at all."""

    text: str
    unsupported: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        """True when every element of the answer survived into `text`."""
        return not self.unsupported


def _atom(part: str) -> str:
    """Parenthesise a fraction part only when it is not already one token.

    `1/2` is what the operator writes; `(1)/(2)` is noise. But `(a+b)/2c` reads
    as ((a+b)/2)c, so anything longer than a single symbol or a plain number
    keeps its parentheses.
    """
    body = part.strip()
    return body if len(body) == 1 or body.isdigit() else f"({body})"


def _cases(match: re.Match) -> str:
    """One 場合分け per line: `\\begin{cases} a & x>0 \\\\ b & x<0 \\end{cases}`."""
    rows = [row.strip() for row in re.split(r"\\\\|\n", match.group(1))]
    return "\n".join(row.replace("&", " ").strip() for row in rows if row.strip())


def _script(match: re.Match, table: dict[int, str], fallback: str) -> str:
    """Render one ^{...} or _{...} run, or keep it readable if it has no glyphs."""
    body = match.group(1) if match.group(1) is not None else match.group(2)
    converted = body.translate(table)
    if converted == body and any(c.isalnum() for c in body):
        return fallback.format(body)
    return converted


def to_display_answer(answer: str) -> DisplayAnswer:
    """Convert `answer` for the glasses display and name what did not convert."""
    text = (answer or "").strip()
    if not text:
        return DisplayAnswer("")

    unsupported: list[str] = []
    if _IMAGE.search(text):
        unsupported.append(_IMAGE_LABEL)
        text = _IMAGE.sub("", text)
    if _TABLE_ROW.search(text) and _TABLE_RULE.search(text):
        unsupported.append(_TABLE_LABEL)
    if _CODE_FENCE.search(text):
        unsupported.append(_FENCE_LABEL)
        text = _CODE_FENCE.sub("", text)

    text = _CASES.sub(_cases, text)
    for _ in range(4):  # a nested \frac{\frac{a}{b}}{c} needs one pass per level
        converted = _FRAC.sub(lambda m: f"{_atom(m.group(1))}/{_atom(m.group(2))}", text)
        if converted == text:
            break
        text = converted
    text = _SQRT.sub(lambda m: f"\u221a({m.group(1)})", text)
    text = _POWER.sub(lambda m: _script(m, _SUPERSCRIPT, "^({0})"), text)
    text = _INDEX.sub(lambda m: _script(m, _SUBSCRIPT, "_({0})"), text)
    text = _COMMAND.sub(lambda m: _COMMANDS.get(m.group(1), "\\" + m.group(1)), text)

    # Name what is left BEFORE the braces go, or `\begin{cases}` is reported as
    # the run-together `\begincasesx` instead of `\begin`.
    leftover = sorted(set(_LEFTOVER.findall(text)))
    if leftover:
        unsupported.append(_NOTATION_LABEL + " ".join(leftover[:5]))

    for delimiter in _MATH_DELIMITERS:
        text = text.replace(delimiter, "")
    text = text.replace("{", "").replace("}", "")

    text = re.sub(r"[ \t]+", " ", text).strip()
    return DisplayAnswer(text, tuple(unsupported))
