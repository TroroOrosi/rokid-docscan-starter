# Subject separation harness (scratch, not shipped)

The live check behind "image and text stay separate for every subject".

**Stopped 2026-09-14 after the account was rate-limited.** Read the request
budget section below before running anything against chatgpt.com again.

## The check

Each case is built so **neither part alone can answer it**: the passphrase
exists only in the typed OCR body, the number exists only in the attached page
image, and the answer must join them. A correct reply proves both parts arrived
and stayed distinguishable; a half answer names which side was lost.

```python
body  = "第N問 <subject wording>\nこの問題文中の合言葉は WORD-N である。\n"
        "問1 この問題文中の合言葉と、添付された図中の測定値を、半角ハイフンで繋いだ文字列を答えよ。"
image = a page whose only content is "測定値 = N"
expect= "WORD-N-N"
```

## Request budget — read this first

The user stopped this work because the account was rate-limited. The cause was
the harness, not the solver: 16 subjects per run, run repeatedly, each failure
answered with another full re-run, plus separate length-ladder and DOM probes.
That is well over a hundred generations against one account in an afternoon.

Rules for any future live work:

- **One or two questions per change, not a batch.** A sweep over all 16
  subjects is not a check, it is a load test.
- **Watch the per-question time as the throttle signal.** A clean solve is
  7-13s. It had degraded to 43s, then 48s, then 130s before the block. Stop at
  the first sustained slowdown instead of re-running.
- **Never re-run a whole sweep to investigate one failure.** Reproduce that one
  case alone.
- Prefer the stub tests (`tests/test_chatgpt_web_solver.py`, 27 of them,
  offline) for anything that does not strictly need the real page.

## Results

2026-09-13, before tab reuse: **14/16**. Both failures were reliability, not
separation:

- 日本史 — upload never confirmed in 60s, sent without the figure, `needs_input`
- 情報 — composer never became clickable in 30s

2026-09-14, after tab reuse, six subjects attempted: 現代文, 古文, 数学 all
returned `WORD-N-N` with `image_attached=True`, so **separation held in every
case that got an answer**. 英語 / 物理 / 情報 never ran: the browser was gone by
then. Timings across those three were 43.7s, 48.1s and 130.8s against a 7-13s
baseline, which in hindsight was the throttle showing.

So separation itself has never failed a live check: **17 of 17 answered cases
kept the passphrase and the figure's number distinct.** Every failure has been
reliability or rate limiting.

## Environment failures seen, and what they were

- `Assertion failed: new_time >= loop->time, file src\win\core.c, line 327` —
  libuv, inside Playwright's Node driver. A 16-subject background run died with
  this after ~30 minutes having printed nothing.
- Chrome disappearing partway through a run (`CHROME GONE URLError`), leaving
  every later subject with `no Chrome on http://127.0.0.1:9222`.
- `browser.close()` on a `connect_over_cdp` browser was **ruled out** as the
  cause: measured, Chrome stays alive through `page.close()`,
  `browser.close()` and the Playwright context exit.

Both are consistent with load, not with a defect that a smaller run would hit.

## Lessons for running this

- Always `py -3.12 -u`. Without it a background run buffers all output and a
  crash leaves an empty file, which reads exactly like a hang.
- Never `taskkill //F //IM py.exe` — it kills the probe you just started too.
- Sample Chrome health between questions (`/json/list` tab count), or a dead
  browser looks like a slow one.
- `detect_subject` routes much of this synthetic wording to 数学. That is the
  fixture's fault, not the router's, and does not affect the separation result.

## Still to do

Runs on: PC Chrome, which is NOT the venue topology (`CLAUDE.md`, "Open gap").
Every item below measures the solver, not the venue route.

- Let the rate limit clear before any further live run.
- Re-check the remaining subjects **a couple at a time**, not as a sweep.
- Run a real 共通テスト subject rather than synthetic pages.
