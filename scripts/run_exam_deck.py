#!/usr/bin/env python3
"""Run ONE exam subject through the whole server flow (PC bench).

Two routes:

- Without --server: an in-process FastAPI server, for comparing PC-side
  pieces (solver, PDF text extraction, --daimon, --audio, --scale). Each PDF
  page is rendered to a PNG with its pdfminer text attached, exactly as
  before.
- With --server: drives the PHONE's own server over HTTP, along the exact
  glassdoc route -- JPEG pages, no OCR text, `finalize-reading?solve=
  background`, then polling answer-bundle. A PDF is rendered into spreads
  (two pages per image, at glasses-photo density) because glassdoc never
  uploads a single page; --images sends glassdoc's own originals unchanged.
  The key comes from --key or ROKID_API_KEY and is never printed.

One subject per invocation, on purpose. A sweep over every subject in one run
is what rate-limited the account on 2026-09-14; see
.agents/progress/subject-separation-harness.md. Use --pages to run a single 大問
while checking a change, and keep --solver local (in-process route only) for
anything that does not need the real model.

    py -3.12 scripts/run_exam_deck.py --pdf C:/rokid-exam-materials/kyotsu/butsuri_kiso.pdf \
        --pages 1-4 --server http://<phone>:8000
    py -3.12 scripts/run_exam_deck.py --images data/device-setup/glassdoc-kokugo-20260927/originals \
        --server http://<phone>:8000

Needs `pip install pypdfium2 pdfminer.six` for --pdf (bench only; the server
itself never reads a PDF). The exam material is copyrighted: keep it, and
these reports, out of the repository.
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

# A glasses still of a B5 spread covers about this pixel density; PDF spreads
# are rendered to match it instead of the sharper (and unrealistic) --scale
# used for the in-process PC-comparison route.
PX_PER_MM = 5

# glassdoc's camera2 still is landscape 4032x3024 and it sends this rotation
# (DocScanGlassActivity.MEASURED_ROTATION_DEGREES). A PDF spread is already
# built upright, so it goes with rotation 0.
GLASSDOC_ROTATION = 270

# How often wait_for_answers polls answer-bundle. Tests set interval=0.
POLL_S = 5.0

# Per-call ceiling for a plain JSON round trip, well below the stall bound
# wait_for_answers uses across many such calls.
REQUEST_TIMEOUT_S = 30.0
# The one call that legitimately takes longer: a multi-megabyte spread sent
# over the phone's own Wi-Fi.
PAGE_UPLOAD_TIMEOUT_S = 600.0


def answer_ceiling_s() -> float:
    """The longest one chatgpt-web solve can legitimately take.

    ATTEMPTS preparation attempts (ChatGptWebClient._ask_locked), each up to
    READY_TIMEOUT_S + UPLOAD_TIMEOUT_S, plus their RETRY_BACKOFF_S back-offs
    (arithmetic series, sum 0..ATTEMPTS-1), plus one generation (TIMEOUT_S),
    plus one page load (cdp.DEFAULT_TIMEOUT_S). 375s with defaults.

    ponytail: this reads the PC's env, not the phone's; if the phone
    overrides ROKID_CHATGPT_TIMEOUT_S, /v1/settings would have to publish it
    for this bound to track that override.
    """
    from app.solvers.cdp import DEFAULT_TIMEOUT_S
    from app.solvers.chatgpt_web import (
        ATTEMPTS, READY_TIMEOUT_S, RETRY_BACKOFF_S, TIMEOUT_S, UPLOAD_TIMEOUT_S,
    )

    return (
        ATTEMPTS * (READY_TIMEOUT_S + UPLOAD_TIMEOUT_S)
        + RETRY_BACKOFF_S * ATTEMPTS * (ATTEMPTS - 1) / 2
        + TIMEOUT_S
        + DEFAULT_TIMEOUT_S
    )


def call(step: str, func, *args, **kwargs):
    """One server-route HTTP call: a dropped connection prints FAIL and stops
    the run instead of a bare traceback. Never prints the key -- only the
    exception's class name, never its text or the request.
    """
    import httpx

    try:
        return func(*args, **kwargs)
    except httpx.TransportError as error:
        print(f"FAIL  {step}: no response ({type(error).__name__})")
        return None


def render_pages(pdf: Path, pages: range, scale: float) -> list[tuple[bytes, str]]:
    """(PNG bytes, page text) per page, in reading order.

    The image is what the model looks at and the text is what the server
    segments into questions, which is the same split the relay produces: a
    photo plus the phone's OCR of it. In-process route only.
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


