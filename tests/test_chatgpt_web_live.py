"""Opt-in live checks for the chatgpt-web route. Skipped without a browser.

Everything else in the suite stubs the page, which is what keeps the suite
offline and fast -- and is also why the stubs passed while five separate live
defects sat in the code. These run only when a signed-in debuggable Chrome is
reachable, and they cover the two things a stub cannot reach:

1. the server calls the solver from FastAPI's threadpool, and Playwright's sync
   API is bound to the thread that created it;
2. a deck solves problem after problem, which is where the flakes appeared.

Enable with a reachable CDP endpoint (see README), then::

    py -3.12 -m pytest tests/test_chatgpt_web_live.py -q
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from app.solvers.chatgpt_web import cdp_available
from tests.conftest import image_bytes, make_image

pytestmark = pytest.mark.skipif(
    cdp_available() is None,
    reason="no debuggable Chrome on the CDP endpoint; see README for the setup",
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ROKID_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-web")
    monkeypatch.delenv("ROKID_ALLOW_REAL_EXAM_SOLVE", raising=False)
    import app.config as config

    importlib.reload(config)
    import app.db as db

    importlib.reload(db)
    import app.main as main

    importlib.reload(main)
    main.ensure_dirs()
    main.db.init_db()
    return TestClient(main.app)


def _page(client, doc_id, index, text):
    r = client.post(
        f"/v1/documents/{doc_id}/pages",
        data={"page_index": index, "ocr_text": text},
        files={"image": (f"p{index}.png", image_bytes(make_image(120, 160)), "image/png")},
    )
    assert r.status_code == 201, r.text


def test_a_deck_solves_through_the_server_threadpool(client):
    """The whole server path, not the solver alone.

    FastAPI runs sync endpoints in a worker thread, and Playwright's sync API
    refuses to be used from a thread other than the one that created it. The
    solver builds its Playwright instance per call for exactly this reason;
    this test is what proves the arrangement holds in the server.
    """
    r = client.post("/v1/documents", json={"title": "live deck"})
    doc_id = r.json()["document_id"]
    _page(client, doc_id, 0, "第1問 次の計算をせよ。\n問1 2x+3=7 を解け。")
    _page(client, doc_id, 1, "第2問 次の計算をせよ。\n問1 5+7 を計算せよ。")
    assert client.post(f"/v1/documents/{doc_id}/finalize").status_code == 200

    r = client.post(
        "/v1/exam-sessions",
        json={"mode": "study", "document_id": doc_id,
              "exam_type": "written", "answer_format": "written"},
    )
    sid = r.json()["session_id"]

    r = client.post(f"/v1/exam-sessions/{sid}/finalize-reading")
    assert r.status_code == 200, r.text

    solutions = client.get(f"/v1/exam-sessions/{sid}/solutions").json()
    assert solutions["deck"], f"no problems in the deck: {solutions}"

    served = [i for i in solutions["deck"] if i.get("solved")]
    assert served, (
        "the deck solved nothing through the server; a threadpool/Playwright "
        f"failure looks exactly like this: {solutions}"
    )
    for item in served:
        assert item.get("served_by") != "local", (
            "fell back to the offline placeholder, so the browser route did not "
            f"run: {item}"
        )
