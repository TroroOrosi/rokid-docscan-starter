"""Authenticated preservation of sealed evaluation MP4s on the phone.

The client journal describes the bytes; it is not independent sensor evidence.
A receipt says only that the original and journal were stored, never that the
codec, text, frame coverage or booklet passed inspection. No decoder/AI runs here.
"""
from __future__ import annotations

from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
import uuid

from fastapi import HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from . import config, db
from .glasses_state import list_states, read_state, state_guard

MAX_BYTES = 128 * 1024 * 1024  # Evaluation clip budget, never a booklet-page limit.
MAX_METADATA_BYTES = 512 * 1024
CHUNK_BYTES = 64 * 1024
_I64 = 2**63 - 1
_I32 = 2**31 - 1
_HEX = re.compile(r"[a-f0-9]{64}\Z")
_CLIP = re.compile(r"video-[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\Z")
_TERMINAL = {"chooser", "writing_done", "closed"}
_JOURNAL_KEYS = set("""schema kind state reason device_id generation clip_id rotation original audio_enabled
selected_profile profile_quality_calibrated max_jpeg_width max_jpeg_height app_version app_version_code
producer_revision advertised_compatible_encoder actual_encoder_name actual_file bytes sha256
first_preview_sensor_ns last_preview_sensor_ns first_preview_frame_number last_preview_frame_number
largest_preview_sensor_gap_ns scene_clock sensor_timestamp_source latest_result_crop
latest_result_video_stabilization latest_result_optical_stabilization video_to_jpeg_field_of_view
scene_observation_source sensor_to_video_pts capture_gap_status exact_stream_support all_pages_or_characters_verified
auto_upload_allowed complete_scope event_budget_exceeded evaluation_max_bytes evaluation_max_duration_ms events""".split())
_EVENT_FIELDS = {
    "recorder_started": {}, "exact_session_support": {"support": "text"},
    "scene_observed": {"scene_sequence": "int", "sensor_timestamp_ns": "int", "observation_elapsed_ms": "int"},
    "native_still_requested": {"still_generation": "int"},
    "native_still_delivered": {"still_generation": "int", "sensor_timestamp_ns": "int", "width": "positive",
                               "height": "positive", "jpeg_sha256": "hash"},
    "capture_gap_or_anomaly": {"reason": "text"},
}


def _fail(detail: str, status: int = 400):
    raise HTTPException(status_code=status, detail=detail)


def _require(condition: bool):
    if not condition:
        _fail("invalid_video_metadata")


def _integer(value, minimum=0, maximum=_I64):
    return type(value) is int and minimum <= value <= maximum


def _text(value, maximum=256, *, empty=False):
    return type(value) is str and (empty or bool(value)) and len(value) <= maximum and "\0" not in value


