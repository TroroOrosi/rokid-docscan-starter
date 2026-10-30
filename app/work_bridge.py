"""Durable phone-local handoff to a Work transport.

This is an authenticated HTTP boundary, not an MCP/OAuth implementation. It
does not start ChatGPT, upload to Drive, verify model selection, or prove that
a model visually read an image. A cloud-reachable, authorized Work transport
still has to be connected before physical use.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager

from PIL import Image
from pathlib import Path


class WorkPending(RuntimeError):
    """An immutable job is waiting; never fall through to another paid solver."""


class WorkConflict(ValueError):
    """A handoff does not belong to the immutable job or its current stage."""


class WorkBrowserResultRejected(ValueError):
    """A completed browser reply failed validation; never silently keep waiting."""


class WorkReadabilityRejected(WorkBrowserResultRejected):
    """A known browser reply attempted answers from unreadable/uncertain pages."""


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _receipt_matches(claim: object, expected: str | None) -> bool:
    # token_urlsafe(24) produces 32 ASCII characters. Validate before the
    # constant-time str comparison, which rejects non-ASCII with TypeError.
    return (type(claim) is str and re.fullmatch(r"[A-Za-z0-9_-]{32}", claim) is not None
            and type(expected) is str and re.fullmatch(r"[A-Za-z0-9_-]{32}", expected) is not None
            and secrets.compare_digest(claim, expected))


def _identifier(value, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", value):
        raise ValueError(f"invalid {field}")
    return value


def browser_source_name(source: dict) -> str:
    """Stable flat names for the browser's unchanged canonical originals."""
    if "page_number" in source:
        if source["mime_type"] != "image/png":
            raise WorkConflict("browser image delivery requires canonical PNG originals")
        return f"page_{source['page_number']:03d}.png"
    suffix = {"audio/wav": "wav", "audio/mpeg": "mp3", "audio/mp4": "m4a",
              "audio/ogg": "ogg", "audio/flac": "flac"}[source["mime_type"]]
    return f"original_audio.{suffix}"


def configured_work_store() -> WorkStore:
    from . import config  # noqa: PLC0415

    profiles = tuple(p.strip() for p in os.environ.get("ROKID_CAPTURE_VALIDATED_PROFILES", "").split(",") if p.strip())
    return WorkStore(config.DATA_DIR, validated_profiles=profiles)


