"""The official Codex CLI as a booklet solver: one `codex exec` request carries every page image.

Measured on the phone on 2026-11-14 (docs/hardware-measurements.md, M-21). These tests run a real child process:
a stand-in `codex` written in Python that checks what it is given and writes the reply file, as the CLI does.
"""
from __future__ import annotations

import contextlib
import json
import math
import os
import select as select_module
import socket
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageDraw

from app import config
from app.solvers import codex_cli
from app.solvers.base import Question
from app.solvers.chatgpt_web import (ChatGptWebAuthenticationRequired, ChatGptWebCheckFailed, ChatGptWebError,
                                     ChatGptWebModelMismatch, ChatGptWebRateLimit, ChatGptWebReplyIncomplete,
                                     ChatGptWebSendNotAuthorized)

FAKE_CODEX = r'''
import atexit, json, os, sys, time
from pathlib import Path
args = sys.argv[1:]
call = {"args": args, "proxy": os.environ.get("HTTPS_PROXY"), "cert": os.environ.get("SSL_CERT_FILE"),
        "stdin": sys.stdin.read(), "files": sorted(os.listdir(".")), "started": time.time()}


def _record():
    # A file of its own for each call: two reads run at once, and appends to one file can interleave.
    call["ended"] = time.time()
    path = f'{os.environ["FAKE_CODEX_RECORD"]}.{os.getpid()}.{time.time_ns()}.json'
    with open(path + ".tmp", "w", encoding="utf-8") as record:
        record.write(json.dumps(call))
    os.replace(path + ".tmp", path)


atexit.register(_record)
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
call["sizes"] = sizes
if "--output-schema" in args:
    call["schema"] = json.loads(Path(args[args.index("--output-schema") + 1]).read_text(encoding="utf-8"))
output = Path(args[args.index("-o") + 1])
call["reply_file"] = output.name
second = output.name.startswith("reply-2")  # the second read, whole ("reply-2.json") or a part of it ("reply-2-1.json")
# What this one request does, by its reply file: {"reply-1-2.json": {"reply": ..., "fail": ..., "sleep": ...}}.
mine = json.loads(os.environ.get("FAKE_CODEX_PARTS") or "{}").get(output.name, {})
gone = json.loads(os.environ.get("FAKE_CODEX_FAIL_MODEL") or "{}")  # {"model": "...", "message": "..."}
if gone and args[args.index("-m") + 1] == gone["model"]:
    sys.stderr.write(gone["message"])
    sys.exit(1)
locating = any(name.startswith("photo") for name in sizes)
if any(name.startswith("capture") for name in sizes):  # the request that asks where the major problems begin
    if os.environ.get("FAKE_CODEX_OUTLINE_FAIL"):
        sys.stderr.write(os.environ["FAKE_CODEX_OUTLINE_FAIL"])
        sys.exit(1)
    time.sleep(float(os.environ.get("FAKE_CODEX_OUTLINE_SLEEP", "0")))
    output.write_text(os.environ.get("FAKE_CODEX_OUTLINE", '{"starts": []}'), encoding="utf-8")
    sys.exit(0)
if locating and os.environ.get("FAKE_CODEX_LOCATE_FAIL"):
    sys.stderr.write(os.environ["FAKE_CODEX_LOCATE_FAIL"])
    sys.exit(1)
if locating:
    time.sleep(float(os.environ.get("FAKE_CODEX_LOCATE_SLEEP", "0")))
    print("tokens used\n12,345")
    Path(args[args.index("-o") + 1]).write_text(os.environ.get("FAKE_CODEX_REGIONS", '{"images": []}'), encoding="utf-8")
    sys.exit(0)
first = json.loads(os.environ.get("FAKE_CODEX_FAIL_FIRST") or "{}")  # {"times": 2, "message": "..."}
refused = Path(os.environ["FAKE_CODEX_RECORD"] + ".refused")
if first and "canary.jpg" not in sizes and (refused.stat().st_size if refused.exists() else 0) < first["times"]:
    with open(refused, "ab") as marker:
        marker.write(b"x")
    sys.stderr.write(first["message"])
    sys.exit(1)
failure = mine.get("fail") or os.environ.get("FAKE_CODEX_FAIL") or (
    "canary.jpg" not in sizes and os.environ.get("FAKE_CODEX_FAIL_2" if second else "FAKE_CODEX_FAIL_1"))
if failure:
    sys.stdout.write(os.environ.get("FAKE_CODEX_STDOUT", ""))
    sys.stderr.write(failure)
    sys.exit(1)
if "canary.jpg" in sizes:
    if "--ephemeral" not in args and os.environ.get("FAKE_CODEX_ROLLOUT"):
        folder = Path(os.environ["CODEX_HOME"]) / "sessions" / "2026" / "11" / "16"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ("rollout-check-%d.jsonl" % os.getpid())).write_text(
            '{"type": "session_meta"}' + "\n" + os.environ["FAKE_CODEX_ROLLOUT"] + "\n", encoding="utf-8")
    picture = Image.open("canary.jpg").convert("L")
    dark = [picture.getpixel((x, picture.height // 2)) < 128 for x in range(picture.width)]
    count = sum(1 for x in range(len(dark)) if dark[x] and not (x and dark[x - 1]))
    Path(args[args.index("-o") + 1]).write_text(os.environ.get(
        "FAKE_CODEX_CANARY_REPLY", json.dumps({"squares": count}) if "--output-schema" in args else str(count)),
        encoding="utf-8")
    sys.exit(0)
time.sleep(float(mine.get("sleep") or second and os.environ.get("FAKE_CODEX_SLEEP_2") or os.environ.get("FAKE_CODEX_SLEEP", "0")))
if second and os.environ.get("FAKE_CODEX_BAD_BYTES_2"):
    output.write_bytes(b"\xff\xfe\x00 not UTF-8")
    sys.exit(0)
output.write_text(mine["reply"] if "reply" in mine
                  else os.environ.get("FAKE_CODEX_REPLY_2", os.environ["FAKE_CODEX_REPLY"]) if second
                  else os.environ["FAKE_CODEX_REPLY"], encoding="utf-8")
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
    record = tmp_path / "calls.jsonl"
    monkeypatch.setattr(codex_cli, "_command", lambda: [sys.executable, str(fake)])
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setenv("FAKE_CODEX_RECORD", str(record))
    monkeypatch.setenv("FAKE_CODEX_REPLY", json.dumps(REPLY, ensure_ascii=False))
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    for name in ("FAKE_CODEX_FAIL", "FAKE_CODEX_LOGIN", "FAKE_CODEX_REGIONS", "FAKE_CODEX_LOCATE_FAIL",
                 "FAKE_CODEX_CANARY_REPLY", "FAKE_CODEX_REPLY_2", "FAKE_CODEX_FAIL_1", "FAKE_CODEX_FAIL_2",
                 "FAKE_CODEX_SLEEP", "FAKE_CODEX_ROLLOUT", "FAKE_CODEX_LOCATE_SLEEP", "FAKE_CODEX_SLEEP_2",
                 "FAKE_CODEX_BAD_BYTES_2", "FAKE_CODEX_STDOUT", "ROKID_CODEX_TIMEOUT_S", "FAKE_CODEX_PARTS",
                 "ROKID_CODEX_PARTS", "FAKE_CODEX_OUTLINE", "FAKE_CODEX_OUTLINE_FAIL", "FAKE_CODEX_OUTLINE_SLEEP",
                 "FAKE_CODEX_FAIL_FIRST", "FAKE_CODEX_FAIL_MODEL", "ROKID_CODEX_MODEL"):
        monkeypatch.delenv(name, raising=False)
    # The CLI's own folder is this test's: the check reads the session record its request leaves there.
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    # One read unless a test asks for the default of two: most tests here are about one request.
    monkeypatch.setenv("ROKID_CODEX_READS", "1")
    monkeypatch.setattr(codex_cli, "_needs_proxy", lambda: False)
    return lambda: sorted((json.loads(path.read_text(encoding="utf-8")) for path in tmp_path.glob(record.name + ".*.json")),
                          key=lambda call: call["started"])


def _booklet(tmp_path, pages=2, **fields) -> Question:
    rows = []
    for number in range(1, pages + 1):
        path = tmp_path / f"page-{number}.png"
        Image.new("RGB", (300, 420), (200, 200, 190 + number)).save(path)
        rows.append({"page_number": number, "image_path": str(path)})
    return Question(question_no=None, chat_key="session:7", document_pages=rows, document_id="3", **fields)


def test_the_cli_answers_in_fast_mode_unless_a_trial_asks_for_standard(codex, tmp_path, monkeypatch):
    """The operator, 2026-11-16 (M-33): the Codex CLI and Work answer in Fast mode; a trial runs at Standard (11/10).
    The CLI's key is service_tier: `priority` is its Fast tier, `default` asks for standard routing even where a
    model's own default is Fast (codex-rs config_toml.rs and protocol config_types.rs, read 2026-11-16)."""
    monkeypatch.delenv("ROKID_CODEX_SPEED", raising=False)
    codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))
    assert all("service_tier=priority" in call["args"] for call in codex() if call["args"][:1] == ["exec"])
    assert len(_runs(codex())) == 1

    monkeypatch.setenv("ROKID_CODEX_SPEED", "standard")
    codex_cli.CodexCliSolver().check()
    assert "service_tier=default" in codex()[-1]["args"] and "service_tier=priority" not in codex()[-1]["args"]

    monkeypatch.setenv("ROKID_CODEX_SPEED", "anything else")
    codex_cli.CodexCliSolver().check()
    assert "service_tier=priority" in codex()[-1]["args"]  # only the one word turns Fast off


def _runs(calls):
    """The requests that ask for answers (not the ones that ask where the pages are or where the major problems begin)."""
    return [call for call in calls if call["args"][:1] == ["exec"] and not _locating(call) and not _outlining(call)]


def _outlining(call):
    return call["args"][:1] == ["exec"] and any(name.startswith("capture") for name in call.get("sizes", {}))


def _outlines(calls):
    return [call for call in calls if _outlining(call)]


def _locating(call):
    return call["args"][:1] == ["exec"] and any(name.startswith("photo") for name in call.get("sizes", {}))


def _locates(calls):
    return [call for call in calls if _locating(call)]


def test_a_booklet_is_one_exec_request_with_every_page_and_its_reply_becomes_the_answers(codex, tmp_path):
    replies = codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path, pages=3))

    [run] = _runs(codex())
    args = run["args"]
    assert [args[i + 1] for i, a in enumerate(args) if a == "-i"] == ["page001.jpg", "page002.jpg", "page003.jpg"]
    assert args[args.index("-m") + 1] == "gpt-6.2-sol" and "model_reasoning_effort=high" in args
    assert args[args.index("-s") + 1] == "read-only" and "--skip-git-repo-check" in args and "--ephemeral" in args
    assert "Answer EVERY question in the attached booklet" in args[-1] and "page001.jpg is capture page 1" in args[-1]
    # Phone, 2026-11-14: a CLI started from a piped script read the rest of the script as its input.
    assert run["stdin"] == ""
    assert [(item["label"], result.answer, result.extras["answer_status"]) for item, result in replies] == [
        ("問1", "④", "ready"), ("問2", "", "needs_input")]
    assert replies[0][1].extras["source"] == "codex-cli" and replies[0][1].extras["model"] == "gpt-6.2-sol"


def test_the_request_asks_what_the_captures_leave_out(codex, tmp_path):
    """Until 2026-11-16 a skipped page, or a part of a large sheet no capture showed, only made the list shorter."""
    codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))

    prompt = _runs(codex())[0]["args"][-1]
    assert "gap in the printed page numbers" in prompt and "cut off at an image's edge" in prompt
    assert "ONE extra item" in prompt and "no other capture continues it" in prompt


def test_a_page_recorded_as_a_clip_is_said_to_be_greyscale(codex, tmp_path):
    """The recorded route keeps luma only (ClipCamera, app/gather.py): a colour-coded graph, map or legend was
    answered from grey with nothing said."""
    codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))
    assert "reyscale" not in _runs(codex())[-1]["args"][-1]

    recorded = _booklet(tmp_path, pages=3)
    for page in recorded.document_pages[1:]:
        page["capture_provenance"] = {"source_kind": "clip_frame"}
    codex_cli.CodexCliSolver().answer_all(question=recorded)
    prompt = _runs(codex())[-1]["args"][-1]
    assert "Greyscale capture pages" in prompt and "): 2, 3. " in prompt
    assert "telling colours apart" in prompt and "is needs_input" in prompt and "which colours" in prompt


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


# The CLI's own sentence at its limit: as its --json events gave it on the phone on 2026-11-16 (M-34: exit 1, credits
# to buy or a time to try again), in the words and with the typographic apostrophe its binary holds (codex 0.167.0 on
# this PC, read 2026-11-18). How the same failure reads on stderr without --json was not recorded.
_AT_LIMIT = ("You’ve hit your usage limit. Visit https://chatgpt.com/settings/usage to purchase more credits "
             "or try again at 10:16 AM.")
_NO_MESSAGE = "Warning: no last agent message; wrote empty content to reply.json"  # the binary's words, with -o


@pytest.mark.parametrize("stdout, stderr", [
    ("", "ERROR: " + _AT_LIMIT),
    ("", _AT_LIMIT + "\n" + _NO_MESSAGE),
    # The allowance's other sentences in the CLI (codex-rs/protocol/src/error.rs at rust-v0.170.0, read 2026-11-18).
    ("", "ERROR: Quota exceeded. Check your plan and billing details.\n" + _NO_MESSAGE),
    ("", "ERROR: Your workspace is out of credits.\n" + _NO_MESSAGE),
    (json.dumps({"type": "error", "message": _AT_LIMIT}), _NO_MESSAGE),
    (json.dumps({"type": "turn.failed", "error": {"message": _AT_LIMIT}}), _NO_MESSAGE),
])
def test_the_clis_own_word_of_its_limit_is_a_usage_limit(codex, tmp_path, monkeypatch, stdout, stderr):
    monkeypatch.setenv("FAKE_CODEX_STDOUT", stdout)
    monkeypatch.setenv("FAKE_CODEX_FAIL", stderr)
    with pytest.raises(ChatGptWebRateLimit):
        codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))


def test_the_clis_own_sentence_is_a_usage_limit_wherever_it_stands_in_what_the_cli_wrote(codex, tmp_path, monkeypatch):
    """How the CLI ends its stderr at a real limit is not on record (M-34 kept a summary). Its own sentence is not
    something a page says: it is taken anywhere there. Only the service's bare words need an error line at the end."""
    after = "\n".join(f"tokens used: line {number}" for number in range(12))
    monkeypatch.setenv("FAKE_CODEX_FAIL", "ERROR: " + _AT_LIMIT + "\n" + after)
    with pytest.raises(ChatGptWebRateLimit):
        codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))


# A request refused for its rate, in the CLI's words (codex-rs at rust-v0.170.0, read 2026-11-18: api_bridge.rs,
# protocol/src/error.rs, sse/responses_error.rs). An HTTP 429 that is not the allowance is retried by the CLI only
# when the service names a wait; a rate limit inside the stream it retries five times in about six seconds.
_REFUSED = ["ERROR: exceeded retry limit, last status: 429 Too Many Requests, request id: 0000",
            "ERROR: rate limit exceeded: Rate limit reached for requests. Please try again in 20s.",
            "ERROR: Selected model is at capacity. Please try a different model."]


@pytest.mark.parametrize("message", _REFUSED)
def test_a_request_refused_for_its_rate_is_sent_again_and_is_no_usage_limit(codex, tmp_path, monkeypatch, capsys, message):
    """Until 2026-11-18 the words "rate limit" on an error line were a usage limit, which closes the CLI and Work
    for the booklet and leaves Chat: that evening Chat did not answer a booklet in an hour. A read in parts sends
    several requests at once, and what the service answers to that is not known."""
    monkeypatch.setattr(codex_cli, "_RATE_WAITS", (0.1, 0.2))
    monkeypatch.setenv("FAKE_CODEX_FAIL_FIRST", json.dumps({"times": 2, "message": message + "\n" + _NO_MESSAGE}))
    replies = codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))

    assert len(replies) == 2 and len(_runs(codex())) == 3
    told = [json.loads(line) for line in capsys.readouterr().out.splitlines() if '"codex_rate_refused"' in line]
    assert told == [{"event": "codex_rate_refused", "again_in_s": 0.1}, {"event": "codex_rate_refused", "again_in_s": 0.2}]


@pytest.mark.parametrize("message", _REFUSED)
def test_a_request_refused_for_its_rate_every_time_is_a_send_that_did_not_happen(codex, tmp_path, monkeypatch, message):
    monkeypatch.setattr(codex_cli, "_RATE_WAITS", (0.1,))
    monkeypatch.setenv("FAKE_CODEX_FAIL", message + "\n" + _NO_MESSAGE)
    with pytest.raises(ChatGptWebError) as raised:
        codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))
    assert type(raised.value) is ChatGptWebError, "the bare class: the other routes stay open"
    assert len(_runs(codex())) == 2


@pytest.mark.parametrize("stdout, stderr", [
    # What the run had written of its reply before it failed for another cause.
    ("The import quota was doubled, and the rate limit of the made-up reaction is its slowest step.",
     "ERROR: stream disconnected before completion"),
    # The same on stderr, where the CLI shows the model's messages as it goes.
    ("", "codex\nThe import quota was doubled; the usage limit of the made-up hall is 200 people.\n"
         "ERROR: stream disconnected before completion"),
    # An event of the run that is not the CLI's word of its own failure.
    (json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "a rate limit and a quota"}}),
     "ERROR: stream disconnected before completion"),
])
def test_a_failed_run_that_only_speaks_of_limits_is_not_taken_for_a_usage_limit(codex, tmp_path, monkeypatch, stdout, stderr):
    """Until 2026-11-17 the words were looked for anywhere in what a failed run had written. A usage limit closes the
    CLI and Work for the booklet: an English passage about quotas and a dropped connection sent it straight to Chat."""
    monkeypatch.setenv("FAKE_CODEX_STDOUT", stdout)
    monkeypatch.setenv("FAKE_CODEX_FAIL", stderr)
    with pytest.raises(ChatGptWebError) as raised:
        codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))
    assert type(raised.value) is ChatGptWebError


def test_a_run_that_fails_for_another_reason_is_a_send_that_did_not_happen(codex, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_FAIL", "error sending request for url (https://chatgpt.com/backend-api/codex/responses)")
    with pytest.raises(ChatGptWebError) as raised:
        codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))
    assert type(raised.value) is ChatGptWebError, "the bare class is what the server retries and moves to another route"
    assert "error sending request" in str(raised.value), "the CLI's own last line is the only record of the cause"


def test_a_newly_installed_release_is_tried_as_a_booklets_requests_run_it(codex, tmp_path, monkeypatch):
    """Before the route runs a release it has installed by itself (app/codex_update.py): signed in, and one request
    with every flag the booklet's requests use, answered from the picture."""
    new = codex_cli._command()
    monkeypatch.setattr(codex_cli, "_command", lambda: ["the-release-in-use"])  # not what is tried
    codex_cli.CodexCliSolver.verify(new)

    status, run = codex()[-2:]
    assert status["args"] == ["login", "status"]
    args = run["args"]
    assert {"exec", "-m", "-s", "--skip-git-repo-check", "--ephemeral", "--output-schema", "-i", "-o"} <= set(args)
    assert "service_tier=priority" in args and "model_reasoning_effort=low" in args
    assert run["schema"]["required"] == ["squares"] and list(run["sizes"]) == ["canary.jpg"]
    monkeypatch.setenv("FAKE_CODEX_CANARY_REPLY", '{"squares": 99}')
    with pytest.raises(ChatGptWebCheckFailed):
        codex_cli.CodexCliSolver.verify(new)
    monkeypatch.setenv("FAKE_CODEX_CANARY_REPLY", "It shows squares.")
    with pytest.raises(ChatGptWebCheckFailed):
        codex_cli.CodexCliSolver.verify(new)
    monkeypatch.setenv("FAKE_CODEX_LOGIN", "Not logged in")
    with pytest.raises(ChatGptWebAuthenticationRequired):
        codex_cli.CodexCliSolver.verify(new)


def _offered(home, *models, version="0.170.0"):
    """The CLI's own model list as it keeps it (models_cache.json): slug, visibility and context window, in the
    order of their priority."""
    home.mkdir(parents=True, exist_ok=True)
    (home / "models_cache.json").write_text(json.dumps({"client_version": version, "models": [
        {"slug": slug, "visibility": visibility, "priority": priority, "context_window": window}
        for priority, (slug, visibility, window) in enumerate(models, 1)]}), encoding="utf-8")


def _model_of(call):
    return call["args"][call["args"].index("-m") + 1]


def test_a_booklet_is_read_with_the_newest_sol_the_clis_own_model_list_offers(codex, tmp_path, monkeypatch, capsys):
    """The operator, 2026-11-18: tools and models are to be kept at the latest. GPT-6.2 Sol had been out a day
    before anyone here looked, and the model's name was a constant. The CLI keeps the list the service offers its
    version (models_cache.json, fetched again by every run older than five minutes; codex-rs models-manager at
    rust-v0.170.0): the newest Sol in it that is shown and has the context this route sizes a booklet for."""
    _offered(tmp_path / "codex-home", ("gpt-6.3-astra", "list", 272000), ("gpt-6.3-sol", "list", 500000),
             ("gpt-6.2-sol", "list", 500000), ("gpt-7-sol", "hide", 500000), ("gpt-6.10-sol-preview", "list", 500000),
             ("gpt-6.4-sol", "list", 272000))
    replies = codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))

    assert {_model_of(call) for call in codex() if call["args"][:1] == ["exec"]} == {"gpt-6.3-sol"}
    assert all(result.extras["model"] == "gpt-6.3-sol" for _, result in replies)
    assert '"codex_model"' in capsys.readouterr().out
    codex_cli.CodexCliSolver().check()
    assert _model_of(codex()[-1]) == "gpt-6.3-sol", "the check before use tries what a booklet will be read with"


@pytest.mark.parametrize("models, named, expected", [
    (None, None, codex_cli.MODEL),                                                    # no list kept
    ("not json", None, codex_cli.MODEL),
    ([("gpt-6.1-sol", "list", 500000), ("gpt-6-sol", "list", 272000)], None, codex_cli.MODEL),  # nothing newer
    ([("gpt-6.3-sol", "list", 272000)], None, codex_cli.MODEL),                        # newer, with less context
    ([("gpt-6.3-sol", "hide", 500000)], None, codex_cli.MODEL),                        # newer, not shown
    ([("gpt-6.9-sol", "list", 500000), ("gpt-6.10-sol", "list", 600000)], None, "gpt-6.10-sol"),  # by number
    ([("gpt-6.3-sol", "list", 500000)], "gpt-6.1-sol", "gpt-6.1-sol"),                 # the operator's own choice
], ids=["no list", "unreadable", "older", "small context", "hidden", "numeric", "named"])
def test_the_model_is_never_older_than_the_one_this_was_built_on_unless_it_is_named(codex, tmp_path, monkeypatch,
                                                                                    models, named, expected):
    home = tmp_path / "codex-home"
    if isinstance(models, list):
        _offered(home, *models)
    elif models:
        home.mkdir(parents=True)
        (home / "models_cache.json").write_text(models, encoding="utf-8")
    if named:
        monkeypatch.setenv("ROKID_CODEX_MODEL", named)
    assert codex_cli._model() == expected


def test_a_newer_model_the_service_refuses_gives_the_booklet_to_the_model_this_was_built_on(codex, tmp_path, monkeypatch, capsys):
    """Listed and refused has not been seen. What it would cost is known: a model that is not offered hands the
    booklet to Work and Chat, and neither answers a booklet inside a test's time (2026-11-18)."""
    _offered(tmp_path / "codex-home", ("gpt-6.3-sol", "list", 500000))
    monkeypatch.setenv("FAKE_CODEX_FAIL_MODEL", json.dumps({"model": "gpt-6.3-sol", "message": _MODEL_GONE[1]}))
    replies = codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))

    tried = [_model_of(call) for call in codex() if call["args"][:1] == ["exec"]]
    assert tried[0] == "gpt-6.3-sol" and tried[-1] == codex_cli.MODEL and len(replies) == 2
    assert all(result.extras["model"] == codex_cli.MODEL for _, result in replies)
    assert '"codex_model_refused"' in capsys.readouterr().out
    codex_cli.CodexCliSolver().check()
    assert _model_of(codex()[-1]) == codex_cli.MODEL, "and the check passes with it"


def test_a_named_model_that_is_refused_is_not_replaced(codex, tmp_path, monkeypatch):
    monkeypatch.setenv("ROKID_CODEX_MODEL", "gpt-6.1-sol")
    monkeypatch.setenv("FAKE_CODEX_FAIL_MODEL", json.dumps({"model": "gpt-6.1-sol", "message": _MODEL_GONE[1]}))
    with pytest.raises(ChatGptWebModelMismatch):
        codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))
    assert {_model_of(call) for call in codex() if call["args"][:1] == ["exec"]} == {"gpt-6.1-sol"}


# A model the service no longer offers. The first line is the CLI's own warning, read from the binary of a CLI
# installed on this PC (codex 0.153.2, 2026-11-16); `model_not_found` is an error code in that binary's list. The
# other two are the service's words as they have read elsewhere, which the pattern has to tolerate: no run has been
# made against a model that was really withdrawn.
_MODEL_GONE = [
    "warning: Model metadata for `gpt-6.1-sol` not found. Defaulting to fallback metadata; this can degrade "
    "performance and cause issues.\nERROR: unexpected status 400 Bad Request",
    'ERROR: {"type":"error","error":{"code":"model_not_found","message":"..."}}',
    "ERROR: unexpected status 400 Bad Request: {\"detail\":\"The 'gpt-6.1-sol' model is not supported when using "
    "Codex with a ChatGPT account.\"}",
    "stream error: The model `gpt-6.1-sol` does not exist or you do not have access to it.",
]


@pytest.mark.parametrize("message", _MODEL_GONE)
def test_the_check_names_a_model_that_is_no_longer_offered(codex, monkeypatch, message):
    """The route check then says model_mismatch, not the code every other failure of the CLI gets."""
    monkeypatch.setenv("FAKE_CODEX_FAIL", message)
    with pytest.raises(ChatGptWebModelMismatch):
        codex_cli.CodexCliSolver().check()


@pytest.mark.parametrize("message", _MODEL_GONE)
def test_a_booklet_whose_model_is_no_longer_offered_stops_at_the_first_request_and_asks_no_other_model(
        codex, tmp_path, monkeypatch, message):
    """ChatGptWebModelMismatch is a send that did not happen: the server hands the booklet to the next route."""
    monkeypatch.setenv("FAKE_CODEX_LOCATE_FAIL", message)
    monkeypatch.setenv("FAKE_CODEX_FAIL", message)
    with pytest.raises(ChatGptWebModelMismatch) as raised:
        codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))
    assert "gpt-6.1-sol" not in str(raised.value) and "Bad Request" not in str(raised.value)
    [request] = [call for call in codex() if call["args"][:1] == ["exec"]]
    assert request["args"][request["args"].index("-m") + 1] == "gpt-6.2-sol", "no other model is guessed"


@pytest.mark.parametrize("output", [
    "model: gpt-6.1-sol\nERROR: stream disconnected before completion",
    # What a run had written of an exam's own matter before it failed for another cause.
    "The Bohr model does not exist in this form, and the older model is not supported by the data.\n"
    "ERROR: stream disconnected before completion",
])
def test_a_failed_run_that_only_speaks_of_a_model_is_not_taken_for_a_model_that_is_gone(
        codex, tmp_path, monkeypatch, output):
    monkeypatch.setenv("FAKE_CODEX_FAIL", output)
    with pytest.raises(ChatGptWebError) as raised:
        codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))
    assert type(raised.value) is ChatGptWebError


def test_a_usage_limit_is_still_a_usage_limit_when_the_model_is_also_unknown_to_the_cli(codex, monkeypatch):
    """A limit sends the booklet straight to Chat; the CLI's warning about its own model list must not hide it."""
    monkeypatch.setenv("FAKE_CODEX_FAIL", _MODEL_GONE[0] + "\nERROR: You've hit your usage limit.")
    with pytest.raises(ChatGptWebRateLimit):
        codex_cli.CodexCliSolver().check()


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
    with pytest.raises(ChatGptWebReplyIncomplete):
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


def test_the_proxy_says_how_much_a_request_sent_and_how_fast(monkeypatch, capsys):
    """What a booklet's request uploads is 20 to 45 MB and the venue has the mobile network. Until 2026-11-18 nothing
    recorded how long that took: a way of reading that sent three times the bytes was tried on Wi-Fi alone."""
    upstream = socket.socket()
    upstream.bind(("127.0.0.1", 0))
    upstream.listen(1)
    got = []

    def sink():
        connection, _ = upstream.accept()
        while len(b"".join(got)) < 3_000_000:
            got.append(connection.recv(65536))
        connection.sendall(b"done")
        connection.close()

    threading.Thread(target=sink, daemon=True).start()
    monkeypatch.setattr(codex_cli, "_connect_upstream", lambda address, timeout=None: socket.create_connection(
        ("127.0.0.1", upstream.getsockname()[1]), timeout=timeout))
    with codex_cli.name_resolving_proxy() as port:
        client = socket.create_connection(("127.0.0.1", port), timeout=5)
        client.sendall(b"CONNECT chatgpt.com:443 HTTP/1.1\r\nHost: chatgpt.com:443\r\n\r\n")
        assert client.recv(100).startswith(b"HTTP/1.1 200")
        client.sendall(b"\x17" * 3_000_000)
        assert client.recv(100) == b"done"
        client.close()
        small = socket.create_connection(("127.0.0.1", port), timeout=5)  # a tunnel that sent little says nothing
        small.close()
        deadline = time.monotonic() + 5
        while '"codex_upload"' not in (printed := capsys.readouterr().out) and time.monotonic() < deadline:
            time.sleep(0.05)
    [told] = [json.loads(line) for line in printed.splitlines() if '"codex_upload"' in line]
    assert told["mb"] == 3.0 and told["seconds"] >= 0 and set(told) == {"event", "mb", "seconds", "mbit_s"}


@pytest.mark.parametrize("allowed, kept", [(1650.0, 1650.0), (90.0, 600.0)])
def test_the_proxy_keeps_a_silent_tunnel_for_as_long_as_the_run_may_take_and_ten_minutes_at_least(monkeypatch, allowed, kept):
    """A tunnel through which nothing passed for 600 s was closed, whatever the run was allowed: the answers of more
    than twelve pages may take longer (240 s and 30 s a page), and a stream cut while the model works ends the run as
    a bare failure, which costs another whole attempt."""
    waited = []

    def select(read, write, failed, timeout):
        waited.append(timeout)
        return select_module.select(read, write, failed, timeout)

    monkeypatch.setattr(codex_cli, "select", types.SimpleNamespace(select=select))  # the tunnel's own waits only
    upstream = socket.socket()
    upstream.bind(("127.0.0.1", 0))
    upstream.listen(1)

    def echo():
        connection, _ = upstream.accept()
        connection.recv(100)
        connection.sendall(b"pong")
        connection.close()

    threading.Thread(target=echo, daemon=True).start()
    monkeypatch.setattr(codex_cli, "_connect_upstream", lambda address, timeout=None: socket.create_connection(
        ("127.0.0.1", upstream.getsockname()[1]), timeout=timeout))
    with codex_cli.name_resolving_proxy(allowed) as port:
        client = socket.create_connection(("127.0.0.1", port), timeout=5)
        client.sendall(b"CONNECT chatgpt.com:443 HTTP/1.1\r\nHost: chatgpt.com:443\r\n\r\n")
        assert client.recv(100).startswith(b"HTTP/1.1 200")
        client.sendall(b"ping")
        assert client.recv(100) == b"pong"
        client.close()
    assert waited and set(waited) == {kept}


def test_a_run_tells_the_proxy_how_long_it_may_take(codex, tmp_path, monkeypatch):
    asked = []

    @contextlib.contextmanager
    def proxy(idle_s=None):
        asked.append(idle_s)
        yield 9

    monkeypatch.setattr(codex_cli, "_needs_proxy", lambda: True)
    monkeypatch.setattr(codex_cli, "name_resolving_proxy", proxy)
    codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path, pages=20))

    assert asked == [2700.0], "the tunnel is kept as long as the run may take"


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
    began, out["seen"] = time.time(), []
    deadline, bundle = began + float(os.environ.get("FLOW_WAIT_S", "40")), None
    while time.time() < deadline:
        bundle = client.get(f"/v1/exam-sessions/{sid}/answer-bundle", headers=auth)
        if bundle.status_code == 200:
            body = bundle.json()
            if not out["seen"] or out["seen"][-1]["revision"] != body["revision"]:
                out["seen"].append({"revision": body["revision"], "at": round(time.time() - began, 1),
                                    "ids": [item["question_id"] for item in body["items"]],
                                    "labels": [item["question_label"] for item in body["items"]]})
            # The first read's answers alone are not the last word: the route is still comparing them.
            if all(item["status"] != "pending" and item["question_id"] != "read-comparing" for item in body["items"]):
                break
        time.sleep(0.3)
    out["bundle"] = bundle.status_code
    out["items"] = [(item["status"], item["answer"]) for item in bundle.json()["items"]] if bundle.status_code == 200 else []
    out["issues"] = [item["issue"] for item in bundle.json()["items"]] if bundle.status_code == 200 else []
record = Path(os.environ["FAKE_CODEX_RECORD"])
out["exec_runs"] = sum(json.loads(path.read_text(encoding="utf-8"))["args"][:1] == ["exec"]
                       for path in record.parent.glob(record.name + ".*.json"))
print("RESULT " + json.dumps(out, ensure_ascii=False))
'''


