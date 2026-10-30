"""Native capture receipts bind JPEG uploads to canonical PNGs; no device/cloud."""

import hashlib
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from tests.test_work_bridge import client as client


def native_image():
    output = io.BytesIO()
    Image.new("RGB", (24, 32), (40, 180, 230)).save(output, "JPEG")
    return output.getvalue()


def provenance(raw, **changes):
    return {"schema": 1, "source_kind": "native_still",
            "capture_id": "11111111-1111-4111-8111-111111111111",
            "local_session_id": "22222222-2222-4222-8222-222222222222",
            "jpeg_sha256": hashlib.sha256(raw).hexdigest(), "width": 24, "height": 32,
            "page_index": 0, "rotation_degrees": 270,
            "image_timestamp_ns": 100, "result_timestamp_ns": 100, "frame_number": 3,
            "exposure_ns": 25_000_000, "sensitivity_iso": 100, "af_state": 0, "ae_state": 2,
            **changes}


def create_document(client):
    return client.post("/v1/documents", json={"title": "native capture"}).json()["document_id"]


def upload(client, document, raw, meta, **changes):
    data = {"page_index": 0, "image_rotation": 270, **changes}
    if meta is not None:
        data["capture_provenance"] = meta if isinstance(meta, str) else json.dumps(meta)
    return client.post(f"/v1/documents/{document}/pages", data=data,
                       files={"image": ("original.jpg", raw, "image/jpeg")})


def test_native_receipt_preserves_metadata_and_exact_canonical_hash_after_db_reinit(client):
    from app import main

    raw = native_image()
    meta = provenance(raw)
    document = create_document(client)
    response = upload(client, document, raw, meta)
    assert response.status_code == 201, response.text
    receipt = response.json()
    canonical = Path(receipt["image_path"])
    assert receipt["capture_provenance"] == meta
    assert receipt["canonical_image_sha256"] == hashlib.sha256(canonical.read_bytes()).hexdigest()
    with Image.open(canonical) as image:
        assert image.format == "PNG" and image.size == (32, 24)
    main.db.init_db()
    with main.db.connect() as conn:
        row = conn.execute("SELECT capture_metadata_json FROM pages WHERE document_id=?", (document,)).fetchone()
    assert json.loads(row[0]) == {"capture_provenance": meta,
                                  "canonical_image_sha256": receipt["canonical_image_sha256"]}
    assert list(canonical.parent.iterdir()) == [canonical]  # No raw-JPEG retention.


@pytest.mark.parametrize(("field", "value"), [
    ("schema", True), ("schema", "1"), ("schema", 1.0), ("schema", 2),
    ("source_kind", "unknown"), ("capture_id", "AAAAAAAA-1111-4111-8111-111111111111"),
    ("local_session_id", "bad"), ("jpeg_sha256", "A" * 64),
    ("width", True), ("width", "24"), ("height", 32.0), ("width", 2**31),
    ("page_index", -1), ("rotation_degrees", 360), ("image_timestamp_ns", 0),
    ("result_timestamp_ns", 101), ("frame_number", -1), ("frame_number", 2**63),
    ("exposure_ns", "25000000"), ("sensitivity_iso", 2**31),
    ("af_state", False), ("ae_state", -1),
    ("width", 25), ("height", 33), ("page_index", 1), ("rotation_degrees", 0),
    ("jpeg_sha256", "0" * 64),
])
def test_invalid_native_identity_has_no_persisted_image_or_page(client, field, value):
    from app import main

    raw = native_image()
    document = create_document(client)
    response = upload(client, document, raw, provenance(raw, **{field: value}))
    assert response.status_code == 400, response.text
    assert list(main.IMAGE_DIR.iterdir()) == []
    with main.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 0


@pytest.mark.parametrize("change", ["missing_null", "extra", "no_result", "no_image", "oversized", "duplicate"])
def test_schema_requires_every_key_and_consistent_native_result(client, change):
    raw = native_image()
    meta = provenance(raw)
    if change == "missing_null":
        del meta["af_state"]
    elif change == "extra":
        meta["physical_page_turn"] = 1
    elif change == "no_result":
        meta["result_timestamp_ns"] = None
    elif change == "no_image":
        meta["image_timestamp_ns"] = None
    elif change == "oversized":
        meta = " " * 8192 + json.dumps(meta)
    else:
        meta = json.dumps(meta)[:-1] + ', "schema":1}'
    response = upload(client, create_document(client), raw, meta)
    assert response.status_code == 400, response.text


