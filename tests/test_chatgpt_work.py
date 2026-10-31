"""Work core integration with local byte fixtures; no browser or cloud calls."""

import hashlib
import io
import re
import wave
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from tests.test_work_bridge import api_session, client as _client_fixture, picture, wait_for

client = _client_fixture


@pytest.mark.parametrize("available", [False, True])
def test_real_browser_client_presence_cannot_replace_a_readiness_probe(monkeypatch, available):
    from app.solvers import chatgpt_work
    from app.solvers.chatgpt_web import ChatGptWebClient

    endpoint, calls = "http://127.0.0.1:1", []
    def probe(target):
        calls.append(target)
        return {"Browser": "local fixture"} if available else None
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    monkeypatch.setattr(chatgpt_work, "cdp_available", probe)
    info = chatgpt_work.ChatGptWorkSolver(client=ChatGptWebClient(endpoint=endpoint)).info()
    assert info["ready"] is available
    assert calls == [endpoint]


class BrowserReply:
    model = "GPT-6.1 Sol"
    conversation_id = "observed-browser-chat"

    def __init__(self):
        self.calls = []
        self.before = None
        self.after = None
        self.fail_once = False

    def resolve_new_job_settings(self, *, requested_settings, follow_family):
        from app.work_model_policy import resolve_work_model
        return {**requested_settings, "model": resolve_work_model(
            ["gpt-6.1-sol"], requested_settings["model"], follow_family=follow_family)}

    def complete_json(self, **options):
        if self.before:
            self.before()
        options["before_submit"]()
        files = list(options["files"]())
        self.calls.append({**options, "files": files})
        extracted, reviews = [], []
        for payload in files:
            if payload["mimeType"] == "application/zip":
                with zipfile.ZipFile(io.BytesIO(payload["buffer"])) as archive:
                    for name in archive.namelist():
                        number = len(reviews) + 1
                        assert name == f"page_{number:03d}.png"
                        assert archive.getinfo(name).date_time == (1980, 1, 1, 0, 0, 0)
                        raw = archive.read(name)
                        with Image.open(io.BytesIO(raw)) as image:
                            width, height = image.size
                        sha = hashlib.sha256(raw).hexdigest()
                        assert sha not in options["prompt"]
                        extracted.append({"source_id": f"p{number}", "file_name": name,
                                          "sha256": sha, "width": width, "height": height})
                        reviews.append({"source_id": f"p{number}", "status": "readable",
                                        "image_viewer_used": True, "reasons": []})
            else:
                extracted.append({"source_id": "audio", "file_name": payload["name"],
                                  "sha256": hashlib.sha256(payload["buffer"]).hexdigest()})
        questions = [{"group": "第1問", "label": "問1", "pages": [1], "answer_no": [1],
                      "status": "ready", "answer": "4", "diagrams": []}]
        if options["booklet_stage"] == "reading":
            questions[0]["requires_audio"] = False
            questions.append({"group": "Listening", "label": "問2", "pages": [1], "answer_no": [2],
                              "requires_audio": True, "status": "pending_audio", "answer": "", "diagrams": []})
        elif options["booklet_stage"] == "listening":
            questions[0].update(question_id=options["stage_question_ids"][0], answer_no=[2], label="問2")
        if self.fail_once and len(self.calls) == 1:
            from app.solvers.chatgpt_web import ChatGptWebUncertain
            raise ChatGptWebUncertain("fixture interrupted after submit")
        if self.after:
            self.after()
        return {"manifest_sha256": re.search(r"manifest_sha256=([a-f0-9]{64})", options["prompt"])[1],
                "extraction": {"status": "ok", "files": extracted}, "readability": reviews, "questions": questions}