def pair_spreads(images: list) -> list:
    """Pair consecutive pages into one spread image, earlier page on the LEFT.

    White RGB canvas, width = sum of both widths, height = the taller one; an
    odd last page stands alone. Why left: 共通テスト 理科 booklets are 横書き
    and left-bound (the thumb tab prints on the later/right page).

    ponytail: a 縦書き booklet (国語) opens the other way and would need the
    pair mirrored; not built until a 国語 paper actually needs this route.
    """
    from PIL import Image

    out = []
    for i in range(0, len(images), 2):
        pair = images[i:i + 2]
        if len(pair) == 1:
            out.append(pair[0])
            continue
        left, right = pair
        canvas = Image.new(
            "RGB", (left.width + right.width, max(left.height, right.height)), "white")
        canvas.paste(left, (0, 0))
        canvas.paste(right, (left.width, 0))
        out.append(canvas)
    return out


def render_spreads(pdf: Path, span: range) -> list[tuple[bytes, str]]:
    """(JPEG bytes, "") per spread -- two consecutive pages side by side.

    Rendered at PX_PER_MM (5 px/mm; a B5 page, 515.9 x 728.5 pt, becomes about
    910 x 1285 px, the density a glasses still of a B5 spread covers) and
    paired by pair_spreads. No OCR text travels on this route: the server's
    own ROKID_SOLVER reads the images directly, as the glasses do.
    """
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf))
    scale = PX_PER_MM * 25.4 / 72
    pages = []
    for index in span:
        if index >= len(doc):  # clipped to the document length
            break
        pages.append(doc[index].render(scale=scale).to_pil().convert("RGB"))
    out = []
    for spread in pair_spreads(pages):
        buffer = io.BytesIO()
        spread.save(buffer, format="JPEG", quality=90)
        out.append((buffer.getvalue(), ""))
    return out


_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def load_images(directory: Path | str, span: range) -> list[tuple[bytes, str]]:
    """(image bytes, no text) per photo, in file-name order, for pages in span.

    This is what glassdoc uploads on the chatgpt-web route: the original
    still and no OCR. Its originals are named by capture time, so name order
    is page order. Only the files inside span are opened and validated, so a
    bad file the run never touches cannot fail it. camera2's still is
    landscape; a portrait file is not a glassdoc original, and sending it
    with image_rotation=270 (glassdoc's own value) would put the page
    sideways, so it is rejected instead of guessed.
    """
    from PIL import Image, UnidentifiedImageError

    files = sorted(p for p in Path(directory).iterdir() if p.suffix.lower() in _IMAGE_SUFFIXES)
    out: list[tuple[bytes, str]] = []
    for path in files[span.start:span.stop]:
        data = path.read_bytes()
        try:
            with Image.open(io.BytesIO(data)) as image:
                portrait = image.height > image.width
        except (OSError, UnidentifiedImageError) as error:
            raise ValueError(f"{path} is not a readable image ({error})") from error
        if portrait:
            raise ValueError(
                f"{path} is portrait; glassdoc originals are landscape (4032x3024)")
        out.append((data, ""))
    return out


def _load_photos(src: Path, span: range) -> list[tuple[bytes, str]] | None:
    """load_images, with the FAIL print run() gives every other bad-input path.

    None (already printed) on a bad file inside the span; run() must check
    for it and stop, same as any other FAIL.
    """
    try:
        return load_images(src, span)
    except ValueError as error:
        print(f"FAIL  {error}")
        return None


