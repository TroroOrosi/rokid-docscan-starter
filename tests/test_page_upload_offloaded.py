"""Turning an uploaded photo into the stored PNG must not stop the server.

Measured on the phone on 2026-11-15 with a real 4032x3024 photo: the PNG encoding alone takes 2.2 s. It ran on the
event loop, inside the database's write transaction, so for 40 pages every other request (the watcher's poll, the
glasses' state, the next upload) waited about 100 s in all (docs/whole-review-2026-11-14.md, C-9).
"""
import asyncio
import importlib
import io
import sqlite3

from fastapi.testclient import TestClient
from PIL import Image


def test_the_png_is_encoded_off_the_event_loop_and_outside_the_write_transaction(tmp_path, monkeypatch):
    monkeypatch.setenv("ROKID_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ROKID_API_KEY", raising=False)
    from app import config, db, main
    for module in (config, db, main):
        importlib.reload(module)
    main.ensure_dirs()
    main.db.init_db()
    client = TestClient(main.app)
    document = client.post("/v1/documents", json={"title": "t"}).json()["document_id"]
    seen = []
    save = Image.Image.save

    def watched(self, target, format=None, **options):
        if format == "PNG":
            try:
                asyncio.get_running_loop()
                on_loop = True
            except RuntimeError:
                on_loop = False
            other = sqlite3.connect(config.DB_PATH, timeout=0)
            try:
                other.execute("BEGIN IMMEDIATE")
                other.rollback()
                write_free = True
            except sqlite3.OperationalError:
                write_free = False
            finally:
                other.close()
            seen.append((on_loop, write_free))
        return save(self, target, format=format, **options)

    monkeypatch.setattr(Image.Image, "save", watched)
    photo = io.BytesIO()
    save(Image.new("RGB", (640, 480), (200, 190, 180)), photo, format="JPEG")

    response = client.post(f"/v1/documents/{document}/pages", data={"page_index": "0", "image_rotation": "270"},
                           files={"image": ("page.jpg", photo.getvalue(), "image/jpeg")})

    assert response.status_code == 201, response.text
    assert seen == [(False, True)], "encoded once, in a worker thread, while another writer could still take the database"
    with db.connect() as conn:
        stored = conn.execute("SELECT image_path FROM pages WHERE document_id = ?", (document,)).fetchone()["image_path"]
    with Image.open(stored) as upright:
        assert upright.size == (480, 640) and upright.format == "PNG"
