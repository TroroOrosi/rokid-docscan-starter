"""Authenticated power notifications survive restart and reject late updates."""

import importlib
import time

import pytest

from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch, key="test-key"):
    monkeypatch.setenv("ROKID_DATA_DIR", str(tmp_path))
    if key:
        monkeypatch.setenv("ROKID_API_KEY", key)
    else:
        monkeypatch.delenv("ROKID_API_KEY", raising=False)
    from app import config, db, main
    for module in (config, db, main):
        importlib.reload(module)
    main.ensure_dirs()
    main.db.init_db()
    application = main.app

    async def app_with_peer(scope, receive, send):
        if scope["type"] == "http":
            scope = {**scope, "client": ("10.0.0.12", 54321)}
        await application(scope, receive, send)

    return TestClient(app_with_peer)


HEADERS = {"Authorization": "Bearer test-key"}
STATE = {"device_id": "glasses-serial", "session_id": None,
         "generation": 3, "sequence": 1, "phase": "capturing"}


def test_state_requires_auth_even_when_other_local_endpoints_do_not(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, key=None)
    assert client.post("/v1/glasses/state", json=STATE).status_code == 503
    client = _client(tmp_path, monkeypatch)
    assert client.post("/v1/glasses/state", json=STATE).status_code == 401
    assert client.get("/v1/glasses/state?device_id=glasses-serial").status_code == 401


