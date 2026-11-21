"""The capture log checker against made-up excerpts: one clean and one violating log per rule.

Every line below is written for this test in the app's formats; none is copied from a device.
"""

import pytest

from scripts import capture_log_invariants as checker

SAVED = "READING: Photo committed locally; network upload queued"
REQUEST = "CAPTURING: Requesting glasses photo for page index 1 (1920x1080 q80)"
ARMED = "AIMING: Manual shutter armed for page index 1"
PAUSED = "READING: Capture paused by the wearer"
PHOTO = "captured 4032x3024 in 817 ms"


def log(*lines):
    """Each line is 'HH:MM:SS.mmm message', written as `adb logcat -v threadtime` writes the app's tag."""
    return "\n".join(
        f"11-17 {stamp}  2315  2380 I DocScanGlassDoc: {message}" for stamp, message in (line.split(" ", 1) for line in lines)
    )


def status(stamp, pending=False, page_ready=False, future=False):
    return (
        f"{stamp} preview_status frames=10 max_work_ms=20 max_gap_ms=110 pending={str(pending).lower()}"
        f" page_ready={str(page_ready).lower()} future={str(future).lower()} scene=4 page_still=true"
    )


def clip(stamp, counted, kept="true", short=0):
    return f"{stamp} clip frames={counted + 6} counted={counted} dropped=0 bytes=2400000 first_ms=1100 kept={kept} short={short}"


def rules(text, since=None):
    return [violation.rule for violation in checker.check(text, since)]


# ---- R1: automatic capture has stopped silently --------------------------------------------------------------------

def test_r1_a_camera_that_waits_for_the_next_page_is_clean():
    text = log(f"09:00:00.000 {SAVED}", *(status(f"09:00:0{second}.500", page_ready=True) for second in range(1, 8)))
    assert rules(text) == []


def test_r1_five_status_lines_with_no_page_waited_for_are_reported_with_their_times():
    text = log(
        f"09:00:00.000 {SAVED}",
        status("09:00:01.000", page_ready=True),
        *(status(f"09:00:0{second}.000") for second in range(2, 8)),
        status("09:00:08.000", page_ready=True),
    )
    found = [violation for violation in checker.check(text) if violation.rule == "R1"]
    assert len(found) == 1
    assert len(found[0].lines) == 6
    assert str(found[0]).startswith("R1 09:00:02.000-09:00:07.000 automatic capture has stopped silently")


@pytest.mark.parametrize(
    "before",
    [
        PAUSED,  # the wearer cleared the display
        "CAPTURE_REVIEW: Review last photo before finishing",  # an end was asked for
        "READY: Manual capture: the automatic loop is disabled for this session",
        ARMED,  # a page is being taken: not READY or READING
    ],
)
def test_r1_is_silent_while_paused_ending_manual_or_taking_a_page(before):
    text = log(f"09:00:00.000 {before}", *(status(f"09:00:0{second}.000") for second in range(1, 8)))
    assert "R1" not in rules(text)


def test_r1_needs_five_in_a_row_and_a_pending_photo_breaks_the_row():
    quiet = [status(f"09:00:0{second}.000") for second in range(1, 5)]
    text = log("09:00:00.000 READY: Started local capture session", *quiet, status("09:00:05.000", pending=True),
               *(status(f"09:00:1{second}.000") for second in range(0, 4)))
    assert "R1" not in rules(text)


def test_r1_counts_across_a_controller_line_that_leaves_the_capture_waiting():
    text = log(
        "09:00:00.000 READING: Capture resumed by the wearer",
        status("09:00:01.000"), status("09:00:02.000"), status("09:00:03.000"),
        "09:00:03.500 READING: Network work paused; local images retained for retry",
        status("09:00:04.000"), status("09:00:05.000"),
    )
    assert rules(text) == ["R1"]


# ---- R2: nothing happens after a save ------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "following",
    [ARMED, PAUSED, "CAPTURE_REVIEW: Photo awaiting confirmation: page 1", "FINALIZING: Local capture finished; analysis queued", SAVED],
)
def test_r2_a_save_followed_within_ten_seconds_by_the_next_step_is_clean(following):
    text = log(f"09:00:00.000 {SAVED}", f"09:00:04.000 {following}", status("09:00:08.000", page_ready=True),
               status("09:00:30.000", page_ready=True))
    assert "R2" not in rules(text)