def test_local_work_browser_returns_original_bound_answers_and_restart_reads_the_sealed_job(client, monkeypatch):
    from app import main
    from app.solvers.base import Question
    from app.solvers.chatgpt_work import ChatGptWorkSolver

    doc, session, job = api_session(client, generation=7)
    wait_for(lambda: session not in main._background_solves)
    with main.db.connect() as conn:
        pages = main._document_source_pages(conn, doc, session)
    question = Question(chat_key=f"session:{session}", document_pages=pages)
    fake = BrowserReply()
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    replies = ChatGptWorkSolver(client=fake).answer_all(question=question)
    assert replies[0][1].answer == "4"
    assert replies[0][1].extras["browser_review"]["calibrated"] is False
    assert replies[0][1].extras["visual_reading_verified"] is False
    assert fake.calls[0]["files"][0]["mimeType"] == "application/zip"
    assert b"page_001.png" in fake.calls[0]["files"][0]["buffer"]
    assert fake.calls[0]["requested_settings"] == job["requested_settings"]
    class NoBrowser:
        def complete_json(self, **options):
            pytest.fail("a sealed job must not send again")
    monkeypatch.setenv("ROKID_WORK_MODEL", "GPT-6.99 Sol")
    resumed = ChatGptWorkSolver(client=NoBrowser()).answer_all(question=question)
    assert resumed[0][1].answer == "4"
    assert len(fake.calls) == 1


def question_for(doc, session, *, stage="single", **extra):
    from app import main
    from app.solvers.base import Question
    with main.db.connect() as conn:
        pages = main._document_source_pages(conn, doc, session)
    return Question(chat_key=f"session:{session}", document_pages=pages, booklet_stage=stage, **extra)


@pytest.mark.parametrize(("count", "soft_limit"), [(21, None), (47, 1), (21, 1250)])
def test_canonical_pages_remain_byte_exact_in_bounded_deterministic_zips_after_interruption(
        client, monkeypatch, count, soft_limit):
    from app import main
    from app.solvers.chatgpt_web import ChatGptWebUncertain
    from app.solvers.chatgpt_work import ChatGptWorkSolver
    from app.solvers import chatgpt_work
    from app.work_bridge import configured_work_store

    doc = client.post("/v1/documents", json={"title": "21 native originals"}).json()["document_id"]
    for number in range(count):
        assert client.post(f"/v1/documents/{doc}/pages", data={"page_index": number},
            files={"image": ("page.png", picture(number), "image/png")}).status_code == 201
    assert client.post(f"/v1/documents/{doc}/finalize").status_code == 200
    session = client.post("/v1/exam-sessions", json={"document_id": doc, "mode": "study"}).json()["session_id"]
    assert client.post(f"/v1/exam-sessions/{session}/finalize-reading?solve=background").status_code == 200
    wait_for(lambda: configured_work_store().list_jobs()["jobs"])
    wait_for(lambda: session not in main._background_solves)
    question = question_for(doc, session)
    fake = BrowserReply()
    fake.fail_once = True
    if soft_limit is not None:
        monkeypatch.setattr(chatgpt_work, "MAX_BROWSER_ZIP_BYTES", soft_limit)
        monkeypatch.setattr(chatgpt_work, "MAX_BROWSER_FILE_BYTES", 1500)
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    with pytest.raises(ChatGptWebUncertain):
        ChatGptWorkSolver(client=fake).answer_all(question=question)
    assert len(configured_work_store().list_jobs()["jobs"]) == 1
    monkeypatch.setenv("ROKID_WORK_MODEL", "GPT-6.99 Sol")
    fake.resolve_new_job_settings = lambda **options: pytest.fail("an uncertain job must retain its model")
    assert ChatGptWorkSolver(client=fake).answer_all(question=question)[0][1].answer == "4"
    assert fake.calls[0]["requested_settings"] == fake.calls[1]["requested_settings"]
    first, second = [call["files"] for call in fake.calls]
    assert first == second
    entries = {}
    for file in first:
        with zipfile.ZipFile(io.BytesIO(file["buffer"])) as archive:
            if soft_limit == 1:
                assert len(archive.infolist()) == 1  # A page over the soft target stays intact.
            entries.update({name: archive.read(name) for name in archive.namelist()})
    assert len(entries) == count
    assert all(entries[f"page_{page['page_number']:03d}.png"] == Path(page["image_path"]).read_bytes()
               for page in question.document_pages)
    if soft_limit is None:
        assert len(first) == 1
    else:
        assert sum(len(file["buffer"]) for file in first) > chatgpt_work.MAX_BROWSER_FILE_BYTES
        assert all(len(file["buffer"]) <= chatgpt_work.MAX_BROWSER_FILE_BYTES for file in first)
    assert configured_work_store().list_jobs()["jobs"] == []


