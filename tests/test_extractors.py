from app.extractors import (
    KINDS,
    ExtractorResult,
    MediaExtractor,
    detect_media,
    get_extractor,
    list_extractors,
    register_extractor,
)
from app.extractors.local_placeholder import LocalPlaceholderExtractor


def test_local_extractor_registered_and_offline():
    names = [e["name"] for e in list_extractors()]
    assert "local" in names
    assert get_extractor().offline is True


def test_handles_each_kind_without_raising():
    ex = get_extractor("local")
    for kind in KINDS:
        r = ex.extract(kind=kind, ocr_text="図1 と 表2 と グラフ x = 1")
        assert r.kind == kind
        assert r.content  # non-empty placeholder
        # Placeholder must look unconfident — it is not a real extraction.
        assert r.confidence <= 0.3


def test_safe_on_empty_input():
    r = get_extractor().extract(ocr_text=None)
    assert isinstance(r, ExtractorResult)
    assert r.confidence == 0.0


def test_detect_media_finds_kinds():
    assert detect_media("これは 図1 です") == ["figure"]
    assert "table" in detect_media("表3 を見よ")
    assert "math" in detect_media("2x + 3 = 7 を解け")
    assert detect_media("ただの文章") == []


def test_registry_falls_back_to_local_for_unknown():
    assert get_extractor("does-not-exist").name == "local"


def test_register_and_route_custom_extractor():
    class DummyExtractor(MediaExtractor):
        name = "dummy-extractor"
        provider_version = "t-1"
        offline = True

        def extract(self, *, image_path=None, ocr_text=None, kind=None, region=None):
            return ExtractorResult(kind=kind or "figure", content="DUMMY", confidence=1.0)

    register_extractor(DummyExtractor(), replace=True)
    assert get_extractor("dummy-extractor").extract(kind="math").content == "DUMMY"
    # default routing still returns local
    assert get_extractor().name == "local"


def test_local_placeholder_detects_math_from_text():
    r = LocalPlaceholderExtractor().extract(ocr_text="y = 2x + 1")
    assert r.kind == "math"
