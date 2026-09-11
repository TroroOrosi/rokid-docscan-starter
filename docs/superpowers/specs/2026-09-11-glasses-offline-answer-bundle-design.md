# Glasses offline answer bundle

Status: Implemented, unit-tested, green build (2026-09-11). **Not verified on
hardware in any respect** — no device was involved at any point. The
phone-hotspot topology has never been exercised end to end, `AnswerView`'s
readability on the glasses is unverified, reading with the hotspot off is
unverified, and the two-stage exit and re-wear recovery were not re-tested
after this branch changed the `KEYCODE_BACK` consumption decision.

## Problem

The operator needs to read every sub-question's written answer on the glasses
during a 150-minute exam. The venue has no Wi-Fi network. The phone has mobile
data; the glasses have none of their own.

The glasses already read answers: `DocScanController` reaches
`RelayState.REVIEW` and calls `GET /v1/exam-sessions/{id}/review` once per
screen, rendering into `HudView`. That path needs a server round trip for every
page turn, so it cannot work where the glasses have no route to the server.

`AnswerBundle`, `AnswerReader`, `AnswerStore` and `AnswerView` were built for
the offline case and are complete with unit tests, but nothing produces an
`AnswerBundle`: no server endpoint emits one, and `AnswerView.bind` is never
called. This design closes that gap.

## Topology

The phone runs its Wi-Fi hotspot; the glasses join it as an ordinary WPA2
client and reach the server through the phone's mobile data. No new
device-to-device protocol is introduced, and `DocScanApi` works unchanged.

Measured 2026-09-11 over adb, read-only:

- Glasses: Wi-Fi enabled, associated to a WPA2 2.4 GHz network at 150 Mbps.
- Phone F-51F: SoftAP supported and previously started as `F-51F_6031`;
  `SupportedChannelListIn24g[1..13]`, `MaximumSupportedClientNumber=10`,
  driver country JP; `tether_dun_required` is null; carrier NTT DOCOMO.

The CXR-L alternative was inspected and rejected for this purpose. The
1.1.1 AAR does expose an arbitrary byte channel on the phone side --
`sendCustomCmd(String, byte[])`, `sendCustomCmdStream(String, byte[], byte[])`
and `ICustomCmdCallback.onCustomCmdResult(String, byte[])` -- but no public
glasses-side receiver is known, so it would need a hardware spike and a new
protocol to deliver what plain HTTP already delivers.

**Unresolved dependency.** At the venue the server must be reachable over
mobile data. Deployment target, authentication and budget are FS-63 and are
undecided; no Firebase project exists. On the home LAN this design works today.
Do not record the venue topology as verified until a deployed server has been
reached from the phone's hotspot.

## Sub-question structure

`AnswerItem` requires a group and a question. The database has no group column;
`questions` carries `question_no`, `page_number`, `subject` and a
`structure_json` that holds only `{"page_indexes": [...], "deck": true}`.

The structure is recoverable from `question_no` because the segmenter already
emits group headings and sub-questions as separate deck rows in document order.
Measured 2026-09-11 by running `layout.segment_problems` on a multi-line page:

```
'第1問' | 第1問 次の問いに答えよ。
'問1'   | 問1 2次関数 y = x^2 - 4x + 1 の頂点の y 座標を求めよ。
'問2'   | 問2 このとき x = 2 で最小値をとる理由を述べよ。
'第2問' | 第2問 次の英文を読み設問に答えよ。
'(1)'   | (1) 下線部を和訳せよ。
'(2)'   | (2) 筆者の主張を80字で述べよ。
```

**Correction (final review, measured on the current head):** the claim above
that this split "appears in" the evidence pack does not hold. Running
`layout.segment_problems` over all eight forms' stored page text in
`tests/fixtures/answer_forms/cases.json` produces only `第N問`/`大問N`
headings and zero sub-question deck rows for every form — each one collapses
to the `全問` whole-section fallback described under "Grouping rule" below,
not the per-sub-question split this feature is for:

```
K01 lines=1 units=['第1問']      T02 lines=3 units=['第1問','第2問','第4問']
K02 lines=1 units=['第2問']      K03 lines=1 units=['第2問']
T01 lines=1 units=['第3問']      K04 lines=1 units=['第3問']
T03 lines=1 units=['第5問']      T04 lines=3 units=['第1問','第2問','第4問']
```

The seventeen `expected[].source.section`/`source.item` values (`第N問` as
section; `問N`, `(N)`, `(三)`, `(A)`, `全問` as items) are hand-authored
scoring metadata, not something the segmenter reproduces from the stored
text. The cause: the fixture pack stores each page's OCR as a single line
(`input.pages[].text` contains no `\n`), and `parse_layout` scans
`text.splitlines()`, so a marker that would be line-leading in real,
multi-line OCR is instead mid-line in this pack and is never seen as a
boundary. Whether real device OCR emits actual line breaks — which would
make this a non-issue in production — is an open question with no evidence
in this repository, not a conclusion; see the pytest case pinning this
measurement in `tests/test_layout.py`.

