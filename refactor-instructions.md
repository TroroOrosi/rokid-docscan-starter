# Refactor Implementation Instructions

## Objective

この文書は、`rokid-docscan-starter` の既存仕様を変えずに、確認済みの技術的負債だけを小さく解消するための実装指示書である。

実装担当モデルには、次の指示として渡すこと。

> `refactor-instructions.md` の `Required Scope` だけを、`Stop And Ask Conditions` を守りながら実装し、`Definition of Done` を満たしてください。

今回の Required は D01、D02、D03 の3件である。公開 API、DB schema、保存形式、設定キー、契約 version、Android 実装は変更しない。仕様判断が必要な不整合は Required から分離した。

## Repository State

- 調査日: 2026-07-24
- リポジトリルート: `C:\Users\pupu_\OneDrive\ドキュメント\rokid-docscan-starter`
- 調査基準 commit: `51ea83d5ea5ffd105a65191a96278109a3c76edd`
- 基準 commit の件名: `Merge pull request #24 from TroroOrosi/agent/add-android-real-device-relay`
- 調査ブランチ: `agent/add-refactor-instructions`
- 最新の `git status --short`: `?? refactor-instructions.md` のみ。これは今回作成する成果物であり、ほかの tracked 差分は表示されなかった。
- tracked file 数: 124
  - `app/`: 42
  - `tests/`: 32
  - `android-relay/`: 25
  - `docs/`: 11
  - `.github/workflows/`: 2
- リポジトリ内の適用指示はルートの `CLAUDE.md`。`AGENTS.md` と `CONTRIBUTING*` は見つからなかった。Android 固有情報には `android-relay/README.md` も適用する。
- `refactor-instructions.md` 以外のファイルは調査中に変更していない。依存関係の追加・更新・インストール、自動修正、migration、外部サービス接続は行っていない。

実装開始時は、この記録を現在の状態と同一視せず、必ず `git status --short`、`git diff --stat`、`git diff --cached --stat`、`git rev-parse HEAD` を取り直すこと。

## Project Understanding

### 提供するもの

このリポジトリは、Rokid Glasses で紙面を撮影し、Android リレーで日本語 OCR を行い、FastAPI サーバーで文書化・解析・問題分割・解答・解説を行い、最大3行の HUD 表示へ返すシステムである。

実機の主経路は `CLAUDE.md:9-36`、`README.md:7-30`、`android-relay/app/src/main/java/dev/rokid/docscanrelay/DocScanController.java:181-265` で確認した。

1. CXR-L `takePhoto` が JPEG を返す。
2. Android の `JapaneseOcr` が bundled Japanese ML Kit OCR を実行する。
3. `DocScanApi.uploadPage` が JPEG、OCR、回転角を FastAPI に送る。
4. `app.main.add_page` が画像を OCR と同じ向きへ回転し、PNG として保存し、SQLite の `pages` を作成または置換する。
5. `/v1/documents/{id}/finalize` が Analyzer を呼び、OCR、図表テキスト、summary を確定する。
6. exam/review または explain session が問題・解答・根拠を生成し、`app/glasses_view.py` の HUD 契約で表示する。

text-only page と image-based `/v1/match` は互換経路として残っている。実機写真経路と混同して削除してはならない。

### 主要エントリーポイント

- Server: `app/main.py:250-3226` の `FastAPI` route 群。起動指定は `Dockerfile:14` の `uvicorn app.main:app`。
- Android: `android-relay/app/src/main/java/dev/rokid/docscanrelay/MainActivity.java`。
- Android workflow state machine: `DocScanController`。
- CXR-L / Global Hi Rokid 境界: `RokidGlobalLink`。
- HTTP client: `DocScanApi`。
- 実データ向け matcher 評価 CLI: `scripts/evaluate.py`。

### 主要モジュールと責務

- `app/main.py`: HTTP validation、ワークフロー調停、SQLite transaction、provider 呼び出し。
- `app/db.py`: SQLite schema、接続、既存 DB の additive migration と `pages` rebuild。
- `app/matching.py`: pHash、OCR 正規化、候補 scoring、verdict。
- `app/layout.py`: OCR から問題構造を抽出。
- `app/analyzers/`, `app/solvers/`, `app/explainers/`, `app/extractors/`: provider port と local/cloud adapter。
- `app/provider_registry.py`: 4 adapter family 共通の登録・選択ロジック。
- `app/retrieval.py`: explanation/solution 用の evidence retrieval。
- `app/glasses_view.py`: HUD、capture、gesture/input 契約。
- `app/version.py`: HTTP、matcher、HUD、provider port の互換 version。
- `android-relay/.../DocScanController.java`: capture、OCR、upload、finalize、review の直列状態機械。
- `android-relay/.../RokidGlobalLink.java`: Global Hi Rokid package/action と CXR-L callback の隔離。

### データフローと状態の所有者

- 永続状態の主所有者は SQLite。`app/db.py:13-165` に `documents`、`pages`、`exam_sessions`、`questions`、`solutions`、`solution_claims`、`explain_sessions`、`explain_views`、`explain_claims` がある。
- page image と listening audio は `ROKID_DATA_DIR` 配下のファイルに保存され、SQLite が path を保持する。既定 path は `app/config.py:14-18`。
- `pages` の互換性境界は `UNIQUE(document_id, page_index)`、nullable `image_path`、`phash`、OCR/vision/summary 列である（`app/db.py:21-39`）。
- Android は active document/session/index を `SharedPreferences` に保持する（`DocScanController.java:27-71`）が、文書・ページ・解答の権威状態は server 側にある。
- paid/slow provider の重複実行防止には claim table が使われる。Required でこの仕組みを変更しない。

### 外部境界

- Global Hi Rokid と公式 `com.rokid.cxr:client-l:1.0.1`。
- Android bundled Japanese ML Kit OCR。
- Android relay と FastAPI の HTTP API。
- optional OpenAI、Gemini、Anthropic adapter。credential がない既定状態は local placeholder。
- SQLite とローカル画像・音声 storage。
- Docker/Compose。Compose の公開先は既定 loopback（`docker-compose.yml:1-39`）。

