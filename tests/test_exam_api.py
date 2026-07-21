import importlib

import pytest
from fastapi.testclient import TestClient

from tests.conftest import image_bytes, make_image


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ROKID_DATA_DIR", str(tmp_path))
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


def _new_session(client, mode="study", voice=False):
    r = client.post(
        "/v1/exam-sessions",
        json={"mode": mode, "voice_enabled": voice},
    )
    assert r.status_code == 201
    return r.json()["session_id"]


def _add_question(client, sid, ocr_text="問2 次の計算\n① 12\n② 13\n③ 14\n④ 15"):
    files = {"image": ("q.png", image_bytes(make_image(seed=5)), "image/png")}
    return client.post(
        f"/v1/exam-sessions/{sid}/questions",
        data={"ocr_text": ocr_text},
        files=files,
    )


def test_settings_advertise_silent_contract(client):
    body = client.get("/v1/settings").json()
    hud = body["hud"]
    assert hud["silent"] is True
    assert hud["animations"] is False
    assert hud["max_lines"] == 3
    # White-flash suppression / instant transition / low brightness are now
    # advertised as machine-readable render constraints.
    assert hud["white_flash"] is False
    assert hud["transition"] == "instant"
    assert hud["brightness"] == "low"
    assert body["voice_enabled_default"] is False
    # Silent shutter, and the privacy LED is explicitly NON-disable-able.
    # It lights while the camera is active (reading phase) and is dark during
    # the answer/review phases, when the camera is closed.
    capture = body["capture"]
    assert capture["shutter_sound"] is False
    assert capture["privacy_led"] == {
        "state": "on_while_camera_active",
        "tamper": "forbidden",
    }
    assert capture["led_off_during_review"] is True
    # 撮影しない: no photographic flash, silent capture, and silent audio recording.
    assert capture["flash"] == "off"
    assert capture["capture_tone"] is False
    assert capture["audio_record"]["start_tone"] is False
    assert capture["audio_record"]["stop_tone"] is False


def test_capture_ack_is_silent_and_short(client):
    sid = _new_session(client)
    ack = _add_question(client, sid).json()["capture_ack"]
    assert len(ack["lines"]) <= 3
    # The confirmation must not carry any sound/flash directive.
    for forbidden in ("sound", "audio", "flash", "beep"):
        assert forbidden not in ack


def test_version_lists_solvers(client):
    body = client.get("/v1/version").json()
    assert "solver_api_version" in body
    assert any(s["name"] == "local" for s in body["solvers"])


def test_full_exam_flow_study(client):
    sid = _new_session(client)
    r = _add_question(client, sid)
    assert r.status_code == 201
    qid = r.json()["question_id"]
    assert r.json()["question_no"] == "問2"
    assert r.json()["subject"]
    # No figure/table/graph/formula cue in this OCR -> media is empty.
    assert r.json()["media"] == []

    solved = client.post(
        f"/v1/exam-sessions/{sid}/questions/{qid}/solve"
    ).json()
    assert solved["locked"] is False
    view = solved["glasses_view"]
    assert len(view["lines"]) <= 3
    assert view["stage"] == "answer"
    # overlay targets the answer box and advertises 2D (non-6DoF) tracking
    assert "items" in solved["overlay"]
    assert solved["overlay"]["tracking"] == "2d_image_anchor"
    assert solved["overlay"]["fixed_ar"] is False
    # Phase 3: the serving solver tier and (possibly empty) evidence are exposed.
    assert solved["served_by"] == "local"
    assert "evidence" in solved


def test_add_question_extracts_media_when_present(client):
    sid = _new_session(client)
    r = _add_question(client, sid, ocr_text="問3 図1を参照し、表2の値を求めよ")
    media = r.json()["media"]
    kinds = {m["kind"] for m in media}
    assert "figure" in kinds and "table" in kinds


