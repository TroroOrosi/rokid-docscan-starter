#!/usr/bin/env python3
r"""Rehearse HEAD's server on the phone before it goes live there: a recorded booklet through the whole Codex route.

    py -3.12 scripts/phone_rehearsal.py --phone <adb transport> --serial <the phone's ro.serialno>
        [--make-fixture <document id>]   keep that booklet of the live server as the rehearsal's booklet (once)
        [--pace recorded|fast]           recorded (default): the uploads at the pace the wearer made them
        [--model-seconds 20]             how long the stand-in takes over a request for answers

What runs, all of it on the phone and beside the live server, which is not touched:

- HEAD's ``app/`` (from git, never the working tree), in a folder of its own (``~/rokid-rehearsal``), as a second
  server on a port of its own with data of its own, started with the live server's settings;
- a booklet a wearer really recorded (its frames and clips, kept in ``~/rokid-rehearsal/source`` by --make-fixture:
  the live server removes clips after three days), sent as the glasses sent it (scripts/replay_booklet.py);
- the Codex route with the stand-in CLI (scripts/standin_codex.py) in the model's place: nothing is sent to the
  model and no allowance is spent. ``ROKID_CODEX_BIN`` names the stand-in, and the route then runs nothing else.

It passes when the replay's own four checks pass (every clip gathered, the finalize inside its limit, answers there,
no failed item), every page was prepared ahead and used (``codex_ahead``, ``codex_prepared``), and the server's log
holds no failure. The result is printed and written to ``data/rehearsals/<commit>.json`` on this PC (untracked), which
is what the deploy looks for.

What it shows: that this code does a booklet's work on that phone (the gathering beside the uploads, the wait at
the end, the hand-over, the cutting, the parts, the comparison, the answers). What it cannot show: the model (what
it reads, how long it takes, what a request costs, a refusal), the glasses (the capture, the display, the watcher's
wake), and the hotspot. A change to what is sent to the model still needs one real read (the operator's allowance).

Runs on: this PC, driving the phone over adb. Not the venue topology: no glasses, no hotspot, no model.
"""
from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import tarfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ADB = Path.home() / "AppData/Local/Android/Sdk/platform-tools/adb.exe"
PORT = 18002
HEAD = ("export PREFIX=/data/data/com.termux/files/usr HOME=/data/data/com.termux/files/home\n"
        "export PATH=$PREFIX/bin:$PATH LD_LIBRARY_PATH=$PREFIX/lib TMPDIR=$PREFIX/tmp\n"
        "R=$HOME/rokid-rehearsal\nmkdir -p $R || exit 9\ncd $R || exit 9\n")
