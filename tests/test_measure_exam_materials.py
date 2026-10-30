import ctypes
import json
import sys
from contextlib import closing

import pytest
from PIL import Image

from scripts.measure_exam_materials import _page_metrics, main, measure_materials


@pytest.fixture
def pdf(tmp_path, request):
    pdfium = pytest.importorskip("pypdfium2")
    raw = pdfium.raw
    path = tmp_path / "paper.pdf"
    with pdfium.PdfDocument.new() as document:
        page = document.new_page(500, 700)
        text = [] if getattr(request, "param", None) == "image-only" else [("ABC", 24, 50), ("x", 6, 150)]
        for value, size, x in text:
            obj = raw.FPDFPageObj_NewTextObj(document, b"Helvetica", size)
            buffer = (value + "\0").encode("utf-16-le")
            assert raw.FPDFText_SetText(obj, ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ushort)))
            raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, x, 600)
            page.insert_obj(pdfium.PdfObject(obj, pdf=document))
        rect = raw.FPDFPageObj_CreateNewRect(25, 25, 450, 650)
        assert raw.FPDFPath_SetDrawMode(rect, 0, 1)
        page.insert_obj(pdfium.PdfObject(rect, pdf=document))
        image = pdfium.PdfImage.new(document)
        with closing(pdfium.PdfBitmap.from_pil(Image.new("RGB", (40, 40), "red"))) as bitmap:
            image.set_bitmap(bitmap)
        image.set_matrix(pdfium.PdfMatrix(100, 0, 0, 100, 200, 300))
        page.insert_obj(image)
        page.gen_content()
        document.new_page(500, 700)
        document.save(path)
    return path


def test_metrics_count_glyphs_and_objects_at_a_common_image_scale(pdf):
    import pypdfium2 as pdfium

    with pdfium.PdfDocument(pdf) as document, closing(document[0]) as page:
        metrics, heights = _page_metrics(page)
        native = page.render(scale=2).to_pil()
        smaller = page.render(scale=1).to_pil()
        assert native.width == 1000 and smaller.width == 500
        assert metrics["measured_glyphs"] == 4
        assert metrics["glyphs_below_12px_at_1000_fraction"] == .25
        assert metrics["small_font_fraction"] == .25
        assert metrics["vector_path_objects"] == metrics["embedded_image_objects"] == 1
        assert metrics["char_height_p10_at_1000px"] == min(heights)
        # The glyph's PDF geometry is compared at 1000px regardless of rendering width.
        with closing(page.get_textpage()) as text:
            bbox = text.get_charbox(0)
        native_height = (bbox[3]-bbox[1]) * native.width/page.get_width()
        smaller_height = (bbox[3]-bbox[1]) * smaller.width/page.get_width()
        assert native_height == pytest.approx(smaller_height * 1000/smaller.width)
        assert heights[0] == pytest.approx(native_height)


def _manifest(tmp_path, pdf, **changes):
    entry = {"exam": "共通テスト", "subject": "物理", "year": 2026,
             "path": str(pdf), "source_url": "https://example.org/official.pdf",
             "complete_for_correctness": False, "notes": "資料1点省略", **changes}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"materials": [entry], "page_width_px": 500}), encoding="utf-8")
    return path