class WorkStore:
    """SQLite keeps originals, retrieval receipts and answers in atomic commits.

    The database lives on the phone under DATA_DIR. It is separate from the
    existing document schema, and no schema/credential migration is performed.
    """

    def __init__(self, directory: Path, *, validated_profiles=()):
        self.path = Path(directory) / "work-jobs.db"
        if (not isinstance(validated_profiles, (tuple, list, set, frozenset))
                or any(type(p) is not str or not p.strip() or len(p) > 80 for p in validated_profiles)):
            raise ValueError("invalid caller-validated capture profiles")
        self.validated_profiles = tuple(validated_profiles)

    @contextmanager
    def _connect(self):
        conn = self._new_connection()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _new_connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                seq INTEGER PRIMARY KEY, job_id TEXT NOT NULL UNIQUE,
                session_id INTEGER NOT NULL, conversation_key TEXT NOT NULL,
                stage TEXT NOT NULL, generation INTEGER NOT NULL,
                identity_json TEXT NOT NULL, manifest_sha256 TEXT NOT NULL,
                spec_json TEXT NOT NULL, conversation_id TEXT,
                result_json TEXT, submission_json TEXT,
                UNIQUE(session_id, stage)
            );
            CREATE TABLE IF NOT EXISTS sources (
                job_id TEXT NOT NULL, source_id TEXT NOT NULL,
                data BLOB NOT NULL, sha256 TEXT NOT NULL, receipt TEXT,
                PRIMARY KEY(job_id, source_id)
            );
            CREATE TABLE IF NOT EXISTS inspections (
                job_id TEXT NOT NULL, source_id TEXT NOT NULL,
                request_json TEXT NOT NULL, result_json TEXT,
                PRIMARY KEY(job_id, source_id)
            );
            CREATE TABLE IF NOT EXISTS inspection_images (
                job_id TEXT NOT NULL, source_id TEXT NOT NULL, image_id TEXT NOT NULL,
                data BLOB NOT NULL, sha256 TEXT NOT NULL, receipt TEXT,
                PRIMARY KEY(job_id, source_id, image_id)
            );
        """)
        return conn

    def enqueue(self, *, session_id: int, conversation_key: str, stage: str,
                sources: list[dict], system: str, prompt: str, question_ids=(),
                device_id: str | None = None, generation: int = 0,
                requested_settings: dict | None = None) -> dict:
        if type(session_id) is not int or session_id < 1:
            raise ValueError("invalid session identity")
        _identifier(conversation_key, "conversation key")
        if stage not in ("single", "reading", "listening"):
            raise ValueError("invalid booklet stage")
        if type(generation) is not int or generation < 0:
            raise ValueError("invalid generation")
        if device_id is not None:
            _identifier(device_id, "device identity")
        if not isinstance(sources, list) or not sources:
            raise ValueError("the original images are required")
        manifest, seen = [], set()
        for source in sources:
            source_id = _identifier(source.get("source_id"), "source identity")
            data, mime = source.get("data"), source.get("mime_type")
            if (source_id in seen or not isinstance(data, bytes) or not data
                    or mime not in ("image/png", "image/jpeg", "audio/wav", "audio/mpeg", "audio/mp4", "audio/ogg", "audio/flac")):
                raise ValueError("invalid or duplicate original")
            seen.add(source_id)
            item = {"source_id": source_id, "mime_type": mime, "sha256": _sha(data), "bytes": len(data)}
            if mime.startswith("image/"):
                number = source.get("page_number")
                if type(number) is not int or number < 1:
                    raise ValueError("invalid original page number")
                item["page_number"] = number
            manifest.append(item)
        numbers = [item["page_number"] for item in manifest if "page_number" in item]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError("original page order must be complete and dense")
        if not numbers:
            raise ValueError("the original images are required")
        if stage == "reading" and len(numbers) != len(manifest):
            raise ValueError("reading starts before the original audio")
        if (not isinstance(system, str) or not isinstance(prompt, str)
                or not isinstance(question_ids, (list, tuple))
                or any(not isinstance(q, str) or not q for q in question_ids)
                or len(set(question_ids)) != len(question_ids)):
            raise ValueError("invalid Work instruction or question identities")
        requested_settings = requested_settings or {"model": "gpt-6.1-sol", "effort": "xhigh", "speed": "fast"}
        if (set(requested_settings) != {"model", "effort", "speed"}
                or any(not isinstance(v, str) or not v.strip() for v in requested_settings.values())):
            raise ValueError("invalid requested model settings")
        identity = {"session_id": session_id, "device_id": device_id, "generation": generation,
                    "conversation_key": conversation_key, "stage": stage, "sources": manifest,
                    "system": system, "prompt": prompt, "question_ids": list(question_ids),
                    "requested_settings": requested_settings}
        encoded = _json(identity)
        job_id, manifest_sha256 = _sha(encoded.encode()), _sha(_json(manifest).encode())
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute("SELECT * FROM jobs WHERE session_id=? AND stage=?", (session_id, stage)).fetchone()
            if previous:
                if previous["identity_json"] != encoded:
                    raise WorkConflict("the existing job identity changed; nothing was requeued")
                return self._public(conn, previous)
            previous_job_id, conversation_id, new_ids = None, None, [p["source_id"] for p in manifest]
            if stage == "listening":
                prior = conn.execute("SELECT * FROM jobs WHERE session_id=? AND stage='reading'", (session_id,)).fetchone()
                if not prior or prior["result_json"] is None or prior["conversation_key"] != conversation_key:
                    raise WorkConflict("the completed reading conversation is required first")
                old = json.loads(prior["spec_json"])
                if ([p for p in manifest if "page_number" in p] != old["sources"]
                        or prior["generation"] != generation or old["device_id"] != device_id):
                    raise WorkConflict("the listening original image identity changed")
                new_ids = [p["source_id"] for p in manifest if "page_number" not in p]
                if not new_ids or not question_ids:
                    raise WorkConflict("the completed original audio and pending question slots are required")
                previous_job_id, conversation_id = prior["job_id"], prior["conversation_id"]
            spec = {**identity, "job_id": job_id, "manifest_sha256": manifest_sha256,
                    "previous_job_id": previous_job_id, "new_source_ids": new_ids}
            conn.execute("INSERT INTO jobs(job_id,session_id,conversation_key,stage,generation,identity_json,"
                         "manifest_sha256,spec_json,conversation_id) VALUES(?,?,?,?,?,?,?,?,?)",
                         (job_id, session_id, conversation_key, stage, generation, encoded,
                          manifest_sha256, _json(spec), conversation_id))
            for source, item in zip(sources, manifest, strict=True):
                conn.execute("INSERT INTO sources(job_id,source_id,data,sha256) VALUES(?,?,?,?)",
                             (job_id, item["source_id"], source["data"], item["sha256"]))
            return self._public(conn, self._row(conn, job_id))

    @staticmethod
    def _row(conn, job_id):
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError("Work job not found")
        return row

    def _public(self, conn, row):
        spec = json.loads(row["spec_json"])
        submitted = json.loads(row["submission_json"]) if row["submission_json"] else {}
        deliveries = [{key: item[key] for key in ("source_id", "sha256", "delivery", "inspection_manifest_sha256")
                       if key in item} for item in submitted.get("source_receipts", [])]
        qualities = {entry["source_id"]: json.loads(entry["result_json"])
                     for entry in conn.execute("SELECT source_id,result_json FROM inspections "
                                               "WHERE job_id=? AND result_json IS NOT NULL", (row["job_id"],))}
        return {**spec, "conversation_id": row["conversation_id"],
                "status": "completed" if row["result_json"] is not None else "pending",
                "model_selection_verified": False, "visual_reading_verified": False,
                "quality": qualities,
                "delivery_acknowledgements": {"kind": "transport_acknowledgement_claim", "sources": deliveries},
                **({"browser_review": submitted["browser_review"]} if "browser_review" in submitted else {}),
                "transport": "phone_local_browser" if "browser_review" in submitted else "phone_authenticated_http",
                "cloud_transport_connected": False}

    def get(self, job_id: str) -> dict:
        with self._connect() as conn:
            return self._public(conn, self._row(conn, job_id))

    def list_jobs(self, *, cursor: int = 0, limit: int = 100) -> dict:
        if type(cursor) is not int or not 0 <= cursor < 2**63 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid Work job pagination")
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM jobs WHERE seq>? AND result_json IS NULL ORDER BY seq LIMIT ?",
                                (cursor, limit + 1)).fetchall()
            return {"jobs": [self._public(conn, row) for row in rows[:limit]],
                    "next_cursor": rows[limit - 1]["seq"] if len(rows) > limit else None}

    def read_source(self, job_id: str, source_id: str) -> tuple[bytes, dict]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            job = self._public(conn, self._row(conn, job_id))
            row = conn.execute("SELECT * FROM sources WHERE job_id=? AND source_id=?", (job_id, source_id)).fetchone()
            if row is None:
                raise KeyError("Work original not found")
            original = row["data"]
            if _sha(original) != row["sha256"]:
                raise WorkConflict("the stored original hash changed")
            receipt = row["receipt"] or secrets.token_urlsafe(24)
            conn.execute("UPDATE sources SET receipt=? WHERE job_id=? AND source_id=?", (receipt, job_id, source_id))
            item = next(p for p in job["sources"] if p["source_id"] == source_id)
            return original, {**item, "receipt": receipt}

    @staticmethod
    def _prepared_quality(conn, job: dict, source_id: str):
        from .capture_quality import prepare_captured_image  # noqa: PLC0415

        item = next((p for p in job["sources"] if p["source_id"] == source_id and "page_number" in p), None)
        row = conn.execute("SELECT data FROM sources WHERE job_id=? AND source_id=?",
                           (job["job_id"], source_id)).fetchone()
        if item is None or row is None:
            raise KeyError("Work image not found")
        if _sha(row["data"]) != item["sha256"]:
            raise WorkConflict("the inspection original hash changed")
        # These are the server's sealed source/order identities, not invented
        # hardware capture metadata. Phone PNGs have already been oriented.
        return prepare_captured_image(row["data"], session_id=str(job["session_id"]),
                                       capture_id=f"{job['job_id'][:24]}:{source_id}",
                                       generation=job["generation"], page_turn=item["page_number"] - 1,
                                       revision=1, rotation=0)

    def quality_request(self, job_id: str, source_id: str) -> dict:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            job = self._public(conn, self._row(conn, job_id))
            cached = conn.execute("SELECT request_json FROM inspections WHERE job_id=? AND source_id=?",
                                  (job_id, source_id)).fetchone()
            if cached:
                request = json.loads(cached["request_json"])
            else:
                prepared = self._prepared_quality(conn, job, source_id)
                request = prepared.request
                conn.execute("INSERT INTO inspections(job_id,source_id,request_json) VALUES(?,?,?)",
                             (job_id, source_id, _json(request)))
                for image in prepared.images:
                    conn.execute("INSERT INTO inspection_images(job_id,source_id,image_id,data,sha256) VALUES(?,?,?,?,?)",
                                 (job_id, source_id, image.image_id, image.data, _sha(image.data)))
            return {**request, "identity_origin": "server_sealed_source_and_order",
                    "inspection_manifest_sha256": _sha(_json(request).encode()),
                    "validated_profile_ids": list(self.validated_profiles),
                    "requested_settings": {"model": "gpt-6-luna", "effort": "low", "speed": "fast"},
                    "model_selection_verified": False}

    def read_quality_image(self, job_id: str, source_id: str, image_id: str) -> tuple[bytes, dict]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM inspection_images WHERE job_id=? AND source_id=? AND image_id=?",
                               (job_id, source_id, image_id)).fetchone()
            if row is None:
                raise KeyError("inspection image not found; obtain its request first")
            if _sha(row["data"]) != row["sha256"]:
                raise WorkConflict("the inspection image hash changed")
            receipt = row["receipt"] or secrets.token_urlsafe(24)
            conn.execute("UPDATE inspection_images SET receipt=? WHERE job_id=? AND source_id=? AND image_id=?",
                         (receipt, job_id, source_id, image_id))
            return row["data"], {"image_id": image_id, "sha256": row["sha256"], "receipt": receipt}

    def submit_quality(self, job_id: str, source_id: str, *, response: object,
                       image_receipts: list[dict]) -> dict:
        from .capture_quality import assess_captured_image  # noqa: PLC0415

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._row(conn, job_id)
            job = self._public(conn, row)
            cached = conn.execute("SELECT * FROM inspections WHERE job_id=? AND source_id=?",
                                  (job_id, source_id)).fetchone()
            if cached is None:
                raise WorkConflict("the original inspection request is required")
            prepared = self._prepared_quality(conn, job, source_id)
            if prepared.request != json.loads(cached["request_json"]):
                raise WorkConflict("the original inspection policy changed")
            self._check_image_receipts(conn, job_id, source_id, image_receipts)
            assessed = assess_captured_image(prepared, response, current_identity=prepared.identity,
                                             validated_profiles=self.validated_profiles)
            encoded = _json(assessed)
            if row["result_json"] is not None and cached["result_json"] != encoded:
                raise WorkConflict("the Work answer was already committed")
            conn.execute("UPDATE inspections SET result_json=? WHERE job_id=? AND source_id=?",
                         (encoded, job_id, source_id))
            return assessed

    @staticmethod
    def _check_image_receipts(conn, job_id: str, source_id: str, image_receipts: list[dict]) -> None:
        delivered = conn.execute("SELECT image_id,sha256,receipt FROM inspection_images "
                                 "WHERE job_id=? AND source_id=?", (job_id, source_id)).fetchall()
        if (not delivered or not isinstance(image_receipts, list) or len(image_receipts) != len(delivered)
                or any(not isinstance(item, dict) or type(item.get("image_id")) is not str for item in image_receipts)
                or {item["image_id"] for item in image_receipts} != {item["image_id"] for item in delivered}):
            raise WorkConflict("every inspection image needs its own retrieval acknowledgement")
        by_id = {item["image_id"]: item for item in image_receipts}
        for image in delivered:
            claimed = by_id[image["image_id"]]
            if (set(claimed) != {"image_id", "sha256", "receipt"}
                    or claimed.get("sha256") != image["sha256"]
                    or not _receipt_matches(claimed.get("receipt"), image["receipt"])):
                raise WorkConflict("an inspection image receipt does not match")

    def result(self, job_id: str) -> dict | None:
        with self._connect() as conn:
            encoded = self._row(conn, job_id)["result_json"]
            return json.loads(encoded) if encoded is not None else None

    def submit_result(self, job_id: str, *, manifest_sha256: str, generation: int,
                      conversation_id: str, source_receipts: list[dict], result: dict) -> dict:
        """External/MCP results retain the calibrated all-native-tile admission."""
        return self._submit_result(job_id, manifest_sha256=manifest_sha256, generation=generation,
            conversation_id=conversation_id, source_receipts=source_receipts, result=result)

    def submit_browser_result(self, job_id: str, *, manifest_sha256: str, generation: int,
                              conversation_id: str, source_receipts: list[dict], result: dict,
                              extraction: dict, readability: list[dict]) -> dict:
        """Internal local-CDP path; no HTTP request can select this admission.

        Full-original readability is an uncalibrated model judgement, never an
        eligible capture profile or proof of character accuracy/visual reading.
        """
        return self._submit_result(job_id, manifest_sha256=manifest_sha256, generation=generation,
            conversation_id=conversation_id, source_receipts=source_receipts, result=result,
            browser_evidence=(extraction, readability))

    def _submit_result(self, job_id: str, *, manifest_sha256: str, generation: int,
                       conversation_id: str, source_receipts: list[dict], result: dict,
                       browser_evidence=None) -> dict:
        _identifier(conversation_id, "Work conversation identity")
        encoded = _json(result)
        if len(encoded.encode()) > 8 * 1024 * 1024:
            raise ValueError("the answer result is too large")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._row(conn, job_id)
            job = self._public(conn, row)
            if (manifest_sha256 != job["manifest_sha256"] or type(generation) is not int
                    or generation != job["generation"]):
                raise WorkConflict("Work result source identity mismatch")
            if job["conversation_id"] and conversation_id != job["conversation_id"]:
                raise WorkConflict("the Work conversation changed")
            expected = job["new_source_ids"]
            if (not isinstance(source_receipts, list) or len(source_receipts) != len(expected)
                    or any(not isinstance(item, dict) or type(item.get("source_id")) is not str
                           for item in source_receipts)
                    or {item.get("source_id") for item in source_receipts} != set(expected)):
                raise WorkConflict("every original must have its own retrieval acknowledgement")
            claims = []
            for item in source_receipts:
                source = conn.execute("SELECT * FROM sources WHERE job_id=? AND source_id=?",
                                      (job_id, item["source_id"])).fetchone()
                if source is None or item.get("sha256") != source["sha256"]:
                    raise WorkConflict("an original retrieval receipt does not match")
                delivery = item.get("delivery", "original_bytes")
                if delivery == "original_bytes":
                    if (set(item) - {"source_id", "sha256", "delivery", "receipt"}
                            or not _receipt_matches(item.get("receipt"), source["receipt"])):
                        raise WorkConflict("an original retrieval receipt does not match")
                elif delivery == "native_tiles":
                    original = next(p for p in job["sources"] if p["source_id"] == item["source_id"])
                    packet = conn.execute("SELECT request_json FROM inspections WHERE job_id=? AND source_id=?",
                                          (job_id, item["source_id"])).fetchone()
                    if (set(item) != {"source_id", "sha256", "delivery", "inspection_manifest_sha256", "image_receipts"}
                            or "page_number" not in original or packet is None
                            or item["inspection_manifest_sha256"] != _sha(packet["request_json"].encode())):
                        raise WorkConflict("the native tile packet does not match its original")
                    self._check_image_receipts(conn, job_id, item["source_id"], item["image_receipts"])
                else:
                    raise WorkConflict("unknown original image delivery kind")
                claims.append({**item, "delivery": delivery})
            self._validate_result(job, result)
            browser_review = (self._browser_review(conn, job, *browser_evidence)
                              if browser_evidence is not None else None)
            if browser_review is not None:
                if not self._non_answering_stop(result):
                    if len(browser_review["images"]) != sum("page_number" in p for p in job["sources"]):
                        raise WorkBrowserResultRejected("every browser original requires its original readability review")
                    if any(p["status"] != "readable" for p in browser_review["images"]):
                        if any(item.get("status") == "ready" for item in result["questions"]):
                            raise WorkReadabilityRejected("browser readability review does not support answering")
                        raise WorkBrowserResultRejected("every browser original must be readable before accepting answers")
            elif not self._non_answering_stop(result):
                for source in job["sources"]:
                    if "page_number" not in source:
                        continue
                    quality = job["quality"].get(source["source_id"])
                    if job["stage"] == "listening":
                        prior = self._public(conn, self._row(conn, job["previous_job_id"]))
                        quality = prior["quality"].get(source["source_id"])
                    if (not quality or quality["decision"] != "eligible"
                            or quality.get("evidence", {}).get("profile_id") not in self.validated_profiles):
                        raise WorkConflict("every original image requires eligible source-bound quality evidence")
            # These are transport acknowledgements, not proof that the model saw
            # the pixels. A local original GET alone never records cloud delivery.
            submission = _json({"result": result, "conversation_id": conversation_id,
                                "source_receipts": sorted(claims, key=lambda item: item["source_id"]),
                                **({"browser_review": browser_review} if browser_review is not None else {})})
            if row["result_json"] is not None:
                if row["submission_json"] != submission:
                    raise WorkConflict("the Work answer was already committed")
                return job
            conn.execute("UPDATE jobs SET result_json=?,submission_json=?,conversation_id=? WHERE job_id=?",
                         (encoded, submission, conversation_id, job_id))
            return self._public(conn, self._row(conn, job_id))

    def _browser_review(self, conn, job: dict, extraction: dict, readability: list[dict]) -> dict:
        expected = []
        for source in job["sources"]:
            if source["source_id"] not in job["new_source_ids"]:
                continue
            item = {"source_id": source["source_id"], "file_name": browser_source_name(source),
                    "sha256": source["sha256"]}
            if "page_number" in source:
                raw = conn.execute("SELECT data FROM sources WHERE job_id=? AND source_id=?",
                                   (job["job_id"], source["source_id"])).fetchone()["data"]
                if _sha(raw) != source["sha256"]:
                    raise WorkConflict("the stored original hash changed")
                try:
                    with Image.open(io.BytesIO(raw)) as image:
                        if image.format != "PNG":
                            raise ValueError("not canonical PNG")
                        item.update(width=image.width, height=image.height)
                        image.verify()
                except (OSError, ValueError) as error:
                    raise WorkConflict("the canonical original image is unavailable") from error
            expected.append(item)
        if (not isinstance(extraction, dict) or set(extraction) != {"status", "files"}
                or extraction["status"] != "ok" or extraction["files"] != expected
                or any(type(item.get(axis)) is not int for item in extraction["files"]
                       for axis in ("width", "height") if axis in item)):
            raise WorkBrowserResultRejected("browser extraction must match every original hash, dimension and order")
        if job["stage"] == "listening":
            if readability != []:
                raise WorkBrowserResultRejected("listening must retain the original image review")
            prior = self._public(conn, self._row(conn, job["previous_job_id"]))
            images = prior.get("browser_review", {}).get("images", [])
        else:
            originals = [p for p in expected if "width" in p]
            if (not isinstance(readability, list) or len(readability) != len(originals)
                    or any(not isinstance(review, dict) or set(review) != {
                        "source_id", "status", "image_viewer_used", "reasons"}
                           for review in readability)):
                raise WorkBrowserResultRejected("every original requires its own browser readability review")
            images = []
            for original, review in zip(originals, readability, strict=True):
                reasons, status = review["reasons"], review["status"]
                if (review["source_id"] != original["source_id"]
                        or status not in ("readable", "unreadable", "uncertain")
                        or type(review["image_viewer_used"]) is not bool
                        or (status == "readable" and not review["image_viewer_used"])
                        or not isinstance(reasons, list) or len(reasons) > 16
                        or any(not isinstance(reason, str) or not reason.strip() or len(reason) > 500
                               for reason in reasons)
                        or (status != "readable" and not reasons)):
                    raise WorkBrowserResultRejected("invalid or incomplete browser readability review")
                images.append({"source_id": original["source_id"], "source_sha256": original["sha256"],
                               "width": original["width"], "height": original["height"],
                               **{key: review[key] for key in ("status", "image_viewer_used", "reasons")}})
        return {"kind": "uncalibrated_browser_readability", "calibrated": False,
                "visual_reading_verified": False, "images": images}

    @staticmethod
    def _non_answering_stop(result: dict) -> bool:
        # Called only after validation. A stop can describe unreadable material,
        # but cannot carry answers through extra blocks, derivations or diagrams.
        if set(result) != {"questions"}:
            return False
        fields = {"group", "label", "pages", "answer_no", "status", "answer",
                  "missing_material", "diagrams", "requires_audio", "question_id"}
        items = result["questions"]
        return (any(item.get("status") == "needs_input" for item in items)
                and all(set(item) <= fields
                        and item.get("status") in ("needs_input", "pending_audio")
                        and item.get("answer") == "" and item.get("diagrams", []) == []
                        and (item.get("status") != "needs_input"
                             or (isinstance(item.get("missing_material"), str)
                                 and bool(item["missing_material"].strip())))
                        for item in items))

    @staticmethod
    def _validate_result(job: dict, result: dict) -> None:
        from .solvers.chatgpt_web import _booklet_replies  # noqa: PLC0415

        items = result.get("questions") if isinstance(result, dict) else None
        if not isinstance(items, list) or not 1 <= len(items) <= 300:
            raise ValueError("a complete non-empty question list is required")
        page_count = sum("page_number" in source for source in job["sources"])
        numbers = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("invalid Work answer item")
            pages = item.get("pages")
            if (not isinstance(pages, list) or not pages
                    or any(type(p) is not int or not 1 <= p <= page_count for p in pages)):
                raise ValueError("each Work answer must identify its source pages")
            answer_no = item.get("answer_no", [])
            if not isinstance(answer_no, list) or any(type(n) is not int or n < 1 for n in answer_no):
                raise ValueError("invalid printed answer numbers")
            numbers.extend(answer_no)
        if len(numbers) != len(set(numbers)):
            raise ValueError("a printed answer number appears more than once")
        replies = _booklet_replies(result, subject=None, extras={}, stage=job["stage"],
                                   question_ids=job["question_ids"])
        if any(isinstance(answer, Exception) for _, answer in replies):
            raise ValueError("the Work reply contains an invalid answer")