### Grouping rule

Walk the deck in document order.

- `大問N` or `第N問` starts a new group. The heading row is not an answer item.
- Every other row joins the current group as an item.
- A deck that starts with a non-heading row opens one default group first.
- A group that gains no item keeps its own heading row as a single item
  labelled `全問`. `AnswerBundle` rejects an empty item list, and the
  figure-style whole-section question (`第4問 全問` in T02/T04) is a real form.

`AnswerItem.identifier` accepts `[A-Za-z0-9_.-]` only, so identifiers are
synthesized -- `g1`, `g2`, ... for groups and `q{questions.id}` for questions --
and the Japanese text goes to `groupLabel` and `questionLabel`, which allow up
to 120 characters.

### Segmenter defect found while verifying

`app/layout.py:32` detects a parenthesized sub-question with

```python
_PAREN_Q_RE = re.compile(r"^\s*[（(]\s*([0-9０-９]{1,3})\s*[)）]")
```

Only half-width and full-width Arabic digits match. A line-leading `(三)` or
`(A)` is absorbed into the preceding item's body instead of becoming its own
deck row. This narrowing is real and is confirmed with hand-built,
genuinely line-leading cases
(`tests/test_layout.py::test_kanji_and_letter_sub_questions_split`) — **not**
with the evidence pack. **Correction (final review):** T02 and T04's `(三)`
and `(A)` are mid-line, not line-leading — T02's stored page text is
`'第1問 (三) 傍線部について…'` — so `_PAREN_Q_RE`'s `^\s*` anchor never
reaches them regardless of the character class, and this widening changes
nothing for T02 or T04. See "Sub-question structure" above for what the
eight-form measurement does and does not establish.

Fix: extend the character class to kanji numerals 一-十 and Latin capitals A-Z.
The rule stays anchored at the start of a line, so the existing protection
against mid-text parentheses such as `大戦（1914）` is unaffected, and a
genuinely line-leading `(三)`/`(A)` — the form real per-line OCR would
produce — now splits correctly. The fix is correct on its own terms; it just
does not do what this section originally claimed for T02/T04.

## Server: GET /v1/exam-sessions/{id}/answer-bundle

Read-only. Returns exactly the JSON `AnswerBundle.fromJson` parses:
`schema_version`, `session_id`, `input_digest`, `revision`, `items[]`, each item
carrying `group_id`, `group_label`, `question_id`, `question_label`, `answer`,
`status`, `issue`.

- **items** come from `_deck_question_rows` plus `_latest_solution_row`, grouped
  by the rule above.
- **status** is `ready` when a solution row exists with non-empty answer text,
  `pending` when no solution row exists, and `failed` when a solution row exists
  with empty answer text. `AnswerItem` requires the answer string to be empty
  unless the status is `ready`, and moves the explanation into `issue`.
- **input_digest** is a SHA-256 over the document's page identity: the ordered
  `(page_index, phash, ocr_md5)` triples. It is stable for an unchanged input
  and changes when a page is re-captured. A session with no bound document
  digests its ordered question ids instead.
- **revision** is `max(solutions.id) + 1` within the session, or `1` when no
  solution row exists. It only has to increase; `AnswerStore` rejects a bundle
  older than the saved one.
- **409** during the reading phase and when `mode=real` is locked. The bundle
  schema cannot express "locked", so the existing locked payload is not
  returned here.

`API_VERSION` is bumped. README examples and the documentation-contract test
move with it.

## Android

`DocScanApi.answerBundle(long sessionId)` -- one method over the existing
private `get(String)` -- returns a parsed `AnswerBundle`.

On the glasses, `DocScanGlassActivity` swaps `setContentView` to `AnswerView`
when a bundle is available and back to `HudView` when the reader exits. The
bundle is fetched once, saved through `AnswerStore`, and read offline; a resume
restores the saved question and offset.

The four measured gestures map straight onto the reader, which already exposes
exactly those verbs:

| Gesture | Reader |
|---|---|
| `SWIPE_FORWARD` | `forward()` |
| `SWIPE_BACK` | `backward()` |
| `SHORT_TAP` | `tap()` |
| `BACK` | `back()`; false leaves the reader |

`LONG_PRESS` stays unbound.

## Out of scope

- FS-63 deployment, authentication and budget.
- Math, table and figure rendering inside an answer (the todo list's FS-65).
- Any privacy-indicator behaviour.
- Physical verification of the hotspot topology, the two-stage exit and the
  re-wear recovery. Those are hardware runs, recorded separately.

## Verification

- Server: pytest cases for the grouping rule against the eight fixture forms,
  the empty-group fallback, digest stability, revision monotonicity, and the
  409 paths. `ruff check .`.
- Segmenter: a case pair proving `(三)` and `(A)` split while `大戦（1914）`
  does not.
- Android: unit tests for `answerBundle` parsing and for the gesture-to-reader
  mapping, then `test testDebugUnitTest assembleDebug`.
- Hardware, separately: glasses join the phone hotspot, fetch one bundle, then
  read it with the phone's hotspot off.
