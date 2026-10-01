"""Reading answers precede original audio in one durable mixed-exam session."""

import importlib
import io
import sqlite3
import threading
import time
import wave

import pytest
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ROKID_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ROKID_SOLVER", raising=False)
    monkeypatch.delenv("ROKID_API_KEY", raising=False)
    from app import config, db, main
    for module in (config, db, main):
        importlib.reload(module)
    main.ensure_dirs()
    db.init_db()
    return TestClient(main.app)


def _session(client, exam_type="mixed"):
    doc_id = client.post("/v1/documents", json={"title": "English paper"}).json()["document_id"]
    photo = io.BytesIO()
    Image.new("RGB", (120, 160), "white").save(photo, format="PNG")
    response = client.post(f"/v1/documents/{doc_id}/pages",
                           data={"page_index": 0, "ocr_text": "問1 reading\n問2 listening"},
                           files={"image": ("page.png", photo.getvalue(), "image/png")})
    assert response.status_code == 201
    assert client.post(f"/v1/documents/{doc_id}/finalize").status_code == 200
    response = client.post("/v1/exam-sessions", json={"mode": "mock", "document_id": doc_id, "exam_type": exam_type})
    assert response.status_code == 201
    return doc_id, response.json()["session_id"]


def test_mixed_session_keeps_exam_mode_and_starts_with_reading_stage(client):
    _, session_id = _session(client)
    session = client.get(f"/v1/exam-sessions/{session_id}").json()
    assert session["mode"] == "mock" and session["exam_type"] == "mixed"
    assert session["analysis_stage"] == "reading"


def test_ordinary_session_uses_the_compatible_single_stage(client):
    _, session_id = _session(client, "written")
    assert client.get(f"/v1/exam-sessions/{session_id}").json()["analysis_stage"] == "single"


def _wait(session_id):
    from app import main
    deadline = time.monotonic() + 5
    while session_id in main._background_solves and time.monotonic() < deadline:
        time.sleep(0.01)
    assert session_id not in main._background_solves


def _reading_reply():
    from app.solvers.base import SolveResult
    return [
        ({"group": "第1問", "label": "問1", "answer_no": [1], "pages": [1], "requires_audio": False},
         SolveResult(answer="4", extras={"answer_no": [1]})),
        ({"group": "第2問", "label": "問1", "answer_no": [2], "pages": [1], "requires_audio": True}, None),
    ]


def test_first_stage_commits_all_question_ids_but_only_reading_solutions(client, monkeypatch):
    from app import main
    doc_id, session_id = _session(client)
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-web")
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    requests = []

    def answer_all(question):
        requests.append(question)
        return _reading_reply()

    monkeypatch.setattr(main, "_answer_all", answer_all)
    assert client.post(f"/v1/exam-sessions/{session_id}/finalize-reading?solve=background").status_code == 200
    _wait(session_id)
    bundle = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()
    assert bundle["analysis_stage"] == "awaiting_audio" and bundle["available_stage"] == "reading"
    assert [(item["status"], item["answer_no"]) for item in bundle["items"]] == [("ready", [1]), ("pending", [2])]
    assert requests[0].booklet_stage == "reading" and requests[0].audio_path is None
    assert requests[0].document_pages[0]["image_path"]
    with main.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM solutions").fetchone()[0] == 1
        assert conn.execute("SELECT document_id FROM exam_sessions WHERE id=?", (session_id,)).fetchone()[0] == doc_id
    client.post(f"/v1/exam-sessions/{session_id}/finalize-reading?solve=background")
    _wait(session_id)
    assert len(requests) == 1


def test_mixed_base_input_digest_is_unchanged_when_original_audio_is_bound(client):
    from app import main
    _, session_id = _session(client)
    with main.db.connect() as conn:
        session = main._exam_session_or_404(conn, session_id)
        before = main._answer_input_digest(conn, session)
        audio = main.config.DATA_DIR / "recording.wav"
        audio.write_bytes(b"captured original audio")
        conn.execute("UPDATE exam_sessions SET audio_path=? WHERE id=?", (str(audio), session_id))
        session = main._exam_session_or_404(conn, session_id)
        assert main._answer_input_digest(conn, session) == before