### 現在確認できる検証経路

- Server: `python -m pytest -q`
- Python lint: `ruff check .`
- Android: `gradle --no-daemon -p android-relay testDebugUnitTest assembleDebug`
- Android wrapper bootstrap: `android-relay\gradlew.bat`
- matcher evaluation: `python scripts/evaluate.py --synthetic N` または `--db PATH`
- 実機経路: `docs/windows-android-real-device-setup.md` と `docs/device-verification-checklist.md`

## Scope And Evidence Limits

### 調査した範囲

- 124 tracked files の配置、依存定義、Docker/Compose、2つの CI workflow。
- `CLAUDE.md`、ルート README、Android README、`docs/` の役割と、負債候補に直接関係する文書。
- FastAPI route 一覧と、page 登録、scan status、finalize、match、exam/review、explain の主要経路。
- SQLite schema/migration と file storage。
- matcher と評価 CLI。
- provider registry、local/cloud adapter 境界、version pin。
- Android の activity、CXR-L 境界、capture/OCR/upload/review state machine、および unit-test 配置。
- 関連する pytest。特に finalize concurrency、idempotency、matcher evaluation、HUD/capture contract。

### 深く確認していない範囲

- 全 tracked file の全行を均等には読んでいない。負債候補と主要フローに関係する範囲を優先した。
- 実機 Rokid Glasses、Global Hi Rokid、Android SDK 36、CXR-L callback は実行していない。
- optional cloud provider は credential と外部接続が必要なため実行していない。
- production/shared environment、実データ、`.env`、credential の値には接続・参照していない。
- `.git` 内部、dependency/vendor、build output、cache、coverage、runtime `data/` は根拠に必要ないため除外した。

### 根拠の読み方

- 行番号は調査基準 commit に対するもの。実装時にずれた場合は併記した symbol を使って再確認する。
- 文書上の意図と実装・テスト上の挙動を区別した。
- `Hypothesis` は計測または設計判断が不足しており、Required に含めていない。
- D06 と D07 は重要な不整合だが、正解を一意に決められないため Proposal Only とした。これにより、ブロッキング質問なしで D01-D03 を安全に確定できる。

## Behaviors To Preserve

1. 実機主経路は CXR-L `takePhoto` → JPEG callback → phone-side Japanese OCR → JPEG と OCR の upload である。
2. text-only page、optional image match、既存 API field は互換経路として維持する。
3. page は `(document_id, page_index)` で一意。review 開始前の同一 index 再送は置換であり、page row を増やさない。
4. new page は open document にだけ追加できる。finalize と page 追加の race で ready document に new page が入ってはならない。
5. page index は finalize/navigation 時に 0 始まりで dense である必要がある。
6. finalize は page ごとに冪等で、summary 済み page に Analyzer を再課金・再実行しない。
7. Analyzer が返した text/vision/summary の現在の優先順位と最大 summary 長を変えない。
8. Analyzer 失敗、競合、snapshot 不一致で stale/partial summary や ready status を commit しない。
9. live `/v1/match` は `document_id` 内だけを候補にする（`app/main.py:863-868`）。
10. `scripts/evaluate.py` の JSON report key、集計の意味、CLI option、synthetic mode、threshold 算出を維持する。
11. HUD は黒地・緑・静的・最大3行。HUD payload 自体は audio/animation/white-flash 指示を出さない。
12. 撮影時の shutter sound、flash、capture indicator は device-controlled。privacy LED を無効化、回避、隠蔽、誤表現しない。
13. `GET /v1/settings` の現行 capture 値、HTTP schema/status、version pin を Required では変えない。
14. server-side provider は明示 routing と local fallback の現在の挙動を維持する。
15. `ROKID_ALLOW_REAL_EXAM_SOLVE` による real exam lock を弱めない。
16. API key、Hi Rokid token、page contents、provider credential を log や報告へ出さない。

## Non-Negotiables

- 最初に `git status --short` を確認し、開始時の差分をそのまま記録する。
- 開始時の未コミット変更を上書き、破棄、stash、reset しない。
- 必要な編集箇所と既存差分が重なる場合は実装前に停止して質問する。
- Required で変更してよい path は次の5つだけ。
  - `app/main.py`
  - `tests/test_scan_status.py`
  - `scripts/evaluate.py`
  - `tests/test_evaluate.py`
  - `docs/glasses-ux-contract.md`
- `refactor-instructions.md` 自体を実装都合で書き換えない。
- dependency manifest、lockfile、DB schema/migration、API schema、設定キー、version constant、Android code を変更しない。
- 無関係な format、rename、移動、`app/main.py` 全体分割を行わない。
- tracked file を変更する auto-fix を使わない。特に `ruff --fix` を実行しない。
- テスト削除、assert 弱体化、skip/xfail/ignore の広範追加で通さない。
- baseline の既存失敗と新規失敗を区別する。
- 外部 provider、production、shared DB、実機状態へ書き込まない。
- secret 値を表示、記録、commit しない。
- commit/push は利用者から明示的に依頼された場合だけ行う。

## Stop And Ask Conditions

次のいずれかが起きたら、その項目の実装を止め、確認済み事実、選択肢、変更される受け入れ条件を報告して質問する。

1. Required の許可 path に既存差分がある、または Required 外の file 変更が必要になる。
2. 公開 API、HTTP status/detail の意味、DB schema、保存済みデータ、file layout、設定キー、version bump が必要になる。
3. D01 で Analyzer 呼び出しを write transaction 外へ出すと、現行の冪等性、page replacement、all-or-nothing、dense-index guard を同時に維持できない。
4. D01 の regression test が、無関係な sleep 延長や不安定な timing 依存なしでは書けない。
5. D02 で report schema、既存 aggregate の意味、CLI 引数、matcher threshold/version を変える必要がある。
6. D02 の候補を文書単位に分けるべきでないことを示す、現行運用または consumer の具体的証拠が見つかる。
7. D03 と同じ適用範囲で、現行 `CLAUDE.md`、実装、テストより優先される SDK 仕様が見つかる。
8. shutter/flash/privacy LED の実機挙動を未検証のまま断定する必要が生じる。
9. 宣言済み既存 dependency が不足して検証できず、利用者から環境構築の許可がない。勝手に install しない。
10. baseline になかった失敗、warning、tracked/generated 差分が発生し、今回の変更との因果を説明できない。
11. Recommended または Proposal Only を Required と同じ変更へ混ぜる必要がある。

