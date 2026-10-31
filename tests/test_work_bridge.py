"""Phone-local Work handoff. No browser, cloud service or device is contacted."""

import hashlib
import importlib
import io
import json
import random
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image


def picture(number=0):
    output = io.BytesIO()
    Image.new("RGB", (24, 32), (number % 255, 230, 240)).save(output, "PNG")
    return output.getvalue()


def sources(count=1):
    return [{"source_id": f"p{n + 1}", "page_number": n + 1,
             "mime_type": "image/png", "data": picture(n)} for n in range(count)]


def answer(label="問1", text="x=2", pages=None):
    return {"questions": [{"group": "第1問", "label": label, "pages": pages or [1],
                           "answer_no": [1], "status": "ready", "answer": text,
                           "missing_material": "", "diagrams": []}]}


def needs_input():
    result = answer(text="")
    result["questions"][0].update(status="needs_input", missing_material="P1の文字が判読できません")
    return result


def queue(store, count=1, **extra):
    return store.enqueue(session_id=1, conversation_key="session:1", stage="single",
                         sources=sources(count), system="write answers only", prompt="all questions",
                         **extra)


def quality_reply(request):
    return {"schema": 1, "capture": request["capture"],
            "inspected_image_ids": [item["image_id"] for item in request["images"]],
            "evidence": {"schema": 1, "source_sha256": request["capture"]["source_sha256"],
                         "rotation": 0, "inventory_complete": True, "profile_id": "fixture",
                         "layout": "single", "pages": [{"id": "paper", "paper_bounds": "pass",
                            "occlusion": "pass", "regions": [{"id": "text", "kind": "text",
                                "source_detail": "pass", "exposure": "pass", "readability": "pass"}]}]}}


def inspect(store, job, source_id):
    request = store.quality_request(job["job_id"], source_id)
    delivered = []
    for part in request["images"]:
        raw, meta = store.read_quality_image(job["job_id"], source_id, part["image_id"])
        assert hashlib.sha256(raw).hexdigest() == part["sha256"] == meta["sha256"]
        delivered.append(meta)
    return store.submit_quality(job["job_id"], source_id, response=quality_reply(request),
                                image_receipts=delivered)


def receipt(store, job, source_id, *, quality=True):
    original, metadata = store.read_source(job["job_id"], source_id)
    assert hashlib.sha256(original).hexdigest() == metadata["sha256"]
    if quality and metadata["mime_type"].startswith("image/"):
        assert inspect(store, job, source_id)["decision"] == "eligible"
    return {"source_id": source_id, "sha256": metadata["sha256"],
            "receipt": metadata["receipt"]}


def complete(store, job, receipts, result=None, **extra):
    return store.submit_result(job["job_id"], manifest_sha256=job["manifest_sha256"],
                               generation=job["generation"], conversation_id="work-chat-1",
                               source_receipts=receipts, result=result or answer(), **extra)


def browser_observations(job, *, statuses=None):
    statuses = statuses or ["readable"] * len(job["sources"])
    files, reviews = [], []
    for source, status in zip(job["sources"], statuses, strict=True):
        number = source["page_number"]
        files.append({"source_id": source["source_id"], "file_name": f"page_{number:03d}.png",
                      "sha256": source["sha256"], "width": 24, "height": 32})
        reviews.append({"source_id": source["source_id"], "status": status,
                        "image_viewer_used": True,
                        "reasons": [] if status == "readable" else ["small text is blurred"]})
    return {"status": "ok", "files": files}, reviews


def test_browser_original_review_can_return_answers_without_claiming_calibration(tmp_path):
    from app.work_bridge import WorkConflict, WorkStore

    store = WorkStore(tmp_path)
    job = queue(store, 2)
    acquired = [receipt(store, job, source["source_id"], quality=False) for source in job["sources"]]
    extraction, readability = browser_observations(job)
    saved = store.submit_browser_result(job["job_id"], manifest_sha256=job["manifest_sha256"],
        generation=job["generation"], conversation_id="browser-chat-1", source_receipts=acquired,
        result=answer(pages=[1, 2]), extraction=extraction, readability=readability)
    assert saved["status"] == "completed"
    review = saved["browser_review"]
    assert review["kind"] == "uncalibrated_browser_readability"
    assert review["calibrated"] is False and review["visual_reading_verified"] is False
    assert [item["source_sha256"] for item in review["images"]] == [source["sha256"] for source in job["sources"]]
    assert saved["quality"] == {} and saved["visual_reading_verified"] is False
    restarted = WorkStore(tmp_path)
    assert restarted.get(job["job_id"])["browser_review"] == review
    assert restarted.result(job["job_id"]) == answer(pages=[1, 2])
    # The external/MCP result route still requires its original calibrated evidence.
    with pytest.raises(WorkConflict, match="eligible"):
        restarted.submit_result(job["job_id"], manifest_sha256=job["manifest_sha256"],
            generation=job["generation"], conversation_id="browser-chat-1", source_receipts=acquired,
            result=answer(pages=[1, 2]))


@pytest.mark.parametrize("change", ["hash", "dimension", "float_dimension", "missing", "extra", "order",
    "review_missing", "review_order", "viewer_false", "status", "calibration_claim", "reason"])
def test_browser_evidence_is_bound_to_every_original_and_cannot_claim_calibrated_quality(tmp_path, change):
    from app.work_bridge import WorkBrowserResultRejected, WorkStore

    store = WorkStore(tmp_path)
    job = queue(store, 2)
    acquired = [receipt(store, job, source["source_id"], quality=False) for source in job["sources"]]
    extraction, review = browser_observations(job)
    if change == "hash":
        extraction["files"][0]["sha256"] = "0" * 64
    elif change == "dimension":
        extraction["files"][0]["width"] += 1
    elif change == "float_dimension":
        extraction["files"][0]["width"] = 24.0
    elif change == "missing":
        extraction["files"].pop()
    elif change == "extra":
        extraction["files"].append(extraction["files"][0])
    elif change == "order":
        extraction["files"].reverse()
    elif change == "review_missing":
        review.pop()
    elif change == "review_order":
        review.reverse()
    elif change == "viewer_false":
        review[0]["image_viewer_used"] = False
    elif change == "status":
        review[0]["status"] = "eligible"
    elif change == "calibration_claim":
        review[0]["profile_id"] = "fixture"
    else:
        review[0].update(status="uncertain", reasons=[])
    with pytest.raises(WorkBrowserResultRejected):
        store.submit_browser_result(job["job_id"], manifest_sha256=job["manifest_sha256"],
            generation=job["generation"], conversation_id="browser-chat", source_receipts=acquired,
            result=answer(), extraction=extraction, readability=review)
    assert store.result(job["job_id"]) is None


