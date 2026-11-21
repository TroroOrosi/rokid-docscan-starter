"""Remove from the phone what will not be read again.

Nobody is at the phone and nothing else removes anything: after two days of use the clips alone were 9 GB.
``sweep`` removes three things and nothing else:

- the clip of a gathered page (row ``done``) once it has been gathered for ROKID_KEEP_DONE_CLIP_DAYS days (3), whether
  its booklet went on or was left open: the gathered image has taken the page's place and the server does not read the
  clip again, but a use is read from its clips afterwards (which frames counted, why a page was not placed);
- a failed clip once it has been failed for ROKID_KEEP_FAILED_CLIP_DAYS days (7): until then it is what the failure can
  be looked into with;
- an upload cut off before its end (``*.part`` in the clips' directory) once it is an hour old.

Rows, pages, page images and documents stay; a row whose file went says so (``page_clips.file_removed_at``). A clip
that waits or is being gathered is never touched, so a sweep may run beside the gathering. Only a plain file inside the
clips' directory is ever removed, whatever a row's names say.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from contextlib import closing
from pathlib import Path

from . import config, db, page_clips

PART_SECONDS = 3600.0  # a whole clip arrives in well under a minute; a part this old was cut off

_DUE = ("SELECT document_id, page_index, sha256, status FROM page_clips WHERE file_removed_at IS NULL "
        "AND ((status = 'done' AND COALESCE(updated_at, created_at, 0) < ?) "
        "OR (status = 'failed' AND COALESCE(updated_at, created_at, 0) < ?))")


def free_bytes() -> int:
    """Bytes still free on the storage that holds the data directory. Raises OSError when that cannot be asked."""
    return shutil.disk_usage(config.DATA_DIR).free


def _keep_seconds(name: str, days: float) -> float:
    try:
        return float(os.environ.get(name) or days) * 86400
    except ValueError:
        return days * 86400.0


def _remove(path: Path, root: Path, result: dict, kind: str) -> bool:
    """Remove one file and count it under ``kind``. True when no file is there afterwards.

    A path that leads out of ``root`` or is a link, and a file that could not be removed, are counted as errors and left.
    """
    try:
        resolved = path.resolve()
        if root not in resolved.parents or path.is_symlink():
            raise OSError("not a file of the clips' directory")
        size = resolved.stat().st_size
        resolved.unlink()
    except FileNotFoundError:
        return True
    except (OSError, ValueError):
        result["errors"] += 1
        return False
    result[kind] += 1
    result["bytes"] += size
    return True


def _sweep_rows(root: Path, now: float, result: dict) -> None:
    with closing(db.connect()) as conn:
        # Under the write lock: an upload gives a clip its name and its row under that lock (page_clips.store_clip), so
        # a row read here still owns its file when the file goes.
        # ponytail: one transaction a sweep. Uploads and the workers' claims wait while the files go (db.connect gives
        # them thirty seconds); commit file by file if a first sweep over months of clips ever takes that long.
        conn.execute("BEGIN IMMEDIATE")
        for row in conn.execute(_DUE, (now - _keep_seconds("ROKID_KEEP_DONE_CLIP_DAYS", 3),
                                       now - _keep_seconds("ROKID_KEEP_FAILED_CLIP_DAYS", 7))).fetchall():
            path = page_clips.clip_path(row["document_id"], row["page_index"], row["sha256"])
            if _remove(path, root, result, f"{row['status']}_files"):  # marked only once the file is gone
                conn.execute("UPDATE page_clips SET file_removed_at = ? WHERE document_id = ? AND page_index = ? AND sha256 = ?",
                             (now, row["document_id"], row["page_index"], row["sha256"]))
        conn.commit()


def _sweep_parts(root: Path, now: float, result: dict) -> None:
    # ponytail: walks every page's directory, the emptied ones too (directories are not removed). When that walk shows
    # in a sweep's time, remove the empty directories of booklets that went on.
    for part in list(root.rglob("*.part")) if root.is_dir() else ():
        try:
            old = part.lstat().st_mtime < now - PART_SECONDS
        except OSError:
            continue  # gone meanwhile: its upload ended
        if old:
            _remove(part, root, result, "part_files")


def sweep(now: float | None = None) -> dict:
    """Remove what has no further use (the module's text says what); counts, bytes freed, errors and the space now
    free (``free_bytes``) come back.

    Never raises: what could not be removed or looked at is counted in ``errors`` and tried again by the next sweep.
    One line of JSON is printed for it, numbers only.
    """
    now = time.time() if now is None else now
    result = {"event": "retention", "done_files": 0, "failed_files": 0, "part_files": 0, "bytes": 0, "errors": 0,
              "free_bytes": -1}  # -1: the storage could not be asked
    for step in (_sweep_rows, _sweep_parts):
        try:
            step((config.DATA_DIR / "page-clips").resolve(), now, result)
        except Exception:  # noqa: BLE001 - the database or the storage could not be reached: the next sweep tries again
            result["errors"] += 1
    try:
        result["free_bytes"] = free_bytes()  # after the removing: what is left for the next uploads
    except Exception:  # noqa: BLE001
        result["errors"] += 1
    try:
        print(json.dumps(result), flush=True)
    except Exception:  # noqa: BLE001 - a closed output is no reason to fail the caller
        pass
    return result
