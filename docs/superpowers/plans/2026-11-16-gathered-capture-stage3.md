# 撮影の作り直し・段階3：録画で撮る経路をアプリとサーバーに入れる Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Status: 計画（2026-11-16）。段階2（§M-27〜§M-29）で決まった形の実装。本人の了承（要旨）：撮り方の変更を承認（11/15 夜）。介入が必要な実機テストが可能になるまで全て許可（11/15 23:58）。

**Goal:** 通常の読取で、グラスが 1 頁ごとに「視野の中央を拡大率 2 で録った短い録画」を残し、スマホがそれを重ねて頁の画像にし、今の解答の経路へ渡す。机上の検査（代役の解答器）まで。

**Architecture:** 今の「1頁＝写真1枚」の流れ（3秒確認、未送信の保存、送信、受領、再起動後の復旧）は変えない。録画用のカメラ `ClipCamera` を新しく作り（静止画の `GlassCamera` はそのまま残す）、録画の 1 フレームを JPEG の「仮の頁」として今の流れに乗せる。録画（MP4）と添えた記録は、その頁に付く追加の原本として別の口で送り、スマホの重ね合わせの係が頁の画像を置き換える。重ね合わせが失敗しても、頁は仮の頁のまま残る。

**Tech Stack:** Java 17／Android（camera2、MediaCodec、MediaMuxer。`:glassdoc`・`:relaycore`、Robolectric の単体試験）、Python 3.12（FastAPI、SQLite、numpy、ffmpeg。`app/`、pytest）。新しい依存は無い（numpy と ffmpeg はスマホに導入済み。§M-26）。

**Spec:** `docs/superpowers/specs/2026-11-15-gathered-capture-design.md`（6 章が設計、4 章が測定値）。測定は `docs/hardware-measurements.md` §M-27〜§M-29。

## Global Constraints

- カメラの出力は 2016×1512 の YUV 1本、`SCALER_CROP_REGION`＝センサーの中央の 2016×1512（拡大率 2）。録画用の出力・原寸の出力は置かない。
- 手動露光 30 ms（`flicker=60` の指定がある時は 25 ms）、ISO 800、デジタルの増幅は「直前のプレビューの自動露光と同じ明るさになる値」で **100〜500 の範囲に切る**（5.0 倍まで）。雑音除去・輪郭強調は切。`TONEMAP_MODE` は指定しない（指定するとエラーで止まる）。
- エンコーダーは HEVC、`COLOR_FormatYUV420Flexible`、指定 95 Mbit/s（実測 約 1.35 bit）、キーフレーム間隔 1 秒。色の面は灰色（128）。
- **セッションの切り替えは必ず「`stopRepeating()` → そのセッションの `onReady` → `createCaptureSession()`」**（1.5 秒で打ち切り）。待たずに切り替えると 16〜28 頁でカメラが空にならず失敗する（§M-29）。
- **カメラの画像の受け取りは、カメラの切り替えのスレッドと別のスレッド。** 録っていない間も受け取って閉じる。エンコーダーの出力の取り出しとファイルへの書き込みは、録画ごとの書き込みスレッド。カメラのスレッドとフレームのスレッドは、ファイルを待たない。
- 目標の枚数の初期値 60（最初の 6 枚は数えず、使わない）。上限 10 秒。最短 1 秒。
- 仮の頁は、録った中の 1 フレームの JPEG（2016×1512、灰色、品質 90）。由来の種類は `clip_frame`。JPEG の上限 20 MiB は変えない。
- 録画の上限は 1 本 192 MiB。グラスは、サーバーが受領を返すまで録画を消さない。
- 合同英語・リスニングの撮影、凍結した比較用の起動（ZSL、比較用の録画、追加の原寸撮影）は変えない。`GlassCamera` の挙動は変えない。
- プライバシー表示に触れない。表示に案内の文字を足さない。消音のまま。
- 版：`APP_VERSION` 0.77.0、`API_VERSION` 1.47.0、`GLASSES_VIEW_CONTRACT_VERSION` は表示の意味が変わる Task 6 で上げる。glassdoc の版は 0.44.0。
- 既定は今の静止画の撮り方のまま。録画の経路は起動時の指定 `capture=clip` で保存して選ぶ。机上の検査が通るまで既定を変えない。
- 検証：`py -3.12 -m pytest -q tests`、`py -3.12 -m ruff check .`、`./android-relay/gradlew --no-daemon test testDebugUnitTest assembleDebug`（JDK と SDK は `CLAUDE.md` のとおり）。ビルドと単体試験は実機の確認ではない。