@pytest.mark.parametrize("status", ["unreadable", "uncertain"])
@pytest.mark.parametrize("kind", ["ready", "stop", "mixed", "hidden_answer"])
def test_browser_uncertain_pages_return_only_genuine_non_answering_stops(tmp_path, status, kind):
    from app.work_bridge import WorkBrowserResultRejected, WorkConflict, WorkReadabilityRejected, WorkStore

    store = WorkStore(tmp_path)
    job = queue(store, 2)
    acquired = [receipt(store, job, source["source_id"], quality=False) for source in job["sources"]]
    extraction, review = browser_observations(job, statuses=["readable", status])
    result = answer() if kind == "ready" else needs_input()
    if kind == "mixed":
        ready = answer(label="問2")["questions"][0]
        ready["answer_no"] = [2]
        result["questions"].append(ready)
    elif kind == "hidden_answer":
        result["questions"][0]["derivation"] = "hidden answer: x=2"
    def submit():
        return store.submit_browser_result(job["job_id"], manifest_sha256=job["manifest_sha256"],
            generation=job["generation"], conversation_id="browser-chat", source_receipts=acquired,
            result=result, extraction=extraction, readability=review)
    if kind == "stop":
        assert submit()["status"] == "completed"
        assert store.result(job["job_id"]) == needs_input()
        assert submit()["browser_review"]["images"][1]["status"] == status
    else:
        expected = WorkReadabilityRejected if kind in ("ready", "mixed") else WorkBrowserResultRejected
        with pytest.raises(expected) as error:
            submit()
        if kind in ("ready", "mixed"):
            assert str(error.value) == "browser readability review does not support answering"
            assert not isinstance(error.value, WorkConflict)
        assert store.result(job["job_id"]) is None


def test_120_originals_are_ordered_immutable_and_restart_reuses_the_job(tmp_path):
    from app.work_bridge import WorkStore

    store = WorkStore(tmp_path, validated_profiles=("fixture",))
    job = queue(store, 120)
    assert [item["page_number"] for item in job["sources"]] == list(range(1, 121))
    assert len(job["sources"]) == 120
    assert not any("data" in item or "path" in item for item in job["sources"])
    acquired = [receipt(store, job, item["source_id"]) for item in job["sources"]]
    restarted = WorkStore(tmp_path, validated_profiles=("fixture",))
    assert queue(restarted, 120)["job_id"] == job["job_id"]
    assert restarted.get(job["job_id"])["status"] == "pending"
    saved = complete(restarted, job, acquired, answer(pages=list(range(1, 121))))
    assert saved["status"] == "completed"
    assert saved["visual_reading_verified"] is False
    assert complete(restarted, job, acquired, answer(pages=list(range(1, 121)))) == saved
    assert restarted.result(job["job_id"]) == answer(pages=list(range(1, 121)))


def test_one_missing_original_cannot_be_called_a_completed_booklet(tmp_path):
    from app.work_bridge import WorkConflict, WorkStore

    store = WorkStore(tmp_path, validated_profiles=("fixture",))
    job = queue(store, 21)
    acquired = [receipt(store, job, item["source_id"]) for item in job["sources"][:-1]]
    with pytest.raises(WorkConflict, match="every original"):
        complete(store, job, acquired)
    assert store.get(job["job_id"])["status"] == "pending"


@pytest.mark.parametrize("change", ["hash", "generation", "receipt", "source_hash", "duplicate", "answer"])
@pytest.mark.parametrize("stop", [False, True])
def test_wrong_identity_or_invalid_answer_is_not_committed(tmp_path, change, stop):
    from app.work_bridge import WorkConflict, WorkStore

    store = WorkStore(tmp_path, validated_profiles=("fixture",))
    job = queue(store)
    acquired = [receipt(store, job, "p1", quality=not stop)]
    options = dict(manifest_sha256=job["manifest_sha256"], generation=job["generation"],
                   conversation_id="work-chat-1", source_receipts=acquired,
                   result=needs_input() if stop else answer())
    if change == "hash":
        options["manifest_sha256"] = "a" * 64
    elif change == "generation":
        options["generation"] += 1
    elif change == "receipt":
        acquired[0]["receipt"] = "not-a-source-receipt"
    elif change == "source_hash":
        acquired[0]["sha256"] = "a" * 64
    elif change == "duplicate":
        acquired.append(acquired[0])
    else:
        options["result"] = answer(text="")
    with pytest.raises((WorkConflict, ValueError)):
        store.submit_result(job["job_id"], **options)
    assert store.result(job["job_id"]) is None


def test_a_changed_original_does_not_create_a_second_pending_send(tmp_path):
    from app.work_bridge import WorkConflict, WorkStore

    store = WorkStore(tmp_path, validated_profiles=("fixture",))
    first = queue(store)
    changed = sources()
    changed[0]["data"] = picture(9)
    with pytest.raises(WorkConflict, match="identity"):
        store.enqueue(session_id=1, conversation_key="session:1", stage="single",
                      sources=changed, system="write answers only", prompt="all questions")
    assert store.list_jobs()["jobs"][0]["job_id"] == first["job_id"]


def test_result_cannot_be_changed_after_its_first_commit(tmp_path):
    from app.work_bridge import WorkConflict, WorkStore

    store = WorkStore(tmp_path, validated_profiles=("fixture",))
    job = queue(store)
    acquired = [receipt(store, job, "p1")]
    complete(store, job, acquired)
    with pytest.raises(WorkConflict, match="committed"):
        complete(store, job, acquired, answer(text="different answer"))


def test_uncalibrated_quality_is_persisted_as_hold_and_cannot_admit_answers(tmp_path):
    from app.work_bridge import WorkConflict, WorkStore

    store = WorkStore(tmp_path)
    job = queue(store)
    fetched = receipt(store, job, "p1", quality=False)
    assessed = inspect(store, job, "p1")
    assert assessed["decision"] == "hold"
    assert assessed["reasons"] == ["profile_not_validated_by_caller"]
    assert WorkStore(tmp_path).get(job["job_id"])["quality"]["p1"] == assessed
    with pytest.raises(WorkConflict, match="quality evidence"):
        complete(store, job, [fetched])


def test_quality_requires_all_native_image_receipts_and_correct_capture_identity(tmp_path):
    from app.work_bridge import WorkConflict, WorkStore

    store = WorkStore(tmp_path, validated_profiles=("fixture",))
    job = queue(store)
    fetched = receipt(store, job, "p1", quality=False)
    request = store.quality_request(job["job_id"], "p1")
    response = quality_reply(request)
    with pytest.raises(WorkConflict, match="every inspection"):
        store.submit_quality(job["job_id"], "p1", response=response, image_receipts=[])
    delivered = [store.read_quality_image(job["job_id"], "p1", part["image_id"])[1]
                 for part in request["images"]]
    response["capture"]["generation"] += 1
    stale = store.submit_quality(job["job_id"], "p1", response=response, image_receipts=delivered)
    assert stale["decision"] == "hold" and stale["reasons"] == ["capture_identity_mismatch"]
    assert WorkStore(tmp_path).get(job["job_id"])["quality"]["p1"] == stale
    with pytest.raises(WorkConflict, match="quality evidence"):
        complete(store, job, [fetched])


