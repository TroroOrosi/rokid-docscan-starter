#!/usr/bin/env bash
# Runs on the phone in Termux. Requires existing git, cmake and clang; installs nothing.
set -euo pipefail
cd "$(dirname "$0")/.."
revision=2eeeba56e9edd762b4b38467bab96c2517163158
source_dir=data/local-asr/whisper.cpp
for tool in git cmake clang python; do command -v "$tool" >/dev/null; done
if [[ ! -d "$source_dir" ]]; then
    git clone --depth 1 --branch v1.8.3 https://github.com/ggml-org/whisper.cpp.git "$source_dir"
fi
[[ "$(git -C "$source_dir" rev-parse HEAD)" == "$revision" ]] || { echo 'ASR source revision mismatch; retained' >&2; exit 1; }
[[ -z "$(git -C "$source_dir" status --porcelain --untracked-files=no)" ]] || { echo 'ASR source modified; retained' >&2; exit 1; }
cmake -S "$source_dir" -B "$source_dir/build" -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=OFF -DGGML_OPENMP=OFF -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_SERVER=OFF
cmake --build "$source_dir/build" --target whisper-cli -j 4
python scripts/prepare_local_asr.py
echo 'ASR assets ready; set ROKID_WHISPER_CLI / MODEL / VAD_MODEL as documented before starting FastAPI.'
