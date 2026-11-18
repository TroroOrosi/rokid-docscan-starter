#!/usr/bin/env python3
"""A stand-in for the Codex CLI: the server's Codex route, rehearsed without the model.

    ROKID_CODEX_BIN=/path/to/standin_codex.py    (made executable; app/solvers/codex_cli.py then runs nothing else)

It takes what ``codex login status`` and ``codex exec`` are given by app/solvers/codex_cli.py and writes replies of
the shape that route expects, from the names of the attached images alone. Nothing is read from a page, nothing is
sent anywhere, no allowance is spent:

- the request that asks where the pages lie (images named photoNNN): one region on every photo, its middle;
- the request that asks where the major problems begin (captureNNN): the first capture and the one halfway through;
- the route's own check (canary.jpg): the number of dark squares in it;
- a request for answers: one made-up question for each capture page it is asked about (those attached at full size,
  pageNNN...; of a part, the pages its note names), with that page's number as its printed answer number.

What a rehearsal with it shows: that the server's own work on a booklet (the gathering, the wait at the end, what
is prepared ahead, the cutting, the parts, the comparison, the answers' way to the glasses) runs on that machine
with that code. What it cannot show: anything the model does, how long it takes, or what a request costs.

STANDIN_CODEX_SECONDS makes every request for answers take that long (0), to stand for the model's time.
"""
import json
import os
import re
import sys
import time
from pathlib import Path


def main(args: list[str]) -> int:
    if args[:2] == ["login", "status"]:
        print("Logged in using ChatGPT (stand-in: nothing is sent)")
        return 0
    if args[:1] != ["exec"] or "-o" not in args:
        print("the stand-in knows `login status` and `exec ... -o <reply file> <prompt>` only", file=sys.stderr)
        return 2
    images = [args[index + 1] for index, value in enumerate(args[:-1]) if value == "-i"]
    reply, prompt = Path(args[args.index("-o") + 1]), args[-1]
    numbers = sorted({int(found[1]) for name in images for found in [re.search(r"(\d{3})", name)] if found})
    if images and all(name.startswith("photo") for name in images):
        data = {"images": [{"index": index, "regions": [
            {"left": 60, "top": 60, "right": 940, "bottom": 940, "vertical_text": False}]}
            for index in range(1, len(images) + 1)]}
    elif images and all(name.startswith("capture") for name in images):
        data = {"starts": sorted({numbers[0], numbers[len(numbers) // 2]}) if numbers else [], "shared": []}
    elif images == ["canary.jpg"]:
        from PIL import Image  # noqa: PLC0415 - the check alone needs a picture read

        with Image.open("canary.jpg") as picture:
            row = [picture.convert("L").getpixel((x, picture.height // 2)) < 128 for x in range(picture.width)]
        squares = sum(1 for x, dark in enumerate(row) if dark and not (x and row[x - 1]))
        reply.write_text(json.dumps({"squares": squares}) if "--output-schema" in args else str(squares), encoding="utf-8")
        print("tokens used\n0")
        return 0
    else:
        own = sorted({int(found[1]) for name in images for found in [re.match(r"page-?(\d{3})", name)] if found}) or numbers
        part = re.search(r"begin on capture pages (\d+) to (\d+) only", prompt)
        if part:
            own = [page for page in own if int(part[1]) <= page <= int(part[2])]
        time.sleep(float(os.environ.get("STANDIN_CODEX_SECONDS") or 0))
        data = {"questions": [
            {"group": "", "label": f"stand-in {page}", "answer_no": [page], "pages": [page], "status": "ready",
             "answer": "①", "missing_material": "", "diagrams": []} for page in own]}
    reply.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print("tokens used\n0")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
