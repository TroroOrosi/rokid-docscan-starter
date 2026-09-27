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

--images DIR sends glassdoc's own originals instead: each photo as the glasses
upload it, with no OCR text. --background asks for the glassdoc finalize
(`?solve=background`) and polls answer-bundle as the reader does. --server
drives the phone's server over HTTP instead of an in-process one; the key comes
from --key or ROKID_API_KEY and is never printed.

    py -3.12 scripts/run_exam_deck.py --images data/device-setup/<run>/originals \
        --subject 物理基礎 --background --server http://<phone>:8000

Needs `pip install pypdfium2 pdfminer.six` for --pdf (bench only; the server
itself never reads a PDF). The exam material is copyrighted: keep it, and these
reports, out of the repository.
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


_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def load_images(directory: Path | str) -> list[tuple[bytes, str]]:
    """(image bytes, no text) per photo, in file-name order.

    This is what glassdoc uploads on the chatgpt-web route: the original still
    and no OCR. Its originals are named by capture time, so name order is page
    order.
    """
    files = sorted(p for p in Path(directory).iterdir() if p.suffix.lower() in _IMAGE_SUFFIXES)
    return [(p.read_bytes(), "") for p in files]


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


_UNSAFE = set('<>:"/|?*' + chr(92))


def source_name(source: Path | str) -> str:
    """A PDF's stem, or `<run>-<dir>` for a photo directory.

    glassdoc keeps a run's photos in <run>/originals: name the run, or every
    run would share one `originals` database and report.
    """
    source = Path(source)
    return f"{source.parent.name}-{source.name}" if source.is_dir() else source.stem


def deck_data_dir(root: Path | str, pdf: Path | str) -> Path:
    """This paper's OWN database directory, under the run root.

    Every paper used to be written into one --data-dir, so a query run after a
    later paper read the earlier paper's rows. That happened while diagnosing
    on 2026-09-14. One paper is one directory; the same PDF resolves to the
    same directory, so a re-run of that paper still resumes in place.
    """
    stem = source_name(pdf).strip()
    safe = "".join("_" if c in _UNSAFE or ord(c) < 32 else c for c in stem)
    return Path(root) / (safe or "unnamed")


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


def remote_client(server: str, key: str | None):
    """The phone's server, reached over HTTP the way the glasses reach it."""
    import httpx

    headers = {"Authorization": f"Bearer {key}"} if key else {}
    # One ceiling for every call. A synchronous finalize-reading over a long
    # paper can outlast it; --background returns at once and polls instead.
    return httpx.Client(base_url=server.rstrip("/"), headers=headers, timeout=600)


def wait_for_answers(client, session_id: int, timeout: float, interval: float = 5.0):
    """Poll answer-bundle as glassdoc does, until no 小問 is pending.

    The 409 served while the model is still listing the 小問 is polled
    through; any other non-200 is the result. Items can stay pending after
    the batch has stopped (the glasses would poll on), so the wait ends at
    ``timeout`` and returns the last response as it is.
    """
    deadline = time.monotonic() + timeout
    shown = None
    while True:
        r = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle")
        listing = r.status_code == 409 and "being made" in r.text
        if r.status_code != 200 and not listing:
            return r
        pending = 0
        if r.status_code == 200:
            statuses = [i["status"] for i in r.json()["items"]]
            pending = statuses.count("pending")
            if statuses != shown:
                shown = statuses
                print(f"..    answers        {statuses.count('ready')}/{len(statuses)} ready, "
                      f"{pending} pending")
            if not pending:
                return r
        if time.monotonic() >= deadline:
            print(f"WARN  stopped waiting after {timeout:.0f}s "
                  f"({'still listing' if listing else f'{pending} pending'})")
            return r
        time.sleep(interval)


