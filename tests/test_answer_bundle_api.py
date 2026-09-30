"""The offline answer bundle the glasses read (see
docs/superpowers/specs/2026-09-11-glasses-offline-answer-bundle-design.md)."""

import importlib
import json
import sqlite3
import time

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


def _session_with(client, pages, mode="study"):
    doc_id = client.post("/v1/documents", json={"title": "t"}).json()["document_id"]
    for index, text in enumerate(pages):
        client.post(
            f"/v1/documents/{doc_id}/pages",
            data={"page_index": index, "ocr_text": text},
        )
    client.post(f"/v1/documents/{doc_id}/finalize")
    session_id = client.post(
        "/v1/exam-sessions",
        json={
            "mode": mode,
            "document_id": doc_id,
            "exam_type": "written",
            "answer_format": "mark",
        },
    ).json()["session_id"]
    return doc_id, session_id


PAGE = "\n".join([
    "第1問 次の問いに答えよ。",
    "問1 2x + 3 = 7 を解け。",
    "問2 その理由を述べよ。",
    "第2問 図を見て答えよ。",
])


def test_vector_answer_round_trip_and_invalid_stored_diagram(client):
    import json
    from app import db

    _, session_id = _session_with(client, [PAGE])
    client.post(f"/v1/exam-sessions/{session_id}/finalize-reading")
    bundle = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()
    question_id = int(bundle["items"][0]["question_id"][1:])
    diagram = {"alt": "円", "aspect_ratio": 1, "elements": [
        {"type": "circle", "cx": 0.5, "cy": 0.5, "r": 0.3}]}
    with db.connect() as conn:
        conn.execute("INSERT INTO solutions(question_id, answer, diagrams_json) VALUES (?, '', ?)",
                     (question_id, json.dumps([diagram])))
    bundle = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()
    assert bundle["schema_version"] == 2
    assert bundle["items"][0]["status"] == "ready"
    assert bundle["items"][0]["answer"] == ""
    assert bundle["items"][0]["diagrams"] == [diagram]
    with db.connect() as conn:
        conn.execute("UPDATE solutions SET diagrams_json = '[{}]' WHERE question_id = ?", (question_id,))
    item = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()["items"][0]
    assert item["status"] == "failed" and "図" in item["issue"]
    with db.connect() as conn:
        conn.execute("UPDATE solutions SET diagrams_json = NULL, answer_metadata_json = ? WHERE question_id = ?",
                     (json.dumps({"answer_status": "needs_input", "missing_material": "図の寸法が不明"}), question_id))
    item = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()["items"][0]
    assert item["status"] == "needs_input" and item["issue"] == "図の寸法が不明"


def test_bundle_groups_sub_questions_under_their_section(client):
    _, session_id = _session_with(client, [PAGE])
    client.post(f"/v1/exam-sessions/{session_id}/finalize-reading")

    body = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()

    assert body["schema_version"] == 1
    assert body["session_id"] == str(session_id)
    assert len(body["input_digest"]) == 64
    assert body["revision"] >= 1
    assert [(i["group_label"], i["question_label"]) for i in body["items"]] == [
        ("第1問", "問1"),
        ("第1問", "問2"),
        ("第2問", "全問"),
    ]
    assert body["items"][0]["group_id"] == "g1"
    assert body["items"][2]["group_id"] == "g2"
    assert all(i["question_id"].startswith("q") for i in body["items"])


def test_unsolved_items_are_pending_with_no_answer_text(client):
    _, session_id = _session_with(client, [PAGE])
    client.post(f"/v1/exam-sessions/{session_id}/finalize-reading")

    items = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()["items"]

    for item in items:
        if item["status"] != "ready":
            assert item["answer"] == ""
            assert item["issue"]


def test_a_section_without_sub_questions_becomes_one_whole_item(client):
    # tests/fixtures/answer_forms/cases.json stores each page as a single
    # line, so the segmenter yields the 第N問 heading alone. The group must
    # still carry one item, or AnswerBundle rejects the whole snapshot.
    _, session_id = _session_with(
        client, ["第1問 問1 頂点の y 座標を求めよ。 問2 最小値を答えよ。"]
    )
    client.post(f"/v1/exam-sessions/{session_id}/finalize-reading")

    items = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()["items"]

    assert [(i["group_label"], i["question_label"]) for i in items] == [
        ("第1問", "全問"),
    ]


