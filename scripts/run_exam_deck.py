#!/usr/bin/env python3
"""Run ONE exam subject through the whole server flow, from a PDF (PC bench).

The real input is the glasses camera. This stands in for it so the route can be
checked without hardware: each PDF page is rendered to a PNG exactly as a
photographed page would arrive, its text is extracted as the relay's ML Kit OCR
would provide it, and the document then goes through the ordinary endpoints --
pages -> finalize -> exam session -> finalize-reading (which is where the
solver, and therefore ChatGPT, actually runs) -> answer-bundle, the same
snapshot the glasses read.

One subject per invocation, on purpose. A sweep over every subject in one run
is what rate-limited the account on 2026-09-14; see
.agents/progress/subject-separation-harness.md. Use --pages to run a single 大問
while checking a change, and keep --solver local for anything that does not
need the real model.

    py -3.12 scripts/run_exam_deck.py --pdf C:/rokid-exam-materials/kyotsu/sugaku1A.pdf \
        --subject 数学 --pages 1-8 --solver local
    py -3.12 scripts/run_exam_deck.py --pdf .../eigo_listening.pdf --subject 英語 \
        --audio .../eigo_listening_audio.mp3

Needs `pip install pypdfium2 pdfminer.six` (bench only; the server itself never
reads a PDF). The exam material is copyrighted: keep it, and these reports, out
of the repository.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def render_pages(pdf: Path, pages: range, scale: float) -> list[tuple[bytes, str]]:
    """(PNG bytes, page text) per page, in reading order.

    The image is what the model looks at and the text is what the server
    segments into questions, which is the same split the relay produces: a
    photo plus the phone's OCR of it.
    """
    import pypdfium2 as pdfium
    from pdfminer.high_level import extract_text
    from pdfminer.layout import LAParams

    logging.disable(logging.WARNING)  # the DNC PDFs carry a no-extract flag
    doc = pdfium.PdfDocument(str(pdf))
    out: list[tuple[bytes, str]] = []
    for index in pages:
        if index >= len(doc):
            break
        buffer = io.BytesIO()
        doc[index].render(scale=scale).to_pil().save(buffer, format="PNG")
        # detect_vertical: 国語 and 古文 are set vertically, and without it
        # pdfminer returns one character per line, which segments into nothing.
        text = extract_text(
            str(pdf), page_numbers=[index], laparams=LAParams(detect_vertical=True)
        ) or ""
        out.append((buffer.getvalue(), text.strip()))
    return out


def mark_daimon(
    pages: list[tuple[bytes, str]], spec: str, offset: int
) -> list[tuple[bytes, str]]:
    """Prepend a 第N問 line to the pages the operator says start a 大問.

    Needed only for this bench. The 東大 PDFs draw their numbers as unmapped
    glyphs -- 第一問 comes out of text extraction as `第(cid:2)問` -- and the
    国語/地歴 booklets carry no extractable marker at all, so the boundary
    cannot come from the text. On the real path the phone OCRs the printed
    page and reads the heading normally; this option does not paper over that,
    it stands in for a reading this PDF cannot give.
    """
    starts = [int(p) - 1 for p in spec.replace(" ", "").split(",") if p]
    marked = []
    for i, (png, text) in enumerate(pages):
        page_index = i + offset
        if page_index in starts:
            text = f"第{starts.index(page_index) + 1}問" + chr(10) + text
        marked.append((png, text))
    return marked


def parse_pages(spec: str | None) -> range:
    """--pages 1-8 (1-based, inclusive) -> the 0-based range to render."""
    if not spec:
        return range(0, 10_000)
    first, _, last = spec.partition("-")
    start = int(first) - 1
    return range(start, int(last) if last else start + 1)


def build_client(data_dir: Path, solver: str):
    """A server bound to its own data directory, so runs cannot collide."""
    import importlib

    os.environ["ROKID_DATA_DIR"] = str(data_dir)
    os.environ["ROKID_SOLVER"] = solver
    from fastapi.testclient import TestClient

    import app.config as config

    importlib.reload(config)
    import app.db as db

    importlib.reload(db)
    import app.main as main

    importlib.reload(main)
    main.ensure_dirs()
    main.db.init_db()
    return TestClient(main.app)


def run(args) -> int:
    pdf = Path(args.pdf)
    report_path = Path(args.out or (pdf.parent.parent / "reports" / f"{pdf.stem}.json"))
    if report_path.exists() and not args.force:
        print(f"skip  {report_path} already exists (--force to redo)")
        return 0
    report_path.parent.mkdir(parents=True, exist_ok=True)

    pages = render_pages(pdf, parse_pages(args.pages), args.scale)
    if args.daimon:
        pages = mark_daimon(pages, args.daimon, parse_pages(args.pages).start)
    if not pages:
        print(f"FAIL  no pages rendered from {pdf}")
        return 1
    print(f"ok    pages          {len(pages)} rendered, "
          f"{sum(len(t) for _, t in pages)} chars of text")

    client = build_client(Path(args.data_dir), args.solver)
    doc_id = client.post("/v1/documents", json={"title": pdf.stem}).json()["document_id"]
    for index, (png, text) in enumerate(pages):
        r = client.post(
            f"/v1/documents/{doc_id}/pages",
            data={"page_index": index, "ocr_text": text},
            files={"image": (f"p{index:02d}.png", png, "image/png")},
        )
        if r.status_code != 201:
            print(f"FAIL  page {index}: {r.status_code} {r.text[:200]}")
            return 1
    r = client.post(f"/v1/documents/{doc_id}/finalize")
    if r.status_code != 200:
        print(f"FAIL  finalize: {r.status_code} {r.text[:200]}")
        return 1

    listening = bool(args.audio)
    r = client.post(
        "/v1/exam-sessions",
        json={
            "mode": "study",
            "document_id": doc_id,
            "exam_type": "listening" if listening else "written",
            "answer_format": "mark",
        },
    )
    session_id = r.json()["session_id"]
    if listening:
        # The recording travels with the pages: a transcript flattens speaker
        # turns and the numbers the questions turn on.
        r = client.post(
            f"/v1/exam-sessions/{session_id}/audio",
            files={"audio": (Path(args.audio).name, Path(args.audio).read_bytes(), "audio/mpeg")},
        )
        if r.status_code != 200:
            print(f"FAIL  audio: {r.status_code} {r.text[:200]}")
            return 1
        print(f"ok    audio          {Path(args.audio).name} attached to the session")

    print(f"..    solving        {args.solver} (this is where the generations are spent)")
    started = time.monotonic()
    r = client.post(f"/v1/exam-sessions/{session_id}/finalize-reading")
    elapsed = time.monotonic() - started
    if r.status_code != 200:
        print(f"FAIL  finalize-reading: {r.status_code} {r.text[:300]}")
        return 1

    bundle = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle")
    if bundle.status_code != 200:
        print(f"FAIL  answer-bundle: {bundle.status_code} {bundle.text[:200]}")
        return 1
    body = bundle.json()
    items = body["items"]
    ready = [i for i in items if i["status"] == "ready"]
    per_question = elapsed / len(items) if items else 0.0
    print(f"ok    answers        {len(ready)}/{len(items)} ready in {elapsed:.1f}s "
          f"({per_question:.1f}s per question)")
    if per_question > 40 and args.solver != "local":
        print("WARN  per-question time is in the range that preceded the 2026-09-14 "
              "rate limit (7-13s clean). Stop rather than starting the next subject.")
    for item in items[:5]:
        print(f"      {item['question_label']:<10} {item['answer'] or item['issue']}")

    report = {
        "pdf": str(pdf),
        "subject": args.subject,
        "solver": args.solver,
        "pages": len(pages),
        "audio": args.audio,
        "elapsed_s": round(elapsed, 1),
        "seconds_per_question": round(per_question, 1),
        "bundle": body,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ok    report         {report_path}")
    return 0 if ready else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--subject", default="")
    parser.add_argument("--audio", default=None, help="listening recording to send too")
    parser.add_argument("--pages", default=None, help="1-based inclusive, e.g. 1-8")
    parser.add_argument(
        "--daimon",
        default=None,
        help="1-based pages where a 大問 starts, e.g. 1,7,13 (for PDFs whose "
             "printed numbers are unmapped glyphs; the real path reads them via OCR)",
    )
    parser.add_argument("--solver", default="chatgpt-web")
    parser.add_argument("--scale", type=float, default=2.0, help="render scale")
    parser.add_argument("--out", default=None)
    parser.add_argument("--data-dir", default="C:/rokid-exam-materials/rundata")
    parser.add_argument("--force", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