@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("change", ["generation", "closed", "original"])
def test_browser_delivery_cannot_send_or_commit_for_changed_glasses_or_originals(client, monkeypatch, when, change):
    from app import glasses_state, main
    from app.solvers.chatgpt_work import ChatGptWorkSolver
    from app.work_bridge import WorkConflict, configured_work_store

    doc, session, job = api_session(client, generation=7)
    wait_for(lambda: session not in main._background_solves)
    question = question_for(doc, session)
    fake = BrowserReply()
    def mutate():
        if change == "original":
            Path(question.document_pages[0]["image_path"]).write_bytes(picture(99))
        else:
            glasses_state.record_state(glasses_state.GlassesState(device_id="fixture-glasses", session_id=session,
                generation=8 if change == "generation" else 7, sequence=2,
                phase="analyzing" if change == "generation" else "closed"), "127.0.0.1")
    setattr(fake, when, mutate)
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    with pytest.raises(WorkConflict):
        ChatGptWorkSolver(client=fake).answer_all(question=question)
    assert len(fake.calls) == (0 if when == "before" else 1)
    assert configured_work_store().result(job["job_id"]) is None


def test_mixed_work_stages_keep_the_same_browser_chat_and_send_only_original_audio_later(client, monkeypatch, tmp_path):
    from app import main
    from app.solvers.chatgpt_work import ChatGptWorkSolver
    from app.work_bridge import configured_work_store

    doc, session, first = api_session(client, exam_type="mixed", generation=7)
    wait_for(lambda: session not in main._background_solves)
    fake = BrowserReply()
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    reading = ChatGptWorkSolver(client=fake).answer_all(question=question_for(doc, session, stage="reading"))
    assert reading[0][1].answer == "4" and reading[1][1] is None
    monkeypatch.setattr(main, "get_solver", lambda *args: ChatGptWorkSolver(client=fake))
    main._solve_deck_in_background(session, doc)
    monkeypatch.setenv("ROKID_WORK_MODEL", "GPT-6.99 Sol")
    fake.resolve_new_job_settings = lambda **options: pytest.fail("listening must inherit the reading model")
    audio = tmp_path / "original.wav"
    with wave.open(str(audio), "wb") as output:
        output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        output.writeframes(b"\x01\x00" * 64)
    assert client.post(f"/v1/documents/{doc}/audio-chunks",
        data={"sequence": 0, "start_sample": 0, "captured_at_ms": 10000},
        files={"audio": ("chunk.wav", audio.read_bytes(), "audio/wav")}).status_code == 200
    assert client.post(f"/v1/documents/{doc}/audio-complete",
        json={"expected_chunks": 1, "total_samples": 64}).status_code == 200
    assert client.post(f"/v1/exam-sessions/{session}/document-audio").status_code == 200
    wait_for(lambda: len(fake.calls) == 2)
    wait_for(lambda: session not in main._background_solves)
    assert fake.calls[0]["chat_key"] == fake.calls[1]["chat_key"]
    assert fake.calls[0]["requested_settings"] == fake.calls[1]["requested_settings"] == first["requested_settings"]
    assert [file["mimeType"] for file in fake.calls[1]["files"]] == ["audio/wav"]
    with main.db.connect() as conn:
        recorded_path = conn.execute("SELECT audio_path FROM exam_sessions WHERE id=?", (session,)).fetchone()[0]
    assert fake.calls[1]["files"][0]["buffer"] == Path(recorded_path).read_bytes()
    bundle = client.get(f"/v1/exam-sessions/{session}/answer-bundle").json()
    assert [item["answer"] for item in bundle["items"]] == ["4", "4"]
    listening_job = next(source for source in configured_work_store().list_jobs()["jobs"]
                         if source["stage"] == "listening") if configured_work_store().list_jobs()["jobs"] else None
    assert listening_job is None
    assert configured_work_store().result(first["job_id"])["questions"][0]["answer"] == "4"