def _keys(value, expected):
    _require(type(value) is dict and value.keys() == set(expected))


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def nonfinite(_):
        raise ValueError("nonfinite number")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def parse_metadata(raw: str) -> tuple[dict, bytes]:
    """Exact schema-1 journal from the current MediaRecorder evaluation producer."""
    try:
        _require(type(raw) is str)
        encoded = raw.encode("utf-8")
        if len(encoded) > MAX_METADATA_BYTES:
            _fail("video_metadata_too_large", 413)
        value = _json(encoded)
        _keys(value, ("schema", "session_id", "document_id", "journal"))
        _require(_integer(value["schema"], 1, 1) and _integer(value["session_id"], 1, _I32)
                 and _integer(value["document_id"], 1, _I32))
        journal = value["journal"]
        _keys(journal, _JOURNAL_KEYS)
        _require(_integer(journal["schema"], 1, 1))
        _require(_text(journal["device_id"], 100) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", journal["device_id"]) is not None)
        _require(_integer(journal["generation"]) and type(journal["clip_id"]) is str and _CLIP.fullmatch(journal["clip_id"]) is not None)
        _require(_integer(journal["rotation"], 0, 270) and journal["rotation"] in (0, 90, 180, 270))
        _require(_text(journal["reason"], empty=True) and _text(journal["app_version"], 128)
                 and _integer(journal["app_version_code"], 1, _I32) and _text(journal["advertised_compatible_encoder"]))
        constants = {"kind": "raw_video_evaluation", "original": "original.mp4", "audio_enabled": False,
            "profile_quality_calibrated": False, "producer_revision": "mediarecorder_hybrid_v1",
            "actual_encoder_name": "unknown_public_mediarecorder", "scene_clock": "camera_sensor_ns",
            "video_to_jpeg_field_of_view": "unknown_requires_physical_calibration",
            "scene_observation_source": "small_yuv_not_original_video_frame", "sensor_to_video_pts": "unknown_requires_decoded_pts",
            "capture_gap_status": "unknown_requires_decoded_frame_coverage", "exact_stream_support": "see_session_events",
            "all_pages_or_characters_verified": False, "auto_upload_allowed": False,
            "complete_scope": "sealed_local_video_container_only", "event_budget_exceeded": False,
            "evaluation_max_bytes": MAX_BYTES, "evaluation_max_duration_ms": 60_000}
        _require(all(type(journal[key]) is type(expected) and journal[key] == expected for key, expected in constants.items()))
        _require(type(journal["state"]) is str)
        if journal["state"] != "complete":
            _fail("video_not_sealed", 409)
        _require(_integer(journal["bytes"], 1, MAX_BYTES) and type(journal["sha256"]) is str and _HEX.fullmatch(journal["sha256"]) is not None)
        profile, actual = journal["selected_profile"], journal["actual_file"]
        _keys(profile, ("codec", "mime", "width", "height", "fps", "bitrate"))
        _keys(actual, ("mime", "width", "height", "rotation_metadata", "video_tracks", "audio_tracks",
                       "duration_us", "bitrate_metadata", "frame_rate_metadata"))
        _require(type(profile["codec"]) is str and profile["codec"] in ("avc", "hevc")
                 and profile["mime"] == f"video/{profile['codec']}")
        _require(all(_integer(profile[key], 1, _I32) for key in ("width", "height"))
                 and profile["width"] * 3 == profile["height"] * 4 and profile["width"] * profile["height"] <= 25_000_000)
        _require(_integer(profile["fps"], 1, 60) and _integer(profile["bitrate"], 1, 200_000_000))
        _require(all(type(actual[key]) is type(profile[key]) and actual[key] == profile[key] for key in ("mime", "width", "height")))
        _require(_integer(actual["rotation_metadata"], 0, 0) and _integer(actual["video_tracks"], 1, 1)
                 and _integer(actual["audio_tracks"], 0, 0) and _integer(actual["duration_us"], 1, 60_000_000))
        _require(actual["bitrate_metadata"] is None or _integer(actual["bitrate_metadata"], 1, 200_000_000))
        _require(actual["frame_rate_metadata"] is None or _integer(actual["frame_rate_metadata"], 1, 60))
        _require(all(_integer(journal[key], 1, _I32) for key in ("max_jpeg_width", "max_jpeg_height"))
                 and journal["max_jpeg_width"] * journal["max_jpeg_height"] <= 25_000_000)
        for key in ("first_preview_sensor_ns", "last_preview_sensor_ns", "largest_preview_sensor_gap_ns"):
            _require(_integer(journal[key]))
        _require(journal["last_preview_sensor_ns"] >= journal["first_preview_sensor_ns"])
        for key in ("first_preview_frame_number", "last_preview_frame_number"):
            _require(_integer(journal[key], -1))
        for key in ("sensor_timestamp_source", "latest_result_video_stabilization", "latest_result_optical_stabilization"):
            _require(journal[key] is None or _integer(journal[key], 0, _I32))
        crop = journal["latest_result_crop"]
        if crop is not None:
            _keys(crop, ("left", "top", "right", "bottom"))
            _require(all(_integer(number, 0, _I32) for number in crop.values())
                     and crop["right"] > crop["left"] and crop["bottom"] > crop["top"])
        _require(type(journal["events"]) is list and len(journal["events"]) <= 512)
        for event in journal["events"]:
            _require(type(event) is dict and type(event.get("event")) is str and event["event"] in _EVENT_FIELDS)
            fields = _EVENT_FIELDS[event["event"]]
            _keys(event, {"event", "elapsed_realtime_ns", *fields})
            _require(_integer(event["elapsed_realtime_ns"]))
            for key, kind in fields.items():
                item = event[key]
                _require((_integer(item) if kind == "int" else _integer(item, 1, _I32) if kind == "positive"
                          else type(item) is str and _HEX.fullmatch(item) is not None if kind == "hash" else _text(item)))
        return value, encoded
    except (ValueError, TypeError, UnicodeError, RecursionError):
        _fail("invalid_video_metadata")


@contextmanager
def _current(value, source_ip):
    """Hold only short local authorization/publication work against notifications."""
    with state_guard():
        try:
            journal = value["journal"]
            current = read_state(journal["device_id"])
            if (current is None or current["session_id"] != value["session_id"]
                    or current["generation"] != journal["generation"] or current["phase"] in _TERMINAL
                    or not source_ip or current["source_ip"] != source_ip):
                _fail("stale_video_capture", 409)
            if any(other["device_id"] != journal["device_id"] and other["session_id"] == value["session_id"]
                   and other["phase"] not in _TERMINAL for other in list_states()):
                _fail("ambiguous_video_owner", 409)
            conn = db.connect()
            try:
                session = conn.execute("SELECT document_id, status FROM exam_sessions WHERE id = ?", (value["session_id"],)).fetchone()
                document = conn.execute("SELECT id FROM documents WHERE id = ?", (value["document_id"],)).fetchone()
                if session is None or document is None:
                    _fail("video_session_or_document_not_found", 404)
                if session["document_id"] != value["document_id"] or session["status"] not in ("open", "reviewing"):
                    _fail("stale_video_document", 409)
            finally:
                conn.close()
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
            _fail("video_state_unavailable", 503)
        yield


def _plain(path):
    for part in (path, *path.parents):
        if part.is_symlink() or (getattr(part, "is_junction", lambda: False)()):
            raise OSError("video symlink path")
    if path.exists() and not (path.is_file() or path.is_dir()):
        raise OSError("video special path")


def _directory(path):
    _plain(path)
    path.mkdir(mode=0o700, exist_ok=True)
    if not path.is_dir():
        raise OSError("video directory unavailable")
    if os.name == "posix":
        path.chmod(0o700)


def _private_file(path):
    _plain(path)
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb")


def _sync_directory(path):
    if os.name == "posix":
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _publish_noreplace(source, target):
    """Same public Bionic API30 primitive as standalone scripts/phone_update.py.

    Keep the updater standalone. Some phone Python builds lack a usable link();
    never substitute POSIX rename(), which can replace an existing target.
    """
    if source.parent != target.parent:
        raise OSError("video publication directory")
    try:
        link = getattr(os, "link", None)
        if not callable(link):
            raise NotImplementedError
        link(source, target)
        return
    except NotImplementedError:
        pass
    except OSError as error:
        if error.errno not in (errno.ENOSYS, errno.EOPNOTSUPP):
            raise
    import ctypes
    try:
        rename = ctypes.CDLL(None, use_errno=True).renameat2
    except (AttributeError, OSError) as error:
        raise OSError("video exclusive publication unavailable") from error
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    ctypes.set_errno(0)
    if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code if type(code) is int and 0 < code <= 4095 else errno.EIO, "video exclusive publication failed")


