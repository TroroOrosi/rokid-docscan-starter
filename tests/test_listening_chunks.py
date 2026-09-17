import io
import wave

import pytest

from app import listening


def wav(samples, value=b"\x01\x00"):
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        target.writeframes(value * samples)
    return output.getvalue()


def test_chunk_retry_missing_tail_and_original_audio_survive(tmp_path, monkeypatch):
    monkeypatch.setattr(listening.config, "AUDIO_DIR", tmp_path)

    def asr(path, start_sample):
        return {"segments": [{"start_ms": start_sample//16, "end_ms": start_sample//16+100,
                              "text": "Question two", "needs_audio_check": True}],
                "samples": listening.wav_samples(path), "asr_seconds": 1, "real_time_factor": .1}
    monkeypatch.setattr(listening, "transcribe_chunk", asr)
    first = wav(480000)
    row = listening.store_chunk(1, 0, 0, 1000, first)
    assert listening.store_chunk(1, 0, 0, 1000, first) == row
    with pytest.raises(ValueError, match="conflict"):
        listening.store_chunk(1, 0, 0, 1000, wav(480000, b"\x02\x00"))
    with pytest.raises(ValueError, match="missing"):
        listening.complete_recording(1, 2, 496000)
    listening.store_chunk(1, 1, 464000, 30000, wav(32000))
    done = listening.complete_recording(1, 2, 496000)
    with wave.open(done["audio_path"], "rb") as original:
        assert original.getnframes() == 496000
    assert listening.complete_recording(1, 2, 496000) == done
    path, transcript = listening.recording_transcript(1)
    assert "Question two" in transcript and "needs_audio_check=True" in transcript
    assert "29000..29100" in transcript
    assert path == done["audio_path"]


