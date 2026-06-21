"""Build the answer-area overlay payload (案17).

The server provides WHERE (a normalized answer-area box) and WHAT (short answer
/ answer number) to draw near the paper's answer column. Actual placement is
the client's responsibility.

IMPORTANT hardware note: the 49g Rokid Glasses are an information-display HUD
with NO 6DoF/SLAM, so a precise paper-locked overlay is not achievable on the
glasses themselves. This payload therefore targets a 2D image-anchored
rendering (e.g. drawn onto a captured frame / approximate head-locked text);
true paper-fixed AR is a future item gated on 6DoF tracking.
"""

from __future__ import annotations

from .solvers import SolveResult

_MAX_FULL = 64


def build_overlay(
    solution: SolveResult,
    *,
    answer_box: dict | None,
    locked: bool = False,
) -> dict:
    """Return {items:[{kind, text, box, anchor}], locked}."""
    if locked or answer_box is None:
        return {"items": [], "locked": locked}

    answer = (solution.answer or "").strip()
    # Short token (answer number / choice label) for the cramped answer cell.
    short = answer.split(":", 1)[0].strip() if ":" in answer else answer
    items = [
        {
            "kind": "answer_no",
            "text": short[:8] or answer[:8],
            "box": dict(answer_box),
            "anchor": "answer_area",
        }
    ]
    if answer and answer != short:
        items.append(
            {
                "kind": "answer_full",
                "text": answer[:_MAX_FULL],
                "box": dict(answer_box),
                "anchor": "answer_area",
            }
        )
    return {"items": items, "locked": False}