## Baseline Commands And Results

以下は調査時の実測。実装担当は編集前に再実行し、時刻、終了 code、差を記録すること。

### Repository

```powershell
git status --short
git branch --show-current
git rev-parse HEAD
```

- 終了 code: 0
- branch: `agent/add-refactor-instructions`
- HEAD: `51ea83d5ea5ffd105a65191a96278109a3c76edd`
- status: `?? refactor-instructions.md` のみ。

### Python version

```powershell
python --version
```

- 終了 code: 0
- `Python 3.12.10`

### Python syntax parse

tracked Python file を `ast.parse` する read-only script を実行した。

- 終了 code: 0
- `parsed_python_files=78`

### Pytest

```powershell
python -m pytest -q
```

- 終了 code: 1
- collection 前に `tests/conftest.py:4` で `ModuleNotFoundError: No module named 'PIL'`。
- `requirements.txt:5` には `pillow>=10.0` が宣言されているが、この環境には入っていない。
- 調査制約に従い install しなかった。したがって test pass/fail は未確認であり、「テスト失敗」と「未収集」を混同しないこと。

### Ruff

```powershell
ruff check .
```

- 終了 code: 1
- 既存 7 errors:
  - `app/devtools/rokid_led.py:607` F541
  - `app/devtools/rokid_led.py:608` F541
  - `app/llm.py:32` F401
  - `scripts/rokid_led.py:66` F401
  - `tests/test_layout.py:25` F841
  - `tests/test_rokid_led.py:9` F401
  - `tests/test_versioning.py:9` F401
- 既存 warning: `app/matching.py:85` の invalid `# noqa` directive。
- Required の Python path だけを対象にした次の command は終了 code 0。

```powershell
ruff check app/main.py tests/test_scan_status.py scripts/evaluate.py tests/test_evaluate.py
```

`ruff --fix` は実行していない。

### Android

```powershell
Get-Command gradle
```

- system `gradle`: 見つからなかった。
- `android-relay/gradlew` と `android-relay/gradlew.bat` は存在する。
- `android-relay/local.properties` は存在しない。
- wrapper 実行は Gradle distribution/dependency download を起こし得るため、調査中は build/test を実行しなかった。
- Required は Android code を変更しないため、Android build を Required の合格条件にはしない。

### D02 minimal reproduction

Pillow を install せず、画像 API を呼ばない stub import で `_eval_candidates` の候補 pooling だけを実行した。

```text
items:
  page 1 / document A / page_index 0 / hash 000...000
  page 2 / document B / page_index 0 / hash 000...000
queries:
  document A -> expected page 1
  document B -> expected page 2
```

- 終了 code: 0
- `page_count=2`
- `query_count=2`
- `variant_match_accuracy=0.5`
- `matched_page_ids=[1, 1]`

同一 hash の別文書 page が1つの候補集合に入り、document B の query が page 1 に tie-break された。これは live `/v1/match` の document scope と一致しない。

## Debt Map

### D01 — Finalize が remote analysis 中も SQLite writer lock を保持する

- **Status**: Verified
- **Evidence**:
  - `app/main.py:656-791`, symbol `finalize_document`
  - Analyzer call: `app/main.py:691-694`
  - page update: `app/main.py:710-726`
  - write transaction の意図を述べる comment と最終処理: `app/main.py:746-775`
  - 現行 concurrency tests: `tests/test_scan_status.py:187-306`
  - idempotency test: `tests/test_api.py:571-596`
- **Observation**: 2枚以上の未 summary page があると、1枚目の Analyzer 後に `UPDATE pages` が implicit write transaction を開始する。その次の loop では、transaction を commit しないまま2枚目以降の Analyzer を呼ぶ。`if not conn.in_transaction: BEGIN IMMEDIATE` は loop 後なので、1回でも update した経路では「最終 check/update だけ短い write transaction」という comment の状態にならない。既存 concurrency tests は1回目の Analyzer call を block するため、最初の update 後の lock 保持を検出しない。
- **Why It Matters**: remote Analyzer の latency 中に SQLite writer lock が保持され、page の再読取・追加や同じ DB の別 write request が待たされる。timeout や操作停止へつながり、comment が保証しているつもりの concurrency invariant を将来の変更者が誤認する。
- **Impact**: document finalize、同時 page upload/replacement、同一 SQLite DB の write endpoint。HTTP schema は変更対象外。
- **Change Risk**: Medium
- **Priority**: P1
- **Recommendation**: 全 Analyzer call と変換結果の計算を DB write 前に行い、元 snapshot と pending updates を memory に保持する。解析完了後に短い `BEGIN IMMEDIATE` を開始し、dense index と元 snapshot を再確認してから、page updates と ready status を1 transaction で commit する。
- **Verification**: 2枚目の Analyzer を block し、その間の page replacement が block せず完了し、Analyzer release 後の finalize が 409 となり replacement が保持される regression test。既存 finalize concurrency/idempotency tests と全 pytest。
- **Disposition**: Required
- **Stop Condition**: API/error 意味、DB schema、Analyzer interface を変えないと all-or-nothing、idempotency、replacement guard を維持できない場合。

### D02 — Matcher 評価 CLI が異なる document の page を同じ候補集合で比較する