def test_known_bad_quality_cannot_be_turned_into_a_completed_answer(tmp_path):
    from app.work_bridge import WorkConflict, WorkStore

    store = WorkStore(tmp_path, validated_profiles=("fixture",))
    job = queue(store)
    fetched = receipt(store, job, "p1", quality=False)
    request = store.quality_request(job["job_id"], "p1")
    delivered = [store.read_quality_image(job["job_id"], "p1", part["image_id"])[1]
                 for part in request["images"]]
    response = quality_reply(request)
    response["evidence"]["pages"][0]["regions"][0]["readability"] = "fail"
    assessed = store.submit_quality(job["job_id"], "p1", response=response, image_receipts=delivered)
    assert assessed["decision"] == "retake"
    with pytest.raises(WorkConflict, match="quality evidence"):
        complete(store, job, [fetched])


@pytest.mark.parametrize("decision", ["retake", "hold"])
def test_non_answering_needs_input_survives_quality_failure_and_restart(tmp_path, decision):
    from app.work_bridge import WorkStore

    profiles = ("fixture",) if decision == "retake" else ()
    store = WorkStore(tmp_path, validated_profiles=profiles)
    job = queue(store)
    fetched = receipt(store, job, "p1", quality=False)
    request = store.quality_request(job["job_id"], "p1")
    delivered = [store.read_quality_image(job["job_id"], "p1", part["image_id"])[1]
                 for part in request["images"]]
    response = quality_reply(request)
    if decision == "retake":
        response["evidence"]["pages"][0]["regions"][0]["readability"] = "fail"
    assessed = store.submit_quality(job["job_id"], "p1", response=response, image_receipts=delivered)
    assert assessed["decision"] == decision

    result = needs_input()
    saved = complete(store, job, [fetched], result)
    assert saved["status"] == "completed"
    restarted = WorkStore(tmp_path, validated_profiles=profiles)
    assert restarted.result(job["job_id"]) == result
    assert restarted.get(job["job_id"])["quality"]["p1"] == assessed
    assert complete(restarted, job, [fetched], result) == saved


@pytest.mark.parametrize("field,value,level", [
    ("answer", "推測値 x=2", "question"),
    ("diagrams", [{"alt": "推測図", "aspect_ratio": 1,
                   "elements": [{"type": "text", "x": 0.5, "y": 0.5, "text": "x=2"}]}], "question"),
    ("answer_blocks", [{"text": "x=2"}], "question"),
    ("derivation", "x+1=3 より x=2", "question"),
    ("solution_steps", ["x=2"], "question"),
    ("missing_material", "", "question"),
    ("missing_material", {"answer": "x=2"}, "question"),
    ("blocks", [{"text": "x=2"}], "result"),
    ("derivation", "x=2", "result"),
])
def test_needs_input_cannot_hide_answers_from_the_quality_guard(tmp_path, field, value, level):
    from app.work_bridge import WorkConflict, WorkStore

    store = WorkStore(tmp_path)
    job = queue(store)
    fetched = receipt(store, job, "p1", quality=False)
    result = needs_input()
    target = result["questions"][0] if level == "question" else result
    target[field] = value
    with pytest.raises(WorkConflict, match="quality evidence"):
        complete(store, job, [fetched], result)
    assert store.result(job["job_id"]) is None


def test_ready_answer_beside_needs_input_still_requires_every_original_quality(tmp_path):
    from app.work_bridge import WorkConflict, WorkStore

    store = WorkStore(tmp_path, validated_profiles=("fixture",))
    job = queue(store, 2)
    fetched = [receipt(store, job, "p1"), receipt(store, job, "p2", quality=False)]
    result = answer(pages=[1])
    result["questions"].append(dict(needs_input()["questions"][0], label="問2", pages=[2], answer_no=[2]))
    with pytest.raises(WorkConflict, match="quality evidence"):
        complete(store, job, fetched, result)
    assert store.result(job["job_id"]) is None


@pytest.mark.parametrize("change", ["empty", "status", "page", "label"])
def test_non_answering_stop_still_validates_the_result_envelope(tmp_path, change):
    from app.work_bridge import WorkStore

    store = WorkStore(tmp_path)
    job = queue(store)
    fetched = receipt(store, job, "p1", quality=False)
    result = needs_input()
    if change == "empty":
        result["questions"] = []
    elif change == "status":
        result["questions"][0]["status"] = "pending_audio"
    elif change == "page":
        result["questions"][0]["pages"] = [2]
    else:
        result["questions"][0]["label"] = False
    with pytest.raises(ValueError):
        complete(store, job, [fetched], result)
    assert store.result(job["job_id"]) is None


def test_unreadable_reading_stop_can_keep_listening_unanswered(tmp_path):
    from app.work_bridge import WorkStore

    store = WorkStore(tmp_path)
    job = store.enqueue(session_id=1, conversation_key="session:1", stage="reading",
                        sources=sources(), system="answer", prompt="reading")
    fetched = receipt(store, job, "p1", quality=False)
    result = needs_input()
    result["questions"][0]["requires_audio"] = False
    result["questions"].append({"group": "Listening", "label": "問2", "pages": [1], "answer_no": [2],
                                "requires_audio": True, "status": "pending_audio", "answer": "", "diagrams": []})
    complete(store, job, [fetched], result)
    assert store.result(job["job_id"]) == result


def tile_receipt(store, job, source_id):
    request = store.quality_request(job["job_id"], source_id)
    delivered = [store.read_quality_image(job["job_id"], source_id, part["image_id"])[1]
                 for part in request["images"]]
    assessed = store.submit_quality(job["job_id"], source_id, response=quality_reply(request),
                                    image_receipts=delivered)
    assert assessed["decision"] == "eligible"
    return {"source_id": source_id, "sha256": request["capture"]["source_sha256"],
            "delivery": "native_tiles", "inspection_manifest_sha256": request["inspection_manifest_sha256"],
            "image_receipts": delivered}


