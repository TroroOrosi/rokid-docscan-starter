# Model and reasoning effort for the booklet routes: what the sources say (2026-11-16)

Status: Research. Every source below was read on 2026-11-16. Nothing in this file was measured on
this system: it records what OpenAI documents, what the open-source Codex CLI does in code, and what
third parties measured. It does not decide the setting. Sections 7 to 9 say what an in-house
measurement still has to decide.

The question: the Codex CLI route and the ChatGPT Work route must share one model and one reasoning
effort, chosen on evidence. Order of criteria: image reading accuracy, then correctness on hard
problems, then time. The setting today is GPT-6.1 Sol at Extra High (`xhigh`) on the Fast tier on
both routes.

How to read this file:

- Section 1 is what OpenAI states. Section 2 is what was read in the Codex source at the release tag
  the phone runs. Section 3 is one observation on the development PC. Section 4 is independent
  measurement. Section 5 is my inference and is marked as such. Section 6 lists what was looked for
  and not found.
- Source keys such as [O3] or [C2] point to the list at the end, which gives the URL and the read
  date. A page that changes after that date is not covered.
- Pages were read as text. Where a number came through a fetch-and-summarise tool rather than from
  the page's own text or data, the entry says so; those numbers need a human look before anything
  rests on them.
- Wording is paraphrased. One phrase is quoted, in section 1.2.

## 1. Official statements

### 1.1 Models for Work and Codex with a ChatGPT sign-in

OpenAI's model page for Work and Codex names four current models [O1]. Their API model pages give the
specifications [O8][O9][O10][O11].

| Model (id) | What OpenAI says it is for | Effort levels (API page) | Context window | Image input |
|---|---|---|---|---|
| GPT-6 Astra (`gpt-6-astra`) | OpenAI's strongest model; for the hardest end-to-end work in code, apps and research [O1][O10] | low, medium, high, xhigh, max; no `none` [O10][O12] | API 1,050,000, at most 922,000 input and 128,000 output [O10] | yes [O10] |
| GPT-6.1 Sol (`gpt-6.1-sol`) | Nearly Astra's level on complex work for less; suggested for long-running, repeated work in code, apps and documents [O1][O8] | low, medium (API default), high, xhigh, max; no `none` or `minimal` [O8][O12] | API 1,050,000; 500,000 by default in Codex and Work [O1][O8] | yes [O8] |
| GPT-6.1 Terra (`gpt-6.1-terra`) | Quick and economical; aimed at writing, understanding images and screens, and computer use [O1][O9] | none, low, medium (API default), high, xhigh, max [O9] | API 1,050,000 [O9] | yes [O9] |
| GPT-6 Luna (`gpt-6-luna`) | The cheapest to run; for narrow, repeated tasks such as extraction and summarising [O1][O11] | none to max; up to Max but not Ultra in Codex [O1][O11] | API 1,050,000 [O11] | yes [O11] |

Further points on that page and its neighbours:

- Where each model is offered: the page lists the desktop app, Work on the web, the CLI and the IDE
  extension beside Astra, GPT-6.1 Sol and Luna, and the first three beside GPT-6.1 Terra (CLI 0.159.0
  or later), and gives a `codex -m` command for each [O1]. The availability marks beside those rows
  did not come through in the page's text. In words: GPT-6.1 Sol is for Plus, Pro, Business,
  Enterprise and Edu in Work and Codex [O18]; GPT-6.1 Terra likewise [O3].
- GPT-6.1 Sol and GPT-6.1 Terra are offered in Work and Codex and not in Chat [O3][O18].
- GPT-6 Sol (`gpt-6-sol`) still exists as the previous Sol; its API page points to GPT-6.1 Sol as the
  newer one [O11]. GPT-5.5 was retired from Codex with ChatGPT sign-in on 2026-10-14 [O1].
- In the clients the effort names are Light (Low in the CLI), Medium, High and Extra High, with Max
  and Ultra beyond them where offered. Max gives a single run more time to reason; Ultra splits work
  across subagents. The page says most tasks need neither [O1].
- Plans: the Plus card lists GPT-6.1 Sol and GPT-6 Luna, while the usage table on the same page gives
  Plus a figure for Astra and for Terra as well, and the Astra announcement says Astra is offered to
  Plus [O3][O20]. The page is not consistent with itself on Astra for Plus.

Is any model positioned as better at vision or document reading than GPT-6.1 Sol?

- GPT-6.1 Terra is the one positioned for visual work. OpenAI describes it as combining detailed
  visual reasoning with computer use, and gives interpreting technical drawings and reading invoices
  as uses [O9][O19]. But on the visual-reasoning benchmark OpenAI itself cites (MMMU-Pro) the claim is
  that Terra beats the older GPT-5.6 Terra at every reasoning setting and comes close to Astra and
  GPT-6.1 Sol at lower cost. That is a claim of near parity, not of reading better than Sol [O19]. The
  same post says Sol and Astra remain the better choice for the most complex coding tasks [O19].
- GPT-6 Astra is positioned as the most capable overall [O1][O20]. Its announcement gives no document
  or text-reading score; the one perception number is ScreenSpot-Pro (locating screen elements),
  92.7% [O20].
- GPT-6.1 Sol's own announcement cites GDP.pdf, answering professional questions from complex PDF
  pages with tables, charts and fine print, and says Sol approaches Astra there at about a fifth of
  the cost per task [O18].

Is any model positioned as faster at equal quality?

- Not as a model. Terra is described as fast, and as finishing tasks on one benchmark (Agents' Last
  Exam) more than three times faster than Astra and Sol, but it is not claimed to equal Sol on hard
  work [O19].
