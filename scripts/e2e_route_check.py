"""Drive the whole route on the real glasses, as a wearer would, without sending anything to the model.

    wear -> choose -> capture pages -> end -> upload -> analysis wait -> answers arrive -> wake -> read -> finish

The glasses run the same app under a second package name (`-PglassdocRouteCheck`, installed beside the real app, whose
saved server, key and answers are never touched). Server and watcher run on this PC: the server with
`ROKID_SOLVER=recorded` (a recorded reply stands for the model; sending is off, no browser is involved) and its own
data directory; the glasses reach it over `adb reverse`. Gestures are written to the touchpad's own input device.

This checks the glasses-side route and the server and watcher logic. It does NOT check the venue topology: the phone,
its hotspot, its load and its browser are not in the loop.

    py -3.12 scripts/e2e_route_check.py --glasses <adb transport> --data <server data dir> --key <test api key>
        [--server http://127.0.0.1:8765] [--photos 3] [--capture clip] [--report <dir>]

--capture says how a page is taken and is saved by the test app on every start: `still` (the default) or `clip`,
where a page is a short recording that the server gathers into the page's image (the server needs numpy and ffmpeg).
With `clip` every page's recording is checked (frames, none dropped, gain, the wait for its first frame, the
gyroscope's clock), then that each clip reached the server and became its page's image. --long-above N (hundredths of
gain, saved by the test app on every start) lets a clip take 60 ms instead of 30 where 30 ms would need more gain
than N: 705 is the light a page was read at, and 300 makes the app take 60 ms on a desk, which is too bright for it
otherwise. 0, the default, never takes it: on a worn head hardly a frame was still at 60 ms (M-31).

--glasses is any adb transport of the glasses. Without a cable it is the one scripts/glasses_over_phone.py prints
(this PC -> the phone on the home network -> the glasses on the phone's hotspot); `adb reverse` works over it too.
A worn recording has to use that one: nobody reads a booklet on a cable.

With --paper SECONDS the run is a recording of worn use and nothing else: unless --no-reference is given (the photo
goes to the glasses' gallery; with --capture clip the light is read from the watch preview anyway), the glasses' own
camera takes one reference
photo of what the wearer is looking at (its exposure and sensitivity say how much light is on the page), then the
reading is started, the wearer reads a
real booklet for that long without touching the touchpad, and the run reports the light the camera measured, the
head's turning, every photo and the turning during its exposure, and keeps the 200 Hz head-motion trace
(scripts/head_motion_report.py replays capture rules against it). The capture is not ended, so not even the stand-in
is asked. The real app is force-stopped first: its wear detection would bring it to the front, and there the double
tap that ends a capture sends the pages to the model. Its wear detection starts again when it is next opened.

Start the server first (see the docstring of app/solvers/recorded.py for its environment) and `adb reverse` its port.
The double tap that ends the capture is sent only after the server answering the app is confirmed to be the
stand-in. The start double tap is sent once and confirmed from a time-stamped log filter, never repeated.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ADB = os.environ.get("ADB", r"C:\Users\pupu_\AppData\Local\Android\Sdk\platform-tools\adb.exe")
PACKAGE = "dev.rokid.docscanglass.doc.routecheck"
REAL_PACKAGE = "dev.rokid.docscanglass.doc"
ACTIVITY = f"{PACKAGE}/dev.rokid.docscanglass.doc.DocScanGlassActivity"
GLASSES_SERIAL = "1904092623381086"
TOUCHPAD = "/dev/input/event1"
TAP, SWIPE_FORWARD, SWIPE_BACK, DOUBLE_TAP = (204, 28), (204, 106, 108), (204, 105, 103), (204, 204, 158)
ENV = dict(os.environ, MSYS_NO_PATHCONV="1")
# One line a clip from ClipCamera: frames in the clip, frames counted, frames the encoder refused, the clip's bytes, the
# wait from the request to the first frame and from the end to watching again, the gain in hundredths, the exposure,
# and the frames whose exposure the gyroscope's readings covered.
CLIP_LINE = (r"clip frames=(\d+) counted=(\d+) dropped=(\d+) bytes=(\d+) first_ms=(-?\d+) back_ms=(-?\d+) boost=(\d+) "
             r"exposure_ms=(\d+) gyro=(\d+)")


class Check:
    def __init__(self, options: argparse.Namespace) -> None:
        self.o = options
        self.rows: list[tuple[str, str, str]] = []
        self.report = Path(options.report) if options.report else None
        if self.report:
            self.report.mkdir(parents=True, exist_ok=True)
        self.zero = time.monotonic()

    # ------------------------------------------------------------ plumbing
    def adb(self, *args: str, timeout: int = 60) -> bytes:
        return subprocess.run([ADB, "-s", self.o.glasses, *args], capture_output=True, timeout=timeout, env=ENV).stdout

    def sh(self, command: str, timeout: int = 60) -> str:
        return self.adb("shell", command, timeout=timeout).decode("utf-8", "replace")

    @staticmethod
    def keys(codes: tuple[int, ...]) -> str:
        return "; ".join(f"sendevent {TOUCHPAD} 1 {c} 1; sendevent {TOUCHPAD} 0 0 0; sendevent {TOUCHPAD} 1 {c} 0; "
                         f"sendevent {TOUCHPAD} 0 0 0; sleep 0.08" for c in codes)

    def gesture(self, codes: tuple[int, ...]) -> None:
        self.sh(self.keys(codes))

    def stamp(self) -> str:
        return self.sh("date '+%m-%d %H:%M:%S.000'").strip()

    def log(self, since: str) -> list[str]:
        pid = self.sh(f"pidof {PACKAGE}").strip()
        text = self.sh(f'logcat -d -v time -t "{since}" -s DocScanGlassDoc:*', timeout=120)
        mine = re.compile(r"\(\s*" + re.escape(pid) + r"\)") if pid else None
        return [line.split("): ", 1)[-1] for line in text.splitlines() if mine and mine.search(line[:70])]

    def wait_log(self, since: str, pattern: str, seconds: float) -> str | None:
        deadline = time.monotonic() + seconds
        while True:
            for line in self.log(since):
                if re.search(pattern, line):
                    return line
            if time.monotonic() >= deadline:
                return None
            time.sleep(1)

    def wait_saved(self, count: int, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while True:
            if sum("Photo committed locally" in line for line in self.log(self.since)) >= count:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.5)

    def clip_lines(self) -> list[tuple[int, ...]]:
        return [tuple(map(int, found.groups())) for line in self.log(self.since) if (found := re.search(CLIP_LINE, line))]

    def wait_clips(self, count: int, seconds: float) -> list[tuple[int, ...]]:
        deadline = time.monotonic() + seconds
        while True:
            clips = self.clip_lines()
            if len(clips) >= count or time.monotonic() >= deadline:
                return clips
            time.sleep(1)

    def clip_row(self, number: int, clip: tuple[int, ...]) -> None:
        frames, counted, dropped, size, first, back, boost, exposure, gyro = clip
        settle = 15 if exposure > 30 else 6  # the long exposure settles more slowly
        self.row(f"page {number}'s clip is whole: enough frames, none dropped, a gain of at most 5.0, begun within 2 s",
                 frames >= 60 + settle and counted >= 60 and dropped == 0 and boost <= 500 and 0 <= first <= 2000,
                 f"{frames} frames, {counted} counted, {dropped} dropped, {size / 1e6:.1f} MB, first frame after {first} ms, "
                 f"watching again after {back} ms, gain {boost / 100:.2f}, {exposure} ms")
        # No reading inside the exposures would mean the camera's and the gyroscope's clocks differ: every frame
        # would then count as still, silently.
        self.row(f"page {number}: the gyroscope's readings fall inside the frames' exposures", gyro >= frames * 0.9,
                 f"{gyro} of {frames} frames")

    def gathered(self, committed: int) -> None:
        """Each page's clip on the server, and the page's image replaced by what was gathered from it."""
        document = self.db("select max(id) from documents")[0][0]
        started, clips = time.monotonic(), []
        while True:
            clips = self.api(f"/v1/documents/{document}/clips")[1].get("clips", [])
            if (len(clips) >= committed and all(c["status"] in ("done", "failed") for c in clips)) or time.monotonic() - started > 300:
                break
            time.sleep(2)

        def told(c: dict) -> str:
            how = f" ({c['reason']})" if c.get("reason") else f", {c['used']} of {c['total']} frames, level over noise {c['level']}" if c["status"] == "done" else ""
            return f"page {c['page_index'] + 1} {c['status']}{how}, {c['bytes'] / 1e6:.1f} MB"

        self.row("every page's clip reached the server and was gathered", len(clips) >= committed and all(c["status"] == "done" for c in clips),
                 ("; ".join(map(told, clips)) or "no clip on the server") + f"; {time.monotonic() - started:.0f} s after the pages")
        replaced = self.db(f"select count(*) from pages where document_id = {document} and capture_metadata_json like '%\"gathered\"%'")[0][0]
        self.row("each page's image is the one gathered from its clip", replaced >= committed, f"{replaced} of {committed}")

    def lit(self, name: str) -> int:
        from PIL import Image  # noqa: PLC0415
        image = Image.open(io.BytesIO(self.adb("exec-out", "screencap", "-p"))).convert("L")
        if self.report:
            image.save(self.report / f"{len(self.rows):02d}-{name}.png")
        return sum(1 for value in image.tobytes() if value > 24)

    def api(self, path: str) -> tuple[int, dict]:
        request = urllib.request.Request(self.o.server + path, headers={"Authorization": f"Bearer {self.o.key}"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, {}

    def db(self, query: str) -> list[tuple]:
        connection = sqlite3.connect(f"file:{Path(self.o.data) / 'docscan.db'}?mode=ro", uri=True)
        try:
            return connection.execute(query).fetchall()
        finally:
            connection.close()

    def wait_db(self, query: str, accept, seconds: float):
        deadline = time.monotonic() + seconds
        while True:
            rows = self.db(query)
            if accept(rows) or time.monotonic() >= deadline:
                return rows
            time.sleep(1)

    def row(self, name: str, ok: bool | None, detail: str = "") -> bool:
        state = "PASS" if ok else "INFO" if ok is None else "FAIL"
        self.rows.append((name, state, detail))
        print(f"{time.monotonic() - self.zero:6.1f}s {state:4s} {name}: {detail}", flush=True)
        return bool(ok)

    def foreground(self) -> str:
        found = re.search(r"ResumedActivity: ActivityRecord\{\S+ \S+ (\S+)", self.sh("dumpsys activity activities"))
        return found.group(1) if found else ""

    # ------------------------------------------------------------ the route
    def run(self) -> int:
        watcher = None
        try:
            # Before the real app is stopped: its wear detection is what keeps the wear sensor reporting.
            if self.o.paper and not self.wait_worn():
                return 1
            if not self.prepare():
                return 1
            watcher = self.start_watcher()
            if self.o.paper:
                self.sh(f"rm -f /sdcard/Android/data/{PACKAGE}/files/head-motion.bin")  # this run's turning only
                if not self.o.no_reference:
                    self.standard_photo()
                if self.start():
                    self.paper()
            elif self.capture() and self.finish_and_wait():
                self.read_and_exit()
        finally:
            self.sh(f"am force-stop {PACKAGE}")
            if self.report:
                # The app's own record (UseLog, from glassdoc 0.44.19): every gesture, upload and step with its time.
                # The whole file, earlier runs included; scripts/use_log_report.py reads the last reading in it.
                kept = self.adb("exec-out", "cat", f"/sdcard/Android/data/{PACKAGE}/files/use-log.txt", timeout=60)
                if kept:
                    (self.report / "use-log.txt").write_bytes(kept)
            if watcher:
                watcher.terminate()
                subprocess.run([ADB, "disconnect", "127.0.0.1:5555"], capture_output=True, timeout=20)
                self.adb("forward", "--remove", "tcp:5555")
        failed = [name for name, state, _ in self.rows if state == "FAIL"]
        print("-" * 78)
        print(f"{len([r for r in self.rows if r[1] == 'PASS'])} passed, {len(failed)} failed"
              + (": " + "; ".join(failed) if failed else ""))
        return 1 if failed else 0

    def prepare(self) -> bool:
        if self.o.paper:
            self.sh(f"am force-stop {REAL_PACKAGE}")  # see the module docstring
        ok = self.row("these are the glasses", self.sh("getprop ro.serialno").strip() == GLASSES_SERIAL)
        status, settings = self.api("/v1/settings")
        solver = settings.get("providers", {}).get("solver", {}) if status == 200 else {}
        ok &= self.row("the server answering is the stand-in, armed", solver.get("name") == "recorded" and solver.get("ready") is True,
                       json.dumps(solver))
        ok &= self.row("the glasses reach that server", '"status":"ok"' in self.sh(f"curl -s -m 4 {self.o.server}/health"))
        ok &= self.row("the test-only app is installed beside the real one",
                       PACKAGE in self.sh("pm list packages") and "package:dev.rokid.docscanglass.doc\n" in self.sh("pm list packages").replace("\r", ""))
        self.before = {"documents": self.db("select count(*) from documents")[0][0], "sessions": self.db("select count(*) from exam_sessions")[0][0]}
        return ok

    def start_watcher(self):
        environment = dict(os.environ, ROKID_API_KEY=self.o.key, PATH=str(Path(ADB).parent) + os.pathsep + os.environ.get("PATH", ""),
                           PYTHONIOENCODING="utf-8")
        log = open(self.report / "watcher.log", "w", encoding="utf-8") if self.report else subprocess.DEVNULL  # noqa: SIM115
        # The watcher finds the glasses, as at the venue, from the address the server saw their request come from.
        # Through `adb reverse` that address is this PC, so the glasses' own adb TCP port is forwarded to it as well.
        self.adb("forward", "tcp:5555", "tcp:5555")
        return subprocess.Popen([sys.executable, "-X", "utf8", str(Path(__file__).with_name("watch_glasses.py")), "--serial", "auto",
                                 "--expected-serial", GLASSES_SERIAL, "--server", self.o.server, "--package", PACKAGE],
                                env=environment, stdout=log, stderr=subprocess.STDOUT)

    def changed(self, before: bytes, seconds: float = 8.0) -> bytes | None:
        """The screen once it differs from `before`, or None after `seconds`. A gesture written over the phone's relay
        reaches the glasses after up to a few seconds: judged 1.5 s after it was written, a swipe that had turned the
        page was twice reported as having done nothing (2026-11-16)."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            time.sleep(0.7)
            now = self.adb("exec-out", "screencap", "-p")
            if now != before:
                return now
        return None

    def start(self) -> bool:
        self.sh(f"am force-stop {PACKAGE}; input keyevent KEYCODE_WAKEUP; sleep 1")
        self.since = self.stamp()
        options = (f"--es server {self.o.server} --es key {self.o.key} --es capture {self.o.capture} "
                   f"--ei long_above {self.o.long_above}" + (f" --ei clip_frames {self.o.clip_frames}" if self.o.clip_frames else ""))
        self.sh(f"am start -W -n {ACTIVITY} {options} --ez chooser true >/dev/null 2>&1")
        time.sleep(1.5)
        # Once more without the chooser flag. This check's own watcher opens a stopped app's chooser, and a chooser
        # launch onto a running app is rebuilt without its options: on 2026-11-16, with nothing saved from earlier
        # runs, a session started with no server and with stills. Without the flag the options are only applied.
        self.sh(f"am start -W -n {ACTIVITY} {options} >/dev/null 2>&1")
        # This check's watcher is started anew for every run and first acts on the state the run before left on the
        # server, which asks for a dark display (closed, or the chooser gone to sleep). That soft sleep reaches the
        # glasses 0.25 to 1 s after the app was started: once the app's window holds the display it is ignored, before
        # that the display goes dark and the chooser was reported as not drawn (twice on 2026-11-18, after the two
        # runs that ended by leaving the app). At the venue the phone's watcher runs on and has long acted on it.
        self.sh("input keyevent KEYCODE_WAKEUP")
        time.sleep(0.8)
        self.row("the chooser is drawn", self.lit("chooser") > 0)
        self.gesture(DOUBLE_TAP)  # once; a second one would land in a running capture
        started = self.row("one double tap starts the reading", bool(self.wait_log(self.since, "Started local capture session", 8)))
        camera = self.wait_log(self.since, r"capture=(clip|still)", 3) or ""
        return self.row(f"pages are taken as asked: {self.o.capture}", camera.endswith("capture=" + self.o.capture), camera) and started

    def wear_reading(self) -> tuple[str, float] | None:
        """The wear (proximity) sensor's last report: its sensor time and its value, 5 when nothing is near."""
        dump = self.sh("dumpsys sensorservice", timeout=30)
        block = re.search(r"Proximity Sensor Wakeup: last \d+ events\n((?:\s+\d+ \(ts=.*\n)+)", dump)
        last = re.findall(r"\(ts=([\d.]+),[^)]*\) ([\d.]+),", block.group(1))[-1:] if block else []
        return (last[0][0], float(last[0][1])) if last else None

    def wait_worn(self) -> bool:
        """On 2026-11-14 a recording started as soon as the cable was seen and held two minutes of a desk."""
        if not self.o.worn_wait:
            return True
        print(f"----- put the glasses on: the recording starts once they are worn (waiting up to {self.o.worn_wait} s) -----", flush=True)
        deadline, near, before, silent = time.monotonic() + self.o.worn_wait, 0, None, 0
        while time.monotonic() < deadline:
            reading = self.wear_reading()
            fresh = reading is not None and before is not None and reading[0] != before
            near = near + 1 if fresh and reading[1] < 2.5 else 0
            silent = 0 if fresh or before is None else silent + 1
            if silent == 3:  # nobody is listening to the sensor: the real app, whose wear detection does, was stopped
                self.sh(f"input keyevent KEYCODE_WAKEUP; am start -n {REAL_PACKAGE}/.DocScanGlassActivity >/dev/null 2>&1")
            before = reading[0] if reading else None
            if near >= 3:
                return self.row("worn: the wear sensor reports the glasses on a head", True)
            time.sleep(1)
        return self.row("worn: the wear sensor reports the glasses on a head", False,
                        "it stayed 'far' or silent; nothing was recorded")

    def standard_photo(self) -> None:
        """The glasses' own camera on what the wearer is looking at, before the app holds the camera: the reference for light."""
        print("----- look at the page: the glasses' own camera takes one photo first (about 10 s) -----", flush=True)
        before = self.sh("ls /sdcard/DCIM/Camera").split()
        self.sh("input keyevent KEYCODE_WAKEUP; sleep 1; input keyevent KEYCODE_SPRITE_FUNCTION; sleep 9")
        new = sorted(set(self.sh("ls /sdcard/DCIM/Camera").split()) - set(before))
        if not new:
            self.row("worn: the glasses' own camera took the reference photo", False, "no new file")
            return
        raw = self.adb("exec-out", "cat", f"/sdcard/DCIM/Camera/{new[-1]}", timeout=120)
        detail = f"{new[-1]}, {len(raw)} bytes"
        try:
            from PIL import Image  # noqa: PLC0415
            exif = Image.open(io.BytesIO(raw))._getexif() or {}
            detail += f", exposure {float(exif.get(33434, 0)) * 1000:.1f} ms at ISO {exif.get(34855)}"
        except Exception as error:  # noqa: BLE001 - the photo is kept whatever its tags say
            detail += f" (tags unread: {type(error).__name__})"
        if self.report:
            (self.report / "standard-camera.jpg").write_bytes(raw)
        self.row("worn: the glasses' own camera took the reference photo", len(raw) > 100_000, detail)

    def paper(self) -> None:
        print(f"----- worn use: {self.o.paper} s. Read the booklet and turn its pages; do not touch the touchpad. -----", flush=True)
        time.sleep(self.o.paper)
        pid = self.sh(f"pidof {PACKAGE}").strip()  # with the clock times, which log() drops
        text = "\n".join(line for line in self.sh(f'logcat -d -v time -t "{self.since}" -s DocScanGlassDoc:*', timeout=120).splitlines()
                         if pid and re.search(r"\(\s*" + re.escape(pid) + r"\)", line[:70]))
        if self.report:
            (self.report / "paper-log.txt").write_text(text, encoding="utf-8")
        if self.o.capture == "clip":
            self.paper_clips(text)
            return
        photos = re.findall(r"(\d\d:\d\d:\d\d)\.\d+ .*captured \d+x\d+ (\d+)B in (\d+)ms gen=(\d+)", text)
        self.row("worn: photos taken", None, f"{len(photos)} in {self.o.paper} s" + "".join(f"; {at} #{gen}" for at, _, _, gen in photos[:20]))
        self.row("worn: waits for stillness that ran out (10 s each)", None, str(len(re.findall("preparation expired", text))))
        motions = re.findall(r"still_motion gen=(\d+) samples=\d+ covered=\w+ window_ms=(\d+) mean_rad_s=[\d.]+ peak_rad_s=([\d.]+) blur_px=([\d.]+)", text)
        self.row("worn: turning during each photo's own exposure", None,
                 "; ".join(f"#{gen} {peak} rad/s over {window} ms, {blur} px" for gen, window, peak, blur in motions[:20]) or "no photo")
        status = re.findall(r"preview_status .*?metered=true exposure_ns=(\d+) .*?limit_rad_s=([\d.]+) head_1s=\d+ mean_rad_s=[\d.]+ peak_rad_s=([\d.]+) pace=(\d+) gain=(\d+)", text)
        if status:
            # Exposure times gain is what the scene needs, whichever range the preview is in: watching (15 frames a
            # second, a long exposure) or preparing a photo. Said as the gain a 30 ms and a 10 ms exposure would need.
            needs = sorted(int(e) / 1e6 * int(gain) / 30 for e, *_, gain in status if int(e))
            peaks = sorted(float(peak) for _, _, peak, _, _ in status)
            under = sum(1 for _, limit, peak, _, _ in status if float(limit) > 0 and float(peak) <= float(limit))
            self.row("worn: light on what the wearer looks at", None,
                     f"a 30 ms exposure needs a total gain of {needs[len(needs) // 2]:.0f} (median; {needs[0]:.0f}-{needs[-1]:.0f}), "
                     f"a 10 ms one {3 * needs[len(needs) // 2]:.0f}; the still's frame-rate range {sorted({pace for *_, pace, _ in status})}")
            self.row("worn: each second's fastest turning", None,
                     f"median {peaks[len(peaks) // 2]:.3f}, quietest {peaks[0]:.3f}, largest {peaks[-1]:.3f} rad/s; "
                     f"{under} of {len(status)} seconds wholly under the limit then in force ({sorted({limit for _, limit, *_ in status})})")
        self.row("worn: page changes counted", None, str(len(re.findall("page_change scene=", text))))
        new_document = self.db("select count(*) from documents")[0][0] > self.before["documents"]
        pages = self.db("select count(*) from pages where document_id = (select max(id) from documents)")[0][0] if new_document else 0
        self.row("worn: photos that reached the server", None, str(pages))
        trace = self.adb("exec-out", "cat", f"/sdcard/Android/data/{PACKAGE}/files/head-motion.bin", timeout=120)
        if self.report:
            (self.report / "head-motion.bin").write_bytes(trace)
        self.row("worn: head-motion trace", None, f"{len(trace)} bytes ({len(trace) / 20 / 200:.0f} s at 200 Hz)")
        self.row("nothing failed in the app", not re.search(r"capture failed|preview failed|ERROR:", text))

    def paper_clips(self, text: str) -> None:
        clips = [(at, *map(int, rest)) for at, *rest in re.findall(r"(\d\d:\d\d:\d\d)\.\d+ .*" + CLIP_LINE, text)]
        pages = [clip for clip in clips if clip[2] > 0]
        self.row("worn: clips recorded", None, f"{len(clips)} in {self.o.paper} s, {len(pages)} with a page" + "".join(
            f"; {at} {frames} frames, {counted} counted, {exposure} ms at gain {boost / 100:.2f}, first frame after {first} ms, {dropped} dropped"
            for at, frames, counted, dropped, _, first, _, boost, exposure, _ in clips[:24]))
        self.row("worn: clips in which no frame was still enough to count", None, str(len(clips) - len(pages)))
        status = re.findall(r"watch_status frames=(\d+) max_work_ms=(\d+) exposure_ns=(\d+) iso=(\d+) boost=(\d+) far=(\w+)", text)
        if status:
            needs = sorted(int(e) / 1e6 * int(iso) * int(boost) / 100 / 30 for _, _, e, iso, boost, _ in status if int(e))
            far = sum(1 for *_, mark in status if mark == "true")
            self.row("worn: light on what the wearer looks at", None,
                     f"a 30 ms exposure needs a total gain of {needs[len(needs) // 2]:.0f} (median; {needs[0]:.0f}-{needs[-1]:.0f}); "
                     f"the clip has 4000 at most" + (f", and takes 60 ms above {8 * self.o.long_above}" if self.o.long_above else "")
                     if needs else "not measured")
            self.row("worn: seconds of watching with the 'paper too far' mark shown", None, f"{far} of {len(status)}")
            work = max(int(ms) for _, ms, *_ in status)
            self.row("worn: the watch preview's handler kept up", work <= 100, f"{work} ms at most over {len(status)} s")
        self.row("worn: page changes counted", None, str(len(re.findall("page_change scene=", text))))
        new_document = self.db("select count(*) from documents")[0][0] > self.before["documents"]
        if new_document and pages:
            document = self.db("select max(id) from documents")[0][0]
            deadline = time.monotonic() + 240  # the last clips are still on their way and being gathered
            while True:
                rows = self.db(f"select page_index, status, reason, used, total, level, record_json from page_clips where document_id = {document} order by page_index")
                if (len(rows) >= len(pages) and all(row[1] in ("done", "failed") for row in rows)) or time.monotonic() >= deadline:
                    break
                time.sleep(3)
            for index, state, reason, used, total, level, record in rows:
                smears = sorted(frame.get("smear_px", 0) for frame in json.loads(record).get("frames", []))
                moving = f"; smear a frame: median {smears[len(smears) // 2]:.1f} px, over 2 px in {sum(1 for v in smears if v > 2)} of {len(smears)}" if smears else ""
                self.row(f"worn: page {index + 1}'s clip on the server", None,
                         (f"gathered from {used} of {total} frames, level over noise {level}" if state == "done" else f"{state}: {reason}") + moving)
            self.row("worn: clips that became their page's image", None, f"{sum(1 for row in rows if row[1] == 'done')} of {len(pages)} pages")
        else:
            self.row("worn: pages that reached the server", None, "none")
        self.row("nothing failed in the app", not re.search(r"capture failed|clip camera failed|ERROR:", text))

    def capture(self) -> bool:
        if not self.start():
            return False
        clip = self.o.capture == "clip"
        if clip:
            clips = self.wait_clips(1, 40)
            if not self.row("the first page is recorded without any input", bool(clips), "" if clips else "no clip within 40 s; app: "
                            + " | ".join(line[:70] for line in self.log(self.since) if "watch_status" not in line)[-300:]):
                return False
            self.clip_row(1, clips[0])
            page = self.wait_log(self.since, r"captured \d+x\d+ in \d+ ms", 10) or ""
            self.row("the page is one frame of its clip", "captured 2016x1512 " in page, page)
        else:
            first = self.wait_log(self.since, r"captured \d+x\d+ \d+B in \d+ms gen=1", 40)
            if not self.row("the first photo is taken without any input", bool(first), first or "no photo within 40 s"):
                return False
        committed = 1
        self.row("photo 1 is saved after its 3-second review", self.wait_saved(1, 15))
        for number in range(2, self.o.photos + 1):
            self.gesture(SWIPE_FORWARD)
            if clip:
                clips = self.wait_clips(number, 30)
                taken = f"clip {number}" if len(clips) >= number else None
                if taken:
                    self.clip_row(number, clips[number - 1])
            else:
                taken = self.wait_log(self.since, rf"captured \d+x\d+ \d+B in \d+ms gen={number} *$", 25)
            # Counted, not looked for after a clock mark: the mark is cut to the second, and on 2026-11-14 the save of
            # the photo before was taken for this one's, so the next swipe fell in its review and retook it.
            saved = self.wait_saved(number, 14) if taken else False
            committed += 1 if saved else 0
            self.row(f"a forward swipe takes photo {number} and it is saved", bool(saved), (taken or "no photo")[:70])
        stills = len(self.clip_lines()) if clip else len([line for line in self.log(self.since) if "still_requested" in line])
        self.row("clips recorded so far" if clip else "stills requested so far", None, f"{stills} for {committed} saved photo(s)")
        pages = self.wait_db("select count(*) from pages where document_id = (select max(id) from documents)",
                             lambda rows: rows and rows[0][0] >= committed, 60)
        new_document = self.db("select count(*) from documents")[0][0] > self.before["documents"]
        self.committed = committed
        reached = self.row("every saved photo reached the server, in one new document", new_document and pages[0][0] >= committed,
                           f"{pages[0][0]} page(s) on the server for {committed} saved")
        if reached and clip:
            self.gathered(committed)
        return reached

    def finish_and_wait(self) -> bool:
        status, settings = self.api("/v1/settings")
        safe = (status == 200 and settings["providers"]["solver"].get("name") == "recorded" and self.foreground().startswith(PACKAGE + "/")
                and self.db("select count(*) from documents")[0][0] > self.before["documents"])
        if not self.row("ending is safe: the test app is in front and its pages are on the stand-in server", safe, self.foreground()):
            return False
        mark = self.stamp()
        self.gesture(DOUBLE_TAP)
        time.sleep(4)
        self.row("screen after the ending double tap", None, f"{self.lit('after-end')} lit pixels; "
                 + " | ".join(line[:60] for line in self.log(mark) if "preview_status" not in line and "page_change" not in line)[-3:][0:200])
        session = self.wait_db("select id, status, document_id from exam_sessions order by id desc limit 1",
                               lambda rows: rows and self.db("select count(*) from exam_sessions")[0][0] > self.before["sessions"], 90)
        if not self.row("ending the capture creates the analysis session on the server",
                        bool(session) and self.db("select count(*) from exam_sessions")[0][0] > self.before["sessions"],
                        f"session {session[0] if session else None}; app: "
                        + " | ".join(line[:70] for line in self.log(mark) if re.search("finish|Finish|analysis|REVIEW|ERROR|解析", line))[:260]):
            return False
        self.session = session[0][0]
        pages = self.db(f"select page_index from pages where document_id = {session[0][2]} order by page_index")
        self.row("the document's pages are complete and in order", [p[0] for p in pages] == list(range(len(pages))) and len(pages) >= self.committed,
                 f"indexes {[p[0] for p in pages]}")
        self.row("the answers are not there before the stand-in has answered", self.api(f"/v1/exam-sessions/{self.session}/answer-bundle")[0] == 409)
        if self.o.interrupt == "wait":
            # What folding the temple arms does while the answers are being made: the system force-stops the app.
            # Putting the glasses back on brings the chooser up through the watcher's launch, reproduced here.
            self.sh(f"am force-stop {PACKAGE}")
            time.sleep(3)
            self.sh(f"am start -W -n {ACTIVITY} --ez chooser true --ez wear_bootstrap true >/dev/null 2>&1")
            time.sleep(2)
            self.row("interrupted during the wait: app force-stopped and the chooser reopened", None, f"{self.lit('chooser-after-kill')} lit pixels")
        time.sleep(8)
        asleep = "mWakefulness=Asleep" in self.sh("dumpsys power")
        self.row("the display goes off while waiting", asleep and self.lit("waiting") == 0, f"asleep={asleep}")
        deadline = time.monotonic() + 150
        ready_at = None
        while time.monotonic() < deadline and ready_at is None:
            if self.api(f"/v1/exam-sessions/{self.session}/answer-bundle")[0] == 200:
                ready_at = time.monotonic()
            else:
                time.sleep(2)
        if not self.row("the stand-in's answers become a bundle on the server", ready_at is not None):
            return False
        self.ready_at, self.ready_stamp = ready_at, mark
        if self.o.capture == "clip":
            items = self.api(f"/v1/exam-sessions/{self.session}/answer-bundle")[1].get("items", [])
            # The notices of the reads (照合中 while the second read runs, 照合なし after one read) stand in the same
            # group and are no page left ungathered: counted as one on 2026-11-18, with the two-read stand-in.
            named = [str(item.get("question_label")) for item in items if item.get("group_id") == "pages"
                     and item.get("question_id") not in ("read-comparing", "read-once")]
            self.row("the answers name no page as left ungathered", not named, ", ".join(named))
        first = self.api(f"/v1/exam-sessions/{self.session}/answer-bundle")[1]
        self.comparing = any(item.get("question_id") == "read-comparing" for item in first.get("items", []))
        self.first_revision = first.get("revision")
        return True

    def read_and_exit(self) -> None:
        shown = None
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and shown is None:
            if "mWakefulness=Awake" in self.sh("dumpsys power") and self.lit("answers") > 0:
                shown = time.monotonic()
            else:
                time.sleep(1)
        self.row("the glasses wake and show the answers by themselves", shown is not None,
                 f"{shown - self.ready_at:.1f} s after the bundle was ready" if shown else "not within 45 s; app: "
                 + " | ".join(line[:70] for line in self.log(self.ready_stamp) if "preview_status" not in line)[-240:])
        if shown is None or self.o.interrupt:
            if self.o.interrupt:
                self.sh("input keyevent KEYCODE_WAKEUP")
                time.sleep(2)
                self.row("what the wearer finds after the interruption", None, f"{self.lit('after-interruption')} lit pixels; state "
                         + json.dumps({k: v for k, v in (self.api('/v1/glasses/state')[1] or {}).items() if k in ('devices',)})[:200])
            return
        first = self.adb("exec-out", "screencap", "-p")
        self.gesture(SWIPE_FORWARD)
        second = self.changed(first)
        self.lit("answers-next")
        self.row("a forward swipe moves on through the answers", second is not None)
        self.gesture(SWIPE_BACK)
        self.row("a back swipe returns", second is not None and self.changed(second) is not None)
        self.gesture(TAP)
        time.sleep(1.5)
        self.row("a tap hides the answers", self.lit("answers-hidden") == 0)
        self.gesture(TAP)
        time.sleep(1.5)
        self.row("the next gesture brings them back", self.lit("answers-back") > 0)
        time.sleep(7)
        self.row("the answers stay on screen while reading (no idle sleep)", "mWakefulness=Awake" in self.sh("dumpsys power") and self.lit("answers-held") > 0)
        if getattr(self, "comparing", False):
            # The stand-in stood for two reads (ROKID_RECORDED_REPLY_2): the compared answers follow the first read's
            # while the wearer reads. The reader has to take them where it stands.
            deadline, later = time.monotonic() + 60, {}
            while time.monotonic() < deadline:
                later = self.api(f"/v1/exam-sessions/{self.session}/answer-bundle")[1]
                if not any(item.get("question_id") == "read-comparing" for item in later.get("items", [])):
                    break
                time.sleep(2)
            time.sleep(8)  # the watcher's notice and the glasses' load
            gone = not any(item.get("question_id") == "read-comparing" for item in later.get("items", []))
            self.row("the compared answers follow the first read's under a newer revision", gone
                     and later.get("revision") != self.first_revision,
                     f"revision {self.first_revision} then {later.get('revision')}")
            devices = (self.api("/v1/glasses/state")[1] or {}).get("devices") or []
            acknowledged = [device.get("ack_answer_revision") for device in devices if device.get("session_id") == self.session]
            self.row("the glasses took them while reading: acknowledged, still awake and showing answers",
                     bool(acknowledged) and acknowledged[0] == later.get("revision")
                     and "mWakefulness=Awake" in self.sh("dumpsys power") and self.lit("answers-updated") > 0,
                     f"acknowledged {acknowledged}")
        state = self.db("select count(*) from exam_sessions")[0][0]
        mark = self.stamp()
        self.gesture(DOUBLE_TAP)
        time.sleep(6)
        self.row("a double tap in the reader ends the writing and the display goes off",
                 self.lit("writing-done") == 0, " | ".join(line[:70] for line in self.log(mark) if "preview_status" not in line)[-200:])
        # One command: sent as two over the phone relay they reached the glasses 4.5 s apart on 2026-11-16, past the
        # three seconds the app allows, and a correct app stayed in front.
        self.sh(self.keys(DOUBLE_TAP) + "; sleep 0.6; " + self.keys(DOUBLE_TAP))
        time.sleep(4)
        self.row("two more double taps within three seconds leave the app", not self.foreground().startswith(PACKAGE + "/"), self.foreground())
        self.row("no further session was created by reading and leaving", self.db("select count(*) from exam_sessions")[0][0] == state)
        guard = Path(self.o.data) / "browser-state"
        self.row("nothing was sent to the model", not guard.exists() or not any(guard.iterdir()),
                 "no browser send record in the server's data directory")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--glasses", required=True)
    parser.add_argument("--data", required=True, help="the stand-in server's data directory on this PC")
    parser.add_argument("--key", required=True, help="the stand-in server's API key (a test value, not the phone's)")
    parser.add_argument("--server", default="http://127.0.0.1:8765")
    parser.add_argument("--photos", type=int, default=3)
    parser.add_argument("--capture", choices=["still", "clip"], default="still",
                        help="how a page is taken; saved by the test app on every start")
    parser.add_argument("--long-above", type=int, default=0,
                        help="with --capture clip: the gain in hundredths that 30 ms may need before 60 ms is taken; 0: never")
    parser.add_argument("--clip-frames", type=int, default=0,
                        help="with --capture clip: still frames a clip gathers before it ends (60 to 250), this launch only; "
                             "250 makes the ten-second clips of about 140 MB a worn head makes")
    parser.add_argument("--interrupt", choices=["wait"], help="force-stop the app (what a fold does) at this point and reopen the chooser")
    parser.add_argument("--paper", type=int, default=0, help="seconds of worn reading to record; the capture is not ended")
    parser.add_argument("--worn-wait", type=int, default=240, help="with --paper: seconds to wait for the wear sensor; 0 records at once (a desk dry run)")
    parser.add_argument("--no-reference", action="store_true",
                        help="with --paper: take no photo with the glasses' own camera (it goes to their gallery)")
    parser.add_argument("--report")
    return Check(parser.parse_args()).run()


if __name__ == "__main__":
    raise SystemExit(main())