def test_large_original_can_be_acknowledged_by_all_native_tiles_without_fetching_its_encoded_bytes(tmp_path):
    from app.work_bridge import WorkStore

    output = io.BytesIO()
    with Image.frombytes("RGB", (1800, 1800), random.Random(73).randbytes(1800 * 1800 * 3)) as image:
        image.save(output, "PNG")
    original = output.getvalue()
    assert len(original) > 8 * 1024 * 1024
    store = WorkStore(tmp_path, validated_profiles=("fixture",))
    job = store.enqueue(session_id=1, conversation_key="session:1", stage="single", system="answer", prompt="all",
                        sources=[{"source_id": "p1", "page_number": 1, "mime_type": "image/png", "data": original}])
    claim = tile_receipt(store, job, "p1")
    with store._connect() as conn:
        assert conn.execute("SELECT receipt FROM sources").fetchone()[0] is None
    saved = complete(store, job, [claim])
    assert saved["delivery_acknowledgements"]["kind"] == "transport_acknowledgement_claim"
    assert saved["delivery_acknowledgements"]["sources"][0]["delivery"] == "native_tiles"
    assert saved["visual_reading_verified"] is False
    restarted = WorkStore(tmp_path, validated_profiles=("fixture",))
    assert complete(restarted, job, [claim]) == saved
    assert restarted.read_source(job["job_id"], "p1")[0] == original


@pytest.mark.parametrize("change", ["missing", "tile_hash", "manifest", "source_hash", "delivery"])
def test_native_tile_receipts_require_the_bound_packet_and_every_delivered_image(tmp_path, change):
    from app.work_bridge import WorkConflict, WorkStore

    store = WorkStore(tmp_path, validated_profiles=("fixture",))
    job = queue(store)
    claim = tile_receipt(store, job, "p1")
    if change == "missing":
        claim["image_receipts"].pop()
    elif change == "tile_hash":
        claim["image_receipts"][0]["sha256"] = "0" * 64
    elif change == "manifest":
        claim["inspection_manifest_sha256"] = "0" * 64
    elif change == "source_hash":
        claim["sha256"] = "0" * 64
    else:
        claim["delivery"] = "local_fetch_only"
    with pytest.raises(WorkConflict):
        complete(store, job, [claim])
    assert store.result(job["job_id"]) is None


@pytest.mark.parametrize("model", ["gpt-6.1-sol", "GPT-6.10 Sol"])
def test_mixed_audio_keeps_the_reading_conversation_and_original_images(tmp_path, model):
    from app.work_bridge import WorkConflict, WorkStore

    store = WorkStore(tmp_path, validated_profiles=("fixture",))
    reading_result = answer()
    reading_result["questions"][0]["requires_audio"] = False
    reading_result["questions"].append({"group": "Listening", "label": "問2", "pages": [1],
                                        "answer_no": [2], "requires_audio": True,
                                        "status": "pending_audio", "answer": "", "diagrams": []})
    first = store.enqueue(session_id=1, conversation_key="session:1", stage="reading",
                          sources=sources(), system="answer", prompt="reading",
                          requested_settings={"model": model, "effort": "xhigh", "speed": "fast"})
    acquired = [receipt(store, first, "p1")]
    complete(store, first, acquired, reading_result)
    audio = {"source_id": "audio", "mime_type": "audio/wav", "data": b"original recording"}
    with pytest.raises(WorkConflict, match="settings"):
        store.enqueue(session_id=1, conversation_key="session:1", stage="listening",
                      sources=[*sources(), audio], system="answer", prompt="listening", question_ids=["q2"],
                      requested_settings={"model": "GPT-6.99 Sol", "effort": "xhigh", "speed": "fast"})
    second = store.enqueue(session_id=1, conversation_key="session:1", stage="listening",
                           sources=[*sources(), audio], system="answer", prompt="listening",
                           question_ids=["q2"])
    assert second["previous_job_id"] == first["job_id"]
    assert second["requested_settings"] == first["requested_settings"]
    assert second["conversation_id"] == "work-chat-1"
    assert second["new_source_ids"] == ["audio"]
    listening_result = answer(label="問2", text="B")
    listening_result["questions"][0]["question_id"] = "q2"
    audio_receipt = receipt(store, second, "audio")
    with pytest.raises(WorkConflict, match="conversation"):
        store.submit_result(second["job_id"], manifest_sha256=second["manifest_sha256"],
                            generation=second["generation"], conversation_id="different-chat",
                            source_receipts=[audio_receipt], result=listening_result)
    complete(store, second, [audio_receipt], listening_result)
    assert store.result(first["job_id"]) == reading_result


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ROKID_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ROKID_API_KEY", "local-test-key")
    monkeypatch.setenv("ROKID_SOLVER", "chatgpt-work")
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "0")
    # Synthetic profile for the local API fixture; no production profile is approved.
    monkeypatch.setenv("ROKID_CAPTURE_VALIDATED_PROFILES", "fixture")
    monkeypatch.delenv("ROKID_REAL_MODE", raising=False)
    import app.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)
    import app.main as main
    importlib.reload(main)
    main.ensure_dirs()
    main.db.init_db()
    return TestClient(main.app, headers={"Authorization": "Bearer local-test-key"})


def wait_for(predicate):
    until = time.monotonic() + 5
    while time.monotonic() < until:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("phone-local background processing did not finish")


def api_session(client, *, exam_type="written", generation=None):
    doc = client.post("/v1/documents", json={"title": "local Work test"}).json()["document_id"]
    assert client.post(f"/v1/documents/{doc}/pages", data={"page_index": 0},
                       files={"image": ("page.png", picture(), "image/png")}).status_code == 201
    assert client.post(f"/v1/documents/{doc}/finalize").status_code == 200
    response = client.post("/v1/exam-sessions", json={"document_id": doc, "mode": "study", "exam_type": exam_type})
    assert response.status_code == 201, response.text
    session = response.json()["session_id"]
    if generation is not None:
        assert client.post("/v1/glasses/state", json={"device_id": "fixture-glasses", "session_id": session,
                           "generation": generation, "sequence": 1, "phase": "analyzing"}).json()["accepted"]
    assert client.post(f"/v1/exam-sessions/{session}/finalize-reading?solve=background").status_code == 200
    job = wait_for(lambda: (client.get("/v1/work/jobs").json().get("jobs") or [None])[0])
    return doc, session, job


def api_tile_receipt(client, job, source_id="p1", *, submit_quality=True):
    route = f"/v1/work/jobs/{job['job_id']}/sources/{source_id}"
    response = client.get(f"{route}/quality")
    assert response.status_code == 200, response.text
    request = response.json()
    inspected = []
    for image in request["images"]:
        pixels = client.get(f"{route}/quality/images/{image['image_id']}")
        assert pixels.status_code == 200
        inspected.append({"image_id": image["image_id"], "sha256": hashlib.sha256(pixels.content).hexdigest(),
                          "receipt": pixels.headers["x-work-source-receipt"]})
    if submit_quality:
        quality = client.post(f"{route}/quality", json={"response": quality_reply(request), "image_receipts": inspected})
        assert quality.status_code == 200 and quality.json()["decision"] == "eligible", quality.text
    return {"source_id": source_id, "sha256": request["capture"]["source_sha256"],
            "delivery": "native_tiles", "inspection_manifest_sha256": request["inspection_manifest_sha256"],
            "image_receipts": inspected}


