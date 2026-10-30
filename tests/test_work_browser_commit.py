"""The local browser cannot seal results across a changed wearer/input."""

import asyncio
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException

from app import main
from app.glasses_state import state_guard
from app.work_bridge import WorkConflict
from tests.test_chatgpt_work_web import browser_page as browser_page, page as page
from tests.test_work_bridge import api_session, client as client, wait_for


def test_internal_browser_commit_rejects_a_stale_job_before_sealing(monkeypatch):
    def stale(_):
        raise HTTPException(status_code=409, detail="the glasses generation changed")

    monkeypatch.setattr(main, "_work_current_job", stale)
    with pytest.raises(WorkConflict, match="no longer current"):
        main._commit_work_browser_result("stale-job", result={"questions": []})


def test_wearer_change_cannot_interleave_with_browser_result_sealing(monkeypatch):
    entered, attempted, release, changed = (threading.Event() for _ in range(4))
    current_generation = [7]

    class Store:
        def submit_browser_result(self, job_id, **payload):
            entered.set()
            assert attempted.wait(3)
            assert release.wait(3)
            assert current_generation == [7]
            assert not changed.is_set()
            return {"job_id": job_id, "generation": 7, "status": "completed"}

    def current(_):
        if current_generation != [7]:
            raise HTTPException(status_code=409, detail="the glasses generation changed")
        return Store(), {"generation": 7, "status": "queued", "manifest_sha256": "fixed-manifest"}

    def change_wearer():
        attempted.set()
        with state_guard():
            current_generation[0] = 8
            changed.set()

    monkeypatch.setattr(main, "_work_current_job", current)
    monkeypatch.setattr(main, "_resume_answers", lambda *a: pytest.fail("sealing must not start a second solver"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        sealing = pool.submit(main._commit_work_browser_result, "job", manifest_sha256="fixed-manifest",
                              result={"questions": []})
        assert entered.wait(3)
        rollover = pool.submit(change_wearer)
        try:
            assert attempted.wait(3)
            assert not changed.is_set()
        finally:
            release.set()
        assert sealing.result(timeout=3)["status"] == "completed"
        rollover.result(timeout=3)
    assert changed.is_set()
    with pytest.raises(WorkConflict, match="no longer current"):
        main._commit_work_browser_result("job", manifest_sha256="fixed-manifest", result={"questions": []})


def test_completed_recording_replacement_invalidates_its_work_job(monkeypatch, tmp_path):
    audio = tmp_path / "original.wav"
    audio.write_bytes(b"same-size original audio")
    job = {"session_id": 1, "device_id": "glasses", "generation": 7,
           "sources": [{"page_number": 1, "sha256": "page-sha"},
                       {"source_id": "audio", "sha256": hashlib.sha256(audio.read_bytes()).hexdigest()}]}

    class Store:
        def get(self, _):
            return job

    class Connection:
        def close(self):
            pass

    monkeypatch.setattr(main, "configured_work_store", Store)
    monkeypatch.setattr(main.db, "connect", Connection)
    monkeypatch.setattr(main, "_exam_session_or_404", lambda *a: {
        "document_id": 1, "mode": "practice", "audio_path": str(audio)})
    monkeypatch.setattr(main, "_session_phase", lambda _: "reviewing")
    monkeypatch.setattr(main, "work_binding", lambda _: ("glasses", 7))
    monkeypatch.setattr(main, "_document_source_pages", lambda *a: [
        {"page_number": 1, "image_sha256": "page-sha"}])
    assert main._work_current_job("job")[1] is job
    audio.write_bytes(b"same-size replaced audio")
    with pytest.raises(HTTPException) as error:
        main._work_current_job("job")
    assert error.value.status_code == 409


@pytest.mark.parametrize("provider", ["chatgpt-web", "chatgpt-work"])
def test_supervised_browser_may_start_after_the_phone_api(monkeypatch, provider):
    import app.solvers

    monkeypatch.setenv("ROKID_SOLVER", provider)
    monkeypatch.setattr(main.config, "REAL_MODE", True)
    monkeypatch.setattr(main, "ensure_dirs", lambda: None)
    monkeypatch.setattr(main.db, "init_db", lambda: None)
    monkeypatch.setattr(main, "get_analyzer", lambda: object())
    monkeypatch.setattr(main, "_resume_all_answers", lambda: None)
    monkeypatch.setattr(app.solvers, "get_solver", lambda: pytest.fail("browser is checked before sending"))

    async def start():
        async with main.lifespan(main.app):
            pass

    asyncio.run(start())


def test_nonbrowser_real_provider_is_still_checked_at_startup(monkeypatch):
    import app.solvers

    monkeypatch.setenv("ROKID_SOLVER", "not-a-browser")
    monkeypatch.setattr(main.config, "REAL_MODE", True)
    monkeypatch.setattr(main, "ensure_dirs", lambda: None)
    monkeypatch.setattr(main.db, "init_db", lambda: None)
    monkeypatch.setattr(main, "get_analyzer", lambda: object())

    def unready():
        raise RuntimeError("unready real provider")

    monkeypatch.setattr(app.solvers, "get_solver", unready)

    async def start():
        async with main.lifespan(main.app):
            pass

    with pytest.raises(RuntimeError, match="unready real provider"):
        asyncio.run(start())


@pytest.mark.parametrize("stale", [False, True])
def test_rejected_readability_stops_visibly_without_resend_for_only_the_current_wearer(
        client, monkeypatch, stale):
    from app import glasses_state
    from app.work_bridge import WorkReadabilityRejected, configured_work_store

    doc, session, job = api_session(client, generation=7)
    wait_for(lambda: session not in main._background_solves)
    calls = []

    def reject(question):
        calls.append(question.booklet_stage)
        if stale:
            assert glasses_state.record_state(glasses_state.GlassesState(
                device_id="fixture-glasses", session_id=session, generation=8,
                sequence=1, phase="analyzing"), "127.0.0.1")
        raise WorkReadabilityRejected("browser readability review does not support answering")

    monkeypatch.setattr(main, "_answer_all", reject)
    main._solve_deck_in_background(session, doc)
    assert calls == ["single"]
    assert configured_work_store().result(job["job_id"]) is None
    monkeypatch.setattr(main, "_resume_answers", lambda *args: None)
    response = client.get(f"/v1/exam-sessions/{session}/answer-bundle")
    if stale:
        assert response.status_code == 409
        with main.db.connect() as conn:
            assert not any(main._solve_failure(row) for row in conn.execute(
                "SELECT structure_json FROM questions WHERE session_id=?", (session,)))
    else:
        assert response.status_code == 200
        bundle = response.json()
        assert [(item["status"], item["answer"], item["issue"]) for item in bundle["items"]] == [
            ("failed", "", "画像の判読確認と回答が一致しません。資料は保持しています")]


@pytest.mark.parametrize("corrupt", ["manifest", "hash", "dimensions", "review"])
def test_current_browser_result_validation_failure_is_visible_without_resubmitting(
        client, monkeypatch, corrupt):
    from app.solvers.chatgpt_work import ChatGptWorkSolver
    from app.work_bridge import configured_work_store
    from tests.test_chatgpt_work import BrowserReply

    doc, session, job = api_session(client, generation=7)
    wait_for(lambda: session not in main._background_solves)

    class InvalidReply(BrowserReply):
        def complete_json(self, **options):
            reply = super().complete_json(**options)
            if corrupt == "manifest":
                reply["manifest_sha256"] = "0" * 64
            elif corrupt == "hash":
                reply["extraction"]["files"][0]["sha256"] = "0" * 64
            elif corrupt == "dimensions":
                reply["extraction"]["files"][0]["width"] += 1
            else:
                reply["readability"] = []
            return reply

    fake = InvalidReply()
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    monkeypatch.setattr(main, "get_solver", lambda *args: ChatGptWorkSolver(client=fake))
    main._solve_deck_in_background(session, doc)
    assert len(fake.calls) == 1
    assert configured_work_store().result(job["job_id"]) is None
    monkeypatch.setattr(main, "_resume_answers", lambda *args: None)
    response = client.get(f"/v1/exam-sessions/{session}/answer-bundle")
    assert response.status_code == 200, response.text
    assert [(item["status"], item["answer"], item["issue"]) for item in response.json()["items"]] == [
        ("failed", "", "Workの返答と原画像の照合に失敗しました。資料は保持しています")]


def test_a_concurrently_sealed_valid_result_wins_over_a_rejected_browser_reply(client, monkeypatch):
    from app.solvers.chatgpt_work import ChatGptWorkSolver
    from app.work_bridge import configured_work_store
    from tests.test_chatgpt_work import BrowserReply
    from tests.test_work_bridge import answer, api_complete, api_tile_receipt

    doc, session, job = api_session(client, generation=7)
    wait_for(lambda: session not in main._background_solves)
    acquired = [api_tile_receipt(client, job)]
    monkeypatch.setattr(main, "_resume_answers", lambda *args: None)

    class LateInvalidReply(BrowserReply):
        def complete_json(self, **options):
            reply = super().complete_json(**options)
            response = api_complete(client, job, acquired, answer(text="先行した答案"))
            assert response.status_code == 200, response.text
            reply["manifest_sha256"] = "0" * 64
            return reply

    fake = LateInvalidReply()
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    monkeypatch.setattr(main, "get_solver", lambda *args: ChatGptWorkSolver(client=fake))
    main._solve_deck_in_background(session, doc)
    assert len(fake.calls) == 1
    assert configured_work_store().result(job["job_id"]) == answer(text="先行した答案")
    response = client.get(f"/v1/exam-sessions/{session}/answer-bundle")
    assert response.status_code == 200, response.text
    assert [(item["status"], item["answer"]) for item in response.json()["items"]] == [
        ("ready", "先行した答案")]


@pytest.mark.parametrize("stage", ["single", "reading"])
def test_state_poll_recovers_the_current_work_job_after_an_uncertain_send(client, monkeypatch, stage):
    from app.solvers.chatgpt_work import ChatGptWorkSolver
    from app.work_bridge import configured_work_store
    from tests.test_chatgpt_work import BrowserReply

    doc, session, job = api_session(client, exam_type="mixed" if stage == "reading" else "written", generation=7)
    wait_for(lambda: session not in main._background_solves)
    fake = BrowserReply()
    fake.fail_once = True
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    monkeypatch.setattr(main, "get_solver", lambda *args: ChatGptWorkSolver(client=fake))
    main._solve_deck_in_background(session, doc)
    assert len(fake.calls) == 1 and configured_work_store().result(job["job_id"]) is None
    with main.db.connect() as conn:
        row = main._deck_question_rows(conn, session)[0]
        assert main._solve_failure(row) == {"code": "browser_outcome_unknown", "work_job_id": job["job_id"]}
        # Uncertain recovery is a read of its durable batch, not another bounded
        # presend attempt. A long generation must survive repeated phone polls.
        metadata = main.json.loads(row["structure_json"])
        metadata["solve_failures"] = main.RESUME_LIMIT + 1
        conn.execute("UPDATE questions SET structure_json=? WHERE id=?", (main.json.dumps(metadata), row["id"]))
        conn.commit()
        assert main._retrying(main._deck_question_rows(conn, session)[0])
    response = client.get("/v1/glasses/state?device_id=fixture-glasses")
    assert response.status_code == 200, response.text
    wait_for(lambda: configured_work_store().result(job["job_id"]))
    wait_for(lambda: session not in main._background_solves)
    assert len(fake.calls) == 2  # Browser entry/recovery; the DOM test counts actual Send clicks.
    bundle = client.get(f"/v1/exam-sessions/{session}/answer-bundle").json()
    assert bundle["items"][0]["answer"] == "4"
    assert bundle["items"][0]["status"] == "ready"
    assert bundle["available_stage"] == ("reading" if stage == "reading" else "complete")


@pytest.mark.parametrize("change", ["generation", "original", "missing_job"])
def test_uncertain_work_recovery_cannot_restart_for_a_stale_or_missing_input(client, monkeypatch, change):
    from app import glasses_state
    from app.solvers.chatgpt_work import ChatGptWorkSolver
    from tests.test_chatgpt_work import BrowserReply, picture

    doc, session, job = api_session(client, generation=7)
    wait_for(lambda: session not in main._background_solves)
    fake = BrowserReply()
    fake.fail_once = True
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    monkeypatch.setattr(main, "get_solver", lambda *args: ChatGptWorkSolver(client=fake))
    main._solve_deck_in_background(session, doc)
    if change == "generation":
        glasses_state.record_state(glasses_state.GlassesState(device_id="fixture-glasses", session_id=session,
            generation=8, sequence=1, phase="analyzing"), "127.0.0.1")
    elif change == "original":
        from pathlib import Path
        with main.db.connect() as conn:
            path = main._document_source_pages(conn, doc, session)[0]["image_path"]
        Path(path).write_bytes(picture(99))
    else:
        with main.db.connect() as conn:
            row = main._deck_question_rows(conn, session)[0]
            metadata = main.json.loads(row["structure_json"])
            metadata["solve_failure"]["work_job_id"] = "0" * 64
            conn.execute("UPDATE questions SET structure_json=? WHERE id=?", (main.json.dumps(metadata), row["id"]))
            conn.commit()
    with main.db.connect() as conn:
        assert not main._resume_answers(conn, main._exam_session_or_404(conn, session))
    assert len(fake.calls) == 1


def test_a_previous_chat_unknown_send_does_not_become_a_new_work_send(client, monkeypatch):
    from app.solvers.chatgpt_web import ChatGptWebUncertain

    doc, session, _ = api_session(client, generation=7)
    wait_for(lambda: session not in main._background_solves)
    def old_chat_failure(question):
        raise ChatGptWebUncertain("provider-private message")
    monkeypatch.setattr(main, "_answer_all", old_chat_failure)
    main._solve_deck_in_background(session, doc)
    with main.db.connect() as conn:
        row = main._deck_question_rows(conn, session)[0]
        assert main._solve_failure(row) == {"code": "browser_outcome_unknown"}
        assert not main._retrying(row)
        assert not main._resume_answers(conn, main._exam_session_or_404(conn, session))


def test_state_poll_recovers_the_real_local_work_dom_without_a_second_send(client, page, monkeypatch):
    import json
    from types import SimpleNamespace

    from app.solvers import cdp, chatgpt_web
    from app.solvers.chatgpt_work import ChatGptWorkSolver
    from app.solvers.chatgpt_work_web import WorkWebClient
    from app.work_bridge import configured_work_store
    from tests.test_chatgpt_work import BrowserReply
    from tests.test_chatgpt_work_web import _Context, _VenueTab, _guard_state, _upload_composer

    doc, session, job = api_session(client, generation=7)
    wait_for(lambda: session not in main._background_solves)
    _upload_composer(page)
    page.evaluate("window.suppressFinal = true")
    tab = _VenueTab(page)
    envelope = []

    class LocalWork(WorkWebClient):
        def complete_json(self, **options):
            if not envelope:
                # This fixture supplies a source-bound body; actual DOM controls,
                # Send click, uncertainty journal and final recovery stay real.
                envelope.append(BrowserReply().complete_json(**options))
                page.evaluate("window.boundReply = " + json.dumps(envelope[0]) + "; true")
                page.evaluate("""window.finish = function() {
                    const users = document.querySelectorAll('[data-user-message-bubble=true]');
                    const receipt = JSON.parse(users[users.length-1].textContent.split('Transfer receipt:\\n').at(-1));
                    const owner = document.createElement('div');
                    owner.setAttribute('data-local-conversation-final-assistant','true');
                    const final = document.createElement('div');
                    final.setAttribute('data-markdown-text-style','assistant-message');
                    final.textContent = JSON.stringify({...window.boundReply, batch_id:receipt.batch_id});
                    owner.append(final); document.getElementById('conversation').append(owner);
                }; true""")
            return super().complete_json(**options)

    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    monkeypatch.setattr(cdp, "connect_over_cdp", lambda endpoint: SimpleNamespace(
        contexts=[_Context(tab)], close=lambda: None))
    monkeypatch.setattr(chatgpt_web, "POLL_S", 0.001)
    monkeypatch.setattr(chatgpt_web, "RETRY_BACKOFF_S", 0)
    monkeypatch.setattr(chatgpt_web, "TIMEOUT_S", 0.2)
    monkeypatch.setattr(chatgpt_web, "REPLY_START_S", 0.05)
    monkeypatch.setattr(main, "get_solver", lambda *args: ChatGptWorkSolver(client=LocalWork()))
    main._solve_deck_in_background(session, doc)
    assert page.evaluate("window.sent") == 1 and _guard_state() == "uncertain"
    assert configured_work_store().result(job["job_id"]) is None
    page.evaluate("window.finish()")
    assert client.get("/v1/glasses/state?device_id=fixture-glasses").status_code == 200
    wait_for(lambda: configured_work_store().result(job["job_id"]))
    wait_for(lambda: session not in main._background_solves)
    assert page.evaluate("window.sent") == 1 and _guard_state() == "idle"
    assert len(page.evaluate("window.uploaded")) == 1
    bundle = client.get(f"/v1/exam-sessions/{session}/answer-bundle").json()
    assert [(item["status"], item["answer"]) for item in bundle["items"]] == [("ready", "4")]


def test_new_session_retires_an_expired_work_send_without_old_answers_or_another_old_send(client, page, monkeypatch):
    import json
    from types import SimpleNamespace

    from app.solvers import cdp, chatgpt_web
    from app.solvers.chatgpt_work import ChatGptWorkSolver
    from app.solvers.chatgpt_work_web import WorkWebClient
    from app.work_bridge import configured_work_store
    from tests.test_chatgpt_work import BrowserReply
    from tests.test_chatgpt_work_web import _Context, _VenueTab, _guard_state, _upload_composer

    doc, session, old = api_session(client, generation=7)
    wait_for(lambda: session not in main._background_solves)
    _upload_composer(page)
    page.evaluate("window.suppressFinal = true")
    tab = _VenueTab(page)

    class LocalWork(WorkWebClient):
        def complete_json(self, **options):
            body = BrowserReply().complete_json(**options)
            page.evaluate("window.boundReply = " + json.dumps(body) + "; true")
            page.evaluate("""window.finish = function() {
                const users = document.querySelectorAll('[data-user-message-bubble=true]');
                const receipt = JSON.parse(users[users.length-1].textContent.split('Transfer receipt:\\n').at(-1));
                const owner = document.createElement('div');
                owner.setAttribute('data-local-conversation-final-assistant','true');
                const final = document.createElement('div');
                final.setAttribute('data-markdown-text-style','assistant-message');
                final.textContent = JSON.stringify({...window.boundReply, batch_id:receipt.batch_id});
                owner.append(final); document.getElementById('conversation').append(owner);
            }; true""")
            return super().complete_json(**options)

    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    monkeypatch.setattr(cdp, "connect_over_cdp", lambda endpoint: SimpleNamespace(
        contexts=[_Context(tab)], close=lambda: None))
    monkeypatch.setattr(chatgpt_web, "POLL_S", 0.001)
    monkeypatch.setattr(chatgpt_web, "TIMEOUT_S", 0.2)
    monkeypatch.setattr(chatgpt_web, "REPLY_START_S", 0.05)
    monkeypatch.setattr(main, "PRESEND_TRIES", 1)
    monkeypatch.setattr(main, "get_solver", lambda *args: ChatGptWorkSolver(client=LocalWork()))
    main._solve_deck_in_background(session, doc)
    assert page.evaluate("window.sent") == 1 and _guard_state() == "uncertain"
    with main.db.connect() as conn:
        old_revision = main._answer_revision(conn, session)
    assert client.post("/v1/glasses/state", json={"device_id": "fixture-glasses", "session_id": session,
        "generation": 7, "sequence": 2, "phase": "closed"}).json()["accepted"]
    assert client.get("/v1/glasses/state?device_id=fixture-glasses").json()["answer_ready"] is False

    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "0")
    _, newer, _ = api_session(client, generation=8)
    store = configured_work_store()
    queued = wait_for(lambda: next((job for job in store.list_jobs()["jobs"] if job["session_id"] == newer), None))
    wait_for(lambda: newer not in main._background_solves)
    original_read = type(store).read_source
    def read_source(instance, job_id, source_id):
        assert job_id != old["job_id"], "retirement must not reopen or rebuild the old originals"
        return original_read(instance, job_id, source_id)
    monkeypatch.setattr(type(store), "read_source", read_source)
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    # An unfinished known stale owner remains pending across more than the
    # ordinary preparation-failure budget, without pretending the new job sent.
    for _ in range(main.RESUME_LIMIT + 1):
        assert client.get("/v1/glasses/state?device_id=fixture-glasses").status_code == 200
        wait_for(lambda: newer not in main._background_solves)
    with main.db.connect() as conn:
        assert not any(main._solve_failure(row) for row in main._deck_question_rows(conn, newer))
    from app.browser_guard import BrowserGuard
    navigations = len(tab.navigations)
    with BrowserGuard():
        for _ in range(main.RESUME_LIMIT + 1):
            assert client.get("/v1/glasses/state?device_id=fixture-glasses").status_code == 200
            wait_for(lambda: newer not in main._background_solves)
        with main.db.connect() as conn:
            assert not any(main._solve_failure(row) for row in main._deck_question_rows(conn, newer))
    with main._background_solves_lock:
        main._background_solves.add(session)
    try:
        for _ in range(main.RESUME_LIMIT + 1):
            assert client.get("/v1/glasses/state?device_id=fixture-glasses").status_code == 200
            wait_for(lambda: newer not in main._background_solves)
        with main.db.connect() as conn:
            assert not any(main._solve_failure(row) for row in main._deck_question_rows(conn, newer))
    finally:
        with main._background_solves_lock:
            main._background_solves.discard(session)
    assert len(tab.navigations) == navigations
    assert page.evaluate("window.sent") == 1 and _guard_state() == "uncertain"
    page.evaluate("window.finish(); window.suppressFinal = false")
    assert client.get("/v1/glasses/state?device_id=fixture-glasses").status_code == 200
    wait_for(lambda: store.result(queued["job_id"]))
    wait_for(lambda: newer not in main._background_solves)
    assert page.evaluate("window.sent") == 2 and _guard_state() == "idle"
    assert len(page.evaluate("window.uploaded")) == 2
    assert store.result(old["job_id"]) is None
    with main.db.connect() as conn:
        assert main._answer_revision(conn, session) == old_revision
        assert not any(main._latest_solution_row(conn, row["id"]) for row in main._deck_question_rows(conn, session))
    bundle = client.get(f"/v1/exam-sessions/{newer}/answer-bundle").json()
    assert [(item["status"], item["answer"]) for item in bundle["items"]] == [("ready", "4")]


@pytest.mark.parametrize("change", ["generation", "closed", "writing_done", "original", "current",
                                   "missing_image", "missing_owner", "ambiguous_owner", "active", "policy"])
def test_expired_work_guard_requires_positive_expiry_and_an_inactive_known_wearer(client, monkeypatch, change):
    from pathlib import Path
    from app import config, glasses_state
    from app.work_bridge import WorkPending
    from tests.test_chatgpt_work import picture

    doc, session, job = api_session(client, generation=7)
    wait_for(lambda: session not in main._background_solves)
    if change in ("generation", "closed", "writing_done", "active"):
        state = glasses_state.GlassesState(device_id="fixture-glasses", session_id=session,
            generation=8 if change == "generation" else 7, sequence=2,
            phase=change if change in ("closed", "writing_done") else "analyzing")
        assert glasses_state.record_state(state, "127.0.0.1")
    elif change in ("original", "missing_image"):
        with main.db.connect() as conn:
            image = Path(main._document_source_pages(conn, doc, session)[0]["image_path"])
        if change == "original":
            image.write_bytes(picture(99))
        else:
            image.unlink()
    elif change == "missing_owner":
        for path in (config.DATA_DIR / "glasses-state").glob("*.json"):
            path.unlink()
    elif change == "ambiguous_owner":
        assert glasses_state.record_state(glasses_state.GlassesState(device_id="other-glasses", session_id=session,
            generation=1, sequence=1, phase="analyzing"), "127.0.0.1")
    elif change == "policy":
        with main.db.connect() as conn:
            conn.execute("UPDATE exam_sessions SET mode='real' WHERE id=?", (session,))
        monkeypatch.setattr(config, "ALLOW_REAL_EXAM_SOLVE", False)
        with pytest.raises(HTTPException) as error:
            main._work_current_job(job["job_id"])
        assert error.value.status_code == 409
    if change == "active":
        with main._background_solves_lock:
            main._background_solves.add(session)
    try:
        if change in ("generation", "closed", "writing_done", "original"):
            with main._expired_work_job_guard(job["job_id"]) as expired:
                assert expired["job_id"] == job["job_id"]
        else:
            with pytest.raises(WorkPending if change == "active" else WorkConflict):
                with main._expired_work_job_guard(job["job_id"]):
                    pytest.fail("a live/unknown Work input authorized retirement")
    finally:
        with main._background_solves_lock:
            main._background_solves.discard(session)
