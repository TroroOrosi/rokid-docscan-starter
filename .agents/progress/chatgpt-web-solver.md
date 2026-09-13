# Subscription-only GPT route (`ROKID_SOLVER=chatgpt-web`)

Updated 2026-09-14. Branch `agent/group-scoped-solver-context`. The route is
committed as `cd567f4` (the solver) and `e231b76` (the live-run fixes below).

## Objective

Answer exam pages through the operator's own signed-in ChatGPT **web** session
instead of a local model or a paid API. The capture path is unchanged:

```text
Rokid Glasses -> Hi Rokid -> Android relay (ML Kit JA OCR) -> FastAPI
  -> Chrome (CDP) -> chatgpt.com -> HUD
```

**Non-goals / settled decisions.** Do not re-argue these:

- **No API key.** The user chose the web UI over `ROKID_SOLVER=openai` twice,
  after the OpenAI-API route was shown to be config-only and working
  (`name: openai, ready: True, model: gpt-4o` once `OPENAI_BASE_URL` is
  cleared; that variable points at the abandoned local model on this machine).
- **No manual phone operation.** A `?q=`-prefilled deep link or hand-pasting is
  not acceptable; the session must run without per-question hand work.
- **Automating the ChatGPT web UI breaks OpenAI's terms of use** and risks the
  account. This was raised three times and reaffirmed each time. It is the
  user's decision. Do not re-litigate it; do state it in user-facing docs.
- Do not build a browser connection pool. See the measurement below.

## Verified state

All of the following were run, not inferred.

### Suite

```bash
py -3.12 -m pytest -q     # 510 passed
py -3.12 -m ruff check .  # All checks passed
```

`python -m pytest` is **not** usable on this machine: the default `python` is
3.14 with no pytest. Use `py -3.12`.

### Live route, signed in (Chrome/152.0.7977.83, 2026-09-13)

```text
py -3.12 -m app.solvers.chatgpt_web "第2問 角 x の大きさを求めよ。" page01.png page02.png
ok    browser        Chrome/152.0.7977.83
ok    images         2 attached
ok    status         ready
ok    answer         '70度'        # smoke exit 0
```

Per-question, measured through the real `ChatGptWebSolver.solve`:

| case | time | result |
|---|---|---|
| text only | 7.58s | `x=2` |
| one image | 8.98s | `70°`, `image_attached=True` |
| two pages | 11.45s | `70度`, `image_attached=True` |

Browser attach is **0.61s** total (playwright start 0.23 / CDP 0.03 / new_page
0.06 / goto 0.28). It is not the bottleneck, which is why there is no
connection pool: reusing it would need a dedicated thread (Playwright's sync
API is bound to its creating thread, FastAPI runs sync endpoints in a
threadpool) to save 0.61s against 8-11s of generation.

### Multi-page proof

Two pages built so **neither alone suffices**: `page01` carries only the
conditions (a=50°, b=60°), `page02` only the figure (labels a, b, x), and the
OCR body text `第2問 角 x の大きさを求めよ。` carries no numbers.

```text
1 page only (p02 figure)   status=needs_input  answer=''
    missing: 角a、角bの大きさ（またはそれらを決定できる条件）が不足しています。
2 pages (p01+p02)          status=ready        answer='70度'
```

This is the evidence that the pre-fix behaviour could not answer a 大問 that
spans pages, and that the answer-only contract refuses to guess.

### Confirmed selectors (signed-in DOM only)

| purpose | value | observation |
|---|---|---|
| composer | `#prompt-textarea` | count=1; mounts ~1.75s after `goto` |
| file input | `input[data-testid="upload-photos-input"]` | `accept="image/*"`, `multiple` |
| attachment | `form img` | 0 -> 1 per uploaded page |
| reply | `[data-message-author-role="assistant"]` | read back fine |
| streaming | `[data-testid="stop-button"]` | present only while streaming |

### Prompt length (2026-09-13)

`composer.fill()` carries a long 大問 intact. A sentinel placed at the very END
of the body was returned for every rung, so nothing was truncated:

| body chars | secs | sentinel |
|---|---|---|
| 1,115 | 7.4 | yes |
| 4,265 | 7.8 | yes |
| 8,465 | 8.5 | yes |
| 17,033 | 10.4 | yes |
| 34,205 | 23.9 | yes |

## Defects found and fixed (each cost a live run to see)

1. **`input[type="file"]` matched FIVE inputs** (`upload-files`,
   `upload-photos`, `upload-media`, `upload-camera`, `upload-media-files`) and
   Playwright rejects an ambiguous locator: `strict mode violation`. Every
   image upload failed. The stub tests passed throughout.
2. **`form img` matched 1 element on an empty composer** in the signed-out
   shell, so any non-zero check reported every upload as confirmed. Fixed by
   requiring the count to **rise by `len(images)`**.
3. **A signed-out chatgpt.com serves a `lightweight-shell`** placeholder whose
   DOM has no composer, no `contenteditable`, and one `data-testid`
   (`desktop-app-shell`). The composer is now waited for, and the error names
   sign-in as the likely cause.