FIXTURE = r'''
import shutil, sqlite3, sys
from pathlib import Path
live, kept, document = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
if kept.exists():
    shutil.rmtree(kept)
kept.mkdir(parents=True)
source = sqlite3.connect(f"file:{live / 'docscan.db'}?mode=ro", uri=True)
target = sqlite3.connect(kept / "docscan.db")
source.backup(target)
target.close()
(kept / "images").mkdir()
images = list((live / "images").glob(f"{document}_*"))
for image in images:
    shutil.copy2(image, kept / "images" / image.name)
clips = live / "page-clips" / str(document)
shutil.copytree(clips, kept / "page-clips" / str(document))
(kept / "document.txt").write_text(str(document))
movies = list((kept / "page-clips").rglob("*.mp4"))
print(f"fixture: document {document}, {len(images)} image files, {len(movies)} clips, "
      f"{sum(path.stat().st_size for path in movies) // 1_000_000} MB of clips")
'''
SERVER = r'''
for p in $(pgrep -f uvicorn); do if tr "\0" " " < /proc/$p/cmdline | grep -q "__PORT__"; then kill $p; fi; done
sleep 1
rm -rf $R/data $R/codex-home; mkdir -p $R/data $R/codex-home
printf 'rehearsal-key' > $R/key
printf '#!%s/bin/sh\nexec %s/bin/python %s/scripts/standin_codex.py "$@"\n' "$PREFIX" "$PREFIX" "$R" > $R/standin
chmod 700 $R/standin
ACTIVE=$(grep -o -E "[A-Za-z0-9._/-]+\.env" $PREFIX/var/service/rokid-api/run | head -1)
# The live server's settings, then what makes this a server of its own. In this shell and not in a subshell sent to the
# background: such a subshell keeps adb's output open for as long as the server runs, and this call never returns.
set -a; . "$ACTIVE"; set +a
export ROKID_DATA_DIR=$R/data ROKID_API_KEY=rehearsal-key ROKID_SOLVER=codex-cli ROKID_SOLVER_FALLBACKS= \
  ROKID_ROUTE_CHECK_INTERVAL_S=0 ROKID_CAPTURE_INSPECTION=0 ROKID_CODEX_AUTO_UPDATE=0 ROKID_CODEX_BIN=$R/standin \
  CODEX_HOME=$R/codex-home STANDIN_CODEX_SECONDS=__SECONDS__
nohup python -m uvicorn app.main:app --host 127.0.0.1 --port __PORT__ --workers 1 --no-access-log \
  > $R/server.log 2>&1 < /dev/null &
sleep 9
curl -s -m 5 http://127.0.0.1:__PORT__/health | cut -c1-90
'''
REPLAY = r'''
python $R/scripts/replay_booklet.py --source-data $R/source --document $(cat $R/source/document.txt) \
  --server http://127.0.0.1:__PORT__ --key @$R/key --target-data $R/data --pace __PACE__ --real-solver \
  --timeout 900 --report $R/report.json > $R/replay.log 2>&1 < /dev/null
echo "replay exit $?"
'''
STOP = r'''
for p in $(pgrep -f uvicorn); do if tr "\0" " " < /proc/$p/cmdline | grep -q "__PORT__"; then kill $p; fi; done
sleep 1
rm -rf $R/data
'''
EVENTS = ("codex_ahead", "codex_prepared", "codex_plan", "codex_outline", "gather_wait", "codex_read_done")
FAILURES = ("prepare_ahead_failed", "codex_ahead_failed", "codex_outline_failed", "codex_run_failed",
            "codex_reply_unusable", "codex_read_failed", "solve_failure", "Traceback")


def git(*arguments: str) -> bytes:
    return subprocess.run(["git", "-C", str(REPO), *arguments], capture_output=True, check=True).stdout


