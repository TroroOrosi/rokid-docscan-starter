"""How a rehearsal on the phone is judged (scripts/phone_rehearsal.py): from the replay's report and the staged
server's log. The run itself needs the phone; what counts as passed is decided here."""
import json

from scripts import phone_rehearsal

REPORT = {"pages": [{}] * 3, "checks": [{"name": "answers arrived", "result": "PASS", "detail": ""}],
          "finalize": {"gather_wait_s": 12.0}, "answers": {"first_s": 40.0}}


def _log(*events, extra=""):
    return "\n".join(["INFO: started", *(json.dumps(event) for event in events), extra])


GOOD = [{"event": "codex_ahead", "pages": 2, "located": 2, "seconds": 4.0},
        {"event": "gather_wait", "document_id": 1, "seconds": 12.0, "left": 0},
        {"event": "codex_ahead", "pages": 1, "located": 1, "seconds": 2.0},
        {"event": "codex_prepared", "seconds": 1.5, "pages": 3, "ahead": 3},
        {"event": "codex_plan", "pages": 3, "parts": 0, "parts_long": None, "whole_long": None},
        {"event": "codex_read_done", "read": 1, "seconds": 20.0}]


def _results(report, log):
    checks, numbers = phone_rehearsal.judged(report, log)
    return [check["result"] for check in checks], numbers


def test_a_rehearsal_passes_when_the_replay_passed_and_every_page_was_prepared_and_used():
    results, numbers = _results(REPORT, _log(*GOOD))
    assert results == ["PASS"] * 4
    assert numbers["prepared_s"] == 1.5 and numbers["ahead_s"] == [4.0, 2.0] and numbers["gather_wait_s"] == [12.0]


def test_a_page_not_prepared_or_not_used_fails_it():
    one_missing = [dict(GOOD[0], located=1), *GOOD[1:]]
    assert _results(REPORT, _log(*one_missing))[0] == ["PASS", "FAIL", "PASS", "PASS"]
    not_used = [*GOOD[:3], dict(GOOD[3], ahead=2), *GOOD[4:]]
    assert _results(REPORT, _log(*not_used))[0] == ["PASS", "PASS", "FAIL", "PASS"]


def test_a_failure_in_the_log_or_in_the_replay_fails_it():
    assert _results(REPORT, _log(*GOOD, extra='{"event": "prepare_ahead_failed", "type": "OSError"}'))[0][3] == "FAIL"
    assert _results(REPORT, _log(*GOOD, extra="Traceback (most recent call last):"))[0][3] == "FAIL"
    failed = dict(REPORT, checks=[{"name": "answers arrived", "result": "FAIL", "detail": "none"}])
    assert _results(failed, _log(*GOOD))[0][0] == "FAIL"
    assert _results({}, "")[0] == ["FAIL", "FAIL", "FAIL", "PASS"], "no report and no log is no rehearsal"