def test_r2_ten_quiet_seconds_after_a_save_are_reported():
    text = log(f"09:00:00.000 {SAVED}", f"09:00:14.000 {ARMED}")
    found = checker.check(text)
    assert [violation.rule for violation in found] == ["R2"]
    assert str(found[0]) == f"R2 09:00:00.000 nothing happens within 10 s of a save | {SAVED}"


def test_r2_a_controller_line_of_another_kind_right_after_a_save_is_reported():
    text = log(f"09:00:00.000 {SAVED}", "09:00:00.100 READING: Capture resumed by the wearer")
    assert rules(text) == ["R2"]


def test_r2_is_silent_while_the_still_camera_waits_for_the_page_to_be_turned():
    text = log(f"09:00:00.000 {SAVED}", *(status(f"09:00:{second:02d}.000", page_ready=True) for second in range(1, 30)),
               f"09:00:30.000 {ARMED}")
    assert rules(text) == []


def test_r2_is_silent_while_the_clip_camera_watches_a_paper_that_has_not_changed():
    """The checker's first run on a real log (2026-11-18, forty desk clips) reported three saves after which the clip
    camera was plainly watching: it writes watch_status once a second, which the rule did not know."""
    watching = "watch_status frames=16 max_work_ms=40 exposure_ns=50000000 iso=800 boost=325 far=false lines=81.2"
    text = log(f"09:00:00.000 {SAVED}", *(f"09:00:{second:02d}.000 {watching}" for second in range(1, 30)),
               f"09:00:30.000 {ARMED}")
    assert rules(text) == []
    stalled = "watch_status frames=0 max_work_ms=0 exposure_ns=50000000 iso=800 boost=325 far=false lines=0.0"
    text = log(f"09:00:00.000 {SAVED}", *(f"09:00:{second:02d}.000 {stalled}" for second in range(1, 30)),
               f"09:00:30.000 {ARMED}")
    assert rules(text) == ["R2"], "a camera that hands over no frame is not watching"


def test_r2_passes_over_the_uploads_own_line():
    retry = "READING: Network work paused; local images retained for retry"
    assert rules(log(f"09:00:00.000 {SAVED}", f"09:00:01.000 {retry}", f"09:00:05.000 {ARMED}")) == []
    assert rules(log(f"09:00:00.000 {SAVED}", f"09:00:01.000 {retry}", f"09:00:15.000 {ARMED}")) == ["R2"]


def test_r2_says_nothing_of_a_save_the_log_ends_on():
    assert rules(log(f"09:00:00.000 {SAVED}", status("09:00:03.000"))) == []


# ---- R3: every camera request is answered once ---------------------------------------------------------------------

@pytest.mark.parametrize(
    "answer",
    [
        [f"09:00:02.000 {PHOTO}"],
        # the still camera's own line for the same photo is not a second answer
        ["09:00:01.900 captured 4032x3024 1830221B in 817ms gen=3", f"09:00:02.000 {PHOTO}"],
        [clip("09:00:09.000", 60), "09:00:09.100 captured 2016x1512 in 8700 ms"],  # a clip and its page
        [clip("09:00:09.000", 12, kept="false"), "09:00:09.100 READING: Local preparation expired before any camera request"],
        ["09:00:05.000 READING: Local preparation expired before any camera request"],
        ["09:00:05.000 CAPTURE_REVIEW: Retake did not start; previous review photo retained: camera not still"],
        ["09:00:31.000 ERROR: カメラ状態が不明です"],
        ["09:00:05.000 FINALIZING: Local capture finished; analysis queued"],  # ended while the page was asked for
    ],
)
def test_r3_a_request_with_one_answer_is_clean(answer):
    text = log(f"09:00:00.000 {REQUEST}", *answer, f"09:02:00.000 {REQUEST}", f"09:02:02.000 {PHOTO}")
    assert "R3" not in rules(text)


