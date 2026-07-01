"""Central version & contract identifiers.

Every externally observable contract gets its own version string so clients
(Android / iOS / Rokid / Android XR) can negotiate behavior and so we can
evolve one contract without silently breaking another.

Bump rules (semantic-ish):
- API_VERSION:          the URL/JSON envelope shape of the HTTP API.
- MATCHER_VERSION:      pHash/OCR-MD5 scoring algorithm & thresholds.
- HUD_CONTRACT_VERSION: the on-glass HUD payload shape (line count, fields).
- ANALYZER_API_VERSION: the analyzer plugin interface (app/analyzers/base.py).
- EXPLAINER_API_VERSION: the explainer plugin interface (app/explainer.py).

Clients should treat an unknown *major* bump as "ask the user to update".
"""

from __future__ import annotations

# 0.4.0: real Anthropic Claude adapters shipped for every provider port
#        (analyzer/solver/explainer/extractor). Offline local placeholders
#        remain the default; the cloud path is opt-in via ROKID_*=claude +
#        ANTHROPIC_API_KEY. The HTTP envelope (API_VERSION) is unchanged;
#        /v1/version now additionally lists the "claude" adapters.
# 0.5.0: multi-vendor adapters (claude/openai/gemini) for every port;
#        /v1/settings now publishes an `input` KeyCode contract (overridable via
#        ROKID_KEYMAP); optional bearer auth (ROKID_API_KEY). API_VERSION stays
#        1.6.0 (envelope unchanged; /v1/settings gains an additive block).
APP_VERSION = "0.5.0"

# HTTP API envelope. Path prefix stays "/v1" until a breaking envelope change.
# 1.2.0: /match responses gained the additive `ocr_similarity` field.
# 1.3.0: added exam-solving endpoints (/v1/exam-sessions, /v1/settings).
# 1.4.0: /v1/settings advertises the full render+capture contract (white_flash,
#        transition, brightness, capture.shutter_sound, capture.privacy_led) and
#        add_question returns a silent `capture_ack`.
# 1.5.0: add_question returns extracted `media`; solve returns `evidence` and
#        `served_by`; new .../reasoning endpoint; overlay gains tracking metadata.
# 1.6.0: added /v1/explain-sessions — live multi-page document explanation with
#        per-page RAG context. /v1/version now includes `explainers` list.
API_VERSION = "1.6.0"

# Matching algorithm identity. Bump when thresholds or hashing change so a
# re-index/eval is triggered. Mirrors thresholds in app/matching.py.
# 1.1.0: OCR signal is now graded text similarity, not exact MD5 only.
MATCHER_VERSION = "1.1.0"

# HUD payload shape: {verdict, confidence, lines:[3]}.
HUD_CONTRACT_VERSION = "1.0.0"

# Analyzer plugin interface (provider-agnostic OCR/summary/embedding).
ANALYZER_API_VERSION = "1.0.0"

# Solver plugin interface (provider-agnostic question answering).
SOLVER_API_VERSION = "1.0.0"

# Media-extractor plugin interface (formula/figure/graph/table).
EXTRACTOR_API_VERSION = "1.0.0"

# Explainer plugin interface (live page explanation with RAG context).
EXPLAINER_API_VERSION = "1.0.0"

# On-glasses staged view payload (silent, <=3 lines per page, paginated stages).
# 1.1.0: added the silent `capture_ack` payload (no sound/flash on capture).
# 1.2.0: removed server-side character-per-line truncation (was [:24]).
#        Client renderer is now solely responsible for text reflow.
#        _wrap() returns each logical line as-is; pagination is line-count only.
GLASSES_VIEW_CONTRACT_VERSION = "1.2.0"

# Answer-area overlay payload (box + short answer; 2D image-anchored).
# 1.1.0: added tracking metadata (tracking/fixed_ar/anchor_hint).
OVERLAY_CONTRACT_VERSION = "1.1.0"


def version_info() -> dict:
    """Machine-readable version block embedded in API responses."""
    return {
        "app_version": APP_VERSION,
        "api_version": API_VERSION,
        "matcher_version": MATCHER_VERSION,
        "hud_contract_version": HUD_CONTRACT_VERSION,
        "analyzer_api_version": ANALYZER_API_VERSION,
        "solver_api_version": SOLVER_API_VERSION,
        "extractor_api_version": EXTRACTOR_API_VERSION,
        "explainer_api_version": EXPLAINER_API_VERSION,
        "glasses_view_contract_version": GLASSES_VIEW_CONTRACT_VERSION,
        "overlay_contract_version": OVERLAY_CONTRACT_VERSION,
    }
