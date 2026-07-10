"""Tests for the 3-phase exam flow (読取 → 一括解答 → 閲覧).

Covers:
  * POST /finalize-reading — segmentation into problems, status open→reviewing,
    reading ack (client sensor-close requirement), idempotency, document requirement,
  * server-side solve-all only when a non-local ROKID_SOLVER is configured
    (whole document as context; listening transcript folded in),
  * POST /solutions — onboard AI ingest (primary path): deck solved flags,
    served_by, 409 before finalize, unknown problem_no appends, latest wins,
    empty answer rejected,
  * GET /solutions — review-deck listing (polling-safe during reading),
  * GET /review — merged single-stream HUD, clamping, problem navigation,
    unsolved placeholder, 409 before finalize,
  * mode=real lock across finalize/ingest/deck/review,
  * regression: solve-current keeps working after finalize-reading.

All offline: no external credentials, fake solver injected where needed.
"""

import importlib

import pytest
from fastapi.testclient import TestClient

from tests.conftest import image_bytes, make_image


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ROKID_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ROKID_ALLOW_REAL_EXAM_SOLVE", raising=False)
    monkeypatch.delenv("ROKID_TRANSCRIBER", raising=False)
    monkeypatch.delenv("ROKID_SOLVER", raising=False)
    import app.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)
    import app.main as main
    importlib.reload(main)
    main.ensure_dirs()
    main.db.init_db()
    return TestClient(main.app)


def _doc_with_text_pages(client, texts):
    r = client.post("/v1/documents", json={"title": "模試"})
    assert r.status_code == 201
    doc_id = r.json()["document_id"]
    for i, t in enumerate(texts):
        r = client.post(
            f"/v1/documents/{doc_id}/pages", json={"page_index": i, "ocr_text": t}
        )
        assert r.status_code == 201, r.text
    assert client.post(f"/v1/documents/{doc_id}/finalize").status_code == 200
    return doc_id


