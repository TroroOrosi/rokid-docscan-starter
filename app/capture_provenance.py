"""Strict native-camera metadata; unknown values stay explicit nulls."""

from __future__ import annotations

import json
import re

_UUID = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
_SHA256 = r"[0-9a-f]{64}"
_INT32_MAX = 2**31 - 1
_INT64_MAX = 2**63 - 1
_NULLABLE_INTS = {
    "image_timestamp_ns": (1, _INT64_MAX), "result_timestamp_ns": (1, _INT64_MAX),
    "frame_number": (0, _INT64_MAX), "exposure_ns": (1, _INT64_MAX),
    "sensitivity_iso": (1, _INT32_MAX), "af_state": (0, _INT32_MAX), "ae_state": (0, _INT32_MAX),
}
_FIELDS = {"schema", "source_kind", "capture_id", "local_session_id", "jpeg_sha256",
           "width", "height", "page_index", "rotation_degrees", *_NULLABLE_INTS}


def _integer(value, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def validate_capture_provenance(value: object) -> dict:
    if type(value) is not dict or set(value) != _FIELDS:
        raise ValueError("capture_provenance requires exactly the schema 1 fields")
    if (type(value["schema"]) is not int or value["schema"] != 1
            or type(value["source_kind"]) is not str
            or value["source_kind"] not in ("native_still", "zsl_reprocess")):
        raise ValueError("unsupported capture_provenance schema or source kind")
    for key, pattern in (("capture_id", _UUID), ("local_session_id", _UUID), ("jpeg_sha256", _SHA256)):
        if type(value[key]) is not str or re.fullmatch(pattern, value[key]) is None:
            raise ValueError(f"invalid capture_provenance {key}")
    for key, minimum in (("width", 1), ("height", 1), ("page_index", 0)):
        if not _integer(value[key], minimum, _INT32_MAX):
            raise ValueError(f"invalid capture_provenance {key}")
    if type(value["rotation_degrees"]) is not int or value["rotation_degrees"] not in (0, 90, 180, 270):
        raise ValueError("invalid capture_provenance rotation_degrees")
    for key, (minimum, maximum) in _NULLABLE_INTS.items():
        if value[key] is not None and not _integer(value[key], minimum, maximum):
            raise ValueError(f"invalid capture_provenance {key}")
    result = value["result_timestamp_ns"]
    if result is not None and result != value["image_timestamp_ns"]:
        raise ValueError("native result timestamp does not match its image")
    if value["source_kind"] == "zsl_reprocess" and result is None:
        raise ValueError("ZSL provenance requires its matching source exposure")
    if result is None and any(value[key] is not None for key in _NULLABLE_INTS
                              if key not in ("image_timestamp_ns", "result_timestamp_ns")):
        raise ValueError("native result metadata requires a matching result timestamp")
    return dict(value)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate capture metadata key")
        result[key] = value
    return result


def parse_capture_provenance(text: str) -> dict:
    if len(text.encode("utf-8")) > 8192:
        raise ValueError("capture_provenance exceeds 8KiB")
    return validate_capture_provenance(json.loads(text, object_pairs_hook=_unique_object))


def validate_capture_metadata(value: object) -> dict:
    if type(value) is not dict or set(value) != {"capture_provenance", "canonical_image_sha256"}:
        raise ValueError("invalid saved capture metadata")
    sha = value["canonical_image_sha256"]
    if type(sha) is not str or re.fullmatch(_SHA256, sha) is None:
        raise ValueError("invalid canonical image hash")
    return {"capture_provenance": validate_capture_provenance(value["capture_provenance"]),
            "canonical_image_sha256": sha}


def parse_capture_metadata(text: str | None) -> dict | None:
    return None if text is None else validate_capture_metadata(json.loads(text, object_pairs_hook=_unique_object))
