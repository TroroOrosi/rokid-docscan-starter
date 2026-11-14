"""The official Codex CLI as a booklet solver: one `codex exec` request carries every page image.

Measured on the phone on 2026-11-14 (docs/hardware-measurements.md, M-21). These tests run a real child process:
a stand-in `codex` written in Python that checks what it is given and writes the reply file, as the CLI does.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from PIL import Image

from app import config
from app.solvers import codex_cli
from app.solvers.base import Question
from app.solvers.chatgpt_web import (ChatGptWebAuthenticationRequired, ChatGptWebError, ChatGptWebRateLimit,
                                     ChatGptWebSendNotAuthorized)

FAKE_CODEX = r'''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
record = Path(os.environ["FAKE_CODEX_RECORD"])
calls = json.loads(record.read_text(encoding="utf-8")) if record.exists() else []
calls.append({"args": args, "proxy": os.environ.get("HTTPS_PROXY"), "cert": os.environ.get("SSL_CERT_FILE"),
              "stdin": sys.stdin.read(), "files": sorted(os.listdir("."))})
record.write_text(json.dumps(calls), encoding="utf-8")
if args[:2] == ["login", "status"]:
    print(os.environ.get("FAKE_CODEX_LOGIN", "Logged in using ChatGPT"))
    sys.exit(0)
assert args[0] == "exec", args
from PIL import Image
sizes = {}
for index, value in enumerate(args):
    if value == "-i":
        assert open(args[index + 1], "rb").read(2) == b"\xff\xd8", "every attached page must be a JPEG"
        sizes[args[index + 1]] = Image.open(args[index + 1]).size
calls[-1]["sizes"] = sizes
record.write_text(json.dumps(calls), encoding="utf-8")
locating = any(name.startswith("photo") for name in sizes)
if locating and os.environ.get("FAKE_CODEX_LOCATE_FAIL"):
    sys.stderr.write(os.environ["FAKE_CODEX_LOCATE_FAIL"])
    sys.exit(1)
if locating:
    Path(args[args.index("-o") + 1]).write_text(os.environ.get("FAKE_CODEX_REGIONS", '{"images": []}'), encoding="utf-8")
    sys.exit(0)
if os.environ.get("FAKE_CODEX_FAIL"):
    sys.stderr.write(os.environ["FAKE_CODEX_FAIL"])
    sys.exit(1)
if "canary.jpg" in sizes:
    picture = Image.open("canary.jpg").convert("L")
    dark = [picture.getpixel((x, picture.height // 2)) < 128 for x in range(picture.width)]
    count = sum(1 for x in range(len(dark)) if dark[x] and not (x and dark[x - 1]))
    Path(args[args.index("-o") + 1]).write_text(os.environ.get("FAKE_CODEX_CANARY_REPLY", str(count)), encoding="utf-8")
    sys.exit(0)
Path(args[args.index("-o") + 1]).write_text(os.environ["FAKE_CODEX_REPLY"], encoding="utf-8")
print("tokens used\n12,345")
'''

REPLY = {"questions": [
    {"group": "第1問", "label": "問1", "answer_no": [1], "pages": [1], "status": "ready", "answer": "④",
     "missing_material": "", "diagrams": []},
    {"group": "第1問", "label": "問2", "answer_no": [2], "pages": [2], "status": "needs_input", "answer": "",
     "missing_material": "本文の頁が無い", "diagrams": []}]}


@pytest.fixture
def codex(tmp_path, monkeypatch):
    """A stand-in CLI on disk, the solver pointed at it, sending on, and a data directory of its own."""
    fake = tmp_path / "fake_codex.py"
    fake.write_text(FAKE_CODEX, encoding="utf-8")
    record = tmp_path / "calls.json"
    monkeypatch.setattr(codex_cli, "_command", lambda: [sys.executable, str(fake)])
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setenv("FAKE_CODEX_RECORD", str(record))
    monkeypatch.setenv("FAKE_CODEX_REPLY", json.dumps(REPLY, ensure_ascii=False))
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    for name in ("FAKE_CODEX_FAIL", "FAKE_CODEX_LOGIN", "FAKE_CODEX_REGIONS", "FAKE_CODEX_LOCATE_FAIL",
                 "FAKE_CODEX_CANARY_REPLY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(codex_cli, "_needs_proxy", lambda: False)
    return lambda: json.loads(record.read_text(encoding="utf-8")) if record.exists() else []


def _booklet(tmp_path, pages=2, **fields) -> Question:
    rows = []
    for number in range(1, pages + 1):
        path = tmp_path / f"page-{number}.png"
        Image.new("RGB", (300, 420), (200, 200, 190 + number)).save(path)
        rows.append({"page_number": number, "image_path": str(path)})
    return Question(question_no=None, chat_key="session:7", document_pages=rows, document_id="3", **fields)


def _runs(calls):
    """The requests that ask for answers (not the one that asks where the pages are)."""
    return [call for call in calls if call["args"][:1] == ["exec"] and not _locating(call)]


def _locating(call):
    return call["args"][:1] == ["exec"] and any(name.startswith("photo") for name in call.get("sizes", {}))


def _locates(calls):
    return [call for call in calls if _locating(call)]


def test_a_booklet_is_one_exec_request_with_every_page_and_its_reply_becomes_the_answers(codex, tmp_path):
    replies = codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path, pages=3))

    [run] = _runs(codex())
    args = run["args"]
    assert [args[i + 1] for i, a in enumerate(args) if a == "-i"] == ["page001.jpg", "page002.jpg", "page003.jpg"]
    assert args[args.index("-m") + 1] == "gpt-6.1-sol" and "model_reasoning_effort=xhigh" in args
    assert args[args.index("-s") + 1] == "read-only" and "--skip-git-repo-check" in args and "--ephemeral" in args
    assert "Answer EVERY question in the attached booklet" in args[-1] and "page001.jpg is capture page 1" in args[-1]
    # Phone, 2026-11-14: a CLI started from a piped script read the rest of the script as its input.
    assert run["stdin"] == ""
    assert [(item["label"], result.answer, result.extras["answer_status"]) for item, result in replies] == [
        ("問1", "④", "ready"), ("問2", "", "needs_input")]
    assert replies[0][1].extras["source"] == "codex-cli" and replies[0][1].extras["model"] == "gpt-6.1-sol"


def test_the_reply_is_kept_so_the_same_booklet_is_not_paid_for_twice(codex, tmp_path):
    question = _booklet(tmp_path)
    first = codex_cli.CodexCliSolver().answer_all(question=question)
    again = codex_cli.CodexCliSolver().answer_all(question=question)

    assert len(_runs(codex())) == 1
    assert [result.answer for _, result in again] == [result.answer for _, result in first]


def test_a_changed_page_is_a_different_booklet_and_runs_again(codex, tmp_path):
    question = _booklet(tmp_path)
    codex_cli.CodexCliSolver().answer_all(question=question)
    Image.new("RGB", (300, 420), (10, 10, 10)).save(question.document_pages[0]["image_path"])
    codex_cli.CodexCliSolver().answer_all(question=question)

    assert len(_runs(codex())) == 2


def test_nothing_runs_while_sending_is_disabled(codex, tmp_path, monkeypatch):
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "0")
    with pytest.raises(ChatGptWebSendNotAuthorized):
        codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))
    assert not _runs(codex())


def test_a_usage_limit_is_a_rate_limit_so_the_booklet_moves_to_the_next_route(codex, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_FAIL", "ERROR: You've hit your usage limit. Try again in 3 hours.")
    with pytest.raises(ChatGptWebRateLimit):
        codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))


def test_a_run_that_fails_for_another_reason_is_a_send_that_did_not_happen(codex, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_FAIL", "error sending request for url (https://chatgpt.com/backend-api/codex/responses)")
    with pytest.raises(ChatGptWebError) as raised:
        codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))
    assert type(raised.value) is ChatGptWebError, "the bare class is what the server retries and moves to another route"
    assert "error sending request" in str(raised.value), "the CLI's own last line is the only record of the cause"


def test_not_signed_in_is_unready_and_an_authentication_failure(codex, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_LOGIN", "Not logged in")
    solver = codex_cli.CodexCliSolver()
    assert not solver.ready()
    with pytest.raises(ChatGptWebAuthenticationRequired):
        solver.answer_all(question=_booklet(tmp_path))
    assert not _runs(codex())


def test_it_is_ready_when_the_cli_is_there_and_signed_in(codex):
    assert codex_cli.CodexCliSolver().ready()


def test_a_missing_cli_is_unready(monkeypatch):
    monkeypatch.setattr(codex_cli, "_command", lambda: [])
    assert not codex_cli.CodexCliSolver().ready()


@pytest.mark.parametrize("fields", [{"audio_path": "listening.mp3"}, {"booklet_stage": "reading"},
                                     {"booklet_stage": "listening"}])
def test_a_booklet_that_needs_audio_is_refused_before_anything_runs(codex, tmp_path, fields):
    """The CLI takes images only. The bare error lets the server hand the booklet to a route that takes audio."""
    with pytest.raises(ChatGptWebError) as raised:
        codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path, **fields))
    assert type(raised.value) is ChatGptWebError
    assert not _runs(codex())


def test_a_reply_that_is_not_the_question_list_is_not_kept(codex, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_REPLY", "I could not read the pages.")
    question = _booklet(tmp_path)
    with pytest.raises(ValueError):
        codex_cli.CodexCliSolver().answer_all(question=question)
    monkeypatch.setenv("FAKE_CODEX_REPLY", json.dumps(REPLY, ensure_ascii=False))
    assert codex_cli.CodexCliSolver().answer_all(question=question)
    assert len(_runs(codex())) == 2


def test_it_answers_whole_booklets_only():
    with pytest.raises(ValueError):
        codex_cli.CodexCliSolver().solve(question=Question(question_id="q"))


def test_on_a_host_that_cannot_resolve_names_the_cli_is_given_the_loopback_proxy(codex, tmp_path, monkeypatch):
    """Phone, 2026-11-14: Android has no /etc/resolv.conf and the static binary failed every request until
    HTTPS_PROXY pointed at a proxy that resolves names for it."""
    monkeypatch.setattr(codex_cli, "_needs_proxy", lambda: True)
    codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))

    [run] = _runs(codex())
    assert run["proxy"].startswith("http://127.0.0.1:")


def test_the_proxy_tunnels_port_443_by_name_and_refuses_anything_else(monkeypatch):
    upstream = socket.socket()
    upstream.bind(("127.0.0.1", 0))
    upstream.listen(1)
    seen = {}

    def echo():
        connection, _ = upstream.accept()
        seen["received"] = connection.recv(100)
        connection.sendall(b"pong")
        connection.close()

    threading.Thread(target=echo, daemon=True).start()
    asked = []

    def connect(address, timeout=None):
        asked.append(address)
        return socket.create_connection(("127.0.0.1", upstream.getsockname()[1]), timeout=timeout)

    monkeypatch.setattr(codex_cli, "_connect_upstream", connect)
    with codex_cli.name_resolving_proxy() as port:
        client = socket.create_connection(("127.0.0.1", port), timeout=5)
        client.sendall(b"CONNECT chatgpt.com:443 HTTP/1.1\r\nHost: chatgpt.com:443\r\n\r\n")
        assert client.recv(100).startswith(b"HTTP/1.1 200")
        client.sendall(b"ping")
        assert client.recv(100) == b"pong"
        client.close()
        for request in (b"CONNECT chatgpt.com:22 HTTP/1.1\r\n\r\n", b"GET http://chatgpt.com/ HTTP/1.1\r\n\r\n"):
            refused = socket.create_connection(("127.0.0.1", port), timeout=5)
            refused.sendall(request)
            assert refused.recv(100).startswith(b"HTTP/1.1 4")
            refused.close()
    assert asked == [("chatgpt.com", 443)] and seen["received"] == b"ping"


FLOW = r'''
import io, json, os, sys, time
from pathlib import Path
from fastapi.testclient import TestClient
from PIL import Image
from app import main
from app.solvers import codex_cli

codex_cli._command = lambda: [sys.executable, os.environ["FAKE_CODEX_SCRIPT"]]
codex_cli._needs_proxy = lambda: False
auth = {"Authorization": "Bearer route-key"}
out = {"routes": main._booklet_routes()}
with TestClient(main.app) as client:
    out["solver"] = client.get("/v1/settings").json()["providers"]["solver"]
    doc = client.post("/v1/documents", json={"title": "route"}, headers=auth).json()["document_id"]
    for index in range(2):
        buffer = io.BytesIO()
        Image.new("RGB", (640, 480), (40 * index + 30, 90, 120)).save(buffer, "JPEG")
        page = client.post(f"/v1/documents/{doc}/pages", headers=auth, data={"page_index": str(index), "image_rotation": "0"},
                           files={"image": (f"page-{index + 1}.jpg", buffer.getvalue(), "image/jpeg")})
        assert page.status_code in (200, 201), page.text
    assert client.post(f"/v1/documents/{doc}/finalize", headers=auth).status_code in (200, 201)
    sid = client.post("/v1/exam-sessions", headers=auth, json={
        "mode": "study", "document_id": doc, "exam_type": "written", "answer_format": "mark"}).json()["session_id"]
    client.post(f"/v1/exam-sessions/{sid}/finalize-reading?solve=background", headers=auth)
    deadline, bundle = time.time() + float(os.environ.get("FLOW_WAIT_S", "40")), None
    while time.time() < deadline:
        bundle = client.get(f"/v1/exam-sessions/{sid}/answer-bundle", headers=auth)
        if bundle.status_code == 200 and all(item["status"] != "pending" for item in bundle.json()["items"]):
            break
        time.sleep(0.3)
    out["bundle"] = bundle.status_code
    out["items"] = [(item["status"], item["answer"]) for item in bundle.json()["items"]] if bundle.status_code == 200 else []
record = Path(os.environ["FAKE_CODEX_RECORD"])
out["exec_runs"] = sum(call["args"][:1] == ["exec"] for call in json.loads(record.read_text(encoding="utf-8"))) if record.exists() else 0
print("RESULT " + json.dumps(out, ensure_ascii=False))
'''


def test_the_server_half_of_the_route_runs_from_pages_to_the_answer_bundle(tmp_path):
    """With ROKID_SOLVER=codex-cli in real mode, and Chat behind it for a limit, as the phone will run it."""
    fake = tmp_path / "fake_codex.py"
    fake.write_text(FAKE_CODEX, encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    environment = dict(os.environ, ROKID_DATA_DIR=str(data), ROKID_API_KEY="route-key", ROKID_REAL_MODE="1",
                       ROKID_ANALYZER="client-ocr", ROKID_SOLVER="codex-cli", ROKID_CHATGPT_SEND_ENABLED="1",
                       ROKID_CAPTURE_INSPECTION="0", PYTHONIOENCODING="utf-8", FAKE_CODEX_SCRIPT=str(fake),
                       FAKE_CODEX_RECORD=str(tmp_path / "calls.json"), FAKE_CODEX_REPLY=json.dumps(REPLY, ensure_ascii=False))
    environment.pop("ROKID_SOLVER_FALLBACKS", None)
    done = subprocess.run([sys.executable, "-X", "utf8", "-c", FLOW], capture_output=True, text=True, encoding="utf-8",
                          env=environment, cwd=Path(__file__).resolve().parents[1], timeout=180)
    lines = [line for line in done.stdout.splitlines() if line.startswith("RESULT ")]
    assert lines, done.stderr[-2500:]
    result = json.loads(lines[-1][7:])
    assert result["routes"] == ["codex-cli", "chatgpt-web"]
    assert result["solver"]["name"] == "codex-cli" and result["solver"]["ready"] is True
    assert result["bundle"] == 200
    assert result["items"] == [["ready", "④"], ["needs_input", ""]]


def test_with_sending_off_the_route_reports_it_and_runs_nothing(tmp_path):
    """The gate every route that spends the operator's subscription waits for (ROKID_CHATGPT_SEND_ENABLED)."""
    fake = tmp_path / "fake_codex.py"
    fake.write_text(FAKE_CODEX, encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    environment = dict(os.environ, ROKID_DATA_DIR=str(data), ROKID_API_KEY="route-key", ROKID_REAL_MODE="1",
                       ROKID_ANALYZER="client-ocr", ROKID_SOLVER="codex-cli", ROKID_CHATGPT_SEND_ENABLED="0",
                       ROKID_CAPTURE_INSPECTION="0", PYTHONIOENCODING="utf-8", FAKE_CODEX_SCRIPT=str(fake), FLOW_WAIT_S="4",
                       FAKE_CODEX_RECORD=str(tmp_path / "calls.json"), FAKE_CODEX_REPLY=json.dumps(REPLY, ensure_ascii=False))
    done = subprocess.run([sys.executable, "-X", "utf8", "-c", FLOW], capture_output=True, text=True, encoding="utf-8",
                          env=environment, cwd=Path(__file__).resolve().parents[1], timeout=180)
    lines = [line for line in done.stdout.splitlines() if line.startswith("RESULT ")]
    assert lines, done.stderr[-2500:]
    result = json.loads(lines[-1][7:])
    assert result["solver"]["ready"] is False and result["solver"]["code"] == "send_not_authorized"
    assert result["exec_runs"] == 0
    assert all(status == "pending" for status, _ in result["items"]), result


REGIONS = {"images": [{"index": 1, "pages": [{"left": 520, "top": 250, "right": 900, "bottom": 750},
                                             {"left": 100, "top": 250, "right": 480, "bottom": 750}]}]}


def _photo(tmp_path, size=(1500, 2000)) -> Question:
    path = tmp_path / "photo.png"
    Image.new("RGB", size, (190, 190, 185)).save(path)
    return Question(question_no=None, chat_key="session:9", document_pages=[{"page_number": 1, "image_path": str(path)}],
                    document_id="5")


def test_the_pages_are_located_first_from_a_small_view_of_each_photo(codex, tmp_path, monkeypatch):
    """Phone, 2026-11-15, all 27 real photos: the model returned every page's box, dark or bright desk, in 37 s at low
    effort; brightness and text-density rules each failed on some background."""
    monkeypatch.setenv("FAKE_CODEX_REGIONS", json.dumps(REGIONS))
    codex_cli.CodexCliSolver().answer_all(question=_photo(tmp_path))

    [locate] = _locates(codex())
    args = locate["args"]
    assert list(locate["sizes"]) == ["photo001.jpg"] and max(locate["sizes"]["photo001.jpg"]) == 1024
    assert "model_reasoning_effort=low" in args and "--output-schema" in args
    assert "thousandths" in args[-1]


def test_each_located_page_is_sent_enlarged_right_page_first_and_inside_the_model_side_budget(codex, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_REGIONS", json.dumps(REGIONS))
    codex_cli.CodexCliSolver().answer_all(question=_photo(tmp_path))

    [run] = _runs(codex())
    names = [name for name in run["sizes"] if name.startswith("page")]
    assert names and all(name.startswith(("page001-1", "page001-2")) for name in names)
    assert names.index(next(n for n in names if n.startswith("page001-2"))) > names.index(next(n for n in names if n.startswith("page001-1")))
    # The first region is 570 px wide and 1000 px tall on the 1500x2000 photo, before its margin: enlarged about 2.3 times.
    first = [run["sizes"][name] for name in names if name.startswith("page001-1")]
    assert sum(height for _, height in first) >= 2400
    assert all(max(size) <= 2048 for size in run["sizes"].values())
    assert "page001-1a.jpg" in run["args"][-1] or "tile" in run["args"][-1]
    assert "overview001.jpg" in run["sizes"], "the whole photo goes along small, so nothing outside the boxes is lost unseen"


def test_a_photo_in_which_no_page_was_found_is_sent_as_before(codex, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_REGIONS", json.dumps({"images": [{"index": 1, "pages": []}]}))
    codex_cli.CodexCliSolver().answer_all(question=_photo(tmp_path))

    [run] = _runs(codex())
    assert "page001.jpg" in run["sizes"]


def test_when_locating_fails_the_booklet_is_still_sent_as_before(codex, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_LOCATE_FAIL", "error sending request for url (https://chatgpt.com/backend-api/codex/responses)")
    replies = codex_cli.CodexCliSolver().answer_all(question=_photo(tmp_path))

    [run] = _runs(codex())
    assert list(run["sizes"]) == ["page001.jpg"] and replies


def test_a_usage_limit_while_locating_is_a_rate_limit_and_nothing_more_runs(codex, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_LOCATE_FAIL", "ERROR: You've hit your usage limit.")
    with pytest.raises(ChatGptWebRateLimit):
        codex_cli.CodexCliSolver().answer_all(question=_photo(tmp_path))
    assert not _runs(codex())


@pytest.mark.parametrize("regions", [
    {"images": [{"index": 1, "pages": [{"left": 900, "top": 100, "right": 200, "bottom": 800}]}]},   # right of left
    {"images": [{"index": 1, "pages": [{"left": 100, "top": 100, "right": 110, "bottom": 105}]}]},   # a speck
    {"images": [{"index": 7, "pages": [{"left": 100, "top": 100, "right": 900, "bottom": 900}]}]},   # no such photo
    {"oops": True},
])
def test_boxes_that_make_no_sense_are_not_used(codex, tmp_path, monkeypatch, regions):
    monkeypatch.setenv("FAKE_CODEX_REGIONS", json.dumps(regions))
    codex_cli.CodexCliSolver().answer_all(question=_photo(tmp_path))

    [run] = _runs(codex())
    assert "page001.jpg" in run["sizes"]


def _checks(calls):
    return [call for call in calls if call["args"][:1] == ["exec"] and "canary.jpg" in call.get("sizes", {})]


def test_the_check_before_use_is_one_small_real_request_whose_reply_depends_on_the_picture(codex):
    """Phone, 2026-11-15 (M-23): five black squares counted in 5 s at low effort, 14,834 input tokens, 12,160 of them cached."""
    codex_cli.CodexCliSolver().check()

    assert codex_cli.CodexCliSolver.check_sends is True, "the proof is a real request, not a look at readiness"

    [check] = _checks(codex())
    args = check["args"]
    assert "model_reasoning_effort=low" in args and args[args.index("-s") + 1] == "read-only" and "--ephemeral" in args
    assert max(check["sizes"]["canary.jpg"]) <= 512 and check["stdin"] == ""
    assert not _runs([call for call in codex() if call not in _checks(codex())]), "no booklet request is made"


def test_the_check_fails_when_the_reply_is_not_what_the_picture_shows(codex, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_CANARY_REPLY", "9")  # the picture shows three to seven
    with pytest.raises(ChatGptWebError):
        codex_cli.CodexCliSolver().check()


def test_the_check_reports_a_usage_limit_as_a_usage_limit(codex, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_FAIL", "ERROR: You've hit your usage limit. Try again in 3 hours.")
    with pytest.raises(ChatGptWebRateLimit):
        codex_cli.CodexCliSolver().check()


def test_the_check_sends_nothing_when_the_cli_is_not_signed_in(codex, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_LOGIN", "Not logged in")
    with pytest.raises(ChatGptWebAuthenticationRequired):
        codex_cli.CodexCliSolver().check()
    assert not _checks(codex())


def test_the_check_sends_nothing_while_sending_is_disabled(codex, monkeypatch):
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "0")
    with pytest.raises(ChatGptWebSendNotAuthorized):
        codex_cli.CodexCliSolver().check()
    assert not codex()


def test_the_check_goes_through_the_loopback_proxy_where_names_do_not_resolve(codex, monkeypatch):
    monkeypatch.setattr(codex_cli, "_needs_proxy", lambda: True)
    codex_cli.CodexCliSolver().check()

    [check] = _checks(codex())
    assert check["proxy"].startswith("http://127.0.0.1:")
