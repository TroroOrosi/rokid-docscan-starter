# Codex CLI limits, errors, images, updates: primary-source findings

Status: Research record, 2026-11-18. Outside sources only; nothing here was tried against the live service. What was then measured on the phone is in `docs/hardware-measurements.md` §M-44 (19).

Read on 2026-11-18 (every source below was read that day unless a line says otherwise).

How the sources were obtained:

- Documentation: fetched pages of `learn.chatgpt.com` (the Codex docs; `developers.openai.com/codex/pricing`
  serves the same pricing page), `developers.openai.com/api/docs`, `help.openai.com`.
- Source: `git clone --depth 1 --branch rust-v0.170.0 https://github.com/openai/codex` (sparse: `codex-rs`, `docs`);
  `git log -1` printed `29eb79e9866b3262a777fdf8195c1b9e63684c91 2026-11-17T18:28:28-08:00`. File links below are
  `https://github.com/openai/codex/blob/rust-v0.170.0/<path>`; line numbers are from that tag.
- npm: `curl https://registry.npmjs.org/@openai/codex`, `time` field.
- Release notes: `https://api.github.com/repos/openai/codex/releases?per_page=100` (4 pages), stable rust-v0.16x/0.17x only.

Paths such as codex-rs/core/src/x.rs below are paths in openai/codex at that tag, not in this repository; they are written without code font for that reason.

Labels: **documented** (vendor documentation says it), **read in source** (read in the 0.170.0 code),
**inferred** (my arithmetic or reasoning from the two), **not found** (no primary source answered).
Nothing here was tried against the live service. What the service actually returns (status, body, headers) is
outside the client source and is marked not found where it matters.

Doc wording is paraphrased; strings in `code font` are literals copied from the open-source client.

---

## 1. Codex usage limits by ChatGPT plan

**Windows**

- Limits may apply over a five-hour window and a weekly window; where both apply, allowance must remain in both.
  A five-hour window starts with the first Work/Codex message after the previous one ended. **documented**
  https://help.openai.com/en/articles/20001516-managing-usage-with-gpt-6-astra-in-work-and-codex (2026-11-18)
- Pro 100, Pro 200 and Pro 500 currently have no five-hour limit in Work and Codex; they still have an included
  allowance (the weekly window). **documented** same article; also the pricing page, "Included usage" section:
  https://learn.chatgpt.com/docs/pricing (2026-11-18)
- Plus and Business Standard: five-hour window plus "weekly limits may also apply". Estimated local messages per
  five hours for Plus: GPT-6.2 Sol 17-180, GPT-6.1 Sol 15-160, GPT-6.2 Astra 6-50, GPT-6 Luna 350-3,000. The page
  says these are estimates, not fixed message limits. **documented** https://learn.chatgpt.com/docs/pricing (2026-11-18)
- Pro tiers: $100, $200, $500 a month; Pro 200 has more than Pro 100, Pro 500 the most; Pro 100 and Pro 500 were
  recently doubled. No numeric quota is published; an example in the article is explicitly illustrative.
  **documented** https://help.openai.com/en/articles/9793128-about-chatgpt-pro-tiers (2026-11-18)
- Numeric size of the Pro weekly allowance (tokens, credits or messages): **not found**. The docs point to
  Settings -> Usage and `/status` in the CLI.
- The client does not hard-code windows. It reads them from response headers `x-codex-primary-used-percent`,
  `-primary-window-minutes`, `-primary-reset-at` and the `secondary` equivalents. **read in source**
  codex-rs/codex-api/src/rate_limits.rs L68-79.
- Enterprise/Edu with flexible pricing: no fixed rate limits, usage scales with credits; without flexible pricing:
  same per-seat limits as Plus for most features. Free/Go: GPT-6 Luna at Standard speed in the desktop app only.
  **documented** https://learn.chatgpt.com/docs/pricing (2026-11-18)

**How usage is counted**

- Not a fixed number of messages. It depends on model, context size, reasoning, tool use, retrieval, caching and
  speed. **documented** https://learn.chatgpt.com/docs/pricing ; https://help.openai.com/en/articles/9793128-about-chatgpt-pro-tiers