def test_native_unknown_result_values_remain_null_without_inference(client):
    raw = native_image()
    meta = provenance(raw, **dict.fromkeys(("image_timestamp_ns", "result_timestamp_ns", "frame_number",
                                          "exposure_ns", "sensitivity_iso", "af_state", "ae_state")))
    receipt = upload(client, create_document(client), raw, meta).json()
    assert receipt["capture_provenance"] == meta


def test_same_native_retry_returns_unchanged_receipt_even_during_review(client, monkeypatch):
    from app import main

    document, raw = create_document(client), native_image()
    meta = provenance(raw)
    first = upload(client, document, raw, meta, ocr_text="original text").json()
    with main.db.connect() as conn:
        conn.execute("INSERT INTO exam_sessions(document_id,status) VALUES(?, 'reviewing')", (document,))
        conn.commit()
        before = dict(conn.execute("SELECT * FROM pages WHERE document_id=?", (document,)).fetchone())
    paths = {p.name: p.stat().st_mtime_ns for p in main.IMAGE_DIR.iterdir()}
    monkeypatch.setattr(main.Image.Image, "save", lambda *a, **kw: pytest.fail("native replay created a new image"))
    retry = upload(client, document, raw, meta, ocr_text="changed retry text")
    assert retry.status_code == 201, retry.text
    assert retry.json()["image_path"] == first["image_path"]
    assert retry.json()["canonical_image_sha256"] == first["canonical_image_sha256"]
    with main.db.connect() as conn:
        assert dict(conn.execute("SELECT * FROM pages WHERE document_id=?", (document,)).fetchone()) == before
    assert {p.name: p.stat().st_mtime_ns for p in main.IMAGE_DIR.iterdir()} == paths


def test_capture_id_cannot_change_metadata_or_repair_corrupt_canonical_on_retry(client):
    document, raw = create_document(client), native_image()
    meta = provenance(raw)
    first = upload(client, document, raw, meta).json()
    response = upload(client, document, raw, provenance(raw, frame_number=4))
    assert response.status_code == 409
    path = Path(first["image_path"])
    path.write_bytes(b"corrupt saved PNG")
    response = upload(client, document, raw, meta)
    assert response.status_code == 409
    assert path.read_bytes() == b"corrupt saved PNG"


def test_new_native_capture_replaces_atomically_and_legacy_replacement_clears_metadata(client):
    from app import main

    document, raw = create_document(client), native_image()
    first = upload(client, document, raw, provenance(raw)).json()
    replacement = provenance(raw, capture_id="33333333-3333-4333-8333-333333333333")
    response = upload(client, document, raw, replacement)
    assert response.status_code == 201 and response.json()["replaced"] is True
    assert response.json()["capture_provenance"] == replacement
    assert not Path(first["image_path"]).exists()
    old = response.json()
    with main.db.connect() as conn:
        conn.execute("INSERT INTO exam_sessions(document_id,status) VALUES(?, 'reviewing')", (document,))
        conn.commit()
    denied = upload(client, document, raw, provenance(raw, capture_id="44444444-4444-4444-8444-444444444444"))
    assert denied.status_code == 409
    assert Path(old["image_path"]).exists()
    with main.db.connect() as conn:
        conn.execute("DELETE FROM exam_sessions WHERE document_id=?", (document,))
        conn.commit()
    legacy = upload(client, document, raw, None)
    assert legacy.status_code == 201
    assert legacy.json()["capture_provenance"] is None and legacy.json()["canonical_image_sha256"] is None
    with main.db.connect() as conn:
        assert conn.execute("SELECT capture_metadata_json FROM pages WHERE document_id=?", (document,)).fetchone()[0] is None


def test_native_capture_cannot_claim_png_bytes_or_a_text_only_page(client):
    raw = native_image()
    output = io.BytesIO()
    Image.new("RGB", (24, 32)).save(output, "PNG")
    png = output.getvalue()
    document = create_document(client)
    assert upload(client, document, png, provenance(png)).status_code == 400
    result = client.post(f"/v1/documents/{document}/pages", data={"page_index": 0, "ocr_text": "text",
        "image_rotation": 270, "capture_provenance": json.dumps(provenance(raw))})
    assert result.status_code == 400


@pytest.mark.parametrize("elsewhere", ["page", "document"])
def test_native_id_cannot_be_rebound_to_another_current_page_or_document(client, elsewhere):
    from app import main

    document, raw = create_document(client), native_image()
    first = upload(client, document, raw, provenance(raw)).json()
    target = create_document(client) if elsewhere == "document" else document
    page = 1 if elsewhere == "page" else 0
    result = upload(client, target, raw, provenance(raw, page_index=page), page_index=page)
    assert result.status_code == 409
    assert list(main.IMAGE_DIR.iterdir()) == [Path(first["image_path"])]
    with main.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 1