## Review Focus

1. 録画の送信の途中でアプリが落ちる／畳まれる：再起動後、未送信の録画が残っていて送り直され、同じ頁に二重に付かない。→ Task 4、Task 2
2. 重ね合わせが失敗する／numpy が無い／ffmpeg が無い：頁は仮の頁のまま残り、冊子の確定は止まらず、答案の束にその頁の印が出る。→ Task 3
3. 取り直し（前スワイプ）・捨てた撮影の録画が、次の頁に付かない／残り続けない。→ Task 4
4. 録っている間のタップ（休止）・終了・畳み：カメラが固まらない（切り替えは `onReady` の後）。録画のファイルが閉じられる。→ Task 5
5. サーバーへ録画が届く前に冊子の確定が呼ばれる：確定は重ね合わせの未了を上限つきで待ち、上限を越えたら済んだ頁だけで進む。→ Task 3

---

### Task 1: サーバー：頁に付く録画の受け口と保存

**Files:**
- Create: app/page_clips.py、tests/test_page_clips.py
- Modify: `app/db.py`（表 `page_clips` を足す）、`app/main.py`（口を足す）、`app/capture_provenance.py`（由来の種類 `clip_frame`）、`app/version.py`、`tests/test_versioning.py`、`README.md`（版の行）

**Interfaces:**
- Produces:
  - 表 `page_clips(document_id INTEGER, page_index INTEGER, capture_id TEXT, sha256 TEXT, bytes INTEGER, record_json TEXT, status TEXT, reason TEXT, used INTEGER, total INTEGER, level REAL, created_at REAL, updated_at REAL, PRIMARY KEY(document_id, page_index))`。`status` は `stored`／`gathering`／`done`／`failed`。
  - `POST /v1/documents/{document_id}/pages/{page_index}/clip`（multipart：`clip`＝`video/mp4`、`record`＝JSON、`capture_id`、`sha256`）。返り値 `{"status": "stored"|"done"|"failed"|"gathering", "sha256": ..., "bytes": ...}`、新規 201・同じ `sha256` の再送 200。
    - 頁（`document_id`, `page_index`）が無い → 404。文書が `open` でない → 409。その頁の由来の `capture_id` と違う → 409。`sha256`・大きさが本体と違う → 400。192 MiB 超 → 413。`ftyp` で始まらない → 400。
    - 本体は一時ファイルへ流して書き、検証の後に `DATA_DIR/page-clips/{document_id}/{page_index}/{sha256}.mp4` へ上書きなしで移す。同じ頁に違う `sha256` が来たら（取り直し）、行を置き換えて `stored` に戻し、古いファイルを消す。
  - app/page_clips.py：`store_clip(document_id, page_index, capture_id, sha256, record_text, stream) -> dict`、`pending(document_id) -> int`（`stored` と `gathering` の数）、`rows(document_id) -> list[dict]`、`claim() -> dict | None`（最も古い `stored` を `gathering` にして返す）、`finish(document_id, page_index, sha256, *, used, total, level)`、`fail(document_id, page_index, sha256, reason)`、`requeue_interrupted()`（起動時に `gathering` を `stored` へ）。
  - `GET /v1/documents/{document_id}/clips` → `{"clips": [{"page_index", "status", "reason", "used", "total", "level", "bytes"}]}`（検査用）。
  - `capture_provenance` は `source_kind` に `clip_frame` を受け入れる（16 個の鍵は同じ）。