def mark_daimon(
    pages: list[tuple[bytes, str]], spec: str, offset: int
) -> list[tuple[bytes, str]]:
    """Prepend a 第N問 line to the pages the operator says start a 大問.

    Needed only for this bench. The 東大 PDFs draw their numbers as unmapped
    glyphs -- 第一問 comes out of text extraction as `第(cid:2)問` -- and the
    国語/地歴 booklets carry no extractable marker at all, so the boundary
    cannot come from the text. On the real path the phone OCRs the printed
    page and reads the heading normally; this option does not paper over that,
    it stands in for a reading this PDF cannot give. In-process route only.
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
    """This paper's OWN database directory, under the run root. In-process
    route only -- the server route never opens a database on this machine.

    Every paper used to be written into one --data-dir, so a query run after a
    later paper read the earlier paper's rows. That happened while diagnosing
    on 2026-09-14. One paper is one directory; the same PDF resolves to the
    same directory, so a re-run of that paper still resumes in place.
    """
    stem = source_name(pdf).strip()
    safe = "".join("_" if c in _UNSAFE or ord(c) < 32 else c for c in stem)
    return Path(root) / (safe or "unnamed")


def build_client(data_dir: Path, solver: str):
    """A server bound to its own data directory, so runs cannot collide.
    In-process route only."""
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
    """The phone's server, reached over HTTP the way the glasses reach it.

    No client-wide timeout: each call sets its own -- REQUEST_TIMEOUT_S for a
    plain JSON round trip, PAGE_UPLOAD_TIMEOUT_S for the one call that sends
    megabytes.
    """
    import httpx

    headers = {"Authorization": f"Bearer {key}"} if key else {}
    return httpx.Client(base_url=server.rstrip("/"), headers=headers)


def wait_for_answers(
    client, session_id: int, stall_s: float, *,
    interval: float = POLL_S, clock=time.monotonic, sleep=time.sleep,
):
    """Poll answer-bundle as glassdoc does, until stopped or nothing pending.

    Returns (last_good_response_or_None, reason_or_None). There is no overall
    ceiling: a listing 409 or a changing revision can run indefinitely. The
    wait ends only when the server has visibly stopped -- the revision hasn't
    moved for `stall_s`, or nothing has answered at all for `stall_s`.
    """
    import httpx

    since = clock()
    last_good = None
    last_revision = None
    listed = False
    while True:
        try:
            r = client.get(
                f"/v1/exam-sessions/{session_id}/answer-bundle", timeout=REQUEST_TIMEOUT_S)
        except httpx.TransportError as error:
            print(f"..    no response: {type(error).__name__}")
            if clock() - since > stall_s:
                return last_good, f"no response from the server for {stall_s:.0f}s"
            sleep(interval)
            continue

        if r.status_code == 409 and "being made" in r.text:
            # The model is listing the 小問. The server ends a listing itself
            # (the background batch always leaves _background_solves, success
            # or failure), so this adds no limit of its own.
            if not listed:
                print("..    listing        the model is listing the 小問")
                listed = True
            since = clock()
            sleep(interval)
            continue
        if r.status_code != 200:
            return r, None

        last_good = r
        body = r.json()
        items = body["items"]
        pending = sum(1 for item in items if item["status"] == "pending")
        if not pending:
            return r, None
        revision = body.get("revision")
        if revision != last_revision:
            last_revision = revision
            since = clock()
            ready = sum(1 for item in items if item["status"] == "ready")
            print(f"..    answers        {ready}/{len(items)} ready, "
                  f"{pending} pending (revision {revision})")
        if clock() - since > stall_s:
            return r, (f"revision {revision} unchanged for {stall_s:.0f}s with "
                       f"{pending} pending: the server's batch has stopped")
        sleep(interval)


_SERVER_INCOMPATIBLE = (
    ("daimon", "--daimon"),
    ("solver", "--solver"),
    ("scale", "--scale"),
    ("data_dir", "--data-dir"),
    ("audio", "--audio"),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--pdf")
    source.add_argument(
        "--images",
        help="directory of glassdoc originals, sent in name order (requires --server)",
    )
    parser.add_argument("--server", default=None, help="e.g. http://<phone>:8000")
    parser.add_argument(
        "--key", default=None,
        help="the server's API key (server route only; default ROKID_API_KEY, "
             "which keeps it out of shell history)",
    )
    parser.add_argument("--subject", default="")
    parser.add_argument(
        "--audio", default=None,
        help="listening recording to send too (in-process route only)",
    )
    parser.add_argument(
        "--pages", default=None,
        help="1-based inclusive, e.g. 1-8; with --server spreads pair from the first "
             "page of the span, so the span must start on a left-hand page",
    )
    parser.add_argument(
        "--daimon", default=None,
        help="1-based pages where a 大問 starts, e.g. 1,7,13 (in-process route only; "
             "for PDFs whose printed numbers are unmapped glyphs)",
    )
    parser.add_argument(
        "--solver", default=None, help="in-process route only (default chatgpt-web)")
    parser.add_argument(
        "--scale", type=float, default=None,
        help="render scale, in-process route only (default 2.0)")
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--data-dir", default=None,
        help="run ROOT, in-process route only (default C:/rokid-exam-materials/rundata). "
             "Each paper gets its own subdirectory named after the PDF, so one paper's "
             "rows are never read back for another",
    )
    parser.add_argument("--force", action="store_true")
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.images and not args.server:
        parser.error("--images requires --server: photos only go the glassdoc route")
    if args.key is not None and not args.server:
        parser.error("--key requires --server: the in-process route has no server API key")
    if args.server:
        for dest, flag in _SERVER_INCOMPATIBLE:
            if getattr(args, dest) is not None:
                parser.error(
                    f"{flag} is not compatible with --server: that route sends only "
                    "photos and the phone's own solver answers"
                )
    return args


def run(args) -> int:
    src = Path(args.pdf or args.images)
    name = source_name(src)
    if args.out:
        report_path = Path(args.out)
    else:
        suffix = f"-p{args.pages}" if args.pages else ""
        filename = f"{name}{suffix}-server.json" if args.server else f"{name}.json"
        report_path = src.parent.parent / "reports" / filename
    if report_path.exists() and not args.force:
        print(f"skip  {report_path} already exists (--force to redo)")
        return 0
    report_path.parent.mkdir(parents=True, exist_ok=True)

    span = parse_pages(args.pages)

    if args.server:
        key = args.key or os.environ.get("ROKID_API_KEY")
        client = remote_client(args.server, key)
        r = call("settings", client.get, "/v1/settings", timeout=REQUEST_TIMEOUT_S)
        if r is None:
            return 1
        if r.status_code != 200:
            print(f"FAIL  settings: {r.status_code} {r.text[:200]}")
            return 1
        settings = r.json()
        solver_info = settings["providers"]["solver"]
        solver_name = solver_info["name"]
        print(f"ok    settings       {args.server} app "
              f"{settings['versions']['app_version']} solver {solver_name} "
              f"(ready={solver_info['ready']})")

        pages = render_spreads(src, span) if args.pdf else _load_photos(src, span)
        if pages is None:
            return 1
        rotation = 0 if args.pdf else GLASSDOC_ROTATION
        if not pages:
            print(f"FAIL  no pages read from {src}")
            return 1
        print(f"ok    pages          {len(pages)} read, "
              f"{sum(len(t) for _, t in pages)} chars of text")
    else:
        # Read/render pages BEFORE touching the data directory: a bad --pdf
        # or --images path must leave no rundata/<stem> behind.
        if args.pdf:
            pages = render_pages(src, span, args.scale if args.scale is not None else 2.0)
        else:
            pages = _load_photos(src, span)
            if pages is None:
                return 1
        rotation = 0 if args.pdf else GLASSDOC_ROTATION
        if args.daimon:
            pages = mark_daimon(pages, args.daimon, span.start)
        if not pages:
            print(f"FAIL  no pages read from {src}")
            return 1
        print(f"ok    pages          {len(pages)} read, "
              f"{sum(len(t) for _, t in pages)} chars of text")

        data_dir = deck_data_dir(args.data_dir or "C:/rokid-exam-materials/rundata", src)
        print(f"ok    data dir       {data_dir}")
        solver_name = args.solver or "chatgpt-web"
        client = build_client(data_dir, solver_name)

    r = call("documents", client.post, "/v1/documents", json={"title": name},
              timeout=REQUEST_TIMEOUT_S)
    if r is None:
        return 1
    if r.status_code != 201:
        print(f"FAIL  documents: {r.status_code} {r.text[:200]}")
        return 1
    doc_id = r.json()["document_id"]
    for index, (image, text) in enumerate(pages):
        jpeg = image[:2] == b"\xff\xd8"
        fields = {"page_index": index, "image_rotation": rotation}
        if text:
            fields["ocr_text"] = text
        r = call(
            f"page {index}", client.post, f"/v1/documents/{doc_id}/pages",
            data=fields,
            files={"image": (f"p{index:02d}.{'jpg' if jpeg else 'png'}", image,
                             "image/jpeg" if jpeg else "image/png")},
            timeout=PAGE_UPLOAD_TIMEOUT_S,
        )
        if r is None:
            return 1
        if r.status_code != 201:
            print(f"FAIL  page {index}: {r.status_code} {r.text[:200]}")
            return 1
    r = call("finalize", client.post, f"/v1/documents/{doc_id}/finalize",
              timeout=REQUEST_TIMEOUT_S)
    if r is None:
        return 1
    if r.status_code != 200:
        print(f"FAIL  finalize: {r.status_code} {r.text[:200]}")
        return 1

    listening = bool(args.audio)
    r = call(
        "exam-sessions", client.post, "/v1/exam-sessions",
        json={
            "mode": "study",
            "document_id": doc_id,
            "exam_type": "listening" if listening else "written",
            "answer_format": "mark",
        },
        timeout=REQUEST_TIMEOUT_S,
    )
    if r is None:
        return 1
    if r.status_code not in (200, 201):
        print(f"FAIL  exam-sessions: {r.status_code} {r.text[:200]}")
        return 1
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

    print(f"..    solving        {solver_name} (this is where the generations are spent)")
    started = time.monotonic()
    reason = None
    if args.server:
        r = call(
            "finalize-reading", client.post, f"/v1/exam-sessions/{session_id}/finalize-reading",
            params={"solve": "background"}, timeout=REQUEST_TIMEOUT_S,
        )
        if r is None:
            return 1
        if r.status_code != 200:
            print(f"FAIL  finalize-reading: {r.status_code} {r.text[:300]}")
            return 1
        finalize_body = r.json()
        if finalize_body.get("solving") != "background":
            print(f"FAIL  the server did not start a background solve "
                  f"(status {finalize_body.get('status')}); is ROKID_SOLVER on the "
                  "server unset or local?")
            return 1
        bundle, reason = wait_for_answers(client, session_id, answer_ceiling_s(), interval=POLL_S)
    else:
        r = call(
            "finalize-reading", client.post,
            f"/v1/exam-sessions/{session_id}/finalize-reading", timeout=REQUEST_TIMEOUT_S,
        )
        if r is None:
            return 1
        if r.status_code != 200:
            print(f"FAIL  finalize-reading: {r.status_code} {r.text[:300]}")
            return 1
        bundle = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle")

    elapsed = time.monotonic() - started
    if reason:
        print(f"STOP  {reason}")
    if bundle is None or bundle.status_code != 200:
        status = bundle.status_code if bundle is not None else "no response"
        snippet = bundle.text[:200] if bundle is not None else ""
        print(f"FAIL  answer-bundle: {status} {snippet}")
        return 1
    body = bundle.json()
    items = body["items"]
    ready = [i for i in items if i["status"] == "ready"]
    per_question = elapsed / len(items) if items else 0.0
    print(f"ok    answers        {len(ready)}/{len(items)} ready in {elapsed:.1f}s "
          f"({per_question:.1f}s per question)")
    if reason is None and per_question > 40 and solver_name != "local":
        print("WARN  per-question time is in the range that preceded the 2026-09-14 "
              "rate limit (7-13s clean). Stop rather than starting the next subject.")
    for item in items[:5]:
        print(f"      {item['question_label']:<10} {item['answer'] or item['issue']}")

    report = {
        "source": str(src),
        "subject": args.subject,
        "solver": None if args.server else solver_name,
        "server": args.server,
        "server_solver": solver_name if args.server else None,
        "pages": len(pages),
        "audio": args.audio,
        "elapsed_s": round(elapsed, 1),
        "seconds_per_question": round(per_question, 1),
        "stopped": reason,
        "bundle": body,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ok    report         {report_path}")
    return 0 if ready and not reason else 2


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