- **Status**: Verified
- **Evidence**:
  - `_eval_candidates`: `scripts/evaluate.py:106-181`
  - `from_db` query は `document_id` を select せず、全 row を1つの `items`/`queries` に追加: `scripts/evaluate.py:184-232`
  - live `/v1/match` は `WHERE document_id = ?`: `app/main.py:863-868`
  - DB evaluator tests は document 1つだけ: `tests/test_evaluate.py:91-163`
  - `Baseline Commands And Results` の2文書 minimal reproduction
- **Observation**: `ORDER BY document_id` は順序を変えるだけで scope を分けない。評価 query は別 document の candidate と競合するが、production match は指定 document 以外を検索しない。同一 hash の2文書再現で accuracy は 0.5 になった。
- **Why It Matters**: 実機データを複数文書含む DB で threshold tuning すると、production では起こらない cross-document collision を false mismatch として数え、accuracy と suggested threshold を歪める。
- **Impact**: `scripts/evaluate.py --db` report の正確性。live matcher と DB schema は変更対象外。
- **Change Risk**: Low
- **Priority**: P1
- **Recommendation**: candidate と query に internal document scope を持たせ、各 query は同じ document の candidate だけで評価する。全 document の結果は既存 report schema と集計定義へ合算する。synthetic mode は単一の sentinel scope とする。
- **Verification**: 同一画像を document 1 と document 2 に1枚ずつ登録する DB test を追加し、双方の variant が自 document の page に HIT して accuracy 1.0 となることを確認。既存 missing-image、single-document、synthetic、CLI tests を維持。
- **Disposition**: Required
- **Stop Condition**: report key/意味、CLI、matcher threshold/version、DB schema の変更が必要になる、または cross-document pool が意図されたことを示す現行 consumer が見つかる場合。

### D03 — 旧 UX 文書が現行 capture contract と反対の無音・無フラッシュ制御を命令する

- **Status**: Verified
- **Evidence**:
  - README は当該文書を「旧操作を含むグラス UX 参考資料」と分類: `README.md:90-102`
  - 旧文書は「必ず守る規約」とし、CXR-S/Camera2 無音撮影を要求: `docs/glasses-ux-contract.md:1-24`
  - 旧文書は `shutter_sound:false`、`flash:"off"`、`capture_tone:false`、`cxr-s/camera2` を現行値として記述: `docs/glasses-ux-contract.md:30-40`
  - 現行実装は `device_controlled` と `cxr-l/takePhoto`: `app/glasses_view.py:80-93`
  - 現行 test: `tests/test_exam_api.py:42-69`
  - 上位指示は未実測の silent/no-flash claim を禁止: `CLAUDE.md:38-50`
- **Observation**: 同じ repo 内で、現行実装・test・上位指示と旧参考文書が正反対の capture semantics を断定している。HUD の「音や white flash の指示を出さない」と、物理撮影 cue をアプリが制御できるという主張も混同している。
- **Why It Matters**: 実装担当が旧文書を契約として読むと、公式主経路から外れた camera path を追加したり、device-controlled privacy/capture indicator を無効化できると誤認する。安全性と実機互換性の両方に影響する。
- **Impact**: documentation と将来の実装判断。Required では runtime/API を変更しない。
- **Change Risk**: Low
- **Priority**: P1
- **Recommendation**: 文書冒頭で legacy reference であることと現行優先 source を明示し、capture に関する能動的な断定だけを現行 `GET /v1/settings` 契約へ合わせる。HUD の silent/static/no-white-flash 表示契約は保持し、物理 shutter/flash/capture indicator は device-controlled・実機確認必須と区別する。
- **Verification**: stale capture literal の targeted `rg`、現行値の文書確認、`tests/test_exam_api.py::test_settings_advertise_silent_contract`。コード・version diff がないことも確認。
- **Disposition**: Required
- **Stop Condition**: exact firmware で app-controlled silent/no-flash を保証する公開 SDK 根拠が見つかる、または文書全体の legacy 操作を同時改訂しないと capture 節だけを安全に直せない場合。

### D04 — 文書化された Ruff baseline と CI が一致せず、既存 lint debt が常態化している

- **Status**: Verified
- **Evidence**:
  - `CLAUDE.md:66-73` は `ruff check .` を標準検証に指定。
  - `.github/workflows/ci.yml:25-31` は requirements install と pytest だけで Ruff を実行しない。
  - `requirements.txt:1-18` に Ruff の version/pin はない。
  - 調査時 `ruff check .` は7 errorsと1 warning。詳細は baseline 節。
- **Observation**: contributor 向け必須 command は既に失敗するが、CI では検出されない。Required path の targeted Ruff は clean だった。
- **Why It Matters**: lint を「必須」として扱う人と CI の合格条件が異なり、新規 error と既存 error の区別が難しくなる。
- **Impact**: developer workflow、CI、Python 全体。product behavior への直接影響はない。
- **Change Risk**: Low
- **Priority**: P2
- **Recommendation**: Required 完了とは別の小さい変更で、列挙済み7 errorsと invalid noqa だけを手修正し、`ruff check .` を clean にする。Ruff の導入/pin/CI gate は、その clean baseline 後に別判断する。
- **Verification**: `ruff check .`、`python -m pytest -q`、lint 修正 path の targeted tests。
- **Disposition**: Recommended
- **Stop Condition**: lint cleanup が behavior change、広範 format、dependency/toolchain policy 変更を必要とする場合。

### D05 — Android relay version が build metadata と HTTP payload に重複している

- **Status**: Verified
- **Evidence**:
  - `versionName = "0.1.0"`: `android-relay/app/build.gradle.kts:10-17`
  - `client_version = "android-relay/0.1.0"`: `android-relay/app/src/main/java/dev/rokid/docscanrelay/DocScanApi.java:59-65`
  - `client_version` を固定する Android unit test は見つからなかった。
