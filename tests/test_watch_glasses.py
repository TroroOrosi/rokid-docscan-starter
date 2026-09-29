import subprocess

import pytest

from scripts import watch_glasses


def test_only_a_fold_then_open_starts_the_chooser_and_disconnect_keeps_the_fold(monkeypatch):
    observations = iter(["1", "1", "0", subprocess.TimeoutExpired("adb", 5), "1", "1", "0", "1"])
    starts = []

    def adb(serial, *args):
        assert serial == "glasses:5555"
        if args == ("shell", "getprop", "ro.serialno"):
            return "expected"
        if args == ("shell", "getprop", "vendor.rkd.glasses.is_spread"):
            item = next(observations)
            if isinstance(item, Exception):
                raise item
            return item
        starts.append(args)
        return "Status: ok"

    monkeypatch.setattr(watch_glasses, "adb", adb)
    monkeypatch.setattr(watch_glasses.time, "sleep", lambda _: None)
    with pytest.raises(StopIteration):
        watch_glasses.watch("glasses:5555", "expected", 0.5)
    assert starts == [
        ("shell", "input", "-d", "0", "keyevent", "KEYCODE_WAKEUP"),
        ("shell", "am", "start", "-W", "-n", watch_glasses.COMPONENT),
    ] * 2

    with pytest.raises(SystemExit, match="identity"):
        watch_glasses.watch("glasses:5555", "wrong", 0.5)


def test_unknown_launch_is_not_retried_while_the_glasses_stay_open(monkeypatch):
    observations = iter(["0", "1", "1", "1"])
    launches = []

    def adb(serial, *args):
        if "ro.serialno" in args:
            return "expected"
        if "vendor.rkd.glasses.is_spread" in args:
            return next(observations)
        if "am" in args:
            launches.append(args)
            raise subprocess.TimeoutExpired("adb", 10)
        return ""

    monkeypatch.setattr(watch_glasses, "adb", adb)
    monkeypatch.setattr(watch_glasses.time, "sleep", lambda _: None)
    with pytest.raises(StopIteration):
        watch_glasses.watch("glasses:5555", "expected", 0.5)
    assert len(launches) == 1



def test_auto_finds_the_glasses_among_the_hotspot_clients(monkeypatch):
    """2026-09-30: the app failed before talking to the server, so the watcher
    never learned the address and unfolding brought back the home screen."""
    tethering = ("{android.net.ip.IpServer@99d6002={/10.248.83.1=downstream: 306 "
                 "(9e:9f:64:05:5e:3f), client: /10.248.83.1 (ec:4c:8c:74:88:3f), "
                 "/10.248.83.167=downstream: 306 (9e:9f:64:05:5e:3f), "
                 "client: /10.248.83.167 (ac:86:d1:5b:e3:66)}}")
    serials = {"10.248.83.1:5555": subprocess.CalledProcessError(1, "adb"),
               "10.248.83.167:5555": "glasses"}

    def adb(serial, *args):
        result = serials[serial]
        if isinstance(result, Exception):
            raise result
        return result

    connects = []

    def run(args, **_):
        if args[-2:] == ["dumpsys", "tethering"]:
            # The real dump carries "Exception" in its history (2026-09-30).
            return subprocess.CompletedProcess(args, 0, tethering + " IllegalStateException", "")
        connects.append(args[-1])

    monkeypatch.setattr(watch_glasses, "adb", adb)
    monkeypatch.setattr(watch_glasses.subprocess, "run", run)

    assert watch_glasses.target("auto", "glasses") == "10.248.83.167:5555"
    assert connects == ["10.248.83.1:5555", "10.248.83.167:5555"]
    assert watch_glasses.target("192.168.0.31:5555", "glasses") == "192.168.0.31:5555"