def test_mixed_input_identity_comes_from_original_images_not_later_ocr_edits(client):
    from app import main
    doc_id, session_id = _session(client)
    with main.db.connect() as conn:
        before = main._answer_input_digest(conn, main._exam_session_or_404(conn, session_id))
        conn.execute("UPDATE pages SET ocr_text='later OCR', vision_text='later description' WHERE document_id=?", (doc_id,))
        assert main._answer_input_digest(conn, main._exam_session_or_404(conn, session_id)) == before


def _record_complete(client, doc_id):
    samples = 64
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as target:
        target.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        target.writeframes(b"\x01\x00" * samples)
    original = buffer.getvalue()
    response = client.post(f"/v1/documents/{doc_id}/audio-chunks",
                           data={"sequence": 0, "start_sample": 0, "captured_at_ms": 10000},
                           files={"audio": ("chunk.wav", original, "audio/wav")})
    assert response.status_code == 200
    response = client.post(f"/v1/documents/{doc_id}/audio-complete",
                           json={"expected_chunks": 1, "total_samples": samples})
    assert response.status_code == 200
    return original


@pytest.mark.parametrize("arrival", ["before", "during", "after"])
def test_completed_audio_waits_for_reading_commit_then_updates_only_listening(client, monkeypatch, arrival):
    from app import main
    from app.solvers.base import SolveResult
    doc_id, session_id = _session(client)
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-web")
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    reading_started, release_reading = threading.Event(), threading.Event()
    stages, first_bundles = [], []

    def answer_all(question):
        stages.append(question.booklet_stage)
        if question.booklet_stage == "reading":
            assert question.audio_path is None
            reading_started.set()
            assert release_reading.wait(3)
            return _reading_reply()
        first_bundles.append(main.exam_answer_bundle(session_id))
        slot = question.booklet_questions[0]
        assert slot["answer_no"] == [2]
        return [({**slot, "group": "changed", "label": "changed", "answer_no": [999], "pages": [999]},
                 SolveResult(answer="3", extras={"answer_no": [999]}))]

    monkeypatch.setattr(main, "_answer_all", answer_all)
    if arrival == "before":
        _record_complete(client, doc_id)
        assert client.post(f"/v1/exam-sessions/{session_id}/document-audio").status_code == 200
    assert client.post(f"/v1/exam-sessions/{session_id}/finalize-reading?solve=background").status_code == 200
    assert reading_started.wait(3)
    if arrival == "during":
        _record_complete(client, doc_id)
        assert client.post(f"/v1/exam-sessions/{session_id}/document-audio").status_code == 200
    assert stages == ["reading"]
    release_reading.set()
    _wait(session_id)
    if arrival == "after":
        assert client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()["available_stage"] == "reading"
        _record_complete(client, doc_id)
        assert client.post(f"/v1/exam-sessions/{session_id}/document-audio").status_code == 200
        _wait(session_id)
    bundle = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()
    assert stages == ["reading", "listening"]
    first = first_bundles[0]
    assert first["available_stage"] == "reading" and first["items"][0]["answer"] == "4"
    assert bundle["analysis_stage"] == "complete" and bundle["available_stage"] == "complete"
    assert bundle["input_digest"] == first["input_digest"]
    shape = lambda snapshot: [(item["question_id"], item["group_id"], item["question_label"], item["answer_no"]) for item in snapshot["items"]]  # noqa: E731
    assert shape(bundle) == shape(first)
    assert [item["answer"] for item in bundle["items"]] == ["4", "3"]
    assert bundle["revision"] > first["revision"]
    assert client.post(f"/v1/exam-sessions/{session_id}/document-audio").status_code == 200
    main._resume_all_answers()
    _wait(session_id)
    assert stages == ["reading", "listening"]