- **Observation**: 同じ version が build config と request payload に別々に hard-code されている。
- **Why It Matters**: release 時に片方だけ更新すると、server telemetry/compatibility metadata と実 APK version がずれる。
- **Impact**: Android build と create-document payload。
- **Change Risk**: Low
- **Priority**: P2
- **Recommendation**: 別変更で payload を build-generated `VERSION_NAME` から組み立て、HTTP test で固定する。Android build/versioning 方針は維持する。
- **Verification**: Android unit tests、`assembleDebug`、request body assertion。
- **Disposition**: Recommended
- **Stop Condition**: 現在の Android Gradle Plugin 設定で `BuildConfig.VERSION_NAME` が生成されない、または client protocol version と APK version を別管理する要件がある場合。

### D06 — `ROKID_REAL_MODE` server invariant が実装・設定・test に存在しない

- **Status**: Verified
- **Evidence**:
  - invariant: `CLAUDE.md:52-64`
  - runtime config: `app/config.py:14-88`
  - example config: `.env.example:1-74`
  - Compose mapping: `docker-compose.yml:21-37`
  - repo-wide exact searchで `ROKID_REAL_MODE` は `CLAUDE.md:62` のみ。
- **Observation**: 「`ROKID_REAL_MODE=1` must reject placeholder analyzer/solver combinations」と書かれているが、key の読み込み、起動/request guard、error contract、test、example がない。`ROKID_ALLOW_REAL_EXAM_SOLVE` は別目的の設定である。
- **Why It Matters**: operator が文書だけを信じると、実機用設定で placeholder が fail-open しないという誤った前提を持つ。
- **Impact**: provider routing、startup/request error、deployment config、offline default。
- **Change Risk**: High
- **Priority**: P1
- **Recommendation**: 先に owner が「real mode の範囲」「拒否対象の adapter 組合せ」「startup fail-fast か request error か」「onboard AI 経路の扱い」「既存 deployment の default」を決定する。その後、設定、Compose/example、test、docs、必要な version を一体で設計する。
- **Verification**: 決定後に config matrix tests、startup/request tests、Compose config、offline default regression。
- **Disposition**: Proposal Only
- **Stop Condition**: 承認済み仕様と backward-compatibility 方針がない状態では実装しない。

### D07 — 「original image が authoritative」と、実際の normalized PNG 保存が矛盾する

- **Status**: Verified
- **Evidence**:
  - original image invariant: `CLAUDE.md:52-60`
  - Android は original JPEG を upload: `DocScanController.java:239-265`
  - server は decode/rotate 後に新しい PNG だけを保存: `app/main.py:349-358`
  - README は normalized PNG 保存を説明: `README.md:191-196`
  - Android README は normalized PNG を authoritative と説明: `android-relay/README.md:46-49`
  - user guide は元 JPEG と OCR の両方を保存すると説明: `docs/user-operation-guide.md:61-62`
  - DB には image path が1列だけ: `app/db.py:21-39`
- **Observation**: upload bytes は decode、rotation、RGB conversion、PNG encode 後に破棄される。元 JPEG file は保存されない。「original」の意味が raw upload bytes か、向き補正済み lossless derivative か文書間で一致しない。
- **Why It Matters**: raw source の forensic/re-analysis 要件、storage 容量、privacy/retention、API の image semantics が未決定のまま実装者が schema/file layout を変える危険がある。
- **Impact**: persisted files、DB schema、replacement cleanup、backup/retention、Analyzer input、docs。
- **Change Risk**: High
- **Priority**: P1
- **Recommendation**: owner が raw JPEG を別保存するか、normalized PNG を authoritative と定義し直すか決定する。raw 保存なら naming、migration、retention、replacement、API exposure、容量、privacy を設計する。PNG を正とするなら `CLAUDE.md` と user guide を修正する。
- **Verification**: 決定後に byte/file assertions、rotation tests、replacement cleanup、migration/upgrade test、docs review。
- **Disposition**: Proposal Only
- **Stop Condition**: 保存形式・schema・retention の明示承認なしでは変更しない。

### D08 — async upload route 内の同期 CPU/SQLite 処理が event loop を止める可能性がある

- **Status**: Hypothesis
- **Evidence**:
  - `async def add_page`: `app/main.py:307-493`
  - upload read 後の image rotate、pHash、PNG encode と同期 SQLite: `app/main.py:349-448`
  - `async def match_page`: `app/main.py:794-983`
  - matching の pure-Python DCT/Pillow path: `app/matching.py:1-45`
- **Observation**: coroutine route 内で CPU-bound image work と同期 sqlite3 work を直接行う構造は確認した。ただし、この repo/環境で concurrency latency を計測しておらず、実害の閾値は未確認。
- **Why It Matters**: 大きい画像または同時 upload で、無関係な health/status request まで遅延する可能性がある。
- **Impact**: server throughput、timeout、transaction/thread ownership。実装方法によっては広い変更になる。
- **Change Risk**: Medium
- **Priority**: P2
- **Recommendation**: まず複数 concurrent upload と軽量 GET の latency benchmark を追加し、現行 baseline を測る。実害が確認できた場合だけ、sync route 化、threadpool への限定 offload、画像処理分離の最小案を比較する。
- **Verification**: 再現可能な concurrency benchmark、functional regression、thread-safe DB connection ownership。
- **Disposition**: Proposal Only
- **Stop Condition**: 計測なし、または server concurrency/deployment model が未確定のまま構造変更しない。

### D09 — `app/summarize.py` compatibility shim

- **Status**: Verified
- **Evidence**:
  - shim の目的と delegation: `app/summarize.py:1-16`
  - compatibility test: `tests/test_versioning.py:87-90`
- **Observation**: module は短く、旧 caller を保持しながら active Analyzer へ委譲する明示的 compatibility boundary である。
- **Why It Matters**: 「薄い wrapper」「旧名」という理由だけで削除すると、既存 import を破壊する。
- **Impact**: Python import compatibility。
- **Change Risk**: Medium
- **Priority**: P3
- **Recommendation**: 現時点では保持する。削除は caller inventory と deprecation 方針があるときだけ行う。
- **Verification**: `tests/test_versioning.py::test_summarize_shim_delegates_to_analyzer`
- **Disposition**: No Action
- **Stop Condition**: Required のついでに削除・rename しない。