def test_audio_api_preserves_page_clock_original_and_transcript(tmp_path, monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    from app import config, db, main

    monkeypatch.setenv("ROKID_DATA_DIR", str(tmp_path))
    importlib.reload(config)
    importlib.reload(db)
    importlib.reload(main)
    main.ensure_dirs()
    db.init_db()
    client = TestClient(main.app)
    monkeypatch.setattr(listening, "transcribe_chunk", lambda path, **kw: {
        "segments": [{"start_ms": 100, "end_ms": 800, "text": "Question two", "needs_audio_check": True}],
        "samples": 16000, "asr_seconds": .5, "real_time_factor": .5})
    doc = client.post("/v1/documents", json={"title": "listening"}).json()["document_id"]
    page_url = f"/v1/documents/{doc}/pages"
    assert client.post(page_url, data={"page_index": 0, "ocr_text": "問2 Listen", "captured_at_ms": 123400}).status_code == 201
    assert client.post(page_url, data={"page_index": 0, "ocr_text": "問2 Listen again", "captured_at_ms": 123500}).status_code == 201
    assert client.post(page_url, data={"page_index": 0, "ocr_text": "bad", "captured_at_ms": -1}).status_code == 422
    raw = wav(16000)
    upload_url = f"/v1/documents/{doc}/audio-chunks"
    chunk_data = {"sequence": 0, "start_sample": 0, "captured_at_ms": 123000}
    assert client.post(upload_url, data=chunk_data, files={"audio": ("0000.wav", raw)}).status_code == 200
    complete_url = f"/v1/documents/{doc}/audio-complete"
    assert client.post(complete_url, json={"expected_chunks": 2, "total_samples": 496000}).status_code == 409
    assert client.post(complete_url, json={"expected_chunks": 1, "total_samples": 16000}).status_code == 200
    assert client.post(upload_url, data=chunk_data, files={"audio": ("0000.wav", raw)}).status_code == 200
    client.post(f"/v1/documents/{doc}/finalize")
    session_id = client.post("/v1/exam-sessions", json={"document_id": doc, "exam_type": "listening"}).json()["session_id"]
    assert client.post(f"/v1/exam-sessions/{session_id}/document-audio").status_code == 200
    assert client.post(f"/v1/exam-sessions/{session_id}/audio", data={"transcript": "replacement"}).status_code == 409
    concurrent_id = client.post("/v1/exam-sessions", json={"document_id": doc, "exam_type": "listening"}).json()["session_id"]

    def link_complete_during_transcription(*args, **kwargs):
        main.exam_document_audio(concurrent_id)
        return "replacement"
    monkeypatch.setattr("app.transcribe.transcribe_audio", link_complete_during_transcription)
    assert client.post(f"/v1/exam-sessions/{concurrent_id}/audio", data={"transcript": "replacement"}).status_code == 409
    with db.connect() as conn:
        page = conn.execute("SELECT captured_at_ms FROM pages WHERE document_id = ?", (doc,)).fetchone()
        assert page["captured_at_ms"] == 123500
        session = conn.execute("SELECT * FROM exam_sessions WHERE id = ?", (session_id,)).fetchone()
        assert "100..800 ms" in session["transcript"] and "Question two" in session["transcript"]
        with wave.open(session["audio_path"], "rb") as original:
            assert original.readframes(16000) == b"\x01\x00" * 16000
        first_digest = main._answer_input_digest(conn, session)
        from pathlib import Path
        Path(session["audio_path"]).write_bytes(wav(16000, b"\x02\x00"))
        assert main._answer_input_digest(conn, session) != first_digest


@pytest.fixture
def saved_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(listening.config, "AUDIO_DIR", tmp_path)
    monkeypatch.setattr(listening, "transcribe_chunk", lambda path, **kw: {
        "segments": [], "samples": listening.wav_samples(path),
        "asr_seconds": 0, "real_time_factor": 0,
    })
    return tmp_path


@pytest.mark.parametrize("later_sequence", [2, 599])
def test_completion_rejects_nonadjacent_retained_audio(saved_audio, later_sequence):
    """An out-of-order later chunk must not be silently excluded by a short stop."""
    first = wav(16000)
    listening.store_chunk(1, 0, 0, 1000, first)
    start = later_sequence * listening.CHUNK_SAMPLES - listening.OVERLAP_SAMPLES
    listening.store_chunk(1, later_sequence, start, 1000 + start // 16, wav(32000))
    directory = listening.folder(1)
    originals = {path.name: path.read_bytes() for path in directory.iterdir()}
    with pytest.raises(ValueError, match="omit"):
        listening.complete_recording(1, 1, 16000)
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == originals
    assert not (directory / "complete.json").exists()
    assert not (directory / "original.wav").exists()


def test_chunk_retry_does_not_acknowledge_missing_original(saved_audio, monkeypatch):
    raw = wav(16000)
    listening.store_chunk(1, 0, 0, 1000, raw)
    directory = listening.folder(1)
    metadata = (directory / "0000.json").read_bytes()
    (directory / "0000.wav").unlink()  # e.g. a partial restore from backup
    monkeypatch.setattr(listening, "transcribe_chunk", lambda *a, **kw: pytest.fail("unexpected ASR"))
    with pytest.raises(ValueError, match="integrity|original"):
        listening.store_chunk(1, 0, 0, 1000, raw)
    assert (directory / "0000.json").read_bytes() == metadata
    assert not (directory / "0000.wav").exists()  # fail closed, do not silently rewrite evidence


@pytest.mark.parametrize("key, value", [
    ("sha256", "0" * 64), ("sequence", 1), ("start_sample", 42), ("samples", 1),
])
def test_chunk_retry_rejects_inconsistent_metadata(saved_audio, key, value):
    import json

    raw = wav(16000)
    listening.store_chunk(1, 0, 0, 1000, raw)
    path = listening.folder(1) / "0000.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    metadata[key] = value
    path.write_text(json.dumps(metadata), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="integrity|identity"):
        listening.store_chunk(1, 0, 0, 1000, raw)
    assert (listening.folder(1) / "0000.wav").read_bytes() == raw
    assert path.read_bytes() == before


@pytest.mark.parametrize("retained_suffix", [".wav", ".json"])
def test_completion_rejects_an_orphan_later_original_or_metadata(saved_audio, retained_suffix):
    listening.store_chunk(1, 0, 0, 1000, wav(16000))
    directory = listening.folder(1)
    later = directory / ("0002" + retained_suffix)
    later.write_bytes(wav(16000) if retained_suffix == ".wav" else b"{}")
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    with pytest.raises(ValueError, match="omit"):
        listening.complete_recording(1, 1, 16000)
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == before


def test_valid_out_of_order_chunks_complete_without_losing_or_duplicating_overlap(saved_audio):
    # Upload the short tail before the first full 30-second chunk.
    tail = wav(32000, b"\x02\x00")
    row = listening.store_chunk(1, 1, 464000, 30000, tail)
    listening.store_chunk(1, 0, 0, 1000, wav(480000))
    completed = listening.complete_recording(1, 2, 496000)
    with wave.open(completed["audio_path"], "rb") as original:
        assert original.readframes(496001) == b"\x01\x00" * 480000 + b"\x02\x00" * 16000
    assert listening.store_chunk(1, 1, 464000, 30000, tail) == row
    assert listening.complete_recording(1, 2, 496000) == completed