- As a speed mode, yes: Ultrafast is offered for Astra and GPT-6.1 Sol, up to eight times the
  standard token rate, on the Pro $500 plan and eligible Enterprise and Edu plans only. It draws
  included usage at eight times the Standard rate [O4][O18]. It is not on Plus.

### 1.2 Reasoning effort

- What it does: lower effort favours speed and fewer tokens; higher effort has the model think more
  completely for higher quality. The models also adapt within a setting, spending fewer tokens on
  simple tasks [O12]. The Work and Codex page says the same in product terms: higher effort can
  improve results on complex tasks, takes longer and uses more tokens; start at the client's default
  and raise it when the task needs deeper planning or analysis [O1].
- Reasoning tokens are billed as output tokens and take space in the context window; a response can
  spend from a few hundred to tens of thousands of them. OpenAI suggests leaving at least 25,000
  tokens for reasoning and output when starting out [O12].
- Guidance by level in the API guide [O12]: `medium` is described as the balanced default for most
  workloads; `high` is for hard reasoning where quality matters more than latency, with the advice to
  evaluate both medium and high; `max` is for the most complex tasks. For `xhigh` the guide names
  deep research, asynchronous and long-running agentic work, and adds: "Only use when your evals show
  a clear benefit" (OpenAI, Reasoning models guide [O12]).
- The same guide says to treat effort as a tuning knob and not as the main way to recover quality
  [O12]. The latency guide says to try a lower effort for routine extraction and compare accuracy and
  time on the same examples [O16].
- Model selection guidance pairs GPT-6.1 Sol at Medium with complex technical work that will be
  revised, and GPT-6.1 Sol at Extra High with polished deliverables and decisions built from
  conflicting evidence. It tells the reader to compare on the same inputs, measure completion time
  along with quality, and keep the lightest setting that meets the quality bar [O2].
- Defaults differ by surface: the API default for GPT-6.1 Sol is medium [O8][O12]; the Work and Codex
  page says to start from whatever the client offers by default [O1]. (The CLI's own catalog default
  is in section 2.3.)
- Efforts do not map exactly between model generations [O1]. When moving from GPT-6 Sol to GPT-6.1
  Sol, a former `none` becomes `low` [O17].
- Effort and factual error, from OpenAI's own evaluations on deliberately hard prompts: GPT-6.1
  Terra's error rate is 16.7% at low effort and 4.3% at maximum effort [O19]; GPT-6.1 Sol's is 7.7% at
  low effort [O18]. Both sets were chosen to provoke errors; the Sol post says they are not typical
  use.
- Whether image perception itself changes with effort: OpenAI does not say. The vision guide ties what
  the model can see to image size and the detail level, not to effort [O13]. See section 6.

### 1.3 Fast mode (the priority service tier)

- In the API, Fast mode was called priority processing until 2026-07-30; `service_tier` takes either
  `fast` or `priority` with the same result. The guide gives up to 2.5 times the speed of Standard and
  more consistent latency, and says image inputs are supported [O15].
- In Codex, Fast mode covers GPT-6.1 Sol, GPT-6.1 Terra, GPT-6 Astra, GPT-6 Sol and GPT-6 Luna where
  available. The page gives a number for one family only: 1.5 times for GPT-5.6 [O4]. The Astra
  announcement gives up to twice the speed for Astra in the API [O20].
- Usage: on supported models Fast draws included subscription usage at 2.5 times the Standard rate;
  purchased credits and pay-as-you-go are billed at twice the Standard rate [O3][O4]. This matches the
  internal record.
- Configuration: the documented setting is `service_tier = "fast"`, which the CLI sends as the request
  value `priority`; the Fast controls are on by default [O6].
- Limits: in the API a fast ramp of traffic can be served at standard speed and reported as the
  default tier in the response [O15]. Fast for Astra carries no latency commitment [O15][O17]. Nothing
  comparable is documented for a ChatGPT sign-in.

### 1.4 Image input in the API

From the vision guide [O13] and its calculator page [O14]:

- Formats: PNG, JPEG, WEBP and non-animated GIF. A request may carry up to 1,500 images and up to
  512 MB in total.
- The `detail` parameter takes low, high, original or auto, depending on the model; omitted, it is
  auto. For reading fine detail, the guide names optical character recognition explicitly and says to
  use original where the model supports it.
- Newer models tokenise an image as 32 x 32 pixel patches: the patch count is the width in patches
  times the height in patches, each rounded up; the billable tokens are the patch count times a model
  multiplier. Images are never enlarged.
- Per image there is a hard limit of 30,000 patches after resizing. An image over it is rejected, not
  shrunk.
- The sizing table has rows for these families:

| Family in the table | low | high | original | auto |
|---|---|---|---|---|
| `gpt-6-astra` | fits 512 x 512 | up to 2,500 patches, longest side up to 65,535 px | keeps the image's size up to 65,535 px a side; rejected over 30,000 patches | same as original |
| `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna` | fits 512 x 512 | fits 2048 x 2048 and 2,500 patches | as for Astra | same as original |
| `gpt-5.5` | fits 512 x 512 | 2,500 patches, 2048 px | 10,000 patches, 6000 px | same as original |

- The multiplier table gives 1.2 for `gpt-6-astra` and for the GPT-5.6 family. Worked example from the
  guide for Astra at high: a 2048 x 2048 image is brought to 1600 x 1600, 2,500 patches, 3,000 tokens.
- Neither table has a row for `gpt-6.1-sol`, `gpt-6.1-terra`, `gpt-6-sol` or `gpt-6-luna`. The guide
  says other models can use different limits. See section 6.
- Limitations the guide lists that bear on this system: text in non-Latin scripts, with Japanese named
  as an example, may be read less well; small text should be enlarged, and original detail can help;
  rotated or upside-down text may be misread; images may be resized before analysis even at original
  detail.