def api_complete(client, job, acquired, result):
    return client.post(f"/v1/work/jobs/{job['job_id']}/result", json={
        "manifest_sha256": job["manifest_sha256"], "generation": job["generation"],
        "conversation_id": "cloud-work-chat", "source_receipts": acquired, "result": result})


def test_external_post_cannot_select_uncalibrated_browser_admission(client):
    _, _, job = api_session(client)
    response = client.get(f"/v1/work/jobs/{job['job_id']}/sources/p1")
    acquired = {"source_id": "p1", "sha256": hashlib.sha256(response.content).hexdigest(),
                "receipt": response.headers["x-work-source-receipt"]}
    extraction, readability = browser_observations(job)
    reply = client.post(f"/v1/work/jobs/{job['job_id']}/result", json={
        "manifest_sha256": job["manifest_sha256"], "generation": job["generation"],
        "conversation_id": "browser-chat", "source_receipts": [acquired], "result": answer(),
        "extraction": extraction, "readability": readability,
        "browser_review": {"kind": "uncalibrated_browser_readability", "images": readability}})
    assert reply.status_code in (409, 422), reply.text
    from app.work_bridge import configured_work_store
    assert configured_work_store().result(job["job_id"]) is None


def test_phone_api_returns_non_answering_stop_in_existing_answer_bundle(client):
    _, session, job = api_session(client)
    delivered = [api_tile_receipt(client, job, submit_quality=False)]
    response = api_complete(client, job, delivered, needs_input())
    assert response.status_code == 200, response.text
    bundle = wait_for(lambda: data if (data := client.get(
        f"/v1/exam-sessions/{session}/answer-bundle").json()).get("items") else None)
    assert [(item["status"], item["answer"], item.get("diagrams", [])) for item in bundle["items"]] == [
        ("needs_input", "", [])]
    assert bundle["items"][0]["issue"] == "P1の文字が判読できません"


def test_phone_api_auto_queues_images_and_returns_work_answers_in_the_existing_bundle(client):
    doc = client.post("/v1/documents", json={"title": "local Work test"}).json()["document_id"]
    for index in range(21):
        uploaded = client.post(f"/v1/documents/{doc}/pages", data={"page_index": index},
                               files={"image": ("page.png", picture(index), "image/png")})
        assert uploaded.status_code == 201
    finalized = client.post(f"/v1/documents/{doc}/finalize")
    assert finalized.status_code == 200, finalized.text
    created = client.post("/v1/exam-sessions", json={"document_id": doc, "mode": "study",
                                                    "exam_type": "written"})
    assert created.status_code == 201, created.text
    session = created.json()["session_id"]
    done = client.post(f"/v1/exam-sessions/{session}/finalize-reading?solve=background")
    assert done.status_code == 200
    job = wait_for(lambda: (client.get("/v1/work/jobs").json().get("jobs") or [None])[0])
    assert len(job["sources"]) == 21
    assert job["requested_settings"] == {"model": "gpt-6.1-sol", "effort": "xhigh", "speed": "fast"}
    assert job["model_selection_verified"] is False
    acquired = []
    for item in job["sources"]:
        raw = client.get(f"/v1/work/jobs/{job['job_id']}/sources/{item['source_id']}")
        assert raw.status_code == 200 and raw.headers["content-type"] == "image/png"
        acquired.append({"source_id": item["source_id"],
                         "sha256": hashlib.sha256(raw.content).hexdigest(),
                         "receipt": raw.headers["x-work-source-receipt"]})
        request = client.get(f"/v1/work/jobs/{job['job_id']}/sources/{item['source_id']}/quality").json()
        inspected = []
        for part in request["images"]:
            pixels = client.get(f"/v1/work/jobs/{job['job_id']}/sources/{item['source_id']}/quality/images/{part['image_id']}")
            assert pixels.status_code == 200
            inspected.append({"image_id": part["image_id"], "sha256": hashlib.sha256(pixels.content).hexdigest(),
                              "receipt": pixels.headers["x-work-source-receipt"]})
        quality = client.post(f"/v1/work/jobs/{job['job_id']}/sources/{item['source_id']}/quality",
                              json={"response": quality_reply(request), "image_receipts": inspected})
        assert quality.status_code == 200 and quality.json()["decision"] == "eligible"
        if item["page_number"] == 1:
            acquired[-1] = {"source_id": item["source_id"], "sha256": item["sha256"], "delivery": "native_tiles",
                            "inspection_manifest_sha256": request["inspection_manifest_sha256"],
                            "image_receipts": inspected}
    returned = client.post(f"/v1/work/jobs/{job['job_id']}/result", json={
        "manifest_sha256": job["manifest_sha256"], "generation": job["generation"],
        "conversation_id": "cloud-work-chat", "source_receipts": acquired, "result": answer()})
    assert returned.status_code == 200, returned.text
    bundle = wait_for(lambda: (data if data.get("items") else None)
                      if (response := client.get(f"/v1/exam-sessions/{session}/answer-bundle")).status_code == 200
                      and (data := response.json()) else None)
    assert [(item["question_label"], item["answer"]) for item in bundle["items"]] == [("問1", "x=2")]
    from app import db
    with db.connect() as conn:
        assert conn.execute("SELECT solver_name FROM solutions").fetchone()[0] == "chatgpt-work"


def test_phone_api_mixed_work_roundtrip_keeps_original_audio_and_committed_reading_answers(client, monkeypatch):
    from app import listening, main

    monkeypatch.setattr(listening, "transcribe_chunk", lambda *args, **kwargs: pytest.fail("unneeded ASR"))
    doc, session, first = api_session(client, exam_type="mixed")
    reading = answer(text="4")
    reading["questions"][0]["requires_audio"] = False
    reading["questions"].append({"group": "Listening", "label": "問2", "pages": [1], "answer_no": [2],
                                 "requires_audio": True, "status": "pending_audio", "answer": "", "diagrams": []})
    delivered = [api_tile_receipt(client, first)]
    assert api_complete(client, first, delivered, reading).status_code == 200
    before = wait_for(lambda: data if (data := client.get(
        f"/v1/exam-sessions/{session}/answer-bundle").json()).get("available_stage") == "reading" else None)
    assert [item["answer"] for item in before["items"]] == ["4", ""]
    audio = io.BytesIO()
    with wave.open(audio, "wb") as target:
        target.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        target.writeframes(b"\x01\x00" * 64)
    original_audio = audio.getvalue()
    uploaded = client.post(f"/v1/documents/{doc}/audio-chunks",
                           data={"sequence": 0, "start_sample": 0, "captured_at_ms": 10000},
                           files={"audio": ("chunk.wav", original_audio, "audio/wav")})
    assert uploaded.status_code == 200 and uploaded.json()["asr_seconds"] == 0
    assert client.post(f"/v1/documents/{doc}/audio-complete",
                       json={"expected_chunks": 1, "total_samples": 64}).status_code == 200
    assert client.post(f"/v1/exam-sessions/{session}/document-audio").status_code == 200
    second = wait_for(lambda: (client.get("/v1/work/jobs").json().get("jobs") or [None])[0])
    assert second["stage"] == "listening" and second["previous_job_id"] == first["job_id"]
    assert second["conversation_id"] == "cloud-work-chat" and second["new_source_ids"] == ["audio"]
    raw = client.get(f"/v1/work/jobs/{second['job_id']}/sources/audio")
    assert raw.content == original_audio
    audio_receipt = {"source_id": "audio", "sha256": hashlib.sha256(raw.content).hexdigest(),
                     "delivery": "original_bytes", "receipt": raw.headers["x-work-source-receipt"]}
    result = answer(label="問2", text="3")
    result["questions"][0].update(question_id=before["items"][1]["question_id"], answer_no=[2])
    assert api_complete(client, second, [audio_receipt], result).status_code == 200
    after = wait_for(lambda: data if (data := client.get(
        f"/v1/exam-sessions/{session}/answer-bundle").json()).get("available_stage") == "complete" else None)
    assert [item["answer"] for item in after["items"]] == ["4", "3"]
    assert [(item["question_id"], item["answer_no"]) for item in after["items"]] == [
        (item["question_id"], item["answer_no"]) for item in before["items"]]
    assert client.post(f"/v1/exam-sessions/{session}/document-audio").status_code == 200
    main._resume_all_answers()
    wait_for(lambda: session not in main._background_solves)
    assert client.get("/v1/work/jobs").json()["jobs"] == []
    with main.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM solutions").fetchone()[0] == 2