def test_digest_is_stable_and_revision_advances_when_an_answer_is_ingested(client):
    _, session_id = _session_with(client, [PAGE])
    client.post(f"/v1/exam-sessions/{session_id}/finalize-reading")
    first = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()

    ingested = client.post(
        f"/v1/exam-sessions/{session_id}/solutions",
        json={"solutions": [{"problem_no": "問1", "answer": "x = 2"}]},
    )
    assert ingested.status_code == 200

    second = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()

    assert second["input_digest"] == first["input_digest"]
    assert second["revision"] > first["revision"]
    item = second["items"][0]
    assert (item["group_label"], item["question_label"]) == ("第1問", "問1")
    assert item["status"] == "ready"
    assert item["answer"] == "x = 2"


def test_reading_phase_is_409(client):
    _, session_id = _session_with(client, [PAGE])

    response = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle")

    assert response.status_code == 409
    assert "finalize-reading" in response.json()["detail"]


def test_real_mode_lock_is_409(client):
    # finalize-reading still segments/transitions in mode=real (it reveals
    # nothing); the lock is on answers, so it must reject the bundle itself.
    _, session_id = _session_with(client, [PAGE], mode="real")
    client.post(f"/v1/exam-sessions/{session_id}/finalize-reading")

    response = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle")

    assert response.status_code == 409
    assert "locked" in response.json()["detail"]


def test_unknown_session_is_404(client):
    assert client.get("/v1/exam-sessions/9999/answer-bundle").status_code == 404


def test_items_without_a_group_heading_fall_back_to_one_default_group(client):
    # No 大問N / 第N問 heading anywhere on the page: _answer_groups opens the
    # synthesized "全体" default group instead of leaving the first row
    # groupless.
    page = "\n".join([
        "問1 2x + 3 = 7 を解け。",
        "問2 その理由を述べよ。",
    ])
    _, session_id = _session_with(client, [page])
    client.post(f"/v1/exam-sessions/{session_id}/finalize-reading")

    items = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()["items"]

    assert [(i["group_id"], i["group_label"], i["question_label"]) for i in items] == [
        ("g1", "全体", "問1"),
        ("g1", "全体", "問2"),
    ]


# --- FS-65: 未対応要素を落としたREADYを禁止 ----------------------------------


def _ingest(client, session_id, answer):
    client.post(f"/v1/exam-sessions/{session_id}/finalize-reading")
    posted = client.post(
        f"/v1/exam-sessions/{session_id}/solutions",
        json={"solutions": [{"problem_no": "問1", "answer": answer}]},
    )
    assert posted.status_code == 200
    body = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()
    return next(i for i in body["items"] if i["question_label"] == "問1")


def test_a_latex_fraction_reaches_the_operator_as_writable_text(client):
    _, session_id = _session_with(client, [PAGE])
    item = _ingest(client, session_id, chr(92) + "frac{1}{2}")
    assert item["status"] == "ready"
    assert item["answer"] == "1/2"


def test_an_answer_with_a_table_is_not_reported_ready(client):
    """The HUD renders characters, not columns. Reporting this ready would put
    a row of pipes in front of the operator and call it an answer."""
    _, session_id = _session_with(client, [PAGE])
    item = _ingest(client, session_id, "| a | b |\n|---|---|\n| 1 | 2 |")
    assert item["status"] == "needs_review"
    assert "表" in item["issue"]
    # The text is still carried: a partial answer beats no answer.
    assert item["answer"]


def test_unknown_notation_is_named_and_kept_out_of_ready(client):
    _, session_id = _session_with(client, [PAGE])
    item = _ingest(client, session_id, chr(92) + "begin{array}{c}1" + chr(92) + "end{array}")
    assert item["status"] == "needs_review"
    assert chr(92) + "begin" in item["issue"]


def test_input_digest_changes_for_image_bytes_even_with_identical_phash_and_ocr(client, tmp_path):
    from app import db, main
    doc_id, session_id = _session_with(client, [PAGE])
    path = tmp_path / "same-path.png"
    path.write_bytes(b"first-original")
    with db.connect() as conn:
        conn.execute("UPDATE pages SET image_path = ?, phash = 'same', ocr_md5 = 'same' WHERE document_id = ?",
                     (str(path), doc_id))
        session = conn.execute("SELECT * FROM exam_sessions WHERE id = ?", (session_id,)).fetchone()
        first = main._answer_input_digest(conn, session)
        assert first == main._answer_input_digest(conn, session)
        path.write_bytes(b"other-original")
        assert first != main._answer_input_digest(conn, session)