In the product, the image-input page for Work and Codex says only how to attach images (in the CLI,
`-i` or `--image`, several paths separated by commas or the flag repeated; PNG and JPEG among the
accepted formats). It gives no size or resolution rule [O5].

### 1.5 Usage limits and credit rates

From the pricing page [O3]:

- Work and Codex share one allowance, credits and limits. This matches the internal record.
- Estimated local messages per five hours on Plus (and Standard Business). The page calls these
  estimates and not fixed limits, says weekly limits may also apply, and says Pro plans currently have
  no five-hour limit.

| Model | Plus, local messages per five hours |
|---|---|
| GPT-6 Astra | 5 to 45 |
| GPT-6.1 Sol | 15 to 160 |
| GPT-6.1 Terra | 35 to 285 |
| GPT-6 Sol | 15 to 150 |
| GPT-6 Luna | 350 to 3,000 |

- Credit rates at Standard speed, per million tokens. The page says these do not by themselves
  determine what the subscription includes.

| Model | Input | Cached input | Output |
|---|---|---|---|
| GPT-6 Astra | 250 | 25 | 1,250 |
| GPT-6.1 Sol | 50 | 2.5 | 250 |
| GPT-6.1 Terra | 25 | 1.25 | 125 |
| GPT-6 Sol | 50 | 5 | 250 |
| GPT-6 Luna | 2.5 | 0.25 | 12.5 |

- Usage is counted in tokens and depends on model, context, reasoning, tool use and caching. No figure
  per message by effort is published; effort enters through the reasoning tokens, which are output
  tokens [O3][O12].
- GPT-6.1 Sol usage from a subscription carries no long-context surcharge in Codex or Work [O3][O8].
- At the limit, a turn already running may finish within fair-use limits; after that Plus can wait for
  the reset or buy credits [O3]. `/status` in the CLI and the usage dashboard show what is left [O3].
- The Terra announcement says the same allowance covers substantially more tasks with Terra than with
  GPT-6.1 Sol or Astra [O19].

A change that is coming, from the Help Center article on usage limits (shown as updated 14 days
before the read date) [O21]: starting in December, the allowance of Plus, Pro and Business will be
shared across ChatGPT and Codex and measured in tokens, and only Instant chat will not draw on it.

### 1.6 OpenAI's own evaluation numbers that bear on the question

- Mathematics: Astra, FrontierMath Tier 4 (v2) 97.6%, with the note that scores on that page are the
  maximum at any effort [O20]. No mathematics score is given for GPT-6.1 Sol or Terra in their posts
  [O18][O19].
- Documents: GDP.pdf for GPT-6.1 Sol, described in 1.1; the post gives the comparison in words and not
  as a table of numbers by effort [O18].
- Visual reasoning: MMMU-Pro for Terra, in words only [O19].
- All three posts say the evaluations were run in a research environment or over the API and may
  differ from the product [O18][O19][O20].

## 2. Read in source code

Repository: openai/codex, tag rust-v0.169.0 (tag object a41fe5b, commit d32063f96c2dff1dc96af839b3952abb6acfeda4,
tagged 2026-11-13). This is the CLI version the routes run. The files were read at that tag, not on
the main branch; main has already moved (it has an image sanitizer module the tag does not have), so
this section has to be read again on an upgrade. The code was read, not executed.

### 2.1 What the CLI does with an image given with -i

1. `codex exec` turns each `-i` path into a local-image input with no detail level set [C4, about
   lines 1006, 1030 and 1058].
2. The session converts user input with local images deferred: the file's bytes are carried as they
   are, and the default detail level, high, is attached [C3, lines 1004 and 2281; C5, line 3990].
3. Before the item is stored and sent, the session prepares every image. It chooses the unified budget
   when the feature of that name is on and the model either uses the lighter Responses transport or
   supports original detail; otherwise it goes by each image's detail level [C2, line 47; C5, about
   lines 3934 to 3977].
4. The feature `unified_image_budget` is marked stable and on by default at this tag [C6, line 2028].
   The bundled catalog marks `gpt-6.1-sol` as supporting original detail and as using the lighter
   transport [C10]. So for this model every image, whatever its detail level, is prepared under the
   original-detail policy [C2, lines 393 to 432].
5. The original-detail policy: longest side at most 6000 px and at most 10,000 patches of 32 x 32 px
   [C1, lines 24 and 80 to 82]. An image inside both limits is sent byte for byte if it is PNG, JPEG
   or WebP [C1, line 354]. An image outside either limit is scaled down with a triangle (bilinear)
   filter [C1, lines 164 and 174] and encoded again in its own format, JPEG at quality 85 [C1, line
   395]; a GIF becomes a PNG.
6. The request then drops the detail field for models on the lighter transport, so the server applies
   its own default [C8, lines 113 to 115].
7. The model is not told that an image was reduced: the notice feature is under development and off by
   default [C6, line 2022].

Other paths in the same code, for completeness:

- With the unified budget off, or for a model without original detail, an image with no detail level
  is prepared under the high-detail policy: 2048 px and 2,500 patches [C1, lines 75 to 77; C2, lines
  406 to 420]. Turning the feature off would therefore cut every page to a quarter of the patches.
- A second, older resize in the protocol layer (longest side 2048 px) applies only where local images
  are processed or snapshotted before the session sees them [C1, line 26; C3, line 2006; C16]. The
  exec path does not take it at this tag.
- An image the model opens itself with the built-in image-viewing tool is prepared at original detail
  when the unified budget is on [C13, line 184].
- Low detail is refused by the preparation step [C2].
- A single image may be up to 1 GiB before it is refused; the code calls this a sanity guard [C1,
  line 31]. No limit on the number of images was seen in the files read; that was not searched for
  exhaustively.

Constants:

| Name | Value | Where |
|---|---|---|
| `PROMPT_IMAGE_PATCH_SIZE` | 32 | [C1] line 24 |
| `MAX_DIMENSION` (older resize-to-fit path) | 2048 | [C1] line 26 |
| `MAX_PROMPT_IMAGE_INPUT_BYTES` | 1,073,741,824 | [C1] line 31 |
| `HIGH_DETAIL` | 2048 px, 2,500 patches | [C1] lines 75 to 77 |
| `ORIGINAL_DETAIL` | 6000 px, 10,000 patches | [C1] lines 80 to 82 |
| JPEG quality when re-encoding | 85 | [C1] line 395 |
| `DEFAULT_IMAGE_DETAIL` | high | [C3] line 1004 |
| `ORIGINAL_IMAGE_MAX_PATCHES` (token estimate) | 10,000 | [C9] line 1329 |
| `RESIZED_IMAGE_BYTES_ESTIMATE` (other images) | 7,373 bytes, about 1,844 tokens | [C9] line 1321 |

The repository's own test pins two cases of the resize: 2048 x 2048 under the high policy becomes
1600 x 1600, and 6401 x 100 under the original policy becomes 6000 x 94 [C14]. A port of the function
that reproduces both gives these results for sizes this system produces (computed for this file, not
taken from the source):

| Source image | Patches | Sent by the CLI under the original policy | Linear scale |
|---|---|---|---|
| 4032 x 3024 still | 11,970 | 3669 x 2752, re-encoded | 0.910 |
| 3024 x 4032 gathered page | 11,970 | 2752 x 3669, re-encoded | 0.910 |
| 3000 x 4200 (a 1500 x 2100 page at twice its size) | 12,408 | 2688 x 3763, re-encoded | 0.896 |
| 1500 x 4200 (half of that page as a strip) | 6,204 | unchanged | 1 |
| 2480 x 3508 (A4 at 300 dpi) | 8,580 | unchanged | 1 |
| 2016 x 1512 clip frame | 3,024 | unchanged | 1 |
| 3200 x 3200 | 10,000 | unchanged | 1 |

### 2.2 How the CLI counts image tokens

For its own context accounting the CLI counts an original-detail image as its patch count, capped at
10,000, at one token per patch [C9, lines 1501 onward]. The comments there point to the API vision
guide as the basis and say the cap is hard-coded for now. The CLI's 6000 px and 10,000 patch policy is
the one the guide lists for `gpt-5.5` at original detail, and is tighter than the guide's row for
`gpt-6-astra` (65,535 px, 30,000 patches) [C1][C9][O13].

### 2.3 The bundled model catalog

The catalog shipped in the tag [C10] has these entries for the visible GPT-6 models. It is a fallback;
the catalog a signed-in client is served can differ (section 3).

| Model | Default effort | Efforts listed | Context window, maximum | Fast tier as described | Original detail | Lighter transport |
|---|---|---|---|---|---|---|
| `gpt-6.1-sol` | low | low, medium, high, xhigh, max, ultra | 272,000, 872,000 | twice the speed, more usage | yes | yes |
| `gpt-6-astra` | low | same six | 272,000, 872,000 | twice the speed, more usage | yes | yes |
| `gpt-6.1-terra` | low | same six | 500,000, 872,000 | 1.5 times the speed | yes | yes |
| `gpt-6-sol` | medium | same six | 272,000, 872,000 | 1.5 times; Fast is its default tier | yes | yes |
| `gpt-6-luna` | medium | low to max | 272,000, 872,000 | 1.5 times; Fast is its default tier | yes | yes |

A context window set in configuration is capped at the model's maximum [C15].

### 2.4 Service tier and effort values