@pytest.mark.parametrize("change", ["generation", "closed"])
@pytest.mark.parametrize("stop", [False, True])
def test_phone_api_rejects_stale_work_results_and_image_reads(client, change, stop):
    _, session, job = api_session(client, generation=7)
    delivered = [api_tile_receipt(client, job, submit_quality=not stop)]
    update = {"device_id": "fixture-glasses", "session_id": session, "generation": 7, "sequence": 2,
              "phase": "closed" if change == "closed" else "analyzing"}
    if change == "generation":
        update["generation"] = 8
    assert client.post("/v1/glasses/state", json=update).json()["accepted"]
    assert client.get(f"/v1/work/jobs/{job['job_id']}/sources/p1").status_code == 409
    assert api_complete(client, job, delivered, needs_input() if stop else answer()).status_code == 409
    from app.work_bridge import configured_work_store
    assert configured_work_store().result(job["job_id"]) is None


@pytest.mark.parametrize("route", ["original", "quality", "native"])
def test_non_ascii_receipts_are_http_conflicts_instead_of_server_errors(client, route):
    _, _, job = api_session(client)
    delivered = api_tile_receipt(client, job)
    if route == "original":
        raw = client.get(f"/v1/work/jobs/{job['job_id']}/sources/p1")
        claim = {"source_id": "p1", "sha256": hashlib.sha256(raw.content).hexdigest(), "receipt": "受領"}
        response = api_complete(client, job, [claim], answer())
    else:
        delivered["image_receipts"][0]["receipt"] = "受領"
        if route == "quality":
            path = f"/v1/work/jobs/{job['job_id']}/sources/p1/quality"
            request = client.get(path).json()
            response = client.post(path, json={"response": quality_reply(request),
                                               "image_receipts": delivered["image_receipts"]})
        else:
            response = api_complete(client, job, [delivered], answer())
    assert response.status_code == 409, response.text
    from app.work_bridge import configured_work_store
    assert configured_work_store().result(job["job_id"]) is None