def test_the_server_half_of_the_route_runs_from_pages_to_the_answer_bundle(tmp_path):
    """With ROKID_SOLVER=codex-cli in real mode, with Work and then Chat behind it, as the phone will run it."""
    fake = tmp_path / "fake_codex.py"
    fake.write_text(FAKE_CODEX, encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    environment = dict(os.environ, ROKID_DATA_DIR=str(data), ROKID_API_KEY="route-key", ROKID_REAL_MODE="1",
                       ROKID_ANALYZER="client-ocr", ROKID_SOLVER="codex-cli", ROKID_CHATGPT_SEND_ENABLED="1",
                       ROKID_CAPTURE_INSPECTION="0", PYTHONIOENCODING="utf-8", FAKE_CODEX_SCRIPT=str(fake),
                       FAKE_CODEX_RECORD=str(tmp_path / "calls.jsonl"), FAKE_CODEX_REPLY=json.dumps(REPLY, ensure_ascii=False))
    environment.pop("ROKID_SOLVER_FALLBACKS", None)
    environment.pop("ROKID_CODEX_READS", None)
    done = subprocess.run([sys.executable, "-X", "utf8", "-c", FLOW], capture_output=True, text=True, encoding="utf-8",
                          env=environment, cwd=Path(__file__).resolve().parents[1], timeout=180)
    lines = [line for line in done.stdout.splitlines() if line.startswith("RESULT ")]
    assert lines, done.stderr[-2500:]
    result = json.loads(lines[-1][7:])
    assert result["routes"] == ["codex-cli", "chatgpt-work", "chatgpt-web"]
    assert result["solver"]["name"] == "codex-cli" and result["solver"]["ready"] is True
    assert result["bundle"] == 200
    assert result["items"] == [["ready", "④"], ["needs_input", ""]]


def test_a_run_that_hangs_gives_the_booklet_up_in_minutes_by_its_size(monkeypatch):
    """Until 2026-11-16 a hung run held the booklet 3600 s, longer than a 50-minute test, with two routes waiting."""
    from app.solvers import codex_cli

    monkeypatch.delenv("ROKID_CODEX_TIMEOUT_S", raising=False)
    # (seconds for the answers, seconds for finding the pages)
    assert codex_cli._time_allowed(8) == (2700.0, 120.0)
    assert codex_cli._time_allowed(20) == (2700.0, 180.0)
    assert codex_cli._time_allowed(47) == (2700.0, 342.0)
    assert codex_cli._time_allowed(60) == (3300.0, 420.0)
    monkeypatch.setenv("ROKID_CODEX_TIMEOUT_S", "90")
    assert codex_cli._time_allowed(47) == (90.0, 90.0)


def test_twelve_dense_pages_are_not_given_up_at_ten_minutes(monkeypatch):
    """The operator's use of 2026-11-18: twelve gathered pages of vertical Japanese took a read more than ten minutes.
    The first booklet was given up at 600 s with both reads still running, and Work and Chat then failed: nothing
    after 21 minutes. Of the second, one read came back inside the 600 s and the other was ended there."""
    from app.solvers import codex_cli

    monkeypatch.delenv("ROKID_CODEX_TIMEOUT_S", raising=False)
    answers, _ = codex_cli._time_allowed(12)
    # A backstop, not a budget: no run on record ever hung, and the two that were ended as hung were slow ones
    # whose work was thrown away with nothing behind them that could answer inside the test's time.
    assert answers >= 2700.0


def test_with_sending_off_the_route_reports_it_and_runs_nothing(tmp_path):
    """The gate every route that spends the operator's subscription waits for (ROKID_CHATGPT_SEND_ENABLED)."""
    fake = tmp_path / "fake_codex.py"
    fake.write_text(FAKE_CODEX, encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    environment = dict(os.environ, ROKID_DATA_DIR=str(data), ROKID_API_KEY="route-key", ROKID_REAL_MODE="1",
                       ROKID_ANALYZER="client-ocr", ROKID_SOLVER="codex-cli", ROKID_CHATGPT_SEND_ENABLED="0",
                       ROKID_CAPTURE_INSPECTION="0", PYTHONIOENCODING="utf-8", FAKE_CODEX_SCRIPT=str(fake), FLOW_WAIT_S="4",
                       FAKE_CODEX_RECORD=str(tmp_path / "calls.jsonl"), FAKE_CODEX_REPLY=json.dumps(REPLY, ensure_ascii=False))
    done = subprocess.run([sys.executable, "-X", "utf8", "-c", FLOW], capture_output=True, text=True, encoding="utf-8",
                          env=environment, cwd=Path(__file__).resolve().parents[1], timeout=180)
    lines = [line for line in done.stdout.splitlines() if line.startswith("RESULT ")]
    assert lines, done.stderr[-2500:]
    result = json.loads(lines[-1][7:])
    assert result["solver"]["ready"] is False and result["solver"]["code"] == "send_not_authorized"
    assert result["exec_runs"] == 0
    assert all(status == "pending" for status, _ in result["items"]), result



def test_two_reads_that_differ_reach_the_glasses_bundle_as_an_answer_to_review_with_the_other_one(tmp_path):
    """The default of two reads through the server: the glasses already show such an item as review, reason, answer."""
    fake = tmp_path / "fake_codex.py"
    fake.write_text(FAKE_CODEX, encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    other = json.loads(json.dumps(REPLY))
    other["questions"][0]["answer"] = "②"
    environment = dict(os.environ, ROKID_DATA_DIR=str(data), ROKID_API_KEY="route-key", ROKID_REAL_MODE="1",
                       ROKID_ANALYZER="client-ocr", ROKID_SOLVER="codex-cli", ROKID_CHATGPT_SEND_ENABLED="1",
                       ROKID_CAPTURE_INSPECTION="0", PYTHONIOENCODING="utf-8", FAKE_CODEX_SCRIPT=str(fake),
                       FAKE_CODEX_RECORD=str(tmp_path / "calls.jsonl"), FAKE_CODEX_REPLY=json.dumps(REPLY, ensure_ascii=False),
                       FAKE_CODEX_REPLY_2=json.dumps(other, ensure_ascii=False))
    environment.pop("ROKID_SOLVER_FALLBACKS", None)
    environment.pop("ROKID_CODEX_READS", None)
    done = subprocess.run([sys.executable, "-X", "utf8", "-c", FLOW], capture_output=True, text=True, encoding="utf-8",
                          env=environment, cwd=Path(__file__).resolve().parents[1], timeout=180)
    lines = [line for line in done.stdout.splitlines() if line.startswith("RESULT ")]
    assert lines, done.stderr[-2500:]
    result = json.loads(lines[-1][7:])
    # Whichever read is back first is the one shown (0.88.0); the other one's answer stands in the note.
    [shown, missing] = result["items"]
    assert shown[0] == "needs_review" and shown[1] in ("④", "②") and missing == ["needs_input", ""]
    assert ({"④", "②"} - {shown[1]}).pop() in result["issues"][0]


def test_through_the_server_the_first_reads_answers_are_in_the_bundle_before_the_other_read_is_back(tmp_path):
    """The real route and the real server: the bundle carries the first read's answers, with the notice that they are
    being compared, seconds before the slower read ends; the compared answers then stand under the same questions."""
    fake = tmp_path / "fake_codex.py"
    fake.write_text(FAKE_CODEX, encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    other = json.loads(json.dumps(REPLY))
    other["questions"][0]["answer"] = "②"
    environment = dict(os.environ, ROKID_DATA_DIR=str(data), ROKID_API_KEY="route-key", ROKID_REAL_MODE="1",
                       ROKID_ANALYZER="client-ocr", ROKID_SOLVER="codex-cli", ROKID_CHATGPT_SEND_ENABLED="1",
                       ROKID_CAPTURE_INSPECTION="0", PYTHONIOENCODING="utf-8", FAKE_CODEX_SCRIPT=str(fake),
                       FAKE_CODEX_RECORD=str(tmp_path / "calls.jsonl"), FAKE_CODEX_REPLY=json.dumps(REPLY, ensure_ascii=False),
                       FAKE_CODEX_REPLY_2=json.dumps(other, ensure_ascii=False), FAKE_CODEX_SLEEP_2="5")
    environment.pop("ROKID_SOLVER_FALLBACKS", None)
    environment.pop("ROKID_CODEX_READS", None)
    done = subprocess.run([sys.executable, "-X", "utf8", "-c", FLOW], capture_output=True, text=True, encoding="utf-8",
                          env=environment, cwd=Path(__file__).resolve().parents[1], timeout=180)
    lines = [line for line in done.stdout.splitlines() if line.startswith("RESULT ")]
    assert lines, done.stderr[-2500:]
    result = json.loads(lines[-1][7:])
    early, late = result["seen"]
    assert early["labels"][-1] == "照合中" and late["at"] - early["at"] >= 2.0
    assert late["ids"] == early["ids"][:-1] and late["revision"] > early["revision"]
    assert result["items"] == [["needs_review", "④"], ["needs_input", ""]] and "②" in result["issues"][0]
    assert sum('"codex_read_done"' in line for line in done.stdout.splitlines()) == 2


REGIONS = {"images": [{"index": 1, "regions": [
    {"left": 520, "top": 250, "right": 900, "bottom": 750, "vertical_text": True},
    {"left": 100, "top": 250, "right": 480, "bottom": 750, "vertical_text": True}]}]}


def _patches(size):
    return -(-size[0] // 32) * -(-size[1] // 32)


def _photo(tmp_path, size=(1500, 2000), clip=False) -> Question:
    """One photo as the booklet; ``clip`` makes it a page recorded as a clip (source kind clip_frame)."""
    path = tmp_path / "photo.png"
    Image.new("RGB", size, (190, 190, 185)).save(path)
    page = {"page_number": 1, "image_path": str(path)}
    if clip:
        page["capture_provenance"] = {"source_kind": "clip_frame"}
    return Question(question_no=None, chat_key="session:9", document_pages=[page], document_id="5")


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
    # Which way the lines run decides how a page is cut; a worn photo does not show it to a simple measure.
    region = locate["schema"]["properties"]["images"]["items"]["properties"]["regions"]["items"]
    assert "vertical_text" in region["required"] and region["properties"]["vertical_text"] == {"type": "boolean"}
    assert "vertical" in args[-1]


def test_each_located_page_is_sent_enlarged_in_strips_along_its_vertical_lines_right_page_first(codex, tmp_path, monkeypatch):
    """Phone, 2026-11-15 (M-23, E8): two strips along the lines were read with 1.59% wrong, the page as one image 4.10%."""
    monkeypatch.setenv("FAKE_CODEX_REGIONS", json.dumps(REGIONS))
    codex_cli.CodexCliSolver().answer_all(question=_photo(tmp_path))

    [run] = _runs(codex())
    names = [name for name in run["sizes"] if name.startswith("page")]
    assert [name[:9] for name in names] == sorted(name[:9] for name in names) and {name[:9] for name in names} == {
        "page001-1", "page001-2"}, names
    # The first region is 570x1000 px on the 1500x2000 photo, 604x1060 with its margin: enlarged 2.4 times to 2540 px.
    first = [run["sizes"][name] for name in names if name.startswith("page001-1")]
    assert len(first) == 2 and all(height == 2540 for _, height in first), "strips down the page, each its full height"
    assert all(_patches(run["sizes"][name]) <= 2900 for name in names)
    assert "overview001.jpg" in run["sizes"], "the whole photo goes along small, so nothing outside the boxes is lost unseen"
    assert "right edge" in run["args"][-1] and "overlap" in run["args"][-1]


def test_a_page_of_horizontal_text_is_sent_in_bands_across_it(codex, tmp_path, monkeypatch):
    regions = {"images": [{"index": 1, "regions": [{"left": 520, "top": 250, "right": 900, "bottom": 750, "vertical_text": False}]}]}
    monkeypatch.setenv("FAKE_CODEX_REGIONS", json.dumps(regions))
    codex_cli.CodexCliSolver().answer_all(question=_photo(tmp_path))

    [run] = _runs(codex())
    parts = [run["sizes"][name] for name in run["sizes"] if name.startswith("page001-1")]
    assert len(parts) == 2 and len({width for width, _ in parts}) == 1 and all(height < 2540 for _, height in parts)


def test_a_region_whose_direction_is_missing_is_still_cut_out_and_enlarged(codex, tmp_path, monkeypatch):
    regions = {"images": [{"index": 1, "regions": [{"left": 520, "top": 250, "right": 900, "bottom": 750}]}]}
    monkeypatch.setenv("FAKE_CODEX_REGIONS", json.dumps(regions))
    codex_cli.CodexCliSolver().answer_all(question=_photo(tmp_path))

    [run] = _runs(codex())
    assert any(name.startswith("page001-1") for name in run["sizes"])


def test_a_booklet_too_large_for_the_models_context_is_enlarged_less_and_still_sent_whole(codex, tmp_path, monkeypatch):
    """The model takes 500,000 tokens (the CLI's own model list, phone, 2026-11-15) and an image costs 1.21 a 32-px
    patch. At twice the size 40 pages are about 270,000 tokens; a longer booklet must not be refused for its size."""
    monkeypatch.setenv("FAKE_CODEX_REGIONS", json.dumps(REGIONS))
    monkeypatch.setattr(codex_cli, "_CONTEXT_TOKENS", codex_cli._FIXED_TOKENS + 6000)
    codex_cli.CodexCliSolver().answer_all(question=_photo(tmp_path))

    [run] = _runs(codex())
    pages = [size for name, size in run["sizes"].items() if name.startswith("page001-")]
    views = [size for name, size in run["sizes"].items() if name.startswith("overview")]
    assert pages and (sum(map(_patches, pages)) + sum(map(_patches, views))) * 1.21 <= 6000
    assert max(height for _, height in pages) < 2540


def test_a_booklet_of_gathered_pages_too_large_at_their_own_size_is_reduced_and_still_sent_whole(codex, tmp_path, monkeypatch):
    """A page gathered from its clip is 3024x4032, twice the sensor's pixels: about 15,000 tokens when the paper fills
    it, so forty are over the model's context at their own size. Until 2026-11-16 a page was never reduced, and a
    booklet that did not fit at its own size went out too large."""
    monkeypatch.setenv("FAKE_CODEX_REGIONS", json.dumps(REGIONS))
    monkeypatch.setattr(codex_cli, "_CONTEXT_TOKENS", codex_cli._FIXED_TOKENS + 4000)
    codex_cli.CodexCliSolver().answer_all(question=_photo(tmp_path, size=(3024, 4032), clip=True))

    [run] = _runs(codex())
    pages = [size for name, size in run["sizes"].items() if name.startswith("page001-")]
    views = [size for name, size in run["sizes"].items() if name.startswith("overview")]
    assert {name[:9] for name in run["sizes"] if name.startswith("page")} == {"page001-1", "page001-2"}
    assert (sum(map(_patches, pages)) + sum(map(_patches, views))) * 1.21 <= 4000
    # Each region is 1218x2137 px on the photo with its margin; both pages come out the same size, as large as fits.
    assert 1200 < max(height for _, height in pages) < 2137


WHOLE_SHEET = {"images": [{"index": 1, "regions": [
    {"left": 100, "top": 20, "right": 900, "bottom": 980, "vertical_text": True}]}]}


def test_a_region_cut_from_a_still_is_wanted_at_twice_its_own_pixels_and_a_small_one_as_before(monkeypatch):
    """Phone, M-22 and M-23: characters of about 16 px were read with 18% wrong as photographed and 1.6 to 4% at twice
    the size in strips; larger did no better. Until 2026-11-16 the aim was a long side of 2540 px, twice a B5 page as a
    spread photo shows it, so a large sheet that fills the photo (3000 px, characters of 14 to 20 px) went out at its
    own size."""
    monkeypatch.delenv("ROKID_CODEX_PAGE_SCALE", raising=False)
    monkeypatch.delenv("ROKID_CODEX_PAGE_LONG", raising=False)
    assert codex_cli._wanted_scale((2100, 3000), clip=False) == 2.0
    assert codex_cli._wanted_scale((900, 1270), clip=False) * 1270 == 2540, "a B5 page of a spread: what it was"
    assert codex_cli._wanted_scale((604, 1060), clip=False) * 1060 == pytest.approx(2540), "a smaller one: still 2540"
    assert codex_cli._wanted_scale((400, 560), clip=False) == 2.5, "never past two and a half times"
    # A page gathered from its clip is already on a grid twice as fine as the camera's frame: as before.
    assert codex_cli._wanted_scale((3024, 4032), clip=True) == 1.0
    assert codex_cli._wanted_scale((1218, 2137), clip=True) == pytest.approx(2540 / 2137)
    monkeypatch.setenv("ROKID_CODEX_PAGE_SCALE", "1.5")
    assert codex_cli._wanted_scale((2100, 3000), clip=False) == 1.5
    assert codex_cli._wanted_scale((3024, 4032), clip=True) == 1.0
    monkeypatch.setenv("ROKID_CODEX_PAGE_LONG", "3200")
    assert codex_cli._wanted_scale((900, 1270), clip=False) == 2.5
    assert codex_cli._wanted_scale((2100, 3000), clip=False) == 1.5


def test_a_large_sheet_that_fills_a_still_photo_is_sent_at_twice_its_size_in_strips_the_cli_takes_whole(
        codex, tmp_path, monkeypatch):
    """The CLI reduces an image over 6000 px a side or 10,000 patches of 32 px by itself, unsaid."""
    monkeypatch.setenv("FAKE_CODEX_REGIONS", json.dumps(WHOLE_SHEET))
    codex_cli.CodexCliSolver().answer_all(question=_photo(tmp_path, size=(2400, 3000)))

    [run] = _runs(codex())
    parts = [size for name, size in run["sizes"].items() if name.startswith("page001-1")]
    # The region is 1920x2880 px on the photo, 2036x3000 with its margin, cut at the photo's edge.
    assert len(parts) > 2 and all(height == 6000 for _, height in parts), parts
    assert sum(width for width, _ in parts) >= 2 * 2036
    assert all(_patches(size) <= 2900 for size in parts)
    names = [name for name in run["sizes"] if name.startswith("page001-1")]
    assert names[:2] == ["page001-1a.jpg", "page001-1b.jpg"] and all(name[9:-4].isalpha() for name in names)
    # A band 8064 px long is two files (tests/test_page_tiles.py): the request says how they follow one another.
    assert "cut again across its lines" in run["args"][-1] and "goes on in the next piece" in run["args"][-1]


def test_more_than_26_parts_of_one_region_still_have_names():
    assert [codex_cli._letters(index) for index in (0, 1, 25, 26, 27, 51, 52, 701, 702)] == [
        "a", "b", "z", "aa", "ab", "az", "ba", "zz", "aaa"]


def test_a_stills_region_at_twice_its_size_gives_way_when_the_booklet_would_not_fit(codex, tmp_path, monkeypatch):
    """At twice its size the sheet of the test above is about 32,000 tokens."""
    monkeypatch.setenv("FAKE_CODEX_REGIONS", json.dumps(WHOLE_SHEET))
    monkeypatch.setattr(codex_cli, "_CONTEXT_TOKENS", codex_cli._FIXED_TOKENS + 20000)
    codex_cli.CodexCliSolver().answer_all(question=_photo(tmp_path, size=(2400, 3000)))

    [run] = _runs(codex())
    parts = [size for name, size in run["sizes"].items() if name.startswith("page001-1")]
    views = [size for name, size in run["sizes"].items() if name.startswith("overview")]
    assert (sum(map(_patches, parts)) + sum(map(_patches, views))) * 1.21 <= 20000
    assert 3000 < max(height for _, height in parts) < 6000, "less than twice, and still more than its own size"


def test_the_regions_sent_largest_give_way_first_and_none_when_the_booklet_fits(monkeypatch):
    import math

    still, gathered = ((2000, 3000), 2.0), ((3024, 4032), 1.0)
    assert codex_cli._target_long([still, gathered] * 3, 6 * 800) == math.inf
    # Room for the gathered page at its own size and the still at about 5000 px, not at its 6000.
    monkeypatch.setattr(codex_cli, "_CONTEXT_TOKENS", codex_cli._FIXED_TOKENS + 37500)
    limit = codex_cli._target_long([still, gathered], 0)
    assert 4032 < limit < 6000, "the still is sent smaller than twice; the gathered page keeps its own size"
    monkeypatch.setattr(codex_cli, "_CONTEXT_TOKENS", codex_cli._FIXED_TOKENS + 12000)
    assert codex_cli._target_long([still, gathered], 0) < 3000, "then both, to one long side"
    # Whole photos alone can use up the request (25 of 4032x3024): the regions are still images, not nothing.
    assert codex_cli._target_long([still, gathered], 10 ** 9) == 256


def test_a_page_gathered_from_its_clip_is_still_sent_at_its_own_size(codex, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_REGIONS", json.dumps(WHOLE_SHEET))
    codex_cli.CodexCliSolver().answer_all(question=_photo(tmp_path, size=(3024, 4032), clip=True))

    [run] = _runs(codex())
    parts = [size for name, size in run["sizes"].items() if name.startswith("page001-1")]
    assert parts and all(height == 4032 for _, height in parts), parts
    assert 2565 <= sum(width for width, _ in parts) < 2 * 2565, "2565 px wide on the page, and its parts overlap"


def test_a_photo_in_which_no_page_was_found_is_sent_as_before(codex, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_REGIONS", json.dumps({"images": [{"index": 1, "regions": []}]}))
    codex_cli.CodexCliSolver().answer_all(question=_photo(tmp_path))

    [run] = _runs(codex())
    assert "page001.jpg" in run["sizes"]


def test_when_locating_fails_the_booklet_is_still_sent_as_before(codex, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_LOCATE_FAIL", "error sending request for url (https://chatgpt.com/backend-api/codex/responses)")
    replies = codex_cli.CodexCliSolver().answer_all(question=_photo(tmp_path))

    [run] = _runs(codex())
    assert list(run["sizes"]) == ["page001.jpg"] and replies


def test_a_locating_request_that_does_not_come_back_in_its_time_gives_the_booklet_up_at_once(codex, tmp_path, monkeypatch):
    """Finding the pages took 20 s for 14 photos and 40 s for 31. A request that runs out its time means the CLI or
    the service is stalling: until 2026-11-17 the photos then went whole and the reads still ran their full time,
    the wearer waiting in the dark. The next route is asked at once, as after a read that did not finish."""
    monkeypatch.setenv("FAKE_CODEX_LOCATE_SLEEP", "60")
    monkeypatch.setenv("ROKID_CODEX_TIMEOUT_S", "4")
    with pytest.raises(ChatGptWebReplyIncomplete):
        codex_cli.CodexCliSolver().answer_all(question=_photo(tmp_path))
    assert not _runs(codex()), "no read is started behind a locating request that timed out"


def test_a_usage_limit_while_locating_is_a_rate_limit_and_nothing_more_runs(codex, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_LOCATE_FAIL", "ERROR: You've hit your usage limit.")
    with pytest.raises(ChatGptWebRateLimit):
        codex_cli.CodexCliSolver().answer_all(question=_photo(tmp_path))
    assert not _runs(codex())


@pytest.mark.parametrize("regions", [
    {"images": [{"index": 1, "regions": [{"left": 900, "top": 100, "right": 200, "bottom": 800}]}]},   # right of left
    {"images": [{"index": 1, "regions": [{"left": 100, "top": 100, "right": 110, "bottom": 105}]}]},   # a speck
    {"images": [{"index": 7, "regions": [{"left": 100, "top": 100, "right": 900, "bottom": 900}]}]},   # no such photo
    {"oops": True},
])
def test_boxes_that_make_no_sense_are_not_used(codex, tmp_path, monkeypatch, regions):
    monkeypatch.setenv("FAKE_CODEX_REGIONS", json.dumps(regions))
    codex_cli.CodexCliSolver().answer_all(question=_photo(tmp_path))

    [run] = _runs(codex())
    assert "page001.jpg" in run["sizes"]


def _box(left, top, right, bottom, vertical=False):
    return {"left": left, "top": top, "right": right, "bottom": bottom, "vertical_text": vertical}


PROBLEM_PAGE, ANSWER_SHEET, STRIP = _box(100, 100, 600, 900), _box(620, 100, 980, 400), _box(620, 450, 980, 465)
SPECK = _box(700, 600, 710, 605)


def _desk(tmp_path) -> Question:
    """A synthetic photo: a problem page on a desk, an answer sheet beside it (blue ink) and, under that, a narrow
    strip of a resource card (red ink), one line of print high. The boxes above are where they lie, in thousandths."""
    photo = Image.new("RGB", (2000, 1500), (96, 78, 60))
    draw = ImageDraw.Draw(photo)
    for (left, top, right, bottom), ink in (((200, 150, 1200, 1350), (20, 20, 20)), ((1240, 150, 1960, 600), (0, 0, 170)),
                                            ((1240, 675, 1960, 697), (170, 0, 0))):
        draw.rectangle([left, top, right, bottom], fill=(245, 245, 240))
        for y in range(top + 6, bottom - 8, 14):
            draw.rectangle([left + 12, y, right - 12, y + 6], fill=ink)
    path = tmp_path / "desk.png"
    photo.save(path)
    return Question(question_no=None, chat_key="session:9", document_pages=[{"page_number": 1, "image_path": str(path)}],
                    document_id="5")


def _locate(tmp_path, monkeypatch, question, *boxes):
    """The files the route writes for ``question`` when the locating request returns ``boxes`` for its photo."""
    monkeypatch.setenv("FAKE_CODEX_REGIONS", json.dumps({"images": [{"index": 1, "regions": list(boxes)}]}))
    directory = tmp_path / "request"
    directory.mkdir()
    names = codex_cli.CodexCliSolver._located(directory, dict(os.environ), question.document_pages, model="gpt-6.1-sol",
                                              timeout=60)
    return directory, names


def _tint(image: Image.Image, strong: int, weak: int) -> int:
    """How far one colour band stands over another at the image's most coloured pixel."""
    bands = image.convert("RGB").split()
    return ImageChops.subtract(bands[strong], bands[weak]).getextrema()[1]


def test_every_sheet_part_is_a_region_down_to_a_strip_one_line_high_and_a_speck_is_not():
    """Until 2026-11-16 a region had to be 5% of the photo each way: an answer strip of a line or two (151 px of a
    3024 px photo is five lines of 16 px print and more) was dropped, and nothing said so."""
    reply = {"images": [{"index": 1, "regions": [PROBLEM_PAGE, ANSWER_SHEET, STRIP, SPECK, _box(800, 800, 830, 830)]}]}
    found, partial = codex_cli._regions(json.dumps(reply), 1)
    assert [box[:4] for box in found[1]] == [(0.1, 0.1, 0.6, 0.9), (0.62, 0.1, 0.98, 0.4), (0.62, 0.45, 0.98, 0.465)]
    assert partial == {1}, "a returned box was left out: the photo also goes whole"

    found, partial = codex_cli._regions(json.dumps({"images": [{"index": 1, "regions": [PROBLEM_PAGE, STRIP]}]}), 1)
    assert len(found[1]) == 2 and partial == set()


def test_more_regions_than_the_limit_keep_the_first_and_the_photo_also_goes_whole():
    """Until 2026-11-16 a ninth region made the whole photo go out unenlarged, with no part of it cut out."""
    rows = [_box(50 + 100 * column, 100 + 400 * row, 140 + 100 * column, 450 + 400 * row)
            for row in range(2) for column in range(5)]
    found, partial = codex_cli._regions(json.dumps({"images": [{"index": 1, "regions": rows}]}), 1)
    assert [box[:2] for box in found[1]] == [(row["left"] / 1000, row["top"] / 1000) for row in rows[:8]]
    assert partial == {1}


def test_an_answer_sheet_and_a_narrow_strip_beside_the_page_are_cut_out_and_enlarged_too(codex, tmp_path, monkeypatch):
    directory, names = _locate(tmp_path, monkeypatch, _desk(tmp_path), PROBLEM_PAGE, ANSWER_SHEET, STRIP)

    assert names[0] == "overview001.jpg" and [name[:9] for name in names[1:]] == sorted(name[:9] for name in names[1:])
    assert {name[:9] for name in names[1:]} == {"page001-1", "page001-2", "page001-3"}, names
    with Image.open(directory / "page001-2a.jpg") as sheet, Image.open(directory / "page001-3a.jpg") as strip:
        # The strip is 720x22 px on the photo. With its margin, at two and a half times: every bar of it is there.
        assert strip.width >= 2.5 * 720 and 2.5 * 22 <= strip.height <= 2.5 * 60, strip.size
        assert _tint(strip, 0, 2) > 80 and _tint(sheet, 2, 0) > 80, "the strip's red ink and the sheet's blue"
    assert "page001.jpg" not in names, "every returned box was kept: the regions and the small view are all"


@pytest.mark.parametrize("extra", ["a speck", "a ninth region"])
def test_when_something_returned_is_left_out_the_photo_also_goes_whole_at_its_own_size(codex, tmp_path, monkeypatch, extra):
    boxes = [PROBLEM_PAGE, SPECK] if extra == "a speck" else [
        _box(50 + 100 * column, 100, 140 + 100 * column, 900) for column in range(9)]
    directory, names = _locate(tmp_path, monkeypatch, _desk(tmp_path), *boxes)

    kept = 1 if extra == "a speck" else 8
    assert {name[:9] for name in names if "-" in name} == {f"page001-{number}" for number in range(1, kept + 1)}
    assert names[0] == "overview001.jpg" and names[-1] == "page001.jpg"
    with Image.open(directory / "page001.jpg") as whole:
        assert whole.size == (2000, 1500)
        assert _tint(whole, 0, 2) > 80, "the strip no region shows is in it"


def test_whole_photos_are_counted_in_what_the_request_may_carry(codex, tmp_path, monkeypatch):
    """A whole photo costs up to the 10,000 patches the CLI lets one image be."""
    monkeypatch.setattr(codex_cli, "_CONTEXT_TOKENS", codex_cli._FIXED_TOKENS + 12000)
    directory, names = _locate(tmp_path, monkeypatch, _desk(tmp_path), PROBLEM_PAGE, SPECK)

    sizes = [Image.open(directory / name).size for name in names]
    assert "page001.jpg" in names and sum(map(_patches, sizes)) * 1.21 <= 12000


def test_the_requests_name_sheets_and_regions_not_booklet_pages(codex, tmp_path, monkeypatch):
    """An answer sheet, a resource card or a strip beside the page is exam matter too, and not a printed page."""
    monkeypatch.setenv("FAKE_CODEX_REGIONS", json.dumps({"images": [{"index": 1, "regions": [PROBLEM_PAGE, STRIP]}]}))
    codex_cli.CodexCliSolver().answer_all(question=_desk(tmp_path))

    asked = _locates(codex())[0]["args"][-1]
    assert all(word in asked for word in ("every sheet, or part of a sheet", "answer sheets", "resource", "cards", "strips"))
    assert "one region per printed page" not in asked
    note = _runs(codex())[0]["args"][-1]
    assert "region S" in note and "an answer sheet" in note and "printed page P" not in note
    assert "may not cover everything" in note and "capture page numbers NNN" in note
    # The same request asks where text is cut off at an image's edge (what the captures leave out): every part is cut.
    assert "cut off at an image's edge" in note and "not where the capture ends" in note


def _checks(calls):
    return [call for call in calls if call["args"][:1] == ["exec"] and "canary.jpg" in call.get("sizes", {})]


def test_the_check_before_use_is_one_small_real_request_whose_reply_depends_on_the_picture(codex):
    """Phone, 2026-11-15 (M-23): five black squares counted in 5 s at low effort, 14,834 input tokens, 12,160 of them cached."""
    codex_cli.CodexCliSolver().check()

    assert codex_cli.CodexCliSolver.check_sends is True, "the proof is a real request, not a look at readiness"

    [check] = _checks(codex())
    args = check["args"]
    # Not --ephemeral: the session record this one request leaves is what carries the allowance used.
    assert "model_reasoning_effort=low" in args and args[args.index("-s") + 1] == "read-only" and "--ephemeral" not in args
    assert max(check["sizes"]["canary.jpg"]) <= 512 and check["stdin"] == ""
    assert not _runs([call for call in codex() if call not in _checks(codex())]), "no booklet request is made"


ROLLOUT = {"timestamp": "2026-11-16T14:00:25Z", "type": "event_msg", "payload": {"type": "token_count", "rate_limits": {
    "limit_id": "codex", "plan_type": "pro", "secondary": None, "credits": {"balance": 0, "has_credits": False},
    "primary": {"used_percent": 3.0, "window_minutes": 10080, "resets_at": 1795429113}}}}


def test_the_check_says_how_much_of_the_allowance_is_used(codex, tmp_path, monkeypatch):
    """Phone, 2026-11-16 23:00: the session record of one small request held the service's own view of the limits
    (3.0% of the week used). Nobody is at the venue to look that up, and a limit only shows once it is met."""
    monkeypatch.setenv("FAKE_CODEX_ROLLOUT", json.dumps(ROLLOUT))

    assert codex_cli.CodexCliSolver().check() == {
        "usage": {"used_percent": 3.0, "window_minutes": 10080, "resets_at": 1795429113}}


def test_every_request_logs_the_tokens_the_cli_says_it_used(codex, tmp_path, monkeypatch, capsys):
    """What a booklet costs of the allowance was known only from a display that moves in whole percents: 11% to 14%
    over three booklets, a replay and some small requests on 2026-11-18. The CLI ends a run with the tokens it used
    (97,131 for 47 pages and 38,258 for 14 on record, M-23: not every input token, so what the service counts)."""
    monkeypatch.delenv("ROKID_CODEX_READS", raising=False)
    codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path, pages=3))

    told = [json.loads(line) for line in capsys.readouterr().out.splitlines() if '"codex_tokens"' in line]
    assert sorted(told, key=lambda line: line["images"]) == [
        {"event": "codex_tokens", "tokens": 12345, "images": 3}, {"event": "codex_tokens", "tokens": 12345, "images": 3},
        {"event": "codex_tokens", "tokens": 12345, "images": 3}], "the request that locates the pages and both reads"


def test_of_two_windows_the_check_reports_the_one_nearer_its_limit(codex, tmp_path, monkeypatch):
    """The phone's plan has the weekly window alone (the service's own records there, 2026-11-16 to 11-18:
    ``secondary`` null). Other plans have a five-hour window as well, and where
    both apply allowance has to remain in both (Help Center, read 2026-11-18): the one that runs out first is the
    one to show. Until 2026-11-18 only ``primary`` was read."""
    week = {"used_percent": 12.0, "window_minutes": 10080, "resets_at": 1795429113}
    hours = {"used_percent": 81.0, "window_minutes": 300, "resets_at": 1795000000}
    for limits, shown in (({"primary": week, "secondary": hours}, hours), ({"primary": hours, "secondary": week}, hours),
                          ({"primary": week, "secondary": None}, week), ({"primary": week, "secondary": {"used_percent": "much"}}, week),
                          ({"primary": None, "secondary": hours}, hours)):
        monkeypatch.setenv("FAKE_CODEX_ROLLOUT", json.dumps({"payload": {"rate_limits": limits}}))
        assert codex_cli.CodexCliSolver().check() == {"usage": shown}


def test_a_check_whose_request_left_no_readable_record_still_passes(codex, tmp_path, monkeypatch):
    assert codex_cli.CodexCliSolver().check() is None  # no record at all

    monkeypatch.setenv("FAKE_CODEX_ROLLOUT", "not json")
    assert codex_cli.CodexCliSolver().check() is None

    monkeypatch.setenv("FAKE_CODEX_ROLLOUT", json.dumps({"payload": {"rate_limits": {"primary": {"used_percent": "much"}}}}))
    assert codex_cli.CodexCliSolver().check() is None


def test_a_record_from_before_the_check_is_not_taken_for_its_own(codex, tmp_path, monkeypatch):
    old = tmp_path / "codex-home" / "sessions" / "2026" / "11" / "15" / "rollout-old.jsonl"
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps(ROLLOUT).replace("3.0", "88.0") + "\n", encoding="utf-8")
    os.utime(old, (time.time() - 3600, time.time() - 3600))

    assert codex_cli.CodexCliSolver().check() is None
    assert old.is_file(), "the check removes nothing"


def test_a_booklet_request_still_leaves_no_session_record(codex, tmp_path):
    codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))

    assert all("--ephemeral" in call["args"] for call in _runs(codex()))


def test_the_check_fails_when_the_reply_is_not_what_the_picture_shows(codex, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_CANARY_REPLY", "9")  # the picture shows three to seven
    with pytest.raises(ChatGptWebCheckFailed):  # the check before use then says check_failed, as Chat's deep check does
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


def _read(*answers):
    """One read of a booklet: a question for each (answer number, answer); None stands for 'cannot be answered'."""
    return {"questions": [{"group": "第1問", "label": f"問{number}", "answer_no": [number], "pages": [1],
                           "status": "needs_input" if answer is None else "ready", "answer": answer or "",
                           "missing_material": "不鮮明" if answer is None else "", "diagrams": []}
                          for number, answer in answers]}


def _twice(monkeypatch, first, second):
    monkeypatch.delenv("ROKID_CODEX_READS", raising=False)  # the default
    monkeypatch.setenv("FAKE_CODEX_REPLY", json.dumps(first, ensure_ascii=False))
    monkeypatch.setenv("FAKE_CODEX_REPLY_2", json.dumps(second, ensure_ascii=False))


def _shown(replies):
    return [(item["answer_no"], result.answer, result.extras["answer_status"], result.extras.get("review_note", ""))
            for item, result in replies]


def test_a_booklet_only_one_of_two_reads_answered_says_so_with_every_answer(codex, tmp_path, monkeypatch):
    """Unmarked answers mean "both reads agree". When one read failed or was ended, nothing was compared and the
    answers looked exactly as agreed ones do (found 2026-11-17). Each answer then carries ``read_once`` for the server
    to say so once; a booklet read once because it was asked for once (a trial) carries nothing."""
    _twice(monkeypatch, _read((1, "④"), (2, "②")), _read((1, "④"), (2, "②")))
    monkeypatch.setenv("FAKE_CODEX_BAD_BYTES_2", "1")
    solver = codex_cli.CodexCliSolver()
    replies = solver.answer_all(question=_booklet(tmp_path))
    assert [result.extras.get("read_once") for _, result in replies] == [True, True]
    kept = solver.answer_all(question=_booklet(tmp_path))  # read again from what was kept: the same is said
    assert [result.extras.get("read_once") for _, result in kept] == [True, True]


@pytest.mark.parametrize("reads", ["2", "1"])
def test_a_booklet_read_as_often_as_was_asked_carries_no_such_word(codex, tmp_path, monkeypatch, reads):
    _twice(monkeypatch, _read((1, "④")), _read((1, "④")))
    monkeypatch.setenv("ROKID_CODEX_READS", reads)
    replies = codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))
    assert ["read_once" in result.extras for _, result in replies] == [False]


def test_a_booklet_is_read_twice_at_the_same_time_and_answers_both_reads_agree_on_stand_unmarked(codex, tmp_path, monkeypatch):
    """Phone, 2026-11-15 (M-23): of 72 answers to kanji questions read once from a worn photo, 5 were wrong. Comparing
    every pair of the 18 reads, both were wrong in the same way in 1.6% and disagreed in 10.6%."""
    _twice(monkeypatch, _read((1, "④"), (2, "②")), _read((1, "④"), (2, "②")))
    monkeypatch.setenv("FAKE_CODEX_SLEEP", "0.8")
    replies = codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))

    first, second = sorted(_runs(codex()), key=lambda call: call["reply_file"])
    assert (first["reply_file"], second["reply_file"]) == ("reply-1.json", "reply-2.json")
    assert first["sizes"] == second["sizes"] and first["args"][-1] == second["args"][-1], "the same pages and the same request"
    assert max(first["started"], second["started"]) < min(first["ended"], second["ended"]), "at the same time, not one after the other"
    assert _shown(replies) == [([1], "④", "ready", ""), ([2], "②", "ready", "")]


def test_a_short_answer_the_two_reads_disagree_on_is_kept_and_marked_with_the_other_answer(codex, tmp_path, monkeypatch):
    _twice(monkeypatch, _read((1, "④"), (2, "②")), _read((1, "④"), (2, "③")))
    [one, two] = _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))

    assert one == ([1], "④", "ready", "")
    assert two[:3] == ([2], "②", "ready") and "③" in two[3]