def test_disabled_send_and_oversized_package_keep_the_sealed_originals_without_browser_calls(client, monkeypatch):
    from app import main
    from app.solvers import chatgpt_work
    from app.work_bridge import WorkConflict, WorkPending, configured_work_store

    doc, session, job = api_session(client, generation=7)
    wait_for(lambda: session not in main._background_solves)
    question = question_for(doc, session)
    fake = BrowserReply()
    with pytest.raises(WorkPending):
        chatgpt_work.ChatGptWorkSolver(client=fake).answer_all(question=question)
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    monkeypatch.setattr(chatgpt_work, "MAX_BROWSER_FILE_BYTES", 64)
    with pytest.raises(WorkConflict, match="budget"):
        chatgpt_work.ChatGptWorkSolver(client=fake).answer_all(question=question)
    assert fake.calls == []
    assert configured_work_store().result(job["job_id"]) is None
    assert Path(question.document_pages[0]["image_path"]).is_file()


@pytest.mark.parametrize("when", ["before", "after"])
def test_original_audio_replacement_cannot_send_or_seal_listening_answers(client, monkeypatch, when):
    from app import main
    from app.solvers.chatgpt_work import ChatGptWorkSolver
    from app.work_bridge import configured_work_store

    doc, session, reading_job = api_session(client, exam_type="mixed", generation=7)
    wait_for(lambda: session not in main._background_solves)
    fake = BrowserReply()
    monkeypatch.setattr(main, "get_solver", lambda *args: ChatGptWorkSolver(client=fake))
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    main._solve_deck_in_background(session, doc)
    audio = io.BytesIO()
    with wave.open(audio, "wb") as output:
        output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        output.writeframes(b"\x01\x00" * 64)
    assert client.post(f"/v1/documents/{doc}/audio-chunks",
        data={"sequence": 0, "start_sample": 0, "captured_at_ms": 10000},
        files={"audio": ("chunk.wav", audio.getvalue(), "audio/wav")}).status_code == 200
    assert client.post(f"/v1/documents/{doc}/audio-complete",
        json={"expected_chunks": 1, "total_samples": 64}).status_code == 200
    def replace_audio():
        with main.db.connect() as conn:
            path = Path(conn.execute("SELECT audio_path FROM exam_sessions WHERE id=?", (session,)).fetchone()[0])
        original = path.read_bytes()
        path.write_bytes(original[:-2] + b"\x02\x00")  # Same path/size, different original samples.
    setattr(fake, when, replace_audio)
    assert client.post(f"/v1/exam-sessions/{session}/document-audio").status_code == 200
    wait_for(lambda: any(job["stage"] == "listening" for job in configured_work_store().list_jobs()["jobs"]))
    wait_for(lambda: session not in main._background_solves)
    assert len(fake.calls) == (1 if when == "before" else 2)
    pending = next(job for job in configured_work_store().list_jobs()["jobs"] if job["stage"] == "listening")
    assert configured_work_store().result(pending["job_id"]) is None
    assert configured_work_store().result(reading_job["job_id"])["questions"][0]["answer"] == "4"


