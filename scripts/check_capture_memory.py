"""Run the saved-photo regression under a small JVM heap; no Android/device/network.

Requires a preinstalled JDK (JAVA_HOME or PATH). Compiles the actual repository
classes into a temporary directory and removes all synthetic data afterwards.
The 7 MiB byte array is a persistence fixture, not an OCR/optical-quality test.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

PROBE = r'''
package dev.rokid.docscanrelay;
import java.io.*;
import java.nio.file.*;
public class CaptureMemoryProbe {
    public static void main(String[] args) throws Exception {
        File root = new File(args[0]);
        File file = new File(root, "pending.bin");
        CaptureReviewPersistence store = new CaptureReviewPersistence(file);
        store.save(new CaptureReviewStore.Pending(0, new byte[]{1,2,3}, "original", 270, ""));
        byte[] before = Files.readAllBytes(file.toPath());
        boolean rejected = false;
        try { store.save(new CaptureReviewStore.Pending(-1, new byte[]{9}, "invalid", 270, "")); }
        catch (IOException expected) { rejected = true; }
        if (!rejected || !java.util.Arrays.equals(before, Files.readAllBytes(file.toPath())))
            throw new AssertionError("invalid replacement overwrote the original");
        System.out.println("invalid save preserves original: PASS");
        byte[] jpeg = new byte[7 * 1024 * 1024];
        CaptureReviewStore.Pending pending = new CaptureReviewStore.Pending(0, jpeg, "source", 270, "");
        LocalCaptureSession session = LocalCaptureSession.create(root, "http://127.0.0.1:8000", false);
        for (int i = 0; i < 20; i++) {
            session.commit(pending);
            if (!session.contains(pending)) throw new AssertionError("lost original");
        }
        System.out.println("7MiB fixture: 20 commits/equality checks under -Xmx16m, PASS");
    }
}
'''


def _java_tool(name: str) -> str:
    home = os.environ.get("JAVA_HOME")
    executable = name + (".exe" if os.name == "nt" else "")
    candidate = Path(home) / "bin" / executable if home else None
    if candidate is not None and candidate.is_file():
        return str(candidate)
    found = shutil.which(executable)
    if found:
        return found
    raise RuntimeError("A preinstalled JDK is required: set JAVA_HOME or PATH. Nothing was downloaded.")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    java, javac = _java_tool("java"), _java_tool("javac")
    package = "src/main/java/dev/rokid/docscanrelay"
    sources = [root / "android-relay/pagequality" / package / "PageFraming.java"]
    sources.extend(root / "android-relay/relaycore" / package / (name + ".java")
                   for name in ("CaptureReviewStore", "CaptureReviewPersistence", "LocalCaptureSession"))
    with tempfile.TemporaryDirectory(prefix="capture-memory-") as directory:
        work = Path(directory)
        probe = work / "CaptureMemoryProbe.java"
        probe.write_text(PROBE, encoding="utf-8")
        classes = work / "classes"
        classes.mkdir()
        subprocess.run([javac, "-encoding", "UTF-8", "-d", str(classes),
                        *map(str, sources), str(probe)], check=True, timeout=60)
        subprocess.run([java, "-Xmx16m", "-cp", str(classes),
                        "dev.rokid.docscanrelay.CaptureMemoryProbe", str(work)],
                       check=True, timeout=120)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(f"capture memory check failed: {error}") from error
