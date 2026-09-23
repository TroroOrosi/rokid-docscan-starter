"""Durable original WAV chunks; optional ASR for the non-browser compatibility route."""

import hashlib
import json
import threading
import wave

from . import config
from .local_asr import transcribe_chunk, wav_samples

# ponytail: single phone recording; serialize chunk writes and completion, not camera uploads.
_LOCK = threading.Lock()
CHUNK_SAMPLES = 30 * 16000
OVERLAP_SAMPLES = 16000


def requires_transcript():
    from .solvers.registry import _tier_names

    return _tier_names(None)[0] != "chatgpt-web"


def folder(document_id):
    if type(document_id) is not int or document_id < 1:
        raise ValueError("invalid document identity")
    return config.AUDIO_DIR / f"document-{document_id}"


def store_chunk(document_id, sequence, start_sample, captured_at_ms, raw, *, transcribe=True):
    if (not 0 <= sequence < 600 or start_sample != max(0, sequence * CHUNK_SAMPLES - OVERLAP_SAMPLES)
            or captured_at_ms < 1 or len(raw) > 1_100_000):
        raise ValueError("invalid recording chunk metadata")
    with _LOCK:
        directory = folder(document_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{sequence:04d}.wav"
        meta_path = path.with_suffix(".json")
        digest = hashlib.sha256(raw).hexdigest()
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("recording chunk identity conflict; original retained")
        if meta_path.exists():
            try:
                metadata = json.loads(meta_path.read_text(encoding="utf-8"))
                # A metadata-only restore is not proof that the original is
                # retained. Never ACK it or silently rewrite the evidence.
                if (not path.is_file() or not isinstance(metadata, dict)
                        or metadata.get("sha256") != digest
                        or metadata.get("sequence") != sequence
                        or metadata.get("start_sample") != start_sample
                        or metadata.get("samples") != wav_samples(path)):
                    raise ValueError("inconsistent recording metadata")
            except (OSError, ValueError, wave.Error, EOFError):
                raise ValueError("recording chunk integrity check failed; original retained") from None
            if metadata.get("captured_at_ms") != captured_at_ms:
                raise ValueError("recording clock identity conflict")
            return metadata
        if (directory / "complete.json").exists():
            raise ValueError("recording already complete")
        pending = path.with_suffix(".pending")
        pending.write_bytes(raw)
        try:
            count = wav_samples(pending)
            if count > CHUNK_SAMPLES + (OVERLAP_SAMPLES if sequence else 0):
                raise ValueError("invalid recording chunk size")
        except (ValueError, wave.Error, EOFError):
            pending.unlink(missing_ok=True)
            raise ValueError("invalid recording WAV") from None
        pending.replace(path)  # keep original even when ASR fails below
        result = (transcribe_chunk(path, start_sample=start_sample) if transcribe else
                  {"segments": [], "samples": count, "asr_seconds": 0, "real_time_factor": 0})
        metadata = {**result, "sequence": sequence, "start_sample": start_sample,
                    "captured_at_ms": captured_at_ms, "sha256": digest,
                    "audio_file": path.name, "overlap_ms": 1000 if sequence else 0}
        pending_meta = meta_path.with_suffix(".pending-json")
        pending_meta.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
        pending_meta.replace(meta_path)
        return metadata


def complete_recording(document_id, expected_chunks, total_samples):
    if not 1 <= expected_chunks <= 600 or not 0 < total_samples <= expected_chunks * CHUNK_SAMPLES:
        raise ValueError("invalid recording completion")
    with _LOCK:
        directory = folder(document_id)
        complete = directory / "complete.json"
        if complete.exists():
            manifest = json.loads(complete.read_text(encoding="utf-8"))
            if (manifest["chunks"], manifest["total_samples"]) != (expected_chunks, total_samples):
                raise ValueError("recording completion conflict")
            return manifest
        rows = []
        for sequence in range(expected_chunks):
            meta = directory / f"{sequence:04d}.json"
            if not meta.is_file():
                raise ValueError("recording has missing chunks")
            row = json.loads(meta.read_text(encoding="utf-8"))
            chunk_path = directory / f"{sequence:04d}.wav"
            if (row["sequence"] != sequence or row["start_sample"] != max(0, sequence * CHUNK_SAMPLES - OVERLAP_SAMPLES)
                    or not chunk_path.is_file() or hashlib.sha256(chunk_path.read_bytes()).hexdigest() != row["sha256"]
                    or wav_samples(chunk_path) != row["samples"]):
                raise ValueError("recording chunk integrity check failed")
            if rows and row["captured_at_ms"] - row["start_sample"] // 16 != rows[0]["captured_at_ms"]:
                raise ValueError("recording has a clock discontinuity")
            expected = min(CHUNK_SAMPLES, total_samples - sequence * CHUNK_SAMPLES)
            if sequence:
                expected += OVERLAP_SAMPLES
            if expected <= 0 or row["samples"] != expected:
                raise ValueError("recording has a sample gap or truncated chunk")
            rows.append(row)
        # Uploads may arrive out of order. Checking only the immediately next
        # number would silently finalize a prefix while a later original (or
        # its metadata) still belongs to this recording.
        for retained in directory.iterdir():
            if (retained.suffix in (".wav", ".json") and len(retained.stem) == 4
                    and retained.stem.isascii() and retained.stem.isdigit()
                    and int(retained.stem) >= expected_chunks):
                raise ValueError("recording completion would omit a chunk")
        output = directory / "original.wav"
        pending = directory / "original.pending"
        with wave.open(str(pending), "wb") as target:
            target.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            for row in rows:
                with wave.open(str(directory / f"{row['sequence']:04d}.wav"), "rb") as source:
                    data = source.readframes(source.getnframes())
                target.writeframes(data[OVERLAP_SAMPLES*2:] if row["sequence"] else data)
        pending.replace(output)
        manifest = {"document_id": document_id, "chunks": expected_chunks,
                    "total_samples": total_samples, "audio_path": str(output), "segments": rows}
        pending_manifest = directory / "complete.pending"
        pending_manifest.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        pending_manifest.replace(complete)
        return manifest


def recording_transcript(document_id, *, require_transcript=True):
    manifest_path = folder(document_id) / "complete.json"
    if not manifest_path.is_file():
        raise ValueError("finish recording and retain every chunk before analysis")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not require_transcript:
        return manifest["audio_path"], ""
    lines = ["# English listening transcript", f"document_id: {document_id}",
             "Times refer to original.wav; adjacent chunks overlap by 1 second.",
             "ASR is imperfect. Match spoken question numbers and content to OCR question_ids;",
             "timestamps/page proximity are hints only. Check original audio for uncertain words,",
             "stress, pronunciation, emotion and speaker identity. No speaker identity inferred."]
    for row in manifest["segments"]:
        for segment in row["segments"]:
            lines.append(f"[{segment['start_ms']}..{segment['end_ms']} ms; "
                         f"chunk={row['sequence']}; capture_epoch_ms={row['captured_at_ms']}; "
                         f"needs_audio_check={segment['needs_audio_check']}] {segment['text']}")
    if len(lines) == 6:
        raise ValueError("no speech recognized; original audio retained for retry")
    return manifest["audio_path"], "\n".join(lines)