@pytest.mark.parametrize("policy", [None, "exact"])
def test_new_browser_job_seals_actual_inventory_model_and_reuses_it_after_restart(tmp_path, monkeypatch, policy):
    from app.solvers import chatgpt_work
    from app.solvers.base import Question
    from app.work_bridge import WorkPending, WorkStore

    store = WorkStore(tmp_path)
    original = tmp_path / "page.png"
    original.write_bytes(picture())
    question = Question(chat_key="session:1", document_pages=[{"page_number": 1, "image_path": str(original)}])
    monkeypatch.setattr(chatgpt_work, "configured_work_store", lambda: store)
    monkeypatch.setattr(chatgpt_work, "work_binding", lambda session_id: ("fixture-glasses", 7))
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    monkeypatch.delenv("ROKID_WORK_MODEL", raising=False)
    if policy:
        monkeypatch.setenv("ROKID_WORK_MODEL_POLICY", policy)
    else:
        monkeypatch.delenv("ROKID_WORK_MODEL_POLICY", raising=False)

    def pending(*args):
        raise WorkPending("fixture pauses after durable enqueue, before Send")
    monkeypatch.setattr(chatgpt_work.ChatGptWorkSolver, "_consume_browser", pending)

    class Inventory:
        calls = []

        def resolve_new_job_settings(self, *, requested_settings, follow_family):
            self.calls.append((requested_settings, follow_family))
            return {**requested_settings, "model": "GPT-6.10 Sol" if follow_family else "GPT 6.1 Sol"}

    inventory = Inventory()
    with pytest.raises(WorkPending):
        chatgpt_work.ChatGptWorkSolver(client=inventory).answer_all(question=question)
    first = store.session_jobs(1)[0]
    assert first["requested_settings"] == {"model": "GPT-6.10 Sol" if policy is None else "GPT 6.1 Sol",
                                          "effort": "xhigh", "speed": "fast"}
    assert inventory.calls == [({"model": "gpt-6.1-sol", "effort": "xhigh", "speed": "fast"}, policy is None)]
    raw, _ = store.read_source(first["job_id"], "p1")
    assert raw == original.read_bytes()
    monkeypatch.setenv("ROKID_WORK_MODEL", "GPT-6.99 Sol")
    monkeypatch.setenv("ROKID_WORK_MODEL_POLICY", "invalid-after-seal")
    with pytest.raises(WorkPending):
        chatgpt_work.ChatGptWorkSolver(client=inventory).answer_all(question=question)
    assert store.session_jobs(1)[0]["job_id"] == first["job_id"] and len(inventory.calls) == 1