def test_input_digest_includes_vision_text_not_only_ocr(client):
    from app import db, main
    doc_id, session_id = _session_with(client, [PAGE])
    with db.connect() as conn:
        session = conn.execute("SELECT * FROM exam_sessions WHERE id = ?", (session_id,)).fetchone()
        first = main._answer_input_digest(conn, session)
        conn.execute("UPDATE pages SET vision_text = 'changed diagram' WHERE document_id = ?", (doc_id,))
        assert first != main._answer_input_digest(conn, session)


def test_audio_digest_works_without_python_311_file_digest(client, tmp_path, monkeypatch):
    import hashlib
    from app import db, main
    _, session_id = _session_with(client, [PAGE])
    path = tmp_path / "original.wav"
    path.write_bytes(b"audio original")
    monkeypatch.delattr(hashlib, "file_digest", raising=False)
    with db.connect() as conn:
        conn.execute("UPDATE exam_sessions SET audio_path = ? WHERE id = ?", (str(path), session_id))
        session = conn.execute("SELECT * FROM exam_sessions WHERE id = ?", (session_id,)).fetchone()
        first = main._answer_input_digest(conn, session)
        path.write_bytes(b"audio changed")
        assert first != main._answer_input_digest(conn, session)


def test_failed_solve_is_persisted_without_leaking_exception_text(client, monkeypatch):
    from app import main
    _, session_id = _session_with(client, [PAGE])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")
    def fail(**_):
        raise RuntimeError("private OCR text and credential must not be returned")
    monkeypatch.setattr(main, "solve_with_fallback", fail)
    assert client.post(f"/v1/exam-sessions/{session_id}/finalize-reading").status_code == 200
    first = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()
    assert all(item["status"] == "failed" for item in first["items"])
    assert "private OCR" not in str(first)
    client.post(f"/v1/exam-sessions/{session_id}/finalize-reading")
    second = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()
    assert second["revision"] > first["revision"]


def test_uncertain_browser_send_stops_batch_before_other_questions(client, monkeypatch):
    from app import main
    from app.solvers.chatgpt_web import ChatGptWebUncertain
    _, session_id = _session_with(client, ["問1 2+2を求めよ。\n問2 3+3を求めよ。"])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")
    calls = []
    def fail(**_):
        calls.append(1)
        raise ChatGptWebUncertain("send needs inspection")
    monkeypatch.setattr(main, "solve_with_fallback", fail)
    assert client.post(f"/v1/exam-sessions/{session_id}/finalize-reading").status_code == 200
    assert len(calls) == 1
    body = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()
    assert body["items"][0]["status"] == "failed"
    assert "再送" in body["items"][0]["issue"]
    assert any(item["status"] == "pending" for item in body["items"][1:])


CHAT_LOST_ISSUE = "教科のチャットへ戻れません。新しいチャットは作っていません"


def test_a_lost_subject_chat_stops_the_batch_and_says_why(client, monkeypatch):
    # Every later question would cost ATTEMPTS page loads and end the same way.
    from app import main
    from app.solvers.chatgpt_web import ChatGptWebChatLost
    _, session_id = _session_with(client, ["問1 2+2を求めよ。\n問2 3+3を求めよ。"])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")
    calls = []
    def lost(**_):
        calls.append(1)
        raise ChatGptWebChatLost("could not return to the subject's chat")
    monkeypatch.setattr(main, "solve_with_fallback", lost)
    assert client.post(f"/v1/exam-sessions/{session_id}/finalize-reading").status_code == 200
    assert len(calls) == 1
    body = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()
    assert body["items"][0]["status"] == "failed"
    assert body["items"][0]["issue"] == CHAT_LOST_ISSUE
    assert any(item["status"] == "pending" for item in body["items"][1:])


def test_bundle_keeps_items_and_revision_in_one_snapshot(client, monkeypatch):
    """Concurrent committed answers cannot lend their revision to older items.

    WAL is enabled only in this fixture to commit deterministically while the
    read is paused, without timing assumptions or changing production settings.
    """
    from app import db, main

    _, session_id = _session_with(client, [PAGE])
    client.post(f"/v1/exam-sessions/{session_id}/finalize-reading")
    url = f"/v1/exam-sessions/{session_id}/answer-bundle"
    before = client.get(url).json()
    question_id = int(before["items"][0]["question_id"][1:])
    with db.connect() as conn:
        assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    original_revision = main._answer_revision
    inserted = False

    def publish_answer_during_snapshot(conn, selected_session):
        nonlocal inserted
        if not inserted:
            inserted = True
            with db.connect() as writer:
                writer.execute("INSERT INTO solutions(question_id, answer) VALUES (?, ?)",
                               (question_id, "new concurrent answer"))
        return original_revision(conn, selected_session)

    monkeypatch.setattr(main, "_answer_revision", publish_answer_during_snapshot)
    during = client.get(url).json()
    after = client.get(url).json()
    assert inserted
    assert during == before
    assert after["items"][0]["answer"] == "new concurrent answer"
    assert after["revision"] > during["revision"]
    assert after["input_digest"] == during["input_digest"]


