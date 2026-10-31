"""Resolve public Work model labels without UI, environment or job mutation."""

import pytest

from app.work_model_policy import (
    WorkModelPolicyError,
    model_identity,
    resolve_work_model,
)


@pytest.mark.parametrize("label", ["GPT-6.1 Sol", "gpt6.1sol", "Sol 6.1", "ＧＰＴ－６．１　Ｓｏｌ"])
def test_identity_keeps_the_existing_work_model_grammar(label):
    assert model_identity(label) == "6.1:sol"


def test_exact_is_the_default_and_returns_the_existing_public_label():
    existing = "  GPT 6.1 Sol  "
    assert resolve_work_model(["Default", "GPT-6.2 Sol", existing, "GPT-6.1 Terra"]) == existing


def test_follow_family_chooses_numeric_highest_version_without_switching_family():
    labels = ["Default", "GPT-6.2 Sol", "GPT-6.10 Sol", "GPT-7.0 Terra", "GPT-9.0 Astra", "GPT-6.0 Sol"]
    assert resolve_work_model(labels, follow_family=True) == "GPT-6.10 Sol"


def test_follow_family_can_use_the_baseline_when_it_is_the_only_eligible_model():
    assert resolve_work_model(["GPT-6.0 Sol", "Sol 6.1"], follow_family=True) == "Sol 6.1"


def test_requested_identity_sets_the_family_and_minimum_version():
    labels = ["GPT-6.10 Sol", "GPT-6.1 Terra", "Terra 6.3"]
    assert resolve_work_model(labels, "GPT-6.1 Terra", follow_family=True) == "Terra 6.3"


@pytest.mark.parametrize("follow", [False, True])
@pytest.mark.parametrize("labels", [[], ["Default"], ["GPT-6.0 Sol"], ["GPT-9.0 Luna"]])
def test_missing_eligible_model_never_falls_back_to_default_old_or_different_family(labels, follow):
    with pytest.raises(WorkModelPolicyError):
        resolve_work_model(labels, follow_family=follow)


@pytest.mark.parametrize("labels", [
    ["GPT-6.2 Sol", "GPT-6.2 Sol"],
    ["GPT-6.2 Sol", "Sol 6.2"],
    ["GPT-6.02 Sol", "Sol 6.2"],
])
def test_follow_family_rejects_duplicate_highest_controls_even_with_different_spellings(labels):
    with pytest.raises(WorkModelPolicyError, match="ambiguous"):
        resolve_work_model(labels, follow_family=True)


def test_duplicate_lower_versions_do_not_make_a_unique_highest_version_ambiguous():
    assert resolve_work_model(["GPT-6.1 Sol", "Sol 6.1", "GPT-6.2 Sol"], follow_family=True) == "GPT-6.2 Sol"


def test_exact_rejects_duplicate_matching_controls():
    with pytest.raises(WorkModelPolicyError, match="ambiguous"):
        resolve_work_model(["GPT-6.1 Sol", "Sol 6.1"])


def test_exact_does_not_silently_upgrade_when_only_a_newer_version_exists():
    with pytest.raises(WorkModelPolicyError):
        resolve_work_model(["GPT-6.2 Sol"])


@pytest.mark.parametrize("label", ["Latest", "GPT-Next Sol", "GPT-6.2 Sol recommended", "6.2", ""])
def test_unreadable_future_labels_do_not_silently_leave_follow_mode_on_an_old_model(label):
    with pytest.raises(WorkModelPolicyError):
        resolve_work_model(["GPT-6.1 Sol", label], follow_family=True)


@pytest.mark.parametrize("requested", ["Default", "Latest", "GPT-6.1", "", None])
def test_an_unreadable_requested_model_is_rejected(requested):
    with pytest.raises(WorkModelPolicyError):
        resolve_work_model(["GPT-6.1 Sol"], requested)


@pytest.mark.parametrize("labels", [None, "GPT-6.1 Sol", [None], ["GPT-6.1 Sol", 6.2]])
def test_candidates_must_be_public_label_strings(labels):
    with pytest.raises(WorkModelPolicyError):
        resolve_work_model(labels, follow_family=True)


def test_resolution_only_returns_a_label_and_does_not_mutate_the_candidate_list():
    labels = ["GPT-6.1 Sol", "Sol 6.2"]
    original = labels.copy()
    assert resolve_work_model(labels, follow_family=True) == "Sol 6.2"
    assert labels == original