### D10 — Provider registry と local fallback

- **Status**: Verified
- **Evidence**:
  - 共通抽象化と routing precedence: `app/provider_registry.py:1-61`
  - analyzer wrapper: `app/analyzers/registry.py:21-49`
  - solver tier semantics: `app/solvers/registry.py:49-130`
  - fallback tests: `tests/test_solver_fallback.py:37-76`
  - analyzer route tests: `tests/test_versioning.py:54-84`
- **Observation**: 以前の4 family 重複は共通 `ProviderRegistry` に集約済みで、family 固有 wrapper と solver tier behavior は test されている。local fallback は offline-first の意図された挙動である。
- **Why It Matters**: 長さや import-time registration だけを理由に再抽象化すると、routing precedence と offline fallback を壊す可能性がある。
- **Impact**: 全 provider family と offline operation。
- **Change Risk**: Medium
- **Priority**: P3
- **Recommendation**: 現時点では変更しない。具体的な order-dependence や routing bug の再現が得られた場合にのみ別 debt として扱う。
- **Verification**: registry/fallback tests と provider list/settings tests。
- **Disposition**: No Action
- **Stop Condition**: Required の範囲で registry API、fallback、registration lifecycle を変えない。

## Required Scope

### R1 / D01 — Finalize の analysis phase と write phase を分離する

#### 目的

2枚目以降の slow/remote Analyzer 実行中に SQLite writer lock を保持しない。同時 page replacement を待たせず、解析対象 snapshot が変わった finalize は stale result を書かず 409 にする。

#### 変更してよい範囲

- `app/main.py` の `finalize_document` 内だけ。
- `tests/test_scan_status.py` の finalize concurrency tests。

#### 変更してはいけない境界

- route、request/response schema、成功 code、既存 400/409 detail の意味。
- `app/db.py`、schema、migration、connection global policy。
- Analyzer interface、provider routing、summary text の優先順位・48文字上限。
- `add_page`、page replacement rule、ready document の new page guard。
- contract/API version。

#### 実装手順

1. まず2枚の未 summary page を作る regression test を追加する。
2. test Analyzer は1枚目を即時返却し、2枚目の call で `Event` を通知して block する。
3. 2枚目が block 中に別 thread で同一 document の page replacement を開始し、Analyzer を release する前に replacement request が完了することを bounded `Event.wait` で確認する。固定 sleep を合否条件にしない。
4. release は `finally` で必ず行い、失敗時にも thread を残さない。
5. production code では、DB から読んだ `original_snapshot` と Analyzer の `pending_updates` を分ける。全 Analyzer call と結果整形を、page/document への DML より前に完了する。
6. 解析後に `BEGIN IMMEDIATE` を開始し、document/page density と `original_snapshot` を再読する。変更があれば既存の 409 semantics で中断し、pending result を一切書かない。
7. snapshot が同一の場合だけ、pending page updates と `documents.status='ready'` を同じ短い transaction で適用・commit する。
8. summary 済み page は Analyzer を再実行しない。Analyzer 例外時は page/ready status を一切 commit しない。
9. 既存 test の期待値を変更せず、必要なら transaction 意図の comment だけを実装に合わせて更新する。

#### 必須 test / 再現

- 新規: 1枚目 update 相当の計算後、2枚目 Analyzer block 中でも replacement が完了する。
- 新規 test の finalize response は release 後 409。
- replacement 後の OCR が残り、summary は `NULL`、document status は `open`。
- 既存:
  - `test_finalize_rechecks_pages_after_slow_analysis`
  - `test_finalize_does_not_overwrite_concurrent_page_replacement`
  - `test_finalize_is_idempotent_per_page`
- Analyzer が2枚目で例外を投げたとき、1枚目にも partial update がないことが既存 test で固定されていなければ追加する。

#### 受け入れ条件

- Analyzer 実行中は finalize connection が write transaction を保持しない。
- concurrent replacement/addition は Analyzer release を待たず DB write を完了できる。
- snapshot 変更時は stale result を1件も書かず、document を ready にせず、既存 409 を返す。
- 競合なしでは全 page summary と ready status が1 transaction で commit される。
- 再 finalize は summary 済み page を再解析しない。

#### 検証 command

```powershell
python -m pytest -q tests/test_scan_status.py tests/test_api.py::test_finalize_is_idempotent_per_page
ruff check app/main.py tests/test_scan_status.py
```

#### 停止条件

`Stop And Ask Conditions` に加え、SQLite timeout を長くする、global lock を追加する、test の timeout を緩めるだけで見かけ上通す必要が出た場合は停止する。

### R2 / D02 — DB matcher evaluation を document scope に合わせる

#### 目的

`scripts/evaluate.py --db` が、各 query を production と同じ document の candidate だけに照合し、複数文書 DB でも threshold report を歪めないようにする。

#### 変更してよい範囲

- `scripts/evaluate.py` の `_eval_candidates`、`from_db`、`from_synthetic` と必要な小さい内部 helper。
- `tests/test_evaluate.py`。

#### 変更してはいけない境界

- `app/matching.py` と live `/v1/match`。
- DB schema/migration。
- CLI option、exit code、output path behavior。
- report の既存 top-level key、`source` key、各 result key、accuracy/hamming/threshold の意味。
- pHash variant、threshold constants、matcher/version。

#### 実装手順

1. `from_db` の SELECT で `document_id` を保持する。
2. internal candidate/query representation に scope ID を追加するか、同等の小さい grouping helper を作る。
3. query ごとに同じ `document_id` の candidate list だけを `match` へ渡す。
4. page/query/hit/top1/hamming は全 document を通した既存 aggregate として計算する。
5. synthetic mode は全 item/query に同じ sentinel scope を付け、現在の結果を維持する。
6. missing image page は、現在と同様に candidate として残し、query 生成だけを skip する。ただし別 document の query には混ぜない。
7. 同一画像を異なる2 document に1枚ずつ保存した test を追加する。現在の実装なら片方が誤 tie-break される fixture にする。