def test_r3_a_request_with_no_answer_before_the_next_is_reported():
    text = log(f"09:00:00.000 {REQUEST}", f"09:00:40.000 {REQUEST}", f"09:00:42.000 {PHOTO}")
    found = [violation for violation in checker.check(text) if violation.rule == "R3"]
    assert [str(violation) for violation in found] == [f"R3 09:00:00.000 a camera request is never answered | {REQUEST}"]


def test_r3_two_photos_for_one_request_are_reported():
    text = log(f"09:00:00.000 {REQUEST}", f"09:00:02.000 {PHOTO}", f"09:00:02.400 {PHOTO}")
    found = [violation for violation in checker.check(text) if violation.rule == "R3"]
    assert len(found) == 1 and "answered 2 times" in found[0].message and len(found[0].lines) == 3


def test_r3_waits_a_minute_for_the_request_the_log_ends_on():
    assert "R3" not in rules(log(f"09:00:00.000 {REQUEST}", status("09:00:20.000", pending=True)))
    assert "R3" in rules(log(f"09:00:00.000 {REQUEST}", status("09:01:30.000", pending=True)))


# ---- R4: refused ends and missed scenes ----------------------------------------------------------------------------

def test_r4_a_capture_that_ends_when_asked_is_clean():
    assert rules(log("09:00:00.000 FINALIZING: Local capture finished; analysis queued")) == []


@pytest.mark.parametrize(
    "line",
    [
        "ERROR: Finish rejected while a CXR-L photo lease is unresolved",
        "AIMING: Finish ignored while capture pipeline is active",
        "READING: Observed scene was not captured; preserved originals are not proof of complete coverage",
    ],
)
def test_r4_each_of_the_three_diagnostics_is_reported(line):
    found = [violation for violation in checker.check(log(f"09:00:00.000 {line}")) if violation.rule == "R4"]
    assert len(found) == 1 and found[0].lines[0].text == line


# ---- R5: a short clip saved as a page ------------------------------------------------------------------------------

def test_r5_a_whole_clip_is_clean():
    assert rules(log(f"09:00:00.000 {REQUEST}", clip("09:00:09.000", 60), "09:00:09.100 captured 2016x1512 in 8700 ms")) == []


def test_r5_a_short_clip_that_became_a_page_is_reported():
    text = log(f"09:00:00.000 {REQUEST}", clip("09:00:10.000", 22), "09:00:10.100 captured 2016x1512 in 9900 ms",
               f"09:00:14.000 {SAVED}", f"09:00:16.000 {ARMED}")
    found = [violation for violation in checker.check(text) if violation.rule == "R5"]
    assert len(found) == 1 and found[0].message == "a short clip was saved as a page: 22 counted frames"


@pytest.mark.parametrize(
    "lines",
    [
        [f"09:00:00.000 {REQUEST}", clip("09:00:10.000", 22, kept="false")],  # recorded again, not saved
        [f"09:00:00.000 {REQUEST}", clip("09:00:10.000", 22, short=2)],  # the third short clip in a row is taken as it is
        # the wearer's tap ended it
        [f"09:00:00.000 {REQUEST}", "09:00:04.000 CAPTURING: Capture paused by the wearer; the page in hand is kept",
         clip("09:00:04.600", 22)],
        # the wearer's double tap ended it: the capture ends with this page
        [f"09:00:00.000 {REQUEST}", clip("09:00:04.600", 22), "09:00:04.700 captured 2016x1512 in 4500 ms",
         f"09:00:08.000 {SAVED}", "09:00:08.100 FINALIZING: Local capture finished; analysis queued"],
        [f"09:00:00.000 {REQUEST}", "09:00:09.000 clip frames=28 counted=22 dropped=0 bytes=2400000"],  # an older build's line
    ],
)
def test_r5_is_silent_for_a_clip_that_was_not_saved_or_that_the_wearer_cut_short(lines):
    assert "R5" not in rules(log(*lines))