The CLI knows two service tiers, fast and flex. It accepts either `fast` or `priority` for the first
and sends `priority`; `default` is a separate value meaning the user chose standard routing on purpose
[C11, lines 528 to 550]. This confirms the internal record. The effort values the CLI knows are none,
minimal, low, medium (the type's default), high, xhigh, max, ultra and persistent, plus any value a
model defines [C12, line 74]; which of them a model accepts comes from the catalog.

## 3. Observed on the development PC

Not a source and not the phone: the model catalog the CLI had cached on the development PC, written by
client 0.169.0 with a fetch time of 2026-11-16 08:58 UTC. It shows what the service handed a signed-in
client that day.

| Model | Default effort | Context window, maximum | Usable share | Fast tier as described | Original detail | Lighter transport |
|---|---|---|---|---|---|---|
| `gpt-6.1-sol` | low | 500,000, 872,000 | 95% | twice the speed, more usage | yes | yes |
| `gpt-6-astra` | medium | 272,000, 872,000 | 95% | twice the speed, more usage | yes | yes |
| `gpt-6.1-terra` | low | 500,000, 872,000 | 95% | 1.5 times the speed | yes | yes |
| `gpt-6-sol` | medium | 272,000, 872,000 | 95% | 1.5 times the speed | yes | yes |
| `gpt-6-luna` | medium | 272,000, 872,000 | 95% | 1.5 times the speed | yes | yes |

It agrees with the documentation on the 500,000 window for GPT-6.1 Sol [O1] and differs from the
bundled catalog there (272,000). It confirms the two flags that put the model on the unified image
budget. The GPT-5.6 family was also listed as visible. The phone's own cache was not read.

## 4. Independent measurements

### 4.1 Artificial Analysis, by reasoning effort

Artificial Analysis runs each effort level as its own entry, over OpenAI's API [I1][I2][I3]. The pages
do not mention the Fast tier, so the timings are taken here as the standard tier. The headline numbers are in the pages' text; the per-evaluation numbers below were taken
from the data embedded in the same pages, and the column mapped to the hard subset of CritPt v2 was
identified by its field name. Sample sizes, from the methodology page as read through a
fetch-and-summarise tool [I4]: MMMU-Pro 1,730 questions, one run, ten-option multiple choice; GDP.pdf
100 tasks, five runs each, graded by a rubric with every criterion required, with page images given to
models that take images; HLE-Diamond 1,000 questions, 272 of them with an image; CritPt v2 hard subset
40 problems; Terminal-Bench-Science 70 tasks, three runs. Time per task is derived by Artificial
Analysis from output tokens and output speed; it is not a wall-clock measurement of a run.

GPT-6.1 Sol [I1]:

| Effort | Index | MMMU-Pro (visual) | HLE-Diamond | CritPt v2 hard | GDP.pdf all-pass | Seconds to first answer token | Seconds per index task | Reasoning tokens per index task | USD per index task |
|---|---|---|---|---|---|---|---|---|---|
| low | 34.8 | 83.1% | 38.2% | 62.5% | 27.0% | 3.0 | 113 | 1,585 | 0.16 |
| medium | 46.4 | 83.9% | 46.0% | 67.0% | 30.0% | 4.8 | 260 | 4,805 | 0.36 |
| high | 50.3 | 84.9% | 51.9% | 68.5% | 32.0% | 32.9 | 455 | 10,140 | 0.59 |
| xhigh | 52.5 | 85.1% | 55.8% | 69.5% | 31.8% | 68.6 | 592 | 15,527 | 0.76 |
| max | 54.6 | 86.0% | 58.8% | 69.5% | 31.0% | 167.4 | 1,372 | 49,210 | 1.27 |

GPT-6 Astra [I3]:

| Effort | Index | MMMU-Pro (visual) | HLE-Diamond | CritPt v2 hard | GDP.pdf all-pass | Seconds to first answer token | Seconds per index task | Reasoning tokens per index task | USD per index task |
|---|---|---|---|---|---|---|---|---|---|
| low | 43.3 | 84.6% | 45.1% | 63.0% | 30.4% | 3.5 | 204 | 3,304 | 1.42 |
| medium | 51.6 | 85.1% | 52.7% | 72.0% | 30.4% | 6.1 | 414 | 8,581 | 2.73 |
| high | 54.9 | 86.4% | 59.3% | 71.5% | 31.0% | 49.3 | 553 | 12,090 | 3.24 |
| xhigh | 55.3 | 86.2% | 61.5% | 71.0% | 32.2% | 87.5 | 685 | 14,690 | 3.66 |
| max | 56.9 | 86.9% | 63.8% | 70.5% | 31.0% | 200.4 | 1,254 | 35,760 | 6.25 |

GPT-6.1 Terra [I2]:

| Effort | Index | MMMU-Pro (visual) | HLE-Diamond | CritPt v2 hard | GDP.pdf all-pass | Seconds to first answer token | Seconds per index task | Reasoning tokens per index task | USD per index task |
|---|---|---|---|---|---|---|---|---|---|
| none | 30.5 | 76.0% | 14.5% | 33.5% | 23.2% | 2.4 | 143 | 0 | 0.23 |
| low | 29.4 | 82.5% | 24.9% | 50.5% | 25.6% | 2.7 | 69 | 950 | 0.07 |
| medium | 38.2 | 82.8% | 31.3% | 56.5% | 28.4% | 4.5 | 166 | 4,055 | 0.17 |
| high | 42.4 | 83.8% | 35.4% | 61.5% | 28.0% | 10.3 | 246 | 7,618 | 0.26 |
| xhigh | 45.3 | 83.8% | 42.3% | 60.5% | 26.6% | 29.5 | 375 | 14,190 | 0.40 |
| max | 51.3 | 84.7% | 47.3% | 68.0% | 28.6% | 150.7 | 827 | 39,360 | 0.96 |

Output speed, tokens a second including reasoning: GPT-6.1 Sol 49 to 52 at every effort, Terra 65 to
72, Astra 39 to 45 [I1][I2][I3]. The older GPT-6 Sol runs at 104 to 125 with lower scores (MMMU-Pro
82.5% at xhigh, 83.0% at max) [I12]. No entry for the Fast tier was seen.

### 4.2 Roboflow Vision Evals: reading text, low against high effort

Read through a fetch-and-summarise tool only; a direct fetch was refused (HTTP 429). The pages give
evals as updated 2026-11-12 and do not state the number of samples, the content of the reading set or
its language [I6][I7]. Most task scores are means of three runs; the reading rows show no run count.

| Model | Reading task, low | Reading task, high | Transcription only, low | Transcription only, high | All five tasks pooled, low |
|---|---|---|---|---|---|
| GPT-6.1 Sol | 75.8% | 75.8% | 95.7% | 96.0% | 81.7% |
| GPT-6.1 Terra | 81.9% | 84.4% | 96.7% | 97.0% | 85.8% |
| GPT-6 Astra | 77.8% | 77.6% | 95.9% | 97.5% | 83.4% |

The reading task has four parts: single-value extraction, transcription, structured output and text
localisation. Terra's lead over Sol comes mostly from single-value extraction (70.9% against 58.3% at
low) and localisation; on plain transcription the three models are within about one point at low
effort.

### 4.3 Mathematics

- MathArena, research-level problems drawn from recent arXiv papers, run through the Codex harness
  [I8][I9]. GPT-6.1 Sol at max: 92.8% (plus or minus 3.1) overall on its ArXivMath sets, expected
  performance 80.6%, rank 3. GPT-6 Astra at max: expected 78.0%; at low: 73.3%. On the three
  ArXivMath sets both Astra entries share, low against max: 88.8% against 95.0%, 84.4% against 94.4%,
  85.1% against 88.6%, each with an interval of four to seven points. No entry exists for GPT-6.1 Sol
  below max, or for Terra. Problem counts are not on the model pages.