@pytest.mark.parametrize("first, second", [("④", "4"), ("⑤、⑥", "5,6"), (" x = 3 ", "x=3"), ("ア", "ｱ")])
def test_marks_are_compared_as_marks_not_as_strings(codex, tmp_path, monkeypatch, first, second):
    _twice(monkeypatch, _read((1, first)), _read((1, second)))
    [(_, _, _, note)] = _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert note == ""


def test_written_answers_are_not_compared_because_two_writings_of_one_solution_differ(codex, tmp_path, monkeypatch):
    _twice(monkeypatch, _read((1, "運動エネルギーの変化は外力のした仕事に等しいので、速さは変わらない。")),
           _read((1, "外力のする仕事が運動エネルギーの変化に等しいことから、速さは一定である。")))
    [(_, answer, _, note)] = _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert answer.startswith("運動エネルギー") and note == ""


def test_a_result_with_its_working_is_compared_by_the_result_alone(codex, tmp_path, monkeypatch):
    """The operator's trial of 2026-11-17: a written mathematics answer carries its working, and two writings of one
    derivation differ. What is compared is what stands before the line that begins with 式："""
    _twice(monkeypatch, _read((1, "3/8\n式：表が1回だけ出るのは3通り。3/2³＝3/8")),
           _read((1, "3/8\n式：₃C₁×(1/2)×(1/2)² = 3/8")))
    [(_, answer, _, note)] = _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert answer.startswith("3/8\n式：表が") and note == ""