@pytest.mark.parametrize("failure", ["unavailable", "authentication", "missing-resolver", "bad-policy"])
def test_new_browser_inventory_failure_preserves_original_and_allows_later_resume(tmp_path, monkeypatch, failure):
    from app.solvers import chatgpt_work
    from app.solvers.base import Question
    from app.solvers.chatgpt_web import ChatGptWebAuthenticationRequired, ChatGptWebBrowserUnavailable, ChatGptWebModelMismatch
    from app.work_bridge import WorkPending, WorkStore

    store = WorkStore(tmp_path)
    original = tmp_path / "page.png"
    original.write_bytes(picture())
    before = original.read_bytes(), original.stat().st_mtime_ns
    question = Question(chat_key="session:1", document_pages=[{"page_number": 1, "image_path": str(original)}])
    monkeypatch.setattr(chatgpt_work, "configured_work_store", lambda: store)
    monkeypatch.setattr(chatgpt_work, "work_binding", lambda session_id: ("fixture-glasses", 7))
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    monkeypatch.delenv("ROKID_WORK_MODEL_POLICY", raising=False)
    error = {"unavailable": ChatGptWebBrowserUnavailable, "authentication": ChatGptWebAuthenticationRequired,
             "missing-resolver": ChatGptWebModelMismatch, "bad-policy": ChatGptWebModelMismatch}[failure]

    class Inventory:
        unavailable = True

        def resolve_new_job_settings(self, *, requested_settings, follow_family):
            if self.unavailable:
                raise error("fixture browser is unavailable or unauthenticated")
            return {**requested_settings, "model": "GPT-6.10 Sol"}

    def pending(*args):
        raise WorkPending("fixture pauses before Send")
    monkeypatch.setattr(chatgpt_work.ChatGptWorkSolver, "_consume_browser", pending)
    inventory = Inventory()
    if failure == "bad-policy":
        monkeypatch.setenv("ROKID_WORK_MODEL_POLICY", "unreviewed-policy")
    with pytest.raises(error):
        chatgpt_work.ChatGptWorkSolver(client=object() if failure == "missing-resolver" else inventory).answer_all(question=question)
    assert store.session_jobs(1) == []
    assert (original.read_bytes(), original.stat().st_mtime_ns) == before
    inventory.unavailable = False
    monkeypatch.delenv("ROKID_WORK_MODEL_POLICY", raising=False)
    with pytest.raises(WorkPending):
        chatgpt_work.ChatGptWorkSolver(client=inventory).answer_all(question=question)
    assert store.session_jobs(1)[0]["requested_settings"]["model"] == "GPT-6.10 Sol"


@pytest.mark.parametrize("send_enabled", ["0", "1"])
def test_orphan_listening_preserves_originals_and_rejects_before_model_inventory(tmp_path, monkeypatch, send_enabled):
    from app.solvers import chatgpt_work
    from app.solvers.base import Question
    from app.work_bridge import WorkConflict, WorkStore

    store = WorkStore(tmp_path)
    original = tmp_path / "page.png"
    original.write_bytes(picture())
    audio = tmp_path / "original.wav"
    with wave.open(str(audio), "wb") as output:
        output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        output.writeframes(b"\x01\x00" * 64)
    before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in (original, audio)]
    monkeypatch.setattr(chatgpt_work, "configured_work_store", lambda: store)
    monkeypatch.setattr(chatgpt_work, "work_binding", lambda session_id: ("fixture-glasses", 7))
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", send_enabled)
    monkeypatch.setenv("ROKID_WORK_MODEL_POLICY", "follow-family")
    calls = []

    class NoInventory:
        def resolve_new_job_settings(self, **options):
            calls.append(options)
            raise AssertionError("listening cannot inspect or resolve a new model")

    question = Question(chat_key="session:1", booklet_stage="listening", audio_path=str(audio),
        document_pages=[{"page_number": 1, "image_path": str(original)}],
        booklet_questions=[{"question_id": "q1"}])
    with pytest.raises(WorkConflict):
        chatgpt_work.ChatGptWorkSolver(client=NoInventory()).answer_all(question=question)
    assert calls == [] and store.session_jobs(1) == []
    assert [(path.read_bytes(), path.stat().st_mtime_ns) for path in (original, audio)] == before


def test_new_manual_work_queue_keeps_explicit_settings_without_reading_inventory(tmp_path, monkeypatch):
    from app.solvers import chatgpt_work
    from app.solvers.base import Question
    from app.work_bridge import WorkPending, WorkStore

    store = WorkStore(tmp_path)
    original = tmp_path / "page.png"
    original.write_bytes(picture())
    monkeypatch.setattr(chatgpt_work, "configured_work_store", lambda: store)
    monkeypatch.setattr(chatgpt_work, "work_binding", lambda session_id: ("fixture-glasses", 7))
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "0")
    monkeypatch.setenv("ROKID_WORK_MODEL", "GPT-6.2 Sol")
    question = Question(chat_key="session:1", document_pages=[{"page_number": 1, "image_path": str(original)}])
    with pytest.raises(WorkPending):
        chatgpt_work.ChatGptWorkSolver(client=object()).answer_all(question=question)
    job = store.session_jobs(1)[0]
    assert job["requested_settings"]["model"] == "GPT-6.2 Sol" and job["model_selection_verified"] is False
    assert store.read_source(job["job_id"], "p1")[0] == original.read_bytes()