- [ ] **Step 1: 試験を書く**（tests/test_page_clips.py。既存の `tests/test_native_capture_upload.py` の作り方に合わせ、`TestClient` と一時の `ROKID_DATA_DIR` を使う）
  - `test_a_clip_is_stored_beside_its_page`：頁を由来つき（`clip_frame`）で登録 → 録画を送る → 201、`status == "stored"`、ファイルの sha256 が一致、`GET .../clips` に 1 行。
  - `test_the_same_clip_again_is_a_replay`：同じものを 2 度 → 2 度目は 200、ファイルは 1 つ。
  - `test_a_retake_replaces_the_clip`：頁を別の由来で置き換え、別の録画を送る → 行の `sha256` が新しく、古いファイルは無い、`status == "stored"`。
  - `test_a_clip_of_another_capture_is_refused`：`capture_id` が頁の由来と違う → 409、ファイルは残らない。
  - `test_a_clip_without_its_page_is_refused` → 404。`test_a_clip_after_the_booklet_is_ready_is_refused` → 409。
  - `test_a_damaged_clip_is_refused`：`sha256` 不一致 → 400、`ftyp` なし → 400、どちらも一時ファイルが残らない。
  - `test_clip_frame_is_a_capture_kind`：`clip_frame` の由来で頁を登録できる。未知の種類は今までどおり 400。
- [ ] **Step 2: 失敗を確かめる** — `py -3.12 -m pytest -q tests/test_page_clips.py` → 404（口が無い）で落ちる。
- [ ] **Step 3: 書く**。流して書く所は `app/capture_video_upload.py` の受け取り（大きさと SHA-256 を数えながら一時ファイルへ）と同じ作りにする。`app/db.py` の表は `CREATE TABLE IF NOT EXISTS`。版を上げる。
- [ ] **Step 4:** `py -3.12 -m pytest -q tests/test_page_clips.py tests/test_versioning.py tests/test_native_capture_upload.py tests/test_documentation_contract.py` → 全部通る。
- [ ] **Step 5: Commit** — `feat(server): a page takes the clip it was cut from`

### Task 2: サーバー：重ね合わせの係と、頁の画像の置き換え

**Files:**
- Create: app/page_gather.py、tests/test_page_gather.py
- Modify: `app/main.py`（`lifespan` で係を始めて止める。置き換えの関数）、`app/gather.py`（必要なら頁の画像にする小さな関数）

**Interfaces:**
- Consumes: Task 1 の `claim`／`finish`／`fail`／`requeue_interrupted`、`app.gather.gather_clip(path, record, settle=6)`。
- Produces:
  - app/page_gather.py：`class GatherService`（`start()`、`stop()`、`wake()`。係のスレッド `ROKID_GATHER_WORKERS` 本、既定 3）。`app/capture_inspection.py` の `InspectionService` と同じ作り（起こす合図と止める合図）。numpy と `app.gather` は係の中で初めて読み込む（サーバーは numpy 無しでも起動する）。
  - `page_image(gathered, rotation_degrees) -> bytes`：重ねた画像（float32 の光）を、明るい側 0.5% を白にして 8 ビットにし、指定の向きへ回して RGB の PNG にする（今の `scripts/gather_stage2.py` の `shown` と同じ変換）。
  - `replace_page_image(document_id, page_index, png_bytes, note: dict) -> bool`（`app/main.py`）：その頁の正本の PNG を置き換える。`add_page` が使っている `_prepare_page_image`／`_write_page_files` と同じ道具で書き、`pages` の行を `BEGIN IMMEDIATE` の中で更新し、古い PNG を消す。仮の頁の JPEG と由来の記録は残す。`capture_metadata_json` に `gathered`（`used`、`total`、`level_over_noise`、`clip_sha256`）を足す。文書が `open` でない時は置き換えず `False`。
  - 失敗の理由：`"numpy unavailable"`、`"ffmpeg unavailable"`、`"not placed"`（`placed` が偽）、`"too dark"`（`level_over_noise < 8`）、`"gather error: ..."`、`"timeout"`（1 本 180 秒）。