def test_background_finalize_publishes_each_answer_before_the_batch_ends(client, monkeypatch):
    """RP-15: the glasses read saved 小問 while later ones are still solving."""
    import threading
    import time

    from app import main
    from app.solvers.base import SolveResult

    _, session_id = _session_with(client, ["問1 2+2を求めよ。\n問2 3+3を求めよ。"])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")
    second_may_finish = threading.Event()
    calls = []

    class Solver:
        name = "test-provider"

    def solve(*, question):
        calls.append(question.question_id)
        if len(calls) == 2:
            assert second_may_finish.wait(5)
        return SolveResult(answer=f"answer {len(calls)}"), Solver()

    monkeypatch.setattr(main, "solve_with_fallback", solve)
    url = f"/v1/exam-sessions/{session_id}/answer-bundle"
    finalize = f"/v1/exam-sessions/{session_id}/finalize-reading?solve=background"
    body = client.post(finalize).json()
    assert body["status"] == "reviewing" and body["solving"] == "background"

    def statuses():
        response = client.get(url)  # 409 while the answers are being made
        return [item["status"] for item in response.json()["items"]] if response.status_code == 200 else []

    deadline = time.monotonic() + 5
    while statuses() != ["ready", "pending"] and time.monotonic() < deadline:
        time.sleep(0.01)
    partial = client.get(url).json()
    assert [i["status"] for i in partial["items"]] == ["ready", "pending"]
    # A repeated call while the batch runs must not start a second browser user.
    assert client.post(finalize).json()["solving"] == "background"
    second_may_finish.set()
    while statuses() != ["ready", "ready"] and time.monotonic() < deadline:
        time.sleep(0.01)
    final = client.get(url).json()
    assert [i["status"] for i in final["items"]] == ["ready", "ready"]
    assert final["revision"] > partial["revision"]
    assert len(calls) == 2


def test_finalize_without_background_still_solves_before_returning(client, monkeypatch):
    from app import main
    from app.solvers.base import SolveResult

    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")

    class Solver:
        name = "test-provider"

    monkeypatch.setattr(main, "solve_with_fallback", lambda **_: (SolveResult(answer="4"), Solver()))
    body = client.post(f"/v1/exam-sessions/{session_id}/finalize-reading").json()
    assert body["server_solved"] == 1 and "solving" not in body


def _background_finalize_and_wait(client, session_id, done):
    import time

    url = f"/v1/exam-sessions/{session_id}/answer-bundle"
    body = client.post(f"/v1/exam-sessions/{session_id}/finalize-reading?solve=background").json()
    assert body["solving"] == "background"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(url)
        if response.status_code == 200 and done(response.json()["items"]):
            return response.json()
        time.sleep(0.01)
    raise AssertionError("background batch did not finish")


def _replies(*rows):
    """answer_all's shape: (item, SolveResult or the error that item raised)."""
    from app.solvers.base import SolveResult

    return [({"group": group, "label": label, "pages": pages},
             SolveResult(answer=answer) if isinstance(answer, str) else answer)
            for group, label, pages, answer in rows]


def test_one_message_names_and_answers_the_whole_deck(client, monkeypatch):
    """9/29: the next message went out before anything was answered. Now one does it all."""
    from app import main

    _, session_id = _session_with(client, ["問1 Choose\n(1) a\n(2) b"])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")
    asked, per_question = [], []

    def answer_all(question):
        asked.append(question)
        return _replies(("第1問", "問1", [1], "④"), ("第1問", "問2", [1, 99], "②"),
                        ("第2問", "問1", [], "③"), ("", "", [1], "x"))

    monkeypatch.setattr(main, "_answer_all", answer_all)
    monkeypatch.setattr(main, "solve_with_fallback", lambda **_: per_question.append(1))
    bundle = _background_finalize_and_wait(
        client, session_id, lambda items: all(i["status"] == "ready" for i in items))
    assert [(i["group_label"], i["question_label"], i["answer"]) for i in bundle["items"]] == [
        ("第1問", "問1", "④"), ("第1問", "問2", "②"), ("第2問", "問1", "③")]
    assert len(asked) == 1 and per_question == []
    assert asked[0].chat_key == f"session:{session_id}" and asked[0].document_pages

    # A repeated finalize after the answers are in asks nothing again.
    _background_finalize_and_wait(
        client, session_id, lambda items: all(i["status"] == "ready" for i in items))
    assert len(asked) == 1


