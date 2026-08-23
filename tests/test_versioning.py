from app import version
from app.analyzers import (
    Analyzer,
    AnalyzerResult,
    get_analyzer,
    list_analyzers,
    register_analyzer,
)


# --- version module ---------------------------------------------------------

def test_version_info_pins_every_contract():
    # FULL pin of all 10 fields: any bump anywhere must fail here, forcing the
    # simultaneous doc/pin update CLAUDE.md requires (no silent version drift —
    # docs hardcode several of these, e.g. user-operation-guide's JSON block).
    assert version.version_info() == {
        "app_version": "0.14.0",
        "api_version": "1.13.1",
        "matcher_version": "1.2.0",
        "hud_contract_version": "1.0.0",
        "analyzer_api_version": "1.0.0",
        "solver_api_version": "1.2.0",
        "extractor_api_version": "1.0.0",
        "explainer_api_version": "1.1.0",
        "glasses_view_contract_version": "1.8.0",
        "overlay_contract_version": "1.1.0",
    }


def test_glasses_contract_reflects_explicit_capture_review():
    # 1.8.0: snapshots are reviewed before upload; safe gestures retake and
    # an intentional long press confirms registration.
    assert version.GLASSES_VIEW_CONTRACT_VERSION == "1.8.0"


def test_contract_versions_reflect_phase234():
    # Phase 2/3/4: media extraction, RAG evidence/served_by, reasoning endpoint,
    # and overlay tracking metadata.
    assert version.EXTRACTOR_API_VERSION == "1.0.0"
    assert version.OVERLAY_CONTRACT_VERSION == "1.1.0"


def test_contract_versions_reflect_review_and_media_integrity():
    # 1.13.1: decoded image limits consistently return 413 and OpenAI only
    # receives a documented transcription container.
    assert version.API_VERSION == "1.13.1"
    assert version.SOLVER_API_VERSION == "1.2.0"
    assert version.EXPLAINER_API_VERSION == "1.1.0"


# --- analyzer registry ------------------------------------------------------

def test_local_analyzer_registered_and_offline():
    names = [a["name"] for a in list_analyzers()]
    assert "local" in names
    assert get_analyzer().offline is True


def test_local_analyzer_summarizes_and_is_safe_on_empty():
    a = get_analyzer("local")
    assert a.analyze(ocr_text="Hello\nWorld").summary == "Hello"
    # empty input must not raise
    assert a.analyze(ocr_text=None).summary == "(no text)"


def test_registry_falls_back_to_local_for_unknown():
    a = get_analyzer("does-not-exist")
    assert a.name == "local"


def test_register_and_route_custom_analyzer():
    class DummyAnalyzer(Analyzer):
        name = "dummy-test"
        provider_version = "t-1"
        offline = True

        def analyze(self, *, image_path=None, ocr_text=None, max_summary_len=48):
            return AnalyzerResult(text=ocr_text, summary="DUMMY")

    register_analyzer(DummyAnalyzer(), replace=True)
    assert get_analyzer("dummy-test").analyze(ocr_text="x").summary == "DUMMY"
    # default routing still returns local
    assert get_analyzer().name == "local"


def test_summarize_shim_delegates_to_analyzer():
    from app.summarize import summarize_page

    assert summarize_page("First line\nsecond") == "First line"
