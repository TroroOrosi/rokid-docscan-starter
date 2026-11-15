"""Gather each recorded page's clip into that page's image, in the background, while the next pages are recorded.

A page arrives as one frame of its clip and its clip follows (app/page_clips.py). Worker threads here take the stored
clips oldest first, add their frames with app/gather.py and put the result in place of the page's image. A clip that
cannot be gathered leaves the page as the one frame it arrived as, with the reason on the clip's row; the booklet goes
on, and the answers name that page (main._answer_snapshot). Design:
docs/superpowers/specs/2026-11-15-gathered-capture-design.md, 6.5 and 6.6.

Threads, not processes: numpy and the decoder release the interpreter while they work. On the phone a 5-second clip was
gathered in 34-35 s and three at once in 39 s (docs/hardware-measurements.md, M-26), hence three workers.
"""
from __future__ import annotations

import io
import json
import logging
import os
import shutil
import threading
from contextlib import closing

from . import db, page_clips

CLIP_SECONDS = 180.0  # the most one clip may take; about five times what a 5-second clip took on the phone
MIN_LEVEL = 8.0  # level over noise: under it nothing could be read, and reading took over nine minutes (M-24)
STALE = "gather error: the page was taken again or its booklet went on"


def _gather_module():
    """app.gather imports numpy when it is imported; the server has to start without numpy."""
    from . import gather  # noqa: PLC0415

    return gather


def page_image(gathered, rotation_degrees: int) -> bytes:
    """The gathered light as the page's PNG: the brightest half percent white, 8 bits through the display curve, turned
    upright (clockwise, as a page upload's image_rotation), RGB like every stored page."""
    import numpy as np  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    white = float(np.percentile(gathered.image, 99.5)) or 1.0
    scaled = np.clip(gathered.image / white, 0, 1)
    shown = np.where(scaled <= 0.0031308, scaled * 12.92, 1.055 * scaled ** (1 / 2.4) - 0.055)
    picture = Image.fromarray((shown * 255 + 0.5).astype(np.uint8)).rotate(-rotation_degrees, expand=True)
    encoded = io.BytesIO()
    picture.convert("RGB").save(encoded, format="PNG")
    return encoded.getvalue()


class GatherService:
    """Worker threads with a wake and a stop signal, as capture_inspection.InspectionService has one."""

    def __init__(self, replace) -> None:
        self._replace = replace  # main.replace_page_image, handed in: main imports this module
        self._wake = threading.Event()
        self._stop = threading.Event()

    def start(self) -> None:
        self._stop = stop = threading.Event()  # a fresh one: workers of an earlier start end on theirs
        for number in range(max(1, int(os.environ.get("ROKID_GATHER_WORKERS") or 3))):
            threading.Thread(target=self._run, args=(stop,), name=f"page-gather-{number}", daemon=True).start()

    def wake(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                worked = self.process_one()
            except Exception as error:  # noqa: BLE001 - the database could not be reached: the worker stays, and looks again
                logging.getLogger(__name__).warning("page gathering stopped this pass: %s", type(error).__name__)
                worked = False
            if not worked:
                self._wake.wait(5)  # a clip that arrives wakes every waiting worker; the five seconds cover a missed wake
                self._wake.clear()

    def process_one(self) -> bool:
        """Gather the oldest stored clip. False when none waits. Whatever stops a clip becomes the reason on its row."""
        clip = page_clips.claim()
        if clip is None:
            return False
        try:
            reason = self._gather(clip)
        except Exception as error:  # noqa: BLE001 - one clip's failure is that clip's; the next one is still taken
            reason = f"gather error: {type(error).__name__}: {error}"
        if reason:
            page_clips.fail(clip["document_id"], clip["page_index"], clip["sha256"], reason)
        return True

    def _gather(self, clip: dict) -> str | None:
        """Why this clip did not become its page's image; None when it did."""
        document_id, page_index, sha256 = clip["document_id"], clip["page_index"], clip["sha256"]
        with closing(db.connect()) as conn:
            capture, _ = page_clips.open_capture(conn, document_id, page_index)
        if capture.get("capture_id") != clip["capture_id"]:
            return STALE  # known before half a minute is spent on it
        try:
            gather = _gather_module()
        except ImportError:
            return "numpy unavailable"
        if shutil.which(os.environ.get("ROKID_FFMPEG") or "ffmpeg") is None:
            return "ffmpeg unavailable"
        try:
            gathered = gather.gather_clip(page_clips.clip_path(document_id, page_index, sha256), json.loads(clip["record_json"]),
                                          settle=6, seconds=CLIP_SECONDS)
        except gather.GatherTimeout:
            return "timeout"
        if not gathered.placed:
            return "not placed"
        if gathered.level_over_noise < MIN_LEVEL:
            return "too dark"
        level = round(float(gathered.level_over_noise), 2)
        note = {"used": gathered.used, "total": gathered.total, "level_over_noise": level, "clip_sha256": sha256}
        if not self._replace(document_id, page_index, page_image(gathered, capture["rotation_degrees"]), note):
            return STALE
        page_clips.finish(document_id, page_index, sha256, used=gathered.used, total=gathered.total, level=level)
        return None
