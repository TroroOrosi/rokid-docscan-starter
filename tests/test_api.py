import importlib

import pytest
from fastapi.testclient import TestClient

from tests.conftest import image_bytes, make_image


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Point all storage at a temp dir, then reload modules that captured paths.
    monkeypatch.setenv("ROKID_DATA_DIR", str(tmp_path))
    import app.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)
    import app.main as main
    importlib.reload(main)
    main.ensure_dirs()
    main.db.init_db()
    return TestClient(main.app)


def _create_doc(client, title="Spec v1"):
    r = client.post("/v1/documents", json={"title": title, "capture_device": "CXR-S"})
    assert r.status_code == 201
    return r.json()["document_id"]


def _add_page(client, doc_id, idx, seed, ocr_text=None):
    files = {"image": (f"p{idx}.png", image_bytes(make_image(seed=seed)), "image/png")}
    data = {"page_index": str(idx)}
    if ocr_text is not None:
        data["ocr_text"] = ocr_text
    return client.post(f"/v1/documents/{doc_id}/pages", data=data, files=files)


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert "versions" in body
    assert "api_version" in body["versions"]


def test_version_endpoint(client):
    body = client.get("/v1/version").json()
    assert "matcher_version" in body
    assert "hud_contract_version" in body
    assert any(a["name"] == "local" for a in body["analyzers"])


def test_match_response_carries_versions_and_hints(client):
    doc_id = _create_doc(client)
    _add_page(client, doc_id, 0, seed=10, ocr_text="page one")
    client.post(f"/v1/documents/{doc_id}/finalize")
    files = {"image": ("q.png", image_bytes(make_image(seed=10)), "image/png")}
    r = client.post(
        "/v1/match",
        data={
            "document_id": str(doc_id),
            "client_version": "android-0.9.1",
            "sdk_hint": "cxr-l",
        },
        files=files,
    )
    body = r.json()
    assert body["versions"]["hud_contract_version"]
    assert body["client_version"] == "android-0.9.1"
    assert body["sdk_hint"] == "cxr-l"


def test_full_flow_hit(client):
    doc_id = _create_doc(client)
    assert _add_page(client, doc_id, 0, seed=10, ocr_text="page one").status_code == 201
    assert _add_page(client, doc_id, 1, seed=200, ocr_text="page two").status_code == 201

    fin = client.post(f"/v1/documents/{doc_id}/finalize").json()
    assert fin["status"] == "ready"
    assert fin["page_count"] == 2
    assert len(fin["summaries"]) == 2

    # query with the same image as page 0 -> HIT on page_index 0
    files = {"image": ("q.png", image_bytes(make_image(seed=10)), "image/png")}
    r = client.post("/v1/match", data={"document_id": str(doc_id)}, files=files)
    body = r.json()
    assert body["verdict"] == "HIT"
    assert body["best_page"]["page_index"] == 0
    assert len(body["hud"]["lines"]) == 3
    assert body["hud"]["lines"][0].startswith("PAGE")


def test_match_no_page(client):
    doc_id = _create_doc(client)
    _add_page(client, doc_id, 0, seed=10)
    client.post(f"/v1/documents/{doc_id}/finalize")

    files = {"image": ("q.png", image_bytes(make_image(seed=777)), "image/png")}
    r = client.post("/v1/match", data={"document_id": str(doc_id)}, files=files)
    body = r.json()
    assert body["verdict"] in {"NO_PAGE", "LOW_CONF"}
    assert len(body["hud"]["lines"]) == 3


def test_match_hud_counts_text_only_pages_in_mixed_document(client):
    doc_id = _create_doc(client)
    # Page 0 follows the primary no-photography path (scored by text only).
    # Page 1 keeps the optional compatibility image.
    assert client.post(
        f"/v1/documents/{doc_id}/pages",
        data={"page_index": 0, "ocr_text": "text-only page"},
    ).status_code == 201
    assert _add_page(client, doc_id, 1, seed=20, ocr_text="image page").status_code == 201
    assert client.post(f"/v1/documents/{doc_id}/finalize").status_code == 200

    files = {"image": ("q.png", image_bytes(make_image(seed=20)), "image/png")}
    body = client.post(
        "/v1/match", data={"document_id": str(doc_id)}, files=files
    ).json()
    assert body["verdict"] == "HIT"
    assert body["best_page"]["page_index"] == 1
    assert body["hud"]["lines"][0] == "PAGE 2/2"