def test_the_reply_shape_the_model_may_use_still_lands_on_the_right_rows(client, monkeypatch):
    """Audit 2026-09-29: one 問 with two answer slots, the 大問 repeated in the
    label, and an answer for a whole 大問 with no label of its own."""
    from app import main

    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")
    monkeypatch.setattr(main, "_answer_all", lambda question: _replies(
        ("第1問", "問3", [1], "4"), ("第1問", "問3", [1], "2"),
        ("第2問", "第2問 問1", [1], "⑤"), ("第3問", "", [1], "図")))
    monkeypatch.setattr(main, "solve_with_fallback", lambda **_: pytest.fail("per-question send"))
    bundle = _background_finalize_and_wait(
        client, session_id, lambda items: items and all(i["status"] != "pending" for i in items))
    assert [(i["group_label"], i["question_label"], i["status"], i["answer"])
            for i in bundle["items"]] == [
        ("第1問", "問3", "ready", "4"), ("第1問", "問3", "ready", "2"),
        ("第2問", "問1", "ready", "⑤"), ("第3問", "全問", "ready", "図")]


def test_a_kanji_numbered_group_stays_a_group(client, monkeypatch):
    """Run 4b (2026-09-30): "第一問" was folded into its labels and shown as one 全体."""
    from app import main

    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")
    monkeypatch.setattr(main, "_answer_all", lambda question: _replies(
        ("第一問", "問一（一）", [1], "4"), ("第一問", "問一（二）", [1], "2"),
        ("大問二", "問1", [1], "⑤")))
    monkeypatch.setattr(main, "solve_with_fallback", lambda **_: pytest.fail("per-question send"))
    bundle = _background_finalize_and_wait(
        client, session_id, lambda items: items and all(i["status"] != "pending" for i in items))
    assert [(i["group_label"], i["question_label"], i["answer"]) for i in bundle["items"]] == [
        ("第一問", "問一（一）", "4"), ("第一問", "問一（二）", "2"), ("大問二", "問1", "⑤")]


@pytest.mark.parametrize("error, status, issue", [
    ("limit", "failed", "ChatGPTの利用制限です。解除後に再開してください"),
    ("busy", "pending", "別の解析がブラウザを使用中です。自動で再試行します"),
    ("no chrome", "pending", "ChatGPTへ送れませんでした。自動で再試行します")])
def test_a_limit_or_a_busy_browser_says_so_on_the_glasses(client, monkeypatch, error, status, issue):
    from app import main
    from app.solvers.chatgpt_web import ChatGptWebBusy, ChatGptWebError, ChatGptWebRateLimit

    monkeypatch.setattr(main, "PRESEND_RETRY_S", 0)  # nothing sent: tried again, then shown
    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")

    def answer_all(question):
        raise (ChatGptWebRateLimit("usage limit") if error == "limit"
               else ChatGptWebBusy("browser is busy; no message sent") if error == "busy"
               else ChatGptWebError("no Chrome on http://127.0.0.1:9222"))

    monkeypatch.setattr(main, "_answer_all", answer_all)
    bundle = _background_finalize_and_wait(
        client, session_id, lambda items: items[0]["issue"] == issue)
    assert bundle["items"][0]["status"] == status


def test_a_failure_before_anything_was_sent_is_tried_again(client, monkeypatch):
    """No PC at the venue: an unreachable Chrome must not cost the subject."""
    from app import main
    from app.solvers.chatgpt_web import ChatGptWebError, ChatGptWebUncertain

    monkeypatch.setattr(main, "PRESEND_RETRY_S", 0)
    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")
    calls = []

    def answer_all(question):
        calls.append(1)
        if len(calls) < 3:
            raise ChatGptWebError("no Chrome on http://127.0.0.1:9222")
        return _replies(("第1問", "問1", [1], "4"))

    monkeypatch.setattr(main, "_answer_all", answer_all)
    bundle = _background_finalize_and_wait(
        client, session_id, lambda items: items and all(i["status"] == "ready" for i in items))
    assert len(calls) == 3 and bundle["items"][0]["answer"] == "4"

    # After a send whose outcome is unknown, never again.
    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    calls.clear()

    def uncertain(question):
        calls.append(1)
        raise ChatGptWebUncertain("send outcome unknown")

    monkeypatch.setattr(main, "_answer_all", uncertain)
    _background_finalize_and_wait(client, session_id, lambda items: items[0]["status"] == "failed")
    assert len(calls) == 1