- [ ] **Step 1: 試験を書く**（tests/test_page_gather.py。録画は `tests/test_gather.py` と同じく生成した場面を ffmpeg で作る。numpy か ffmpeg が無い環境では skip）
  - `test_a_stored_clip_becomes_the_page`：頁（灰色 1 フレームの JPEG）＋録画を登録 → 係を 1 回まわす → 行が `done`、頁の PNG が変わっている（ハッシュが仮の頁と違う）、`used > 0`、`capture_metadata_json` に `gathered`。
  - `test_a_clip_that_cannot_be_placed_leaves_the_page`：模様の無い録画 → `failed`、理由 `not placed`、頁の PNG は元のまま。
  - `test_without_numpy_the_page_stays`：`app.page_gather` の読み込み口を差し替えて ImportError → `failed`、理由 `numpy unavailable`。
  - `test_interrupted_work_is_taken_up_again`：行を `gathering` にしてから `requeue_interrupted()` → `stored`。
  - `test_the_page_image_is_upright`：横倒しの場面を回転 270 で頁にする → PNG の向きが正立（幅 < 高さ）。
- [ ] **Step 2: 失敗を確かめる** — `ModuleNotFoundError: app.page_gather`。
- [ ] **Step 3: 書く**。係は `claim()` が `None` の間は合図を待つ。1 本ごとに try で包み、どんな失敗も `fail()` に理由を残して次へ進む。`gather_clip` は別プロセスにしない（スレッド。numpy は GIL を放す）。
- [ ] **Step 4:** `py -3.12 -m pytest -q tests/test_page_gather.py tests/test_page_clips.py tests/test_gather.py tests/test_photo_pipeline.py tests/test_page_upload_offloaded.py` → 全部通る。
- [ ] **Step 5: Commit** — `feat(server): gather a page's clip into its image`

### Task 3: サーバー：冊子の確定は重ね合わせを待つ。済まなかった頁を答案の束に出す

**Files:**
- Modify: `app/main.py`（`_finalize_document_once` の先頭、`_answer_snapshot`）、tests/test_page_gather.py

**Interfaces:**
- Consumes: Task 1 の `pending(document_id)`・`rows(document_id)`。
- Produces:
  - `_finalize_document_once` は、頁を読む前に、その文書の `pending` が 0 になるのを `ROKID_GATHER_WAIT_S` 秒（既定 150）まで待つ（0.5 秒おき）。越えたら待つのをやめて進む。待った秒数を記録に残す。
  - `_answer_snapshot` は、`status` が `failed` か、確定の時点で `done` でなかった録画つきの頁ごとに、束の末尾へ `status: "needs_review"`・`answer: ""`・`issue: "{n}頁目は重ねられませんでした（1枚の画像で解析）。必要なら録り直してください"` の項目を足す（`n` は 1 始まり）。今のアプリはこの形の項目を表示できる（`AnswerItem` の検証：`answer` が空、`issue` は 1000 文字以内）。
- [ ] **Step 1: 試験を足す**
  - `test_finalize_waits_for_the_gathering`：録画を登録して係を止めたまま確定を呼ぶスレッドを始め、0.3 秒後に係を 1 回まわす → 確定は成功し、頁は重ねた画像。
  - `test_finalize_goes_on_after_the_limit`：`ROKID_GATHER_WAIT_S=1` で係を動かさず確定 → 成功（仮の頁のまま）、所要 1〜3 秒。
  - `test_a_page_that_was_not_gathered_is_named_in_the_answers`：失敗した録画つきの頁がある冊子を代役の解答器（`ROKID_SOLVER=recorded`）で解く → 束に `needs_review` の項目があり、`issue` に頁番号。