def test_resending_page_index_replaces_the_page(client):
    # 再読取: re-sending an index replaces the page (fix a bad read), it does
    # not 409 and does not grow the document.
    doc_id = _create_doc(client)
    first = _add_page(client, doc_id, 0, seed=10, ocr_text="bad read")
    assert first.status_code == 201 and first.json()["replaced"] is False
    second = _add_page(client, doc_id, 0, seed=11, ocr_text="good read")
    assert second.status_code == 201
    body = second.json()
    assert body["replaced"] is True
    assert body["page_id"] == first.json()["page_id"]
    assert body["phash"] != first.json()["phash"]

    fin = client.post(f"/v1/documents/{doc_id}/finalize").json()
    assert fin["page_count"] == 1
    assert fin["summaries"][0]["summary"] == "good read"


def test_missing_document_404(client):
    files = {"image": ("q.png", image_bytes(make_image(seed=1)), "image/png")}
    r = client.post("/v1/match", data={"document_id": "9999"}, files=files)
    assert r.status_code == 404


# --- text-first /match (撮影しない主経路) ------------------------------------

def _add_text_only_page(client, doc_id, idx, ocr_text=None, vision_text=None):
    data = {"page_index": str(idx)}
    if ocr_text is not None:
        data["ocr_text"] = ocr_text
    if vision_text is not None:
        data["vision_text"] = vision_text
    return client.post(f"/v1/documents/{doc_id}/pages", data=data)