def test_a_failure_that_sent_nothing_is_answered_later_without_the_operator(client, monkeypatch):
    """Chrome was away for the whole batch; the glasses' next poll starts it again."""
    from app import main
    from app.solvers.chatgpt_web import ChatGptWebError

    monkeypatch.setattr(main, "PRESEND_RETRY_S", 0)
    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")
    chrome = []

    def answer_all(question):
        if not chrome:
            raise ChatGptWebError("no Chrome on http://127.0.0.1:9222")
        return _replies(("第1問", "問1", [1], "4"), ("第1問", "問2", [1], "6"))

    monkeypatch.setattr(main, "_answer_all", answer_all)
    _background_finalize_and_wait(client, session_id,
                                  lambda items: items[0]["status"] == "pending" and items[0]["issue"])
    chrome.append(True)
    bundle = _background_finalize_and_wait(
        client, session_id, lambda items: items and all(i["status"] == "ready" for i in items))
    assert [i["answer"] for i in bundle["items"]] == ["4", "6"]


def test_a_restart_that_lost_the_batch_starts_it_again(client, monkeypatch):
    """A reviewing session with no deck and no batch running is picked up again."""
    import time

    from app import main, db

    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")
    with db.connect() as conn:  # what a restart mid-analysis leaves behind
        conn.execute("UPDATE exam_sessions SET status = 'reviewing' WHERE id = ?", (session_id,))
    monkeypatch.setattr(main, "_answer_all", lambda question: _replies(("第1問", "問1", [1], "4")))
    main._resume_all_answers()
    url = f"/v1/exam-sessions/{session_id}/answer-bundle"
    deadline = time.monotonic() + 5
    while client.get(url).status_code != 200 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert client.get(url).json()["items"][0]["answer"] == "4"


def test_an_item_without_a_valid_answer_fails_alone(client, monkeypatch):
    from app import main

    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")
    monkeypatch.setattr(main, "_answer_all", lambda question: _replies(
        ("第1問", "問1", [1], "4"), ("第1問", "問2", [1], ValueError("empty answer"))))
    monkeypatch.setattr(main, "solve_with_fallback", lambda **_: pytest.fail("per-question send"))
    bundle = _background_finalize_and_wait(
        client, session_id, lambda items: all(i["status"] != "pending" for i in items))
    assert [(i["question_label"], i["status"]) for i in bundle["items"]] == [
        ("問1", "ready"), ("問2", "failed")]


def test_an_unusable_reply_fails_the_deck_without_another_send(client, monkeypatch):
    from app import main

    _, session_id = _session_with(client, ["問1 2+2を求めよ。\n問2 3+3を求めよ。"])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")

    def answer_all(question):
        raise ValueError("no JSON")

    monkeypatch.setattr(main, "_answer_all", answer_all)
    monkeypatch.setattr(main, "solve_with_fallback", lambda **_: pytest.fail("per-question send"))
    bundle = _background_finalize_and_wait(
        client, session_id, lambda items: items[0]["status"] == "failed")
    # OCR does not sort the questions: one row for the booklet carries the reason.
    assert [i["question_label"] for i in bundle["items"]] == ["全体"]
    assert bundle["items"][0]["issue"] == "解析に失敗しました。資料は保持しています"

    # A retry that is answered replaces that row with the model's questions.
    monkeypatch.setattr(main, "_answer_all", lambda question: _replies(
        ("第1問", "問1", [1], "4"), ("第1問", "問2", [1], "6")))
    bundle = _background_finalize_and_wait(
        client, session_id, lambda items: items and all(i["status"] == "ready" for i in items))
    assert [(i["question_label"], i["answer"]) for i in bundle["items"]] == [("問1", "4"), ("問2", "6")]


@pytest.mark.parametrize("error, issue", [
    ("uncertain", "再送"), ("lost", CHAT_LOST_ISSUE)])
def test_an_uncertain_or_lost_chat_stops_the_one_message(client, monkeypatch, error, issue):
    from app import main
    from app.solvers.chatgpt_web import ChatGptWebChatLost, ChatGptWebUncertain

    _, session_id = _session_with(client, ["問1 2+2を求めよ。\n問2 3+3を求めよ。"])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")

    def answer_all(question):
        raise (ChatGptWebUncertain("send needs inspection") if error == "uncertain"
               else ChatGptWebChatLost("could not return to the subject's chat"))

    monkeypatch.setattr(main, "_answer_all", answer_all)
    monkeypatch.setattr(main, "solve_with_fallback", lambda **_: pytest.fail("per-question send"))
    bundle = _background_finalize_and_wait(
        client, session_id, lambda items: items[0]["status"] == "failed")
    assert issue in bundle["items"][0]["issue"]