def _fingerprint(info):
    # Windows lstat/fstat expose different ctime meanings on Python 3.12.
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns if os.name == "posix" else None)


def _read_verified(path, limit, *, digest_only=False):
    _plain(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise OSError("video stored file type or size")
    digest, chunks, count = hashlib.sha256(), [], 0
    with path.open("rb") as stream:
        while block := stream.read(CHUNK_BYTES):
            count += len(block)
            if count > limit:
                raise OSError("video stored file too large")
            digest.update(block)
            if not digest_only:
                chunks.append(block)
        if _fingerprint(before) != _fingerprint(os.fstat(stream.fileno())):
            raise OSError("video stored file changed")
    if _fingerprint(before) != _fingerprint(path.lstat()):
        raise OSError("video stored file replaced")
    return (digest.hexdigest() if digest_only else b"".join(chunks)), before


def _check_verified(entries):
    """Recheck parent names as well as file identities after unlocked hashing."""
    for path, before in entries:
        _plain(path)
        current = path.lstat()
        if stat.S_ISDIR(before.st_mode):
            # New unrelated objects/receipts can legitimately change directory
            # timestamps; the containing directory itself must stay the same.
            if (not stat.S_ISDIR(current.st_mode)
                    or (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino)):
                raise OSError("video storage directory changed")
        elif not stat.S_ISREG(current.st_mode) or _fingerprint(before) != _fingerprint(current):
            raise OSError("stored video changed after verification")


def _receipt_base(value, source_ip):
    journal = value["journal"]
    return {"schema": 1, "kind": "raw_video_receipt", "status": "stored", "quality_status": "unevaluated",
            "session_id": value["session_id"], "document_id": value["document_id"], "device_id": journal["device_id"],
            "generation": journal["generation"], "clip_id": journal["clip_id"], "sha256": journal["sha256"],
            "bytes": journal["bytes"], "source_ip": source_ip, "all_pages_or_characters_verified": False,
            "auto_analysis_allowed": False}


def _existing(marker, value):
    _plain(marker)
    if not marker.exists():
        return None
    try:
        raw, _ = _read_verified(marker, 16 * 1024)
        record = _json(raw)
        _keys(record, ("object_id", "metadata_identity_sha256", "receipt"))
        _require(type(record["object_id"]) is str and re.fullmatch(r"[a-f0-9]{32}", record["object_id"]) is not None)
        if record["metadata_identity_sha256"] != hashlib.sha256(_canonical(value)).hexdigest():
            _fail("video_clip_conflict", 409)
        receipt = record["receipt"]
        _keys(receipt, {*_receipt_base(value, ""), "receipt_id", "metadata_sha256"})
        _require(_text(receipt["source_ip"]) and type(receipt["metadata_sha256"]) is str
                 and _HEX.fullmatch(receipt["metadata_sha256"]) is not None)
        expected = {**_receipt_base(value, receipt["source_ip"]), "receipt_id": marker.stem,
                    "metadata_sha256": receipt["metadata_sha256"]}
        _require(_canonical(receipt) == _canonical(expected))
        return record
    except (ValueError, TypeError, KeyError, RecursionError):
        raise OSError("video receipt unavailable") from None
    except HTTPException as error:
        if error.status_code == 409:
            raise
        raise OSError("video receipt invalid") from None


def _verify_existing(root, record, value):
    folder = root / "objects" / record["object_id"]
    directories = []
    for path in (root.parent, root, root / "objects", folder, root / "receipts"):
        _plain(path)
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise OSError("video storage directory unavailable")
        directories.append((path, info))
    original = folder / "original.mp4"
    digest, original_stat = _read_verified(original, MAX_BYTES, digest_only=True)
    if digest != value["journal"]["sha256"] or original_stat.st_size != value["journal"]["bytes"]:
        raise OSError("stored video hash mismatch")
    metadata_path = original.with_name("metadata.json")
    encoded, metadata_stat = _read_verified(metadata_path, MAX_METADATA_BYTES)
    try:
        stored, _ = parse_metadata(encoded.decode("utf-8"))
    except (HTTPException, UnicodeError):
        raise OSError("stored video metadata invalid") from None
    if (hashlib.sha256(encoded).hexdigest() != record["receipt"]["metadata_sha256"]
            or _canonical(stored) != _canonical(value)):
        raise OSError("stored video metadata mismatch")
    verified = (*directories, (original, original_stat), (metadata_path, metadata_stat))
    _check_verified(verified)
    return verified


async def receive_capture_video(video: UploadFile, metadata: str, source_ip: str) -> tuple[dict, bool]:
    """Stream without a state lock; fence the final immutable receipt publication."""
    value, encoded = parse_metadata(metadata)
    if video.content_type != "video/mp4":
        _fail("video_mp4_required", 415)
    root = config.DATA_DIR / "capture-videos"
    marker_id = hashlib.sha256(value["journal"]["clip_id"].encode("ascii")).hexdigest()
    marker = root / "receipts" / f"{marker_id}.json"
    stream = None
    candidate = None
    try:
        with _current(value, source_ip):
            previous = _existing(marker, value)
        if previous is None:
            for directory in (root, root / "objects", root / "receipts"):
                _directory(directory)
            object_id = uuid.uuid4().hex
            folder = root / "objects" / object_id
            folder.mkdir(mode=0o700)
            stream = _private_file(folder / "original.mp4")
        digest, count, header = hashlib.sha256(), 0, bytearray()
        while block := await video.read(CHUNK_BYTES):
            count += len(block)
            if count > MAX_BYTES or count > value["journal"]["bytes"]:
                _fail("video_byte_budget_or_length", 413)
            digest.update(block)
            if len(header) < 12:
                header.extend(block[:12 - len(header)])
            if stream is not None:
                stream.write(block)
        if count != value["journal"]["bytes"] or digest.hexdigest() != value["journal"]["sha256"]:
            _fail("video_hash_or_length_mismatch")
        if len(header) < 12 or header[4:8] != b"ftyp":
            _fail("video_mp4_header_required", 415)
        # This is only an MP4 signature check; no codec/track claim is verified.
        if stream is not None:
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            stream = None
            with _private_file(folder / "metadata.json") as target:
                target.write(encoded)
                target.flush()
                os.fsync(target.fileno())
            _sync_directory(folder)
            _sync_directory(root / "objects")
            _sync_directory(root)
            record = {"object_id": object_id, "metadata_identity_sha256": hashlib.sha256(_canonical(value)).hexdigest(),
                      "receipt": {**_receipt_base(value, source_ip), "receipt_id": marker_id,
                                  "metadata_sha256": hashlib.sha256(encoded).hexdigest()}}
            descriptor, name = tempfile.mkstemp(prefix="pending-", suffix=".json", dir=marker.parent)
            candidate = Path(name)
            with os.fdopen(descriptor, "wb") as target:
                target.write(_canonical(record))
                target.flush()
                os.fsync(target.fileno())
        while True:
            # Hashing 128 MiB never holds the notification guard.
            verified = await run_in_threadpool(_verify_existing, root, previous if previous is not None else record, value)
            if previous is None:
                pending, pending_stat = await run_in_threadpool(_read_verified, candidate, 16 * 1024)
                if pending != _canonical(record):
                    raise OSError("video pending receipt changed")
                verified = (*verified, (candidate, pending_stat))
            with _current(value, source_ip):
                latest = _existing(marker, value)
                if latest is not None:
                    if previous != latest:
                        previous = latest
                        continue
                    _check_verified(verified)
                    _sync_directory(marker.parent)
                    return latest["receipt"], False
                if previous is not None or candidate is None:
                    raise OSError("stored video receipt disappeared")
                _check_verified(verified)
                try:
                    _publish_noreplace(candidate, marker)
                except FileExistsError:
                    previous = _existing(marker, value)
                    if previous is None:
                        raise OSError("conflicting video publication") from None
                    continue
                _sync_directory(marker.parent)
                return record["receipt"], True
    except (OSError, sqlite3.Error):
        _fail("video_storage_unavailable", 503)
    finally:
        if stream is not None:
            stream.close()
        if candidate is not None:
            candidate.unlink(missing_ok=True)
        # No receipt on failure; retain this request's incomplete/uncertain
        # object for diagnosis rather than inventing an empty successful upload.