#### 必須 test / 再現

- 複数 document、同一 hash/image の各 variant が自 document の expected page に HIT。
- `variant_match_accuracy == 1.0` と `variant_top1_accuracy == 1.0`。
- `page_count` と `query_count` は全 document 合計。
- report schema の key set が既存と同じ。
- 既存 single-document、missing-image、synthetic、CLI tests が無変更で通る。

#### 受け入れ条件

- DB mode の candidate scope が live `/v1/match` と一致する。
- cross-document collision は report に false mismatch を作らない。
- same-document collision は従来どおり評価される。
- report/CLI の backward compatibility を維持する。

#### 検証 command

```powershell
python -m pytest -q tests/test_evaluate.py
ruff check scripts/evaluate.py tests/test_evaluate.py
```

#### 停止条件

既存 report key の削除・rename、accuracy 定義変更、threshold/version bump、DB migration が必要になった場合は停止する。

### R3 / D03 — Legacy UX 文書の capture 安全情報を現行契約へ合わせる

#### 目的

旧操作の参考資料を現行の権威契約と誤認させず、HUD の静かな表示契約と、device-controlled な物理撮影 cue を明確に分ける。

#### 変更してよい範囲

- `docs/glasses-ux-contract.md` の title、冒頭 scope note、capture/shutter/flash/privacy LED に直接関係する記述だけ。

#### 変更してはいけない境界

- Python/Android code、test assertion、API payload、version。
- HUD の最大3行、静的表示、no-animation、no-white-flash directive。
- privacy LED を無効化・回避しない原則。
- capture 以外の legacy gesture/operation 全面改訂。
- 実機で未確認の shutter/flash/indicator behavior の断定。

#### 実装手順

1. title と冒頭に、この文書が旧操作を含む参考資料であることを明記する。
2. real-device capture と SDK boundary は `CLAUDE.md`、`docs/cxr-l-integration.md`、`docs/windows-android-real-device-setup.md`、`docs/device-verification-checklist.md` を優先すると明示する。
3. 「シャッター音を一切鳴らさない」「CXR-S/Camera2 で無音撮影」「flash off/capture tone false」という active requirement を削除または置換する。
4. 現行 machine-readable contract を正確に記載する。
   - `mode: photograph`
   - `camera_path: cxr-l/takePhoto`
   - `shutter_sound: device_controlled`
   - `flash: device_controlled`
   - `capture_tone: device_controlled`
   - privacy LED は `on_while_camera_active` / tamper forbidden
5. HUD の `silent:true` と `white_flash:false` は server render directive であり、物理 shutter/flash を制御・保証する値ではないと明示する。
6. exact firmware で物理 checklist を完了するまで「無音撮影」「フラッシュしない」と報告しない。

#### 必須 test / 再現

```powershell
rg -n 'CXR-S/Camera2|shutter_sound:false|capture_tone:false|flash:\"off\"|無音撮影|一切鳴らさない' docs/glasses-ux-contract.md
rg -n 'device.controlled|cxr-l/takePhoto|privacy LED|プライバシーLED|旧操作|参考資料' docs/glasses-ux-contract.md
python -m pytest -q tests/test_exam_api.py::test_settings_advertise_silent_contract
```

最初の `rg` は active instruction として0件を期待する。歴史説明として残す必要がある場合は、否定・廃止済みであることが同じ段落から明白でなければならない。

#### 受け入れ条件

- 文書だけを読んでも app が shutter/flash/privacy indicator を無効化できると解釈できない。
- 現行 `GET /v1/settings` の capture 値と一致する。
- HUD rendering と physical capture cue の責務が分離されている。
- runtime code、test、version に差分がない。

#### 検証 command

上記 targeted `rg` と pytest に加え、`git diff -- docs/glasses-ux-contract.md` を人が読み、capture 節以外の scope creep がないことを確認する。

#### 停止条件

現行の公開 SDK documentation が exact firmware 上で app-controlled silent/no-flash を保証している証拠が見つかった場合は、証拠を提示して停止する。未検証の hardware claim で妥協しない。

## Recommended Follow-ups

Required 完了後も自動では実装しない。別 scope、別 baseline、別承認で扱う。

1. **D04: 既存 Ruff debt の限定 cleanup**
   - baseline に列挙した7 errorsと1 warningだけを手修正する。
   - behavior、format、dependency、CI gate は混ぜない。
   - clean baseline 後に、Ruff version/pin と CI 導入を別判断する。
2. **D05: Android client version の単一 source 化**
   - APK `versionName` と request `client_version` を同期させる。
   - unit test と Android build が利用できる環境で行う。

## Proposal-only Items

明示的な仕様決定または計測なしに実装してはならない。

1. **D06: `ROKID_REAL_MODE`**
   - fail-fast の場所、対象 adapter、onboard AI、offline default、error/version を owner が決める。
2. **D07: original JPEG と normalized PNG**
   - authoritative source の定義、schema/file layout、migration、retention、privacy、容量を owner が決める。
3. **D08: async route の同期処理**
   - 先に concurrency benchmark で実害を確認し、deployment/thread model を決める。

## Implementation Phases

### Phase 0 — 状態と baseline の固定

- `git status --short`、diff 概要、HEAD を記録する。
- Required path と既存差分が重なれば停止する。
- baseline commands を再実行し、終了 code と既存失敗を記録する。
- dependency 不足が続く場合、勝手に install せず確認する。

### Phase 1 — 安全網を先に追加

- D01 の「1枚目解析後・2枚目 block 中の replacement」test を追加する。
- D02 の「別 document に同一画像」test を追加する。
- それぞれ現行実装で意図した理由により失敗することを確認する。
- test が別理由で失敗する場合は production code を編集せず修正または停止する。

### Phase 2 — D03 documentation correction

- `docs/glasses-ux-contract.md` の capture claim だけを修正する。
- stale literal の `rg` と diff review を行う。

