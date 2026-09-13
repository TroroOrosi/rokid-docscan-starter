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

Versions: `APP 0.25.0`, `API 1.18.0`, `SOLVER_API 1.5.0`.

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


## 2026-09-14: the generations this route no longer spends

The account was rate-limited by the harness (see
[subject-separation-harness.md](subject-separation-harness.md)), but the solver
was making it worse in three ways. All three are now closed, with stub tests
(`tests/test_chatgpt_web_solver.py`, 32 of them, offline):

1. **The retry for an unconfirmed upload happened AFTER the question was
   sent.** It attached, asked, threw the answer away and asked again in a new
   chat. One moved thumbnail selector therefore cost *three generations per
   question*. `_ask_with_retries` now attaches, decides, and only then sends:
   `start_new_chat` -> `attach_images` -> (retry here, free) -> `send_and_read`.
   Pinned by `test_an_unconfirmed_upload_costs_no_generation`.
2. **A usage-limit reply was retried like any other bad answer.** ChatGPT
   refuses a throttled account in the message body, not with an exception, so
   the loop opened another chat and asked again. `ChatGptWebRateLimit` (a
   `ChatGptWebError`, so `solve_with_fallback` still degrades) ends the
   question instead. Markers: `ROKID_CHATGPT_RATE_LIMIT_MARKERS`.
3. **Nothing acted on the documented throttle signal.** Two generations in a
   row over `ROKID_CHATGPT_SLOW_S` (40s; measured 7-13s clean, degraded to
   43/48/130s before the block) now refuse the next send
   (`ROKID_CHATGPT_SLOW_STREAK=0` disables). The streak is process state, so a
   sweep script stops itself rather than relying on the operator watching.

`ask_page` still exists with the same signature and behaviour; it is now
`wait_for_composer` + `attach_images` + `send_and_read` composed.

### Sending the 大問 as one PDF (opt-in, UNVERIFIED)

`ROKID_CHATGPT_BUNDLE_PDF=1` uploads one PDF of every page through
`input[data-testid="upload-files-input"]` instead of one image per page through
the photo input (which is `accept="image/*"` and would reject a PDF). Built
during the rate limit, so **no live run has shown whether a figure survives the
PDF route**; the image-per-page route is the measured one. Verify with a single
figure-only question before using it. `app/page_pdf.py` holds the conversion.

### The phone path gained its missing half

`GET /v1/exam-sessions/{id}/pages.pdf` returns the whole captured document as
one PDF, and `paste-prompt` now carries `pages_pdf_url`. The hand-paste route
was rejected as the *primary* path and still is; this is for running a session
without the PC Chrome at all. Attaching a dozen photos by hand is the step that
does not survive a real session, so the material is one file. `API 1.18.0`,
`APP 0.25.0`.


## 2026-09-14: the deck bench, and what one full sweep would actually cost

`scripts/run_exam_deck.py` runs ONE subject end to end from a PDF: each page is
rendered to a PNG (pypdfium2) as a photographed page would arrive, its text is
extracted (pdfminer.six, `detect_vertical=True`) as the phone's ML Kit OCR
would provide it, and it then goes through the ordinary endpoints, ending at
the `answer-bundle` the glasses read. `--solver local` exercises everything
except the model, which is how all of the numbers below were measured without
spending a single generation.

Material lives OUTSIDE the repository in `C:/rokid-exam-materials/`
(共通テスト 2026 本試験 from dnc.ac.jp, 東大 令和8 前期 from u-tokyo.ac.jp,
plus the official 正解 and the listening MP3). It is copyrighted: do not commit
it, and do not commit the run reports either.

### Two segmentation defects the real material exposed

1. **An exam booklet prints a 第N問 side tab on every page of that 大問.** Each
   tab started a new problem, so 数学Ⅰ・Ａ became **26 problems over 26 pages
   instead of 4** -- 26 solver calls, each seeing only its own page.
   `_is_continuation` now folds a repeated 大問 number into the open problem.
   A repeated 小問 number (問1 under two 大問) still becomes 問1(2).
2. **大問 numbered in kanji (第一問) were not matched at all**, which is how
   東大 numbers every paper. `_Q_PATTERNS` now accepts kanji numerals and
   normalizes them to Arabic, so 第一問 and 第1問 are one problem, not two.

### Measured question counts (offline, `--solver local`)

25 papers, 513 questions total. Per subject, the ones that matter:

| subject | pages | questions |
|---|---|---|
| 情報Ⅰ | 34 | 49 |
| 英語リーディング | 31 | 38 |
| 歴史総合，日本史探究 | 35 | 38 |
| 公共，政治・経済 | 39 | 36 |
| 英語リスニング | 22 | 35 |
| 国語 | 47 | 32 |
| 数学Ⅰ・Ａ | 26 | 4 |
| 東大 国語（文科） | 26 | 4 |

**A full 共通テスト + 東大 sweep is therefore ~513 generations.** What
rate-limited the account on 2026-09-14 was "well over a hundred in an
afternoon". This run is five times that, so it cannot be done in one sitting at
one generation per 小問.

### Bench limitations that are NOT production limitations

- The 東大 PDFs draw their numbers as unmapped glyphs: 第一問 extracts as
  `第(cid:2)問`, and the 国語/地歴 booklets split 第一問 across lines in vertical
  mode. `--daimon 4,12,16,20` lets the operator state where each 大問 starts.
  On the real path the phone OCRs the printed heading and reads it normally.