- Beyond the included allowance, credits are charged per million tokens (Standard speed). GPT-6.2 Sol: 50 credits
  input, 2.5 cached input, 250 output (GPT-6.1 Sol the same; GPT-6.2 Astra 200 / 10 / 1,000). No separate cache-write
  charge. **documented** https://learn.chatgpt.com/docs/pricing "Token rates" (2026-11-18)
- Cached input: for credits it costs one twentieth of fresh input on GPT-6.2 Sol (2.5 against 50). For the
  *included* allowance the docs only say caching affects usage; no weight is published. **documented** (credits) /
  **not found** (weight inside the included allowance).
- After the included allowance is exhausted, available credits can be spent automatically; a saved instruction to
  ask first does not add an approval step. **documented**
  https://help.openai.com/en/articles/12642688-using-credits-for-flexible-usage-in-chatgpt-personal-plans (2026-11-18)
- If the limit is reached during an active turn, that turn may continue, subject to fair-use limits. **documented**
  https://learn.chatgpt.com/docs/pricing FAQ (2026-11-18)
- Auto-review safety checks are free with ChatGPT sign-in. **documented**
  https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan (2026-11-18)

**Fast (service tier `priority`)**

- Fast multiplies consumption relative to Standard on the same model. Included usage: GPT-6.2 Sol and GPT-6.2 Astra
  2x; GPT-6.1 Sol, GPT-6.1 Terra, GPT-6 Astra/Sol/Luna 2.5x. Credits/PAYG: 2x for all of them. **documented**
  https://learn.chatgpt.com/docs/pricing "Speed multipliers" (2026-11-18)
- The Pro-tiers Help Center article still states 2.5x for Fast in general, without the GPT-6.2 exception. The two
  pages disagree for GPT-6.2; the pricing page is the one with a per-model table. **documented** (both), the
  reconciliation is **inferred**.
- Ultrafast: 6x included for GPT-6.2 Sol/Astra (Pro $200 has it for GPT-6.2 Sol only, Pro $500 for both).
  **documented** https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex (2026-11-18)
- In the client, `service_tier = "fast"` and `"priority"` are the same thing: both parse to `ServiceTier::Fast`,
  whose request value is `priority`. **read in source** codex-rs/protocol/src/config_types.rs L528-551;
  **documented** in the config reference (`service_tier`): https://learn.chatgpt.com/docs/config-file/config-reference
- The bundled catalog advertises one tier for `gpt-6.2-sol`: id `priority`, name `Fast`. **read in source**
  codex-rs/models-manager/models.json.

**Concurrency**

- A documented per-plan cap on simultaneous requests or sessions: **not found** (pricing page, the Help Center
  articles above, auth and non-interactive docs were searched for "concurrent", "parallel", "rate limit", "429").
- The Pro-tiers article says unlimited access is subject to abuse guardrails and that automated extraction and
  credential sharing are prohibited. **documented** https://help.openai.com/en/articles/9793128-about-chatgpt-pro-tiers