def test_local_measurement_preserves_images_and_incomplete_partial_scope(pdf, tmp_path):
    before = pdf.read_bytes()
    output = tmp_path / "measurement"
    report = measure_materials(_manifest(tmp_path, pdf, pages=[1]), output)
    material = report["materials"][0]
    assert material["page_count"] == material["attachment_count"] == material["image_only_batches_at_20"] == 1
    assert material["pdf_page_count"] == 2 and material["selected_pdf_pages"] == [1]
    assert material["glyph_geometry_pages"] == 1 and material["glyph_geometry_page_fraction"] == 1
    assert material["complete_for_correctness"] is material["covers_entire_pdf"] is False
    assert material["notes"] == "資料1点省略" and material["gpt_analysis_seconds"] is None
    assert material["render_seconds"] > 0 and material["attachment_seconds"] > 0
    row = material["page_measurements"][0]
    assert row["measured_glyphs"] == 4 and row["embedded_image_objects"] == 1
    assert row["image_near_black_fraction"] > 0 and row["image_adjacent_difference_proxy"] > 0
    assert material["representative_pdf_pages"]["most_image_objects"] == 1
    with Image.open(output / row["original_image"]) as original:
        assert original.size == (500, 700) and original.getpixel((250, 350)) == (255, 0, 0)
    with Image.open(output / row["attachments"][0]["path"]) as prepared:
        assert prepared.size == (500, 700)
        red, green, blue = prepared.getpixel((250, 350))
        assert red > 245 and green < 10 and blue < 10
    assert pdf.read_bytes() == before
    assert (output / "materials.csv").exists() and (output / "pages.csv").exists()
    assert json.loads((output / "measurements.json").read_text(encoding="utf-8")) == report
    assert {p.name for p in output.glob("*.svg")} == {"page-count.svg", "glyph-height.svg", "local-processing-seconds.svg"}
    with pytest.raises(FileExistsError):
        measure_materials(tmp_path / "manifest.json", output)
    assert pdf.read_bytes() == before


def test_actual_image_count_above_twenty_is_measured_without_a_page_cap(tmp_path):
    pdfium = pytest.importorskip("pypdfium2")
    path = tmp_path / "long.pdf"
    with pdfium.PdfDocument.new() as document:
        for _ in range(21):
            document.new_page(500, 700)
        document.save(path)
    material = measure_materials(_manifest(tmp_path, path, complete_for_correctness=True),
                                 tmp_path / "measurement")["materials"][0]
    assert material["page_count"] == material["attachment_count"] == 21
    assert material["image_only_batches_at_20"] == 2
    assert material["covers_entire_pdf"] is material["complete_for_correctness"] is True
    assert material["measured_glyphs"] == 0 and material["char_height_p10_at_1000px"] is None


def test_glyph_chart_identifies_geometry_present_on_only_one_of_two_pages(pdf, tmp_path):
    output = tmp_path / "measurement"
    material = measure_materials(_manifest(tmp_path, pdf), output)["materials"][0]
    assert material["page_count"] == 2 and material["glyph_geometry_pages"] == 1
    assert material["glyph_geometry_page_fraction"] == .5
    assert "1/2頁の文字領域" in (output / "glyph-height.svg").read_text(encoding="utf-8")


@pytest.mark.parametrize("pdf", ["image-only"], indirect=True)
def test_image_pdf_has_no_glyph_geometry_and_retains_image_measurements(pdf, tmp_path):
    output = tmp_path / "measurement"
    material = measure_materials(_manifest(tmp_path, pdf, pages=[1]),
                                 output)["materials"][0]
    row = material["page_measurements"][0]
    assert row["measured_glyphs"] == 0 and row["char_height_p10_at_1000px"] is None
    assert row["embedded_image_objects"] == 1 and row["image_adjacent_difference_proxy"] > 0
    assert material["representative_pdf_pages"]["smallest_glyphs"] is None
    assert material["representative_pdf_pages"]["most_image_objects"] == 1
    assert material["glyph_geometry_pages"] == material["glyph_geometry_page_fraction"] == 0
    assert "PDF文字領域なし (0/1頁の文字領域)" in (output / "glyph-height.svg").read_text(encoding="utf-8")


def test_cli_rejects_bad_json_without_creating_output_or_printing_its_contents(tmp_path, capsys, monkeypatch):
    monkeypatch.setitem(sys.modules, "pypdfium2", None)
    manifest = tmp_path / "bad.json"
    manifest.write_text("{", encoding="utf-8")
    output = tmp_path / "measurement"
    assert main([str(manifest), "--out", str(output)]) == 2
    assert capsys.readouterr().out == "FAIL JSONDecodeError; existing inputs and reports were not overwritten\n"
    assert not output.exists()


@pytest.mark.parametrize("changes", [{"pages": [True]}, {"pages": [1, 1]}, {"pages": []},
                                     {"subject": "英語"}, {"complete_for_correctness": 1}])
def test_invalid_or_excluded_materials_are_rejected_before_output(pdf, tmp_path, changes):
    output = tmp_path / "measurement"
    with pytest.raises(ValueError):
        measure_materials(_manifest(tmp_path, pdf, **changes), output)
    assert not output.exists()
