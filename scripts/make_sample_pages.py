#!/usr/bin/env python3
"""Generate sample page images for the README curl examples.

Usage:  python scripts/make_sample_pages.py
Writes page0.png, page1.png and query.png (== page0) to the cwd.
"""

from __future__ import annotations

from PIL import Image, ImageDraw


def make_page(seed: int, label: str) -> Image.Image:
    size = 512
    img = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(img)
    for i in range(8):
        x0 = (seed * 13 + i * 29) % size
        y0 = (seed * 17 + i * 31) % size
        x1 = (x0 + 60 + i * 9) % size
        y1 = (y0 + 50 + i * 13) % size
        draw.rectangle(
            [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)],
            outline=(20, 20, 20),
            width=3,
        )
    draw.text((20, 20), label, fill="black")
    return img


if __name__ == "__main__":
    make_page(10, "PAGE 0 body text").save("page0.png")
    make_page(200, "PAGE 1 body text").save("page1.png")
    make_page(10, "PAGE 0 body text").save("query.png")  # same as page0
    print("wrote page0.png, page1.png, query.png")