class _BookletChat:
    """ChatGptWebSolver's client, counting sends; the chat holds its one reply."""

    model = "chatgpt-web"
    last_image_attached = None

    def __init__(self, reply):
        self.reply, self.sends, self.chats = reply, 0, set()

    def complete_json(self, *, chat_key, **kw):
        self.sends += 1
        self.chats.add(chat_key)
        return json.loads(self.reply)

    def recorded(self, chat_key):
        return chat_key in self.chats

    def recover(self, *, chat_key, expect):
        return self.reply


def _booklet_solver(monkeypatch, reply):
    from app import main
    from app.solvers import chatgpt_web

    chat = _BookletChat(reply)
    solver = chatgpt_web.ChatGptWebSolver(client=chat)
    monkeypatch.setattr(chatgpt_web, "_booklet_chat_key", lambda question, audio: "session:booklet")
    monkeypatch.setattr(main, "_answer_all", lambda question: solver.answer_all(question=question))
    return chat


def test_a_repeated_finalize_reads_the_booklet_chat_and_never_sends_again(client, monkeypatch):
    """glassdoc finalizes again after a restart; one item's answer was invalid."""
    chat = _booklet_solver(monkeypatch, json.dumps({"questions": [
        {"group": "第1問", "label": "問1", "status": "ready", "answer": "4"},
        {"group": "第1問", "label": "問2", "status": "ready", "answer": ""}]}))
    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")
    done = lambda items: items and all(i["status"] != "pending" for i in items)  # noqa: E731

    _background_finalize_and_wait(client, session_id, done)
    bundle = _background_finalize_and_wait(client, session_id, done)

    assert chat.sends == 1
    assert [i["status"] for i in bundle["items"]] == ["ready", "failed"]


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_answers_lost_before_their_commit_are_read_back_not_sent_again(client, monkeypatch):
    """A kill or a locked database after the reply: the resume reads the chat."""
    import time

    from app import main

    chat = _booklet_solver(monkeypatch, json.dumps({"questions": [
        {"group": "第1問", "label": "問1", "status": "ready", "answer": "4"}]}))
    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")
    real_save = main._save_solution
    failures = []

    def save(*args, **kwargs):
        if not failures:
            failures.append(1)
            raise sqlite3.OperationalError("database is locked")
        return real_save(*args, **kwargs)

    monkeypatch.setattr(main, "_save_solution", save)
    client.post(f"/v1/exam-sessions/{session_id}/finalize-reading?solve=background")
    url = f"/v1/exam-sessions/{session_id}/answer-bundle"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(url)  # the poll that resumes the lost batch
        if response.status_code == 200 and response.json()["items"][0]["status"] == "ready":
            break
        time.sleep(0.01)
    assert client.get(url).json()["items"][0]["answer"] == "4"
    assert chat.sends == 1 and failures == [1]


def test_an_old_reviewing_session_is_never_resumed(client, monkeypatch):
    """B1: the phone DB holds earlier sessions; startup must not send any of them."""
    from app import main, db

    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")
    with db.connect() as conn:
        conn.execute("UPDATE exam_sessions SET status = 'reviewing', "
                     "created_at = datetime('now', '-4 hours') WHERE id = ?", (session_id,))
    calls = []
    monkeypatch.setattr(main, "_answer_all", lambda question: calls.append(1))
    main._resume_all_answers()
    assert client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").status_code == 409
    time.sleep(0.2)
    assert calls == []


def test_retries_that_never_send_stop_and_say_why(client, monkeypatch):
    """M5: after RESUME_LIMIT batches that sent nothing, the deck stops waiting."""
    import time

    from app import main
    from app.solvers.chatgpt_web import ChatGptWebError

    monkeypatch.setattr(main, "PRESEND_RETRY_S", 0)
    monkeypatch.setattr(main, "PRESEND_TRIES", 1)
    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")
    calls = []

    def answer_all(question):
        calls.append(1)
        raise ChatGptWebError("no Chrome on http://127.0.0.1:9222")

    monkeypatch.setattr(main, "_answer_all", answer_all)
    bundle = _background_finalize_and_wait(
        client, session_id, lambda items: items and items[0]["status"] == "failed")
    assert bundle["items"][0]["issue"] == "ChatGPTへ送れませんでした。ブラウザを確認して読取完了をやり直してください"
    time.sleep(0.2)
    client.get(f"/v1/exam-sessions/{session_id}/answer-bundle")
    time.sleep(0.2)
    assert len(calls) == main.RESUME_LIMIT