- [ ] **Step 2: 失敗を確かめる**。
- [ ] **Step 3: 書く**。
- [ ] **Step 4:** `py -3.12 -m pytest -q tests` → 全部通る（数を報告）。`py -3.12 -m ruff check .` → `All checks passed!`。
- [ ] **Step 5: Commit** — `feat(server): the booklet waits for its clips and names the pages that were not gathered`

### Task 4: アプリ（`:relaycore`）：録画を頁に添えて保存し、送る

**Files:**
- Create: android-relay/relaycore/src/main/java/dev/rokid/docscanrelay/ClipInbox.java、.../src/test/java/dev/rokid/docscanrelay/ClipInboxTest.java
- Modify: .../LocalCaptureSession.java、.../DocScanApi.java、.../DocScanController.java（`commitLocalPhoto`、`queueLocalUpload`）、.../CaptureProvenance.java（`clip_frame`）、対応する試験（`LocalReviewTest.java`、`DocScanApiTest` に相当するもの）

**Interfaces:**
- Produces:
  - `final class ClipInbox`：`ClipInbox(File directory)`（`<filesDir>/clip-inbox`）。`File reserve(String captureId)`（`<captureId>.mp4` の置き場を返す）、`void offer(String captureId, byte[] recordJson) throws IOException`（録画が閉じられた後に呼ぶ。`<captureId>.json` を書く）、`boolean has(String captureId)`、`void discardExcept(java.util.Set<String> captureIds)`（それ以外の録画と記録を消す）。
  - `LocalCaptureSession`：`void attachClip(int pageIndex, String captureId, ClipInbox inbox) throws IOException`（録画と記録を記録の置き場へ移し、`v-<index>-<sha256>.mp4`／`.json` と名付け、`clip.<index>` に名前を、`clipack.<index>` を消して保存。前の録画があれば消す）、`Clip nextUnsentClip() throws IOException`（`ack.<index>` が済んでいる頁のうち、`clip.<index>` があって `clipack.<index>` と違う最初のもの）、`void acknowledgeClip(Clip clip) throws IOException`（`clipack.<index>` を書き、録画のファイルを消す）。`static final class Clip { final int index; final String captureId; final File file; final File record; final String sha256; }`。再読み込み（`load`）は `clip.*` の名前を検証する。
  - `DocScanApi.uploadPageClip(long documentId, int pageIndex, String captureId, String sha256, File clip, File record) throws IOException`：`POST /v1/documents/{id}/pages/{index}/clip`。本体は流して送る。呼び出しの上限 10 分。201・200 を成功とする。
  - `DocScanController`：`commitLocalPhoto` は、頁を保存した後、その頁の由来の `captureId` の録画が `ClipInbox` にあれば `attachClip` する。`queueLocalUpload` は、頁を送って受領した後、`nextUnsentClip()` があれば送り、`acknowledgeClip` する。失敗の扱いは頁と同じ（通信の失敗・408・429・5xx は 5 秒後にやり直し、409 は取り直しで古くなった録画なので捨てて進む、ほかは止める）。**未送信の頁と録画が無くなるまで、冊子の確定を呼ばない。**
  - 3秒確認へ新しい写真を出す時と、記録を始める時に、`discardExcept`（確認中の頁の `captureId` だけ残す）を呼ぶ。
