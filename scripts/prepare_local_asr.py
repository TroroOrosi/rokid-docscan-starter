"""Fetch pinned whisper.cpp assets. Never installs or starts anything on a device."""

import argparse
import hashlib
import urllib.request
import zipfile
from pathlib import Path

ASSETS = {
    "ggml-base.en.bin": (
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-base.en.bin",
        "a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002"),
    "ggml-silero-v6.2.0.bin": (
        "https://huggingface.co/ggml-org/whisper-vad/resolve/9ffd54a1e1ee413ddf265af9913beaf518d1639b/ggml-silero-v6.2.0.bin",
        "2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987"),
}
WINDOWS = ("https://github.com/ggml-org/whisper.cpp/releases/download/v1.8.3/whisper-bin-x64.zip",
           "d824b1e37599f882b396e73f1ee0bfd5d0529f700314c48311dcbd00b803321d")


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def download(directory, name, url, expected):
    target = directory / name
    if target.exists():
        if digest(target) != expected:
            raise ValueError(f"existing {name} has an unexpected hash; retained")
        return target
    pending = target.with_suffix(target.suffix + ".download")
    with urllib.request.urlopen(url, timeout=60) as response, pending.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    if digest(pending) != expected:
        raise ValueError(f"download hash mismatch: {name}")
    pending.replace(target)
    print(f"verified {name}: {expected}")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("data/local-asr"))
    parser.add_argument("--windows-cli", action="store_true", help="PC component test only; not phone benchmark")
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    for name, (url, expected) in ASSETS.items():
        download(directory, name, url, expected)
    if args.windows_cli:
        archive = download(directory, "whisper-bin-x64.zip", *WINDOWS)
        binary_dir = directory / "windows-v1.8.3"
        with zipfile.ZipFile(archive) as source:
            for entry in source.infolist():
                target = (binary_dir / entry.filename).resolve()
                if not target.is_relative_to(binary_dir):
                    raise ValueError("unsafe archive path")
            source.extractall(binary_dir)
        print(f"Windows component-test CLI: {binary_dir}")


if __name__ == "__main__":
    main()