def test_results_that_differ_are_marked_whatever_their_working_says(codex, tmp_path, monkeypatch):
    """Phone, 2026-11-17: two reads gave different amounts for one question. With the working written after it the answer is longer
    than a mark, and until now nothing longer than a mark was compared."""
    _twice(monkeypatch, _read((1, "120円\n式：200×(3/5)＝120")), _read((1, "70円\n式：200×(3/5)−50＝70")))
    [(_, answer, status, note)] = _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert answer.startswith("120円") and status == "ready"
    assert "70円" in note and "式" not in note, "the other read's result, not its working"


@pytest.mark.parametrize("other, differs", [("平均:3\n分散:2\n標準偏差:√2\n式：V(X)＝E(X²)−{E(X)}²", False),
                                            ("平均：3\n分散：4\n標準偏差：√2\n式：V(X)＝4", True)])
def test_the_named_results_of_one_question_are_compared_together_before_the_working(codex, tmp_path, monkeypatch, other, differs):
    """A question with several answer boxes gives each on its own line under its printed name: longer than one mark,
    and still results, not writing."""
    _twice(monkeypatch, _read((1, "平均：3\n分散：2\n標準偏差：√2\n式：E(X)＝(1＋2＋3＋4＋5)/5＝3")), _read((1, other)))
    [(_, _, _, note)] = _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert bool(note) is differs


