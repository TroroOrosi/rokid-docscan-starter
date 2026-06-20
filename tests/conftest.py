import io

import pytest
from PIL import Image, ImageDraw


def make_image(seed: int = 0, size: int = 256, text: str | None = None) -> Image.Image:
    """Deterministic synthetic 'page' image."""
    img = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(img)
    # a few seed-dependent shapes so different seeds -> different pHash
    for i in range(6):
        x0 = (seed * 13 + i * 29) % size
        y0 = (seed * 17 + i * 31) % size
        x1 = (x0 + 40 + i * 7) % size
        y1 = (y0 + 30 + i * 11) % size
        draw.rectangle([min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)],
                       fill=(seed * 20 % 256, i * 40 % 256, 60))
    if text:
        draw.text((10, 10), text, fill="black")
    return img


def image_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def make_image_fixture():
    return make_image


@pytest.fixture
def image_bytes_fixture():
    return image_bytes
