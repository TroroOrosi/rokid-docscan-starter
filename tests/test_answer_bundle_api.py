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


def _session_with(client, pages):
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
            "mode": "study",
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


def test_digest_is_stable_and_revision_never_goes_backwards(client):
    _, session_id = _session_with(client, [PAGE])
    client.post(f"/v1/exam-sessions/{session_id}/finalize-reading")
    first = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()
    second = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()

    assert first["input_digest"] == second["input_digest"]
    assert second["revision"] >= first["revision"]


def test_reading_phase_is_409(client):
    _, session_id = _session_with(client, [PAGE])

    response = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle")

    assert response.status_code == 409
    assert "finalize-reading" in response.json()["detail"]


def test_unknown_session_is_404(client):
    assert client.get("/v1/exam-sessions/9999/answer-bundle").status_code == 404
