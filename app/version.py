"""Central version & contract identifiers.

Every externally observable contract gets its own version string so clients
(Android / iOS / Rokid / Android XR) can negotiate behavior and so we can
evolve one contract without silently breaking another.

Bump rules (semantic-ish):
- API_VERSION:          the URL/JSON envelope shape of the HTTP API.
- MATCHER_VERSION:      pHash/OCR-MD5 scoring algorithm & thresholds.
- HUD_CONTRACT_VERSION: the on-glass HUD payload shape (line count, fields).
- ANALYZER_API_VERSION: the analyzer plugin interface (app/analyzers/base.py).

Clients should treat an unknown *major* bump as "ask the user to update".
"""

from __future__ import annotations

APP_VERSION = "0.2.0"

# HTTP API envelope. Path prefix stays "/v1" until a breaking envelope change.
API_VERSION = "1.1.0"

# Matching algorithm identity. Bump when thresholds or hashing change so a
# re-index/eval is triggered. Mirrors thresholds in app/matching.py.
MATCHER_VERSION = "1.0.0"

# HUD payload shape: {verdict, confidence, lines:[3]}.
HUD_CONTRACT_VERSION = "1.0.0"

# Analyzer plugin interface (provider-agnostic OCR/summary/embedding).
ANALYZER_API_VERSION = "1.0.0"


def version_info() -> dict:
    """Machine-readable version block embedded in API responses."""
    return {
        "app_version": APP_VERSION,
        "api_version": API_VERSION,
        "matcher_version": MATCHER_VERSION,
        "hud_contract_version": HUD_CONTRACT_VERSION,
        "analyzer_api_version": ANALYZER_API_VERSION,
    }