def test_restart_after_audio_binding_resumes_only_pending_listening(client, monkeypatch):
    from app import main
    from app.solvers.base import SolveResult
    doc_id, session_id = _session(client)
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-web")
    stages = []

    def answer_all(question):
        stages.append(question.booklet_stage)
        if question.booklet_stage == "reading":
            return _reading_reply()
        return [(question.booklet_questions[0], SolveResult(answer="3"))]

    monkeypatch.setattr(main, "_answer_all", answer_all)
    client.post(f"/v1/exam-sessions/{session_id}/finalize-reading?solve=background")
    _wait(session_id)
    _record_complete(client, doc_id)
    with monkeypatch.context() as paused:
        paused.setattr(main, "_resume_answers", lambda *args: False)
        assert client.post(f"/v1/exam-sessions/{session_id}/document-audio").status_code == 200
    assert stages == ["reading"]
    main._resume_all_answers()
    _wait(session_id)
    assert stages == ["reading", "listening"]
    assert client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()["analysis_stage"] == "complete"


def test_uncertain_audio_send_keeps_reading_answers_and_does_not_automatically_resend(client, monkeypatch):
    from app import main
    from app.solvers.chatgpt_web import ChatGptWebUncertain
    doc_id, session_id = _session(client)
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-web")
    stages = []

    def answer_all(question):
        stages.append(question.booklet_stage)
        if question.booklet_stage == "reading":
            return _reading_reply()
        raise ChatGptWebUncertain("outcome unknown")

    monkeypatch.setattr(main, "_answer_all", answer_all)
    client.post(f"/v1/exam-sessions/{session_id}/finalize-reading?solve=background")
    _wait(session_id)
    first = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()
    _record_complete(client, doc_id)
    assert client.post(f"/v1/exam-sessions/{session_id}/document-audio").status_code == 200
    _wait(session_id)
    main._resume_all_answers()
    bundle = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()
    assert stages == ["reading", "listening"]
    assert bundle["items"][0] == first["items"][0]
    assert bundle["items"][1]["status"] == "failed" and "自動再送は停止" in bundle["items"][1]["issue"]


@pytest.mark.parametrize("failure", ["uncertain", "chat_lost", "invalid_reply"])
def test_terminal_first_stage_failure_is_readable_and_blocks_audio_and_restart(client, monkeypatch, failure):
    from app import main
    from app.solvers.chatgpt_web import ChatGptWebChatLost, ChatGptWebUncertain
    doc_id, session_id = _session(client)
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-web")
    _record_complete(client, doc_id)
    assert client.post(f"/v1/exam-sessions/{session_id}/document-audio").status_code == 200
    stages = []

    def answer_all(question):
        stages.append(question.booklet_stage)
        if failure == "invalid_reply":
            return []
        raise (ChatGptWebUncertain("outcome unknown") if failure == "uncertain"
               else ChatGptWebChatLost("original chat missing"))

    monkeypatch.setattr(main, "_answer_all", answer_all)
    client.post(f"/v1/exam-sessions/{session_id}/finalize-reading?solve=background")
    _wait(session_id)
    first = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()
    main._resume_all_answers()
    assert client.post(f"/v1/exam-sessions/{session_id}/document-audio").status_code == 200
    client.post(f"/v1/exam-sessions/{session_id}/finalize-reading?solve=background")
    _wait(session_id)
    final = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()
    assert stages == ["reading"]  # No second image send and no listening stage.
    assert final == first
    assert first["analysis_stage"] == "reading" and first["available_stage"] == "reading"
    assert first["items"][0]["status"] == "failed" and first["items"][0]["issue"]
    assert first["items"][0]["answer"] == ""
    with main.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM solutions").fetchone()[0] == 0