- [ ] **Step 1: 試験を書く**
  - `ClipInboxTest`：置き場を取り、記録を書くと `has`。`discardExcept` で他が消える。
  - `LocalReviewTest`（既存の偽の `Surface` を使う）に：`a_clip_follows_its_page_into_the_session`（録画つきの撮影を確定 → 記録の置き場に `v-0-….mp4`、`nextUnsentClip()` は頁の受領の後にだけ返る）、`a_retake_drops_the_first_clip`（取り直しで 1 本目が消え、2 本目が付く）、`clips_are_sent_after_their_pages_and_before_the_booklet_is_finalized`（MockWebServer：頁→録画→頁→録画→確定の順）、`an_unsent_clip_survives_a_restart`（録画を送る前に controller を作り直す → 送られる）、`a_refused_stale_clip_does_not_stop_the_upload`（409 → 捨てて次へ）。
  - `DocScanApi` の試験：`uploadPageClip` が multipart の 4 つの部分を送り、201 と 200 を成功にする。
- [ ] **Step 2: 失敗を確かめる** — コンパイルが通らない（`ClipInbox` が無い）。
- [ ] **Step 3: 書く**。状態の保存は今の `state.properties` の原子的な書き換えに乗せる。
- [ ] **Step 4:** `./android-relay/gradlew --no-daemon :relaycore:testDebugUnitTest` → `BUILD SUCCESSFUL`。
- [ ] **Step 5: Commit** — `feat(relaycore): a page carries its clip to the server`

### Task 5: アプリ（`:glassdoc`）：録画用のカメラ `ClipCamera`

**Files:**
- Create: android-relay/glassdoc/src/main/java/dev/rokid/docscanglass/doc/PageCamera.java、.../ClipCamera.java、.../ClipEncoder.java、.../src/test/java/dev/rokid/docscanglass/doc/ClipCameraTest.java
- Modify: .../GlassCamera.java（`implements PageCamera` の 1 行だけ）、.../GlassesCaptureSurface.java（型を `PageCamera` に）、.../DocScanGlassActivity.java（起動時の指定 `capture`、カメラの作り分け、録画の受け渡し）

**Interfaces:**
- Consumes: Task 4 の `ClipInbox`。既存の `PageChange`、`LumaPageEvidence`、`GlassCamera.Callback`、`GlassCamera.Captured`、`CaptureProvenance`。計測アプリの `FeedProbe`（android-relay/glassprobe/.../FeedProbe.java）が、この作りの動く見本。
- Produces:
  - `interface PageCamera`：`GlassesCaptureSurface` と `DocScanGlassActivity` が `GlassCamera` に対して呼んでいるメソッドだけ（`awaitNextPage(Runnable)`、`captureOnce()`、`preview()`、`pausePreview()`、`resetPages()`、`observeFuturePages(...)`、`stopFuturePages(Runnable)`、`nativeSelectionScene(...)`、`isNativeSelectionSceneCurrent(...)`、`requestNativeAlternative(...)`、`close()`、`close(Runnable)`）。`ClipCamera` は、先の頁の観測と追加の原寸撮影を「対応しない」で返す。
  - `interface ClipEncoder { void open(File clip, int width, int height, int bitrate) throws IOException; boolean offer(java.nio.ByteBuffer luma, int rowStride, long timestampNanos); void end(Ended ended); interface Ended { void done(int written, long bytes, String failure); } }` と、その実物 `ClipEncoder.Hardware`（`MediaCodec`＋`MediaMuxer`、録画ごとの書き込みスレッド。`FeedProbe.Writer` と同じ作り）。試験は偽物を使う。
  - `final class ClipCamera implements PageCamera`：`ClipCamera(Context, Handler cameraHandler, GlassCamera.Callback callback, ClipInbox inbox, ClipEncoder encoder, Options options)`。`Options { int targetFrames = 60; long exposureNanos = 30_000_000; int bitrate = 95_000_000; }`。
    - 待ち受け：プレビュー（`GlassCamera.previewSize` と同じ選び方）に拡大率 2、毎秒 15 枚、自動露光。フレームごとに `PageChange` へ渡し、10 Hz で `callback.onPreview(Bitmap, null)`。最後の結果（露光・感度・増幅）を覚える。
    - `captureOnce()`：止める→`onReady`→録画のセッション（2016×1512 の読み取り口 1 つ、拡大率 2、手動露光）。フレームのスレッドが明るさの面を `encoder.offer` へ渡す。7 枚目から数え、流れ（ジャイロの速さ × 露光 × 焦点距離 1900 画素）が 2 画素以内のフレームが `targetFrames` に達するか、10 秒で終える。終える時も 止める→`onReady`→待ち受け。`encoder.end` の後、数えた中ほどの 1 フレームの明るさの面から JPEG を作り、由来（`clip_frame`、そのフレームの撮影結果）を付け、`inbox.offer(captureId, record)` してから `callback.onCaptured(new GlassCamera.Captured(...))`。
    - 記録（JSON）：`{"schema": 1, "capture_id", "width": 2016, "height": 1512, "rotation_degrees", "exposure_ns", "sensitivity_iso", "boost", "preview": {"exposure_ns", "sensitivity_iso", "boost"}, "frames": [{"t_ns", "smear_px"}], "dropped": n, "settle": 6}`。`frames[k]` は録画の k 枚目。
    - 5 Hz で、受け取っているフレームを間引いた画像を `callback.onPreview` へ出す（録っている間の小窓）。
    - 失敗（カメラのエラー、切り替えの拒否、エンコーダーの失敗）は `callback.onCaptureFailed(reason)`。録画のファイルは閉じて消す。カメラは開き直せる状態に戻す。
    - `pausePreview()`／`close()`：録っている最中なら、止める→`onReady`→閉じる。録画は閉じて消す。
  - 起動時の指定 `--es capture clip|still`（保存する。既定 `still`）。`clip` で通常の読取の時だけ `ClipCamera`。合同英語・リスニング、評価用の起動は `GlassCamera`。