def judged(report: dict, log: str) -> tuple[list[dict], dict]:
    """The checks of a rehearsal from the replay's report and the staged server's log, and the numbers on record."""
    events = {name: [json.loads(line) for line in log.splitlines() if line.startswith("{") and f'"{name}"' in line]
              for name in EVENTS}
    pages = len(report.get("pages") or [])
    located = sum(event["located"] for event in events["codex_ahead"])
    prepared = events["codex_prepared"][-1] if events["codex_prepared"] else {}
    failed = [name for name in FAILURES if name in log]
    replayed = report.get("checks") or []
    checks = [
        {"name": "the replay's own checks", "result": "PASS" if replayed and all(
            check["result"] == "PASS" for check in replayed) else "FAIL",
         "detail": "; ".join(f"{check['name']}: {check['result']}" for check in replayed) or "no report"},
        {"name": "every page prepared ahead", "result": "PASS" if pages and located == pages else "FAIL",
         "detail": f"{located} of {pages} located ahead in {len(events['codex_ahead'])} request(s)"},
        {"name": "what was prepared was used", "result": "PASS" if pages and prepared.get("ahead") == pages else "FAIL",
         "detail": f"{prepared.get('ahead')} of {pages} taken; {prepared.get('seconds')} s from the hand-over to the first read"},
        {"name": "no failure in the server's log", "result": "FAIL" if failed else "PASS",
         "detail": ", ".join(failed) or "none"},
    ]
    numbers = {"pages": pages, "gather_wait_s": [event["seconds"] for event in events["gather_wait"]],
               "ahead_s": [event["seconds"] for event in events["codex_ahead"]],
               "outline_s": [event["seconds"] for event in events["codex_outline"]],
               "prepared_s": prepared.get("seconds"), "plan": events["codex_plan"][-1] if events["codex_plan"] else None,
               "reads_s": [event["seconds"] for event in events["codex_read_done"]],
               "finalize": report.get("finalize"), "answers": report.get("answers")}
    return checks, numbers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--phone", required=True, help="the phone's adb transport")
    parser.add_argument("--serial", required=True, help="the phone's ro.serialno: nothing runs on another device")
    parser.add_argument("--make-fixture", type=int, metavar="DOCUMENT")
    parser.add_argument("--pace", default="recorded")
    parser.add_argument("--model-seconds", type=float, default=20.0)
    asked = parser.parse_args(argv)

    def adb(*arguments: str, data: bytes | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
        return subprocess.run([str(ADB), "-s", asked.phone, *arguments], input=data, capture_output=True, timeout=timeout)

    def remote(script: str, timeout: int = 120) -> str:
        done = adb("shell", "run-as com.termux sh -s", data=(HEAD + script).encode(), timeout=timeout)
        return done.stdout.decode("utf-8", "replace").replace("\r", "")

    serial = adb("shell", "getprop ro.serialno").stdout.decode().strip()
    if serial != asked.serial:
        print(f"not the phone named: {serial!r}")
        return 2
    commit = git("rev-parse", "HEAD").decode().strip()
    # scripts/ too: the server itself imports from there (app/capture_quality.py), and the stand-in and the replay live there.
    paths = [path for path in git("ls-tree", "-r", "--name-only", "HEAD", "app", "scripts").decode().split("\n")
             if path and (path.startswith("app/") or path.endswith(".py"))]
    bundle = io.BytesIO()
    with tarfile.open(fileobj=bundle, mode="w") as tar:
        for path in paths:
            blob = git("show", f"HEAD:{path}")
            info = tarfile.TarInfo(path)
            info.size, info.mode, info.mtime = len(blob), 0o644, int(time.time())
            tar.addfile(info, io.BytesIO(blob))
    remote("rm -rf $R/app $R/scripts")
    sent = adb("exec-in", "run-as com.termux sh -c 'cd /data/data/com.termux/files/home/rokid-rehearsal && tar -xf -'",
               data=bundle.getvalue(), timeout=300)
    if sent.returncode != 0:
        print("staging failed:", sent.stderr.decode("utf-8", "replace")[:300])
        return 2
    print(f"staged {len(paths)} files of {commit[:7]}")
    if asked.make_fixture is not None:
        maker = "cat > $R/fixture.py <<'PY'\n" + FIXTURE + "\nPY\n"
        print(remote(maker + f"python $R/fixture.py $HOME/rokid-server/data $R/source {asked.make_fixture} 2>&1 | tail -3",
                     timeout=900).strip())
    if "document.txt" not in remote("ls $R/source 2>/dev/null"):
        print("no rehearsal booklet on the phone: name one of the live server's with --make-fixture <document>")
        return 2

    def filled(script: str) -> str:
        return (script.replace("__PORT__", str(PORT)).replace("__SECONDS__", str(asked.model_seconds))
                .replace("__PACE__", asked.pace))

    health = remote(filled(SERVER), timeout=120).strip()
    print("staged server:", health[-90:])
    try:
        if '"status":"ok"' not in health.replace(" ", ""):
            print(remote("tail -n 15 $R/server.log | cut -c1-200"))
            return 2
        began = time.monotonic()
        print(remote(filled(REPLAY), timeout=1800).strip(), f"after {time.monotonic() - began:.0f} s")
        report_text = adb("exec-out", "run-as com.termux cat /data/data/com.termux/files/home/rokid-rehearsal/report.json",
                          timeout=60).stdout.decode("utf-8", "replace")
        log = adb("exec-out", "run-as com.termux cat /data/data/com.termux/files/home/rokid-rehearsal/server.log",
                  timeout=60).stdout.decode("utf-8", "replace").replace("\r", "")
    finally:
        remote(filled(STOP))
    try:
        report = json.loads(report_text)
    except ValueError:
        report = {}
    checks, numbers = judged(report, log)
    result = "PASS" if all(check["result"] == "PASS" for check in checks) else "FAIL"
    for check in checks:
        print(f"  {check['result']}  {check['name']}: {check['detail']}")
    print("  numbers:", json.dumps(numbers, ensure_ascii=False)[:900])
    print(f"rehearsal of {commit[:7]}: {result}")
    kept = REPO / "data" / "rehearsals"
    kept.mkdir(parents=True, exist_ok=True)
    (kept / f"{commit}.json").write_text(json.dumps({
        "commit": commit, "result": result, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "pace": asked.pace,
        "solver": "codex-cli with the stand-in CLI", "checks": checks, "numbers": numbers}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