- Epoch AI [I10]: FrontierMath Tier 4 (v2), GPT-6.1 Sol 100%, Astra 98%; FrontierMath Erdős, Sol 4%,
  Astra 3%. The page does not state the effort used.
- Nothing was found at university-entrance level for these models. See section 6.

### 4.4 Japanese text

JaWildText (Annual Meeting of the Association for Natural Language Processing, March 2026; marked as
not peer reviewed) is a Japanese set of 335 real-world photographs covering dense scene-text question
answering, receipts and handwriting [I11]. It evaluates open models and reading-specific models, not
the GPT-6 family, which it predates. The text of the paper could be extracted only in part, so no
score is reproduced here. It is listed because it is the one Japanese photographed-text benchmark the
search turned up.

## 5. Inference (mine)

Each point is my reading of the sources above, not something a source states.

1. Effort changes what the model sees very little. On MMMU-Pro, GPT-6.1 Sol moves 2.9 points across
   the whole range from low to max, and 0.2 points from high to xhigh; with 1,730 questions in one
   run, one score has a 95% interval of about plus or minus 1.7 points, so high and xhigh cannot be
   told apart there. Roboflow's reading task shows no change for Sol between low and high. GDP.pdf,
   read from page images, peaks at high (32.0%) and is not higher at xhigh or max; with 500 attempts
   the interval is at least plus or minus 4 points, so the levels from medium up cannot be told apart.
   The step that does matter for vision is reasoning against none (Terra: 76.0% without reasoning,
   82.5% at low).
2. Effort changes hard reasoning by a few points a step. For GPT-6.1 Sol, high to xhigh is 51.9% to
   55.8% on HLE-Diamond (interval about plus or minus 3 points on one score) and 50.3 to 52.5 on the
   index, for 1.3 times the derived time per task, 1.5 times the reasoning tokens and about twice the
   wait for the first answer token. The internal single run (Work, twenty pages) had 1.64 times the
   time. Medium to high is the larger step in score (46.0% to 51.9%) and in wait (4.8 s to 32.9 s).
3. So if reading errors on this system come from the image (size, blur, noise, script), the sources
   predict that raising effort will not remove them and lowering it from xhigh to high will not add
   many. Section 2.1 is where the reading is more likely to be won or lost. This has to be checked on
   the system's own pages; none of the benchmarks is Japanese, vertical or photographed by a wearer.
4. Page size against the CLI's cap. A page over 10,000 patches (about 10.2 megapixels) or 6000 px is
   reduced and re-encoded before it leaves the phone, silently. A full 4032 x 3024 frame or a
   3024 x 4032 gathered page loses 9% in each direction; a whole page enlarged to twice its size past
   the cap is brought back under it, which undoes part of the enlargement. A strip is its own image
   with its own budget, which is a reason, besides the one measured in this repository, why strips
   read better than one large image. Keeping every file at or under 10,000 patches and 6000 px also
   keeps its bytes untouched.
5. Context arithmetic. With a 500,000 window of which 95% is usable, and the CLI counting up to 10,000
   tokens an image, about 47 images at the cap fill the window before any text or output. If the
   service applied the 1.2 multiplier documented for Astra, the same images would count 12,000 each.
   The multiplier for GPT-6.1 Sol is not documented.
6. The CLI and the documentation disagree about how much of an image may be sent: the CLI holds to
   6000 px and 10,000 patches, the API guide allows Astra 65,535 px and 30,000 patches. What the
   ChatGPT service does with an image for GPT-6.1 Sol after the CLI has prepared it is not documented.
   The same model and effort on the CLI and on Work on the web are therefore not shown to read an
   image at the same resolution.
7. Model choice under the one-model rule. Terra is cheaper (half of Sol's credit rates), faster (about
   1.4 times the tokens a second, and roughly 0.6 times the derived time per task at equal effort) and
   ahead on one reading harness, but it is behind Sol on MMMU-Pro at every effort and far behind on
   hard reasoning (HLE-Diamond 42.3% against 55.8% at xhigh). With hard problems assumed, the sources
   do not support moving to Terra. Astra is ahead of Sol by about one point on MMMU-Pro and five to
   seven on HLE-Diamond at equal effort, at five times the credit rates and about a third of the
   messages on Plus; Astra at medium is close to Sol at xhigh on the index (51.6 against 52.5) with a
   far shorter wait for the first token (6 s against 69 s) and about 3.6 times the cost per task. Its
   default window in Codex is 272,000, which would not hold a large booklet without raising it.
8. Usage. One output token costs as much as five input tokens at the published rates for GPT-6.1 Sol,
   so cutting reasoning by 5,000 tokens saves what 25,000 tokens of images cost. Fast multiplies
   whatever the request costs by 2.5 on a subscription. Two parallel reads double it. Cached input is
   a twentieth of the input rate, but two requests sent at the same moment are unlikely to share a
   cache; that was not looked into further.
9. Mathematics at entrance level is not what limits these models, on the evidence available:
   research-level sets are near their ceiling for Sol at max. What the sources cannot say is whether
   Sol at high or medium still solves entrance-level problems as reliably as at xhigh, because no one
   has published that comparison. Thirteen right out of thirteen at both efforts is a ceiling and
   decides nothing. To tell 95% from 85% correct with ordinary confidence takes on the order of 140
   problems a setting if the settings are compared unpaired; fewer if the same problems are run under
   each setting and compared item by item.

## 6. Not found

- How images are sized and counted for `gpt-6.1-sol`, `gpt-6.1-terra`, `gpt-6-sol` and `gpt-6-luna`.
  The vision guide's sizing and multiplier tables have no row for them. Looked in: the vision guide
  and its calculator page (Markdown versions), the four API model pages, the GPT-6 guide.