def test_latest_state_and_real_connection_address_survive_a_server_restart(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    response = client.post("/v1/glasses/state", json=STATE, headers=HEADERS)
    assert response.status_code == 200
    client = _client(tmp_path, monkeypatch)
    body = client.get("/v1/glasses/state?device_id=glasses-serial", headers=HEADERS).json()
    assert body == {**STATE, "display_request": None, "entry_request": None, "ack_answer_revision": None, "source_ip": "10.0.0.12", "answer_ready": False,
                    "available_stage": "none", "answer_revision": 0}
    assert client.get("/v1/glasses/state?device_id=other", headers=HEADERS).status_code == 404


def test_late_generation_and_finished_session_cannot_reenable_wake(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    for update in (STATE, {**STATE, "phase": "writing_done", "sequence": 2},
                   {**STATE, "phase": "analyzing", "sequence": 4},
                   {**STATE, "phase": "reading", "generation": 2, "sequence": 99}):
        assert client.post("/v1/glasses/state", json=update, headers=HEADERS).status_code == 200
    current = client.get("/v1/glasses/state?device_id=glasses-serial", headers=HEADERS).json()
    assert current["phase"] == "writing_done"
    assert current["sequence"] == 2
    assert current["answer_ready"] is False
    next_run = {**STATE, "generation": 4}
    client.post("/v1/glasses/state", json=next_run, headers=HEADERS)
    assert client.get("/v1/glasses/state?device_id=glasses-serial", headers=HEADERS).json()["generation"] == 4


def test_only_a_finished_bundle_for_the_active_session_can_wake(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    from app import main
    bundles = iter([
        {"items": [{"status": "pending"}]},
        {"items": [{"status": "ready"}, {"status": "needs_input"}]},
    ])
    sessions = []

    def bundle(session_id):
        sessions.append(session_id)
        return next(bundles)

    monkeypatch.setattr(main, "exam_answer_bundle", bundle)
    client.post("/v1/glasses/state", json={**STATE, "session_id": 7, "phase": "analyzing"}, headers=HEADERS)
    url = "/v1/glasses/state?device_id=glasses-serial"
    assert client.get(url, headers=HEADERS).json()["answer_ready"] is False
    assert client.get(url, headers=HEADERS).json()["answer_ready"] is True
    client.post("/v1/glasses/state", json={**STATE, "session_id": 7, "phase": "closed", "sequence": 2}, headers=HEADERS)
    assert client.get(url, headers=HEADERS).json()["answer_ready"] is False
    assert sessions == [7, 7]


def test_authenticated_discovery_does_not_need_android_identity_to_be_its_serial(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.get("/v1/glasses/state", headers=HEADERS).json() == {"devices": []}
    android_state = {**STATE, "device_id": "android-id-different-from-serial"}
    client.post("/v1/glasses/state", json=android_state, headers=HEADERS)
    response = client.get("/v1/glasses/state", headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {"devices": [{**android_state, "display_request": None, "entry_request": None, "ack_answer_revision": None,
                                            "source_ip": "10.0.0.12", "answer_ready": False,
                                            "available_stage": "none", "answer_revision": 0}]}


def test_corrupt_state_never_turns_into_an_active_session(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/v1/glasses/state", json=STATE, headers=HEADERS)
    next((tmp_path / "glasses-state").glob("*.json")).write_text("incomplete")
    response = client.get("/v1/glasses/state?device_id=glasses-serial", headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["detail"] == "state_unavailable"


def test_writing_done_during_bundle_read_revokes_a_pending_wake(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    from app import main
    from app.glasses_state import GlassesState, record_state
    analyzing = {**STATE, "session_id": 7, "phase": "analyzing"}
    client.post("/v1/glasses/state", json=analyzing, headers=HEADERS)

    def bundle(session_id):
        record_state(GlassesState(**{**analyzing, "phase": "writing_done", "sequence": 2}), "10.0.0.12")
        return {"items": [{"status": "ready"}]}

    monkeypatch.setattr(main, "exam_answer_bundle", bundle)
    response = client.get("/v1/glasses/state?device_id=glasses-serial", headers=HEADERS).json()
    assert response["phase"] == "writing_done" and response["answer_ready"] is False


@pytest.mark.parametrize("phase", ["chooser", "waiting"])
def test_idle_display_request_survives_restart_without_a_session(tmp_path, monkeypatch, phase):
    client = _client(tmp_path, monkeypatch)
    state = {**STATE, "phase": phase, "display_request": "sleep"}
    assert client.post("/v1/glasses/state", json=state, headers=HEADERS).status_code == 200
    client = _client(tmp_path, monkeypatch)
    saved = client.get("/v1/glasses/state?device_id=glasses-serial", headers=HEADERS).json()
    assert saved["phase"] == phase and saved["display_request"] == "sleep"
    assert saved["answer_ready"] is False


@pytest.mark.parametrize("phase", ["capturing", "reading"])
def test_active_capture_and_answer_reading_reject_a_sleep_request(tmp_path, monkeypatch, phase):
    client = _client(tmp_path, monkeypatch)
    assert client.post("/v1/glasses/state", json=STATE, headers=HEADERS).status_code == 200
    response = client.post("/v1/glasses/state", headers=HEADERS,
                           json={**STATE, "phase": phase, "sequence": 2, "display_request": "sleep"})
    assert response.status_code == 422
    saved = client.get("/v1/glasses/state?device_id=glasses-serial", headers=HEADERS).json()
    assert saved["sequence"] == 1


def test_mixed_reading_snapshot_is_available_while_listening_is_pending(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    from app import main
    monkeypatch.setattr(main, "exam_answer_bundle", lambda _: {
        "available_stage": "reading", "revision": 4,
        "items": [{"status": "ready"}, {"status": "pending"}],
    })
    client.post("/v1/glasses/state", headers=HEADERS,
                json={**STATE, "session_id": 7, "phase": "waiting", "display_request": "sleep"})
    saved = client.get("/v1/glasses/state?device_id=glasses-serial", headers=HEADERS).json()
    assert saved["answer_ready"] is True
    assert saved["available_stage"] == "reading" and saved["answer_revision"] == 4


@pytest.mark.parametrize("ack", [-1, True, "1", 2**63])
def test_received_revision_is_a_strict_nonnegative_counter(tmp_path, monkeypatch, ack):
    client = _client(tmp_path, monkeypatch)
    response = client.post("/v1/glasses/state", headers=HEADERS,
                           json={**STATE, "session_id": 7, "ack_answer_revision": ack})
    assert response.status_code == 422


def test_received_revision_requires_a_session_and_is_never_inferred_from_server_output(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    from app import main
    assert client.post("/v1/glasses/state", headers=HEADERS,
                       json={**STATE, "ack_answer_revision": 1}).status_code == 422
    monkeypatch.setattr(main, "exam_answer_bundle", lambda _: {
        "available_stage": "complete", "revision": 2, "items": [{"status": "ready"}],
    })
    waiting = {**STATE, "session_id": 7, "phase": "waiting"}
    client.post("/v1/glasses/state", headers=HEADERS, json=waiting)
    url = "/v1/glasses/state?device_id=glasses-serial"
    assert client.get(url, headers=HEADERS).json()["ack_answer_revision"] is None
    client.post("/v1/glasses/state", headers=HEADERS,
                json={**waiting, "sequence": 2, "ack_answer_revision": 1})
    restarted = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "exam_answer_bundle", lambda _: {
        "available_stage": "complete", "revision": 2, "items": [{"status": "ready"}],
    })
    restored = restarted.get(url, headers=HEADERS).json()
    assert restored["ack_answer_revision"] == 1
    assert restored["answer_revision"] == 2


def test_received_revision_never_regresses_within_a_session_or_leaks_into_a_new_generation(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    reading = {**STATE, "session_id": 7, "phase": "reading", "ack_answer_revision": 2}
    client.post("/v1/glasses/state", headers=HEADERS, json=reading)
    url = "/v1/glasses/state?device_id=glasses-serial"
    for sequence, ack in [(2, 1), (3, None)]:
        client.post("/v1/glasses/state", headers=HEADERS,
                    json={**reading, "phase": "waiting", "sequence": sequence, "ack_answer_revision": ack})
        assert client.get(url, headers=HEADERS).json()["ack_answer_revision"] == 2
    client.post("/v1/glasses/state", headers=HEADERS, json={**STATE, "generation": 4, "phase": "chooser"})
    assert client.get(url, headers=HEADERS).json()["ack_answer_revision"] is None


@pytest.mark.parametrize("changed", [
    {"phase": "capturing"}, {"session_id": 7}, {"display_request": "sleep"},
    {"display_request": None}, {"entry_request": "other"},
])
def test_chooser_entry_request_requires_a_fresh_visible_sessionless_chooser(tmp_path, monkeypatch, changed):
    client = _client(tmp_path, monkeypatch)
    entry = {**STATE, "phase": "chooser", "display_request": "wake", "entry_request": "chooser"}
    assert client.post("/v1/glasses/state", headers=HEADERS, json={**entry, **changed}).status_code == 422
    assert client.get("/v1/glasses/state", headers=HEADERS).json() == {"devices": []}


def test_wear_entry_needs_a_new_generation_after_a_closed_run(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/v1/glasses/state", headers=HEADERS, json={**STATE, "phase": "closed"})
    entry = {**STATE, "phase": "chooser", "sequence": 2, "display_request": "wake", "entry_request": "chooser"}
    assert client.post("/v1/glasses/state", headers=HEADERS, json=entry).json()["accepted"] is False
    assert client.post("/v1/glasses/state", headers=HEADERS,
                       json={**entry, "generation": 4}).json()["accepted"] is True
    saved = client.get("/v1/glasses/state?device_id=glasses-serial", headers=HEADERS).json()
    assert saved["entry_request"] == "chooser" and saved["generation"] == 4


def test_new_generation_during_partial_bundle_read_revokes_the_old_wake(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    from app import main
    from app.glasses_state import GlassesState, record_state
    waiting = {**STATE, "session_id": 7, "phase": "waiting"}
    client.post("/v1/glasses/state", headers=HEADERS, json=waiting)

    def bundle(_):
        record_state(GlassesState(**{**STATE, "generation": 4, "phase": "chooser"}), "10.0.0.12")
        return {"items": [{"status": "ready"}, {"status": "pending"}], "revision": 4, "available_stage": "reading"}

    monkeypatch.setattr(main, "exam_answer_bundle", bundle)
    saved = client.get("/v1/glasses/state?device_id=glasses-serial", headers=HEADERS).json()
    assert saved["generation"] == 4 and saved["phase"] == "chooser"
    assert saved["answer_ready"] is False and saved["answer_revision"] == 0 and saved["available_stage"] == "none"


@pytest.mark.parametrize(("kind", "code", "resumable"), [
    ("AuthenticationRequired", "authentication_failed", True),
    ("BrowserUnavailable", "browser_unavailable", True),
    ("AttachmentFailed", "attachment_failed", True),
    ("ModelMismatch", "model_mismatch", True),
    ("Uncertain", "browser_outcome_unknown", False),
])
def test_presend_failures_have_distinct_codes_and_unknown_sends_are_never_resumed(
        tmp_path, monkeypatch, kind, code, resumable):
    client = _client(tmp_path, monkeypatch)
    from app import main
    from app.layout import ProblemUnit
    from app.solvers import chatgpt_web
    doc_id = client.post("/v1/documents", json={"title": "test"}, headers=HEADERS).json()["document_id"]
    client.post(f"/v1/documents/{doc_id}/pages", data={"page_index": 0, "ocr_text": "問1 2+2"}, headers=HEADERS)
    client.post(f"/v1/documents/{doc_id}/finalize", headers=HEADERS)
    session_id = client.post("/v1/exam-sessions", json={"mode": "study", "document_id": doc_id}, headers=HEADERS).json()["session_id"]
    error = getattr(chatgpt_web, "ChatGptWeb" + kind)("a provider message containing private data")
    with main.db.connect() as conn:
        main._insert_deck(conn, session_id, doc_id, [ProblemUnit("問1", "問1", start_page_index=0)])
        row = main._deck_question_rows(conn, session_id)[0]
        main._record_solve_failure(conn, row, error)
        updated = main._deck_question_rows(conn, session_id)[0]
        assert main._solve_failure(updated) == {"code": code}
        assert main._retrying(updated) is resumable
        assert main._nothing_sent(error) is resumable


def test_phone_setup_defers_unsent_material_without_failure_and_resumes_after_permission(
        tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    from app import main
    from app.solvers.base import SolveResult

    doc_id = client.post("/v1/documents", json={"title": "test"}, headers=HEADERS).json()["document_id"]
    client.post(f"/v1/documents/{doc_id}/pages", data={"page_index": 0, "ocr_text": "問1 2+2"}, headers=HEADERS)
    client.post(f"/v1/documents/{doc_id}/finalize", headers=HEADERS)
    session_id = client.post("/v1/exam-sessions", json={"mode": "study", "document_id": doc_id}, headers=HEADERS).json()["session_id"]
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-web")
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "0")
    calls = []

    def answer_all(question):
        calls.append(question.chat_key)
        return [({"group": "", "label": "問1", "pages": [1]}, SolveResult(answer="4"))]

    monkeypatch.setattr(main, "_answer_all", answer_all)
    finalized = client.post(f"/v1/exam-sessions/{session_id}/finalize-reading?solve=background", headers=HEADERS)
    assert finalized.status_code == 200
    deadline = time.monotonic() + 3
    while session_id in main._background_solves and time.monotonic() < deadline:
        time.sleep(0.01)
    main._resume_all_answers()
    assert client.get(f"/v1/exam-sessions/{session_id}/answer-bundle", headers=HEADERS).status_code == 409
    with main.db.connect() as conn:
        assert conn.execute("SELECT status FROM exam_sessions WHERE id = ?", (session_id,)).fetchone()[0] == "reviewing"
        assert conn.execute("SELECT ocr_text FROM pages WHERE document_id = ?", (doc_id,)).fetchone()[0] == "問1 2+2"
        assert not main._deck_question_rows(conn, session_id)
        assert conn.execute("SELECT count(*) FROM solutions").fetchone()[0] == 0
    assert calls == []

    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    main._resume_all_answers()
    deadline = time.monotonic() + 3
    while session_id in main._background_solves and time.monotonic() < deadline:
        time.sleep(0.01)
    bundle = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle", headers=HEADERS).json()
    assert [(item["status"], item["answer"]) for item in bundle["items"]] == [("ready", "4")]
    main._resume_all_answers()
    assert calls == [f"session:{session_id}"]


def test_setup_provider_reports_permission_without_touching_the_browser(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    from app.solvers import get_solver
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-web")
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "0")
    solver = get_solver("chatgpt-web")
    monkeypatch.setattr(solver, "info", lambda: pytest.fail("unapproved browser check"))
    status = client.get("/v1/settings").json()["providers"]["solver"]
    assert status["ready"] is False and status["code"] == "send_not_authorized"


def test_permission_does_not_clear_an_old_uncertain_send(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    from app import main
    from app.solvers.chatgpt_web import ChatGptWebSendNotAuthorized, ChatGptWebUncertain
    doc_id = client.post("/v1/documents", json={"title": "test"}, headers=HEADERS).json()["document_id"]
    client.post(f"/v1/documents/{doc_id}/pages", data={"page_index": 0, "ocr_text": "問1 2+2"}, headers=HEADERS)
    client.post(f"/v1/documents/{doc_id}/finalize", headers=HEADERS)
    session_id = client.post("/v1/exam-sessions", json={"mode": "study", "document_id": doc_id}, headers=HEADERS).json()["session_id"]
    client.post(f"/v1/exam-sessions/{session_id}/finalize-reading", headers=HEADERS)
    with main.db.connect() as conn:
        row = main._deck_question_rows(conn, session_id)[0]
        main._record_solve_failure(conn, row, ChatGptWebUncertain("old uncertain send"))
        before = conn.execute("SELECT structure_json FROM questions WHERE id = ?", (row["id"],)).fetchone()[0]
        main._record_solve_failure(conn, row, ChatGptWebSendNotAuthorized("setup only"))
        assert conn.execute("SELECT structure_json FROM questions WHERE id = ?", (row["id"],)).fetchone()[0] == before
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-web")
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    monkeypatch.setattr(main, "_answer_all", lambda _: pytest.fail("uncertain send was retried"))
    main._resume_all_answers()
    bundle = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle", headers=HEADERS).json()
    assert bundle["items"][0]["status"] == "failed"
    assert "自動再送は停止" in bundle["items"][0]["issue"]
    assert session_id not in main._background_solves


def test_setup_also_preserves_a_pending_synchronous_compatibility_deck(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    from app import main
    doc_id = client.post("/v1/documents", json={"title": "test"}, headers=HEADERS).json()["document_id"]
    client.post(f"/v1/documents/{doc_id}/pages", data={"page_index": 0, "ocr_text": "問1 2+2"}, headers=HEADERS)
    client.post(f"/v1/documents/{doc_id}/finalize", headers=HEADERS)
    session_id = client.post("/v1/exam-sessions", json={"mode": "study", "document_id": doc_id}, headers=HEADERS).json()["session_id"]
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-web")
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "0")
    monkeypatch.setattr(main, "solve_with_fallback", lambda **_: pytest.fail("setup reached provider"))
    response = client.post(f"/v1/exam-sessions/{session_id}/finalize-reading", headers=HEADERS)
    assert response.status_code == 200 and response.json()["server_solved"] == 0
    item = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle", headers=HEADERS).json()["items"][0]
    assert item["status"] == "pending"
    with main.db.connect() as conn:
        row = main._deck_question_rows(conn, session_id)[0]
        assert main._solve_failure(row) == {} and main._failure_count(row) == 0
