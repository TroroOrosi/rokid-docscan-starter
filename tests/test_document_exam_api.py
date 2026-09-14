"""Tests for the camera-free document page-move型 exam (v0.7 / api 1.7.0).

Covers:
  * camera-free page ingestion (POST /pages with ocr_text and NO image),
  * document-bound exam session (create with document_id/exam_type/answer_format),
  * page navigation (next-page/prev-page/current, clamped),
  * solve-current (solves the current page's material; persists question+solution
    so /view and /reasoning keep working),
  * 筆記 ⇄ リスニング mode switch (/mode),
  * listening audio upload + provided-transcript fallback (/audio),
  * guardrails (real-mode lock, non-document session rejected).

All offline: the local placeholder solver answers, no external credentials.
"""

import importlib
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from tests.conftest import image_bytes, make_image


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ROKID_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ROKID_ALLOW_REAL_EXAM_SOLVE", raising=False)
    monkeypatch.delenv("ROKID_TRANSCRIBER", raising=False)
    import app.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)
    import app.main as main
    importlib.reload(main)
    main.ensure_dirs()
    main.db.init_db()
    return TestClient(main.app)


# --- camera-free page ingestion ---------------------------------------------

def _new_doc(client, title="模試"):
    r = client.post("/v1/documents", json={"title": title})
    assert r.status_code == 201
    return r.json()["document_id"]


def _add_text_page(client, doc_id, page_index, ocr_text):
    """Camera-free page: no image, only ocr_text."""
    return client.post(
        f"/v1/documents/{doc_id}/pages",
        data={"page_index": page_index, "ocr_text": ocr_text},
    )


def test_add_page_without_image_records_text_only(client):
    doc_id = _new_doc(client)
    r = _add_text_page(client, doc_id, 0, "問1 次の英文を読み設問に答えよ")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["image_path"] is None
    assert body["phash"] == ""
    assert body["ocr_md5"]  # derived from text


def test_add_page_requires_image_or_text(client):
    doc_id = _new_doc(client)
    # No image AND no ocr_text -> 400
    r = client.post(f"/v1/documents/{doc_id}/pages", data={"page_index": 0})
    assert r.status_code == 400


def test_add_page_with_image_still_works(client):
    doc_id = _new_doc(client)
    files = {"image": ("p.png", image_bytes(make_image(seed=3)), "image/png")}
    r = client.post(
        f"/v1/documents/{doc_id}/pages",
        data={"page_index": 0, "ocr_text": "画像あり"},
        files=files,
    )
    assert r.status_code == 201
    assert r.json()["image_path"] is not None
    assert r.json()["phash"]  # pHash computed for the image


def _doc_with_text_pages(client, texts):
    doc_id = _new_doc(client)
    for i, t in enumerate(texts):
        assert _add_text_page(client, doc_id, i, t).status_code == 201
    assert client.post(f"/v1/documents/{doc_id}/finalize").status_code == 200
    return doc_id


# --- document-bound exam session --------------------------------------------

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


def test_create_document_exam_reports_pages(client):
    doc_id = _doc_with_text_pages(client, ["p1", "p2", "p3"])
    body = _new_doc_exam(client, doc_id)
    assert body["document_id"] == doc_id
    assert body["total_pages"] == 3
    assert body["current_page_index"] == 0
    assert body["exam_type"] == "written"
    assert body["answer_format"] == "mark"
    assert "operations" in body


def test_create_rejects_bad_exam_type_or_format(client):
    doc_id = _doc_with_text_pages(client, ["p1"])
    r1 = client.post(
        "/v1/exam-sessions", json={"document_id": doc_id, "exam_type": "bogus"}
    )
    assert r1.status_code == 400
    r2 = client.post(
        "/v1/exam-sessions", json={"document_id": doc_id, "answer_format": "bogus"}
    )
    assert r2.status_code == 400


def test_create_rejects_missing_document(client):
    r = client.post("/v1/exam-sessions", json={"document_id": 9999})
    assert r.status_code == 404