@pytest.mark.parametrize("stage", ["reading", "listening"])
def test_mixed_presend_recovery_saves_the_successful_reply(client, monkeypatch, stage):
    from app import main
    from app.solvers.base import SolveResult
    from app.solvers.chatgpt_web import ChatGptWebBrowserUnavailable
    doc_id, session_id = _session(client)
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-web")
    monkeypatch.setattr(main, "PRESEND_TRIES", 2)
    monkeypatch.setattr(main, "PRESEND_RETRY_S", 0)
    if stage == "listening":
        monkeypatch.setattr(main, "_answer_all", lambda _: _reading_reply())
        with main.db.connect() as conn:
            main._answer_mixed_deck(conn, main._exam_session_or_404(conn, session_id), session_id, doc_id)
        _record_complete(client, doc_id)
        with monkeypatch.context() as paused:
            paused.setattr(main, "_resume_answers", lambda *args: False)
            assert client.post(f"/v1/exam-sessions/{session_id}/document-audio").status_code == 200
    attempts = []

    def answer_all(question):
        attempts.append(question.booklet_stage)
        if len(attempts) == 1:
            raise ChatGptWebBrowserUnavailable("disconnected before send")
        return (_reading_reply() if stage == "reading" else
                [(question.booklet_questions[0], SolveResult(answer="3"))])

    monkeypatch.setattr(main, "_answer_all", answer_all)
    with main.db.connect() as conn:
        main._answer_mixed_deck(conn, main._exam_session_or_404(conn, session_id), session_id, doc_id)
        assert attempts == [stage, stage]
        expected_stage, expected_solutions = ("awaiting_audio", 1) if stage == "reading" else ("complete", 2)
        assert main._exam_session_or_404(conn, session_id)["analysis_stage"] == expected_stage
        assert conn.execute("SELECT count(*) FROM solutions").fetchone()[0] == expected_solutions


def test_first_stage_presend_retry_stays_pending_without_a_readable_stage(client, monkeypatch):
    from app import main
    from app.solvers.chatgpt_web import ChatGptWebBrowserUnavailable
    _, session_id = _session(client)
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-web")
    monkeypatch.setattr(main, "PRESEND_TRIES", 1)

    def answer_all(question):
        raise ChatGptWebBrowserUnavailable("not connected before send")

    monkeypatch.setattr(main, "_answer_all", answer_all)
    client.post(f"/v1/exam-sessions/{session_id}/finalize-reading?solve=background")
    _wait(session_id)
    bundle = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()
    assert bundle["analysis_stage"] == "reading" and bundle["available_stage"] == "none"
    assert bundle["items"][0]["status"] == "pending"


def test_mixed_binding_rejects_incomplete_or_changed_original_audio(client, monkeypatch):
    from app import main, listening
    doc_id, session_id = _session(client)
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-web")
    assert client.post(f"/v1/exam-sessions/{session_id}/document-audio").status_code == 409
    original = _record_complete(client, doc_id)
    audio = listening.folder(doc_id) / "original.wav"
    raw = audio.read_bytes()
    audio.write_bytes(raw[:-2] + b"\x02\x00")
    assert client.post(f"/v1/exam-sessions/{session_id}/document-audio").status_code == 409
    assert (listening.folder(doc_id) / "0000.wav").read_bytes() == original
    with main.db.connect() as conn:
        assert conn.execute("SELECT audio_path FROM exam_sessions WHERE id=?", (session_id,)).fetchone()[0] is None


