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


# How this payload should be anchored on the client. Today the 49g glasses have
# no 6DoF/SLAM, so we target a 2D image-anchored rendering; true paper-locked AR
# is a future item gated on 6DoF and is advertised here as not-yet-available.
_TRACKING = "2d_image_anchor"


def build_overlay(
    solution: SolveResult,
    *,
    answer_box: dict | None,
    locked: bool = False,
    page_number: int | None = None,
) -> dict:
    """Return {items, locked, tracking, fixed_ar, anchor_hint}.

    `tracking`/`fixed_ar`/`anchor_hint` let the client know the overlay is
    2D image-anchored (not 6DoF paper-locked) and which page/box to anchor to.
    """
    base = {
        "locked": locked,
        "tracking": _TRACKING,
        "fixed_ar": False,  # 6DoF paper-locked AR not yet supported (hardware).
        "anchor_hint": {
            "page_number": page_number,
            "box": dict(answer_box) if answer_box else None,
        },
    }
    if locked or answer_box is None:
        return {"items": [], **base}

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
    return {"items": items, **base}
