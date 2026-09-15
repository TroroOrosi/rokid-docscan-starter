import pytest

from app.answer_diagrams import validate_diagrams


def test_diagram_contract_preserves_geometry_and_rejects_unrenderable_elements():
    diagram = {"alt": "直角三角形", "aspect_ratio": 1.5, "elements": [
        {"type": "polyline", "points": [[0.1, 0.1], [0.1, 0.9], [0.9, 0.9], [0.1, 0.1]]},
        {"type": "text", "x": 0.2, "y": 0.2, "text": "A"},
    ]}
    assert validate_diagrams([diagram]) == [diagram]
    for bad in [None, [dict(diagram, elements=[])], [dict(diagram, aspect_ratio=float("nan"))],
                [dict(diagram, elements=[{"type": "image", "url": "https://example.org"}])],
                [dict(diagram, elements=[{"type": "line", "x1": True, "y1": 0, "x2": 1, "y2": 1}])]]:
        with pytest.raises(ValueError):
            validate_diagrams(bad)
