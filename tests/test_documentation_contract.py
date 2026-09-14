"""Repository documentation is a tested operational contract."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CURRENT_RUNBOOKS = (
    "CLAUDE.md",
    "README.md",
    "android-relay/README.md",
    "docs/cxr-l-integration.md",
    "docs/device-verification-checklist.md",
    "docs/real-device-operation.md",
    "docs/user-operation-guide.md",
    "docs/windows-android-real-device-setup.md",
)


def _text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _generated_prefixes() -> tuple[str, ...]:
    """Directory prefixes `.gitignore` marks as generated at runtime.

    A checkout never contains them, so requiring a documented path under one to
    exist passes only on a machine that has already run the thing that writes
    it. `data/docscan.db` is documented as created on startup; asking CI to
    find it is asking the wrong question.
    """
    return tuple(
        line
        for line in (raw.strip() for raw in _text(".gitignore").splitlines())
        if line.endswith("/") and not line.startswith(("#", "!", "*")) and "*" not in line
    )


def _repository_markdown() -> set[str]:
    ignored_parts = {".git", ".pytest_cache"}
    paths = {
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*.md")
        if not ignored_parts.intersection(path.parts)
    }
    # Keep ordinary untracked project docs in the gate. Only local tool output
    # under these exact root directories is exempt; a tracked file never is.
    local_tool_roots = (".agents/skills/", ".claude/", ".cursor/", ".specify/", ".superpowers/", "openspec/")
    if not (ROOT / ".git").exists():
        return paths
    try:
        tracked = set(
            subprocess.check_output(
                ["git", "-C", str(ROOT), "ls-files", "-z"],
                encoding="utf-8",
                stderr=subprocess.DEVNULL,
            ).split("\0")
        )
    except (OSError, subprocess.CalledProcessError):
        # A source archive or unavailable Git must not silently hide documents.
        return paths
    return {
        path for path in paths if path in tracked or not path.startswith(local_tool_roots)
    }


def test_documentation_index_classifies_every_markdown_file():
    index = _text("docs/README.md")
    missing = sorted(
        path
        for path in _repository_markdown()
        if path != "docs/README.md" and f"`{path}`" not in index
    )
    assert missing == []


def test_local_tool_output_is_excluded_but_project_documents_remain(tmp_path, monkeypatch):
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    project_docs = {
        "docs/new-untracked-runbook.md",
        ".agents/progress/current.md",
        "app/openspec/design.md",
        ".claude/tracked-contract.md",
    }
    tool_docs = {
        ".agents/skills/example/SKILL.md",
        ".claude/commands/generated.md",
        ".cursor/commands/generated.md",
        ".specify/templates/generated.md",
        "openspec/AGENTS.md",
    }
    for relative_path in project_docs | tool_docs:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Fixture\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "--", ".claude/tracked-contract.md"],
        check=True,
    )

    assert _repository_markdown() == project_docs


def test_documentation_scan_does_not_hide_files_without_git_metadata(tmp_path, monkeypatch):
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    path = tmp_path / ".agents/skills/example/SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Source archive fixture\n", encoding="utf-8")

    assert _repository_markdown() == {".agents/skills/example/SKILL.md"}


def test_current_runbooks_do_not_promote_indicator_tampering():
    prohibited = (
        "無効化を目指",
        "可能なら無効化",
        "アプリでも無効化",
        "永続化する",
    )
    offenders = []
    for path in CURRENT_RUNBOOKS:
        text = _text(path)
        for phrase in prohibited:
            if phrase in text:
                offenders.append(f"{path}: {phrase}")
    assert offenders == []


def test_current_runbooks_do_not_claim_customview_operator_tap_is_verified():
    prohibited = (
        "ユーザー由来の`AI-exit`",
        "ユーザー由来の `AI-exit`",
        "グラスから得られる唯一の入力",
        "アプリへ配送するグラス入力は**1本指タップだけ**",
    )
    offenders = []
    for path in CURRENT_RUNBOOKS:
        text = _text(path)
        for phrase in prohibited:
            if phrase in text:
                offenders.append(f"{path}: {phrase}")
    assert offenders == []


def test_current_runbooks_describe_normalized_png_not_raw_jpeg_persistence():
    prohibited = (
        "元JPEGとOCRの両方で保存",
        "Store the original page image as the authoritative source",
        "original JPEG remains authoritative",
    )
    offenders = []
    for path in CURRENT_RUNBOOKS:
        text = _text(path)
        for phrase in prohibited:
            if phrase in text:
                offenders.append(f"{path}: {phrase}")
    assert offenders == []


def test_current_runbooks_do_not_document_a_gradle_command_that_cannot_run():
    """No `gradle` on PATH, and the wrapper already supplies -p."""
    prohibited = ("gradle --no-daemon -p", "gradle -p android-relay")
    offenders = []
    for path in CURRENT_RUNBOOKS:
        text = _text(path)
        for phrase in prohibited:
            if phrase in text:
                offenders.append(f"{path}: {phrase}")
    assert offenders == []


def test_every_documented_repository_path_exists():
    """A path that moved silently sends the next agent to the wrong module."""
    reference = re.compile(r"`([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+)`")
    generated = _generated_prefixes()
    offenders = []
    for document in sorted(_repository_markdown()):
        for match in reference.finditer(_text(document)):
            candidate = match.group(1)
            if not Path(candidate).suffix or candidate.startswith(("http", "C:/")):
                continue
            if candidate.startswith(generated):
                continue
            if (ROOT / candidate).exists() or (ROOT / document).parent.joinpath(candidate).exists():
                continue
            offenders.append(f"{document}: {candidate}")
    assert offenders == []


def test_progress_records_name_the_runtime_of_every_resume_list():
    """A resume list without its runtime gets executed on the wrong one."""
    actionable = ("Resume here", "Next steps", "Still to do")
    offenders = []
    for path in sorted((ROOT / ".agents/progress").glob("*.md")):
        sections = re.split(r"^#{2,4} ", path.read_text(encoding="utf-8"), flags=re.MULTILINE)
        for section in sections[1:]:
            title = section.splitlines()[0].strip()
            if title.startswith(actionable) and "Runs on:" not in section:
                offenders.append(f"{path.relative_to(ROOT).as_posix()}: {title}")
    assert offenders == []


def test_readme_versions_match_source_of_truth():
    server_version = re.search(
        r'^APP_VERSION = "([^"]+)"$',
        _text("app/version.py"),
        re.MULTILINE,
    ).group(1)
    api_version = re.search(
        r'^API_VERSION = "([^"]+)"$',
        _text("app/version.py"),
        re.MULTILINE,
    ).group(1)
    glasses_version = re.search(
        r'^GLASSES_VIEW_CONTRACT_VERSION = "([^"]+)"$',
        _text("app/version.py"),
        re.MULTILINE,
    ).group(1)
    solver_version = re.search(
        r'^SOLVER_API_VERSION = "([^"]+)"$',
        _text("app/version.py"),
        re.MULTILINE,
    ).group(1)
    gradle = _text("android-relay/app/build.gradle.kts")
    relay_version = re.search(r'versionName = "([^"]+)"', gradle).group(1)
    cxrl_version = re.search(
        r'com\.rokid\.cxr:client-l:([^"]+)',
        gradle,
    ).group(1)

    readme = _text("README.md")
    expected = (
        f"Server APP {server_version} / API {api_version} / "
        f"Android client {relay_version} / Glasses View {glasses_version} / "
        f"Solver API {solver_version}"
    )
    assert expected in readme
    assert f"com.rokid.cxr:client-l:{cxrl_version}" in readme