- [ ] **Step 1: 試験を書く**（`ClipCameraTest`。既存の `DocScanTestCamera`・`DocScanTestImage`・`ShadowSystemClock` を使い、`ClipEncoder` は偽物）
  - `the_watch_preview_is_zoomed_to_the_centre`：待ち受けの要求の `SCALER_CROP_REGION` が (1008, 756)-(3024, 2268)。
  - `a_clip_session_is_built_only_after_the_watch_session_is_idle`：`captureOnce()` の直後は新しいセッションが作られず、`onReady` の後に作られる。出力は 2016×1512 の 1 つ。
  - `the_clip_request_is_manual_with_the_gain_capped`：露光 30 ms、ISO 800、増幅が 500 を越えない（プレビューの結果が 50 ms・ISO 800・増幅 423 の時は 500）、雑音除去・輪郭強調が切、`TONEMAP_MODE` を設定していない。
  - `sixty_counted_frames_end_the_clip`：66 枚渡すと終わる。`encoder.offer` は 66 回、最初の 6 枚は数えない。
  - `smeared_frames_are_not_counted`：ジャイロが速い間のフレームは数えず、記録の `smear_px` が 2 を越える。
  - `ten_seconds_end_a_clip_that_never_fills`。
  - `the_page_arrives_as_a_frame_with_its_clip_in_the_inbox`：`onCaptured` の JPEG が 2016×1512 で読める、由来の種類が `clip_frame`、`inbox.has(captureId)`、記録の `frames` の数が渡した枚数。
  - `after_the_clip_the_camera_watches_again_once_idle`。
  - `a_pause_while_recording_closes_the_clip_and_the_camera_in_order`：`pausePreview()` → `stopRepeating` → `onReady` → 閉じる。`onCaptured` は呼ばれない。置き場に録画が残らない。
  - `an_encoder_failure_is_a_failed_capture_and_the_camera_goes_on`。
- [ ] **Step 2: 失敗を確かめる** — コンパイルが通らない。
- [ ] **Step 3: 書く**。`FeedProbe` の `whenIdle`／フレームのスレッド／`Writer` を、この順で移す。`GlassCamera` は 1 行（`implements PageCamera`）のほか触らない。
- [ ] **Step 4:** `./android-relay/gradlew --no-daemon test testDebugUnitTest assembleDebug` → `BUILD SUCCESSFUL`。
- [ ] **Step 5: Commit** — `feat(glassdoc): a camera that records the page's clip`

