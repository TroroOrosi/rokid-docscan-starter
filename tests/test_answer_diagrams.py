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


def test_construction_arcs_graph_endpoints_and_shaded_regions_preserve_their_meaning():
    diagram = {"alt": "放物線、開点・閉点と領域", "aspect_ratio": 1.3, "elements": [
        {"type": "line", "x1": .1, "y1": .5, "x2": .9, "y2": .5, "dashed": True},
        {"type": "polyline", "points": [[.1, .1], [.5, .9], [.9, .1]], "dashed": False},
        {"type": "circle", "cx": .2, "cy": .5, "r": .26},
        {"type": "circle", "cx": .8, "cy": .5, "r": .02, "filled": True},
        {"type": "arc", "cx": .5, "cy": .5, "r": .3, "start_degrees": 30,
         "sweep_degrees": -120, "dashed": True},
        {"type": "polygon", "points": [[.1, .8], [.5, .2], [.9, .8]], "hatched": True},
        {"type": "text", "x": .5, "y": .1, "text": "𝑥" * 80},
    ]}
    assert validate_diagrams([diagram]) == [diagram]


@pytest.mark.parametrize("element", [
    {"type": "line", "x1": 0, "y1": 0, "x2": 1, "y2": 1, "dashed": 1},
    {"type": "text", "x": .5, "y": .5, "text": "x", "dashed": False},
    {"type": "circle", "cx": .5, "cy": .5, "r": .1, "filled": "false"},
    {"type": "circle", "cx": .5, "cy": .5, "r": .1, "filled": True, "dashed": True},
    {"type": "polygon", "points": [[0, 0], [1, 1]], "hatched": True},
    {"type": "polygon", "points": [[0, 0], [.5, .5], [1, 1]], "hatched": True},
    {"type": "polygon", "points": [[0, 0], [1, 1], [0, 1]], "hatched": 0},
    {"type": "arc", "cx": .5, "cy": .5, "r": .1, "start_degrees": 0, "sweep_degrees": 0},
    {"type": "arc", "cx": .5, "cy": .5, "r": .1, "start_degrees": float("nan"), "sweep_degrees": 90},
    {"type": "arc", "cx": .5, "cy": .5, "r": .1, "start_degrees": 10**1000, "sweep_degrees": 90},
    {"type": "arc", "cx": .1, "cy": .5, "r": .3, "start_degrees": 0, "sweep_degrees": 90},
])
def test_extended_diagram_rejects_ambiguous_or_unbounded_geometry(element):
    with pytest.raises(ValueError):
        validate_diagrams([{"alt": "bad", "aspect_ratio": 1, "elements": [element]}])