4. **Only the 大問's starting page image was sent.** `app/main.py` stored
   `primary_image_path` while `structure_json` already held every
   `page_indexes`. Fixed via `_page_image_paths()` + `Question.image_paths`.
5. **Reply polling cost a fixed 3s** (`1.0s x 3`). Now `0.25s x 4`.
6. **The wait ended on a "思考中" placeholder** on 4 of 5 long prompts. The stop
   button is present for the WHOLE generation, thinking phase included, and the
   placeholder holds still long enough for text-stability to confirm it. The
   assistant turn then goes briefly EMPTY before the real text arrives. Nothing
   visible while the stop button exists may end the wait; stability is now only
   the fallback for when that selector goes missing. **Do not "optimise" this
   back** — the earlier 7.89s-vs-8.92s measurement was taken on a short answer
   with no thinking phase and does not generalise.
7. **No retry.** Over 16 consecutive solves, one upload never confirmed inside
   60s and one composer never became clickable inside 30s. `ATTEMPTS`/
   `RETRY_BACKOFF_S` now retry in a fresh chat, and an unconfirmed upload is
   itself retryable because sending without the figure does not raise.
8. **The knobs were bound as default arguments at import**, so `ROKID_CHATGPT_*`
   could not retune a running call. Resolved per call now.
9. **The upload wait checked its deadline before looking**, reporting an
   already-landed upload as unconfirmed on a small budget.

## Changed paths

```text
app/solvers/chatgpt_web.py       NEW  solver, client, ask_page, attach_images, _smoke
tests/test_chatgpt_web_solver.py NEW  27 stub-page tests, no network
tests/test_chatgpt_web_live.py   NEW  opt-in live deck check, skips without a browser
app/solvers/base.py                   Question.image_paths
app/solvers/llm_adapter.py            _read_images, overridable _complete, paste_prompt
app/solvers/registry.py               registers chatgpt-web
app/main.py                           _page_image_paths, GET .../paste-prompt
tests/test_review_flow.py             大問 page-span reaches the solver
tests/test_document_exam_api.py       paste-prompt endpoint
app/config.py README.md requirements.txt app/version.py tests/test_versioning.py
```

Versions: `APP 0.24.0`, `API 1.17.0`, `SOLVER_API 1.5.0`.

## Operating requirements

- **A dedicated Chrome profile is mandatory.** Passing
  `--remote-debugging-port` to an already-running Chrome only opens a tab in it
  and never opens the port (it prints `既存のブラウザ セッションで開いています`
  and exits). Launch detached, or the browser dies with the shell job:

  ```bash
  powershell -NoProfile -Command "Start-Process -FilePath 'C:\Program Files\Google\Chrome\Application\chrome.exe' -ArgumentList '--remote-debugging-port=9222','--user-data-dir=C:/chrome-rokid-profile','--no-first-run','--no-default-browser-check','https://chatgpt.com/'"
  ```

  The profile path must use forward slashes; Git Bash mangles the backslash
  form and Chrome silently falls back to the running instance.
- Sign in once in that profile. The login itself is the user's to perform.
- `pip install playwright` only. `playwright install` is **not** needed; the
  solver attaches to the real Chrome.

## Rate limiting (2026-09-14) — read before any live run

The account was rate-limited and the user stopped the work. The cause was the
verification method, not the solver: whole-sweep runs over 16 subjects, re-run
after every failure, plus separate probes — well over a hundred generations in
an afternoon. Per-question time had degraded 7-13s -> 43s -> 48s -> 130s before
the block, and that slowdown was the signal to stop.

Budget rules are in [subject-separation-harness.md](subject-separation-harness.md).
One or two questions per change. Never re-run a sweep to chase one failure.
The 27 stub tests are offline and cover everything that does not strictly need
the real page.

Also fixed on the way in: the route used to `page.goto(CHAT_URL)` once per
question and again per retry. It now claims one tab and starts each chat by
clicking `create-new-chat-button`, so a question costs no page load at all.

## Next steps, in order

0. **Wait for the rate limit to clear.** Do not open a live run before that.
1. **Send one real 共通テスト subject through the web route end to end.** Not
   yet attempted; every live run so far used synthetic single-problem pages.
2. **Confirm image/text separation holds for every subject.** The current proof
   covers one 数学-shaped figure problem. 国語 (vertical text, long passages),
   英語 (long reading + charts), 理科/社会 (graphs, tables, maps) each stress a
   different part: the OCR body, the attachment count, and the prompt length.
   Watch for a page count that exceeds what one message accepts.
3. Check the token/length ceiling of a 大問's OCR text in the composer; `fill`
   places it in one step but nothing currently bounds its size.
4. Not started: the real-device pass through the glasses. `docs/
   windows-android-real-device-setup.md` holds the physical checklist, and an
   Android build proves compilation only.

## Open risks

- Every selector belongs to OpenAI and can change without notice. Each is
  env-overridable (`ROKID_CHATGPT_*`); `py -3.12 -m app.solvers.chatgpt_web` is
  the only check that catches a break, and it needs a signed-in browser.
- `extras["image_attached"]` is the only record of whether the figures reached
  the model. A wrong diagram answer should be diagnosed from it first.
- The API adapters still send a single image; only `chatgpt-web` sends the
  whole page span.
