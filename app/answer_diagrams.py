"""Bounded vector answers shared with the offline glasses Canvas renderer."""

import math


def _number(value, low=0, high=1):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
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
                      "text": ("x", "y"), "polyline": ()}.get(kind)
            if coords is None:
                raise ValueError("unsupported diagram element")
            fields = {"type", *coords} | ({"text"} if kind == "text" else set())
            if kind == "polyline":
                fields.add("points")
                points = element.get("points")
                if not isinstance(points, list) or not 2 <= len(points) <= 256:
                    raise ValueError("invalid diagram points")
                for point in points:
                    if not isinstance(point, list) or len(point) != 2:
                        raise ValueError("invalid diagram point")
                    for number in point:
                        _number(number)
            if set(element) != fields:
                raise ValueError("invalid diagram element fields")
            for coord in coords:
                _number(element[coord])
            if kind == "text":
                _label(element["text"], 80)
            if kind == "circle":
                # r uses the shorter side so circles remain round at any aspect ratio.
                aspect = diagram["aspect_ratio"]
                rx, ry = element["r"] / max(1, aspect), element["r"] * min(1, aspect)
                if element["r"] <= 0 or not (rx <= element["cx"] <= 1-rx
                                              and ry <= element["cy"] <= 1-ry):
                    raise ValueError("circle outside diagram")
    return value
