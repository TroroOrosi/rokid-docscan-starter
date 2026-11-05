"""Bounded vector answers shared with the offline glasses Canvas renderer."""

import math


def _number(value, low=0, high=1):
    if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
        raise ValueError("invalid diagram coordinate")


def _label(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("invalid diagram label")


def validate_diagrams(value):
    if not isinstance(value, list) or len(value) > 4:
        raise ValueError("invalid answer diagrams")
    for diagram in value:
        if not isinstance(diagram, dict) or set(diagram) != {"alt", "aspect_ratio", "elements"}:
            raise ValueError("invalid diagram fields")
        _label(diagram["alt"], 500)
        _number(diagram["aspect_ratio"], 0.25, 4)
        elements = diagram["elements"]
        if not isinstance(elements, list) or not 1 <= len(elements) <= 128:
            raise ValueError("invalid diagram elements")
        for element in elements:
            if not isinstance(element, dict):
                raise ValueError("invalid diagram element")
            kind = element.get("type")
            coords = {"line": ("x1", "y1", "x2", "y2"), "circle": ("cx", "cy", "r"),
                      "arc": ("cx", "cy", "r"), "polygon": (),
                      "text": ("x", "y"), "polyline": ()}.get(kind)
            if coords is None:
                raise ValueError("unsupported diagram element")
            fields = {"type", *coords} | ({"text"} if kind == "text" else set())
            optional = {"dashed"} if kind in ("line", "polyline", "circle", "arc", "polygon") else set()
            if kind == "circle":
                optional.add("filled")
            if kind == "polygon":
                optional.add("hatched")
            for key in optional & element.keys():
                if type(element[key]) is not bool:
                    raise ValueError("invalid diagram style")
            if kind == "circle" and element.get("filled") and element.get("dashed"):
                raise ValueError("filled circle cannot have a dashed boundary")
            if kind in ("polyline", "polygon"):
                fields.add("points")
                points = element.get("points")
                minimum = 3 if kind == "polygon" else 2
                if not isinstance(points, list) or not minimum <= len(points) <= 256:
                    raise ValueError("invalid diagram points")
                for point in points:
                    if not isinstance(point, list) or len(point) != 2:
                        raise ValueError("invalid diagram point")
                    for number in point:
                        _number(number)
                if kind == "polygon" and sum(
                    points[i - 1][0] * point[1] - point[0] * points[i - 1][1]
                    for i, point in enumerate(points)
                ) == 0:
                    raise ValueError("empty diagram polygon")
            if kind == "arc":
                fields.update(("start_degrees", "sweep_degrees"))
                _number(element.get("start_degrees"), 0, 360)
                _number(element.get("sweep_degrees"), -360, 360)
                if element["sweep_degrees"] == 0:
                    raise ValueError("empty diagram arc")
            if not fields <= element.keys() or element.keys() - fields - optional:
                raise ValueError("invalid diagram element fields")
            for coord in coords:
                _number(element[coord])
            if kind == "text":
                _label(element["text"], 80)
            if kind in ("circle", "arc"):
                # r uses the shorter side so circles remain round at any aspect ratio.
                aspect = diagram["aspect_ratio"]
                rx, ry = element["r"] / max(1, aspect), element["r"] * min(1, aspect)
                if element["r"] <= 0 or not (rx <= element["cx"] <= 1-rx
                                              and ry <= element["cy"] <= 1-ry):
                    raise ValueError("circle outside diagram")
    return value


def diagram_schema_version(diagrams):
    """Keep old saved drawings on schema 2; styles/arcs/regions require the new reader."""
    if not diagrams:
        return 1
    return 3 if any(element["type"] in ("arc", "polygon")
                    or {"dashed", "filled", "hatched"} & element.keys()
                    for diagram in diagrams for element in diagram["elements"]) else 2
