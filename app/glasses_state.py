"""Durable, ordered glasses power notifications for the phone's single API worker."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Literal

from pydantic import BaseModel, Field, conint, root_validator

from . import config

_LOCK = threading.RLock()
_COUNTER = conint(strict=True, ge=0, le=2**63 - 1)
_SESSION = conint(strict=True, gt=0, le=2**31 - 1)


class GlassesState(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)
    session_id: _SESSION | None = None
    generation: _COUNTER
    sequence: _COUNTER
    phase: Literal["chooser", "capturing", "analyzing", "waiting", "reading", "writing_done", "closed"]
    display_request: Literal["wake", "sleep"] | None = None
    entry_request: Literal["chooser"] | None = None
    ack_answer_revision: _COUNTER | None = None

    @root_validator(skip_on_failure=True)
    def protect_visible_work(cls, values):
        if values.get("phase") in ("capturing", "reading") and values.get("display_request") == "sleep":
            raise ValueError("capture and answer reading must remain visible")
        if values.get("entry_request") is not None and (
                values.get("phase") != "chooser" or values.get("session_id") is not None
                or values.get("display_request") != "wake"):
            raise ValueError("wear entry requires a visible chooser without a session")
        if values.get("ack_answer_revision") is not None and values.get("session_id") is None:
            raise ValueError("received answer revision requires a session")
        return values


def _path(device_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", device_id):
        raise ValueError("invalid device identity")
    identity = hashlib.sha256(device_id.encode()).hexdigest()
    return config.DATA_DIR / "glasses-state" / f"{identity}.json"


def read_state(device_id: str) -> dict | None:
    with _LOCK:
        return _read(_path(device_id))


def list_states() -> list[dict]:
    with _LOCK:
        directory = config.DATA_DIR / "glasses-state"
        paths = sorted(directory.glob("*.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True)
        return [record for path in paths if (record := _read(path)) is not None]


def _read(path: Path) -> dict | None:
    try:
        with path.open(encoding="utf-8") as source:
            raw = source.read(8193)
        if len(raw) > 8192:
            raise ValueError("oversized state")
        record = json.loads(raw)
        # Validate recovered counters/phase before they authorize any wake.
        state = dict(GlassesState(**record))
        if _path(state["device_id"]) != path or not isinstance(record["source_ip"], str):
            raise ValueError("invalid recovered identity")
        return {**state, "source_ip": record["source_ip"]}
    except FileNotFoundError:
        return None


def record_state(state: GlassesState, source_ip: str) -> bool:
    with _LOCK:
        path = _path(state.device_id)
        previous = read_state(state.device_id)
        record = dict(state)
        if previous:
            if (state.generation, state.sequence) <= (previous["generation"], previous["sequence"]):
                return False
            if state.generation == previous["generation"]:
                if previous["phase"] == "closed" or (previous["phase"] == "writing_done"
                                                     and state.phase != "closed"):
                    return False
                if state.session_id == previous["session_id"] and previous.get("ack_answer_revision") is not None:
                    # Preserve only an acknowledgement the client already sent;
                    # never derive receipt from generated server answers.
                    record["ack_answer_revision"] = max(previous["ack_answer_revision"],
                                                        state.ack_answer_revision or 0)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="state-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as target:
                json.dump({**record, "source_ip": source_ip}, target)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, path)
            if os.name != "nt":
                directory_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return True
