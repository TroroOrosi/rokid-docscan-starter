from app import version
from app.analyzers import (
    Analyzer,
    AnalyzerResult,
    get_analyzer,
    list_analyzers,
    register_analyzer,
)
from app.analyzers.local_placeholder import LocalPlaceholderAnalyzer


# --- version module ---------------------------------------------------------

def test_version_info_has_all_contracts():
    info = version.version_info()
    for key in (
        "app_version",
        "api_version",
        "matcher_version",
        "hud_contract_version",
        "analyzer_api_version",
        "solver_api_version",
        "extractor_api_version",
        "explainer_api_version",
        "glasses_view_contract_version",
        "overlay_contract_version",
    ):
        assert key in info and isinstance(info[key], str)


def test_contract_versions_reflect_silent_capture_contract():
    # Bumped when /v1/settings gained the render+capture contract and
    # add_question gained the silent capture_ack payload.
    assert version.GLASSES_VIEW_CONTRACT_VERSION == "1.1.0"


def test_contract_versions_reflect_phase234():
    # Phase 2/3/4: media extraction, RAG evidence/served_by, reasoning endpoint,
    # and overlay tracking metadata.
    assert version.EXTRACTOR_API_VERSION == "1.0.0"
    assert version.OVERLAY_CONTRACT_VERSION == "1.1.0"


def test_contract_versions_reflect_explain_sessions():
    # 1.6.0: added /v1/explain-sessions (live multi-page document explanation).
    assert version.API_VERSION == "1.6.0"
    assert version.EXPLAINER_API_VERSION == "1.0.0"


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