def test_a_table_headed_in_capitals_by_one_read_and_small_letters_by_the_other_is_one_result(codex, tmp_path, monkeypatch):
    """Phone, 2026-11-17: a table one read headed X and P and the other x and p was shown as a disagreement."""
    _twice(monkeypatch, _read((1, "X：0，1\nP：1/4，3/4\n式：P(X=0)=1/4")), _read((1, "x：0，1\np：1/4，3/4\n式：1−3/4=1/4")))
    [(_, _, _, note)] = _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert note == ""


def test_writing_that_names_no_working_is_still_not_compared(codex, tmp_path, monkeypatch):
    """A line of the answer that merely holds the word 式 does not split it."""
    _twice(monkeypatch, _read((1, "化学反応式：2H₂＋O₂→2H₂O であり、水素が酸化されるので、酸化還元反応である。")),
           _read((1, "化学反応式：2H₂＋O₂→2H₂O より、酸素が還元される酸化還元反応といえる。")))
    [(_, _, _, note)] = _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert note == ""


@pytest.mark.parametrize("first, second", [(None, "④"), ("④", None)])
def test_an_answer_only_one_of_the_reads_gave_is_shown_and_marked(codex, tmp_path, monkeypatch, first, second):
    _twice(monkeypatch, _read((1, first)), _read((1, second)))
    [(numbers, answer, status, note)] = _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert (numbers, answer, status) == ([1], "④", "ready") and note


def test_what_neither_read_could_answer_stays_unanswerable(codex, tmp_path, monkeypatch):
    _twice(monkeypatch, _read((1, None)), _read((1, None)))
    assert _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))) == [([1], "", "needs_input", "")]


@pytest.mark.parametrize("first, second", [(((1, "④"), (3, "①")), ((1, "④"), (2, "②"), (3, "①"))),
                                           (((1, "④"), (2, "②"), (3, "①")), ((1, "④"), (3, "①")))])
def test_a_question_only_one_of_the_reads_listed_is_kept_in_its_place_and_marked(codex, tmp_path, monkeypatch, first, second):
    _twice(monkeypatch, _read(*first), _read(*second))
    shown = _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert [(numbers, answer) for numbers, answer, _, _ in shown] == [([1], "④"), ([2], "②"), ([3], "①")]
    assert [bool(note) for _, _, _, note in shown] == [False, True, False]


@pytest.mark.parametrize("failing", ["FAKE_CODEX_FAIL_1", "FAKE_CODEX_FAIL_2"])
def test_when_one_read_fails_the_other_answers_alone_and_nothing_is_marked(codex, tmp_path, monkeypatch, failing):
    _twice(monkeypatch, _read((1, "④")), _read((1, "④")))
    monkeypatch.setenv(failing, "error sending request for url (https://chatgpt.com/backend-api/codex/responses)")
    assert _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))) == [([1], "④", "ready", "")]


def _logged(capsys, event):
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if f'"{event}"' in line]


def test_a_read_that_hangs_behind_a_finished_one_is_cut_and_the_finished_read_answers_alone(
        codex, tmp_path, monkeypatch, capsys):
    """Until 2026-11-17 the call returned when the slower read ended: one read back at 150 s and the other hung held
    the wearer to the whole limit, ten minutes and more. The other read is given the first one's time again, two
    minutes at least, and then its process is ended. Not half that time: two runs of one booklet of 47 pages ended
    at 366 s and 586 s, so two healthy reads lie that far apart, and a read cut is a booklet nothing was compared
    for."""
    _twice(monkeypatch, _read((1, "④")), _read((1, "④")))
    monkeypatch.setenv("ROKID_CODEX_LOCATE", "0")
    monkeypatch.setenv("FAKE_CODEX_SLEEP", "3")
    monkeypatch.setenv("FAKE_CODEX_SLEEP_2", "120")
    monkeypatch.setenv("ROKID_CODEX_TIMEOUT_S", "30")
    monkeypatch.setattr(codex_cli, "_SECOND_READ_LEAST_S", 0.5)
    started = time.monotonic()
    shown = _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))

    assert time.monotonic() - started < 20, "not the slower read's time, and not the limit"
    assert shown == [([1], "④", "ready", "")]
    [cut] = _logged(capsys, "codex_read_cut")
    assert cut["waited_s"] >= cut["first_s"] >= 3.0, "as long again as the read that came back"
    assert set(cut) == {"event", "first_s", "waited_s"}, "no reply text in the log"
    assert [call["reply_file"] for call in _runs(codex())] == ["reply-1.json"], "the other never ended by itself"


def test_a_slow_first_read_does_not_buy_the_other_as_long_again_without_end(codex, tmp_path, monkeypatch, capsys):
    """The operator's use of 2026-11-18: one read of twelve dense pages came back after some nine minutes. As long
    again for the other is most of what is left of a 50-minute test. The wait behind a finished read has a ceiling
    (fifteen minutes since the first read's answers go out at once: waiting behind it costs the wearer nothing)."""
    assert codex_cli._SECOND_READ_MOST_S == 900.0
    _twice(monkeypatch, _read((1, "④")), _read((1, "④")))
    monkeypatch.setenv("ROKID_CODEX_LOCATE", "0")
    monkeypatch.setenv("FAKE_CODEX_SLEEP", "3")
    monkeypatch.setenv("FAKE_CODEX_SLEEP_2", "120")
    monkeypatch.setenv("ROKID_CODEX_TIMEOUT_S", "30")
    monkeypatch.setattr(codex_cli, "_SECOND_READ_LEAST_S", 0.2)
    monkeypatch.setattr(codex_cli, "_SECOND_READ_MOST_S", 1.0)
    shown = _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))

    assert shown == [([1], "④", "ready", "")]
    [cut] = _logged(capsys, "codex_read_cut")
    assert cut["first_s"] >= 3.0 and cut["waited_s"] == 1.0, "the ceiling, not the first read's time again"


def _boxes_read(*lines):
    """One question that fills the printed answer numbers 1 to len(lines), a line for each."""
    return {"questions": [{"group": "1", "label": "問1", "answer_no": list(range(1, len(lines) + 1)), "pages": [1],
                           "status": "ready", "answer": "\n".join(lines), "missing_material": "", "diagrams": []}]}


def test_the_boxes_of_one_question_are_compared_box_by_box_however_many_there_are(codex, tmp_path, monkeypatch):
    """Phone, 2026-11-18: a word bank's seven boxes came back as seven lines, "[21]：②" and so on. Together they are
    longer than a mark, so nothing of them was compared, and the answers looked like ones both reads agreed on."""
    first = [f"[{number}]：{mark}" for number, mark in zip(range(21, 28), "②⑤①⑦③⑩⑫")]
    second = first[:5] + ["[26]：⑨", "[27]：⑫"]
    _twice(monkeypatch, _boxes_read(*first), _boxes_read(*second))
    [(_, _, status, note)] = _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert status == "ready" and note, "the sixth box differs"


def test_boxes_given_with_the_words_of_their_options_agree_when_label_and_words_do(codex, tmp_path, monkeypatch):
    """An option's words stand after its label so that a label read wrongly can be found on the paper; a space
    inside those words is no second part."""
    lines = ["[1]：③（葉緑体）", "[2]：④（気孔）", "[3]：⑧（道管 2本）", "[4]：⑨（光合成）"]
    _twice(monkeypatch, _boxes_read(*lines), _boxes_read(*[line.replace("：", ": ") for line in lines]))
    [(_, _, _, note)] = _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert note == ""


def test_a_label_the_reads_give_differently_for_the_same_words_is_marked(codex, tmp_path, monkeypatch):
    """The operator's use of 2026-11-18: the paper's labels ran ⑩, ⑫, ⑬ and the answer said ⑪."""
    lines = ["[1]：③（葉緑体）", "[2]：④（気孔）", "[3]：⑧（道管）", "[4]：⑫（光合成）"]
    _twice(monkeypatch, _boxes_read(*lines), _boxes_read(*lines[:3], "[4]：⑪（光合成）"))
    [(_, answer, status, note)] = _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert "⑫" in answer and status == "ready" and note


@pytest.mark.parametrize("first, second", [("①（あ－X）", "①"), ("②（道管）", "②（導管）"), ("ア（光合成）", "ア"),
                                            ("⑨（川（上流））", "⑨")])
def test_a_label_with_the_words_of_its_option_is_compared_by_the_label(codex, tmp_path, monkeypatch, first, second):
    """Phone, 2026-11-18, the first booklet read with options' words asked for: one read added the words and the
    other did not, or wrote them differently, and 18 of 45 items were marked where the labels were the same."""
    _twice(monkeypatch, _read((1, first)), _read((1, second)))
    [(_, _, _, note)] = _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert note == ""


@pytest.mark.parametrize("first, second", [("2(x+1)", "2(x-1)"), ("f(a)", "f(b)"), ("③（葉緑体）", "④（葉緑体）")])
def test_what_stands_in_brackets_after_a_value_is_still_compared(codex, tmp_path, monkeypatch, first, second):
    _twice(monkeypatch, _read((1, first)), _read((1, second)))
    [(_, _, _, note)] = _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert note


def test_a_box_the_reads_differ_on_is_named_with_what_the_other_read_says_there(codex, tmp_path, monkeypatch):
    """The other read's whole answer, cut at 24 characters, showed its first boxes and not the one that differs."""
    lines = ["[1]：③（葉緑体）", "[2]：④（気孔）", "[3]：⑧（道管）", "[4]：⑫（光合成）"]
    _twice(monkeypatch, _boxes_read(*lines), _boxes_read(*lines[:3], "[4]：⑪（光合成）"))
    [(_, _, _, note)] = _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert note.endswith("他方：4は11"), "the box and the other read's label there: no words, no other box"


@pytest.mark.parametrize("answer, asked", [("⑫（光合成）", True), ("[1]：③（葉緑体）\n[2]：⑩（気孔）", True),
                                           ("⑨（光合成）", False), ("12", False), ("㉓", True)])
def test_a_circled_label_of_two_digits_is_always_to_be_checked_on_the_paper(codex, tmp_path, monkeypatch, answer, asked):
    """The operator's use of 2026-11-18: both reads read a word bank's soft two-digit labels wrongly in the same way
    (the 11th option as ⑪ where the paper prints ⑫), so nothing was marked. Read again, the two reads agreed on every
    option's words and differed on every label of two digits."""
    _twice(monkeypatch, _read((1, answer)), _read((1, answer)))
    [(_, shown, status, note)] = _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert shown == answer and status == "ready"
    assert (note == codex_cli._CHECK_LABEL) is asked and bool(note) is asked


@pytest.mark.parametrize("first", ["fails", "is not an answer list"])
def test_a_slower_read_is_waited_for_when_the_first_to_return_gave_nothing_usable(
        codex, tmp_path, monkeypatch, capsys, first):
    _twice(monkeypatch, _read((1, "④")), _read((1, "④")))
    if first == "fails":
        monkeypatch.setenv("FAKE_CODEX_FAIL_1", "error sending request for url (https://chatgpt.com/backend-api/codex/responses)")
    else:
        monkeypatch.setenv("FAKE_CODEX_REPLY", "I could not read the pages.")
    monkeypatch.setenv("FAKE_CODEX_SLEEP_2", "4")
    monkeypatch.setattr(codex_cli, "_SECOND_READ_LEAST_S", 0.5)

    assert _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))) == [([1], "④", "ready", "")]
    assert not _logged(capsys, "codex_read_cut")


def test_a_read_whose_reply_file_cannot_be_read_fails_alone_and_the_other_read_answers(codex, tmp_path, monkeypatch, capsys):
    """From the morning of 2026-11-17 an error of this host leaves the route as a run that did not finish. Raised by
    one read's reply file (not UTF-8, unreadable), it took the whole booklet to the next route although the other
    read had answered."""
    _twice(monkeypatch, _read((1, "④")), _read((1, "④")))
    monkeypatch.setenv("FAKE_CODEX_BAD_BYTES_2", "1")

    assert _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))) == [([1], "④", "ready", "")]
    [failed] = _logged(capsys, "codex_read_failed")
    assert failed["type"] == "UnicodeDecodeError" and failed["at"] and set(failed) == {"event", "type", "at"}


@pytest.mark.parametrize("first_failure, raised", [
    ("error sending request for url (https://chatgpt.com/backend-api/codex/responses)", ChatGptWebReplyIncomplete),
    ("ERROR: You've hit your usage limit. Try again in 3 hours.", ChatGptWebRateLimit),
])
def test_when_every_read_fails_one_that_did_not_finish_in_time_decides_unless_a_usage_limit_does(
        codex, tmp_path, monkeypatch, first_failure, raised):
    """Until 2026-11-17 the first read's failure was raised whatever the other's was: a bare failure beside a read
    that ran out its time cost one more whole attempt 150 s later, where a run that did not finish is given to the
    next route at once. A usage limit still comes first: it closes Work as well."""
    _twice(monkeypatch, _read((1, "④")), _read((1, "④")))
    monkeypatch.setenv("FAKE_CODEX_FAIL_1", first_failure)
    monkeypatch.setenv("FAKE_CODEX_SLEEP_2", "60")
    monkeypatch.setenv("ROKID_CODEX_TIMEOUT_S", "4")
    monkeypatch.setenv("ROKID_CODEX_LOCATE", "0")  # the locating request has the same limit and is not what is tried
    with pytest.raises(ChatGptWebError) as error:
        codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))
    assert type(error.value) is raised


def test_a_second_reply_that_is_not_an_answer_list_leaves_the_first_alone(codex, tmp_path, monkeypatch):
    _twice(monkeypatch, _read((1, "④")), _read((1, "④")))
    monkeypatch.setenv("FAKE_CODEX_REPLY_2", "I could not read the pages.")
    assert _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))) == [([1], "④", "ready", "")]


def test_a_first_reply_that_is_not_an_answer_list_leaves_the_second_alone(codex, tmp_path, monkeypatch):
    _twice(monkeypatch, _read((1, "④")), _read((1, "④")))
    monkeypatch.setenv("FAKE_CODEX_REPLY", "I could not read the pages.")
    assert _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))) == [([1], "④", "ready", "")]


# A reply no answer list can be made of, and the function that refuses it.
_UNUSABLE = {
    "prose": ("I could not read the pages.", "extract_json"),
    "cut off at the output limit": (json.dumps(_read((1, "④"), (2, "②")), ensure_ascii=False)[:-30], "_booklet_replies"),
    "a stray top-level key": (json.dumps({**_read((1, "④")), "note": "a made-up remark"}, ensure_ascii=False),
                              "validate_answer_fields"),
    "an empty item": ('{"questions": [{}]}', "_booklet_replies"),
}


