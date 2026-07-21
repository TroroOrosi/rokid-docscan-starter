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


def test_snippet_anchor_is_case_insensitive(conn):
    # Retrieval normalizes English case before scoring; snippet anchoring must
    # use the same rule or an uppercase match beyond the head is omitted.
    from app.retrieval import retrieve_context

    long_body = (
        "Background material unrelated to the requested indicator. " * 4
        + "GDP reached 3.2 percent growth in the latest period."
    )
    _add_page(conn, 1, 0, long_body)

    r = retrieve_context(conn, "gdp")
    assert r["hits"], "the normalized query must recall the page"
    assert "GDP" in r["hits"][0]["snippet"]
    assert "3.2" in r["hits"][0]["snippet"]


def test_snippet_keeps_body_value_when_vision_unrelated(conn):
    # Codex review: when the query matched only the OCR body, the snippet must
    # not spend half its budget on unrelated vision text and drop a body value
    # that sits past the first ~60 characters (it previously fit the 120-char
    # body window).
    from app.retrieval import retrieve_context

    body = "設問について。" + "あ" * 60 + "答えは東京都である。" + "い" * 60
    unrelated_vision = (
        "図: 富士山の標高に関する詳細な解説がここに延々と記載されています" + "う" * 40
    )
    conn.execute("INSERT OR IGNORE INTO documents (id, title) VALUES (1, 'doc1')")
    conn.execute(
        "INSERT INTO pages (document_id, page_index, image_path, phash, "
        "ocr_text, vision_text, summary) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, 0, None, "", body, unrelated_vision, None),
    )
    conn.commit()

    r = retrieve_context(conn, "設問の答えは何か")
    assert r["hits"], "page must be recalled by its body"
    assert "東京都" in r["hits"][0]["snippet"], (
        "a body value must not be crowded out by an unmatched vision reserve"
    )
    assert "東京都" in r["context"]


def test_single_char_query_snippet_keeps_far_value(conn):
    # Codex review: a single-character query recalls via the containment path,
    # but single chars are filtered from the multi-char snippet anchors. The
    # snippet must fall back to a single-char anchor so a matched value past the
    # first 120 chars is not dropped in favour of the page head.
    from app.retrieval import retrieve_context

    lead_in = "この文章は非常に長い前置きであり特定の語を含まない説明が延々と続きます" * 4
    _add_page(conn, 1, 0, lead_in + "酵素の働き")  # only "酵" occurrence is past 120

    r = retrieve_context(conn, "酵")
    assert r["hits"], "single-char query must recall the page"
    assert "酵" in r["hits"][0]["snippet"], "the matched char's context must survive"
    assert "酵" in r["context"]


def test_short_figure_query_strips_display_header(conn):
    # Codex review: a figure-only question is stored with the
    # 【図・画像の読み取り】 display header in its body; retrieval must strip that
    # header from the query so a short value ("42") still takes the short-query
    # containment path and recalls its supporting vision page instead of being
    # bloated below _MIN_SCORE by the header's bigrams.
    from app.retrieval import retrieve_context

    conn.execute("INSERT OR IGNORE INTO documents (id, title) VALUES (1, 'doc1')")
    conn.execute(
        "INSERT INTO pages (document_id, page_index, image_path, phash, "
        "ocr_text, vision_text, summary) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, 0, None, "", "", "図: 全長は42.195キロメートル", None),
    )
    conn.commit()

    r = retrieve_context(conn, "【図・画像の読み取り】\n42")
    assert r["hits"], "the short figure query must recall the vision page"
    assert r["hits"][0]["page_index"] == 0
    assert "42" in r["context"]


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
