"""Real filesystem/process tests; no browser, credentials, or model traffic."""
import json
import subprocess
import sys

import pytest


def test_browser_lock_excludes_another_process_and_releases(tmp_path):
    from app.browser_guard import BrowserGuard
    script = """from pathlib import Path
import sys
from app.browser_guard import BrowserGuard, BrowserBusy
try:
    with BrowserGuard(Path(sys.argv[1])):
        print('acquired')
except BrowserBusy:
    print('busy')
"""
    with BrowserGuard(tmp_path):
        result = subprocess.run([sys.executable, "-c", script, str(tmp_path)],
                                check=True, capture_output=True, text=True, timeout=15)
        assert result.stdout.strip() == "busy"
    with BrowserGuard(tmp_path):
        pass


def test_uncertain_send_survives_restart_and_requires_matching_ack(tmp_path):
    from app.browser_guard import BrowserGuard, BrowserUncertain
    request_id = "a" * 64
    with BrowserGuard(tmp_path) as guard:
        guard.require_clear()
        guard.mark_sending(request_id)
    with BrowserGuard(tmp_path) as guard:
        with pytest.raises(BrowserUncertain):
            guard.require_clear()
        with pytest.raises(ValueError):
            guard.acknowledge("b" * 64)
        guard.acknowledge(request_id)
    with BrowserGuard(tmp_path) as guard:
        guard.require_clear()


def test_corrupt_journal_fails_closed_without_deleting_it(tmp_path):
    from app.browser_guard import BrowserGuard, BrowserUncertain
    with BrowserGuard(tmp_path) as guard:
        journal = guard.journal_path
    journal.write_text("invalid", encoding="utf-8")
    with BrowserGuard(tmp_path) as guard:
        with pytest.raises(BrowserUncertain):
            guard.require_clear()
    assert journal.read_text(encoding="utf-8") == "invalid"


def test_journal_records_no_prompt_reply_credentials_or_images(tmp_path):
    from app.browser_guard import BrowserGuard
    with BrowserGuard(tmp_path) as guard:
        guard.mark_sending("a" * 64)
        body = json.loads(guard.journal_path.read_text(encoding="utf-8"))
        assert set(body) == {"schema", "state", "request_id"}
        guard.acknowledge("a" * 64)
        guard.require_clear()