### Phase 3 — D02 document-scope boundary

- internal evaluator data に document scope を追加する。
- synthetic/report compatibility を保持する。
- `tests/test_evaluate.py` と targeted Ruff を実行する。

### Phase 4 — D01 transaction responsibility separation

- analysis result を memory に保持し、write transaction を最終 snapshot check と commit だけへ限定する。
- concurrency、exception、idempotency tests を実行する。
- API/schema/version に差分がないことを確認する。

### Phase 5 — 全体検証と scope audit

- Required targeted tests、全 pytest、targeted/full Ruff、syntax parse、diff checks を順に行う。
- baseline の既存失敗との差を説明する。
- `git diff --name-only` が Required の許可 path だけであることを確認する。
- 最終 `git status --short` を記録する。

## Verification Requirements

### 編集前

```powershell
git status --short
git diff --stat
git diff --cached --stat
git rev-parse HEAD
python --version
python -m pytest -q
ruff check .
```

各 command の終了 code と要点を記録する。pytest が `PIL` 不足のままなら Required の DoD を満たせないため、依存を勝手に追加せず停止して環境方針を確認する。

### Required に直接対応する検証

```powershell
python -m pytest -q tests/test_scan_status.py tests/test_api.py::test_finalize_is_idempotent_per_page
python -m pytest -q tests/test_evaluate.py
python -m pytest -q tests/test_exam_api.py::test_settings_advertise_silent_contract
ruff check app/main.py tests/test_scan_status.py scripts/evaluate.py tests/test_evaluate.py
```

これらは次を保証する。

- D01: slow Analyzer、page race、snapshot、idempotency、partial-write 防止。
- D02: production と同じ document scope、report compatibility。
- D03: runtime capture contract が文書修正で変わっていない。
- Ruff: 今回編集した Python path に新規 static error がない。

### 主要フロー回帰

```powershell
python -m pytest -q
```

collection と全 test 完走を要求する。baseline は未収集なので、実行できた場合はその結果を新しい基準として明記する。既存 failure が出る場合は今回の変更との因果を file/test 単位で説明し、説明できなければ完了扱いにしない。

### Static / diff

```powershell
ruff check .
git diff --check
git diff --name-only
git status --short
```

- full Ruff は baseline の7 errorsと1 warningから新規 finding が増えていないことを最低条件とする。D04 は scope 外なので既存 finding をついでに直さない。
- `git diff --check` は whitespace error 0件。
- changed path は Required の許可 path だけ。

tracked Python syntax parse:

```powershell
@'
import ast
import subprocess
from pathlib import Path

paths = [
    Path(p)
    for p in subprocess.check_output(
        ["git", "ls-files", "*.py"], text=True
    ).splitlines()
]
for path in paths:
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
print(f"parsed_python_files={len(paths)}")
'@ | python -
```

### Documentation checks

```powershell
rg -n 'CXR-S/Camera2|shutter_sound:false|capture_tone:false|flash:\"off\"|無音撮影|一切鳴らさない' docs/glasses-ux-contract.md
rg -n 'device.controlled|cxr-l/takePhoto|privacy LED|プライバシーLED|旧操作|参考資料' docs/glasses-ux-contract.md
git diff -- docs/glasses-ux-contract.md
```

### Android / physical verification

Required は Android code と hardware behavior を変更しないため Android build と実機 checklist は必須でない。Required 実装のために Android file、capture payload、hardware claim を変える必要が出た時点で scope 外として停止する。

実行しなかった command は、command 名、未実行理由、代替 evidence、残存 risk を最終報告へ記載する。

## Definition of Done

次をすべて満たしたときだけ Required 完了とする。

- D01、D02、D03 の全受け入れ条件を満たす。
- Required に追加した regression tests が、修正前の問題を正しく捉え、修正後に通る。
- `Behaviors To Preserve` に回帰がない。
- Analyzer 実行中の write lock、cross-document evaluation、stale capture instruction が解消されている。
- 新しい test failure、syntax error、Ruff finding、whitespace error を導入していない。
- baseline の既存 pytest 未収集と Ruff findings を、新規結果から区別して説明できる。
- 公開 API、DB schema/migration、保存形式、設定、version、Android code に変更がない。
- Required Scope 外の変更、無関係な format、dependency 変更がない。
- 実行した全 command と終了 code、未実行 command と理由が記録されている。
- 未解決事項と D04-D08 の残存 risk が報告されている。
- 作業終了時の `git status --short` と changed path が報告されている。

pytest を dependency 不足で最後まで実行できない場合は DoD 未達であり、「実装完了」と報告しない。停止条件に従い利用者へ確認する。

## Reporting Format

実装担当モデルの最終報告は、次の順序で簡潔に記載する。

1. 実装した Debt ID と要約
2. 変更した file/symbol と理由
3. 保持した重要挙動
4. 実行した command、終了 code、結果、baseline との差
5. 実行できなかった検証と理由
6. Required から除外または中断した項目
7. 残存 risk と追加質問
8. 作業終了時の `git status --short`

失敗を省略せず、外部環境・実機で未検証のことを「確認済み」と書かない。

## Out-of-scope Items

- D04、D05 の実装。
- D06、D07、D08 の設計・実装。
- `ROKID_REAL_MODE`、provider fallback、real-exam policy の変更。
- raw JPEG の追加保存、normalized PNG の意味変更、schema/migration/retention 変更。
- Android relay、CXR-L/Global Hi Rokid、gesture、KeyCode、APK version の変更。
- 実機 shutter/flash/privacy LED behavior の断定。
- API field/status/error semantics、contract version の変更。
- matcher algorithm、threshold、production `/v1/match` の変更。
- `app/main.py` の全面分割、framework/ORM/queue 導入。
- dependency 追加・更新、Ruff auto-fix、既存 lint debt のついで修正。
- provider credential を使う cloud test、production/shared environment、deploy、release、migration、seed。
- compatibility shim と provider registry の削除・再設計。