def test_match_text_only_hits_registered_text_page(client):
    doc_id = _create_doc(client)
    _add_text_only_page(client, doc_id, 0, ocr_text="問1 二次方程式を解け")
    _add_text_only_page(client, doc_id, 1, ocr_text="問2 図形の面積を求めよ")
    client.post(f"/v1/documents/{doc_id}/finalize")

    r = client.post(
        "/v1/match",
        data={"document_id": str(doc_id), "ocr_text": "問2 図形の面積を求めよ"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verdict"] == "HIT"
    assert body["best_page"]["page_index"] == 1
    assert body["best_page"]["hamming"] is None
    assert body["query_phash"] is None
    assert body["query_signals"] == {"phash": False, "text": True}
    assert body["hud"]["lines"][0] == "PAGE 2/2"


def test_match_text_only_partial_text_is_low_conf(client):
    doc_id = _create_doc(client)
    _add_text_only_page(
        client, doc_id, 0, ocr_text="alpha beta gamma delta epsilon zeta"
    )
    client.post(f"/v1/documents/{doc_id}/finalize")

    body = client.post(
        "/v1/match",
        data={
            "document_id": str(doc_id),
            "ocr_text": "alpha beta gamma delta unknown tail",
        },
    ).json()
    assert body["verdict"] == "LOW_CONF"
    assert body["best_page"] is None or body["verdict"] != "NO_PAGE"


def test_match_text_only_unrelated_text_no_page(client):
    doc_id = _create_doc(client)
    _add_text_only_page(client, doc_id, 0, ocr_text="invoice 2026 total")
    client.post(f"/v1/documents/{doc_id}/finalize")

    body = client.post(
        "/v1/match",
        data={
            "document_id": str(doc_id),
            "ocr_text": "zzz qqq unrelated words entirely",
        },
    ).json()
    assert body["verdict"] == "NO_PAGE"


def test_match_requires_text_or_image_400(client):
    doc_id = _create_doc(client)
    r = client.post("/v1/match", data={"document_id": str(doc_id)})
    assert r.status_code == 400
    assert "recognized text" in r.json()["detail"]


def test_match_fast_ocr_text_alias_still_works(client):
    # Legacy field name, now usable without an image.
    doc_id = _create_doc(client)
    _add_text_only_page(client, doc_id, 0, ocr_text="the only page here")
    client.post(f"/v1/documents/{doc_id}/finalize")

    body = client.post(
        "/v1/match",
        data={"document_id": str(doc_id), "fast_ocr_text": "the only page here"},
    ).json()
    assert body["verdict"] == "HIT"
    assert body["best_page"]["page_index"] == 0


def test_match_image_compat_path_unchanged(client):
    # The optional legacy image input must keep matching image-registered
    # pages by pHash exactly as before.
    doc_id = _create_doc(client)
    _add_page(client, doc_id, 0, seed=10, ocr_text="page one")
    client.post(f"/v1/documents/{doc_id}/finalize")

    files = {"image": ("q.png", image_bytes(make_image(seed=10)), "image/png")}
    body = client.post(
        "/v1/match", data={"document_id": str(doc_id)}, files=files
    ).json()
    assert body["verdict"] == "HIT"
    assert body["best_page"]["hamming"] == 0
    assert body["query_signals"] == {"phash": True, "text": False}


def test_match_vision_text_distinguishes_same_body_pages(client):
    # Two pages share identical printed text and differ only in their
    # figures: the figure reading must pick the right page.
    doc_id = _create_doc(client)
    body = "問3 グラフから読み取れる値を答えよ"
    _add_text_only_page(
        client, doc_id, 0, ocr_text=body,
        vision_text="折れ線グラフ 気温の推移 夏に最大",
    )
    _add_text_only_page(
        client, doc_id, 1, ocr_text=body,
        vision_text="棒グラフ 降水量の比較 6月に最大",
    )
    client.post(f"/v1/documents/{doc_id}/finalize")

    r = client.post(
        "/v1/match",
        data={
            "document_id": str(doc_id),
            "ocr_text": body,
            "vision_text": "棒グラフ 降水量の比較 6月に最大",
        },
    )
    body_json = r.json()
    assert body_json["verdict"] == "HIT"
    assert body_json["best_page"]["page_index"] == 1


def test_match_body_only_query_matches_page_with_vision_text(client):
    # A page registered with body + a long figure reading must still be an
    # exact match for a query that supplies only the body text — the figure
    # reading must not dilute the comparison when the query has none.
    doc_id = _create_doc(client)
    body = "問5 表の値を用いて平均を求めよ"
    _add_text_only_page(
        client, doc_id, 0, ocr_text=body,
        vision_text=(
            "表: 1月 12.3 / 2月 14.1 / 3月 15.8 / 4月 18.2 / 5月 21.0 / "
            "6月 24.5 / 7月 28.1 / 8月 29.3 / 9月 26.0 / 10月 20.4"
        ),
    )
    client.post(f"/v1/documents/{doc_id}/finalize")

    body_json = client.post(
        "/v1/match", data={"document_id": str(doc_id), "ocr_text": body}
    ).json()
    assert body_json["verdict"] == "HIT"
    assert body_json["best_page"]["page_index"] == 0
    assert body_json["best_page"]["ocr_match"] is True


def test_match_vision_rich_query_matches_body_only_page(client):
    # Reverse shape: the registration missed the figure but the live query
    # includes a long figure reading — the body must still match exactly.
    doc_id = _create_doc(client)
    body = "問6 グラフの傾きを求めよ"
    _add_text_only_page(client, doc_id, 0, ocr_text=body)
    client.post(f"/v1/documents/{doc_id}/finalize")

    body_json = client.post(
        "/v1/match",
        data={
            "document_id": str(doc_id),
            "ocr_text": body,
            "vision_text": (
                "散布図: x軸は時間 y軸は距離 原点から右上へ直線的に増加 "
                "近似直線は(0,0)と(10,50)を通る"
            ),
        },
    ).json()
    assert body_json["verdict"] == "HIT"
    assert body_json["best_page"]["page_index"] == 0
    assert body_json["best_page"]["ocr_match"] is True


def test_match_long_shared_body_with_mismatched_figure_not_hit(client):
    # A long identical prompt must not drag a mismatched figure reading into
    # the HIT band: the components are scored separately (equal weight).
    doc_id = _create_doc(client)
    body = (
        "問9 次の資料を読み、以下の設問に答えよ。この調査は全国の中学生を"
        "対象に実施され、回答者数は一万二千人、回収率は八十二パーセントで"
        "あった。調査項目は生活習慣、学習時間、余暇の過ごし方に及ぶ。"
    )
    _add_text_only_page(
        client, doc_id, 0, ocr_text=body,
        vision_text="円グラフ 内訳 A 40% B 35% C 25%",
    )
    client.post(f"/v1/documents/{doc_id}/finalize")

    body_json = client.post(
        "/v1/match",
        data={
            "document_id": str(doc_id),
            "ocr_text": body,
            "vision_text": "散布図 x軸は学習時間 y軸は得点 右上がりの相関",
        },
    ).json()
    assert body_json["verdict"] in {"LOW_CONF", "NO_PAGE"}


def test_match_image_query_vision_mismatch_gets_no_exact_bonus(client):
    # Legacy image query carrying vision_text: the exact-MD5 shortcut must
    # hash the combined material, not the stored body/raw MD5 — a page whose
    # figure reading differs must not be boosted as if it matched.
    doc_id = _create_doc(client)
    body = "問10 図から読み取れることを答えよ"
    files0 = {"image": ("p0.png", image_bytes(make_image(seed=30)), "image/png")}
    client.post(
        f"/v1/documents/{doc_id}/pages",
        data={"page_index": 0, "ocr_text": body,
              "vision_text": "折れ線グラフ 気温 夏に最大"},
        files=files0,
    )
    files1 = {"image": ("p1.png", image_bytes(make_image(seed=30)), "image/png")}
    client.post(
        f"/v1/documents/{doc_id}/pages",
        data={"page_index": 1, "ocr_text": body,
              "vision_text": "棒グラフ 降水量 6月に最大"},
        files=files1,
    )
    client.post(f"/v1/documents/{doc_id}/finalize")

    # Visually unrelated frame + body + page 1's figure reading.
    files_q = {"image": ("q.png", image_bytes(make_image(seed=99)), "image/png")}
    body_json = client.post(
        "/v1/match",
        data={
            "document_id": str(doc_id),
            "ocr_text": body,
            "vision_text": "棒グラフ 降水量 6月に最大",
        },
        files=files_q,
    ).json()
    by_index = {c["page_index"]: c for c in body_json["candidates"]}
    assert by_index[1]["ocr_match"] is True
    assert by_index[0]["ocr_match"] is False
    # The full-text bonus goes only to the page whose figure agrees...
    assert by_index[1]["confidence"] > by_index[0]["confidence"]
    # ...while the visually unrelated frame still keeps the compat image
    # path from claiming a HIT (text is a bonus, not a verdict, there).
    assert body_json["verdict"] != "HIT"


def test_match_full_signal_hit_outranks_partial_exact_body(client):
    # A body-only page (figure read missed) exactly matches the query body;
    # the true page has one OCR typo in its body but the matching figure.
    # The full-signal HIT must win over the unverifiable exact body.
    doc_id = _create_doc(client)
    body = "問11 グラフの値を読み取り最大値を答えよ"
    noisy_body = "間11 グラフの値を読み取り最大値を答えよ"  # 問→間 OCR typo
    vision = "棒グラフ 4月 80 5月 95 6月 120 7月 110"
    _add_text_only_page(client, doc_id, 0, ocr_text=body)  # figure missed
    _add_text_only_page(client, doc_id, 1, ocr_text=noisy_body, vision_text=vision)
    client.post(f"/v1/documents/{doc_id}/finalize")

    body_json = client.post(
        "/v1/match",
        data={"document_id": str(doc_id), "ocr_text": body, "vision_text": vision},
    ).json()
    assert body_json["verdict"] == "HIT"
    assert body_json["best_page"]["page_index"] == 1


def test_match_vision_only_query_matches_page_with_body_and_vision(client):
    # Live recognition may catch only the figure. The figure reading must be
    # compared against the page's figure reading alone — the registered body
    # must not dilute it.
    doc_id = _create_doc(client)
    vision = "円グラフ 内訳は A 40% B 35% C 25%"
    _add_text_only_page(
        client, doc_id, 0,
        ocr_text=(
            "問7 次の資料を読み、以下の設問に答えよ。資料には調査の背景と"
            "方法、対象者の内訳、集計方針が長く記述されている。"
        ),
        vision_text=vision,
    )
    client.post(f"/v1/documents/{doc_id}/finalize")

    body_json = client.post(
        "/v1/match", data={"document_id": str(doc_id), "vision_text": vision}
    ).json()
    assert body_json["verdict"] == "HIT"
    assert body_json["best_page"]["page_index"] == 0
    assert body_json["best_page"]["ocr_match"] is True


def test_match_prefers_figure_aware_match_over_body_only_fallback(client):
    # Mixed coverage: an earlier page whose figure read was missed shares the
    # body with a later fully-read page. A query carrying the matching figure
    # reading must pick the fully-matched page, not the earlier fallback.
    doc_id = _create_doc(client)
    body = "問8 図を参照して答えよ"
    vision = "ヒストグラム 度数は 3 7 12 9 4"
    _add_text_only_page(client, doc_id, 0, ocr_text=body)  # figure read missed
    _add_text_only_page(client, doc_id, 1, ocr_text=body, vision_text=vision)
    client.post(f"/v1/documents/{doc_id}/finalize")

    body_json = client.post(
        "/v1/match",
        data={"document_id": str(doc_id), "ocr_text": body, "vision_text": vision},
    ).json()
    assert body_json["verdict"] == "HIT"
    assert body_json["best_page"]["page_index"] == 1


def test_match_vision_text_fallback_matches_figure_only_page(client):
    # A page whose recognition is only the figure reading (vision_text) must
    # be matchable by the same figure reading.
    doc_id = _create_doc(client)
    _add_text_only_page(
        client, doc_id, 0, vision_text="棒グラフ 縦軸は人口 横軸は年度"
    )
    client.post(f"/v1/documents/{doc_id}/finalize")

    body = client.post(
        "/v1/match",
        data={
            "document_id": str(doc_id),
            "vision_text": "棒グラフ 縦軸は人口 横軸は年度",
        },
    ).json()
    assert body["verdict"] == "HIT"
    assert body["best_page"]["page_index"] == 0


def test_finalize_is_idempotent_per_page(client, monkeypatch):
    # Re-finalizing (gesture double-fire / resume) must not re-run the analyzer
    # over already-summarized pages — with a cloud ROKID_ANALYZER that would be
    # a full re-bill of the document.
    from app.analyzers import Analyzer, AnalyzerResult, register_analyzer

    calls = []

    class CountingAnalyzer(Analyzer):
        name = "counting-test"
        provider_version = "t-1"
        offline = True

        def analyze(self, *, image_path=None, ocr_text=None, max_summary_len=48):
            calls.append(ocr_text)
            return AnalyzerResult(text=ocr_text, summary="COUNTED")

    register_analyzer(CountingAnalyzer(), replace=True)
    monkeypatch.setenv("ROKID_ANALYZER", "counting-test")

    doc_id = _create_doc(client)
    _add_page(client, doc_id, 0, seed=10, ocr_text="page one")
    _add_page(client, doc_id, 1, seed=11, ocr_text="page two")
    assert client.post(f"/v1/documents/{doc_id}/finalize").status_code == 200
    assert client.post(f"/v1/documents/{doc_id}/finalize").status_code == 200
    assert len(calls) == 2