def run(args) -> int:
    src = Path(args.pdf or args.images)
    name = source_name(src)
    report_path = Path(args.out or (src.parent.parent / "reports" / f"{name}.json"))
    if report_path.exists() and not args.force:
        print(f"skip  {report_path} already exists (--force to redo)")
        return 0
    report_path.parent.mkdir(parents=True, exist_ok=True)

    span = parse_pages(args.pages)
    if args.pdf:
        pages = render_pages(src, span, args.scale)
    else:
        pages = load_images(src)[span.start:span.stop]
    if args.daimon:
        pages = mark_daimon(pages, args.daimon, span.start)
    if not pages:
        print(f"FAIL  no pages read from {src}")
        return 1
    print(f"ok    pages          {len(pages)} read, "
          f"{sum(len(t) for _, t in pages)} chars of text")

    if args.server:
        print(f"ok    server         {args.server} (its own ROKID_SOLVER answers)")
        client = remote_client(args.server, args.key)
    else:
        data_dir = deck_data_dir(args.data_dir, src)
        print(f"ok    data dir       {data_dir}")
        client = build_client(data_dir, args.solver)
    doc_id = client.post("/v1/documents", json={"title": name}).json()["document_id"]
    for index, (image, text) in enumerate(pages):
        jpeg = image[:2] == b"\xff\xd8"
        fields = {"page_index": index, "image_rotation": args.rotation}
        if text:
            fields["ocr_text"] = text
        r = client.post(
            f"/v1/documents/{doc_id}/pages",
            data=fields,
            files={"image": (f"p{index:02d}.{'jpg' if jpeg else 'png'}", image,
                             "image/jpeg" if jpeg else "image/png")},
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

    solver = "the server's solver" if args.server else args.solver
    print(f"..    solving        {solver} (this is where the generations are spent)")
    started = time.monotonic()
    r = client.post(
        f"/v1/exam-sessions/{session_id}/finalize-reading",
        params={"solve": "background"} if args.background else None,
    )
    if r.status_code != 200:
        print(f"FAIL  finalize-reading: {r.status_code} {r.text[:300]}")
        return 1

    if args.background:
        bundle = wait_for_answers(client, session_id, args.timeout)
    else:
        bundle = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle")
    elapsed = time.monotonic() - started
    if bundle.status_code != 200:
        print(f"FAIL  answer-bundle: {bundle.status_code} {bundle.text[:200]}")
        return 1
    body = bundle.json()
    items = body["items"]
    ready = [i for i in items if i["status"] == "ready"]
    per_question = elapsed / len(items) if items else 0.0
    print(f"ok    answers        {len(ready)}/{len(items)} ready in {elapsed:.1f}s "
          f"({per_question:.1f}s per question)")
    if per_question > 40 and (args.server or args.solver != "local"):
        print("WARN  per-question time is in the range that preceded the 2026-09-14 "
              "rate limit (7-13s clean). Stop rather than starting the next subject.")
    for item in items[:5]:
        print(f"      {item['question_label']:<10} {item['answer'] or item['issue']}")

    report = {
        "source": str(src),
        "subject": args.subject,
        "solver": None if args.server else args.solver,
        "server": args.server,
        "background": args.background,
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
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--pdf")
    source.add_argument("--images", help="directory of glassdoc originals, sent in name order")
    parser.add_argument(
        "--rotation", type=int, choices=(0, 90, 180, 270), default=0,
        help="image_rotation sent with each page, as glassdoc does",
    )
    parser.add_argument(
        "--background", action="store_true",
        help="finalize-reading?solve=background, then poll answer-bundle",
    )
    parser.add_argument("--timeout", type=float, default=900, help="seconds to poll for")
    parser.add_argument("--server", default=None, help="e.g. http://<phone>:8000")
    parser.add_argument(
        "--key", default=os.environ.get("ROKID_API_KEY"),
        help="the server's API key (default: ROKID_API_KEY; keeps it out of shell history)",
    )
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
    parser.add_argument(
        "--data-dir",
        default="C:/rokid-exam-materials/rundata",
        help="run ROOT. Each paper gets its own subdirectory named after the "
             "PDF, so one paper's rows are never read back for another",
    )
    parser.add_argument("--force", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
