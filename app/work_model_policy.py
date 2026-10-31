"""Pure policy for resolving a new job's model from public Work radio labels.

The result is a label to select and seal, never proof of the UI's selected model.
Do not resolve again for pending, uncertain or same-book listening continuations.
"""

from collections.abc import Iterable
import re
import unicodedata


# Shared grammar boundary: Work's control reader can import these definitions.
MODEL_PATTERN = (r"(?:gpt[\s_–—-]*)?(?:([0-9]+(?:\.[0-9]+)*)[\s_–—-]*([a-z]+)"
                 r"|([a-z]+)[\s_–—-]*([0-9]+(?:\.[0-9]+)*))")


class WorkModelPolicyError(ValueError):
    """The public labels cannot establish one permitted model."""


def model_identity(value: str) -> str | None:
    """Preserve Work's existing version:family label grammar."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(MODEL_PATTERN, unicodedata.normalize("NFKC", value).strip().lower())
    return f"{match[1] or match[4]}:{match[2] or match[3]}" if match else None


def resolve_work_model(
    candidates: Iterable[str], requested: str = "GPT-6.1 Sol", *, follow_family: bool = False,
) -> str:
    """Return one actual label, exact by default or highest same-family >= requested.

    Default and other families cannot become fallbacks. An unreadable candidate
    blocks follow mode: ignoring it could silently retain an older version.
    Duplicate highest controls are ambiguous even when their labels are identical.
    """
    identity = model_identity(requested)
    if identity is None or not isinstance(follow_family, bool):
        raise WorkModelPolicyError("Invalid requested model or follow-family policy")
    if isinstance(candidates, (str, bytes)):
        raise WorkModelPolicyError("Expected public model label strings")
    try:
        labels = iter(candidates)
    except TypeError as error:
        raise WorkModelPolicyError("Expected public model label strings") from error
    requested_version, requested_family = identity.split(":")
    minimum = tuple(int(part) for part in requested_version.split("."))
    eligible = []
    for label in labels:
        if not isinstance(label, str):
            raise WorkModelPolicyError("Expected public model label strings")
        candidate_identity = model_identity(label)
        if candidate_identity is None:
            if unicodedata.normalize("NFKC", label).strip().lower() == "default":
                continue
            if follow_family:
                raise WorkModelPolicyError("Unreadable public model label")
            continue
        version, family = candidate_identity.split(":")
        numeric_version = tuple(int(part) for part in version.split("."))
        if family == requested_family and (
            numeric_version >= minimum if follow_family else candidate_identity == identity
        ):
            eligible.append((numeric_version, label))
    if not eligible:
        raise WorkModelPolicyError("No permitted public model label")
    highest = max(version for version, _ in eligible)
    matches = [label for version, label in eligible if version == highest]
    if len(matches) != 1:
        raise WorkModelPolicyError("Public model labels are ambiguous")
    return matches[0]
