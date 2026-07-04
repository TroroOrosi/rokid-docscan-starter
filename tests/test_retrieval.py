import importlib

import pytest


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("ROKID_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ROKID_ENABLE_EMBEDDING", raising=False)
    import app.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)
    db.init_db()
    c = db.connect()
    try:
        yield c
    finally:
        c.close()


def _add_page(conn, document_id, page_index, ocr_text):
    conn.execute(
        "INSERT OR IGNORE INTO documents (id, title) VALUES (?, ?)",
        (document_id, f"doc{document_id}"),
    )
    conn.execute(
        "INSERT INTO pages (document_id, page_index, image_path, phash, ocr_text, summary)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (document_id, page_index, "x.png", "0" * 16, ocr_text, ocr_text[:40]),
    )
    conn.commit()


def test_empty_store_is_safe(conn):
    r = __import__("app.retrieval", fromlist=["retrieve_context"]).retrieve_context(
        conn, "光合成とは何か"
    )
    assert r["context"] == ""
    assert r["evidence_pages"] == []
    assert r["hits"] == []


def test_empty_query_is_safe(conn):
    from app.retrieval import retrieve_context

    _add_page(conn, 1, 0, "光合成は植物が光のエネルギーででんぷんを作る反応である")
    assert retrieve_context(conn, "")["hits"] == []
    assert retrieve_context(conn, None)["hits"] == []


def test_returns_most_similar_page(conn):
    from app.retrieval import retrieve_context

    _add_page(conn, 1, 0, "光合成は植物が光のエネルギーででんぷんを作る反応である")
    _add_page(conn, 1, 1, "ニュートンの運動方程式は F = ma で表される")
    _add_page(conn, 1, 2, "江戸幕府は1603年に徳川家康が開いた")

    r = retrieve_context(conn, "光合成について説明せよ")
    assert r["hits"], "expected at least one hit"
    # The photosynthesis page (index 0) should rank first.
    assert r["hits"][0]["page_index"] == 0
    assert 0 in r["evidence_pages"]
    assert "光合成" in r["context"]
    assert r["retriever"] == "lexical"


def test_short_query_still_recalls(conn):
    # 1-2 char queries have (almost) no bigrams, so overlap used to collapse
    # to zero; the containment path must keep recall alive.
    from app.retrieval import retrieve_context

    _add_page(conn, 1, 0, "酵素は生体内の化学反応を触媒するタンパク質である")
    _add_page(conn, 1, 1, "江戸幕府は1603年に徳川家康が開いた")
    for query in ("酵素", "酵"):  # 2-char and the harder 1-char case
        r = retrieve_context(conn, query)
        assert r["hits"], f"expected the enzyme page to be recalled for {query!r}"
        assert r["hits"][0]["page_index"] == 0
