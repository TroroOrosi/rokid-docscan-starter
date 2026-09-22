"""Keep diagnostic tools distinct from the still-unconnected registration gate."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("path", [
    "README.md", "CLAUDE.md", "docs/capture-quality.md", "docs/capture-preflight.md",
    "docs/multimodal-scan.md", "docs/real-device-operation.md", "docs/user-operation-guide.md",
    "docs/rokid-capture-research.md",
])
def test_capture_docs_name_the_unconnected_gate(path):
    text = (ROOT / path).read_text(encoding="utf-8")
    assert "PC" in text and "未接続" in text


def test_diagnostic_runbook_does_not_certify_unknown_content():
    text = (ROOT / "docs/capture-quality.md").read_text(encoding="utf-8")
    for boundary in ("decision=hold", "auto_registration_allowed=false",
                     "paper_completeness=unknown", "semantic_coverage=unknown",
                     "guarantees_all_content=false", "validated_profiles=()"):
        assert boundary in text


def test_full_capture_gate_work_remains_explicitly_open():
    todo = (ROOT / "tasks/todo.md").read_text(encoding="utf-8")
    for number in range(5, 10):
        assert f"- [ ] CQ-{number}" in todo
    assert "完了録音の部分復元" in todo
