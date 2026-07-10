import importlib

import pytest
from fastapi.testclient import TestClient

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
    return client.post(
        f"/v1/exam-sessions/{sid}/questions",
        json={"ocr_text": ocr_text},
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
    # Raw visual media is forbidden; the device remains authoritative for its
    # camera indicator and the server never claims to observe it.
    capture = body["capture"]
    assert capture["shutter_sound"] is False
    assert capture["visual_input"]["photo_capture"] is False
    assert capture["visual_input"]["video_recording"] is False
    assert capture["visual_input"]["raw_image_upload"] is False
    assert capture["visual_input"]["server_media_persistence"] is False
    assert capture["privacy_led"]["state"] == "on_while_camera_active"
    assert capture["privacy_led"]["authority"] == "device_firmware"
    assert capture["privacy_led"]["server_control"] is False
    assert capture["privacy_led"]["tamper"] == "forbidden"
    assert capture["privacy_led"]["guaranteed_off_during_visual_recognition"] is False
    assert capture["close_visual_sensor_before_review"] is True
    assert capture["server_observes_camera_state"] is False
    # 撮影しない: no photographic flash, silent capture, and silent audio recording.
    assert capture["flash"] == "off"
    assert capture["capture_tone"] is False
    assert capture["audio_record"]["start_tone"] is False
    assert capture["audio_record"]["stop_tone"] is False
    assert capture["audio_record"]["microphone_only"] is True
    assert capture["audio_record"]["video_recording"] is False


def test_recognition_ack_is_silent_and_short(client):
    sid = _new_session(client)
    body = _add_question(client, sid).json()
    ack = body["recognition_ack"]
    assert body["capture_ack"] == ack  # deprecated compatibility alias
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


def test_question_requires_recognized_text(client):
    sid = _new_session(client)
    r = client.post(f"/v1/exam-sessions/{sid}/questions", json={})
    assert r.status_code == 400
    assert "ocr_text or vision_text" in r.json()["detail"]


def test_question_rejects_raw_image(client):
    sid = _new_session(client)
    r = client.post(
        f"/v1/exam-sessions/{sid}/questions",
        data={"ocr_text": "問1"},
        files={"image": ("q.png", b"not-read", "image/png")},
    )
    assert r.status_code == 415


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