- Any OpenAI statement on whether image perception changes with reasoning effort. Looked in: the
  reasoning guide, reasoning best practices, the vision guide, the model and model-selection pages,
  the three announcements.
- What ChatGPT's service does to an image after the CLI sends it, and how Work on the web prepares
  images inside an uploaded archive. Looked in: the image-input page, the Work quick start, the web
  and file pages, the pricing page.
- Messages or credits per message by effort. Only the five-hour ranges by model and the per-token
  credit rates are published.
- A weekly limit as a number. The page says only that weekly limits may apply.
- An independent measurement of the Fast tier's speed-up for GPT-6.1 Sol. The documentation and the
  catalog give 1.5 times, twice and up to 2.5 times for different models and surfaces.
- An OpenAI mathematics score for GPT-6.1 Sol, and any mathematics result for it below max effort.
- Any benchmark of these models on Japanese text, on vertical text, or on documents photographed
  rather than scanned. Searches in English and Japanese returned vendor articles without method and
  the JaWildText paper, which does not cover these models. Results for search were thin.
- Any benchmark at university-entrance level for these models at different efforts.
- The system card pages for GPT-6.1 Sol and Terra were not reached; only the announcements that point
  to them were read.
- The speed and capability ratings shown as graphics on the Work and Codex model page do not appear in
  its text version and are not recorded here.

## 7. Candidate settings worth measuring, and what the sources predict

Predictions are from sections 4 and 5, whose timings were taken over the API without the Fast tier;
none is a measurement of this system. Reading means text read correctly from the page image.

| Candidate (both routes) | Reading accuracy | Hard-problem accuracy | Time | Usage |
|---|---|---|---|---|
| GPT-6.1 Sol, xhigh (today) | Reference. MMMU-Pro 85.1% | Reference. HLE-Diamond 55.8%, index 52.5 | Reference. 69 s to first answer token; internal: 556.6 s for twenty pages, once | Reference. About 15,500 reasoning tokens a task |
| GPT-6.1 Sol, high | No difference the sources can resolve (84.9%; reading task equal at low and high) | A few points lower (51.9%; index 50.3) | About 0.6 to 0.8 of the time (internal 339.6 s; derived 455 s against 592 s); 33 s to first token | About two thirds of the reasoning tokens |
| GPT-6.1 Sol, medium | About one point lower on visual reasoning (83.9%), inside the noise | Clearly lower (46.0%; index 46.4) | Under half the time; 5 s to first token | About a third of the reasoning tokens |
| GPT-6.1 Sol, max | About one point higher (86.0%), inside the noise | Higher (58.8%; index 54.6) | More than twice the time; 167 s to first token | About three times the reasoning tokens |
| GPT-6 Astra, medium | Equal to Sol at xhigh (85.1%) | Close to Sol at xhigh (52.7%; index 51.6; CritPt 72.0%) | Shorter; 6 s to first token | Five times the credit rates; Plus 5 to 45 messages per five hours; default window 272,000 |
| GPT-6 Astra, high | About one point higher (86.4%), inside the noise | Higher than Sol at xhigh (59.3%; index 54.9) | Similar to Sol at xhigh | As above, with more reasoning |
| GPT-6.1 Terra, xhigh | Mixed: lower on MMMU-Pro (83.8%), higher on one reading harness (84.4% against 75.8%), equal on plain transcription | Much lower (42.3%; index 45.3) | About 0.6 of the time; 30 s to first token | Half the credit rates; Plus 35 to 285 messages |
| Any of these on Standard instead of Fast | Same | Same | Longer by the tier's factor, which is documented between 1.5 and 2.5 and not independently measured | 2.5 times less |

## 8. What an in-house measurement must still decide

1. Reading on this system's own pages (Japanese print, vertical and horizontal, gathered and still)
   at xhigh, high and medium, with the image preparation held fixed, enough reads a condition to see
   past the read-to-read spread this repository has already measured. The sources contain no such
   data.
2. Whether any file sent with `-i` exceeds 10,000 patches or 6000 px today, and whether reading
   differs between a page just under the cap sent untouched and the same page over the cap and
   reduced by the CLI. The dimensions of the files are enough for the first half and cost nothing.
   Section 2.1 was read and not run: the session record the CLI keeps of a request should hold each
   image as prepared, and its pixel size would confirm the path on the phone (not checked).
3. Hard-problem correctness at high against xhigh on a problem set large and hard enough to leave the
   ceiling, run item by item under both settings.
4. Time on the Fast tier at each effort on both routes, on the phone, for a whole booklet. Artificial
   Analysis timed the standard tier over the API only.
5. Whether Work on the web and the CLI read the same page equally at the same model and effort. The
   one-model rule assumes they do; section 5 point 6 says this is not documented.
6. What a booklet draws from the allowance at each effort and tier, read from the usage dashboard
   before and after.
7. If usage allows it: Astra at medium against Sol at xhigh on the same booklets, since the sources
   put them close in score with Astra much quicker to start answering.

## 9. The three findings most likely to change the current setting

1. Extra High is not supported by the sources as the reading setting. Independent numbers show no
   resolvable gain in visual or document reading from high to xhigh, a gain of a few points on the
   hardest reasoning, and 1.3 to 1.6 times the time with 1.5 times the reasoning tokens; OpenAI's own
   guide reserves xhigh for cases where an evaluation shows a clear benefit. High is the setting to
   test against it, with medium as the lower bound.
2. The CLI reduces and re-encodes any page over 10,000 patches or 6000 px before sending, without
   telling the model, and a full-size still or gathered page is over that cap. For reading accuracy
   this matters more than the effort level, and it is settled by how pages are cut and sized, not by
   the model setting. It also means the two routes are not known to read at the same resolution.