- Not primary evidence, bodies not read: a search listed issues in `openai/codex` whose titles report HTTP 429 with a
  few concurrent sessions (#42685, #54010, #58888). Treat as unverified user reports.

## 2. Shared allowance between Chat, Work and Codex

- Announced: starting in December, the Plus, Pro and Business allowance is shared across ChatGPT and Codex, measured
  in tokens; "Instant chat will not draw from your usage." The article gives no day and no year; it showed
  "Updated: 17 days ago" on 2026-11-18, i.e. about 2026-11-01. **documented**
  https://help.openai.com/en/articles/20001625-understanding-chatgpt-and-codex-usage-limits (2026-11-18)
- At the limit after the change: wait for the reset, upgrade, or buy credits. OpenAI says it expects most users not
  to wait for resets more often than now. **documented** same article.
- What else stays outside after December (GPT-6 Pro messages in Chat, file uploads, image generation, voice):
  **not found** in that article. Only Instant chat is named.
- Today (before the change): Work and Codex already share one allowance and credit pool, together with ChatGPT for
  Excel and Workspace Agents where available. **documented** https://learn.chatgpt.com/docs/pricing ;
  https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan (2026-11-18)
- Today: usage and credit rules of Work and Codex are separate from Chat; GPT-6 Pro message limits in Chat are
  separate from the Work/Codex allowance; ChatGPT file-upload, image and voice limits do not apply to Codex.
  **documented** https://help.openai.com/en/articles/20001354-gpt-6-and-other-models-in-chatgpt ;
  https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan (2026-11-18)
- API-key sessions use API pricing and never the ChatGPT allowance. **documented** https://learn.chatgpt.com/docs/pricing

## 3. What the CLI does at a usage limit and at HTTP 429

All **read in source** at `rust-v0.170.0` unless marked.

**Two retry layers**

- Request layer (`run_with_retry`): `max_attempts = request_max_retries`, base delay 200 ms doubling with 10% jitter,
  `retry_429: false`, `retry_5xx: true`, `retry_transport: true`. An HTTP 429 is never retried here.
  codex-rs/model-provider-info/src/lib.rs L501-507; codex-rs/codex-client/src/retry.rs L22-41, L84-118.
- Turn layer (`handle_response_stream_error`): up to `stream_max_retries` retries of the whole sampling request, only
  for errors whose policy allows it; a server `Retry-After` sets the wait but does not add attempts.
  codex-rs/core/src/responses_retry.rs L88-181; codex-rs/core/src/session/turn.rs L1921.
- Defaults: `request_max_retries` 4, `stream_max_retries` 5, `stream_idle_timeout_ms` 300000; hard caps 100 and 100.
  codex-rs/model-provider-info/src/lib.rs L73-82. **documented** with the same defaults:
  https://learn.chatgpt.com/docs/config-file/config-reference (`model_providers.<id>.*`).
- These keys live under `[model_providers.<id>]`, and the docs say a built-in provider id cannot be overridden (no
  `[model_providers.openai]`). So with plain ChatGPT sign-in they are not tunable without defining a custom provider.
  **documented** https://learn.chatgpt.com/docs/config-file/config-advanced ("Azure provider and per-provider tuning").
  Whether a custom provider with `requires_openai_auth = true` behaves identically for ChatGPT sign-in: not checked.
- Local backoff when the server gives no delay: 200 ms, doubling, +-10% (0.2, 0.4, 0.8, 1.6, 3.2 s for retries 1-5,
  about 6 s in all). codex-rs/async-utils/src/backoff.rs L7-17.

**(a) Plan usage limit**

- Recognised as HTTP 429 whose JSON body has `error.type == "usage_limit_reached"` (also when the same payload
  arrives wrapped over WebSocket). The body's `plan_type`, `resets_at`, `limit_window_minutes` and the rate-limit
  headers are kept. codex-rs/codex-api/src/api_bridge.rs L225-257.
- Never retried: the turn loop returns at once, and the error's retry policy is `Never`.
  codex-rs/core/src/session/turn.rs L2032-2038; codex-rs/protocol/src/error.rs L471-514.
- Message for plan `pro` / `prolite` / `promax` (the apostrophe is U+2019):
  `You’ve hit your usage limit. Visit https://chatgpt.com/settings/usage to purchase more credits or try again at <time>.`
  Without a reset time the tail is ` or try again later.` The time is local, `%-I:%M %p` the same day, otherwise
  `%b %-d<suffix>, %Y %-I:%M %p`. codex-rs/protocol/src/error.rs L848-999.
- Variants: Plus adds an "Upgrade to Pro" clause; Free/Go "Upgrade to Plus"; unknown plan
  `You’ve hit your usage limit. Try again at <time>.`; a limit named other than `codex`/`gpt-reserve`
  `You’ve hit your usage limit for <limit_name>. Switch to another model now, or try again at <time>.`; workspace
  credit cases start `Your workspace is out of credits.` or `You hit your spend cap`. Same lines.
- Sibling 429 bodies: `usage_not_included` -> `To use Codex with your ChatGPT plan, upgrade to Plus: ...`;
  `insufficient_quota`, `credit_balance_exhausted`, `organization_spend_limit_exceeded`, `project_spend_limit_exceeded`,
  `organization_usage_limit_exceeded` -> `Quota exceeded. Check your plan and billing details.` Neither is retried.
  `api_bridge.rs` L258-273; `error.rs` L223-228, L487-488.
- Which of `pro` / `prolite` / `promax` corresponds to $100 / $200 / $500: **not found** in the source read.

**(b) HTTP 429 that is not a usage limit (too many requests)**

- Any other 429 becomes `RetryLimit`, displayed as
  `exceeded retry limit, last status: 429 Too Many Requests` plus `, request id: <id>` when an `x-request-id`,
  `x-oai-request-id` or `cf-ray` header exists. `api_bridge.rs` L276-279, L356-358; `error.rs` L818-835.
- Its policy is `ServerDirected`: it is retried only if the response carried `Retry-After` (seconds or HTTP date),
  sleeping until that deadline, at most `stream_max_retries` times. With no `Retry-After` the turn fails on the
  first 429, despite the wording "exceeded retry limit". `error.rs` L460-469, L515-517;
  codex-rs/http-client/src/retry_after.rs L19-39.
- A rate limit reported inside the stream (`response.failed` with code `rate_limit_exceeded` or `slow_down`, or HTTP
  503 with `slow_down`) becomes `rate limit exceeded: <server message>`. Policy `Backoff`: retried up to
  `stream_max_retries`, waiting for the error's `retry-after` header, else a delay parsed from "try again in N s/ms"
  in the message, else the local backoff. codex-rs/codex-api/src/sse/responses_error.rs L92-99, L107-145;
  `api_bridge.rs` L145-161; `error.rs` L134-136, L519-531.
- Overload is separate: `Selected model is at capacity. Please try a different model.` (`server_is_overloaded`),
  retried only with server advice. `error.rs` L203-204, L515-517.
- Which of these the ChatGPT backend sends when one account runs several requests at once, and whether it sends
  `Retry-After`: **not found** (server behaviour, not in the client).

**What `codex exec` prints, and telling the cases apart**

- Human mode, stderr: `ERROR: <message>` for an error notification and again for a failed turn.
  codex-rs/exec/src/event_processor_with_human_output.rs L254-261, L328-336.
- `--json`, stdout: `{"type":"error","message":"..."}` and, when the turn fails,
  `{"type":"turn.failed","error":{"message":"..."}}`. The event carries `message` only.
  codex-rs/exec/src/exec_events.rs L13-36, L90-94; `event_processor_with_jsonl_output.rs` L450-461, L541-560.
- While retrying, the same `error` event type is emitted with `message` = `Reconnecting... <n>/<max>` and, in JSON
  mode, the underlying error appended in parentheses, e.g. `Reconnecting... 2/5 (rate limit exceeded: ...)`. It is
  not fatal (`will_retry: true`). In release builds the first retry notice is suppressed when WebSockets are on.
  codex-rs/core/src/responses_retry.rs L146-171; codex-rs/core/src/session/mod.rs L5991-6007;
  codex-rs/app-server/src/bespoke_event_handling.rs L1083-1100.
- Exit status 1 after a non-retrying error notification for the turn, or a failed or interrupted turn.
  codex-rs/exec/src/lib.rs L1422-1439, L1484-1486.
- The app-server protocol has a structured category (`usageLimitExceeded`, `rateLimitExceeded`,
  `responseTooManyFailedAttempts` with the HTTP status), but exec's JSONL drops it. `error.rs` L564-611.
- So: the two cases can be told apart, by message text only. `You’ve hit your usage limit` (or the workspace/quota
  sentences) = plan allowance; `exceeded retry limit, last status: 429` or `rate limit exceeded:` = request-rate
  429. No stable machine-readable code reaches stderr or `--json`. **inferred** from the lines above.

## 4. Image inputs

**Service limits (Responses API guide)**

- Up to 1,500 images per request; up to 512 MB total payload per request; PNG, JPEG, WEBP, non-animated GIF.
  **documented** https://developers.openai.com/api/docs/guides/images-vision "Image input requirements" (2026-11-18)
- Per image: at most 30,000 patches of 32 px after the model's resizing rules; above that the request is rejected,
  not resized. A per-image byte limit is not stated. **documented** same section.
- Patch count is `ceil(w/32) x ceil(h/32)`; billable tokens = patches x a per-model multiplier (1.2 for the models
  the table lists). **documented** same page, "Patch-based image tokenization".
- The model sizing table and the multiplier table list `gpt-6-astra`, `gpt-5.6-*`, `gpt-5.5` and older; rows for
  `gpt-6.2-sol` / `gpt-6.1-sol`: **not found**. For `gpt-5.5` the table gives `original` = 10,000 patches and
  6000 px, the same pair the Codex client applies (below).
- Whether the ChatGPT-sign-in endpoint (`https://chatgpt.com/backend-api/codex`) has the same count and size limits
  as the public API: **not found**.

**What the Codex CLI does to `-i` images (read in source)**

- `codex exec -i` creates `UserInput::LocalImage { path, detail: None }`. codex-rs/exec/src/lib.rs L1007, L1030, L1058.
- In a session the file bytes are deferred (`LocalImagePreparation::Defer`) and prepared centrally.
  codex-rs/core/src/session/mod.rs L4004-4008; codex-rs/protocol/src/models.rs L2324-2343.
- Mode: `UnifiedBudget` when feature `unified_image_budget` is on (stable, default on) and the model has
  `use_responses_lite` or `supports_image_detail_original`; otherwise `DetailBased`.
  codex-rs/core/src/image_preparation.rs L47-53; codex-rs/core/src/session/mod.rs L3957-3962;
  codex-rs/features/src/lib.rs L2035-2040.
- `UnifiedBudget` applies one limit to every image whatever its detail hint: longest side at most 6000 px and at
  most 10,000 patches of 32 px. `DetailBased` with no detail (treated as high): 2048 px and 2,500 patches.
  **This confirms the 6000 px / 10,000 patch belief, conditional on the model's catalog entry.**
  codex-rs/utils/image/src/lib.rs L24, L73-84; `image_preparation.rs` L405-420.
- The bundled catalog entry for `gpt-6.2-sol` has `supports_image_detail_original: true` and
  `use_responses_lite: true` (so does `gpt-6.1-sol`), hence `UnifiedBudget`. codex-rs/models-manager/models.json.
  A catalog fetched from the service replaces the bundled one for ChatGPT sign-in; its values were not read.
- Resize arithmetic: scale to the max dimension first, then if still over the patch budget scale by
  `sqrt(32*32*max_patches/(w*h))` and floor so the patch grid fits. Filter `Triangle`, aspect kept, never enlarged.
  utils/image/src/lib.rs L160-179, L308-352.
- An image within the limits that is PNG, JPEG or WebP is sent byte-for-byte (no re-encode). A resized one is
  re-encoded in its own format. utils/image/src/lib.rs L181-218, L354-361.
- A resized user image can be announced to the model with its dimensions if feature `image_resize_notice` is on.
  core/src/session/mod.rs L3963-3971.
- Client sanity cap: 1 GiB per image input (`MAX_PROMPT_IMAGE_INPUT_BYTES`), described in the source as a guard,
  not a protocol limit. utils/image/src/lib.rs L27-31. A client-side cap on the number of images: none found
  (searched `core`, `protocol`, `exec`, `codex-api`).
- Images travel inline as base64 data URLs: the default store is `InlineAttachmentStore`.
  codex-rs/core/src/thread_manager.rs L619; codex-rs/attachment-store/src/lib.rs L192-198.
- `gpt-6.2-sol` prefers WebSockets. The server advertises a maximum message size in header
  `x-codex-websocket-max-message-bytes`; a larger request falls back to HTTPS. 0.170.0's notes say oversized
  WebSocket requests now fall back to HTTP without unnecessary retries. The size itself: **not found**.
  codex-rs/codex-api/src/endpoint/responses_websocket.rs L209, L1048, L1113-1116;
  https://github.com/openai/codex/releases/tag/rust-v0.170.0
- An undecodable or oversized image is not fatal: it is replaced by a text placeholder such as
  `image content omitted because it could not be processed`. `image_preparation.rs` L33-39, L288-295.
- `-i` is declared with `value_delimiter = ','` and `num_args = 1..`: a comma inside a path splits it.
  codex-rs/utils/cli/src/shared_options.rs L12-19.
- Default context in Codex for GPT-6.2 Sol is 500,000 tokens; up to 1 million via `model_context_window`.
  **documented** https://learn.chatgpt.com/docs/models (2026-11-18). The bundled entry has `context_window` 500000,
  `max_context_window` 872000 (read in source); the two maxima differ and were not reconciled.
- **Inferred**: with 50-250 images the binding limit is the context window, not the 1,500-image or 512 MB limit.
  Example: 690 x 2540 px = 22 x 80 = 1,760 patches; 250 such images are 440,000 patches before any multiplier
  (the multiplier for GPT-6.2 Sol is not published).

## 5. How the CLI learns of new versions and models

**Versions**

- Update check lives in the interactive TUI: if `check_for_update_on_startup` is true (default) and the cached check
  is older than 20 hours, a background task asks `https://api.github.com/repos/openai/codex/releases/latest` (Homebrew
  cask API for brew installs; npm installs also confirm the npm package is ready) and writes the result to a version
  file; the banner shows on the next start. **read in source** codex-rs/tui/src/updates.rs L27-62, L84-116.
- It notifies; it does not update by itself. The prompt offers update now / not now / do not remind, and only
  "update now" runs e.g. `npm install -g @openai/codex`. There is also `codex update`. **read in source**
  codex-rs/tui/src/update_prompt.rs L90-105; codex-rs/tui/src/update_action.rs; codex-rs/cli/src/main.rs
  L805-906. **documented**: https://learn.chatgpt.com/docs/developer-commands (`codex update`);
  https://learn.chatgpt.com/docs/config-file/config-reference (`check_for_update_on_startup`).
- `codex exec` contains no update check (no reference to the updater in `codex-rs/exec/src`). A CLI used only
  through `codex exec` is never told about a new version. **read in source** (absence).
- A managed app-server daemon has its own optional auto-update (`auto_update_enabled`); not part of `codex exec`.
  **read in source** codex-rs/app-server-daemon/src/lib.rs L135, L520.

**Models**

- Cache file `$CODEX_HOME/models_cache.json`, TTL 300 s. An entry is used only if its `client_version` equals the
  running version (major.minor.patch), its identity matches the current provider/auth, and it is fresh.
  **read in source** codex-rs/models-manager/src/manager.rs L41-42, L1007-1058; `cache.rs` L200-243.
- Refresh: at session start with strategy `OnlineIfUncached` (cache if fresh, else fetch); whenever a model response
  carries an `X-Models-Etag` different from the cached one (same ETag only renews the TTL); and an app-server worker
  refetches every 4 min 30 s. **read in source** core/src/session/mod.rs L631; core/src/session/turn.rs
  L3524-3529; `manager.rs` L739-765, L780-829; codex-rs/app-server/src/models_refresh_worker.rs L10. Whether that
  worker runs inside `codex exec`'s in-process server was not traced.
- Endpoint: `GET <base_url>/models?client_version=<x.y.z>`; with ChatGPT sign-in the base URL is
  `https://chatgpt.com/backend-api/codex`. The client sends its version, so the list can depend on it; the filtering
  itself is server-side. **read in source** codex-rs/codex-api/src/endpoint/models.rs L33-46;
  codex-rs/models-manager/src/lib.rs L24-31; codex-rs/model-provider-info/src/lib.rs L87.
- With ChatGPT sign-in, a fetched catalog that has at least one `visibility: list` model replaces the bundled list
  (no merge); otherwise fetched entries are merged over the bundled `models.json`. A failed fetch keeps the last
  good snapshot. **read in source** `manager.rs` L848-851, L979-1001.
- `minimal_client_version` exists in the JSON (bundled `gpt-6.2-sol`: `0.166.0`) but no client code reads it; it
  can only act server-side. **read in source** (grep: test fixtures only).
- `priority`: integer sort key, ascending; lower comes first in the picker. Bundled order: `gpt-6.2-sol` 1,
  `gpt-6.2-astra` 2, `gpt-6.1-terra` 3, `gpt-6.1-sol` 4, `gpt-6-astra` 5, `gpt-6-sol` 6, `gpt-6-luna` 7.
  **read in source** `manager.rs` L264-276; protocol/src/openai_models.rs L443; `models.json`.
- `visibility`: `list` (shown in the picker), `hide`, `none`. Only `list` models count as picker-visible.
  **read in source** protocol/src/openai_models.rs L301-311, L1113.
- "Newest model without naming it": omit `model` and `-m`. The default is then the first picker-visible model after
  sorting by `priority`, i.e. whatever the catalog ranks first for this client version. **read in source**
  `manager.rs` L297-321, L1161-1168; `openai_models.rs` L1163-1174. **documented** only as: without a model the CLI
  uses a recommended model (https://learn.chatgpt.com/docs/models, "Configure your default local model").
  An alias such as "latest": **not found**. Model slugs are also matched by longest prefix (`manager.rs` L1181-1196).
- The Help Center tells CLI users to update the CLI to get GPT-6.2. **documented**
  https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex (2026-11-18)
- `model_catalog_json` points the CLI at a local catalog file loaded at startup. **documented**
  https://learn.chatgpt.com/docs/config-file/config-reference

## 6. Release cadence and `codex exec` flag changes

Stable versions of `@openai/codex`, publish time from the npm registry `time` field (UTC):

| Version | Published | Version | Published |
| --- | --- | --- | --- |
| 0.160.0 | 2026-10-01 | 0.166.0 | 2026-10-29 |
| 0.160.1 | 2026-10-05 | 0.167.0 | 2026-11-06 |
| 0.161.0 | 2026-10-07 | 0.167.1 | 2026-11-10 |
| 0.162.0 | 2026-10-08 | 0.167.2 | 2026-11-11 |
| 0.162.1 | 2026-10-09 | 0.168.0 | 2026-11-13 |
| 0.163.0 | 2026-10-15 | 0.169.0 | 2026-11-13 |
| 0.164.0 | 2026-10-23 | 0.169.1 | 2026-11-17 |
| 0.165.0 | 2026-10-27 | 0.170.0 | 2026-11-18 03:45 |

- 16 stable releases in 48 days; 10 minor steps (0.160 -> 0.170), one about every 5 days, gaps of 0 to 8 days
  (0.168.0 and 0.169.0 less than 5 hours apart). The two months before were denser: 0.150.0 (2026-08-26) to
  0.159.3 (2026-09-30). `latest` = 0.170.0, `alpha` = 0.171.0-alpha.13. **documented** (registry)
  https://registry.npmjs.org/@openai/codex (2026-11-18)
- Release notes 0.160.0 to 0.170.0, keyword scan of every stable body (exec, the flag names, breaking, removed,
  no longer, deprecated, renamed), not a full read: no note removes or renames `-m`, `-c`, `-i`, `-s`,
  `--skip-git-repo-check`, `--ephemeral`, `--output-schema` or `-o`. **documented**
  https://github.com/openai/codex/releases (2026-11-18)
- All eight still exist in the 0.170.0 source (`--model/-m`, `--config/-c`, `--image/-i`, `--sandbox/-s`,
  `--skip-git-repo-check`, `--ephemeral`, `--output-schema`, `--output-last-message/-o`), plus `--json`.
  **read in source** codex-rs/exec/src/cli.rs L37-84; codex-rs/utils/cli/src/shared_options.rs;
  codex-rs/utils/cli/src/config_override.rs L30-31.
- Changes in that range that touch `codex exec` behaviour:
  - 0.169.0: project configuration and project MCP servers stay disabled in untrusted directories even with
    `--sandbox workspace-write`; new `--trust`. https://github.com/openai/codex/releases/tag/rust-v0.169.0
  - 0.170.0: oversized WebSocket requests fall back to HTTP at once. https://github.com/openai/codex/releases/tag/rust-v0.170.0
  - 0.161.0 / 0.162.0: retries and WebSocket fallback honour server `Retry-After`. Same releases page.
  - 0.165.0: no more retrying when the provider says the model was not found. Same releases page.
  - 0.161.0: new `codex exec --cyber-access-program`; 0.163.0: exec no longer reprints an unchanged diff.
- Outside the scanned range but current in the docs: `--full-auto` is no longer supported (use
  `--sandbox workspace-write` or `--approve-for-me`); `approval_policy = "untrusted"` stops the CLI from starting
  since 0.149.0. **documented** https://learn.chatgpt.com/docs/non-interactive-mode ;
  https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan (2026-11-18)
- 0.169.1's notes contain no highlights, and 0.170.0's highlights do not mention GPT-6.2, although the 0.170.0
  bundled catalog contains `gpt-6.2-sol`. Which release first bundled it: not determined.

## Not verified

- Any behaviour of the live service: the real status, body and headers of a concurrency 429 on a ChatGPT plan;
  whether `Retry-After` is sent; the WebSocket message-size limit; the image count and payload limits of the
  ChatGPT-sign-in endpoint.
- The numeric Pro allowance and the weight of cached input inside the included allowance.
- The remote model catalog as served to 0.170.0 for this account (only the bundled `models.json` was read).
- One Help Center page (20001516) returned HTTP 403 twice before a third fetch succeeded; its content above is
  from that third fetch.
