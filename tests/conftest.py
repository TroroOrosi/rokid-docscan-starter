import html
import io
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

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


@pytest.fixture
def dom_states():
    """Run a script in local headless Chromium; return what it stored in ``<pre id=states>``.

    A browser start that hangs is retried once with a fresh profile: on CI the same
    commit both passed and timed out at 30 s (2026-11-10, Linux and Windows runners).
    """
    browser = next((p for p in [shutil.which("google-chrome"), shutil.which("chromium"),
                    "C:/Program Files/Google/Chrome/Application/chrome.exe"] if p and Path(p).is_file()), None)
    if browser is None:
        pytest.skip("local Chromium is not installed; no browser is downloaded")

    def run(script: str):
        for attempt in range(2):
            with tempfile.TemporaryDirectory(prefix="rokid-dom-", ignore_cleanup_errors=True) as directory:
                fixture = Path(directory) / "fixture.html"
                fixture.write_text('<meta charset="utf-8"><body><script>' + script + "</script>", encoding="utf-8")
                try:
                    result = subprocess.run([
                        browser, "--headless", "--dump-dom", "--disable-background-networking",
                        "--disable-component-update", "--disable-sync", "--no-first-run",
                        "--no-default-browser-check", "--host-resolver-rules=MAP * ~NOTFOUND",
                        "--user-data-dir=" + str(Path(directory) / "profile"), fixture.as_uri(),
                    ], capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
                except subprocess.TimeoutExpired:
                    if attempt:
                        raise
                    continue
            assert result.returncode == 0, f"{browser} exited {result.returncode}: {result.stderr}"
            return json.loads(html.unescape(result.stdout.split('<pre id="states">', 1)[1].split("</pre>", 1)[0]))

    return run