- 共通テスト PDFs carry a no-extract flag. It is honoured for anything that
  leaves this machine; the text is used only to stand in for OCR.


## 2026-09-14 (evening): the live run that failed, and the premises behind it

### Purpose this route serves (re-read from the authoritative documents)

`docs/README.md` sets the authority order; `docs/real-device-operation.md` is
the current runbook. In production the operator wears the glasses and **does
not touch the phone**: glasses capture (`takePhoto(1920, 1080, 80)`) -> Hi
Rokid -> relay (ML Kit JA OCR) -> server -> HUD, which is black, green and **at
most three lines**. The only output that matters is *the string the operator
writes on the answer sheet*. The ChatGPT web route is a stand-in for an API
key, nothing more. Anything that does not serve that sentence is waste.

### What was run, and what it produced

One live run, 物理基礎 (14 pages, 14 questions), `ROKID_CHATGPT_CHAT_SCOPE=subject`:

```text
ok    answers        3/14 ready in 326.0s (23.3s per question)
      問1   ④: ρ(1−α)Vg
      問2   B: ②（ア＝比例、イ＝反比例、ウ＝Ω・m）
      問3   A: 画像上の正答は④（エ＝崩壊、オ＝原子核、カ＝人体）
```

The operator watching the browser saw **five chats**, the same page images
pasted into each, and answers carrying explanations. Every one of those is a
defect, and every one was findable offline before spending a generation.

### Root causes, each verified against the artifact

1. **`complete()` never passed `chat_key` or `audio` to `_ask_with_retries`.**
   An earlier edit to that call was applied with `str.replace` and **no
   assertion**, so it silently did nothing. Chat scoping therefore never ran at
   all: every question opened a new chat and re-uploaded its pages. Any patch
   to this repository must assert that its anchor matched.
2. **The chat key was derived from `question.subject`.** That field is a
   per-row heuristic (`detect_subject`), not the paper's 科目. Measured in the
   run database: one 物理基礎 paper produced rows labelled
   現代文 / 物理 / 化学 / 数学 / 地学. Even with (1) fixed, that would have
   scattered the paper across chats. The key now comes from the server as
   `session:{id}` -- one session is one paper.
3. **`answer_only` was never set on any solve path.** `grep -n answer_only
   app/main.py` returned exactly one hit: line 1908, the paste-prompt endpoint.
   The deck solve used the tutor contract, whose system prompt says *for
   multiple choice use the label form "B: text"* -- which is precisely the
   "A: ..." prose that came back. The progress record had claimed the server
   uses `Question.answer_only`; the code never did.
4. **The mark-format hint asked for reasoning.** `_ANSWER_FORMAT_HINT["mark"]`
   read 「解答はマーク式（選択肢の記号）で選び、**根拠を簡潔に示してください**」,
   which contradicts the answer-sheet contract from the other direction.
5. **The OCR body was retyped into every message.** With the whole booklet
   attachable as one PDF, that text is redundant, is the longest part of each
   request, and was observed arriving truncated.
6. **The HUD has no per-line character limit.** `app/glasses_view.py:62`:
   "No max_chars_per_line specified". The measured answer rendered as one
   32-character line on a 480x398 px display. Not fixed yet.

### What changed in response (all offline-verified)

- `Question.chat_key` (server-supplied), `document_image_paths`, `page_numbers`.
- The web route attaches the **whole booklet once per chat as a single PDF**
  and sends only a locator:

  ```text
  添付の問題冊子PDFを見て、次の設問に解答してください。
  設問: 問3（P05-P07）
  解答用紙に書く内容だけを出力してください。説明・理由・見出し・前置きは含めません。
  ```

- The deck solve path sets `answer_only=True`; a row whose solve raises is left
  unsolved rather than failing the whole `finalize-reading`.
- `FILE_UPLOAD_SEL` corrected to `input#upload-files`, measured on the live DOM
  (the five file inputs are upload-files, upload-photos-input, upload-media-
  input, upload-camera, upload-media-files; only the first accepts a PDF or
  audio).

### NOT verified, and not to be claimed

- **No live run of the new shape.** The operator stopped live runs. Whether
  ChatGPT reads a figure out of the bundled PDF as well as out of a page image
  is unmeasured.
- The bench renders pages at `--scale 2` PNG; the device captures
  `takePhoto(1920, 1080, 80)` JPEG with measured 16% contrast
  (`docs/capture-timing-findings.md`). The stand-in is kinder than reality.
- Attachment ceilings are third-party figures: 10-20 files per message,
  80 files per 3 hours, ~100 images per conversation. Not measured here.
- 東大 英語 is not published by the university; 世界史第2問 and 生物第3問 are
  partially withheld.

### Resume here

1. One live question, not a subject: confirm the PDF-once + locator shape
   returns an answer-sheet-only string and that the browser shows ONE chat.
2. Then one subject (物理基礎, 14 questions) and score against
   `C:/rokid-exam-materials/kyotsu/seikai/rika_kiso.pdf`.
3. Give the HUD a per-line limit before any accuracy claim: a 32-character
   answer line does not fit 480 px.
4. The bench writes every run into one `--data-dir`; give each paper its own,
   or a later query reads another run's rows (as happened while diagnosing).

Full sweep remains ~513 questions and is NOT scheduled.