def test_the_revision_still_rises_when_the_failed_row_is_replaced(client, monkeypatch):
    """m3: the glasses refuse an older revision, so the failures carry over."""
    from app import main
    from app.solvers.chatgpt_web import ChatGptWebError

    monkeypatch.setattr(main, "PRESEND_RETRY_S", 0)
    monkeypatch.setattr(main, "PRESEND_TRIES", 1)
    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")
    chrome = []

    def answer_all(question):
        if not chrome:
            raise ChatGptWebError("no Chrome on http://127.0.0.1:9222")
        return _replies(("第1問", "問1", [1], "4"))

    monkeypatch.setattr(main, "_answer_all", answer_all)
    failed = _background_finalize_and_wait(
        client, session_id, lambda items: items and items[0]["issue"].endswith("自動で再試行します"))
    chrome.append(True)
    answered = _background_finalize_and_wait(
        client, session_id, lambda items: items and items[0]["status"] == "ready")
    assert answered["revision"] > failed["revision"]


def test_another_sessions_unconfirmed_send_is_waited_out_not_final(client, monkeypatch):
    """m4: blocked by someone else's pending send is retried, not 'uncertain'."""
    from app import main
    from app.solvers.chatgpt_web import ChatGptWebBlocked

    monkeypatch.setattr(main, "PRESEND_RETRY_S", 0)
    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")

    def answer_all(question):
        raise ChatGptWebBlocked("previous send outcome is unknown")

    monkeypatch.setattr(main, "_answer_all", answer_all)
    bundle = _background_finalize_and_wait(
        client, session_id, lambda items: items and items[0]["issue"])
    assert bundle["items"][0]["status"] == "pending"
    assert bundle["items"][0]["issue"] == "前の送信の結果確認待ちです。自動で再試行します"


def _numbered(*rows):
    """Items in the reply's own shape, answered through the real rules.

    Unlike :func:`_replies` this builds the SolveResult from the item, so the
    printed 解答番号 travels the path it travels in a session.
    """
    from app.solvers.llm_adapter import answer_sheet_result

    items = [{"group": group, "label": label, "answer_no": numbers, "pages": [1],
              "status": "ready", "answer": answer}
             for group, label, numbers, answer in rows]
    return [(item, answer_sheet_result(item, subject=None, extras={})) for item in items]


def test_a_skipped_answer_number_is_shown_instead_of_dropped(client, monkeypatch):
    """9/30: a 小問 missing from the one reply left no row at all, so a booklet
    the model had mostly dropped still finalized as a complete deck."""
    from app import main

    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")
    monkeypatch.setattr(main, "_answer_all", lambda question: _numbered(
        ("第1問", "問1", [101], "④"), ("第1問", "問4", [104], "②")))
    monkeypatch.setattr(main, "solve_with_fallback", lambda **_: pytest.fail("per-question send"))

    bundle = _background_finalize_and_wait(
        client, session_id, lambda items: items and all(i["status"] != "pending" for i in items))

    assert [(i["question_label"], i["status"], i["answer"] or i["issue"], i.get("answer_no"))
            for i in bundle["items"]] == [
        ("問1", "ready", "④", [101]),
        ("問4", "ready", "②", [104]),
        ("解答番号102", "failed", "この解答番号の答えが返答にありません", None),
        ("解答番号103", "failed", "この解答番号の答えが返答にありません", None)]


def test_a_booklet_that_prints_no_answer_numbers_keeps_its_deck(client, monkeypatch):
    """Only printed numbers can name a gap; without them nothing is invented."""
    from app import main

    _, session_id = _session_with(client, ["問1 2+2を求めよ。"])
    monkeypatch.setenv("ROKID_SOLVER", "test-provider")
    monkeypatch.setattr(main, "_answer_all", lambda question: _numbered(
        ("第1問", "問1", [], "④"), ("第1問", "問2", [], "②")))
    monkeypatch.setattr(main, "solve_with_fallback", lambda **_: pytest.fail("per-question send"))

    bundle = _background_finalize_and_wait(
        client, session_id, lambda items: items and all(i["status"] != "pending" for i in items))

    assert [(i["question_label"], i["status"]) for i in bundle["items"]] == [
        ("問1", "ready"), ("問2", "ready")]