3. Usage is about to get tighter and the current setting is the costly corner of it: Fast draws 2.5
   times the allowance, two reads double it, and from December the allowance is shared with ChatGPT
   so that only Instant chat stays outside it. A route order that counts on Chat when the allowance is
   spent, and a setting chosen without regard to usage, both need to be looked at again before then.

No source supports changing the model under the one-model rule: Terra reads no better than Sol on the
visual-reasoning benchmark and solves hard problems worse, and Astra is a step up in solving at five
times the rate.

## Sources

All read 2026-11-16.

Official (OpenAI):

- [O1] Models for Work and Codex: https://learn.chatgpt.com/docs/models
- [O2] Model selection: https://learn.chatgpt.com/docs/model-selection
- [O3] Pricing for Work and Codex: https://learn.chatgpt.com/docs/pricing
- [O4] Speed (Fast and Ultrafast): https://learn.chatgpt.com/docs/agent-configuration/speed
- [O5] Image inputs: https://learn.chatgpt.com/docs/image-inputs
- [O6] Configuration reference: https://learn.chatgpt.com/docs/config-file/config-reference
- [O7] What's new: https://learn.chatgpt.com/docs/whats-new
- [O8] API model page, GPT-6.1 Sol: https://developers.openai.com/api/docs/models/gpt-6.1-sol
- [O9] API model page, GPT-6.1 Terra: https://developers.openai.com/api/docs/models/gpt-6.1-terra
- [O10] API model page, GPT-6 Astra: https://developers.openai.com/api/docs/models/gpt-6-astra
- [O11] API model pages, GPT-6 Sol and GPT-6 Luna: https://developers.openai.com/api/docs/models/gpt-6-sol
  and https://developers.openai.com/api/docs/models/gpt-6-luna
- [O12] Reasoning models guide: https://developers.openai.com/api/docs/guides/reasoning
- [O13] Images and vision guide: https://developers.openai.com/api/docs/guides/images-vision
- [O14] Image input token and cost calculator: https://developers.openai.com/api/docs/guides/image-cost-calculator
- [O15] Fast mode guide: https://developers.openai.com/api/docs/guides/fast-mode
- [O16] Latency optimization guide: https://developers.openai.com/api/docs/guides/latency-optimization
- [O17] Using GPT-6: https://developers.openai.com/api/docs/guides/latest-model/gpt-6-astra
- [O18] Introducing GPT-6.1 Sol: https://openai.com/index/introducing-gpt-6-1-sol/
- [O19] Introducing GPT-6.1 Terra: https://openai.com/index/introducing-gpt-6-1-terra/
- [O20] GPT-6 Astra announcement: https://openai.com/index/gpt-6-astra/
- [O21] Help Center, Understanding ChatGPT and Codex usage limits:
  https://help.openai.com/en/articles/20001625-understanding-chatgpt-and-codex-usage-limits

Source code (openai/codex at tag rust-v0.169.0):

- [C1] https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/utils/image/src/lib.rs
- [C2] https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/core/src/image_preparation.rs
- [C3] https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/protocol/src/models.rs
- [C4] https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/exec/src/lib.rs
- [C5] https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/core/src/session/mod.rs
- [C6] https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/features/src/lib.rs
- [C7] https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/tools/src/image_detail.rs
- [C8] https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/core/src/client_common.rs
- [C9] https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/core/src/context_manager/history.rs
- [C10] https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/models-manager/models.json
- [C11] https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/protocol/src/config_types.rs
- [C12] https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/protocol/src/openai_models.rs
- [C13] https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/core/src/tools/handlers/view_image.rs
- [C14] https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/utils/image/src/image_tests.rs
- [C15] https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/models-manager/src/model_info.rs
- [C16] https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/protocol/src/local_media.rs
- Release: https://github.com/openai/codex/releases/tag/rust-v0.169.0

Independent:

- [I1] Artificial Analysis, GPT-6.1 Sol: https://artificialanalysis.ai/models/gpt-6-1-sol
- [I2] Artificial Analysis, GPT-6.1 Terra: https://artificialanalysis.ai/models/gpt-6-1-terra
- [I3] Artificial Analysis, GPT-6 Astra: https://artificialanalysis.ai/models/gpt-6-astra
- [I4] Artificial Analysis, intelligence benchmarking methodology:
  https://artificialanalysis.ai/methodology/intelligence-benchmarking
- [I5] Artificial Analysis, MMMU-Pro: https://artificialanalysis.ai/evaluations/mmmu-pro
- [I6] Roboflow Vision Evals, GPT-6.1 Sol and GPT-6.1 Terra:
  https://playground.roboflow.com/models/compare/gpt-6-1-sol-vs-gpt-6-1-terra
- [I7] Roboflow Vision Evals, GPT-6.1 Sol and GPT-6 Astra:
  https://playground.roboflow.com/models/compare/gpt-6-1-sol-vs-gpt-6-astra
- [I8] MathArena, GPT-6.1 Sol (max): https://matharena.ai/models/openai_gpt_61_sol
- [I9] MathArena, GPT-6 Astra (max) and (low): https://matharena.ai/models/openai_gpt_6_astra and
  https://matharena.ai/models/openai_gpt_6_astra_low
- [I10] Epoch AI, GPT-6.1 Sol: https://epoch.ai/models/gpt-6-1-sol
- [I11] JaWildText, proceedings of the 32nd annual meeting of the Association for Natural Language
  Processing: https://www.anlp.jp/proceedings/annual_meeting/2026/pdf_dir/C2-4.pdf
- [I12] Artificial Analysis, GPT-6 Sol: https://artificialanalysis.ai/models/gpt-6-sol

Tooling note: the Context7 index of openai/codex was queried twice as a cross-check of section 2. It
indexes the main branch and releases up to 0.165.0, and its excerpts agree with the constants read at
the tag. No quota error occurred.