def _new_doc_exam(client, doc_id, exam_type="written", answer_format="mark", mode="study"):
    r = client.post(
        "/v1/exam-sessions",
        json={
            "mode": mode,
            "document_id": doc_id,
            "exam_type": exam_type,
            "answer_format": answer_format,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


_TWO_PROBLEM_PAGES = ["問1 りんごは何個か", "問2 みかんは何個か"]


def _finalized_session(client, texts=None, **kw):
    doc_id = _doc_with_text_pages(client, texts or _TWO_PROBLEM_PAGES)
    sid = _new_doc_exam(client, doc_id, **kw)["session_id"]
    r = client.post(f"/v1/exam-sessions/{sid}/finalize-reading")
    assert r.status_code == 200, r.text
    return sid, r.json()


class _RecordingSolver:
    """Duck-typed solver that records every Question it received (offline)."""

    name = "recording-test"
    provider_version = "t-1"
    offline = True
    seen: list = []

    def solve(self, *, question, max_answer_len=64):
        from app.solvers import SolveResult

        _RecordingSolver.seen.append(question)
        return SolveResult(
            answer="A", solution_steps=["s"], rationale="r", cautions="c",
            answer_confidence=0.9, rationale_confidence=0.9,
        )

    def info(self):
        return {"name": self.name, "provider_version": self.provider_version,
                "offline": self.offline}


def _use_recording_solver(monkeypatch):
    from app.solvers.registry import register_solver

    _RecordingSolver.seen = []
    register_solver(_RecordingSolver(), replace=True)
    monkeypatch.setenv("ROKID_SOLVER", "recording-test")


# --- phase 1 → 2: finalize-reading -------------------------------------------

def test_finalize_reading_segments_and_transitions(client):
    sid, body = _finalized_session(client)
    assert body["status"] == "reviewing"
    assert body["already_finalized"] is False
    assert body["problem_count"] == 2
    assert [p["problem_no"] for p in body["problems"]] == ["問1", "問2"]
    # The server requires client closure but cannot observe camera/LED hardware.
    assert body["camera"] == {
        "client_action": "close_visual_sensor",
        "expected_state": "off_after_client_closes",
        "observed_state": "not_observed_by_server",
        "privacy_led": "device_controlled",
    }
    ack = body["reading_ack"]
    assert len(ack["lines"]) <= 3
    assert ack["camera_close_required"] is True
    assert ack["camera_off_confirmed"] is False
    # Session now reports the reviewing phase.
    s = client.get(f"/v1/exam-sessions/{sid}").json()
    assert s["phase"] == "reviewing"
    assert s["problem_count"] == 2


def test_finalize_reading_is_idempotent(client):
    sid, first = _finalized_session(client)
    r = client.post(f"/v1/exam-sessions/{sid}/finalize-reading")
    assert r.status_code == 200
    again = r.json()
    assert again["already_finalized"] is True
    # Gesture double-fire must not duplicate the deck.
    assert again["problem_count"] == first["problem_count"] == 2


def test_finalize_reading_requires_document_session(client):
    r = client.post("/v1/exam-sessions", json={"mode": "study"})
    sid = r.json()["session_id"]
    assert client.post(f"/v1/exam-sessions/{sid}/finalize-reading").status_code == 400


def test_finalize_reading_without_solver_leaves_deck_unsolved(client):
    # ROKID_SOLVER unset: the onboard AI is the solver (primary path); the
    # local placeholder must NOT fill the deck with junk "solved" rows.
    _sid, body = _finalized_session(client)
    assert body["server_solved"] == 0
    assert all(p["solved"] is False for p in body["problems"])


def test_finalize_reading_server_solves_with_configured_solver(client, monkeypatch):
    _use_recording_solver(monkeypatch)
    doc_id = _doc_with_text_pages(
        client,
        [
            "第1問 長文: メロスは激怒した。必ずかの邪智暴虐の王を除かねばならぬ。",
            "問1 前ページの本文の主題を、続きを踏まえて答えよ。",
        ],
    )
    sid = _new_doc_exam(client, doc_id)["session_id"]
    r = client.post(f"/v1/exam-sessions/{sid}/finalize-reading")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["server_solved"] == body["problem_count"] == 2
    assert all(p["solved"] for p in body["problems"])
    # Every problem was solved with the WHOLE document as context.
    for q in _RecordingSolver.seen:
        assert "【P01" in q.context and "【P02" in q.context


def test_finalize_reading_solve_all_folds_in_listening_transcript(client, monkeypatch):
    _use_recording_solver(monkeypatch)
    doc_id = _doc_with_text_pages(client, ["問1 What did the man buy?"])
    sid = _new_doc_exam(client, doc_id, exam_type="listening")["session_id"]
    client.post(
        f"/v1/exam-sessions/{sid}/audio",
        data={"transcript": "The man bought two apples."},
    )
    r = client.post(f"/v1/exam-sessions/{sid}/finalize-reading")
    assert r.status_code == 200
    assert r.json()["server_solved"] == 1
    assert "The man bought two apples." in _RecordingSolver.seen[0].context


def test_finalize_reading_synthesizes_id_for_boundaryless_document(client):
    # No 問N boundary anywhere -> single fallback problem. It must carry a
    # stable synthesized id so the onboard ingest can address it by name.
    sid, body = _finalized_session(client, texts=["境界のない本文だけの資料である"])
    assert body["problem_count"] == 1
    assert body["problems"][0]["problem_no"] == "全体"

    r = client.post(
        f"/v1/exam-sessions/{sid}/solutions",
        json={"solutions": [{"problem_no": "全体", "answer": "要旨は…"}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["created_problems"] == 0  # matched, no duplicate row
    assert r.json()["problem_count"] == 1
    view = client.get(f"/v1/exam-sessions/{sid}/review").json()
    assert view["solved"] is True
    assert any("要旨は…" in ln for ln in view["glasses_view"]["lines"])


def test_finalize_reading_keyless_cloud_solver_leaves_deck_unsolved(client, monkeypatch):
    # ROKID_SOLVER=openai with no key: solve_with_fallback lands on the local
    # placeholder — that junk must NOT be stored as "solved" (it would shadow
    # the onboard ingest with (要モデル接続) answers).
    from app.solvers.claude import LLMSolver
    from app.solvers.registry import register_solver

    # Restore a pristine (client-less) adapter: other test modules may have
    # replaced the registry entry with a fake-client instance.
    register_solver(LLMSolver(name="openai", provider="openai"), replace=True)
    monkeypatch.setenv("ROKID_SOLVER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    doc_id = _doc_with_text_pages(client, _TWO_PROBLEM_PAGES)
    sid = _new_doc_exam(client, doc_id)["session_id"]
    r = client.post(f"/v1/exam-sessions/{sid}/finalize-reading")
    assert r.status_code == 200, r.text
    assert r.json()["server_solved"] == 0
    assert all(p["solved"] is False for p in r.json()["problems"])


def test_finalize_reading_resumes_unsolved_problems(client, monkeypatch):
    # First finalize without a solver (deck stays unsolved); configuring a
    # solver and double-tapping again must solve the REMAINING problems
    # instead of returning a dead already_finalized deck.
    sid, first = _finalized_session(client)
    assert first["server_solved"] == 0

    _use_recording_solver(monkeypatch)
    r = client.post(f"/v1/exam-sessions/{sid}/finalize-reading")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["already_finalized"] is True
    assert body["server_solved"] == body["problem_count"] == 2
    assert all(p["solved"] for p in body["problems"])
    # A further call has nothing left to solve (no duplicate solutions spam).
    again = client.post(f"/v1/exam-sessions/{sid}/finalize-reading").json()
    assert again["server_solved"] == 0


# --- phase 2: onboard ingest (primary path) ----------------------------------

def test_ingest_onboard_solutions(client):
    sid, _ = _finalized_session(client)
    r = client.post(
        f"/v1/exam-sessions/{sid}/solutions",
        json={
            "solutions": [
                {"problem_no": "問1", "answer": "3個", "solution_steps": ["数える"],
                 "rationale": "本文より", "answer_confidence": 0.8},
                {"problem_no": "問2", "answer": "5個"},
            ]
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ingested"] == 2
    assert body["created_problems"] == 0
    assert body["solved_count"] == body["problem_count"] == 2
    assert len(body["ingest_ack"]["lines"]) <= 3

    deck = client.get(f"/v1/exam-sessions/{sid}/solutions").json()
    assert deck["status"] == "reviewing"
    assert deck["solved_count"] == 2
    assert all(d["served_by"] == "onboard" for d in deck["deck"])


def test_ingest_before_finalize_reading_is_409(client):
    doc_id = _doc_with_text_pages(client, _TWO_PROBLEM_PAGES)
    sid = _new_doc_exam(client, doc_id)["session_id"]
    r = client.post(
        f"/v1/exam-sessions/{sid}/solutions",
        json={"solutions": [{"problem_no": "問1", "answer": "3個"}]},
    )
    assert r.status_code == 409


def test_ingest_unknown_problem_no_appends_to_deck(client):
    # The heuristic missed a problem but the onboard AI found it.
    sid, _ = _finalized_session(client)
    r = client.post(
        f"/v1/exam-sessions/{sid}/solutions",
        json={"solutions": [{"problem_no": "問3", "answer": "x=2", "page_number": 2}]},
    )
    assert r.status_code == 200
    assert r.json()["created_problems"] == 1
    deck = client.get(f"/v1/exam-sessions/{sid}/solutions").json()["deck"]
    assert [d["problem_no"] for d in deck] == ["問1", "問2", "問3"]
    assert deck[2]["solved"] is True


def test_ingest_duplicate_problem_no_latest_wins(client):
    sid, _ = _finalized_session(client)
    for answer in ("最初の答え", "訂正後の答え"):
        r = client.post(
            f"/v1/exam-sessions/{sid}/solutions",
            json={"solutions": [{"problem_no": "問1", "answer": answer}]},
        )
        assert r.status_code == 200
    # The deck did not grow; review shows the newest answer.
    assert client.get(f"/v1/exam-sessions/{sid}/solutions").json()["problem_count"] == 2
    view = client.get(f"/v1/exam-sessions/{sid}/review", params={"index": 0}).json()
    lines = view["glasses_view"]["lines"]
    assert any("訂正後の答え" in ln for ln in lines)


def test_ingest_by_problem_index_resolves_duplicate_numbers(client):
    # 問1 appears under two 大問; the server deck disambiguates as 問1/問1(2),
    # which the onboard AI cannot know — problem_index addresses them exactly.
    sid, body = _finalized_session(
        client, texts=["大問1 前半\n問1 一つ目", "大問2 後半\n問1 二つ目"]
    )
    nos = [p["problem_no"] for p in body["problems"]]
    assert nos == ["大問1", "問1", "大問2", "問1(2)"]

    r = client.post(
        f"/v1/exam-sessions/{sid}/solutions",
        json={
            "solutions": [
                {"problem_no": "問1", "problem_index": 1, "answer": "答えA"},
                {"problem_no": "問1", "problem_index": 3, "answer": "答えB"},
            ]
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["created_problems"] == 0
    v1 = client.get(f"/v1/exam-sessions/{sid}/review", params={"index": 1}).json()
    v3 = client.get(f"/v1/exam-sessions/{sid}/review", params={"index": 3}).json()
    assert any("答えA" in ln for ln in v1["glasses_view"]["lines"])
    assert any("答えB" in ln for ln in v3["glasses_view"]["lines"])
    # Out-of-range index is rejected before anything is stored.
    bad = client.post(
        f"/v1/exam-sessions/{sid}/solutions",
        json={"solutions": [{"problem_no": "x", "problem_index": 99, "answer": "y"}]},
    )
    assert bad.status_code == 400


def test_compat_paths_do_not_pollute_review_deck(client):
    # After finalize-reading, using the compat solve-current path must not
    # append its per-page question rows to the review deck.
    sid, body = _finalized_session(client)
    assert body["problem_count"] == 2
    assert client.post(f"/v1/exam-sessions/{sid}/solve-current").status_code == 200

    deck = client.get(f"/v1/exam-sessions/{sid}/solutions").json()
    assert deck["problem_count"] == 2
    assert [d["problem_no"] for d in deck["deck"]] == ["問1", "問2"]
    view = client.get(f"/v1/exam-sessions/{sid}/review", params={"index": 1}).json()
    assert view["problem_no"] == "問2"
    # get_exam_session: deck-scoped counts, but the compat row still appears
    # in the full questions listing.
    s = client.get(f"/v1/exam-sessions/{sid}").json()
    assert s["problem_count"] == 2
    assert len(s["questions"]) == 3


def test_ingest_rejects_empty_payload_and_blank_answer(client):
    sid, _ = _finalized_session(client)
    assert (
        client.post(f"/v1/exam-sessions/{sid}/solutions", json={"solutions": []})
        .status_code
        == 400
    )
    r = client.post(
        f"/v1/exam-sessions/{sid}/solutions",
        json={"solutions": [{"problem_no": "問1", "answer": "  "}]},
    )
    assert r.status_code == 400
    # All-or-nothing: nothing was stored.
    assert client.get(f"/v1/exam-sessions/{sid}/solutions").json()["solved_count"] == 0


def test_scan_ack_without_total_pages_never_claims_completion(client):
    # The completion signal gates the whole 3-phase flow: with no declared
    # total it must not tell the user to finish after the very first page.
    r = client.post("/v1/documents", json={"title": "模試"})
    doc_id = r.json()["document_id"]
    ack = client.post(
        f"/v1/documents/{doc_id}/pages", json={"page_index": 0, "ocr_text": "問1 a"}
    ).json()["scan_ack"]
    assert ack["all_scanned"] is False
    assert ack["total_pages"] is None
    assert "完了: ダブルタップ" not in ack["lines"]
    # An understated total is corrected upward (no 2/1ページ完了).
    ack2 = client.post(
        f"/v1/documents/{doc_id}/pages",
        json={"page_index": 1, "ocr_text": "問2 b", "total_pages": 1},
    ).json()["scan_ack"]
    assert ack2["total_pages"] == 2
    # Negative page_index is rejected.
    bad = client.post(
        f"/v1/documents/{doc_id}/pages", json={"page_index": -1, "ocr_text": "x"}
    )
    assert bad.status_code == 400


def test_ingest_confidence_is_clamped(client):
    sid, _ = _finalized_session(client)
    client.post(
        f"/v1/exam-sessions/{sid}/solutions",
        json={
            "solutions": [
                {"problem_no": "問1", "answer": "a", "answer_confidence": 80.0},
                {"problem_no": "問2", "answer": "b", "answer_confidence": -1.0},
            ]
        },
    )
    deck = client.get(f"/v1/exam-sessions/{sid}/solutions").json()["deck"]
    assert deck[0]["answer_confidence"] == 1.0
    assert deck[1]["answer_confidence"] == 0.0


def test_image_only_page_is_rejected_before_finalize(client):
    r = client.post("/v1/documents", json={"title": "模試"})
    doc_id = r.json()["document_id"]
    files = {"image": ("p.png", image_bytes(make_image(seed=7)), "image/png")}
    response = client.post(
        f"/v1/documents/{doc_id}/pages", data={"page_index": 0}, files=files
    )
    assert response.status_code == 415
    assert client.post(f"/v1/documents/{doc_id}/finalize").status_code == 400


def test_visual_upload_is_rejected_before_bytes_are_read(client):
    r = client.post("/v1/documents", json={"title": "模試"})
    doc_id = r.json()["document_id"]
    files = {"image": ("p.png", image_bytes(make_image(seed=3)), "image/png")}
    resp = client.post(
        f"/v1/documents/{doc_id}/pages", data={"page_index": 0}, files=files
    )
    assert resp.status_code == 415


# --- phase 3: review deck -----------------------------------------------------

def test_deck_listing_during_reading_is_empty_not_error(client):
    doc_id = _doc_with_text_pages(client, _TWO_PROBLEM_PAGES)
    sid = _new_doc_exam(client, doc_id)["session_id"]
    r = client.get(f"/v1/exam-sessions/{sid}/solutions")
    assert r.status_code == 200
    assert r.json()["status"] == "reading"
    assert r.json()["deck"] == []


def test_review_merged_stream_and_pagination(client):
    sid, _ = _finalized_session(client)
    steps = [f"手順{i}。" for i in range(8)]
    client.post(
        f"/v1/exam-sessions/{sid}/solutions",
        json={
            "solutions": [
                {"problem_no": "問1", "answer": "3個", "solution_steps": steps,
                 "rationale": "本文より。", "cautions": "単位に注意。"}
            ]
        },
    )
    r = client.get(f"/v1/exam-sessions/{sid}/review", params={"index": 0})
    assert r.status_code == 200
    gv = r.json()["glasses_view"]
    assert gv["kind"] == "review"
    assert "問1 1/2" in gv["lines"][0]
    assert gv["total_view_pages"] > 1  # long stream paginates
    # Collect the whole stream: one merged flow, no stage cycling.
    lines = []
    for vp in range(gv["total_view_pages"]):
        page = client.get(
            f"/v1/exam-sessions/{sid}/review", params={"index": 0, "view_page": vp}
        ).json()["glasses_view"]
        assert len(page["lines"]) <= 3
        lines += page["lines"]
    joined = "\n".join(lines)
    for part in ("答え: 3個", "解法", "根拠", "注意"):
        assert part in joined
    # index/view_page clamp instead of erroring.
    over = client.get(
        f"/v1/exam-sessions/{sid}/review", params={"index": 99, "view_page": 99}
    )
    assert over.status_code == 200
    assert over.json()["index"] == 1
    # Problem navigation edges.
    first = client.get(f"/v1/exam-sessions/{sid}/review", params={"index": 0}).json()
    assert first["glasses_view"]["nav"]["prev_problem"] is None
    assert first["glasses_view"]["nav"]["next_problem"] == 1


def test_review_unsolved_problem_shows_placeholder(client):
    sid, _ = _finalized_session(client)
    r = client.get(f"/v1/exam-sessions/{sid}/review", params={"index": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["solved"] is False
    assert "未解答" in body["glasses_view"]["lines"]


def test_review_before_finalize_reading_is_409(client):
    doc_id = _doc_with_text_pages(client, _TWO_PROBLEM_PAGES)
    sid = _new_doc_exam(client, doc_id)["session_id"]
    assert client.get(f"/v1/exam-sessions/{sid}/review").status_code == 409


# --- mode=real lock ------------------------------------------------------------

def test_real_mode_locks_ingest_deck_and_review(client):
    sid, body = _finalized_session(client, mode="real")
    # finalize still transitions (reveals nothing) but reports the lock.
    assert body["status"] == "reviewing"
    assert body["locked"] is True

    r = client.post(
        f"/v1/exam-sessions/{sid}/solutions",
        json={"solutions": [{"problem_no": "問1", "answer": "3個"}]},
    )
    assert r.status_code == 200
    assert r.json()["locked"] is True
    assert r.json()["ingested"] == 0

    deck = client.get(f"/v1/exam-sessions/{sid}/solutions").json()
    assert deck["locked"] is True
    assert deck["deck"] == []
    assert deck["glasses_view"]["locked"] is True

    view = client.get(f"/v1/exam-sessions/{sid}/review").json()
    assert view["locked"] is True
    assert all("3個" not in ln for ln in view["glasses_view"]["lines"])


def test_real_mode_finalize_skips_server_solve(client, monkeypatch):
    _use_recording_solver(monkeypatch)
    _sid, body = _finalized_session(client, mode="real")
    assert body["server_solved"] == 0
    assert _RecordingSolver.seen == []


# --- regression: compat path stays usable --------------------------------------

def test_solve_current_still_works_after_finalize_reading(client):
    sid, _ = _finalized_session(client)
    r = client.post(f"/v1/exam-sessions/{sid}/solve-current")
    assert r.status_code == 200
    assert r.json()["locked"] is False
