"""Synthetic evidence supplied by a trusted caller, not image certification."""
import copy
import importlib

import pytest

SHA = "a" * 64


def evidence(layout="single"):
    return {"schema": 1, "source_sha256": SHA, "rotation": 270,
            "inventory_complete": True, "profile_id": "reviewed-profile", "layout": layout,
            "pages": [{"id": str(i), "paper_bounds": "pass", "occlusion": "pass",
                       "regions": [{"id": "r1", "kind": "text", "source_detail": "pass",
                                    "exposure": "pass", "readability": "pass"}]}
                      for i in range(2 if layout == "spread" else 1)]}


def assess(value, profiles=()):
    return importlib.import_module("scripts.capture_admission").assess_capture(
        value, source_sha256=SHA, rotation=270, validated_profiles=profiles)


@pytest.mark.parametrize("layout", ["single", "spread"])
def test_profile_is_trusted_only_from_the_caller_and_input_stays_unchanged(layout):
    value = evidence(layout)
    before = copy.deepcopy(value)
    assert assess(value)["decision"] == "hold"
    result = assess(value, ["reviewed-profile"])
    assert result["decision"] == "eligible"
    assert result["guarantees_all_content"] is False
    assert value == before
    value["validated_profiles"] = ["reviewed-profile"]
    assert assess(value)["decision"] == "hold"


@pytest.mark.parametrize("profiles", ["reviewed-profile-other", None, [None]])
def test_invalid_profile_collection_never_grants_substring_approval(profiles):
    assert assess(evidence(), profiles)["decision"] == "hold"


@pytest.mark.parametrize("scope,field", [
    ("page", "paper_bounds"), ("page", "occlusion"),
    ("region", "source_detail"), ("region", "exposure"), ("region", "readability"),
])
def test_known_failure_retakes_but_unknown_holds(scope, field):
    value = evidence()
    target = value["pages"][0]
    if scope == "region":
        target = target["regions"][0]
    target[field] = "unknown"
    assert assess(value, ["reviewed-profile"])["decision"] == "hold"
    target[field] = "fail"
    assert assess(value)["decision"] == "retake"
    value["source_sha256"] = "b" * 64
    assert assess(value, ["reviewed-profile"])["decision"] == "hold"


@pytest.mark.parametrize("field,bad", [
    ("schema", True), ("schema", 2), ("source_sha256", "wrong"), ("rotation", 0),
    ("rotation", 270.0), ("inventory_complete", "yes"), ("inventory_complete", False),
    ("profile_id", None), ("layout", "unknown"), ("pages", []), ("pages", "page"),
])
def test_invalid_or_incomplete_envelope_holds(field, bad):
    value = evidence()
    value[field] = bad
    assert assess(value, ["reviewed-profile"])["decision"] == "hold"


@pytest.mark.parametrize("mutation", ["page_duplicate", "region_duplicate", "extra_page", "too_many_regions",
    "empty_regions", "long_page_id", "blank_region_id", "unknown_kind", "nonstring_kind", "invalid_verdict", "missing_field"])
def test_invalid_inventory_holds(mutation):
    value = evidence("spread")
    page = value["pages"][0]
    region = page["regions"][0]
    if mutation == "page_duplicate":
        value["pages"][1]["id"] = page["id"]
    elif mutation == "region_duplicate":
        page["regions"].append(copy.deepcopy(region))
    elif mutation == "extra_page":
        value["pages"].append(copy.deepcopy(page))
    elif mutation == "too_many_regions":
        page["regions"] = [dict(region, id=str(i)) for i in range(257)]
    elif mutation == "empty_regions":
        page["regions"] = []
    elif mutation == "long_page_id":
        page["id"] = "x" * 81
    elif mutation == "blank_region_id":
        region["id"] = " "
    elif mutation == "unknown_kind":
        region["kind"] = "answer"
    elif mutation == "nonstring_kind":
        region["kind"] = []
    elif mutation == "invalid_verdict":
        region["readability"] = True
    else:
        del page["occlusion"]
    assert assess(value, ["reviewed-profile"])["decision"] == "hold"


@pytest.mark.parametrize("kind", ["text", "math", "figure", "table", "blank"])
def test_all_region_kinds_require_readability_evidence(kind):
    value = evidence()
    value["pages"][0]["regions"][0]["kind"] = kind
    assert assess(value, ["reviewed-profile"])["decision"] == "eligible"


@pytest.mark.parametrize("value", [None, [], "pass", {"schema": 1}])
def test_malformed_input_never_raises_or_approves(value):
    result = assess(value, ["reviewed-profile"])
    assert result["decision"] == "hold" and result["reasons"]
