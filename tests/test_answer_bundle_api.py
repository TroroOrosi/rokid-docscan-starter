"""The offline answer bundle the glasses read (see
docs/superpowers/specs/2026-09-11-glasses-offline-answer-bundle-design.md)."""

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
