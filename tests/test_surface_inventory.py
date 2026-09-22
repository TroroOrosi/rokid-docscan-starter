"""Every runnable surface is named in one inventory, or this fails.

Prose asking the next session to "understand the whole repository first" does
not survive contact with a session that has a feature to build. The repeated
result was a second implementation of a role that already had one: two capture
apps, three text wrappers, an automatic-scan loop reported as missing because
one function body said so.

So the inventory is checked instead of requested. Adding a Gradle module, an
Activity or a server display module without a row in
`docs/implementation-surfaces.md` fails here, and the row has to carry a status
-- route, frozen, probe or shared -- which is the question that would have
prevented the duplicates.

The check is on the table ROW, not on the name appearing somewhere in the file.
The first version of this test searched the whole document, so deleting
`:pagequality`'s row still passed: prose elsewhere mentioned it. A test that
cannot fail is worse than no test, because it is quoted as evidence.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = "docs/implementation-surfaces.md"
STATUSES = ("route", "frozen", "probe", "shared")


def _rows() -> dict[str, str]:
    """Table rows, mapped first-backticked-name -> status.

    Only the FIRST backticked cell names the row. The Activity table also
    backticks the module a row belongs to, and registering that too would let a
    deleted `:glassdoc` module row be covered by an Activity that merely
    mentions it -- which is the same hole the whole-document search had.

    The status cell may carry a trailing note ("route -- measures the real
    font"), so it is matched on its first word.
    """
    rows = {}
    for line in (ROOT / INVENTORY).read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or set(line) <= set("|- "):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        names = re.findall(r"`([^`]+)`", cells[0]) if cells else []
        if not names:
            continue
        status = next(
            (cell.split()[0] for cell in cells[1:] if cell and cell.split()[0] in STATUSES),
            "",
        )
        rows[names[0]] = status
    return rows


def _gradle_modules() -> set[str]:
    settings = (ROOT / "android-relay/settings.gradle.kts").read_text(encoding="utf-8")
    return set(re.findall(r'include\("(:[A-Za-z0-9_-]+)"\)', settings))


def _activities() -> set[str]:
    """Classes that are an entry point on a device, by their declaration."""
    found = set()
    for path in (ROOT / "android-relay").rglob("*.java"):
        if "src/test" in path.as_posix() or "src/androidTest" in path.as_posix():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"\bclass\s+\w+\s+extends\s+\w*Activity\b", text):
            found.add(path.stem)
    return found


def _server_display_modules() -> set[str]:
    """Server modules that build what the operator reads on the glasses."""
    return {
        f"app/{path.name}"
        for path in (ROOT / "app").glob("*.py")
        if path.name in {"hud.py", "glasses_view.py"}
    }


def test_every_gradle_module_has_its_own_row():
    missing = sorted(_gradle_modules() - set(_rows()))
    assert missing == [], f"add a row with a status to {INVENTORY}"


def test_every_activity_has_its_own_row():
    missing = sorted(_activities() - set(_rows()))
    assert missing == [], f"add a row with a status to {INVENTORY}"


def test_every_operator_facing_server_module_has_its_own_row():
    missing = sorted(_server_display_modules() - set(_rows()))
    assert missing == [], f"add a row with a status to {INVENTORY}"


def test_every_row_carries_a_known_status():
    """A row without a status is a name, and a name prevents nothing."""
    rows = _rows()
    assert rows, "the inventory lost its tables"
    unstated = sorted(name for name, status in rows.items() if status not in STATUSES)
    assert unstated == [], f"every row needs one of {STATUSES}"


def test_the_inventory_is_reachable_from_the_documentation_index():
    """A map nobody is pointed at is a map nobody reads."""
    index = (ROOT / "docs/README.md").read_text(encoding="utf-8")
    assert f"`{INVENTORY}`" in index
