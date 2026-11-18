"""Where the time of a use went, read from the glasses' own record (scripts/use_log_report.py).

Every line below is made up in the app's formats (UseLog, glassdoc 0.44.19); none is copied from a device.
"""
from scripts import use_log_report as report

T0 = 1_800_000_000_000  # epoch milliseconds of the made-up start


def log(*lines):
    """Each line is (milliseconds after the start, tag, message)."""
    return "\n".join(f"{T0 + at} {5000 + at} {tag} {message}" for at, tag, message in lines)


G, R = "DocScanGlassDoc", "DocScanRelay"
CLIP = ("clip frames=66 counted=60 dropped=0 bytes=33000000 first_ms=1200 back_ms=650 boost=140 exposure_ms=30 gyro=66 "
        "kept=true short=0 open_ms=200 idle_ms=550 idle_timeout=false drain_ms={drain} page_ms=80 closed_ms=500")
USE = log(
    (0, G, "start version=0.44.19 free_mb=15000 ext_free_mb=15000"),
    (900, G, "gesture kind=BACK phase=chooser state=DISCONNECTED asleep=false paused=false"),
    (1000, G, "reading_start free_mb=15000 resumed=false"),
    (2000, G, "AIMING: Manual shutter armed for page index 0"),
    (3600, G, "CAPTURING: Requesting glasses photo for page index 0 (1920x1080 q80)"),
    (7200, G, CLIP.format(drain=140)),
    (7250, G, "captured 2016x1512 in 3600 ms"),
    (7450, R, "review_shown index=0 pending_ms=15 decode_ms=150 drawn_ms=50"),
    (10650, R, "page_saved index=0 record_ms=40 hash_ms=110 total_ms=170"),
    (10700, R, "upload_begin kind=page index=0 bytes=780000 state=READING"),
    (11300, R, "upload_end kind=page index=0 ms=600 result=ok"),
    (11310, R, "upload_begin kind=clip index=0 bytes=33000000 state=READING"),
    (12000, G, "AIMING: Manual shutter armed for page index 1"),
    (13600, G, "CAPTURING: Requesting glasses photo for page index 1 (1920x1080 q80)"),
    (15000, R, "upload_end kind=clip index=0 ms=3690 result=ok"),
    (20500, G, CLIP.format(drain=3400)),
    (20550, G, "captured 2016x1512 in 6900 ms"),
    (20750, R, "review_shown index=1 pending_ms=15 decode_ms=150 drawn_ms=50"),
    (23950, R, "page_saved index=1 record_ms=40 hash_ms=110 total_ms=170"),
    (24000, R, "upload_begin kind=page index=1 bytes=780000 state=READING"),
    (24500, R, "upload_end kind=page index=1 ms=500 result=io_SocketTimeoutException"),
    (29500, R, "upload_retry kind=page index=1 try=2"),
    (29500, R, "upload_begin kind=page index=1 bytes=780000 state=READING"),
    (30000, R, "upload_end kind=page index=1 ms=500 result=ok"),
    (30100, G, "gesture kind=BACK phase=capturing state=READING asleep=false paused=false"),
    (30110, R, "end_requested state=READING"),
    (30200, R, "upload_begin kind=finalize index=-1 bytes=-1 state=FINALIZING"),
    (78200, R, "upload_end kind=finalize index=-1 ms=48000 result=ok"),
    (78500, R, "finalize_done ms=48390"),
    (180000, G, "wake revision=5 accepted=true"),
    (180060, G, "answers_get ms=55 bytes=3000 revision=5 result=ok"),
    (180100, G, "answers_saved ms=40"),
    (180340, G, "answers_drawn ms=340"),
)


def test_the_last_reading_is_laid_out_page_by_page_with_where_its_seconds_went():
    reading = report.last_reading(USE)
    assert reading["version"] == "0.44.19" and reading["free_mb"] == 15000
    first, second = reading["pages"]
    assert first["index"] == 0 and second["index"] == 1
    assert first["cycle_s"] == 9.65, "from the reading's start to the page saved"
    assert second["cycle_s"] == 13.3, "from the page before, saved, to this one saved"
    assert (first["armed_s"], first["first_ms"], first["drain_ms"]) == (1.6, 1200, 140)
    assert second["drain_ms"] == 3400 and second["frames"] == 66 and second["counted"] == 60
    assert reading["end"] == {"finalize_call_ms": 48000, "end_to_done_ms": 48390}
    assert reading["answers"] == [{"revision": 5, "get_ms": 55, "saved_ms": 40, "drawn_ms": 340}]


def test_what_a_reader_of_the_record_must_not_miss_is_named():
    noted = report.notes(report.last_reading(USE))
    assert any("page 2" in note and "3400 ms" in note and "closed" in note for note in noted), noted
    assert any("clip 1" in note and "while page 2 was being recorded" in note for note in noted), noted
    assert any("page 2" in note and "sent again" in note for note in noted), noted
    assert not any("page 1 " in note and "closed" in note for note in noted)


def test_a_clean_reading_has_nothing_to_note_and_a_file_without_a_reading_says_so():
    clean = "\n".join(line for line in USE.splitlines()[:11])  # one page, saved and sent
    assert report.notes(report.last_reading(clean)) == []
    assert report.last_reading(log((0, G, "start version=0.44.19 free_mb=15000 ext_free_mb=15000"))) is None
    assert report.last_reading("") is None


def test_dropped_frames_a_short_clip_a_refused_start_and_little_room_are_named():
    use = log(
        (0, G, "start version=0.44.19 free_mb=900 ext_free_mb=900"),
        (500, G, "start_refused free_mb=600"),
        (1000, G, "reading_start free_mb=900 resumed=false"),
        (3600, G, "CAPTURING: Requesting glasses photo for page index 0 (1920x1080 q80)"),
        (14000, G, CLIP.format(drain=140).replace("dropped=0", "dropped=7").replace("counted=60", "counted=31")
         .replace("idle_timeout=false", "idle_timeout=true")),
        (14100, G, "clip_release ms=5300"),
        (14300, R, "review_shown index=0 pending_ms=15 decode_ms=150 drawn_ms=50"),
        (17500, R, "page_saved index=0 record_ms=40 hash_ms=110 total_ms=170"),
    )
    noted = " | ".join(report.notes(report.last_reading(use)))
    for word in ("7 frame(s) dropped", "31 of 60", "watch session did not end", "5300 ms", "900 MB free", "refused"):
        assert word in noted, (word, noted)
