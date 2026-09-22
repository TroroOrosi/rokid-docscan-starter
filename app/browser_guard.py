"""One browser writer per data directory, with a durable uncertain-send barrier.

All workers sharing the phone's browser MUST share ROKID_DATA_DIR. This does not
coordinate different machines. No lock timeout or process restart clears an
uncertain submission; only a received reply or explicit operator reconciliation
can do that. The journal contains no source, prompt, answer, URL, or credential.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
from pathlib import Path
import re
import tempfile

from . import config


class BrowserGuardError(RuntimeError):
    """Browser ownership or durable state could not be established."""


class BrowserBusy(BrowserGuardError):
    """Another worker owns the browser. No browser operation was attempted."""


class BrowserUncertain(BrowserGuardError):
    """A previous send needs operator reconciliation before any further send."""


class BrowserGuard:
    def __init__(self, data_dir: Path | None = None):
        self.directory = Path(data_dir if data_dir is not None else config.DATA_DIR) / "browser-state"
        self.journal_path = self.directory / "submission.json"
        self._file = None

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.directory / "writer.lock", os.O_RDWR | os.O_CREAT, 0o600)
        self._file = os.fdopen(fd, "r+b", buffering=0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self._file.close()
            self._file = None
            if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise BrowserBusy("browser is busy; no message sent") from error
            raise
        return self

    def __exit__(self, *_):
        if self._file is not None:
            try:
                self._file.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            finally:
                self._file.close()
                self._file = None

    def status(self) -> dict:
        if self._file is None:
            raise RuntimeError("browser lock required")
        try:
            with self.journal_path.open("r", encoding="utf-8") as source:
                raw = source.read(4097)
            if len(raw) > 4096:
                raise ValueError("oversized journal")
            record = json.loads(raw)
            if (not isinstance(record, dict) or record.get("schema") != 1
                    or record.get("state") not in ("idle", "uncertain")):
                raise ValueError("invalid journal")
            if record["state"] == "uncertain" and not re.fullmatch(r"[0-9a-f]{64}", record.get("request_id", "")):
                raise ValueError("invalid request identity")
            return record
        except FileNotFoundError:
            return {"schema": 1, "state": "idle"}
        except (ValueError, TypeError, UnicodeError) as error:
            raise BrowserUncertain("submission journal is invalid; retained for inspection") from error

    def require_clear(self) -> None:
        record = self.status()
        if record["state"] != "idle":
            raise BrowserUncertain("previous send outcome is unknown; inspect and acknowledge before retry")

    def mark_sending(self, request_id: str) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", request_id):
            raise ValueError("invalid request identity")
        self.require_clear()
        self._write({"schema": 1, "state": "uncertain", "request_id": request_id})

    def acknowledge(self, request_id: str) -> None:
        record = self.status()
        if record.get("state") != "uncertain" or record.get("request_id") != request_id:
            raise ValueError("request identity does not match the pending send")
        self._write({"schema": 1, "state": "idle"})

    def _write(self, record: dict) -> None:
        if self._file is None:
            raise RuntimeError("browser lock required")
        fd, temporary = tempfile.mkstemp(prefix="submission-", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as target:
                json.dump(record, target, sort_keys=True)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, self.journal_path)
            if os.name != "nt":
                directory_fd = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            Path(temporary).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "acknowledge"))
    parser.add_argument("--request-id")
    parser.add_argument("--confirm-reviewed", action="store_true")
    args = parser.parse_args()
    if args.action == "acknowledge" and (not args.request_id or not args.confirm_reviewed):
        parser.error("acknowledge requires --request-id and --confirm-reviewed after inspecting the original chat")
    try:
        with BrowserGuard() as guard:
            if args.action == "acknowledge":
                guard.acknowledge(args.request_id)
            print(json.dumps(guard.status(), sort_keys=True))
    except (BrowserGuardError, OSError, ValueError) as error:
        parser.exit(2, f"{type(error).__name__}: browser state requires inspection\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
