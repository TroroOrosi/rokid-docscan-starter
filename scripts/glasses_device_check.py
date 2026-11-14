"""Check the glasses app on the connected device, step by step, with nobody touching it.

Run this after every change to the glasses app and before the wearer is asked to
try anything. The unit tests use a fake camera and a fake display; between
2026-11-01 and 2026-11-12 they hid a frame handler 300 times slower on the device,
a still the firmware never returned, a page photographed again and again, and a
photo too dark to read. Every step here is one of those, or something the
wearer reported.

    py -3.12 scripts/glasses_device_check.py --glasses 1904092623381086 --phone 192.168.0.5:36641

It drives the app over adb exactly as the temple touchpad does (tap, swipe,
double tap), reads the app's own log and the screen, and with --phone pulls the
photos that reached the phone server. It prints one line per check and ends with
a table. Exit code 0 only when nothing failed.

It never ends a capture, so nothing is sent to GPT. The double tap is sent only
on the chooser, where it starts a session. Photos it takes stay on the phone
server as pages of a new document.

With --paper SECONDS it then waits that long while the wearer, doing nothing but
turning pages, reads a real booklet, and reports every photo taken: when, why the
page was counted as turned, how bright it is, and which photos are the same page
twice. --report DIR keeps the photos and the screens.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

PACKAGE = "dev.rokid.docscanglass.doc"
GLASSES_SERIAL = "1904092623381086"
# The firmware every measurement in docs/hardware-measurements.md section M was taken on.
MEASURED_FIRMWARE = "1.29.013-20261110-150201"
# Gestures are the key codes the touchpad itself sends, written to its own input device: a touch on a sleeping
# display is consumed by the wake and never reaches the app, which injected keys (`input keyevent`) do not reproduce.
TOUCHPAD = "/dev/input/event1"
TAP, SWIPE_FORWARD, SWIPE_BACK, DOUBLE_TAP = (204, 28), (204, 106, 108), (204, 105, 103), (204, 204, 158)
PHONE_IMAGES = "/data/data/com.termux/files/home/rokid-server/data/images"
STANDARD_PHOTOS = "/sdcard/DCIM/Camera"  # where the glasses' own camera (the physical photo key) saves


class Check:
    def __init__(self, options: argparse.Namespace) -> None:
        self.options = options
        self.adb = shutil.which("adb") or os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe")
        self.rows: list[tuple[str, str, str]] = []
        self.started = ""
        self.phone_serialno = ""
        self.report = Path(options.report) if options.report else None
        if self.report:
            self.report.mkdir(parents=True, exist_ok=True)

    def run(self, serial: str, *arguments: str, timeout: int = 60) -> bytes:
        environment = dict(os.environ, MSYS_NO_PATHCONV="1")
        return subprocess.run([self.adb, "-s", serial, *arguments], capture_output=True, timeout=timeout,
                              env=environment).stdout

    def shell(self, command: str, timeout: int = 60) -> str:
        return self.run(self.options.glasses, "shell", command, timeout=timeout).decode("utf-8", "replace")

    def row(self, name: str, state: str, detail: str = "") -> bool:
        self.rows.append((name, state, detail))
        print(f"{state:5s} {name}: {detail}", flush=True)
        return state == "PASS"

    def expect(self, name: str, ok: bool, detail: str = "") -> bool:
        return self.row(name, "PASS" if ok else "FAIL", detail)

    def log(self) -> str:
        for _ in range(3):  # a read through the phone relay came back empty once
            text = self.shell(f'logcat -d -v time -t "{self.started}" -s DocScanGlassDoc:*')
            if text.strip():
                return text
            time.sleep(1)
        return ""

    def wait(self, pattern: str, seconds: float, after: int = 0) -> re.Match[str] | None:
        deadline = time.monotonic() + seconds
        while True:
            match = re.search(pattern, self.log()[after:])
            if match or time.monotonic() >= deadline:
                return match
            time.sleep(1)

    def phone_again(self) -> bool:
        """Wireless adb gives the phone a new port whenever its Wi-Fi reconnects: find the same phone again."""
        for _ in range(5):
            listed = subprocess.run([self.adb, "devices"], capture_output=True, text=True, timeout=30).stdout
            for transport in [self.options.phone] + re.findall(r"^(\S+)\s+device$", listed, re.M):
                if (transport != self.options.glasses and self.phone_serialno
                        and self.run(transport, "shell", "getprop ro.serialno").decode().strip() == self.phone_serialno):
                    self.options.phone = transport
                    return True
            time.sleep(3)
        return False

    def keys(self, sequence: str | tuple[int, ...]) -> None:
        if isinstance(sequence, str):  # system keys only: wake, and the glasses' own camera
            self.shell(f"input keyevent {sequence}")
            return
        self.shell("; ".join(f"sendevent {TOUCHPAD} 1 {code} 1; sendevent {TOUCHPAD} 0 0 0; sendevent {TOUCHPAD} 1 {code} 0; "
                             f"sendevent {TOUCHPAD} 0 0 0; sleep 0.08" for code in sequence))

    def chosen(self, name: str) -> int | None:
        """Which line of the chooser the marker is on, read from the screen: the marker is all that is lit left of the text."""
        image = self.screen(name)
        text = image.getbbox()
        if not text:
            return None
        line = (text[3] - text[1]) / 7  # six choices, then the hint line, which starts at the left edge too
        marker = image.crop((0, 0, 30, round(text[1] + 6 * line))).getbbox()
        return None if not marker else round(((marker[1] + marker[3]) / 2 - text[1]) / line - 0.5)

    def screen(self, name: str):
        from PIL import Image  # noqa: PLC0415
        image = Image.open(io.BytesIO(self.run(self.options.glasses, "exec-out", "screencap", "-p"))).convert("RGB")
        if self.report:
            image.save(self.report / f"screen-{name}.png")
        return image

    @staticmethod
    def flat(gray, patches=None):
        """(level, noise, patches) over the flattest mid-bright 64 px squares; given patches are read in place."""
        from PIL import ImageStat  # noqa: PLC0415
        if patches is None:
            found = []
            for top in range(0, gray.height - 64, 96):
                for left in range(0, gray.width - 64, 96):
                    stat = ImageStat.Stat(gray.crop((left, top, left + 64, top + 64)))
                    if 70 <= stat.mean[0] <= 190:
                        found.append((stat.stddev[0], left, top))
            patches = [(left, top) for _, left, top in sorted(found)[:40]]
        if len(patches) < 10:
            return 0.0, 0.0, patches
        stats = [ImageStat.Stat(gray.crop((left, top, left + 64, top + 64))) for left, top in patches]
        noises = sorted(stat.stddev[0] for stat in stats)
        return sum(stat.mean[0] for stat in stats) / len(stats), noises[len(noises) // 2], patches

    def reference(self) -> None:
        """One photo of the same scene with the glasses' own camera, taken before the app holds the camera.

        The physical photo key over adb; the vendor capture plays its sound and leaves its file in the glasses'
        gallery. On 2026-11-13 a still this check had passed as bright enough was colour noise beside that photo
        (level over noise 1.9 against 39.7), so every app photo is now read at the same places as the reference.
        A worn head does not hold one scene, so --paper takes no reference.
        """
        self.standard = None
        if self.options.paper:
            return
        from PIL import Image  # noqa: PLC0415
        before = set(self.shell(f"ls {STANDARD_PHOTOS}").split())
        self.keys("KEYCODE_WAKEUP")
        time.sleep(2)
        self.keys("KEYCODE_SPRITE_FUNCTION")
        name, deadline = None, time.monotonic() + 20
        while name is None and time.monotonic() < deadline:
            time.sleep(2)
            new = sorted(n for n in self.shell(f"ls {STANDARD_PHOTOS}").split() if n.endswith(".jpg") and n not in before)
            name = new[-1] if new else None
        gray = None
        for _ in range(3):  # the file is listed before the vendor has finished writing it
            time.sleep(2)
            data = self.run(self.options.glasses, "exec-out", f"cat {STANDARD_PHOTOS}/{name}", timeout=120) if name else b""
            try:
                image = Image.open(io.BytesIO(data))
                gray = image.convert("L")
                break
            except OSError:
                continue
        if gray is None:
            self.row("the glasses' own camera photographed the scene", "WARN", "no photo from the photo key; app photos are not compared")
            return
        level, noise, patches = self.flat(gray)
        details = image.getexif().get_ifd(0x8769)
        exposure = details.get(0x829A)
        if not noise:
            self.row("the glasses' own camera photographed the scene", "WARN", "no flat mid-bright area to compare at")
            return
        self.standard = (gray.size, patches, level / noise)
        if self.report:
            (self.report / "standard-camera.jpg").write_bytes(data)
        self.row("the glasses' own camera photographed the scene", "PASS",
                 f"{float(exposure) * 1000:.0f} ms, sensitivity {details.get(0x8827)}, level {level:.0f} over noise {noise:.2f}"
                 if exposure else f"level {level:.0f} over noise {noise:.2f}")

    def photos(self) -> list[tuple[str, int, int]]:
        """(sensor log line time, bytes, generation) of every photo since the start."""
        return [(m.group(1), int(m.group(2)), int(m.group(3))) for m in re.finditer(
            r"(\d\d:\d\d:\d\d\.\d+) I/DocScanGlassDoc.*captured \d+x\d+ (\d+)B in \d+ms gen=(\d+)", self.log())]

    # ------------------------------------------------------------------ steps

    def environment(self) -> bool:
        if self.shell("getprop ro.serialno").strip() != self.options.expect_serialno:
            return self.expect("glasses identity", False, "this transport is not the expected glasses")
        firmware = self.shell("getprop ro.build.fingerprint").strip()
        self.row("firmware", "PASS" if MEASURED_FIRMWARE in firmware else "WARN",
                 firmware if MEASURED_FIRMWARE in firmware else
                 f"{firmware}: not the measured {MEASURED_FIRMWARE}; re-run the glassprobe camera variants first")
        if not self.expect("temple arms open", self.shell("getprop vendor.rkd.glasses.is_spread").strip() == "1",
                           "the system stops the app while they are folded"):
            return False
        package = self.shell(f"dumpsys package {PACKAGE}")
        version = re.search(r"versionName=(\S+)", package)
        compiled = re.search(r"status=(\w+)", package)
        self.expect("app installed", bool(version), version.group(1) if version else "missing")
        self.expect("app compiled", bool(compiled) and compiled.group(1) == "speed",
                    (compiled.group(1) if compiled else "unknown")
                    + "; run `cmd package compile -m speed -f` after each install")
        self.expect("camera permission", "android.permission.CAMERA: granted=true" in package)
        level = re.search(r"level: (\d+)", self.shell("dumpsys battery"))
        self.row("battery", "PASS" if level and int(level.group(1)) >= 20 else "WARN", f"{level.group(1) if level else '?'}%")
        if self.options.phone:
            phone = self.phone_serialno = self.run(self.options.phone, "shell", "getprop ro.serialno").decode().strip()
            health = self.run(self.options.phone, "shell",
                              "run-as com.termux /data/data/com.termux/files/usr/bin/curl -s -m 5 "
                              "http://127.0.0.1:8000/health").decode("utf-8", "replace")
            server = re.search(r'"app_version":"([^"]+)"', health)
            self.expect("phone server", bool(server), f"{phone} server {server.group(1) if server else 'no answer'}")
        return True

    def chooser(self) -> bool:
        self.started = self.shell('date "+%m-%d %H:%M:%S.000"').strip()
        self.shell(f"am force-stop {PACKAGE}; input keyevent KEYCODE_WAKEUP; sleep 1; "
                   f"am start -n {PACKAGE}/.DocScanGlassActivity >/dev/null 2>&1")
        if not self.expect("chooser opens", bool(self.wait(r"phase=chooser request=wake", 8))):
            return False
        time.sleep(1)
        self.expect("chooser is drawn", self.screen("chooser").getbbox() is not None)
        mark = len(self.log())
        self.keys(TAP)
        asleep = self.wait(r"phase=chooser request=sleep", 3, mark)
        self.expect("tap turns the chooser's display off", bool(asleep), "no sleep request within 3 s" if not asleep else "")
        time.sleep(1)
        self.expect("the chooser is cleared at once", self.screen("chooser-off").getbbox() is None)
        asleep_at = None
        for second in range(1, 11):  # the system sleep comes through the phone watcher
            if "mWakefulness=Asleep" in self.shell("dumpsys power"):  # read whole: see the camera dump below
                asleep_at = second
                break
            time.sleep(1)
        self.row("the system display sleeps after the tap", "PASS" if asleep_at else "WARN",
                 f"about {asleep_at} s after the tap" if asleep_at else "not within 10 s; the phone watcher did not act")
        self.expect("the tap started no session", "Started local capture session" not in self.log())
        mark = len(self.log())
        # The touch that wakes a sleeping display is consumed by the wake: the app is only resumed. Until 2026-11-14
        # this step injected a wake key and then a swipe, which since 0.43.17 is a second gesture: it moved the
        # choice to mixed English, and the "tap pauses" line below failed on a correct app.
        self.keys(SWIPE_FORWARD)
        self.expect("the gesture after a display-off only turns it back on", bool(self.wait(r"phase=chooser request=wake", 4, mark)))
        self.expect("that gesture started no session", "Started local capture session" not in self.log())
        time.sleep(2)  # the activity must be resumed before the next gesture reaches it
        self.expect("the display is on again", "mWakefulness=Awake" in self.shell("dumpsys power"))
        # The chooser opens on the kind of reading used last. On 2026-11-14 a run left mixed English chosen, where a
        # tap takes a photo, and "tap pauses" failed on a correct app. Read the marker as the wearer does and go back.
        chosen = self.chosen("chooser-before-start")
        for _ in range(chosen or 0):
            self.keys(SWIPE_BACK)
            time.sleep(0.6)
        self.expect("the ordinary reading is the one selected", self.chosen("chooser-selected") == 0,
                    f"the marker was on line {chosen}" if chosen else "")
        self.keys(DOUBLE_TAP)  # safe here only: on the chooser the double tap starts, it never ends a capture
        return self.expect("double tap starts the selected reading", bool(self.wait(r"Started local capture session", 8)))

    def capture(self) -> bool:
        first = self.wait(r"captured (\d+)x(\d+) (\d+)B in (\d+)ms", 30)
        if not self.expect("first photo is taken automatically", bool(first),
                           f"{first.group(1)}x{first.group(2)}, {first.group(3)} bytes, {first.group(4)} ms from the request"
                           if first else "none in 30 s"):
            for line in self.log().splitlines()[-6:]:
                print("      " + line[:200])
            return False
        self.expect("it is full size", int(first.group(1)) >= 4000)
        self.screen("review")
        self.expect("it is saved after the 3-second review", bool(self.wait(r"Photo committed locally", 12)))
        log = self.log()
        preview = re.findall(r"metered=true exposure_ns=(\d+)", log[:log.find("still_requested")])
        still = re.search(r"capture_result gen=1 .*?exposure_ns=(\d+) iso=(\d+)", log)
        if preview and still:
            ratio = int(still.group(1)) / max(1, int(preview[-1]))
            self.row("still exposure against the preview's", "INFO",
                     f"preview {int(preview[-1]) / 1e6:.1f} ms, still {int(still.group(1)) / 1e6:.1f} ms at ISO {still.group(2)} "
                     f"(ratio {ratio:.2f}; sensitivity may carry the rest)")
        motion = re.search(r"still_motion gen=1 samples=(\d+) covered=(\w+) window_ms=(\d+) mean_rad_s=([\d.]+) peak_rad_s=([\d.]+) blur_px=([\d.]+)", log)
        self.expect("the head's turning during the photo's own exposure is recorded", bool(motion) and int(motion.group(1)) >= 2,
                    f"{motion.group(1)} readings over {motion.group(3)} ms, peak {motion.group(5)} rad/s, about {motion.group(6)} px of smear"
                    if motion else "no still_motion line")
        light = re.findall(r"preview_status .*?exposure_ns=(\d+) .*?pace=(\d+) gain=(\d+)", log)
        if light:
            need = int(light[-1][0]) / 1e6 * int(light[-1][2]) / 30  # the same whichever range the preview is in
            self.row("light as the preview measures it", "INFO", f"a 30 ms exposure needs a total gain of {need:.0f}; the still's "
                     f"frame-rate range is {light[-1][1] or 'default'} (60 ms never held on a worn head; 30 ms is the longest asked)")
        time.sleep(self.options.watch)
        log = self.log()
        photos = self.photos()
        causes = re.findall(r"page_change scene=(\d+) (cause=\w+ level_shift=-?\d+ cells_over_percent=\d+)", log)
        self.expect(f"an unmoving scene adds no photo in {self.options.watch} s", len(photos) <= 2,
                    f"{len(photos)} photo(s); page changes counted: " + ("; ".join(f"{n} {c}" for n, c in causes[-4:]) or "none"))
        work = [int(value) for value in re.findall(r"max_work_ms=(\d+)", log)][1:]
        self.expect("the preview handler keeps up", bool(work) and max(work) <= 100,
                    f"{max(work) if work else '?'} ms at most over {len(work)} s")
        box = self.screen("waiting").getbbox()
        width, height = 480, 640
        self.expect("the live image stays in its lower-right corner",
                    box is None or (box[0] >= width * 0.6 and box[1] >= height * 0.4), f"lit area {box}")
        return True

    def pause(self) -> None:
        before = len(self.photos())
        mark = len(self.log())
        self.keys(TAP)
        if not self.expect("tap pauses the capture", bool(self.wait(r"Capture paused by the wearer", 8, mark))):
            return
        time.sleep(1)
        # The dump is read whole here and never piped on the device: on 2026-11-13 `dumpsys media.camera | grep -m1`
        # closed the pipe early while the camera was streaming, the camera provider died of SIGPIPE and the app
        # ended in its camera-state-unknown error. Only asked once the app says the capture is paused.
        dump = self.shell("dumpsys media.camera")
        clients = dump.split("Active Camera Clients:", 1)[1].split("\n", 2)[1] if "Active Camera Clients:" in dump else ""
        self.expect("the camera is closed during the pause", "[]" in clients)
        self.expect("nothing is drawn during the pause", self.screen("paused").getbbox() is None)
        self.keys(SWIPE_FORWARD)
        time.sleep(3)
        self.expect("a swipe during the pause takes no photo", len(self.photos()) == before)
        mark = len(self.log())
        self.keys(TAP)
        self.expect("tap resumes", bool(self.wait(r"Capture resumed by the wearer", 5, mark)))
        time.sleep(6)
        self.expect("the same page is not taken again on return", len(self.photos()) == before, f"{len(self.photos())} photo(s)")
        self.keys(SWIPE_FORWARD)
        taken = self.wait(rf"captured \d+x\d+ \d+B in \d+ms gen={before + 1}", 12)
        self.expect("forward swipe takes a photo", bool(taken))
        self.wait(r"Photo committed locally", 8, len(self.log()) - 200)
        time.sleep(4)

    def paper(self) -> None:
        before = len(self.photos())
        print(f"----- real paper: {self.options.paper} s. Wear the glasses and turn pages; touch nothing. -----", flush=True)
        end = time.monotonic() + self.options.paper
        shot = 0
        while time.monotonic() < end:
            time.sleep(2)
            if self.report and shot < 40:
                self.screen(f"paper-{shot:02d}")
                shot += 1
        log = self.log()
        photos = self.photos()[before:]
        causes = re.findall(r"(\d\d:\d\d:\d\d)\.\d+ I/DocScanGlassDoc.*page_change scene=(\d+) (cause=\w+ level_shift=-?\d+ cells_over_percent=\d+)", log)
        self.row("real paper: photos taken", "INFO", f"{len(photos)} in {self.options.paper} s at " + ", ".join(p[0][:8] for p in photos))
        self.row("real paper: page changes counted", "INFO", "; ".join(f"{t} #{n} {c}" for t, n, c in causes[-12:]) or "none")
        motions = re.findall(r"still_motion gen=(\d+) samples=\d+ covered=\w+ window_ms=\d+ mean_rad_s=[\d.]+ peak_rad_s=([\d.]+) blur_px=([\d.]+)", log)
        self.row("real paper: head turning during each photo's exposure", "INFO",
                 "; ".join(f"#{g} peak {peak} rad/s, {blur} px" for g, peak, blur in motions[-12:]) or "no photo")
        light = re.findall(r"preview_status .*?exposure_ns=(\d+) .*?peak_rad_s=([\d.]+) pace=(\d+) gain=(\d+)", log)
        if light:
            needs = sorted(int(e) / 1e6 * int(g) / 30 for e, *_, g in light if int(e))
            peaks = sorted(float(peak) for _, peak, *_ in light)
            self.row("real paper: light and head, second by second", "INFO",
                     f"a 30 ms exposure needs a total gain of {needs[len(needs) // 2]:.0f} (median; {needs[0]:.0f}-{needs[-1]:.0f}), "
                     f"the still's frame-rate ranges {sorted({pace for _, _, pace, _ in light})}; each second's fastest turning: "
                     f"median {peaks[len(peaks) // 2]:.3f}, quietest {peaks[0]:.3f}, largest {peaks[-1]:.3f} rad/s over {len(peaks)} s")
        if self.report:
            trace = self.run(self.options.glasses, "exec-out", "cat", f"/sdcard/Android/data/{PACKAGE}/files/head-motion.bin", timeout=120)
            (self.report / "head-motion.bin").write_bytes(trace)
            self.row("real paper: head-motion trace kept", "INFO", f"{len(trace)} bytes; read it with scripts/head_motion_report.py")
        self.expect("real paper: nothing failed", not re.search(r"capture failed|preview failed|ERROR:", log))

    def server(self) -> None:
        if not self.options.phone:
            return
        if not self.phone_again():
            self.row("phone server checks", "WARN", "the phone is not reachable over adb now; whether the photos arrived was not checked")
            return
        from PIL import Image, ImageStat  # noqa: PLC0415
        photos = self.photos()
        arrived: dict[int, str] = {}
        missing = [size for _, size, _ in photos]
        for _ in range(10):  # an upload of several megabytes over the hotspot takes a few seconds
            listing = self.run(self.options.phone, "shell",
                               f"run-as com.termux sh -c 'ls -lt {PHONE_IMAGES}/*.jpg | head -{max(1, len(photos))}'").decode()
            arrived = {int(m.group(1)): m.group(2) for m in re.finditer(r"\s(\d{5,})\s+\d{4}-\d\d-\d\d \d\d:\d\d (\S+\.jpg)", listing)}
            missing = [size for _, size, _ in photos if size not in arrived]
            if not missing:
                break
            time.sleep(3)
        self.expect("every photo reached the phone server", not missing, f"{len(photos) - len(missing)} of {len(photos)} arrived")
        hashes: list[tuple[str, int]] = []
        for index, (stamp, size, generation) in enumerate(photos):
            if size not in arrived:
                continue
            data = self.run(self.options.phone, "exec-out", f"run-as com.termux cat {arrived[size]}", timeout=120)
            if len(data) != size:
                self.expect(f"photo {index + 1} can be read back", False, f"{len(data)} of {size} bytes")
                continue
            image = Image.open(io.BytesIO(data))
            gray = image.convert("L").resize((252, 189))
            levels = sorted(gray.tobytes())
            bright = sum(levels[len(levels) * 3 // 4:]) / (len(levels) / 4)
            small = gray.resize((9, 8))
            pixels = small.tobytes()
            code = sum(1 << i for i in range(64) if pixels[i // 8 * 9 + i % 8] > pixels[i // 8 * 9 + i % 8 + 1])
            same = [n for n, (_, other) in enumerate(hashes, 1) if bin(code ^ other).count("1") <= 6]
            hashes.append((stamp, code))
            # On the glasses a page at 40 could not be read and one at 116 could (2026-11-12); between, the scene is dim.
            state = "PASS" if bright >= 90 else "WARN" if bright >= 50 else "FAIL"
            self.row(f"photo {index + 1} ({stamp[:8]}) is bright enough to read", state,
                     f"brightest quarter {bright:.0f} of 255, mean {ImageStat.Stat(gray).mean[0]:.0f}"
                     + (f"; looks like photo {same[0]} again" if same else ""))
            if self.report:
                (self.report / f"photo-{index + 1:02d}.jpg").write_bytes(data)
            standard = getattr(self, "standard", None)
            if standard:
                upright = image.convert("L")
                if upright.width > upright.height:
                    upright = upright.rotate(-270, expand=True)  # sensor orientation, as the upload is turned
                if upright.size != standard[0]:
                    self.row(f"photo {index + 1} is as clean as the glasses' own camera's", "WARN",
                             f"{upright.size} against {standard[0]}: not compared")
                    continue
                level, noise, _ = self.flat(upright, standard[1])
                ratio = level / noise / standard[2] if noise else 0.0
                # One dim desk scene, 2026-11-13: a 30 ms auto-exposure still read 0.65-0.85 of the reference and
                # was legible, a 10 ms one 0.23 and was not, the manual one-period rule 0.05. Provisional bounds.
                self.row(f"photo {index + 1} is as clean as the glasses' own camera's",
                         "PASS" if ratio >= 0.6 else "WARN" if ratio >= 0.3 else "FAIL",
                         f"level over noise {level / noise if noise else 0:.1f} against {standard[2]:.1f} at the same places")

    def main(self) -> int:
        try:
            if self.environment():
                self.reference()
                if self.chooser() and self.capture():
                    if self.options.paper:
                        self.paper()
                    else:
                        self.pause()
                    self.server()
        finally:
            self.shell(f"am force-stop {PACKAGE}")  # never the double tap: ending a capture sends it to GPT
        failed = [name for name, state, _ in self.rows if state == "FAIL"]
        print("\n" + "-" * 72)
        for name, state, detail in self.rows:
            print(f"{state:5s} {name}" + (f" -- {detail}" if state != "PASS" and detail else ""))
        print("-" * 72)
        print(f"{len(self.rows) - len(failed)} of {len(self.rows)} lines without failure; "
              + ("FAILED: " + ", ".join(failed) if failed else "nothing failed"))
        return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--glasses", required=True, help="adb transport of the glasses")
    parser.add_argument("--phone", help="adb transport of the phone that runs the server; adds the server checks")
    parser.add_argument("--expect-serialno", default=GLASSES_SERIAL)
    parser.add_argument("--watch", type=int, default=15, help="seconds to watch an unmoving scene after the first photo")
    parser.add_argument("--paper", type=int, default=0, help="seconds to record a real booklet being read, in place of the pause steps")
    parser.add_argument("--report", help="directory for the pulled photos and the screens")
    sys.exit(Check(parser.parse_args()).main())