### Task 6: アプリ：小窓の表示（進みの線、遠い印、下余白の既定値）

**Files:**
- Modify: android-relay/glassdoc/.../HudView.java、.../GlassesCaptureSurface.java、.../DocScanGlassActivity.java、.../ClipCamera.java、`app/version.py`（`GLASSES_VIEW_CONTRACT_VERSION`）、試験 `HudViewTest`

**Interfaces:**
- Produces: `HudView.showClipProgress(float share)`（0〜1。小窓の下の縁に線。0 で消す）、`HudView.showFar(boolean far)`（小窓の四隅の印）。`ClipCamera` は、録っている間に数えた枚数÷目標を 5 Hz で、待つ間に「プレビューの明るい面の割合が 0.5 未満」を `far` として出す（基準は仮。`--ef far_share` で保存して変えられる。0 で印を出さない）。下余白 `bottom_margin` の既定値を 125 にする（保存された値がある時はそれ）。
- [ ] **Step 1: 試験を足す**：`the_progress_line_grows_with_the_counted_frames`、`the_far_mark_shows_only_while_waiting`、`the_bottom_margin_defaults_to_125`。
- [ ] **Step 2: 失敗を確かめる** → **Step 3: 書く** → **Step 4:** `./android-relay/gradlew --no-daemon test testDebugUnitTest assembleDebug` → `BUILD SUCCESSFUL`、`py -3.12 -m pytest -q tests/test_versioning.py`。
- [ ] **Step 5: Commit** — `feat(glassdoc): the small window shows how far the clip has come`

### Task 7: 机上の検査を録画の経路に合わせる

**Files:**
- Modify: `scripts/glasses_device_check.py`、`scripts/e2e_route_check.py`、`docs/defect-register.md`（「使う順」の表）

**Interfaces:**
- Consumes: `ClipCamera` のログ（`clip frames=<n> counted=<n> dropped=<n> bytes=<n> first_ms=<n> back_ms=<n> boost=<n>`）、`GET /v1/documents/{id}/clips`。
- Produces: 両方のスクリプトに `--capture clip`。`clip` の時：写真の行の代わりに録画の行を読む（枚数 ≥ 66、落ち 0、増幅 ≤ 500、最初のフレームまで 2 秒以内）。サーバーに録画が届き `done` になること、頁の画像が仮の頁から置き換わること、動かない場面を録り直さないこと、休止と再開、前スワイプの録り直し、を確かめる。`e2e_route_check.py` は、代役の解答器で、録る→終える→送る→重ねる→答え→読む、の全体を通す。
- [ ] **Step 1:** スクリプトを直す（単体の `demo` があればそれも）。`py -3.12 -m ruff check scripts`。
- [ ] **Step 2: 机上で実行**（Runs on: 机上のグラス＋スマホ経由の adb＋PC の代役サーバー。掛けない。会場の構成ではない）：検査用の別名のパッケージ（`-PglassdocRouteCheck`）で、`capture=clip` を 3 回。期待：全行通過。失敗した行はそのまま報告する。
- [ ] **Step 3: Commit** — `test: the desk checks drive the clip route`

### Task 8: 記録

**Files:** `docs/hardware-measurements.md`（§M-30：机上の検査の結果）、`CLAUDE.md`、`docs/defect-register.md`、`docs/whole-review-2026-11-14.md`、`.agents/progress/current.md`、`docs/README.md`（この計画の行）、設計書（段階3の結果）

- [ ] 全文を読み直して、古くなった記述を同じ変更で直す。`py -3.12 -m pytest -q tests`、`py -3.12 -m ruff check .`、Android のビルドの結果を出力つきで書く。確かめていないものは確かめていないと書く。
- [ ] Commit、push。
