"""PC-only PDF image measurements; never upload PDFs, text, or images.

PDF glyph geometry and object counts describe the source, not OCR accuracy.
Run: python -m scripts.measure_exam_materials MANIFEST --out NEW_DIRECTORY
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import platform
import sys
import time
from html import escape
from contextlib import closing
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.source_bundle import source_images
from scripts.capture_preflight import MAX_PIXELS
from scripts.capture_quality import measure_tile


def _p10(values):
    return sorted(values)[math.ceil(len(values) * .1) - 1] if values else None


def _page_metrics(page):
    import pypdfium2 as pdfium

    scale = 1000 / page.get_width()
    rotated = page.get_rotation() in (90, 270)
    heights, fonts, centers = [], [], []
    with closing(page.get_textpage()) as text:
        total_chars = text.count_chars()
        for index in range(total_chars):
            code = pdfium.raw.FPDFText_GetUnicode(text, index)
            if not code or chr(code).isspace():
                continue
            left, bottom, right, top = text.get_charbox(index)
            height = (right - left if rotated else top - bottom) * scale
            if height <= 0:
                continue
            heights.append(height)
            fonts.append(pdfium.raw.FPDFText_GetFontSize(text, index) * scale)
            center = ((left + right) / 2, (bottom + top) / 2)
            centers.append(center[::-1] if rotated else center)
    font_median = sorted(fonts)[len(fonts) // 2] if fonts else None
    vertical = sum(abs(y2-y1) > 2*abs(x2-x1) and 0 < abs(y2-y1)*scale < 60
                   for (x1, y1), (x2, y2) in zip(centers, centers[1:]))
    counts = {pdfium.raw.FPDF_PAGEOBJ_PATH: 0, pdfium.raw.FPDF_PAGEOBJ_IMAGE: 0}
    for obj in page.get_objects():
        if obj.type in counts:
            counts[obj.type] += 1
    return {
        "pdf_text_characters": total_chars,
        "measured_glyphs": len(heights),
        "char_height_p10_at_1000px": _p10(heights),
        "char_height_median_at_1000px": sorted(heights)[len(heights)//2] if heights else None,
        "glyphs_below_12px_at_1000_fraction": sum(h < 12 for h in heights) / len(heights) if heights else None,
        "small_font_fraction": sum(f < font_median * .75 for f in fonts) / len(fonts) if fonts else None,
        "vertical_adjacent_glyph_fraction": vertical / (len(centers)-1) if len(centers) > 1 else None,
        "vector_path_objects": counts[pdfium.raw.FPDF_PAGEOBJ_PATH],
        "embedded_image_objects": counts[pdfium.raw.FPDF_PAGEOBJ_IMAGE],
    }, heights


def _csv(path, rows):
    scalar_rows = [{k: v for k, v in row.items() if not isinstance(v, (list, dict))} for row in rows]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(scalar_rows[0]))
        writer.writeheader()
        writer.writerows(scalar_rows)


def _chart(path, materials, key, title):
    maximum = max((m[key] or 0 for m in materials), default=0) or 1
    colors = {year: ("#176aa4", "#be620f", "#39804f")[i % 3]
              for i, year in enumerate(sorted({m["year"] for m in materials}))}
    height = 150 + len(materials)*34
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1800" height="{height}" role="img">',
             f'<title>{escape(title)}</title><rect width="100%" height="100%" fill="white"/>',
             '<g font-family="sans-serif" font-size="16" fill="#222">',
             f'<text x="24" y="32" font-size="24">{escape(title)}</text>',
             '<text x="24" y="60">PDF原本のPC計測。実写の文字正読率・正答率・GPT解析時間は未測定。</text>']
    for index, material in enumerate(materials):
        y = 96 + index*34
        label = f'{material["exam"]} / {material["subject"]} / {material["year"]}'
        value = material[key]
        display = f"{value:.3f}" if value is not None else "PDF文字領域なし"
        if key == "char_height_p10_at_1000px":
            display += f' ({material["glyph_geometry_pages"]}/{material["page_count"]}頁の文字領域)'
        parts.extend([f'<text x="24" y="{y+18}">{escape(label)}</text>',
                      f'<rect x="650" y="{y}" width="{620*(value or 0)/maximum:.2f}" height="23" fill="{colors[material["year"]]}"/>',
                      f'<text x="1280" y="{y+18}">{display}</text>'])
    parts.append('</g></svg>')
    path.write_text("\n".join(parts), encoding="utf-8")


def measure_materials(manifest: Path, output: Path) -> dict:
    import pypdfium2 as pdfium

    manifest = Path(manifest).resolve()
    manifest_bytes = manifest.read_bytes()
    spec = json.loads(manifest_bytes)
    if not isinstance(spec, dict):
        raise ValueError("manifest must be an object")
    materials = spec.get("materials")
    width = spec.get("page_width_px", 1000)
    if not isinstance(materials, list) or not materials or type(width) is not int or not 256 <= width <= 4096:
        raise ValueError("materials must be nonempty and page_width_px must be 256..4096")
    identities = set()
    for entry in materials:
        if (not isinstance(entry, dict) or any(not isinstance(entry.get(k), str) or not entry[k]
                for k in ("exam", "subject", "path", "source_url"))
                or type(entry.get("year")) is not int
                or type(entry.get("complete_for_correctness")) is not bool):
            raise ValueError("each material needs exam, subject, year, path, source_url and an explicit completeness flag")
        identity = (entry["exam"], entry["subject"], entry["year"])
        if identity in identities or "英語" in entry["subject"] or "english" in entry["subject"].lower():
            raise ValueError("duplicate subject/year or English material outside the requested scope")
        identities.add(identity)
        pages = entry.get("pages")
        if pages is not None and (not isinstance(pages, list) or not pages or
                any(type(p) is not int or p < 1 for p in pages) or pages != sorted(set(pages))):
            raise ValueError("pages must be increasing unique positive PDF page numbers")
        if not (manifest.parent / entry["path"]).is_file():
            raise FileNotFoundError(entry["path"])
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)  # A new directory protects inputs and previous measurements.
    report = {
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "page_width_px": width,
        "runtime": {"python": platform.python_version(), "platform": platform.platform(),
                    "pypdfium2": str(pdfium.PYPDFIUM_INFO), "pdfium": str(pdfium.PDFIUM_INFO),
                    "pillow": Image.__version__},
        "limits": ["PDF glyph geometry is not OCR accuracy or an answer-correctness measurement.",
                   "12px and 75% font-size comparisons are exploratory, not acceptance gates.",
                   "Path/image object counts are not counts of graphs, tables or mathematical expressions.",
                   "PDF object traversal uses the installed PDFium helper's 15-level form depth limit.",
                   "Image contrast/adjacent-pixel differences depend on content and scale, not just readability.",
                   "Times measure this PC's local processing; GPT analysis and physical-paper tests are unmeasured."],
        "materials": [],
    }
    for number, entry in enumerate(materials, 1):
        start = time.perf_counter()
        source = (manifest.parent / entry["path"]).resolve()
        data = source.read_bytes()
        folder = output / f"material{number:03d}"
        folder.mkdir()
        rows, heights = [], []
        with pdfium.PdfDocument(data) as document:
            pages = entry.get("pages") or list(range(1, len(document)+1))
            if not pages or pages[-1] > len(document):
                raise ValueError(f"material {number} selects a PDF page outside the document")
            pdf_page_count = len(document)
            for page_number in pages:
                with closing(document[page_number-1]) as page:
                    if math.ceil(page.get_height() * width/page.get_width()) * width > MAX_PIXELS:
                        raise ValueError("rendered PDF page exceeds the existing capture measurement pixel limit")
                    stamp = time.perf_counter()
                    with closing(page.render(scale=width/page.get_width())) as bitmap:
                        image = bitmap.to_pil().convert("RGB")
                    original = folder / f"page{page_number:03d}.png"
                    with image:
                        image.save(original)
                        dimensions = image.size
                    render_seconds = time.perf_counter() - stamp
                    stamp = time.perf_counter()
                    metrics, page_heights = _page_metrics(page)
                    with Image.open(original) as original_image:
                        image_metrics = measure_tile(original_image)
                    metrics.update({"image_luminance_p05": image_metrics["luminance_p05_p50_p95"][0],
                                    "image_luminance_p50": image_metrics["luminance_p05_p50_p95"][1],
                                    "image_luminance_p95": image_metrics["luminance_p05_p50_p95"][2],
                                    "image_near_black_fraction": image_metrics["near_black_fraction"],
                                    "image_near_white_fraction": image_metrics["near_white_fraction"],
                                    "image_adjacent_difference_proxy": image_metrics["mean_adjacent_difference"]})
                    metrics_seconds = time.perf_counter() - stamp
                stamp = time.perf_counter()
                attachments = []
                for item in source_images([{"page_number": page_number, "image_path": str(original)}]):
                    path = folder / item["name"]
                    path.write_bytes(item["buffer"])
                    with Image.open(io.BytesIO(item["buffer"])) as prepared:
                        attachments.append({"path": path.relative_to(output).as_posix(),
                                            "width_px": prepared.width, "height_px": prepared.height,
                                            "bytes": len(item["buffer"]),
                                            "sha256": hashlib.sha256(item["buffer"]).hexdigest()})
                rows.append({"exam": entry["exam"], "subject": entry["subject"], "year": entry["year"],
                             "pdf_page": page_number, "width_px": dimensions[0], "height_px": dimensions[1],
                             **metrics, "render_seconds": render_seconds, "metrics_seconds": metrics_seconds,
                             "attachment_seconds": time.perf_counter() - stamp,
                             "attachment_count": len(attachments), "attachments": attachments,
                             "original_image": original.relative_to(output).as_posix()})
                heights.extend(page_heights)
        count = sum(r["attachment_count"] for r in rows)
        glyph_pages = sum(r["measured_glyphs"] > 0 for r in rows)
        summary = {"exam": entry["exam"], "subject": entry["subject"], "year": entry["year"],
                   "source_path": str(source), "source_url": entry["source_url"],
                   "source_sha256": hashlib.sha256(data).hexdigest(), "source_bytes": len(data),
                   "complete_for_correctness": entry["complete_for_correctness"], "notes": entry.get("notes", ""),
                   "selected_pdf_pages": pages, "pdf_page_count": pdf_page_count,
                   "covers_entire_pdf": len(pages) == pdf_page_count, "page_count": len(rows),
                   "attachment_count": count, "image_only_batches_at_20": math.ceil(count/20),
                   "measured_glyphs": len(heights), "char_height_p10_at_1000px": _p10(heights),
                   "glyph_geometry_pages": glyph_pages, "glyph_geometry_page_fraction": glyph_pages/len(rows),
                   "glyphs_below_12px_at_1000_fraction": sum(h < 12 for h in heights)/len(heights) if heights else None,
                   "vector_path_objects": sum(r["vector_path_objects"] for r in rows),
                   "embedded_image_objects": sum(r["embedded_image_objects"] for r in rows),
                   **{key: sum(r[key] for r in rows) for key in ("render_seconds", "metrics_seconds", "attachment_seconds")},
                   "local_total_seconds": time.perf_counter()-start, "gpt_analysis_seconds": None,
                   "page_measurements": rows}
        summary["representative_pdf_pages"] = {}
        for name, key, choose in [("smallest_glyphs", "char_height_p10_at_1000px", min),
                                  ("most_vector_paths", "vector_path_objects", max),
                                  ("most_image_objects", "embedded_image_objects", max),
                                  ("most_small_font_glyphs", "small_font_fraction", max),
                                  ("most_vertical_adjacent_glyphs", "vertical_adjacent_glyph_fraction", max)]:
            candidates = [r for r in rows if r[key] is not None and r[key] > 0]
            summary["representative_pdf_pages"][name] = choose(candidates, key=lambda r: r[key])["pdf_page"] if candidates else None
        report["materials"].append(summary)
    (output / "measurements.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _csv(output / "materials.csv", report["materials"])
    _csv(output / "pages.csv", [r for m in report["materials"] for r in m["page_measurements"]])
    for name, key, title in [("page-count", "page_count", "教科・年度別の対象PDF頁数"),
                             ("glyph-height", "char_height_p10_at_1000px", "文字領域高さの下位10%値（頁幅1000px換算）"),
                             ("local-processing-seconds", "local_total_seconds", "教科・年度別のPC処理秒（描画・計測・添付前処理）")]:
        _chart(output / f"{name}.svg", report["materials"], key, title)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = measure_materials(args.manifest, args.out)
    except (OSError, ValueError, RuntimeError, ImportError) as error:
        print(f"FAIL {type(error).__name__}; existing inputs and reports were not overwritten")
        return 2
    print(json.dumps({"materials": len(report["materials"]),
                      "pages": sum(m["page_count"] for m in report["materials"]),
                      "gpt_analysis_performed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
