"""Evaluate supplied capture evidence; does not produce or authenticate that evidence.

No profiles are approved by default. This PC component is not a capture/upload gate.
"""
from __future__ import annotations

import re


def assess_capture(evidence: object, *, source_sha256: str, rotation: int,
                   validated_profiles=()) -> dict:
    def result(decision, reason):
        return {"schema": 1, "decision": decision, "reasons": [reason],
                "guarantees_all_content": False}

    def identifier(value):
        return isinstance(value, str) and bool(value.strip()) and 1 <= len(value) <= 80

    def verdict(value):
        return isinstance(value, str) and value in ("pass", "fail", "unknown")

    if (not isinstance(evidence, dict) or type(evidence.get("schema")) is not int
            or evidence["schema"] != 1):
        return result("hold", "invalid_schema")
    if (not isinstance(source_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
            or evidence.get("source_sha256") != source_sha256
            or type(rotation) is not int or rotation not in (0, 90, 180, 270)
            or type(evidence.get("rotation")) is not int or evidence["rotation"] != rotation):
        return result("hold", "source_identity_mismatch")
    layout, pages = evidence.get("layout"), evidence.get("pages")
    if (layout not in ("single", "spread") or not isinstance(pages, list)
            or len(pages) != (1 if layout == "single" else 2)
            or type(evidence.get("inventory_complete")) is not bool
            or not identifier(evidence.get("profile_id"))):
        return result("hold", "invalid_inventory")
    outcomes, page_ids = [], set()
    for page in pages:
        if not isinstance(page, dict) or not identifier(page.get("id")) or page["id"] in page_ids:
            return result("hold", "invalid_page_identity")
        page_ids.add(page["id"])
        outcomes.extend(page.get(field) for field in ("paper_bounds", "occlusion"))
        regions = page.get("regions")
        if not isinstance(regions, list) or not 1 <= len(regions) <= 256:
            return result("hold", "invalid_regions")
        region_ids = set()
        for region in regions:
            if (not isinstance(region, dict) or not identifier(region.get("id"))
                    or region["id"] in region_ids
                    or region.get("kind") not in ("text", "math", "figure", "table", "blank")):
                return result("hold", "invalid_region_identity_or_kind")
            region_ids.add(region["id"])
            outcomes.extend(region.get(field) for field in ("source_detail", "exposure", "readability"))
    if not all(verdict(value) for value in outcomes):
        return result("hold", "invalid_or_missing_verdict")
    if "fail" in outcomes:
        return result("retake", "known_quality_failure")
    if not evidence["inventory_complete"] or "unknown" in outcomes:
        return result("hold", "incomplete_evidence")
    if (not isinstance(validated_profiles, (tuple, list, set, frozenset))
            or not all(identifier(profile) for profile in validated_profiles)
            or evidence["profile_id"] not in validated_profiles):
        return result("hold", "profile_not_validated_by_caller")
    return result("eligible", "supplied_evidence_satisfies_profile")