@pytest.mark.parametrize("elsewhere", ["page", "document"])
def test_native_exact_replay_checks_all_current_rows_for_restored_id_collisions(client, monkeypatch, elsewhere):
    from app import main

    document, raw = create_document(client), native_image()
    first_meta = provenance(raw)
    first = upload(client, document, raw, first_meta).json()
    target = create_document(client) if elsewhere == "document" else document
    page = 1 if elsewhere == "page" else 0
    other_meta = provenance(raw, capture_id="33333333-3333-4333-8333-333333333333", page_index=page)
    other = upload(client, target, raw, other_meta, page_index=page).json()
    restored = {"capture_provenance": {**other_meta, "capture_id": first_meta["capture_id"]},
                "canonical_image_sha256": other["canonical_image_sha256"]}
    with main.db.connect() as conn:
        # A pre-existing restored duplicate is a conflict, even for an exact replay of the first row.
        conn.execute("UPDATE pages SET capture_metadata_json=? WHERE document_id=? AND page_index=?",
                     (json.dumps(restored), target, page))
        conn.commit()
        before = [dict(row) for row in conn.execute("SELECT * FROM pages ORDER BY id")]
    paths = {p.name: p.stat().st_mtime_ns for p in main.IMAGE_DIR.iterdir()}
    monkeypatch.setattr(main.Image.Image, "save", lambda *a, **kw: pytest.fail("conflicting replay created an image"))
    result = upload(client, document, raw, first_meta)
    assert result.status_code == 409, result.text
    with main.db.connect() as conn:
        assert [dict(row) for row in conn.execute("SELECT * FROM pages ORDER BY id")] == before
    assert {p.name: p.stat().st_mtime_ns for p in main.IMAGE_DIR.iterdir()} == paths
    assert Path(first["image_path"]).is_file() and Path(other["image_path"]).is_file()


def test_native_replacement_db_failure_keeps_old_png_and_metadata(client, monkeypatch):
    from app import main

    document, raw = create_document(client), native_image()
    first = upload(client, document, raw, provenance(raw)).json()
    original_connect = main.db.connect
    with original_connect() as conn:
        before = dict(conn.execute("SELECT * FROM pages WHERE document_id=?", (document,)).fetchone())

    class FailedUpdate:
        def __init__(self):
            self.connection = original_connect()

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def execute(self, sql, *args):
            if sql.startswith("UPDATE pages"):
                raise main.db.sqlite3.OperationalError("local write failure")
            return self.connection.execute(sql, *args)

    monkeypatch.setattr(main.db, "connect", FailedUpdate)
    with pytest.raises(main.db.sqlite3.OperationalError, match="local write failure"):
        upload(client, document, raw, provenance(raw, capture_id="33333333-3333-4333-8333-333333333333"))
    with original_connect() as conn:
        assert dict(conn.execute("SELECT * FROM pages WHERE document_id=?", (document,)).fetchone()) == before
    assert list(main.IMAGE_DIR.iterdir()) == [Path(first["image_path"])]


@pytest.mark.parametrize("field", ["image_timestamp_ns", "result_timestamp_ns", "frame_number", "exposure_ns",
                                  "sensitivity_iso", "af_state", "ae_state"])
@pytest.mark.parametrize("bad", [True, 1.0, "1"])
def test_every_nullable_native_integer_is_strict(field, bad):
    from app.capture_provenance import validate_capture_provenance

    with pytest.raises(ValueError):
        validate_capture_provenance(provenance(native_image(), **{field: bad}))


def test_native_integer_bounds_and_upload_json_size_are_inclusive(client):
    from app.capture_provenance import validate_capture_provenance

    meta = provenance(native_image(), image_timestamp_ns=2**63 - 1, result_timestamp_ns=2**63 - 1,
                      frame_number=2**63 - 1, exposure_ns=2**63 - 1,
                      sensitivity_iso=2**31 - 1, af_state=2**31 - 1, ae_state=2**31 - 1)
    assert validate_capture_provenance(meta) == meta
    encoded = json.dumps(meta)
    assert upload(client, create_document(client), native_image(), encoded + " " * (8192 - len(encoded))).status_code == 201
    assert upload(client, create_document(client), native_image(), "").status_code == 400