def test_evidence_is_populated_from_prior_materials(client):
    # Seed a scanned page, then solve a question whose body overlaps it.
    import app.main as main

    conn = main.db.connect()
    try:
        cur = conn.execute("INSERT INTO documents (title) VALUES ('study')")
        doc_id = cur.lastrowid
        conn.execute(
            "INSERT INTO pages (document_id, page_index, image_path, phash, ocr_text, summary)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (doc_id, 0, "p.png", "0" * 16,
             "光合成は植物が光のエネルギーででんぷんを作る反応である", "光合成"),
        )
        conn.commit()
    finally:
        conn.close()

    sid = _new_session(client)
    qid = _add_question(client, sid, ocr_text="問1 光合成について説明せよ").json()["question_id"]
    solved = client.post(f"/v1/exam-sessions/{sid}/questions/{qid}/solve").json()
    assert solved["evidence"], "expected retrieval to surface the photosynthesis page"
    assert solved["evidence_pages"] == [1]
    assert solved["evidence_refs"] == [
        {"document_id": doc_id, "page_number": 1}
    ]


def test_reasoning_endpoint_returns_log(client):
    sid = _new_session(client)
    qid = _add_question(client, sid).json()["question_id"]
    client.post(f"/v1/exam-sessions/{sid}/questions/{qid}/solve")
    r = client.get(f"/v1/exam-sessions/{sid}/questions/{qid}/reasoning")
    assert r.status_code == 200
    body = r.json()
    assert body["locked"] is False
    assert body["served_by"] == "local"
    assert "raw_reasoning" in body


def test_reasoning_real_mode_is_locked(client):
    sid = _new_session(client, mode="real")
    qid = _add_question(client, sid).json()["question_id"]
    client.post(f"/v1/exam-sessions/{sid}/questions/{qid}/solve")
    r = client.get(f"/v1/exam-sessions/{sid}/questions/{qid}/reasoning")
    assert r.json()["locked"] is True


def test_view_stage_navigation(client):
    sid = _new_session(client)
    qid = _add_question(client, sid).json()["question_id"]
    client.post(f"/v1/exam-sessions/{sid}/questions/{qid}/solve")

    for stage in ("answer", "solution", "rationale", "caution"):
        v = client.get(
            f"/v1/exam-sessions/{sid}/questions/{qid}/view",
            params={"stage": stage},
        ).json()["glasses_view"]
        assert v["stage"] == stage
        assert len(v["lines"]) <= 3

    bad = client.get(
        f"/v1/exam-sessions/{sid}/questions/{qid}/view",
        params={"stage": "nope"},
    )
    assert bad.status_code == 400


def test_view_before_solve_conflicts(client):
    sid = _new_session(client)
    qid = _add_question(client, sid).json()["question_id"]
    r = client.get(f"/v1/exam-sessions/{sid}/questions/{qid}/view")
    assert r.status_code == 409


def test_real_mode_is_locked_by_default(client):
    sid = _new_session(client, mode="real")
    qid = _add_question(client, sid).json()["question_id"]
    solved = client.post(
        f"/v1/exam-sessions/{sid}/questions/{qid}/solve"
    ).json()
    assert solved["locked"] is True
    assert solved["glasses_view"]["locked"] is True
    # the answer must not leak
    assert all("①" not in ln for ln in solved["glasses_view"]["lines"])


def test_low_read_confidence_asks_for_retake(client):
    sid = _new_session(client)
    # no OCR text -> low read confidence -> retake hint
    files = {"image": ("q.png", image_bytes(make_image(seed=5)), "image/png")}
    r = client.post(
        f"/v1/exam-sessions/{sid}/questions", files=files
    ).json()
    assert r["read_confidence"] < 0.3
    assert "hint" in r


# --- text-first question ingestion (撮影しない主経路) -------------------------