@pytest.mark.parametrize("kind", ["answer", "quality"])
def test_work_commit_serializes_against_a_concurrent_glasses_generation_update(client, monkeypatch, kind):
    from app import glasses_state, main
    from app.work_bridge import WorkStore, configured_work_store

    _, session, job = api_session(client, generation=7)
    acquired = api_tile_receipt(client, job, submit_quality=kind == "answer")
    entered, release, updated = threading.Event(), threading.Event(), threading.Event()
    operation = "submit_result" if kind == "answer" else "submit_quality"
    original = getattr(WorkStore, operation)

    def paused(store, *args, **kwargs):
        entered.set()
        assert release.wait(3)
        assert glasses_state.read_state("fixture-glasses")["generation"] == 7
        return original(store, *args, **kwargs)

    def update():
        try:
            return glasses_state.record_state(glasses_state.GlassesState(device_id="fixture-glasses",
                session_id=session, generation=8, sequence=1, phase="analyzing"), "127.0.0.1")
        finally:
            updated.set()

    def post():
        if kind == "answer":
            return api_complete(client, job, [acquired], answer())
        path = f"/v1/work/jobs/{job['job_id']}/sources/p1/quality"
        request = client.get(path).json()
        return client.post(path, json={"response": quality_reply(request), "image_receipts": acquired["image_receipts"]})

    monkeypatch.setattr(WorkStore, operation, paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        posted = pool.submit(post)
        assert entered.wait(3)
        notification = pool.submit(update)
        try:
            assert not updated.wait(0.1), "generation must not change between validation and commit"
        finally:
            release.set()
        assert posted.result(timeout=4).status_code == 200
        assert notification.result(timeout=4)
    wait_for(lambda: session not in main._background_solves)
    assert glasses_state.read_state("fixture-glasses")["generation"] == 8
    stored = configured_work_store().get(job["job_id"])
    assert stored["status"] == ("completed" if kind == "answer" else "pending")
    with main.db.connect() as conn:
        rows = conn.execute("SELECT structure_json FROM questions WHERE session_id=?", (session,)).fetchall()
        assert not any("solve_failure" in json.loads(row[0]) for row in rows)


@pytest.mark.parametrize("kind", ["answer", "quality"])
def test_glasses_generation_update_before_work_lock_prevents_any_stale_commit(client, kind):
    from app import glasses_state
    from app.work_bridge import configured_work_store

    _, session, job = api_session(client, generation=7)
    acquired = api_tile_receipt(client, job, submit_quality=kind == "answer")

    def post():
        if kind == "answer":
            return api_complete(client, job, [acquired], answer())
        request = configured_work_store().quality_request(job["job_id"], "p1")
        return client.post(f"/v1/work/jobs/{job['job_id']}/sources/p1/quality", json={
            "response": quality_reply(request), "image_receipts": acquired["image_receipts"]})

    with ThreadPoolExecutor(max_workers=1) as pool:
        with glasses_state.state_guard():
            future = pool.submit(post)
            assert glasses_state.record_state(glasses_state.GlassesState(device_id="fixture-glasses",
                session_id=session, generation=8, sequence=1, phase="analyzing"), "127.0.0.1")
        assert future.result(timeout=4).status_code == 409
    stored = configured_work_store().get(job["job_id"])
    assert stored["status"] == "pending"
    assert ("p1" in stored["quality"]) is (kind == "answer")


@pytest.mark.parametrize("change", ["generation", "closed", "chooser"])
def test_a_worker_resumed_after_the_glasses_changed_does_not_write_a_failed_answer(client, monkeypatch, change):
    from app import glasses_state, main

    doc, session, job = api_session(client, generation=7)
    acquired = api_tile_receipt(client, job)
    wait_for(lambda: session not in main._background_solves)
    with monkeypatch.context() as paused:
        paused.setattr(main, "_resume_answers", lambda *args: False)
        assert api_complete(client, job, [acquired], answer()).status_code == 200
    assert glasses_state.record_state(glasses_state.GlassesState(device_id="fixture-glasses",
        session_id=None if change == "chooser" else session, generation=7 if change == "closed" else 8, sequence=2,
        phase="chooser" if change == "chooser" else "closed" if change == "closed" else "analyzing"), "127.0.0.1")
    main._solve_deck_in_background(session, doc)
    with main.db.connect() as conn:
        rows = conn.execute("SELECT structure_json FROM questions WHERE session_id=?", (session,)).fetchall()
        assert not any("solve_failure" in json.loads(row[0]) for row in rows)
        assert conn.execute("SELECT count(*) FROM solutions").fetchone()[0] == 0


@pytest.mark.parametrize("change", ["generation", "closed"])
def test_generation_can_change_during_reply_read_but_cannot_commit_the_stale_deck(client, monkeypatch, change):
    from app import glasses_state, main

    _, session, job = api_session(client, generation=7)
    acquired = api_tile_receipt(client, job)
    wait_for(lambda: session not in main._background_solves)
    ready, release = threading.Event(), threading.Event()
    original = main._answer_all

    def paused(question):
        replies = original(question)
        ready.set()
        assert release.wait(3)
        return replies

    monkeypatch.setattr(main, "_answer_all", paused)
    try:
        assert api_complete(client, job, [acquired], answer()).status_code == 200
        assert ready.wait(3)
        assert glasses_state.record_state(glasses_state.GlassesState(device_id="fixture-glasses", session_id=session,
            generation=8 if change == "generation" else 7, sequence=2,
            phase="analyzing" if change == "generation" else "closed"), "127.0.0.1")
    finally:
        release.set()
    wait_for(lambda: session not in main._background_solves)
    with main.db.connect() as conn:
        rows = conn.execute("SELECT structure_json FROM questions WHERE session_id=?", (session,)).fetchall()
        assert not any("solve_failure" in json.loads(row[0]) for row in rows)
        assert conn.execute("SELECT count(*) FROM solutions").fetchone()[0] == 0


@pytest.mark.parametrize("stage", ["single", "reading", "listening"])
@pytest.mark.parametrize("change", ["active", "generation", "closed", "input"])
def test_work_preparation_failure_is_visible_only_for_its_current_input(client, monkeypatch, stage, change):
    from app import glasses_state, main

    doc, session, job = api_session(client, exam_type="written" if stage == "single" else "mixed", generation=7)
    wait_for(lambda: session not in main._background_solves)
    if stage == "listening":
        reading = answer(text="4")
        reading["questions"][0]["requires_audio"] = False
        reading["questions"].append({"group": "Listening", "label": "問2", "pages": [1], "answer_no": [2],
                                     "requires_audio": True, "status": "pending_audio", "answer": "", "diagrams": []})
        assert api_complete(client, job, [api_tile_receipt(client, job)], reading).status_code == 200
        wait_for(lambda: session not in main._background_solves)
        audio = io.BytesIO()
        with wave.open(audio, "wb") as target:
            target.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            target.writeframes(b"\x01\x00" * 64)
        assert client.post(f"/v1/documents/{doc}/audio-chunks",
                           data={"sequence": 0, "start_sample": 0, "captured_at_ms": 10000},
                           files={"audio": ("chunk.wav", audio.getvalue(), "audio/wav")}).status_code == 200
        assert client.post(f"/v1/documents/{doc}/audio-complete",
                           json={"expected_chunks": 1, "total_samples": 64}).status_code == 200
        assert client.post(f"/v1/exam-sessions/{session}/document-audio").status_code == 200
        wait_for(lambda: session not in main._background_solves)
    calls = []

    def unavailable(question):
        calls.append(question.booklet_stage)
        if change in ("generation", "closed"):
            assert glasses_state.record_state(glasses_state.GlassesState(device_id="fixture-glasses",
                session_id=session, generation=8 if change == "generation" else 7, sequence=2,
                phase="analyzing" if change == "generation" else "closed"), "127.0.0.1")
        elif change == "input":
            Path(question.document_pages[0]["image_path"]).write_bytes(picture(99))
        raise ValueError("an original Work page image is unavailable")

    monkeypatch.setattr(main, "_answer_all", unavailable)
    main._solve_deck_in_background(session, doc)
    assert calls == [stage]
    with main.db.connect() as conn:
        rows = conn.execute("SELECT structure_json FROM questions WHERE session_id=?", (session,)).fetchall()
        failures = [json.loads(row[0]).get("solve_failure") for row in rows]
        assert sum(bool(failure) for failure in failures) == (1 if change == "active" else 0)
        assert [row[0] for row in conn.execute("SELECT answer FROM solutions")] == ([] if stage != "listening" else ["4"])
    if change == "active":
        bundle = client.get(f"/v1/exam-sessions/{session}/answer-bundle")
        assert bundle.status_code == 200
        assert any(item["status"] == "failed" and "失敗" in item["issue"] for item in bundle.json()["items"])


def test_unready_work_provider_never_holds_the_notification_guard_or_uses_browser_backoff(client, monkeypatch):
    from app import glasses_state, main

    doc, session, _ = api_session(client, generation=7)
    wait_for(lambda: session not in main._background_solves)
    entered, release, updated = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(3)
        raise RuntimeError("local Work transport is unready")

    def update():
        try:
            return glasses_state.record_state(glasses_state.GlassesState(device_id="fixture-glasses",
                session_id=session, generation=8, sequence=1, phase="analyzing"), "127.0.0.1")
        finally:
            updated.set()

    monkeypatch.setattr(main, "get_solver", unavailable)
    monkeypatch.setattr(main, "_nothing_sent", lambda error: pytest.fail("Work must not enter browser retry/backoff"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        worker = pool.submit(main._solve_deck_in_background, session, doc)
        assert entered.wait(3)
        notification = pool.submit(update)
        try:
            assert updated.wait(1), "notifications must proceed during provider preparation"
        finally:
            release.set()
        assert notification.result(timeout=3)
        worker.result(timeout=3)
    assert calls == [1]


@pytest.mark.parametrize(("solver", "expected"), [("chatgpt-web", False), ("chatgpt-work", False), ("local", True)])
def test_work_original_audio_does_not_require_a_local_transcript(monkeypatch, solver, expected):
    from app.listening import requires_transcript

    monkeypatch.setenv("ROKID_SOLVER", solver)
    monkeypatch.delenv("ROKID_SOLVER_TIERS", raising=False)
    assert requires_transcript() is expected


@pytest.mark.parametrize("reason", ["pending", "stale", "readability", "browser_result"])
def test_pending_or_stale_work_job_never_falls_through_to_another_solver(monkeypatch, reason):
    from app.solvers import Question, Solver
    from app.solvers import registry
    from app.work_bridge import WorkBrowserResultRejected, WorkConflict, WorkPending, WorkReadabilityRejected

    error = {"pending": WorkPending, "stale": WorkConflict, "readability": WorkReadabilityRejected,
             "browser_result": WorkBrowserResultRejected}[reason]

    class Pending(Solver):
        name = "chatgpt-work"

        def solve(self, **kwargs):
            raise error("queued-originals")

    def selected(name):
        assert name == "chatgpt-work", "pending job must not spend another tier"
        return Pending()

    monkeypatch.setattr(registry, "get_solver", selected)
    with pytest.raises(error, match="queued-originals"):
        registry.solve_with_fallback(Question(body_text="original booklet", answer_only=True),
                                     tiers=["chatgpt-work", "openai"])


def test_work_api_refuses_missing_auth_even_when_the_general_api_is_open(client, monkeypatch):
    import app.config as config
    monkeypatch.setattr(config, "API_KEY", "")
    response = client.get("/v1/work/jobs")
    assert response.status_code == 503
    assert response.json()["code"] == "authentication_failed"


def test_work_api_unauthenticated_requests_cannot_list_photos(client):
    response = TestClient(client.app).get("/v1/work/jobs")
    assert response.status_code == 401


@pytest.mark.parametrize("cursor", [-1, 2**63, 10**100])
def test_work_queue_cursor_outside_sqlite_integer_range_is_a_client_error(client, cursor):
    response = client.get("/v1/work/jobs", params={"cursor": cursor})
    assert response.status_code == 400, response.text


def test_work_queue_accepts_the_largest_sqlite_cursor(client):
    response = client.get("/v1/work/jobs", params={"cursor": 2**63 - 1})
    assert response.status_code == 200
    assert response.json() == {"jobs": [], "next_cursor": None}


def _work_api_payload(kind):
    image_receipt = {"image_id": "tile-1", "sha256": "a" * 64, "receipt": "image-receipt"}
    if kind == "quality":
        return {"response": {"schema": 1}, "image_receipts": [image_receipt]}
    return {"manifest_sha256": "b" * 64, "generation": 7, "conversation_id": "same-chat",
            "source_receipts": [{"source_id": "p1", "sha256": "a" * 64, "receipt": "source-receipt"}],
            "result": answer()}


@pytest.mark.parametrize(("kind", "changes"), [
    ("quality", None), ("answer", None),  # A list of pairs is not a JSON object.
    ("quality", {"extra": True}), ("answer", {"extra": True}),
    ("quality", {"response": []}), ("quality", {"response": [["schema", 1]]}),
    ("answer", {"result": []}), ("answer", {"result": [["questions", []]]}),
    ("answer", {"generation": True}), ("answer", {"generation": 7.0}),
    ("answer", {"generation": "7"}), ("answer", {"manifest_sha256": 123}),
    ("answer", {"conversation_id": 123}),
    ("quality", {"image_receipts": {}}), ("answer", {"source_receipts": {}}),
    ("quality", {"image_receipts": [[["image_id", "tile-1"], ["sha256", "a" * 64],
                                       ["receipt", "image-receipt"]]]}),
    ("answer", {"source_receipts": [[["source_id", "p1"], ["sha256", "a" * 64],
                                       ["receipt", "source-receipt"]]]}),
    ("quality", {"image_receipts": [{"image_id": 1, "sha256": "a" * 64, "receipt": "token"}]}),
    ("quality", {"image_receipts": [{"image_id": "tile-1", "sha256": "a" * 64,
                                    "receipt": "token", "extra": True}]}),
    ("answer", {"source_receipts": [{"source_id": "p1", "sha256": "a" * 64,
                                    "receipt": "token", "extra": True}]}),
    ("answer", {"source_receipts": [{"source_id": "p1", "sha256": "a" * 64,
                                    "delivery": "native_tiles", "inspection_manifest_sha256": "b" * 64,
                                    "image_receipts": [[["image_id", "tile-1"], ["sha256", "a" * 64],
                                                        ["receipt", "token"]]]}]}),
])
def test_work_api_rejects_invalid_payloads_before_authorizing_a_job(client, monkeypatch, kind, changes):
    from app import main

    def unexpected_job_access(job_id):
        raise main.HTTPException(status_code=418, detail="invalid Work input reached job authorization")

    monkeypatch.setattr(main, "_work_current_job", unexpected_job_access)
    payload = _work_api_payload(kind)
    if changes is None:
        payload = list(payload.items())
    else:
        payload.update(changes)
    route = "sources/p1/quality" if kind == "quality" else "result"
    response = client.post(f"/v1/work/jobs/unused/{route}", json=payload)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("kind", ["quality", "original", "native_tiles"])
def test_work_api_passes_only_validated_plain_payloads_to_the_store(client, monkeypatch, kind):
    from app import main

    received = []

    class Store:
        def submit_quality(self, *args, **kwargs):
            received.append((args, kwargs))
            return {"accepted": True}

        submit_result = submit_quality

    monkeypatch.setattr(main, "_work_current_job", lambda job_id: (Store(), {"session_id": 1}))
    monkeypatch.setattr(main, "_exam_session_or_404", lambda *args: {})
    monkeypatch.setattr(main, "_resume_answers", lambda *args: None)
    payload = _work_api_payload("quality" if kind == "quality" else "answer")
    if kind == "native_tiles":
        payload["source_receipts"] = [{"source_id": "p1", "sha256": "a" * 64,
                                       "delivery": "native_tiles", "inspection_manifest_sha256": "b" * 64,
                                       "image_receipts": _work_api_payload("quality")["image_receipts"]}]
    route = "sources/p1/quality" if kind == "quality" else "result"
    response = client.post(f"/v1/work/jobs/fixture/{route}", json=payload)
    assert response.status_code == 200, response.text
    assert response.json() == {"accepted": True}
    if kind == "original":
        payload["source_receipts"][0]["delivery"] = "original_bytes"
    assert received == [(("fixture", "p1") if kind == "quality" else ("fixture",), payload)]


def test_work_api_schema_forbids_extra_fields_without_publishing_model_configuration(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    for name in ("WorkInspectionReceipt", "WorkSourceReceipt", "WorkTileSourceReceipt",
                 "WorkAnswerPayload", "WorkQualityPayload"):
        assert schemas[name]["additionalProperties"] is False
        assert "model_config" not in schemas[name]["properties"]