@pytest.mark.parametrize("reply, refused_in", _UNUSABLE.values(), ids=_UNUSABLE)
def test_when_no_read_gives_a_usable_reply_the_booklet_moves_to_the_next_route(
        codex, tmp_path, monkeypatch, capsys, reply, refused_in):
    """Until 2026-11-17 this left as a ValueError, which the server records as solver_failed: the booklet ended there
    with Work and Chat never asked, after the requests had been spent. ChatGptWebReplyIncomplete is what a run that
    does not finish in time raises, and the server gives the booklet to the next route at once."""
    monkeypatch.delenv("ROKID_CODEX_READS", raising=False)  # the default of two; both get this reply
    monkeypatch.setenv("FAKE_CODEX_REPLY", reply)
    with pytest.raises(ChatGptWebReplyIncomplete):
        codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))

    assert len(_runs(codex())) == 2
    # Why each read was refused is logged by kind and place. The reply's own text never is.
    printed = capsys.readouterr().out
    causes = [json.loads(line) for line in printed.splitlines() if '"codex_reply_unusable"' in line]
    assert [(cause["type"], cause["at"].rsplit(":", 1)[-1]) for cause in causes] == [("ValueError", refused_in)] * 2
    assert not any(text in printed for text in ("could not read", "made-up", "問1", "④"))


def _a_page_that_cannot_be_opened(question, monkeypatch):
    Path(question.document_pages[0]["image_path"]).write_bytes(b"not an image")


def _no_memory_for_a_page(question, monkeypatch):
    def full(image):
        raise MemoryError

    monkeypatch.setattr(codex_cli, "_readable", full)


@pytest.mark.parametrize("broken, kind", [(_a_page_that_cannot_be_opened, "UnidentifiedImageError"),
                                          (_no_memory_for_a_page, "MemoryError")])
def test_a_run_this_host_could_not_carry_out_moves_the_booklet_to_the_next_route(
        codex, tmp_path, monkeypatch, capsys, broken, kind):
    """An OSError or MemoryError from preparing the request (an image, the working folder on a full disk) also ended
    the booklet as solver_failed. It is a cause other than the allowance: the next route stands in."""
    question = _booklet(tmp_path)
    broken(question, monkeypatch)
    with pytest.raises(ChatGptWebReplyIncomplete):
        codex_cli.CodexCliSolver().answer_all(question=question)

    [cause] = [json.loads(line) for line in capsys.readouterr().out.splitlines() if '"codex_run_failed"' in line]
    assert cause["type"] == kind and cause["at"]
    assert not _runs(codex())


def test_when_both_reads_hit_the_usage_limit_the_booklet_moves_to_the_next_route(codex, tmp_path, monkeypatch):
    _twice(monkeypatch, _read((1, "④")), _read((1, "④")))
    monkeypatch.setenv("FAKE_CODEX_FAIL", "ERROR: You've hit your usage limit. Try again in 3 hours.")
    with pytest.raises(ChatGptWebRateLimit):
        codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))


def test_both_reads_are_kept_so_a_repeat_runs_nothing_and_marks_the_same(codex, tmp_path, monkeypatch):
    _twice(monkeypatch, _read((1, "④"), (2, "②")), _read((1, "④"), (2, "③")))
    question = _booklet(tmp_path)
    first = _shown(codex_cli.CodexCliSolver().answer_all(question=question))
    again = _shown(codex_cli.CodexCliSolver().answer_all(question=question))

    assert len(_runs(codex())) == 2 and again == first and "③" in again[1][3]


def test_a_reply_kept_before_there_were_two_reads_is_still_used(codex, tmp_path, monkeypatch):
    monkeypatch.delenv("ROKID_CODEX_READS", raising=False)
    question = _booklet(tmp_path)
    kept = codex_cli.CodexCliSolver._kept(question)
    kept.parent.mkdir(parents=True)
    kept.write_text(json.dumps(_read((1, "④")), ensure_ascii=False), encoding="utf-8")

    assert _shown(codex_cli.CodexCliSolver().answer_all(question=question)) == [([1], "④", "ready", "")]
    assert not _runs(codex())


def _grouped(*questions):
    """One read whose questions each fill the given answer numbers: (numbers, answer)."""
    return {"questions": [{"group": "第1問", "label": f"問{index}", "answer_no": list(numbers), "pages": [1],
                           "status": "ready", "answer": answer, "missing_material": "", "diagrams": []}
                          for index, (numbers, answer) in enumerate(questions, 1)]}


@pytest.mark.parametrize("first, second", [
    (_grouped(((1, 2, 3), "④、②、①")), _grouped(((1,), "④"), ((2,), "②"), ((3,), "①"))),
    (_grouped(((1,), "④"), ((2,), "②"), ((3,), "①")), _grouped(((1, 2, 3), "④、②、①"))),
    (_grouped(((1, 2), "④、②"), ((3,), "①")), _grouped(((1,), "4"), ((2, 3), "2,1"))),
    # As the model wrote them on the phone: the marks of one question separated by spaces.
    (_grouped(((1, 2, 3, 4, 5), "④ ④ ① ② ②"), ((6,), "③")), _grouped(((1,), "④"), ((2,), "④"), ((3,), "①"), ((4,), "②"), ((5,), "②"), ((6,), "③"))),
])
def test_reads_that_group_the_same_answer_numbers_differently_agree_number_by_number(codex, tmp_path, monkeypatch, first, second):
    """Phone, 2026-11-15, 47 pages: one read gave answer numbers 1 to 5 as one question and the other as five. Matched
    question by question, ten right answers of 35 were marked as listed by one read only."""
    _twice(monkeypatch, first, second)
    shown = _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert [numbers for numbers, _, _, _ in shown] == [question["answer_no"] for question in first["questions"]]
    assert [note for _, _, _, note in shown] == [""] * len(shown)


def test_a_number_the_reads_disagree_on_inside_a_question_of_several_numbers_is_named(codex, tmp_path, monkeypatch):
    _twice(monkeypatch, _grouped(((1, 2, 3), "④、②、①")), _grouped(((1,), "④"), ((2,), "③"), ((3,), "①")))
    [(numbers, answer, _, note)] = _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert (numbers, answer) == ([1, 2, 3], "④、②、①") and "2" in note and "3" in note and "1は" not in note


def test_a_separate_question_is_marked_when_the_other_reads_joined_question_differs_on_its_number(codex, tmp_path, monkeypatch):
    _twice(monkeypatch, _grouped(((1,), "④"), ((2,), "②"), ((3,), "①")), _grouped(((1, 2, 3), "④、③、①")))
    shown = _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert [bool(note) for _, _, _, note in shown] == [False, True, False] and "3" in shown[1][3]


def _boxed(group, *questions):
    """One read of a mark sheet whose answer boxes are lettered and carry no number: (label, answer)."""
    return {"questions": [{"group": group, "label": label, "answer_no": [], "pages": [1], "status": "ready",
                           "answer": answer, "missing_material": "", "diagrams": []} for label, answer in questions]}


def _labelled(replies):
    return [(item["label"], result.answer, result.extras.get("review_note", "")) for item, result in replies]


def test_reads_that_label_the_same_lettered_boxes_differently_agree_box_by_box(codex, tmp_path, monkeypatch):
    """Phone, 2026-11-17, forty pages of a mark sheet whose boxes are lettered: one read labelled a question "アイ"
    and the other "(1) アイ". Matched by the whole label nothing lined up: the 199 items of both reads were all
    shown, every one marked as listed by one read only."""
    first = _boxed("第1問", ("アイ", "12"), ("ウ", "3"), ("エオカ", "-45"))
    # The other read also named the part of the question, as it did on the phone: "(1)(ii) カ", "(1)(iii) サシス".
    second = _boxed("第１問", ("(1)(i) アイ", "12"), ("(1)(ii) ウ", "3"), ("(2) エ", "−"), ("〔2〕(a) オカ", "45"))
    _twice(monkeypatch, first, second)
    shown = _labelled(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert shown == [("アイ", "12", ""), ("ウ", "3", ""), ("エオカ", "-45", "")]


def test_a_lettered_box_the_reads_disagree_on_is_named_by_its_letter(codex, tmp_path, monkeypatch):
    _twice(monkeypatch, _boxed("第2問", ("アイ", "12"), ("ウ", "3")),
           _boxed("第2問", ("(1) ア", "1"), ("(1) イ", "7"), ("(1) ウ", "3")))
    shown = _labelled(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert shown[1] == ("ウ", "3", "")
    assert "イ" in shown[0][2] and "7" in shown[0][2] and "アは" not in shown[0][2]


def test_the_same_letters_under_another_question_group_are_other_boxes(codex, tmp_path, monkeypatch):
    first = {"questions": _boxed("第1問", ("ア", "1"))["questions"] + _boxed("第2問", ("ア", "5"))["questions"]}
    second = {"questions": _boxed("第1問", ("(1) ア", "1"))["questions"] + _boxed("第2問", ("(1) ア", "6"))["questions"]}
    _twice(monkeypatch, first, second)
    shown = _labelled(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert [bool(note) for _, _, note in shown] == [False, True]


def test_a_label_of_words_is_no_row_of_boxes_and_is_compared_whole_as_before(codex, tmp_path, monkeypatch):
    _twice(monkeypatch, _boxed("第1問", ("グラフの概形", "右上がり"), ("エネルギー", "保存される")),
           _boxed("第1問", ("グラフの概形", "右上がり"), ("エネルギー", "保存される")))
    shown = _labelled(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert shown == [("グラフの概形", "右上がり", ""), ("エネルギー", "保存される", "")]


def _unnumbered(*questions):
    """One read of a paper with no answer numbers and no lettered boxes: (group, label, pages, answer)."""
    return {"questions": [{"group": group, "label": label, "answer_no": [], "pages": pages, "status": "ready",
                           "answer": answer, "missing_material": "", "diagrams": []}
                          for group, label, pages, answer in questions]}


def _paged(replies):
    return [(item["label"], item["pages"], result.answer, result.extras.get("review_note", "")) for item, result in replies]


def test_reads_that_name_the_same_questions_differently_are_compared_in_order_page_by_page(codex, tmp_path, monkeypatch):
    """A paper with no answer numbers and no lettered boxes is compared by group and label, and one read writes
    第1問 / (1) where the other writes nothing / 1 (1): nothing lined up, the list doubled and every item of both
    reads was marked as listed by one read only. Then the k-th question a read gives for a page is the k-th the
    other gives for that page."""
    first = _unnumbered(("第1問", "(1)", [1], "12"), ("第1問", "(2)", [1], "右上がり"), ("第2問", "(1)", [2], "7"))
    second = _unnumbered(("", "1 (1)", [1], "12"), ("", "1 (2)", [1], "右上がり"), ("", "2 (1)", [2], "8"))
    _twice(monkeypatch, first, second)
    shown = _paged(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))

    assert [row[:3] for row in shown] == [("(1)", [1], "12"), ("(2)", [1], "右上がり"), ("(1)", [2], "7")]
    assert [row[3] for row in shown[:2]] == ["", ""] and "8" in shown[2][3], "the pair that differs is marked as differing"


@pytest.mark.parametrize("longer", ["second", "first"])
def test_what_one_read_has_more_of_on_a_page_is_what_is_left_over_as_given_by_one_read(codex, tmp_path, monkeypatch, longer):
    short = _unnumbered(("第1問", "(1)", [1], "12"), ("第2問", "(1)", [2], "7"))
    long = _unnumbered(("", "1 (1)", [1], "12"), ("", "1 (2)", [1], "右上がり"), ("", "2 (1)", [2], "7"))
    _twice(monkeypatch, *((short, long) if longer == "second" else (long, short)))
    shown = _paged(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))

    assert [row[1:3] for row in shown] == [([1], "12"), ([1], "右上がり"), ([2], "7")], "in its place, after its page's others"
    assert [row[3] for row in shown] == ["", codex_cli._ONE_LISTED, ""]


def test_sub_questions_named_differently_between_questions_both_reads_name_are_paired_in_order(codex, tmp_path, monkeypatch):
    """Phone, 2026-11-18, twelve pages read twice by GPT-6.2 Sol: one read named the parts of a question "(1)（Ⅰ）" and
    the other "（Ⅰ）". Most labels lined up, so the reads were compared by label, and every part so named came out
    twice, once from each read, each marked as listed by one read only: 47 items for some 34 questions, 22 marks."""
    same = [(f"({number})", "ウ") for number in range(2, 8)]
    first = _boxed("【一】", ("(1)（Ⅰ）", "ア"), ("(1)（Ⅱ）", "イ"), *same, ("(8)（Ⅰ）", "オ"), ("(8)（Ⅱ）", "カ"), ("(9)", "キ"))
    second = _boxed("【一】", ("（Ⅰ）", "ア"), ("（Ⅱ）", "エ"), *[(f"（{number}）", "ウ") for number in range(2, 8)],
                    ("（Ⅰ）", "オ"), ("（Ⅱ）", "カ"), ("（9）", "キ"))
    _twice(monkeypatch, first, second)
    shown = _labelled(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert [label for label, _, _ in shown] == [question["label"] for question in first["questions"]], "eleven questions, not fifteen"
    assert [bool(note) for _, _, note in shown] == [False, True] + [False] * 9, "the one that differs"
    assert "エ" in shown[1][2]


def test_a_stretch_the_reads_split_differently_is_left_as_it_was(codex, tmp_path, monkeypatch):
    """One read gives a question as one item and the other as three: nothing says which belongs to which."""
    first = _boxed("【三】", ("(1)", "ア"), ("(2)", "イ ウ エ"), ("(3)", "オ"), ("(4)", "カ"))
    second = _boxed("【三】", ("（1）", "ア"), ("（ア）", "イ"), ("（イ）", "ウ"), ("（ウ）", "エ"), ("（3）", "オ"), ("（4）", "カ"))
    _twice(monkeypatch, first, second)
    shown = _labelled(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))
    assert len(shown) == 7 and sum(1 for _, _, note in shown if note) == 4


def test_reads_whose_labels_do_line_up_are_compared_by_label_as_before_whatever_their_order(codex, tmp_path, monkeypatch):
    first = _unnumbered(("第1問", "(1)", [1], "12"), ("第1問", "(2)", [1], "3"), ("第1問", "(3)", [1], "5"))
    second = _unnumbered(("第1問", "(2)", [1], "3"), ("第1問", "(1)", [1], "12"), ("第１問", "（３）", [1], "6"))
    _twice(monkeypatch, first, second)
    shown = _paged(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path)))

    assert [row[0] for row in shown] == ["(1)", "(2)", "(3)"]
    assert [bool(row[3]) for row in shown] == [False, False, True] and "6" in shown[2][3]


class _Handed:
    """What the route hands over when its first read is back, and when."""

    def __init__(self):
        self.calls = []

    def __call__(self, replies):
        self.calls.append((time.monotonic(), replies))


def _same_questions(first, replies):
    """The compared answers stand on the very items the first read's answers were handed over with: the server saves
    them over the same questions."""
    return all(early is late for (early, _), (late, _) in zip(first, replies))


def test_the_first_read_back_is_handed_over_at_once_and_the_compared_answers_follow(codex, tmp_path, monkeypatch, capsys):
    """The operator's use of 2026-11-18: one read of a booklet was back minutes before the other, which was ended at
    its limit. The answers were held for the slower read and reached the server ten and a half minutes after the
    capture ended; the wearer had given up. The first read's answers go out when that read is back."""
    _twice(monkeypatch, _read((1, "④"), (2, "②")), _read((1, "④"), (2, "③")))
    monkeypatch.setenv("ROKID_CODEX_LOCATE", "0")
    monkeypatch.setenv("FAKE_CODEX_SLEEP_2", "3")
    handed = _Handed()
    replies = codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path, on_first_read=handed))
    returned = time.monotonic()

    [(at, first)] = handed.calls
    assert returned - at > 1.5, "while the other read was still running"
    assert _shown(first) == [([1], "④", "ready", ""), ([2], "②", "ready", "")]
    assert [result.extras.get("read_once") for _, result in first] == [True, True], "nothing is compared yet"
    one, two = _shown(replies)
    assert one == ([1], "④", "ready", "") and two[:3] == ([2], "②", "ready") and "③" in two[3]
    assert not any("read_once" in result.extras for _, result in replies)
    assert _same_questions(first, replies)
    done = sorted(_logged(capsys, "codex_read_done"), key=lambda line: line["read"])
    assert [line["read"] for line in done] == [1, 2] and done[1]["seconds"] >= 3.0
    assert done[1]["seconds"] - done[0]["seconds"] > 1.5, "each read's own time, so how far apart they end"
    assert all(set(line) == {"event", "read", "seconds"} for line in done), "no reply text in the log"


def test_whichever_read_is_back_first_is_handed_over_and_the_other_is_compared_with_it(codex, tmp_path, monkeypatch):
    _twice(monkeypatch, _read((1, "④"), (2, "②")), _read((1, "④"), (2, "③")))
    monkeypatch.setenv("ROKID_CODEX_LOCATE", "0")
    monkeypatch.setenv("FAKE_CODEX_SLEEP", "3")
    monkeypatch.setenv("FAKE_CODEX_SLEEP_2", "0")
    handed = _Handed()
    question = _booklet(tmp_path, on_first_read=handed)
    replies = codex_cli.CodexCliSolver().answer_all(question=question)

    [(_, first)] = handed.calls
    assert _shown(first)[1][:2] == ([2], "③"), "the second request's reply was back first"
    shown = _shown(replies)
    assert shown[1][:2] == ([2], "③") and "②" in shown[1][3] and _same_questions(first, replies)
    # Kept in that order: a repeat runs nothing, hands nothing over and shows what was shown.
    question.on_first_read = again = _Handed()
    assert _shown(codex_cli.CodexCliSolver().answer_all(question=question)) == shown
    assert not again.calls and len(_runs(codex())) == 2


def test_a_read_cut_behind_the_one_handed_over_leaves_that_ones_answers_as_read_once(codex, tmp_path, monkeypatch):
    """The route has answered once its first read is out: the other read failing or being ended raises nothing."""
    _twice(monkeypatch, _read((1, "④")), _read((1, "④")))
    monkeypatch.setenv("ROKID_CODEX_LOCATE", "0")
    monkeypatch.setenv("FAKE_CODEX_SLEEP_2", "120")
    monkeypatch.setenv("ROKID_CODEX_TIMEOUT_S", "30")
    monkeypatch.setattr(codex_cli, "_SECOND_READ_LEAST_S", 0.5)
    handed = _Handed()
    replies = codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path, on_first_read=handed))

    [(_, first)] = handed.calls
    assert _shown(replies) == [([1], "④", "ready", "")] and _same_questions(first, replies)
    assert [result.extras.get("read_once") for _, result in replies] == [True]