def test_r5_a_pause_long_before_the_clip_does_not_excuse_it():
    text = log(f"09:00:00.000 {PAUSED}", "09:00:01.000 READING: Capture resumed by the wearer",
               f"09:00:20.000 {REQUEST}", clip("09:00:30.000", 22), f"09:00:40.000 {ARMED}")
    assert "R5" in rules(text)


# ---- reading the file ----------------------------------------------------------------------------------------------

def test_the_time_form_of_logcat_and_a_line_without_a_time_are_read():
    text = "\n".join([
        f"11-17 09:00:00.000 I/DocScanGlassDoc( 2315): {SAVED}",
        "11-17 09:00:05.000 D/OtherTag( 2315): READING: Finish rejected",  # not the app's tag
        "I/DocScanGlassDoc( 2315): READING: Observed scene was not captured; preserved originals are not proof",
        "2026-11-17 09:00:20.000  2315  2380 I DocScanGlassDoc: " + ARMED,
    ])
    entries = checker.parse(text)
    assert [(entry.stamp, entry.state) for entry in entries] == [
        ("09:00:00.000", "READING"), ("?", "READING"), ("09:00:20.000", "AIMING")]
    assert entries[1].time == entries[0].time
    assert rules(text) == ["R2", "R4"]


def test_the_apps_own_use_log_is_read_as_logcat_is():
    """From glassdoc 0.44.19 the app keeps its lines in a file of its own (use-log.txt: epoch milliseconds, the
    milliseconds since the glasses started, the tag, the message), which a restart of the glasses does not lose."""
    from datetime import datetime

    def use_log(*lines):
        return "\n".join(f"{int(datetime(2026, 11, 19, 9, 0, second).timestamp() * 1000) + millis} {5000 + second * 1000} {tag} {message}"
                         for second, millis, tag, message in lines)

    text = use_log((0, 0, "DocScanGlassDoc", SAVED), (2, 0, "DocScanRelay", "upload_begin kind=page index=0 bytes=9 state=READING"),
                   (3, 250, "DocScanGlassDoc", "gesture kind=SHORT_TAP phase=capturing state=READING asleep=false paused=false"),
                   (20, 0, "DocScanGlassDoc", ARMED))
    entries = checker.parse(text)
    assert [(entry.stamp, entry.state) for entry in entries] == [
        ("09:00:00.000", "READING"), ("09:00:03.250", None), ("09:00:20.000", "AIMING")], "the app's tag alone, as in logcat"
    assert entries[2].time - entries[0].time == 20.0
    assert rules(text) == ["R2"], "twenty quiet seconds after a save"
    assert [entry.stamp for entry in checker.parse(text, since="09:00:03")] == ["09:00:03.250", "09:00:20.000"]


def test_the_command_prints_one_line_a_violation_and_its_exit_code_tells(tmp_path, capsys):
    clean, broken, empty = tmp_path / "clean.txt", tmp_path / "broken.txt", tmp_path / "empty.txt"
    clean.write_text(log(f"09:00:00.000 {SAVED}", f"09:00:04.000 {ARMED}"), encoding="utf-8")
    broken.write_text(log("08:59:00.000 READING: Finish rejected: empty document", f"09:00:00.000 {SAVED}",
                          f"09:00:14.000 {ARMED}"), encoding="utf-16")  # as Windows PowerShell 5 redirects
    empty.write_text("11-17 09:00:00.000  2315  2380 I OtherTag: nothing of the app\n", encoding="utf-8")

    assert checker.main([str(clean)]) == 0
    assert capsys.readouterr().out == ""
    assert checker.main([str(broken)]) == 1
    assert capsys.readouterr().out.splitlines() == [
        f"R2 09:00:00.000 nothing happens within 10 s of a save | {SAVED}",
        "R4 08:59:00.000 Finish rejected | READING: Finish rejected: empty document",
    ]
    assert checker.main([str(broken), "--since", "09:00:00"]) == 1
    assert capsys.readouterr().out.splitlines() == [f"R2 09:00:00.000 nothing happens within 10 s of a save | {SAVED}"]
    assert checker.main([str(empty)]) == 2
    assert checker.main([str(broken), "--since", "10:00:00"]) == 2