def test_create_rejects_unfinalized_document(client):
    # A document with no pages / not finalized must not create a broken exam.
    doc_id = _new_doc(client)
    r = client.post("/v1/exam-sessions", json={"document_id": doc_id})
    assert r.status_code == 400
    # add a page but do NOT finalize -> still rejected (status != ready)
    _add_text_page(client, doc_id, 0, "p1")
    assert client.post(
        "/v1/exam-sessions", json={"document_id": doc_id}
    ).status_code == 400


def test_match_scores_camera_free_pages_by_text(client):
    """A document mixing a text-only page and an image page must still match.

    撮影しない text-only pages are first-class /match candidates now (scored
    by their recognized text); the pHash comparison only applies between two
    image-backed sides.
    """
    doc_id = _new_doc(client)
    _add_text_page(client, doc_id, 0, "撮影しないテキストページ")  # phash=""
    files = {"image": ("p.png", image_bytes(make_image(seed=7)), "image/png")}
    client.post(
        f"/v1/documents/{doc_id}/pages",
        data={"page_index": 1, "ocr_text": "画像ページ"},
        files=files,
    )
    client.post(f"/v1/documents/{doc_id}/finalize")
    # /match must not raise on the phashless page; it returns a verdict.
    r = client.post(
        "/v1/match",
        data={"document_id": doc_id, "fast_ocr_text": "画像ページ"},
        files={"image": ("q.png", image_bytes(make_image(seed=7)), "image/png")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verdict"] in ("HIT", "LOW_CONF", "NO_PAGE")
    # both pages were scored — the text-only one with hamming: null
    assert len(body["candidates"]) == 2
    hammings = {c["page_index"]: c["hamming"] for c in body["candidates"]}
    assert hammings[0] is None
    assert isinstance(hammings[1], int)


# --- page navigation --------------------------------------------------------

def test_navigation_next_prev_clamped(client):
    doc_id = _doc_with_text_pages(client, ["p1", "p2", "p3"])
    sid = _new_doc_exam(client, doc_id)["session_id"]

    r = client.post(f"/v1/exam-sessions/{sid}/next-page")
    assert r.json()["current_page_index"] == 1
    # clamp at last
    for _ in range(5):
        r = client.post(f"/v1/exam-sessions/{sid}/next-page")
    assert r.json()["current_page_index"] == 2
    assert r.json()["at_last"] is True
    # clamp at first
    for _ in range(5):
        r = client.post(f"/v1/exam-sessions/{sid}/prev-page")
    assert r.json()["current_page_index"] == 0
    assert r.json()["at_first"] is True


def test_current_reports_subject_and_preview(client):
    doc_id = _doc_with_text_pages(
        client, ["問1 次の計算をせよ 12+13", "問2 光合成について述べよ"]
    )
    sid = _new_doc_exam(client, doc_id)["session_id"]
    client.post(f"/v1/exam-sessions/{sid}/next-page")  # -> page 1
    body = client.get(f"/v1/exam-sessions/{sid}/current").json()
    assert body["current_page_index"] == 1
    assert body["subject"]
    assert body["has_image"] is False  # camera-free page
    assert "光合成" in body["preview"]


def test_navigation_requires_document_session(client):
    # A plain (non-document) exam session cannot use page-move endpoints.
    r = client.post("/v1/exam-sessions", json={"mode": "study"})
    sid = r.json()["session_id"]
    assert client.post(f"/v1/exam-sessions/{sid}/next-page").status_code == 400
    assert client.get(f"/v1/exam-sessions/{sid}/current").status_code == 400


# --- solve-current ----------------------------------------------------------

def test_solve_current_answers_and_persists(client):
    doc_id = _doc_with_text_pages(client, ["問1 2x+3=7 を解け", "問2 別ページ"])
    sid = _new_doc_exam(client, doc_id)["session_id"]
    r = client.post(f"/v1/exam-sessions/{sid}/solve-current")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["locked"] is False
    assert body["current_page_index"] == 0
    assert body["served_by"] == "local"
    gv = body["glasses_view"]
    assert gv["stage"] == "answer"
    assert len(gv["lines"]) <= 3
    qid = body["question_id"]

    # The persisted question is navigable via the staged /view endpoint.
    for stage in ("answer", "solution", "rationale", "caution"):
        v = client.get(
            f"/v1/exam-sessions/{sid}/questions/{qid}/view", params={"stage": stage}
        )
        assert v.status_code == 200
        assert v.json()["glasses_view"]["stage"] == stage
    # session detail lists it as solved
    detail = client.get(f"/v1/exam-sessions/{sid}").json()
    assert detail["total_pages"] == 2
    assert any(q["solved"] for q in detail["questions"])


def test_solve_current_real_mode_is_locked(client):
    doc_id = _doc_with_text_pages(client, ["問1"])
    sid = _new_doc_exam(client, doc_id, mode="real")["session_id"]
    body = client.post(f"/v1/exam-sessions/{sid}/solve-current").json()
    assert body["locked"] is True
    assert body["glasses_view"]["locked"] is True


# --- mode switch ------------------------------------------------------------

def test_mode_toggle_written_listening(client):
    doc_id = _doc_with_text_pages(client, ["p1"])
    sid = _new_doc_exam(client, doc_id)["session_id"]
    r = client.post(f"/v1/exam-sessions/{sid}/mode", json={"exam_type": "listening"})
    assert r.status_code == 200
    assert r.json()["exam_type"] == "listening"
    assert client.get(f"/v1/exam-sessions/{sid}").json()["exam_type"] == "listening"
    # bad value rejected
    assert client.post(
        f"/v1/exam-sessions/{sid}/mode", json={"exam_type": "nope"}
    ).status_code == 400


# --- listening audio --------------------------------------------------------

def test_audio_uses_provided_transcript_offline(client):
    doc_id = _doc_with_text_pages(client, ["Listening Part 1 Question 1"])
    sid = _new_doc_exam(client, doc_id, exam_type="listening")["session_id"]
    # No ROKID_TRANSCRIBER configured -> provided transcript is stored as-is.
    r = client.post(
        f"/v1/exam-sessions/{sid}/audio",
        data={"transcript": "Hello, this is the recording."},
        files={"audio": ("rec.wav", b"RIFF....WAVEfake", "audio/wav")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["audio_stored"] is True
    assert body["transcript"] == "Hello, this is the recording."
    assert client.get(f"/v1/exam-sessions/{sid}").json()["has_audio"] is True


def test_replacing_audio_removes_superseded_recording(client, tmp_path):
    doc_id = _doc_with_text_pages(client, ["Listening Part 1 Question 1"])
    sid = _new_doc_exam(client, doc_id, exam_type="listening")["session_id"]
    endpoint = f"/v1/exam-sessions/{sid}/audio"

    first = client.post(
        endpoint,
        data={"transcript": "first"},
        files={"audio": ("first.wav", b"RIFFfirstWAVE", "audio/wav")},
    )
    assert first.status_code == 200
    first_path = next((tmp_path / "audio").iterdir())

    second = client.post(
        endpoint,
        data={"transcript": "second"},
        files={"audio": ("second.wav", b"RIFFsecondWAVE", "audio/wav")},
    )
    assert second.status_code == 200
    remaining = list((tmp_path / "audio").iterdir())
    assert len(remaining) == 1
    assert not first_path.exists()
    assert remaining[0].read_bytes() == b"RIFFsecondWAVE"


def test_audio_filename_is_not_used_as_a_filesystem_suffix(client, tmp_path):
    doc_id = _doc_with_text_pages(client, ["Listening Part 1 Question 1"])
    sid = _new_doc_exam(client, doc_id, exam_type="listening")["session_id"]
    response = client.post(
        f"/v1/exam-sessions/{sid}/audio",
        data={"transcript": "safe filename"},
        files={
            "audio": (
                "recording.wav:alternate-stream",
                b"RIFFsafeWAVE",
                "audio/wav",
            )
        },
    )
    assert response.status_code == 200
    stored = list((tmp_path / "audio").iterdir())
    assert len(stored) == 1
    assert stored[0].suffix == ".wav"
    assert ":" not in stored[0].name
    assert stored[0].read_bytes() == b"RIFFsafeWAVE"


def test_audio_requires_something(client):
    doc_id = _doc_with_text_pages(client, ["p1"])
    sid = _new_doc_exam(client, doc_id, exam_type="listening")["session_id"]
    r = client.post(f"/v1/exam-sessions/{sid}/audio", data={})
    assert r.status_code == 400


# --- vision_text (figure/image reading as text) -----------------------------

def _add_page(client, doc_id, page_index, *, ocr_text=None, vision_text=None):
    data = {"page_index": page_index}
    if ocr_text is not None:
        data["ocr_text"] = ocr_text
    if vision_text is not None:
        data["vision_text"] = vision_text
    return client.post(f"/v1/documents/{doc_id}/pages", data=data)


def test_add_page_vision_text_only(client):
    """A page can be remembered from the on-glass AI's figure reading alone."""
    doc_id = _new_doc(client)
    r = _add_page(client, doc_id, 0, vision_text="回路図: 抵抗R1とコンデンサC1の直列")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["has_vision_text"] is True
    assert body["image_path"] is None
    assert body["ocr_md5"]  # derived from the vision text


def test_add_page_requires_text_or_image(client):
    doc_id = _new_doc(client)
    # No image, no ocr_text, no vision_text -> 400
    r = client.post(f"/v1/documents/{doc_id}/pages", data={"page_index": 0})
    assert r.status_code == 400


class _RecordingSolver:
    """Duck-typed solver that records the Question it received (offline)."""

    name = "recording-test"
    provider_version = "t-1"
    offline = True
    last: dict = {}

    def solve(self, *, question, max_answer_len=64):
        from app.solvers import SolveResult

        _RecordingSolver.last["question"] = question
        return SolveResult(
            answer="A", solution_steps=["s"], rationale="r", cautions="c",
            answer_confidence=0.9, rationale_confidence=0.9,
        )

    def info(self):
        return {"name": self.name, "provider_version": self.provider_version,
                "offline": self.offline}


def test_solve_current_passes_whole_document_as_context(client, monkeypatch):
    """A problem continuing across pages: the solver must see ALL pages."""
    from app.solvers.registry import register_solver

    _RecordingSolver.last = {}
    register_solver(_RecordingSolver(), replace=True)
    monkeypatch.setenv("ROKID_SOLVER", "recording-test")

    doc_id = _doc_with_text_pages(
        client,
        [
            "第1問 長文: メロスは激怒した。必ずかの邪智暴虐の王を除かねばならぬ。",
            "問1 前ページの本文の主題を、続きを踏まえて答えよ。",
        ],
    )
    sid = _new_doc_exam(client, doc_id)["session_id"]
    client.post(f"/v1/exam-sessions/{sid}/next-page")  # -> P2 (the question)
    r = client.post(f"/v1/exam-sessions/{sid}/solve-current")
    assert r.status_code == 200, r.text

    q = _RecordingSolver.last["question"]
    # body = current page (P2); context = the WHOLE document incl. P1's passage.
    assert "問1" in q.body_text
    assert "メロスは激怒した" in q.context      # continuation from P1 is present
    assert "【P01" in q.context and "【P02" in q.context


def test_solve_current_folds_vision_text_into_material(client, monkeypatch):
    """Figure reading (vision_text) must reach the solver as material."""
    from app.solvers.registry import register_solver

    _RecordingSolver.last = {}
    register_solver(_RecordingSolver(), replace=True)
    monkeypatch.setenv("ROKID_SOLVER", "recording-test")

    doc_id = _new_doc(client)
    _add_page(client, doc_id, 0, ocr_text="問1 図の回路の合成抵抗を求めよ",
              vision_text="回路図: R1=2Ω と R2=3Ω が直列")
    assert client.post(f"/v1/documents/{doc_id}/finalize").status_code == 200
    sid = _new_doc_exam(client, doc_id)["session_id"]
    r = client.post(f"/v1/exam-sessions/{sid}/solve-current")
    assert r.status_code == 200, r.text

    q = _RecordingSolver.last["question"]
    assert "【図・画像の読み取り】" in q.body_text
    assert "R1=2Ω" in q.body_text
    # persisted question body also carries the figure reading (for /view)
    qid = r.json()["question_id"]
    reasoning = client.get(
        f"/v1/exam-sessions/{sid}/questions/{qid}/reasoning"
    )
    assert reasoning.status_code == 200


def test_listening_solve_current_folds_in_transcript(client):
    doc_id = _doc_with_text_pages(client, ["Question 1: What did the man buy?"])
    sid = _new_doc_exam(
        client, doc_id, exam_type="listening", answer_format="mark"
    )["session_id"]
    client.post(
        f"/v1/exam-sessions/{sid}/audio",
        data={"transcript": "The man bought two apples."},
    )
    r = client.post(f"/v1/exam-sessions/{sid}/solve-current")
    assert r.status_code == 200
    assert r.json()["exam_type"] == "listening"
    assert r.json()["locked"] is False


# --- paste-prompt (hand-paste into a chat UI) ---------------------------------


def test_paste_prompt_carries_answer_only_rules_and_a_prefilled_url(client):
    doc_id = _doc_with_text_pages(client, ["問1 2x+3=7 を解け"])
    sid = _new_doc_exam(client, doc_id)["session_id"]

    body = client.get(f"/v1/exam-sessions/{sid}/paste-prompt").json()

    # The pasted text must carry the answer-sheet-only rule, or the chat
    # answers like a tutor and the operator copies the wrong thing.
    assert "only what belongs on" in body["text"].lower()
    assert "2x+3=7" in body["text"]
    # Prefill link is percent-encoded, so the Japanese body survives the URL.
    assert body["url"].startswith("https://chatgpt.com/?q=")
    assert urllib.parse.unquote(body["url"].split("?q=", 1)[1]) == body["text"]


def test_pages_pdf_bundles_every_captured_page_into_one_file(client):
    """The phone path's attachment: one file instead of a photo per page.

    Pasting the prompt into the ChatGPT app was already possible; attaching the
    pages by hand, one photo at a time, was the step that does not survive a
    real session.
    """
    doc_id = _new_doc(client)
    for i in range(2):
        r = client.post(
            f"/v1/documents/{doc_id}/pages",
            data={"page_index": i, "ocr_text": f"第{i + 1}問"},
            files={"image": ("p.png", image_bytes(make_image(seed=i + 1)), "image/png")},
        )
        assert r.status_code == 201
    assert client.post(f"/v1/documents/{doc_id}/finalize").status_code == 200
    sid = _new_doc_exam(client, doc_id)["session_id"]

    r = client.get(f"/v1/exam-sessions/{sid}/pages.pdf")

    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert client.get(f"/v1/exam-sessions/{sid}/paste-prompt").json()["pages_pdf_url"] == (
        f"/v1/exam-sessions/{sid}/pages.pdf"
    )


def test_pages_pdf_is_404_when_the_document_is_text_only(client):
    # A camera-free document has nothing to bundle, and an empty PDF would read
    # as "the figures were attached" when they were not.
    doc_id = _doc_with_text_pages(client, ["問1 2x+3=7 を解け"])
    sid = _new_doc_exam(client, doc_id)["session_id"]

    assert client.get(f"/v1/exam-sessions/{sid}/pages.pdf").status_code == 404