def test_a_hand_over_that_fails_costs_neither_read(codex, tmp_path, monkeypatch, capsys):
    def refused(replies):
        raise RuntimeError("the caller could not take 問2 ②")

    _twice(monkeypatch, _read((1, "④"), (2, "②")), _read((1, "④"), (2, "③")))
    monkeypatch.setenv("ROKID_CODEX_LOCATE", "0")
    monkeypatch.setenv("FAKE_CODEX_SLEEP_2", "2")
    shown = _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path, on_first_read=refused)))

    assert shown[1][:2] == ([2], "②") and "③" in shown[1][3], "both reads, compared as ever"
    printed = capsys.readouterr().out
    [cause] = [json.loads(line) for line in printed.splitlines() if '"codex_first_read_not_handed"' in line]
    assert cause["type"] == "RuntimeError" and cause["at"]
    assert "問2" not in printed and "②" not in printed, "which kind and where, never its message"


def test_a_booklet_asked_for_once_is_not_handed_over_early(codex, tmp_path, capsys):
    handed = _Handed()
    replies = codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path, on_first_read=handed))  # one read

    assert len(replies) == 2 and not handed.calls
    [done] = _logged(capsys, "codex_read_done")
    assert done["read"] == 1 and set(done) == {"event", "read", "seconds"}


def test_a_first_read_that_gave_nothing_usable_is_not_handed_over(codex, tmp_path, monkeypatch):
    _twice(monkeypatch, _read((1, "④")), _read((1, "④")))
    monkeypatch.setenv("ROKID_CODEX_LOCATE", "0")
    monkeypatch.setenv("FAKE_CODEX_REPLY", "I could not read the pages.")
    monkeypatch.setenv("FAKE_CODEX_SLEEP_2", "2")
    handed = _Handed()
    replies = codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path, on_first_read=handed))

    assert _shown(replies) == [([1], "④", "ready", "")] and not handed.calls


def test_an_answer_only_the_second_read_gave_stands_under_the_first_reads_question(codex, tmp_path, monkeypatch):
    """The first read's questions are what the wearer may already be reading: an answer the second read alone gave
    goes under that question as the first read named it. Until 2026-11-18 it brought the second read's item along."""
    second = _read((1, "④"))
    second["questions"][0]["label"] = "問一"
    _twice(monkeypatch, _read((1, None)), second)
    [(item, result)] = codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path))

    assert (item["label"], result.answer, result.extras["review_note"]) == ("問1", "④", codex_cli._ONE_ANSWERED)


# A read in parts (ROKID_CODEX_PARTS, off unless set). A small request beside the one that locates the pages asks on
# which captures the booklet's major problems begin. The first read is then one request for each group of major
# problems, all at the same time, each with its own captures at full size and the others as their small overviews at
# most; the second read is whole, as ever. Until the night of 2026-11-18 every part of both reads carried every image:
# twelve pages in three parts sent six times what one whole read sends (about 500 MB in an hour of trials on Wi-Fi),
# where that morning's use, two whole reads a booklet over the mobile network, had sent 50 to 60 MB a booklet.


def _item(number, answer, pages, group="第1問"):
    """A made-up question that fills the printed answer number ``number`` and cites the capture pages ``pages``."""
    return {"group": group, "label": f"問{number}", "answer_no": [number], "pages": pages, "status": "ready",
            "answer": answer, "missing_material": "", "diagrams": []}


def _parts(monkeypatch, count, requests=None, starts=None):
    """The first read in ``count`` requests at most, the booklet's major problems beginning on the capture pages
    ``starts`` (none told when left out). ``requests`` says what the stand-in does for one request, named by its
    reply file ("1-2" is the second part of the first read, "2" the second read, which is whole): the questions of
    its reply or its reply as text, a failure, seconds of sleep. A request not named replies as a whole read does."""
    monkeypatch.setenv("ROKID_CODEX_PARTS", str(count))
    monkeypatch.setenv("ROKID_CODEX_LOCATE", "0")
    if starts is not None:
        monkeypatch.setenv("FAKE_CODEX_OUTLINE", json.dumps({"starts": starts}))
    monkeypatch.setenv("FAKE_CODEX_PARTS", json.dumps({
        f"reply-{name}.json": {"reply": json.dumps({"questions": does["questions"]}, ensure_ascii=False), **does}
        if "questions" in does else does for name, does in (requests or {}).items()}, ensure_ascii=False))


def _events(printed, event):
    return [json.loads(line) for line in printed.splitlines() if f'"{event}"' in line]


def _sent(calls):
    """Every call's arguments, its reply file by name alone: each run works in a folder of its own."""
    sent = []
    for call in calls:
        args = list(call["args"])
        if "-o" in args:
            args[args.index("-o") + 1] = Path(args[args.index("-o") + 1]).name
        sent.append(args)
    return sorted(sent)


def _attached(call):
    args = call["args"]
    return [args[index + 1] for index, value in enumerate(args) if value == "-i"]


_WHOLE = codex_cli._ANSWER_ONLY_SYSTEM + "\n\n" + codex_cli._ALL_TASK + codex_cli._IMAGES_NOTE


@pytest.mark.parametrize("reads, parts, pages", [("1", "1", 4), ("2", "1", 4), ("2", "0", 4), ("2", "3", 3),
                                                 ("2", "three", 4)])
def test_one_part_asks_exactly_what_is_asked_without_the_setting(codex, tmp_path, monkeypatch, capsys, reads, parts, pages):
    """The default, a booklet of fewer than four pages whatever is set, and a setting that is no number (which is
    said, and gives no booklet away): the same requests to the last byte, and nothing asked about major problems."""
    monkeypatch.setenv("ROKID_CODEX_READS", reads)
    question = _booklet(tmp_path, pages=pages)
    codex_cli.CodexCliSolver().answer_all(question=question)
    before = codex()
    codex_cli.CodexCliSolver._kept(question).unlink()
    monkeypatch.setenv("ROKID_CODEX_PARTS", parts)
    codex_cli.CodexCliSolver().answer_all(question=question)

    after = codex()[len(before):]
    assert _sent(after) == _sent(before)
    assert not _outlines(after)
    # ... and that is the request as it was before there were parts: its files' names, and not a word after it.
    assert sorted(call["reply_file"] for call in _runs(after)) == (
        ["reply.json"] if reads == "1" else ["reply-1.json", "reply-2.json"])
    assert all(call["args"][-1] == _WHOLE for call in _runs(after))
    assert len(_events(capsys.readouterr().out, "codex_parts_setting_ignored")) == (parts == "three")


def test_the_major_problems_are_asked_for_beside_the_request_that_locates_the_pages(codex, tmp_path, monkeypatch):
    """Phone's model through the PC's CLI, 2026-11-18: four booklets of that day's use, twice each, from 1024-px
    views at low effort: the same captures both times, and those the full reads' own question lists begin on."""
    monkeypatch.setenv("ROKID_CODEX_PARTS", "3")
    monkeypatch.setenv("FAKE_CODEX_LOCATE_SLEEP", "2")
    monkeypatch.setenv("FAKE_CODEX_OUTLINE_SLEEP", "2")
    codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path, pages=4))

    [outline] = _outlines(codex())
    [locate] = _locates(codex())
    assert list(outline["sizes"]) == [f"capture{number:03d}.jpg" for number in range(1, 5)]
    assert all(max(size) <= 1024 for size in outline["sizes"].values())
    args = outline["args"]
    assert "model_reasoning_effort=low" in args and outline["schema"]["required"] == ["starts", "shared"]
    assert "for the whole exam" in args[-1]
    assert "major problem" in args[-1] and "capture page" in args[-1]
    assert outline["started"] < locate["ended"] and locate["started"] < outline["ended"], "at the same time"
    assert not any(name.startswith("capture") for call in _runs(codex()) for name in call["sizes"])


def test_the_major_problems_are_shared_out_among_the_parts_which_meet_on_the_capture_the_next_begins_on():
    """(first, last capture whose major problems it answers, last capture it is sent at full size). A major problem
    ends partway down the capture the next one begins on, so that capture goes to both parts."""
    spans = codex_cli._section_spans
    twelve = list(range(1, 13))
    assert spans(twelve, [1, 3, 6], 3) == [(1, 2, 3), (3, 5, 6), (6, 12, 12)]
    assert spans(twelve, [1, 5, 9], 3) == [(1, 4, 5), (5, 8, 9), (9, 12, 12)]
    assert spans(twelve, [6, 3, 3, 1], 3) == [(1, 2, 3), (3, 5, 6), (6, 12, 12)], "in any order, each once"
    assert spans(twelve, [3, 6], 3) == [(1, 2, 3), (3, 5, 6), (6, 12, 12)], "the first capture is a start whatever is said"
    # More major problems than parts: neighbours share a part, and the largest share of captures is as small as can be.
    assert spans(list(range(1, 9)), list(range(1, 9)), 3) == [(1, 2, 3), (3, 5, 6), (6, 8, 8)]
    assert spans(twelve, [1, 3, 6], 2) == [(1, 5, 6), (6, 12, 12)]
    assert spans([1, 2, 4, 5, 7, 8], [1, 4, 7], 3) == [(1, 2, 4), (4, 5, 7), (7, 8, 8)], "by the capture pages the booklet has"
    assert spans(twelve, list(range(1, 13)), 9) == spans(twelve, list(range(1, 13)), codex_cli._PARTS_MOST)
    # No second start, nothing usable, or one part asked for: no parts, which is the read as it was.
    for starts in ([1], [], [0, 99, "3", None, 2.5, True], "1, 3, 6", None):
        assert spans(twelve, starts, 3) == []
    assert spans(twelve, [1, 3, 6], 1) == [] == spans([], [1, 3], 3)


def test_twelve_pages_of_three_major_problems_are_three_requests_and_the_whole_read_at_the_same_time(
        codex, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ROKID_CODEX_READS", raising=False)  # the default of two
    _parts(monkeypatch, 3, starts=[1, 5, 9])
    monkeypatch.setenv("FAKE_CODEX_SLEEP", "3")  # four processes to start before the first of them ends
    codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path, pages=12))

    runs = {call["reply_file"]: call for call in _runs(codex())}
    assert sorted(runs) == ["reply-1-1.json", "reply-1-2.json", "reply-1-3.json", "reply-2.json"], "a file each"
    assert max(call["started"] for call in runs.values()) < min(call["ended"] for call in runs.values()), "at the same time"
    whole = runs.pop("reply-2.json")
    assert _attached(whole) == [f"page{number:03d}.jpg" for number in range(1, 13)] and whole["args"][-1] == _WHOLE, (
        "the second read is the whole read as it was")
    shares = {"1": (1, 4, 5), "2": (5, 8, 9), "3": (9, 12, 12)}
    for name, call in runs.items():
        first, own_last, last = shares[name[len("reply-1-")]]
        assert _attached(call) == [f"page{number:03d}.jpg" for number in range(first, last + 1)], (
            "its own captures and the one the next part begins on, nothing else at full size")
        assert call["args"][-1].startswith(_WHOLE), "the whole request as a read in one piece has it"
        added = call["args"][-1][len(_WHOLE):]
        assert f"major problems that begin on capture pages {first} to {own_last}" in added
        assert f"at full size: capture pages {first} to {last}" in added
        others = [share for share in shares.values() if share != (first, own_last, last)]
        assert not any(f"begin on capture pages {other[0]} to {other[1]}" in added for other in others)
        assert "needs_input" in added and "overview" in added and '{"questions":[]}' in added
    # What the first read sends: every capture once and the two the parts meet on twice, not three times the booklet.
    assert sum(len(_attached(call)) for call in runs.values()) == 12 + 2
    printed = capsys.readouterr().out
    [told] = _events(printed, "codex_outline")
    assert (told["starts"], told["shared"]) == (3, 0) and set(told) == {"event", "starts", "shared", "seconds"}
    assert _events(printed, "codex_plan") == [{"event": "codex_plan", "pages": 12, "parts": 3, "parts_long": None, "whole_long": None}]


def test_a_part_is_sent_every_overview_and_the_enlarged_regions_of_its_own_captures_only(codex, tmp_path, monkeypatch):
    monkeypatch.setenv("ROKID_CODEX_PARTS", "2")
    monkeypatch.setenv("FAKE_CODEX_OUTLINE", json.dumps({"starts": [1, 3]}))
    monkeypatch.setenv("FAKE_CODEX_REGIONS", json.dumps({"images": [
        {"index": number, "regions": [{"left": 100, "top": 100, "right": 900, "bottom": 900, "vertical_text": False}]}
        for number in range(1, 5)]}))
    codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path, pages=4))

    runs = {call["reply_file"]: call for call in _runs(codex())}
    assert sorted(runs) == ["reply-1-1.json", "reply-1-2.json"], "one read asked for: that read, in its parts"
    for name, captures in (("reply-1-1.json", {1, 2, 3}), ("reply-1-2.json", {3, 4})):
        names = _attached(runs[name])
        assert [one for one in names if one.startswith("overview")] == [f"overview{number:03d}.jpg" for number in range(1, 5)]
        assert {int(one[4:7]) for one in names if one.startswith("page")} == captures
        assert len(names) > 4 and "small overview" in runs[name]["args"][-1]


@pytest.mark.parametrize("told", [{"FAKE_CODEX_OUTLINE": '{"starts": []}'}, {"FAKE_CODEX_OUTLINE": '{"starts": [1]}'},
                                  {"FAKE_CODEX_OUTLINE": "I cannot tell."},
                                  {"FAKE_CODEX_OUTLINE_FAIL": "error sending request for url"},
                                  {"FAKE_CODEX_OUTLINE_FAIL": "ERROR: You've hit your usage limit. Try again in 3 hours."}],
                         ids=["none", "one start", "prose", "fails", "limit"])
def test_a_booklet_whose_major_problems_are_not_told_is_read_whole_twice_as_without_the_setting(
        codex, tmp_path, monkeypatch, capsys, told):
    """Captures shared out by their count alone would part a passage from its questions. A request about the major
    problems that fails costs the booklet nothing: the reads say for themselves what is wrong with the route."""
    monkeypatch.delenv("ROKID_CODEX_READS", raising=False)
    _parts(monkeypatch, 3)
    for name, value in told.items():
        monkeypatch.setenv(name, value)
    replies = codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path, pages=6))

    runs = _runs(codex())
    assert sorted(call["reply_file"] for call in runs) == ["reply-1.json", "reply-2.json"]
    assert all(call["args"][-1] == _WHOLE and len(_attached(call)) == 6 for call in runs)
    assert len(replies) == 2
    printed = capsys.readouterr().out
    [line] = _events(printed, "codex_outline")
    assert set(line) == {"event", "starts", "shared", "seconds"}
    assert _events(printed, "codex_plan") == [{"event": "codex_plan", "pages": 6, "parts": 0, "parts_long": None, "whole_long": None}]
    assert "cannot tell" not in printed and "usage limit" not in printed


def test_a_read_is_its_parts_question_lists_joined_in_page_order_however_the_parts_came_back(
        codex, tmp_path, monkeypatch, capsys):
    """Everything behind the requests is given one reply of the usual shape for each read. A part on whose pages no
    major problem begins replies with an empty list, which is no failure."""
    _parts(monkeypatch, 3, {"1-1": {"questions": [_item(1, "④", [1]), _item(2, "②", [2])], "sleep": 3},
                            "1-2": {"questions": []},
                            "1-3": {"questions": [_item(3, "①", [5]), _item(4, "③", [6])]}}, starts=[1, 3, 5])
    question = _booklet(tmp_path, pages=6)
    replies = codex_cli.CodexCliSolver().answer_all(question=question)

    assert _shown(replies) == [([1], "④", "ready", ""), ([2], "②", "ready", ""), ([3], "①", "ready", ""),
                               ([4], "③", "ready", "")]
    [kept] = json.loads(codex_cli.CodexCliSolver._kept(question).read_text(encoding="utf-8"))["reads"]
    assert set(kept) == {"questions"} and [item["answer_no"] for item in kept["questions"]] == [[1], [2], [3], [4]]
    printed = capsys.readouterr().out
    parts = sorted(_events(printed, "codex_part_done"), key=lambda line: line["part"])
    assert [(line["read"], line["part"], line["pages"]) for line in parts] == [(1, 1, "1-2"), (1, 2, "3-4"), (1, 3, "5-6")]
    assert all(set(line) == {"event", "read", "part", "pages", "seconds"} for line in parts), "no reply text in the log"
    [done] = _events(printed, "codex_read_done")
    assert done["seconds"] >= parts[0]["seconds"] >= 3.0, "the read is back with its last part"
    assert parts[0]["seconds"] > parts[1]["seconds"], "and the first part was the last one back"
    assert not _events(printed, "codex_parts_duplicate")


@pytest.mark.parametrize("pages, kept", [([2, 3], "②"), ([2], "②"), ([3], "③"), ([3, 2], "③"), ([9], "②")])
def test_a_question_two_parts_both_list_stays_once_from_the_part_its_first_page_lies_in_else_from_the_first(
        codex, tmp_path, monkeypatch, capsys, pages, kept):
    """A question on the capture two parts meet on may be listed by both. The same question: the same group and
    label (as they are compared: full-width or not, spaced or not), the same printed answer numbers, a capture page
    in common."""
    _parts(monkeypatch, 2, {"1-1": {"questions": [_item(1, "④", [1]), _item(2, "②", pages)]},
                            "1-2": {"questions": [_item(2, "③", pages, group="第１問"), _item(3, "①", [4])]}}, starts=[1, 3])
    shown = _shown(codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path, pages=4)))

    assert [(numbers, answer) for numbers, answer, _, _ in shown] == [([1], "④"), ([2], kept), ([3], "①")]
    printed = capsys.readouterr().out
    assert _events(printed, "codex_parts_duplicate") == [{"event": "codex_parts_duplicate", "read": 1, "count": 1}]
    assert not any(text in printed for text in ("問2", "②", "③")), "how many, never what"


_LEFT_OUT = {"group": "", "label": "", "answer_no": [], "pages": [2, 3], "status": "needs_input", "answer": "",
             "missing_material": "3頁の続きが無い", "diagrams": []}