def test_audio_arriving_at_worker_exit_is_not_lost(client, monkeypatch):
    from app import main
    from app.solvers.base import SolveResult
    doc_id, session_id = _session(client)
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-web")
    boundary, bound = threading.Event(), threading.Event()
    stages = []
    real_pending = main._mixed_work_pending

    def pending(conn, session):
        if (threading.current_thread().name.startswith("solve-session-")
                and session["analysis_stage"] == "awaiting_audio" and not session["audio_path"]
                and not boundary.is_set()):
            boundary.set()
            assert bound.wait(3)
            return False  # the worker's snapshot predates the concurrent bind
        return real_pending(conn, session)

    def answer_all(question):
        stages.append(question.booklet_stage)
        return (_reading_reply() if question.booklet_stage == "reading" else
                [(question.booklet_questions[0], SolveResult(answer="3"))])

    monkeypatch.setattr(main, "_mixed_work_pending", pending)
    monkeypatch.setattr(main, "_answer_all", answer_all)
    client.post(f"/v1/exam-sessions/{session_id}/finalize-reading?solve=background")
    assert boundary.wait(3)
    _record_complete(client, doc_id)
    assert client.post(f"/v1/exam-sessions/{session_id}/document-audio").status_code == 200
    assert stages == ["reading"]
    bound.set()
    deadline = time.monotonic() + 5
    while stages != ["reading", "listening"] and time.monotonic() < deadline:
        time.sleep(0.01)
    _wait(session_id)
    assert stages == ["reading", "listening"]
    assert client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()["available_stage"] == "complete"


@pytest.mark.parametrize("crash_stage", ["reading", "listening"])
def test_stage_reply_lost_before_db_commit_is_recovered_without_another_browser_send(client, monkeypatch, crash_stage):
    from app import main
    from app.solvers import cdp, chatgpt_web
    from tests.test_chatgpt_web_solver import _Browser, _MixedBatchPage, _clicks, _fast, _sends
    doc_id, session_id = _session(client)
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-web")
    _fast(monkeypatch)
    page = _MixedBatchPage()
    monkeypatch.setattr(cdp, "connect_over_cdp", lambda _: _Browser(page))
    solver = chatgpt_web.ChatGptWebSolver()

    def answer_all(question):
        page.stage = question.booklet_stage
        return solver.answer_all(question=question)

    monkeypatch.setattr(main, "_answer_all", answer_all)
    _record_complete(client, doc_id)
    assert client.post(f"/v1/exam-sessions/{session_id}/document-audio").status_code == 200
    real_save, failures, thread_errors = main._save_solution, [], []
    crash_reported = threading.Event()

    def report_crash(args):
        thread_errors.append(args.exc_type)
        crash_reported.set()

    monkeypatch.setattr(threading, "excepthook", report_crash)

    def save(conn, *args, **kwargs):
        stage = main._exam_session_or_404(conn, session_id)["analysis_stage"]
        if stage == crash_stage and not failures:
            failures.append(stage)
            raise sqlite3.OperationalError("simulated loss before DB commit")
        return real_save(conn, *args, **kwargs)

    monkeypatch.setattr(main, "_save_solution", save)
    client.post(f"/v1/exam-sessions/{session_id}/finalize-reading?solve=background")
    _wait(session_id)
    assert crash_reported.wait(3)
    assert failures == [crash_stage] and thread_errors == [sqlite3.OperationalError]
    with main.db.connect() as conn:
        assert main._exam_session_or_404(conn, session_id)["analysis_stage"] == crash_stage
        assert conn.execute("SELECT count(*) FROM solutions").fetchone()[0] == (0 if crash_stage == "reading" else 1)
    main._resume_all_answers()
    _wait(session_id)
    bundle = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()
    assert bundle["available_stage"] == "complete" and [i["answer"] for i in bundle["items"]] == ["4", "3"]
    assert len(_sends(page)) == 2 and len(_clicks(page, chatgpt_web.NEW_CHAT_SEL)) == 1
    assert [f["mimeType"] for upload in page.uploads for f in upload] == ["image/jpeg", "audio/wav"]


