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
