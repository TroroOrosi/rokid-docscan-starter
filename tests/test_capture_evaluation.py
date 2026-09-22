"""Leakage and paired-unit evaluation checks with synthetic labels only."""
import copy
import importlib
import json

import pytest


def trial(sample="s1", **kwargs):
    return dict(sample_id=sample, document_id="d1", comparison_id="p1", split="test",
                layout="single", decision="hold", reference_usable=True,
                source_sha256=["a" * 64], **kwargs)


def evaluate(records):
    return importlib.import_module("scripts.capture_evaluation").evaluate_trials(records)


def test_test_only_metrics_include_false_accepts_and_unmatched_pairs():
    single = trial()
    spread = {**trial("s2"), "layout": "spread", "source_sha256": ["b" * 64],
              "reference_usable": False, "decision": "eligible"}
    unmatched = {**trial("s3"), "comparison_id": "p2", "source_sha256": ["c" * 64], "decision": "retake"}
    calibration = {**trial("s4"), "document_id": "d2", "comparison_id": "p3", "split": "calibration", "source_sha256": ["d" * 64]}
    result = evaluate([single, spread, unmatched, calibration])
    assert result["test_records"] == 3
    assert result["layouts"]["single"]["false_accept_rate"] is None
    assert result["layouts"]["single"]["usable_hold"] == 1
    assert result["layouts"]["single"]["usable_retake"] == 1
    assert result["layouts"]["spread"]["false_accept_count"] == 1
    assert result["layouts"]["spread"]["false_accept_rate"] == 1
    assert result["paired_comparisons"] == result["unpaired_comparisons"] == 1
    assert result["winner"] is None and result["profile_approved"] is False


@pytest.mark.parametrize("leak", ["sample", "comparison_layout", "document_split", "image_split", "comparison_split"])
def test_duplicate_or_leaking_data_is_rejected(leak):
    first = trial()
    second = {**trial("s2"), "document_id": "d2", "comparison_id": "p2", "source_sha256": ["b" * 64]}
    if leak == "sample":
        second["sample_id"] = first["sample_id"]
    elif leak == "comparison_layout":
        second["document_id"] = first["document_id"]
        second["comparison_id"] = first["comparison_id"]
    else:
        second["split"] = "validation"
        if leak == "document_split":
            second["document_id"] = first["document_id"]
        elif leak == "image_split":
            second["source_sha256"] = first["source_sha256"]
        else:
            second["comparison_id"] = first["comparison_id"]
    with pytest.raises(ValueError):
        evaluate([first, second])


@pytest.mark.parametrize("field,bad", [
    ("sample_id", ""), ("document_id", "d" * 129), ("comparison_id", None),
    ("split", "train"), ("layout", "unknown"), ("decision", "pass"),
    ("reference_usable", 1), ("source_sha256", []), ("source_sha256", ["x"]),
    ("source_sha256", ["a" * 64] * 9), ("source_sha256", ["a" * 64] * 2),
])
def test_invalid_record_is_rejected(field, bad):
    record = trial()
    record[field] = bad
    with pytest.raises(ValueError):
        evaluate([record])


@pytest.mark.parametrize("records", [None, {}, [], [None], [trial()] * 10001])
def test_array_limits(records):
    with pytest.raises(ValueError):
        evaluate(records)


def test_single_record_can_represent_two_pages_and_inputs_are_not_modified():
    record = trial()
    record["source_sha256"].append("b" * 64)
    before = copy.deepcopy(record)
    assert evaluate([record])["layouts"]["single"]["count"] == 1
    assert record == before


def test_cli_has_file_limit_and_json_output(tmp_path, capsys):
    module = importlib.import_module("scripts.capture_evaluation")
    path = tmp_path / "records.json"
    path.write_text(json.dumps([trial()]))
    assert module.main([str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["test_records"] == 1
    with path.open("wb") as stream:
        stream.truncate(8 * 1024 * 1024 + 1)
    with pytest.raises(SystemExit) as error:
        module.main([str(path)])
    assert error.value.code == 2
