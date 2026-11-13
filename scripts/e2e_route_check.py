"""Drive the whole route on the real glasses, as a wearer would, without sending anything to the model.

    wear -> choose -> capture pages -> end -> upload -> analysis wait -> answers arrive -> wake -> read -> finish

The glasses run the same app under a second package name (`-PglassdocRouteCheck`, installed beside the real app, whose
saved server, key and answers are never touched). Server and watcher run on this PC: the server with
`ROKID_SOLVER=recorded` (a recorded reply stands for the model; sending is off, no browser is involved) and its own
data directory; the glasses reach it over `adb reverse`. Gestures are written to the touchpad's own input device.

This checks the glasses-side route and the server and watcher logic. It does NOT check the venue topology: the phone,
its hotspot, its load and its browser are not in the loop.

    py -3.12 scripts/e2e_route_check.py --glasses <usb serial> --data <server data dir> --key <test api key>
        [--server http://127.0.0.1:8765] [--photos 3] [--report <dir>]

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
ACTIVITY = f"{PACKAGE}/dev.rokid.docscanglass.doc.DocScanGlassActivity"
GLASSES_SERIAL = "1904092623381086"
TOUCHPAD = "/dev/input/event1"
TAP, SWIPE_FORWARD, SWIPE_BACK, DOUBLE_TAP = (204, 28), (204, 106, 108), (204, 105, 103), (204, 204, 158)
ENV = dict(os.environ, MSYS_NO_PATHCONV="1")


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

    def gesture(self, codes: tuple[int, ...]) -> None:
        self.sh("; ".join(f"sendevent {TOUCHPAD} 1 {c} 1; sendevent {TOUCHPAD} 0 0 0; sendevent {TOUCHPAD} 1 {c} 0; "
                          f"sendevent {TOUCHPAD} 0 0 0; sleep 0.08" for c in codes))

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
            if not self.prepare():
                return 1
            watcher = self.start_watcher()
            if self.capture() and self.finish_and_wait():
                self.read_and_exit()
        finally:
            self.sh(f"am force-stop {PACKAGE}")
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

    def capture(self) -> bool:
        self.sh(f"am force-stop {PACKAGE}; input keyevent KEYCODE_WAKEUP; sleep 1")
        self.since = self.stamp()
        self.sh(f"am start -W -n {ACTIVITY} --es server {self.o.server} --es key {self.o.key} --ez chooser true >/dev/null 2>&1")
        time.sleep(1.5)
        self.row("the chooser is drawn", self.lit("chooser") > 0)
        self.gesture(DOUBLE_TAP)  # once; a second one would land in a running capture
        if not self.row("one double tap starts the reading", bool(self.wait_log(self.since, "Started local capture session", 8))):
            return False
        first = self.wait_log(self.since, r"captured \d+x\d+ \d+B in \d+ms gen=1", 40)
        if not self.row("the first photo is taken without any input", bool(first), first or "no photo within 40 s"):
            return False
        committed = 1
        self.row("photo 1 is saved after its 3-second review", bool(self.wait_log(self.since, "Photo committed locally", 12)))
        for number in range(2, self.o.photos + 1):
            mark = self.stamp()
            self.gesture(SWIPE_FORWARD)
            taken = self.wait_log(mark, r"captured \d+x\d+ \d+B in \d+ms gen=\d+", 25)
            saved = self.wait_log(mark, "Photo committed locally", 14) if taken else None
            committed += 1 if saved else 0
            self.row(f"a forward swipe takes photo {number} and it is saved", bool(saved), (taken or "no photo")[:70])
        stills = len([line for line in self.log(self.since) if "still_requested" in line])
        self.row("stills requested so far", None, f"{stills} for {committed} saved photo(s)")
        pages = self.wait_db("select count(*) from pages where document_id = (select max(id) from documents)",
                             lambda rows: rows and rows[0][0] >= committed, 60)
        new_document = self.db("select count(*) from documents")[0][0] > self.before["documents"]
        self.committed = committed
        return self.row("every saved photo reached the server, in one new document", new_document and pages[0][0] >= committed,
                        f"{pages[0][0]} page(s) on the server for {committed} saved")

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
        time.sleep(1.5)
        second = self.adb("exec-out", "screencap", "-p")
        self.lit("answers-next")
        self.row("a forward swipe moves on through the answers", first != second)
        self.gesture(SWIPE_BACK)
        time.sleep(1.5)
        self.row("a back swipe returns", self.adb("exec-out", "screencap", "-p") != second)
        self.gesture(TAP)
        time.sleep(1.5)
        self.row("a tap hides the answers", self.lit("answers-hidden") == 0)
        self.gesture(TAP)
        time.sleep(1.5)
        self.row("the next gesture brings them back", self.lit("answers-back") > 0)
        time.sleep(7)
        self.row("the answers stay on screen while reading (no idle sleep)", "mWakefulness=Awake" in self.sh("dumpsys power") and self.lit("answers-held") > 0)
        state = self.db("select count(*) from exam_sessions")[0][0]
        mark = self.stamp()
        self.gesture(DOUBLE_TAP)
        time.sleep(6)
        self.row("a double tap in the reader ends the writing and the display goes off",
                 self.lit("writing-done") == 0, " | ".join(line[:70] for line in self.log(mark) if "preview_status" not in line)[-200:])
        self.gesture(DOUBLE_TAP)
        time.sleep(0.6)
        self.gesture(DOUBLE_TAP)
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
    parser.add_argument("--interrupt", choices=["wait"], help="force-stop the app (what a fold does) at this point and reopen the chooser")
    parser.add_argument("--report")
    return Check(parser.parse_args()).run()


if __name__ == "__main__":
    raise SystemExit(main())