def test_add_question_text_only_no_image(client):
    sid = _new_session(client)
    r = client.post(
        f"/v1/exam-sessions/{sid}/questions",
        data={"ocr_text": "問2 次の計算\n① 12\n② 13\n③ 14\n④ 15"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["question_no"] == "問2"
    assert body["read_confidence"] > 0
    assert "capture_ack" in body
    # the ingested question is solvable without any stored image
    qid = body["question_id"]
    solved = client.post(f"/v1/exam-sessions/{sid}/questions/{qid}/solve").json()
    assert solved["locked"] is False
    assert solved["glasses_view"]["lines"]


def test_add_question_vision_text_only(client):
    # A figure-only question: the on-glass AI's figure reading alone must be
    # ingestable, drive media extraction, and be solvable.
    sid = _new_session(client)
    r = client.post(
        f"/v1/exam-sessions/{sid}/questions",
        data={"vision_text": "棒グラフ 各月の販売数 4月が最大の120"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["read_confidence"] > 0
    assert body["media"], "figure cues in vision_text must drive extraction"
    qid = body["question_id"]
    solved = client.post(f"/v1/exam-sessions/{sid}/questions/{qid}/solve").json()
    assert solved["locked"] is False


def test_add_question_vision_labels_do_not_split_question(client):
    # Figure readings may contain (1)/問N-shaped labels; they must not be
    # parsed as question boundaries, and the figure lines must stay with the
    # stored question body for solving.
    import app.main as main

    sid = _new_session(client)
    r = client.post(
        f"/v1/exam-sessions/{sid}/questions",
        data={
            "ocr_text": "問1 次の表を読み取り、最大の月を答えよ",
            "vision_text": "表:\n(1) 4月 100\n(2) 5月 200\n(3) 6月 150",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["question_no"] == "問1"
    conn = main.db.connect()
    try:
        row = conn.execute(
            "SELECT body_text FROM questions WHERE id = ?",
            (body["question_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert "(2) 5月 200" in row["body_text"]
    assert "【図・画像の読み取り】" in row["body_text"]


def test_add_question_requires_text_or_image_400(client):
    sid = _new_session(client)
    r = client.post(f"/v1/exam-sessions/{sid}/questions")
    assert r.status_code == 400
    assert "recognized text" in r.json()["detail"]


def test_add_question_text_only_extracts_media(client):
    sid = _new_session(client)
    r = client.post(
        f"/v1/exam-sessions/{sid}/questions",
        data={"ocr_text": "問1 下の図1のグラフを読み、値を求めよ"},
    )
    assert r.status_code == 201
    media = r.json()["media"]
    assert media, "text cues alone must drive media extraction"
    assert all(m["kind"] for m in media)


def test_add_question_malformed_bbox_hints_400_and_no_orphan_image(client):
    # A rejected request must not leave a file in IMAGE_DIR that no
    # questions row owns.
    import app.main as main

    sid = _new_session(client)
    files = {"image": ("q.png", image_bytes(make_image(seed=5)), "image/png")}
    r = client.post(
        f"/v1/exam-sessions/{sid}/questions",
        data={"ocr_text": "問1 計算せよ", "bbox_hints": "{not json"},
        files=files,
    )
    assert r.status_code == 400
    assert "bbox_hints" in r.json()["detail"]
    assert list(main.IMAGE_DIR.glob("q_*")) == []


def test_retake_hint_says_reread_not_rephotograph(client):
    # 撮影しない: recovery guidance must ask for re-recognition, never for a
    # new photograph.
    sid = _new_session(client)
    files = {"image": ("q.png", image_bytes(make_image(seed=5)), "image/png")}
    r = client.post(f"/v1/exam-sessions/{sid}/questions", files=files).json()
    lines = " ".join(r["hint"]["lines"])
    assert "再読取" in lines
    assert "再撮影" not in lines


def test_session_detail_lists_questions(client):
    sid = _new_session(client)
    qid = _add_question(client, sid).json()["question_id"]
    client.post(f"/v1/exam-sessions/{sid}/questions/{qid}/solve")
    body = client.get(f"/v1/exam-sessions/{sid}").json()
    assert body["mode"] == "study"
    assert len(body["questions"]) == 1
    assert body["questions"][0]["solved"] is True


def test_session_404(client):
    r = client.get("/v1/exam-sessions/9999")
    assert r.status_code == 404