@pytest.mark.parametrize("first, second", [
    (_item(2, "②", [2]), _item(2, "③", [3])),  # no capture page in common: answer numbers restart in another section
    ({**_item(2, "②", [2, 3]), "answer_no": []}, {**_item(2, "③", [2, 3]), "answer_no": []}),  # no printed number
    (_LEFT_OUT, _LEFT_OUT),  # what the captures leave out names no question
], ids=["other pages", "no answer number", "nothing printed"])
def test_what_may_be_another_question_under_the_same_name_is_never_dropped(codex, tmp_path, monkeypatch, capsys, first, second):
    """"Printed answer numbers may restart in another section or question, even under the same labels" (the request's
    own words): a question dropped for its name alone would be lost with nothing said. Listed twice it is seen."""
    _parts(monkeypatch, 2, {"1-1": {"questions": [_item(1, "④", [1]), first]},
                            "1-2": {"questions": [second, _item(3, "①", [4])]}}, starts=[1, 3])
    replies = codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path, pages=4))

    assert len(replies) == 4 and not _events(capsys.readouterr().out, "codex_parts_duplicate")


_BOTH = {"questions": [_item(1, "④", [1]), _item(2, "②", [3])]}


@pytest.mark.parametrize("does, logged", [
    ({"fail": "error sending request for url (https://chatgpt.com/backend-api/codex/responses)"}, "codex_read_failed"),
    ({"reply": "I could not read the pages."}, "codex_read_failed"),
    ({"reply": '{"questions": "none"}'}, "codex_read_failed"),
    ({"reply": json.dumps({"questions": [_item(2, "②", [3])], "note": "a made-up remark"}, ensure_ascii=False)},
     "codex_reply_unusable"),
], ids=["fails", "prose", "no list", "a stray top-level key"])
def test_a_part_that_fails_or_cannot_be_used_fails_its_read_and_the_whole_read_answers_alone(
        codex, tmp_path, monkeypatch, capsys, does, logged):
    monkeypatch.delenv("ROKID_CODEX_READS", raising=False)
    _parts(monkeypatch, 2, {"1-1": {"questions": [_item(1, "④", [1])]}, "1-2": does, "2": _BOTH}, starts=[1, 3])
    replies = codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path, pages=4))

    assert _shown(replies) == [([1], "④", "ready", ""), ([2], "②", "ready", "")]
    assert [result.extras.get("read_once") for _, result in replies] == [True, True], "nothing was compared"
    printed = capsys.readouterr().out
    [cause] = _events(printed, logged)
    assert set(cause) == {"event", "type", "at"} and "made-up" not in printed and "could not read" not in printed
    assert len(_runs(codex())) == 3


@pytest.mark.parametrize("requests, everywhere, raised", [
    # A part that merely failed stands before the one at the limit, and the whole read is at the limit: it decides.
    ({"1-1": {"fail": "error sending request"}, "1-2": {"fail": "ERROR: You've hit your usage limit. Try again in 3 hours."},
      "2": {"fail": "ERROR: You've hit your usage limit. Try again in 3 hours."}}, None, ChatGptWebRateLimit),
    ({}, _MODEL_GONE[0], ChatGptWebModelMismatch),
], ids=["usage limit", "model gone"])
def test_a_usage_limit_or_a_model_that_is_gone_leaves_a_read_in_parts_as_it_leaves_a_whole_read(
        codex, tmp_path, monkeypatch, requests, everywhere, raised):
    monkeypatch.delenv("ROKID_CODEX_READS", raising=False)
    _parts(monkeypatch, 2, requests, starts=[1, 3])
    if everywhere:
        monkeypatch.setenv("FAKE_CODEX_FAIL", everywhere)
    with pytest.raises(ChatGptWebError) as error:
        codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path, pages=4))
    assert type(error.value) is raised


def test_a_read_one_of_whose_parts_hangs_behind_the_finished_whole_read_is_cut_and_that_read_answers_alone(
        codex, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ROKID_CODEX_READS", raising=False)
    _parts(monkeypatch, 2, {"1-1": {"questions": [_item(1, "④", [1])]},
                            "1-2": {"questions": [_item(2, "②", [3])], "sleep": 120},
                            # The whole read is back after the parts have started: one of them has ended by then.
                            "2": {**_BOTH, "sleep": 4}}, starts=[1, 3])
    monkeypatch.setenv("ROKID_CODEX_TIMEOUT_S", "30")
    monkeypatch.setattr(codex_cli, "_SECOND_READ_MOST_S", 0.5)
    started = time.monotonic()
    replies = codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path, pages=4))

    assert time.monotonic() - started < 20, "not the hung part's time, and not the limit"
    assert _shown(replies) == [([1], "④", "ready", ""), ([2], "②", "ready", "")]
    assert [result.extras.get("read_once") for _, result in replies] == [True, True]
    printed = capsys.readouterr().out
    assert len(_events(printed, "codex_read_cut")) == 1
    assert [line["read"] for line in _events(printed, "codex_read_done")] == [2]
    assert sorted(call["reply_file"] for call in _runs(codex())) == ["reply-1-1.json", "reply-2.json"], (
        "the part that hung never ended by itself")


def test_the_whole_read_behind_a_read_in_parts_is_waited_for_longer_than_that_read_took(
        codex, tmp_path, monkeypatch, capsys):
    """A read in parts is back in a fraction of the time the whole read takes. Waited for only as long again as
    the first read took, the whole read would be ended every time and nothing would ever be compared."""
    monkeypatch.delenv("ROKID_CODEX_READS", raising=False)
    monkeypatch.setattr(codex_cli, "_SECOND_READ_LEAST_S", 0.2)
    _parts(monkeypatch, 2, {"1-1": {"questions": [_item(1, "④", [1])]}, "1-2": {"questions": [_item(2, "②", [3])]},
                            "2": {**_BOTH, "sleep": 8}}, starts=[1, 3])
    replies = codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path, pages=4))

    printed = capsys.readouterr().out
    assert not _events(printed, "codex_read_cut")
    assert [line["read"] for line in _events(printed, "codex_read_done")] == [1, 2]
    assert [result.extras.get("read_once") for _, result in replies] == [None, None], "both reads were compared"


def test_in_parts_the_first_read_is_handed_over_whole_and_once_and_the_compared_answers_follow(
        codex, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ROKID_CODEX_READS", raising=False)
    _parts(monkeypatch, 2, {"1-1": {"questions": [_item(1, "④", [1])]},
                            "1-2": {"questions": [_item(2, "②", [3])], "sleep": 1.5},
                            "2": {"questions": [_item(1, "④", [1]), _item(2, "③", [3])], "sleep": 5}}, starts=[1, 3])
    handed = _Handed()
    began = time.monotonic()
    replies = codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path, pages=4, on_first_read=handed))
    returned = time.monotonic()

    [(at, early)] = handed.calls
    assert at - began >= 1.5, "not before the last part of that read was back"
    assert returned - at > 1.5, "while the whole read was still running"
    assert _shown(early) == [([1], "④", "ready", ""), ([2], "②", "ready", "")], "a whole read's answers, not a part's"
    assert [result.extras.get("read_once") for _, result in early] == [True, True]
    one, two = _shown(replies)
    assert one == ([1], "④", "ready", "") and two[:3] == ([2], "②", "ready") and "③" in two[3]
    assert _same_questions(early, replies)
    printed = capsys.readouterr().out
    parts = _events(printed, "codex_part_done")
    assert sorted((line["read"], line["part"], line["pages"]) for line in parts) == [(1, 1, "1-2"), (1, 2, "3-4")]
    done = {line["read"]: line for line in _events(printed, "codex_read_done")}
    assert sorted(done) == [1, 2] and all(set(line) == {"event", "read", "seconds"} for line in done.values())
    assert all(done[1]["seconds"] >= line["seconds"] for line in parts), "a read ends with its last part"
    assert done[1]["seconds"] >= 1.5 and done[2]["seconds"] >= 5.0


# A booklet too long for one request (a common test is some forty pages). Until the night of 2026-11-18 every page
# of such a booklet was brought to a smaller size until all fitted the model's context (0.72 of its own at 36 gathered
# pages, 0.61 at 48), for both reads, and nothing said so. The operator: a risk like that is to be held down
# beforehand. Measured that night on a page with a known text (M-44 (20)): at those sizes it read as at its own. What
# is done all the same, for print smaller than that page's: the first read is made in parts by the major problems,
# each part's pages at their own size, in as many parts as that takes; the second read is the whole booklet in one
# request, reduced as far as it has to be, and is the read that has every page in view. What is for the whole exam
# (how to answer, tables) goes with every part. A booklet whose major problems are not told is read whole and reduced
# both times, and the answers say so.

_SIX_REGIONS = {"images": [{"index": number, "regions": [
    {"left": 100, "top": 100, "right": 900, "bottom": 900, "vertical_text": False}]} for number in range(1, 7)]}


def _too_long_for_one(monkeypatch, starts, shared=(), fits=4, long_sides=(300.0,)):
    """Six located pages of which ``fits`` go into one request at their own size: more are held to a long side of
    ``long_sides[0]`` px (and a request of at most four pages to ``long_sides[1]``, when given)."""
    def target(regions, spent):
        if len(regions) <= fits:
            return math.inf
        return long_sides[1] if len(long_sides) > 1 and len(regions) <= 4 else long_sides[0]

    monkeypatch.setattr(codex_cli, "_target_long", target)
    monkeypatch.setattr(codex_cli, "_might_not_fit", lambda sizes: True)
    monkeypatch.setenv("FAKE_CODEX_OUTLINE", json.dumps({"starts": list(starts), "shared": list(shared)}))


def _own_sizes(codex, tmp_path, monkeypatch):
    """The booklet of six pages, each image's size when everything fits one request, and the calls made so far."""
    monkeypatch.delenv("ROKID_CODEX_READS", raising=False)  # two reads
    monkeypatch.setenv("FAKE_CODEX_REGIONS", json.dumps(_SIX_REGIONS))
    question = _booklet(tmp_path, pages=6)
    codex_cli.CodexCliSolver().answer_all(question=question)
    calls = codex()
    assert sorted(call["reply_file"] for call in _runs(calls)) == ["reply-1.json", "reply-2.json"] and not _outlines(calls)
    codex_cli.CodexCliSolver._kept(question).unlink()
    return question, {name: size for call in _runs(calls) for name, size in call["sizes"].items()}, len(calls)


def _tiles(call):
    return [(image, size) for image, size in call["sizes"].items() if "-" in image]


def test_a_booklet_too_long_for_one_request_is_read_in_parts_at_full_size_and_whole_at_the_size_that_fits(
        codex, tmp_path, monkeypatch, capsys):
    question, own, before = _own_sizes(codex, tmp_path, monkeypatch)
    _too_long_for_one(monkeypatch, starts=[1, 4])
    capsys.readouterr()
    replies = codex_cli.CodexCliSolver().answer_all(question=question)

    runs = {call["reply_file"]: call for call in _runs(codex()[before:])}
    assert sorted(runs) == ["reply-1-1.json", "reply-1-2.json", "reply-2.json"]
    for name, pages in (("reply-1-1.json", {1, 2, 3, 4}), ("reply-1-2.json", {4, 5, 6})):
        assert {int(image[4:7]) for image, _ in _tiles(runs[name])} == pages
        assert all(size == own[image] for image, size in runs[name]["sizes"].items()), "every image at its own size"
    whole = _tiles(runs["reply-2.json"])
    assert {int(image[4:7]) for image, _ in whole} == {1, 2, 3, 4, 5, 6}
    assert all(max(size) <= 300 < max(own[image]) for image, size in whole), "the whole booklet at the size that fits"
    assert [name for name in runs["reply-2.json"]["sizes"] if name.startswith("overview")] == [
        f"overview{number:03d}.jpg" for number in range(1, 7)]
    [plan] = _events(capsys.readouterr().out, "codex_plan")
    assert plan == {"event": "codex_plan", "pages": 6, "parts": 2, "parts_long": None, "whole_long": 300}
    assert not any(result.extras.get("pages_reduced") for _, result in replies), "one read saw every page at its own size"
    assert len(replies) == 2


def test_a_long_booklet_is_given_more_parts_than_were_set_until_each_fits(codex, tmp_path, monkeypatch, capsys):
    """Six pages of which three fit a request, two parts set: the major problems begin on every page, and three
    parts hold them without reducing a page."""
    question, own, before = _own_sizes(codex, tmp_path, monkeypatch)
    _too_long_for_one(monkeypatch, starts=[1, 2, 3, 4, 5, 6], fits=3)
    monkeypatch.setenv("ROKID_CODEX_PARTS", "2")
    capsys.readouterr()
    codex_cli.CodexCliSolver().answer_all(question=question)

    runs = {call["reply_file"]: call for call in _runs(codex()[before:])}
    [plan] = _events(capsys.readouterr().out, "codex_plan")
    assert (plan["parts"], plan["parts_long"], plan["whole_long"]) == (3, None, 300), "two parts would hold four pages each"
    assert sorted(runs) == ["reply-1-1.json", "reply-1-2.json", "reply-1-3.json", "reply-2.json"]
    assert all(size == own[image] for name, call in runs.items() if name != "reply-2.json" for image, size in call["sizes"].items())


def test_parts_that_do_not_fit_either_are_reduced_less_than_the_whole_and_the_answers_say_pages_were_reduced(
        codex, tmp_path, monkeypatch, capsys):
    """Two major problems of four and three pages where two pages fit a request: no way of sharing them out sends
    every page at its own size."""
    question, own, before = _own_sizes(codex, tmp_path, monkeypatch)
    _too_long_for_one(monkeypatch, starts=[1, 4], fits=2, long_sides=(300.0, 600.0))
    capsys.readouterr()
    replies = codex_cli.CodexCliSolver().answer_all(question=question)

    runs = {call["reply_file"]: call for call in _runs(codex()[before:])}
    [plan] = _events(capsys.readouterr().out, "codex_plan")
    assert plan == {"event": "codex_plan", "pages": 6, "parts": 2, "parts_long": 600, "whole_long": 300}
    for name in ("reply-1-1.json", "reply-1-2.json"):
        assert all(300 < max(size) <= 600 < max(own[image]) for image, size in _tiles(runs[name]))
    assert all(result.extras.get("pages_reduced") is True for _, result in replies)


def test_a_long_booklet_whose_major_problems_are_not_told_is_read_whole_and_reduced_and_the_answers_say_so(
        codex, tmp_path, monkeypatch, capsys):
    """Shared out by the count of its pages it would part passages from their questions."""
    question, own, before = _own_sizes(codex, tmp_path, monkeypatch)
    _too_long_for_one(monkeypatch, starts=[])
    capsys.readouterr()
    replies = codex_cli.CodexCliSolver().answer_all(question=question)

    runs = _runs(codex()[before:])
    assert sorted(call["reply_file"] for call in runs) == ["reply-1.json", "reply-2.json"]
    tiles = [pair for call in runs for pair in _tiles(call)]
    assert tiles and all(max(size) <= 300 < max(own[image]) for image, size in tiles), "every page held to the long side"
    [plan] = _events(capsys.readouterr().out, "codex_plan")
    assert plan == {"event": "codex_plan", "pages": 6, "parts": 0, "parts_long": None, "whole_long": 300}
    assert all(result.extras.get("pages_reduced") is True for _, result in replies)
    # ... and a repeated finalize, which reads the kept reply, says it again.
    again = codex_cli.CodexCliSolver().answer_all(question=question)
    assert all(result.extras.get("pages_reduced") is True for _, result in again) and len(_runs(codex()[before:])) == 2


def test_what_is_for_the_whole_exam_goes_with_every_part_at_full_size(codex, tmp_path, monkeypatch):
    """How to answer stands on the first pages of a common test and tables at its end: a part that had them as
    overviews only would answer in the wrong form."""
    _parts(monkeypatch, 3, starts=[1, 3, 5])
    monkeypatch.setenv("FAKE_CODEX_OUTLINE", json.dumps({"starts": [1, 3, 5], "shared": [1, 6, 99, "2"]}))
    codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path, pages=6))

    runs = {call["reply_file"]: call for call in _runs(codex())}
    assert _attached(runs["reply-1-1.json"]) == ["page001.jpg", "page002.jpg", "page003.jpg", "page006.jpg"]
    assert _attached(runs["reply-1-2.json"]) == ["page001.jpg", "page003.jpg", "page004.jpg", "page005.jpg", "page006.jpg"]
    assert _attached(runs["reply-1-3.json"]) == ["page001.jpg", "page005.jpg", "page006.jpg"]
    told = {name: call["args"][-1][len(_WHOLE):] for name, call in runs.items()}
    assert all("for the whole exam" in added for added in told.values())
    assert "Capture pages 1 and 6 hold" in told["reply-1-2.json"]
    assert "Capture page 6 holds" in told["reply-1-1.json"], "only what lies outside its own captures is named"
    assert "Capture page 1 holds" in told["reply-1-3.json"]


def test_more_captures_named_for_the_whole_exam_than_an_exam_has_are_not_believed(codex, tmp_path, monkeypatch, capsys):
    """Asked of thirty-two pages of three subjects (2026-11-18), the first wording returned eleven such captures,
    problem pages among them, and not the same eleven twice: every part would have carried them all. A cover with
    instructions, a sheet of formulas and an answer sheet are a few captures; more than that is not taken."""
    _parts(monkeypatch, 3, starts=[1, 3, 5])
    monkeypatch.setenv("FAKE_CODEX_OUTLINE", json.dumps({"starts": [1, 3, 5], "shared": [1, 2, 3, 4, 6]}))
    codex_cli.CodexCliSolver().answer_all(question=_booklet(tmp_path, pages=6))

    runs = {call["reply_file"]: call for call in _runs(codex())}
    assert _attached(runs["reply-1-3.json"]) == ["page005.jpg", "page006.jpg"]
    assert not any("for the whole exam" in call["args"][-1][len(_WHOLE):] for call in runs.values())
    [told] = _events(capsys.readouterr().out, "codex_outline")
    assert told["shared"] == 0
    [outline] = _outlines(codex())
    assert "show no major problem" in outline["args"][-1] and "never listed" in outline["args"][-1]


def test_a_booklet_that_may_not_fit_one_request_is_asked_for_its_major_problems_whatever_is_set():
    """Nineteen pages gathered from clips (3024x4032 each) are what one request holds at their own size."""
    might = codex_cli._might_not_fit
    clip, still = ((3024, 4032), True), ((4032, 3024), False)
    assert not might([clip] * 12) and not might([clip] * 19)
    assert might([clip] * 24) and might([clip] * 40)
    assert not might([still] * 4) and might([still] * 8), "a still's regions go out at twice their size"
    assert not might([])