def test_changed_audio_after_binding_is_rejected_before_the_second_solver_call(client, monkeypatch):
    from app import main, listening
    doc_id, session_id = _session(client)
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-web")
    stages = []

    def answer_all(question):
        stages.append(question.booklet_stage)
        return _reading_reply()

    monkeypatch.setattr(main, "_answer_all", answer_all)
    client.post(f"/v1/exam-sessions/{session_id}/finalize-reading?solve=background")
    _wait(session_id)
    original = _record_complete(client, doc_id)
    with monkeypatch.context() as paused:
        paused.setattr(main, "_resume_answers", lambda *args: False)
        assert client.post(f"/v1/exam-sessions/{session_id}/document-audio").status_code == 200
    audio = listening.folder(doc_id) / "original.wav"
    raw = audio.read_bytes()
    audio.write_bytes(raw[:-2] + b"\x02\x00")
    main._resume_all_answers()
    _wait(session_id)
    bundle = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()
    assert stages == ["reading"] and bundle["items"][0]["answer"] == "4"
    assert bundle["items"][1]["status"] == "failed"
    assert (listening.folder(doc_id) / "0000.wav").read_bytes() == original


def test_mixed_mode_cannot_be_changed_after_analysis_begins(client, monkeypatch):
    from app import main
    _, session_id = _session(client)
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-web")
    monkeypatch.setattr(main, "_answer_all", lambda _: _reading_reply())
    client.post(f"/v1/exam-sessions/{session_id}/finalize-reading?solve=background")
    _wait(session_id)
    assert client.post(f"/v1/exam-sessions/{session_id}/mode", json={"exam_type": "written"}).status_code == 409


def test_mode_change_that_races_with_mixed_analysis_is_rejected(client, monkeypatch):
    from app import main
    _, session_id = _session(client)
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-web")
    monkeypatch.setattr(main, "_answer_all", lambda _: _reading_reply())
    read_mode, release_mode = threading.Event(), threading.Event()
    original_session = main._exam_session_or_404
    result = []

    def session_snapshot(conn, requested_id):
        session = original_session(conn, requested_id)
        if threading.current_thread().name == "mode-race":
            read_mode.set()
            assert release_mode.wait(3)
        return session

    def change_mode():
        try:
            main.exam_set_mode(session_id, main.ExamMode(exam_type="written"))
            result.append(200)
        except main.HTTPException as error:
            result.append(error.status_code)

    monkeypatch.setattr(main, "_exam_session_or_404", session_snapshot)
    worker = threading.Thread(target=change_mode, name="mode-race")
    worker.start()
    try:
        assert read_mode.wait(3)
        assert client.post(f"/v1/exam-sessions/{session_id}/finalize-reading?solve=background").status_code == 200
        _wait(session_id)
    finally:
        release_mode.set()
        worker.join(3)
    assert result == [409]
    with main.db.connect() as conn:
        session = original_session(conn, session_id)
        assert (session["exam_type"], session["analysis_stage"], session["status"]) == (
            "mixed", "awaiting_audio", "reviewing")


def test_finalize_claims_the_mode_before_reading_its_session_snapshot(client, monkeypatch):
    from app import main
    _, session_id = _session(client, "written")
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-web")
    monkeypatch.setattr(main, "_answer_all", lambda _: _reading_reply())
    read_session, release_finalize = threading.Event(), threading.Event()
    original_session = main._exam_session_or_404

    def session_snapshot(conn, requested_id):
        session = original_session(conn, requested_id)
        if threading.current_thread().name == "finalize-race":
            read_session.set()
            assert release_finalize.wait(3)
        return session

    monkeypatch.setattr(main, "_exam_session_or_404", session_snapshot)
    worker = threading.Thread(target=main.exam_finalize_reading,
                              args=(session_id, "background"), name="finalize-race")
    worker.start()
    try:
        assert read_session.wait(3)
        with main.db.connect() as conn:
            conn.execute("PRAGMA busy_timeout=0")
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                conn.execute("UPDATE exam_sessions SET exam_type='mixed', analysis_stage='reading' WHERE id=?",
                             (session_id,))
    finally:
        release_finalize.set()
        worker.join(3)
        _wait(session_id)
    assert client.post(f"/v1/exam-sessions/{session_id}/mode", json={"exam_type": "mixed"}).status_code == 409
