"""The stand-in solver carries the server half of the route end to end and sends nothing to the model.

The flow runs in a fresh interpreter because the server reads its configuration when it is imported.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.solvers.base import Question
from app.solvers.registry import get_solver

FLOW = r'''
import io, json, os, sys, time
from pathlib import Path
from fastapi.testclient import TestClient
from PIL import Image
from app import main

auth = {"Authorization": "Bearer route-key"}
out = {}
with TestClient(main.app) as client:
    out["solver"] = client.get("/v1/settings").json()["providers"]["solver"]
    doc = client.post("/v1/documents", json={"title": "route"}, headers=auth).json()["document_id"]
    for index in range(3):
        buffer = io.BytesIO()
        Image.new("RGB", (640, 480), (40 * index + 30, 90, 120)).save(buffer, "JPEG")
        page = client.post(f"/v1/documents/{doc}/pages", headers=auth, data={"page_index": str(index), "image_rotation": "0"},
                           files={"image": (f"page-{index + 1}.jpg", buffer.getvalue(), "image/jpeg")})
        assert page.status_code in (200, 201), page.text
    assert client.post(f"/v1/documents/{doc}/finalize", headers=auth).status_code in (200, 201)
    sid = client.post("/v1/exam-sessions", headers=auth, json={
        "mode": "study", "document_id": doc, "exam_type": "written", "answer_format": "mark"}).json()["session_id"]
    out["finalize_reading"] = client.post(f"/v1/exam-sessions/{sid}/finalize-reading?solve=background", headers=auth).json().get("status")
    out["bundle_before"] = client.get(f"/v1/exam-sessions/{sid}/answer-bundle", headers=auth).status_code
    client.post("/v1/glasses/state", headers=auth, json={"device_id": "route-device", "session_id": sid, "generation": 7,
                                                           "sequence": 1, "phase": "analyzing", "display_request": "sleep"})
    deadline = time.time() + 30
    ready = False
    while time.time() < deadline and not ready:
        ready = client.get("/v1/glasses/state", params={"device_id": "route-device"}, headers=auth).json()["answer_ready"]
        time.sleep(0.3)
    out["answer_ready"] = ready
    bundle = client.get(f"/v1/exam-sessions/{sid}/answer-bundle", headers=auth)
    out["bundle_after"] = bundle.status_code
    out["items"] = [(item["status"], item["answer"][:6]) for item in bundle.json()["items"]] if bundle.status_code == 200 else []
data = Path(os.environ["ROKID_DATA_DIR"])
out["browser_state"] = sorted(p.name for p in (data / "browser-state").iterdir()) if (data / "browser-state").is_dir() else []
out["work_jobs_db"] = (data / "work-jobs.db").is_file()
print("RESULT " + json.dumps(out, ensure_ascii=False))
'''

REPLY = {"questions": [
    {"group": "第1問", "label": "問1", "answer_no": [1], "pages": [1], "status": "ready",
     "answer": "経路検査の録音回答", "missing_material": "", "diagrams": []},
    {"group": "", "label": "", "answer_no": [], "pages": [1], "status": "needs_input",
     "answer": "", "missing_material": "経路検査：資料不足", "diagrams": []}]}


def test_it_is_armed_only_with_sending_off_and_a_reply_file(tmp_path, monkeypatch):
    reply = tmp_path / "reply.json"
    reply.write_text(json.dumps(REPLY, ensure_ascii=False), encoding="utf-8")
    solver = get_solver("recorded")
    monkeypatch.setenv("ROKID_RECORDED_REPLY", str(reply))
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "1")
    assert not solver.ready(), "with sending on it must stay unready, so real mode refuses it"
    with pytest.raises(RuntimeError):
        solver.answer_all(question=Question(question_id="q"))
    monkeypatch.setenv("ROKID_CHATGPT_SEND_ENABLED", "0")
    assert solver.ready()
    monkeypatch.setenv("ROKID_RECORDED_REPLY", str(tmp_path / "missing.json"))
    assert not solver.ready()
    with pytest.raises(ValueError):
        solver.solve(question=Question(question_id="q"))


def test_the_server_half_of_the_route_runs_to_a_bundle_and_nothing_is_sent(tmp_path):
    reply = tmp_path / "reply.json"
    reply.write_text(json.dumps(REPLY, ensure_ascii=False), encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    environment = dict(os.environ, ROKID_DATA_DIR=str(data), ROKID_API_KEY="route-key", ROKID_REAL_MODE="1",
                       ROKID_ANALYZER="client-ocr", ROKID_SOLVER="recorded", ROKID_SOLVER_FALLBACKS="",
                       ROKID_CHATGPT_SEND_ENABLED="0", ROKID_RECORDED_REPLY=str(reply), ROKID_RECORDED_DELAY_S="1",
                       ROKID_CAPTURE_INSPECTION="0", PYTHONIOENCODING="utf-8")
    done = subprocess.run([sys.executable, "-X", "utf8", "-c", FLOW], capture_output=True, text=True, encoding="utf-8",
                          env=environment, cwd=Path(__file__).resolve().parents[1], timeout=180)
    lines = [line for line in done.stdout.splitlines() if line.startswith("RESULT ")]
    assert lines, done.stderr[-2000:]
    result = json.loads(lines[-1][7:])
    assert result["solver"]["name"] == "recorded" and result["solver"]["ready"] is True
    assert result["bundle_before"] == 409, "the bundle is not there until the stand-in has answered"
    assert result["answer_ready"] is True
    assert result["bundle_after"] == 200
    assert len(result["items"]) == 2 and result["items"][0][1] == "経路検査の録"
    assert result["browser_state"] == [], "no browser send record may exist"
    assert result["work_jobs_db"] is False