@pytest.mark.parametrize("late_final_ready", [False, True])
def test_new_job_retires_only_expired_owner_read_only_before_inventory_and_can_resume(client, monkeypatch, late_final_ready):
    from app import main
    from app.solvers import chatgpt_work
    from app.solvers.chatgpt_work_web import WorkWebClient
    from app.solvers.chatgpt_web import ChatGptWebBlocked
    from app.work_bridge import WorkPending, configured_work_store

    _, old_session, old = api_session(client, generation=7)
    wait_for(lambda: old_session not in main._background_solves)
    doc = client.post("/v1/documents", json={"title": "new model resolution"}).json()["document_id"]
    assert client.post(f"/v1/documents/{doc}/pages", data={"page_index": 0},
        files={"image": ("page.png", picture(), "image/png")}).status_code == 201
    assert client.post(f"/v1/documents/{doc}/finalize").status_code == 200
    session = client.post("/v1/exam-sessions", json={"document_id": doc, "mode": "study"}).json()["session_id"]
    assert client.post("/v1/glasses/state", json={"device_id": "fixture-glasses", "session_id": session,
        "generation": 8, "sequence": 1, "phase": "analyzing"}).json()["accepted"]
    question = question_for(doc, session)
    original = Path(question.document_pages[0]["image_path"])
    before = original.read_bytes(), original.stat().st_mtime_ns
    activity = []

    class OldOwner(WorkWebClient):
        retired = False
        ready = late_final_ready

        def pending_work_owner(self):
            return None if self.retired else {"chat_key": chatgpt_work._browser_chat_key(old), "stage": old["stage"]}

        def retire_expired_batch(self, *, chat_key, booklet_stage, expired_guard):
            assert chat_key == chatgpt_work._browser_chat_key(old) and booklet_stage == old["stage"]
            with expired_guard():
                activity.append("read-old-final")
            if not self.ready:
                return False
            with expired_guard():
                self.retired = True  # Only a matching late body retires its own journal in production.
            return True

        def resolve_new_job_settings(self, *, requested_settings, follow_family):
            if not self.retired:
                raise ChatGptWebBlocked("old uncertain send must be recovered before inventory")
            activity.append("resolve-new")
            return {**requested_settings, "model": "GPT-6.10 Sol"}

    def pending(*args):
        raise WorkPending("fixture pauses the NEW job before Send")
    monkeypatch.setattr(chatgpt_work.ChatGptWorkSolver, "_consume_browser", pending)
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    old_owner = OldOwner()
    solver = chatgpt_work.ChatGptWorkSolver(client=old_owner)
    monkeypatch.setattr(main, "get_solver", lambda *args: solver)
    assert client.post(f"/v1/exam-sessions/{session}/finalize-reading?solve=background").status_code == 200
    wait_for(lambda: session not in main._background_solves)
    store = configured_work_store()
    if not late_final_ready:
        assert store.session_jobs(session) == [] and activity == ["read-old-final"]
        old_owner.ready = True
        with main.db.connect() as conn:
            row = conn.execute("SELECT * FROM exam_sessions WHERE id=?", (session,)).fetchone()
            assert row["status"] == "reviewing" and main._resume_answers(conn, row)
        wait_for(lambda: session not in main._background_solves)
    assert store.session_jobs(session)[0]["requested_settings"]["model"] == "GPT-6.10 Sol"
    assert activity[-2:] == ["read-old-final", "resolve-new"]
    assert store.result(old["job_id"]) is None and store.get(old["job_id"])["requested_settings"] == old["requested_settings"]
    assert (original.read_bytes(), original.stat().st_mtime_ns) == before
