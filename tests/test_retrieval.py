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


def test_vision_text_values_are_retrievable(conn):
    # A supporting study page whose relevant values live only in vision_text
    # (the figure/table reading) must still be recalled and contribute its
    # values to the context snippet.
    from app.retrieval import retrieve_context

    conn.execute(
        "INSERT OR IGNORE INTO documents (id, title) VALUES (1, 'doc1')"
    )
    # Finalized page: a short OCR summary ("参考資料") must NOT hide the
    # figure value that lives only in vision_text.
    conn.execute(
        "INSERT INTO pages (document_id, page_index, image_path, phash, "
        "ocr_text, vision_text, summary) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, 0, None, "", "参考資料", "表: 東京の年間降水量は1520ミリメートル", "参考資料"),
    )
    conn.commit()

    r = retrieve_context(conn, "東京の年間降水量は何ミリメートルか")
    assert r["hits"], "figure-only page must be recalled via vision_text"
    assert r["hits"][0]["page_index"] == 0
    assert "1520" in r["context"]
    assert "1520" in r["hits"][0]["snippet"]


def test_snippet_keeps_vision_value_after_long_body(conn):
    # A page with a long OCR body whose matching value lives only in the
    # appended figure reading: truncating from the start would drop the value,
    # so the snippet must window it in.
    from app.retrieval import retrieve_context

    long_body = "重要な数値に関する前置きの説明がここに延々と続きます" + "あ" * 130
    conn.execute("INSERT OR IGNORE INTO documents (id, title) VALUES (1, 'doc1')")
    conn.execute(
        "INSERT INTO pages (document_id, page_index, image_path, phash, "
        "ocr_text, vision_text, summary) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, 0, None, "", long_body, "図: 全長は42.195キロメートル", None),
    )
    conn.commit()

    r = retrieve_context(conn, "全長は何キロメートルか")
    assert r["hits"], "page must be recalled"
    assert "42.195" in r["hits"][0]["snippet"], "figure value must survive truncation"
    assert "42.195" in r["context"]


def test_boilerplate_header_does_not_recall_unrelated_vision_page(conn):
    # The 【図・画像の読み取り】 display header must NOT be part of the scored
    # text: otherwise a figure-vocabulary query overlaps the boilerplate of
    # every vision page and recalls unrelated figure/table pages.
    from app.retrieval import retrieve_context

    conn.execute("INSERT OR IGNORE INTO documents (id, title) VALUES (1, 'doc1')")
    conn.executemany(
        "INSERT INTO pages (document_id, page_index, image_path, phash, "
        "ocr_text, vision_text, summary) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (1, 0, None, "", "", "光合成では光エネルギーででんぷんを作る反応", None),
            (1, 1, None, "", "", "徳川家康が江戸幕府を開いた出来事", None),
        ],
    )
    conn.commit()

    r = retrieve_context(conn, "光合成の図から読み取れることは何か")
    assert r["hits"] and r["hits"][0]["page_index"] == 0
    assert 1 not in r["evidence_pages"], (
        "an unrelated vision page must not be recalled via header overlap alone"
    )
