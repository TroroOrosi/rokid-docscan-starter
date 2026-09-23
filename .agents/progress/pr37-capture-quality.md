# 撮影品質の継続記録（PR #37 → PR #38）

Status: Internal progress。2026-09-23、PR37はmerge済み。利用者の新PR・必要作業の依頼に基づくPR38の画像比較・露出準備は末尾参照。撮影品質は未解決。標準JPEG8枚の距離・姿勢は未確認。追加撮影・GPT・APK更新・通常読取は停止を維持。
Runs on: Windows PC `C:\rokid-docscan-starter`。前段の実機試験はglassdocとF-51F上のサーバ・Chrome（既存Wi-Fi、スマホAPではない）。最新節はPCでの再点検。

## 再開点と権限（実装時点。後続の実機承認は末尾参照）

対象は [PR #37](https://github.com/TroroOrosi/rokid-docscan-starter/pull/37)、
`origin=https://github.com/TroroOrosi/rokid-docscan-starter.git`、`feature/multimodal-scan`。
清潔な `0be008a` から `git pull --ff-only origin feature/multimodal-scan` で
`781fa7d79d7f490aa435babbb8be6fed238e125a`（tree `08af722d78a47cd943aa7546a9b075d4db219b2c`）へ更新した。
今回の実装はこのHEADに対する追加変更。検証・コミット・pushの最終結果は下の検証欄を参照する。

[復元された実装要件](https://github.com/TroroOrosi/rokid-docscan-starter/pull/37#issuecomment-5725014528)
に従う。ZIPはローカルの確認範囲に見つからず、自己完結したコメントから実装した。
旧patch適用済み、旧候補tree・ZIPとバイト一致とは主張しない。
`pr37-objective-review.md`、`pr37-camera-research.md`、`pr37-offline-remediation.md`、
`pr37-predevice-handoff.md`、`multimodal-scan.md`を全文照合し、従来の停止を引き継いだ。

- 実機撮影・録音・APK導入・実資料の外部送信は停止のまま。今回実行していない。
- 通常の追加commit/push/PR #37更新は許可範囲。mainへのmerge、別PR、履歴変更は対象外。
- クラウドCodexの起動・再委任は撤回済み。今回も行わない。
- 原本・pending・manifest・DB・鍵・ブラウザ送信記録を変更しない。写真と派生物はGitへ入れない。
- 31ファイル統合は最終の撮影品質ゲート完成を意味しない。

## 全31ファイルの対応台帳

「今回統合」はコメントの要件への対応であり、旧ZIPとの同一性ではない。

| # | ファイル | 状態 | 根拠・対応内容 |
|---|---|---|---|
| 1 | `.agents/progress/pr37-capture-quality.md` | 今回統合 | 本記録。停止、台帳、検証、残作業 |
| 2 | `CLAUDE.md` | 今回統合 | 文字枠の限界とPC品質ゲート未接続 |
| 3 | `README.md` | 今回統合 | 正本の版tuple更新、PC部品と本流の区別 |
| 4 | `android-relay/glassdoc/build.gradle.kts` | 今回統合 | versionName/code更新、依存・署名設定不変 |
| 5 | `android-relay/glassdoc/src/main/java/dev/rokid/docscanglass/doc/GlassesHudText.java` | 今回統合 | 構図確認のみ、画質未検証、距離・照明案内 |
| 6 | `android-relay/glassdoc/src/test/java/dev/rokid/docscanglass/doc/GlassesHudTextTest.java` | 今回統合 | 現行レビュー文字列と距離案内の回帰 |
| 7 | `android-relay/pagequality/src/main/java/dev/rokid/docscanrelay/PageFraming.java` | 今回統合 | TEXT_BOUNDS_ONLY、旧COMPLETE token復元 |
| 8 | `android-relay/pagequality/src/main/java/dev/rokid/docscanrelay/ShotScore.java` | 今回統合 | 欠け候補は負、非欠けは非負、非有限confidence対処 |
| 9 | `android-relay/pagequality/src/test/java/dev/rokid/docscanrelay/PageFramingTest.java` | 今回統合 | 限定表示と保存token互換 |
| 10 | `android-relay/pagequality/src/test/java/dev/rokid/docscanrelay/ShotScoreTest.java` | 今回統合 | 欠け順位、全欠け、負count、NaN/Infinity、null、同点 |
| 11 | `android-relay/relaycore/src/test/java/dev/rokid/docscanrelay/AutoCommitDecisionTest.java` | 今回統合 | 相対順位と後段の欠け拒否、既存helper互換 |
| 12 | `android-relay/relaycore/src/test/java/dev/rokid/docscanrelay/ReviewHeadlineTest.java` | 今回統合 | 文字枠を紙面合格にしない、旧token互換 |
| 13 | `app/version.py` | 今回統合 | APP/GLASSES_VIEW更新、HTTP API版不変 |
| 14 | `docs/README.md` | 今回統合 | 新runbook・進捗記録の分類索引、既存履歴保全 |
| 15 | `docs/capture-preflight.md` | 今回統合 | 原寸部品への案内、本流未接続 |
| 16 | `docs/capture-quality.md` | 今回統合 | PCコマンド、入力契約、校正と本流の限界 |
| 17 | `docs/multimodal-scan.md` | 今回統合 | 現行表示と未接続ゲート |
| 18 | `docs/real-device-operation.md` | 今回統合 | 構図確認と品質承認を区別、実機停止維持 |
| 19 | `docs/rokid-capture-research.md` | 今回統合 | PC部品追加と未校正の境界 |
| 20 | `docs/user-operation-guide.md` | 今回統合 | 操作者向け表示、PC部品未接続 |
| 21 | `scripts/capture_admission.py` | 今回統合 | 出所・構造・profileの照合、hold/retake/eligible |
| 22 | `scripts/capture_evaluation.py` | 今回統合 | 分割混入を拒否、test分のみ方式別集計 |
| 23 | `scripts/capture_geometry.py` | 既存で充足 | 変更せずfocus_metrics/detect_paper/rectifyを再利用 |
| 24 | `scripts/capture_quality.py` | 今回統合 | 原寸被覆、回転、上限、補正候補、常時hold、失敗時保全 |
| 25 | `tasks/plan.md` | 今回統合 | 31件の範囲と最終品質ゲートを分離 |
| 26 | `tasks/todo.md` | 今回統合 | CQ-1〜4と未完CQ-5〜9、別の既知課題を維持 |
| 27 | `tests/test_capture_documentation.py` | 今回統合 | PC/未接続/holdと残作業の資料契約 |
| 28 | `tests/test_capture_evaluation.py` | 今回統合 | 集計、重複、混入、上限、CLI |
| 29 | `tests/test_capture_geometry.py` | 今回統合 | パケットへのgeometry統合と見送り・不正四隅 |
| 30 | `tests/test_capture_quality.py` | 今回統合 | 元画素一致、全域被覆、EXIF、入力制限、失敗保全、補正 |
| 31 | `tests/test_versioning.py` | 今回統合 | 正本の版と対応 |

追加の必要変更は `DocScanController.java`（共有見出しの誤った合格と旧enum参照を修正）、
`tests/test_capture_admission.py`（出所・profile・不正/不明の回帰）、`docs/capture-geometry.md`
（既存coreのパケット統合先を明記）。既存 `tests/test_capture_geometry_core.py` は変更しない。
操作割当・可視ACK・3秒・撮影寸法・露出・回転設定・連写数・再試行方針・LED・依存関係は変更しない。

## 変更した挙動と未接続境界

Runs on: Java変更は共有品質部品とglassdoc表示。Pythonの新部品はPCのみ。

文字認識枠は紙面全体の合格を表さない。旧保存tokenもその意味で読み、既存保存物を移行しない。
連写は欠け候補を文字数だけで優先しなくなり、全欠けを品質合格にしない。同点は既存候補を維持する。
グラス表示は構図確認と未検証保存を明示する。凍結phone relayへ新UI機能を加えていない。

PCでは既存Pillowとgeometryだけで原寸タイル、任意の明るさ・台形補正候補、診断JSONを生成する。
カメラ、OCR、モデル、ネットワーク呼出しは加えていない。パケットは常時hold。
admissionは渡された証拠の評価だけで生成・認証をしない。検証済みprofileは既定で空。
evaluationは参照ラベル付きtest記録の集計だけで、方式選択・本番profile承認はしない。
詳しい入力契約は [capture-quality.md](../../docs/capture-quality.md) に集約する。

## 保存写真への適用

Runs on: Windows PC。2026-09-16に保存済みの原本4枚。追加撮影・送信なし。

入力は `data/device-setup/pr37-windows-3e4b777-20260916-200352`。
出力はGit対象外の `data/device-setup/pr37-quality-20260922`、集計は `saved-photo-results.json`。
Pythonで各画像に `build_packet(..., rotation=270, tone=True, auto_rectify=True, layout=...)`
を実行し、前後のSHA-256を比較した。終了0、`original_hashes_unchanged=4/4`。
いずれも原本4032×3024、向き補正後3024×4032、20タイル、decision=hold。

| 原本 | SHA-256 | 全画面の輝度p05/p50/p95 | 自動台形補正 |
|---|---|---|---|
| spread-stop-0.jpg | bbae642b444280eb3251ca0acdf02da3960b37f2e0a165956a9eb998dbf58589 | 0 / 11 / 67 | spreadのためsingle_page_required |
| spread-raised-0.jpg | 43f590dbc40b27442753c3f998d79e70b04f45b595996d6afd9591410635a527 | 0 / 7 / 62 | spreadのためsingle_page_required |
| single-page-0.jpg | 6440698b06335a0155076d7327e80342b404d93e5c9bcd29fbb69ffd3495e277 | 0 / 14 / 61 | border_contact |
| question-page-pending.jpg | 008ed4c84b91c050cb86d676614c85b0f43d325635e74cb5bb674b2aa3654ad1 | 1 / 12 / 66 | unknownのためsingle_page_required |

この輝度は紙面ROIではなく背景を含む全画面。鮮鋭度は62,208標本、stride=14の未校正診断。
overviewと単ページの原寸tile-011/補正候補を目視した。暗部補正はノイズも明るくし、細字の復元を
証明しない。question画像には紙面上のケーブルが見える。紙面完全性・OCR精度・単頁方式の優位は
評価していない。今回の4枚は校正/validation/test分離した参照データセットではない。

## 検証

Runs on: Windows PC。Python 3.12.10、JDK 17.0.20.1+1、Android SDK Platform 36、Gradle wrapper 9.4.1。

変更前の回帰再現:

- `gradlew --no-daemon :pagequality:test :relaycore:testDebugUnitTest --tests '*ReviewHeadlineTest' :glassdoc:testDebugUnitTest --tests '*GlassesHudTextTest'`
  → `21 tests completed, 5 failed`、`BUILD FAILED in 1m 2s`、exit 1。
- `gradlew --no-daemon --continue :relaycore:testDebugUnitTest --tests '*ReviewHeadlineTest' :glassdoc:testDebugUnitTest --tests '*GlassesHudTextTest'`
  → ReviewHeadline 3件中1失敗、GlassesHudText 4件中2失敗、`BUILD FAILED in 35s`、exit 1。
- `py -3.12 -m pytest -q tests/test_capture_quality.py tests/test_capture_geometry.py`
  → `37 failed`（未実装module）、exit 1。
- `py -3.12 -m pytest -q tests/test_capture_admission.py tests/test_capture_evaluation.py`
  → `62 failed`（未実装module）、exit 1。
- 追加した重なり幅の回帰を単独実行 → `1 failed`。末尾位置を詰める方式を直し、元画素の被覆を維持。

修正後の対象試験:

- `gradlew --no-daemon :pagequality:test :relaycore:testDebugUnitTest --tests '*AutoCommitDecisionTest' --tests '*ReviewHeadlineTest' :glassdoc:testDebugUnitTest --tests '*GlassesHudTextTest'`
  → `BUILD SUCCESSFUL in 21s`、47 tasks、exit 0（版更新前のコード検証）。
- `py -3.12 -m pytest -q tests/test_capture_quality.py tests/test_capture_geometry.py tests/test_capture_geometry_core.py tests/test_capture_admission.py tests/test_capture_evaluation.py`
  → `119 passed in 2.53s`、exit 0。
- `py -3.12 -m ruff check .` → `All checks passed!`、exit 0（資料追加前）。

最終レビューで追加した回帰:

- `py -3.12 -m pytest -q tests/test_capture_admission.py -k invalid_profile_collection`
  → `2 failed, 1 passed, 38 deselected in 0.09s`、exit 1。文字列の部分一致承認とNone例外を再現した。
  呼出側の検証済みprofileをID集合として検証し、不正な集合はholdにした。
- `py -3.12 -m pytest -q tests/test_capture_admission.py tests/test_capture_documentation.py tests/test_documentation_contract.py tests/test_versioning.py`
  → `74 passed in 0.88s`、exit 0。

最終ローカル検証（版更新・profile修正後）:

- `py -3.12 -m pytest -q` → `814 passed, 1 skipped, 1 warning in 75.25s (0:01:15)`、exit 0。
  `ROKID_CHATGPT_LIVE=0`、`ROKID_DATA_DIR`は新規TEMP専用ディレクトリ。skipは実送信試験。
  warningは既存FastAPI/Starlette TestClientのhttpx非推奨通知であり、依存を変更していない。
- `py -3.12 -m compileall -q app scripts tests` → 出力なし、exit 0。
- `py -3.12 -m ruff check .` → `All checks passed!`、exit 0。
- `git diff --check` → exit 0（改行正規化の警告のみ）。
- `.\android-relay\gradlew.bat --no-daemon test testDebugUnitTest assembleDebug`
  → `BUILD SUCCESSFUL in 1m 6s`、`199 actionable tasks: 27 executed, 172 up-to-date`、exit 0。
  JUnit XML集計は `391 tests / 0 failures / 0 errors / 0 skipped`。
  app 47、glassapp 6、glassdoc 87、glassinput 32、glassprobe 6、pagequality 21、relaycore 192。
- `.\android-relay\gradlew.bat --version` → `Gradle 9.4.1`、`Launcher JVM: 17.0.20.1 (Microsoft 17.0.20.1+1-LTS)`、exit 0。

APKはこの作業ディレクトリの上記build出力を検査した。APKの版はbuild.gradle.ktsを正本とする。
`aapt2`/`apksigner`はSDKのbuild-tools 36.0.0、両コマンドとも各APKでexit 0。

| APK | `aapt2 dump badging` のpackage / launchable-activity | `Get-FileHash -Algorithm SHA256` |
|---|---|---|
| `android-relay/glassdoc/build/outputs/apk/debug/glassdoc-debug.apk` | dev.rokid.docscanglass.doc / dev.rokid.docscanglass.doc.DocScanGlassActivity | 03e3b4233496059e386d94c60526474327df179b4d50d8f9d0c129e656758b24 |
| `android-relay/app/build/outputs/apk/debug/app-debug.apk` | dev.rokid.docscanrelay / dev.rokid.docscanrelay.MainActivity | 9b71590cd63b27412be03fe7b5aeae44ff4440cda54fde01571594b6710a476b |

`apksigner verify --verbose --print-certs` は `Verifies`、v2=true。
両者のcertificate SHA-256は `906307478018e09e2937cfd8042a674d27598767577e08a304472aae407ccacc`。
APK導入や接続端末の署名比較は行っていない。Android buildは実機検証ではない。

この記録を含むcommitのSHA・push結果・最終HEADのCIはPR #37本文で確定する。
保存前の `git fetch origin feature/multimodal-scan` と `git rev-parse HEAD origin/feature/multimodal-scan`
は双方 `781fa7d79d7f490aa435babbb8be6fed238e125a` を返した。他作業の上書きはない。

構造確認にはcodebase-memory Tier 2を使用したが、索引世代2026-09-14T07:22:29Zは古い。
coverageで変更済みJavaはmetadata_changed、Python新部品はnot_trackedだった。
28コードパスをcoverageで照合し、該当する実ソースと呼出先を直接読んだ。
code-review-graphの `detect_changes(base=781fa7d)` は旧索引 `0be008a` を基に23追跡変更を認識したが、
新規ファイルは含まれないため全件レビューの証拠には使っていない。
指摘されたDocScanController/countdown/version_infoは現ソース・LocalReview/版試験で補った。
新規部品は直接読み、全入力制限・原本保全・profileの不正な部分一致を確認した。
`rg`で新部品の参照はscripts/testsだけと照合。本流に品質ゲートを接続したとは主張しない。
選択skillはAgent Skills router → incremental-implementation/TDD、git-workflow-and-versioning、
codebase-memory、progress-checkpoint。最終差分はcode-review-and-qualityで確認した。

## 実装時点の残作業

Runs on: 当面の実装・検証はWindows PC。会場本流はglassdoc → スマホAP → スマホAPIであり、PC試験はその実機受け入れを代替しない。

1. PR #37本文のcommit・push・CI結果を読む。ソースが同一なら上記ローカル全体試験・APK検査を繰り返さない。
2. [tasks/todo.md](../../tasks/todo.md) CQ-5: 保存原本から紙面・文字・数式・図表の根拠を生成し、参照ラベルで校正する。自動profile承認はしない。
3. CQ-6: 新鮮な撮影前プレビュー、紙面四隅・余白・安定、同時出力/メモリ。撮影後burstを撮影前検査と呼ばない。
4. CQ-7: 同じ本撮影原本で再検査しcapture_id/source_sha256/rotation/policy/profile版を対応付ける。
5. CQ-8: 手動・自動・終了時・復元時の候補保全と正式登録を分離し、confirm/upload/サーバの全境界に同じゲートを接続する。遅延・timeout・不明はhold。
6. CQ-9: 3秒を品質承認にせず、HUDへ理由を出す。実機対応範囲内の調整と再撮影上限は既存停止・事前承認条件を守って扱う。

別の既知課題（完了録音の原本欠落、文書作成request ID/冪等性、長時間HTTPと進捗、答案追加更新、終了時UI待ち）は未解決のまま維持する。
CQ-5〜9とこれらの課題を、この31ファイル対応の完了へ含めない。

## 2026-09-22 CI再実行と承認後の実機試験

Runs on: CIはGitHub Actions。実機はglassdoc → 既存Wi-Fi → F-51F上FastAPI → 同じスマホ上Chrome CDP。PCは導入・SSH・証拠回収のみ。スマホAPが無効のため会場経路の受け入れではない。

実行対象は `57daf52cab4a9a92c1e712cafa714335a1767d10`、tree
`b9c696930d2557c9b53aae7e68f018a9808fda3b`。上の全体試験・APK検査を再利用した。
`gh run rerun <id> --failed` → 各exit 0。run `35727924039` / `35727924052` /
`35727917625` / `35727917622` のattempt 2はすべてcompleted/success。
`gh pr checks 37` → 全16 checks pass、exit 0。初回のartifact容量失敗を受けた削除・設定変更はない。

利用者はグラス `192.168.0.3:5555` とスマホ `192.168.0.6:38043` を明示した確認に
「撮影・解析を含む実機試験まで」と回答し、前段の実機停止をこの試験範囲で解除した。
承認は品質課題の解消を意味しない。エージェントは未解決の撮影範囲・暗さを十分説明せず、
1ページ試験へ進めた。利用者の指摘は「1ページを撮ったが視野が広く両面になった。
画面の枠よりも広い。部屋が明るいはずなのに画像が暗い」。追加撮影・追加送信を止め、
保存画像と現行ソースの照合へ切り替えた。端末接続だけで再試験を始めない。

### 導入と保全

- `adb devices -l` → RG_glasses / F-51Fの上記2接続。以後すべて対象serial指定。
- グラス: 実serial `1904092623381086`、firmware `1.25.015-20260903-150201`、API 32。
  スマホ: 実serial `ZY22LWGDCV`、build `W1VHS36H.80-34-2-2-1-5`、API 36。
  Hi Rokid `G1.13.8.0828`。今回はCXR-Lを使わずglassdocのcamera2経路。
- 上記APK SHAと既存署名の一致・versionCode増加を確認。
  `adb -s 192.168.0.3:5555 install -r <glassdoc-debug.apk>` → `Success`。
  導入前の私有データをtarで保全し、導入前後41ファイルのSHA-256は全件一致。
- スマホの旧app 55ファイルは改行正規化後 `3e4b777` と一致。DB・依存を変更せず現行appへ更新。
  `GET /health` → HTTP 200、既存23データhash・DB行数・envバイト不変。
  バックアップ: スマホの `~/rokid-backups/pr37-57daf52-20260922T125226Z`。
- TermuxのSSHとwake lock起動後、Chromeを前景へ戻した。スマホ内adb対象
  `emulator-5554` の実serialを照合し、
  `adb -s emulator-5554 forward tcp:9222 localabstract:chrome_devtools_remote` → `9222`。
  API/CDPともスマホ上。送信前journalはidle。既存キーを再利用し出力していない。
- グラスの接続先を同じスマホの現在IPへ更新。起動 → `Status: ok`、読取選択画面。
  起動後の変更は接続情報・表示設定。既存保存セッションの欠落なし。

### 1ページを意図した試験の結果

- `adb -s 192.168.0.3:5555 logcat ...` → 21:58:47〜21:59:00に撮影と単タップでの撮り直し。
  最終原本4032×3024、6,190,468 B、1139 ms。21:59:01.749の表示ACK後に3秒review開始。
  21:59:04.862の物理BACK、21:59:06.053のlocal commit、同06.060のfinalizeを記録。
- 保存はlocal session `dd0108b6-5328-4682-b6ef-b6e358a05737` の1画像。
  サーバdocument 13 / exam-session 5 / page 16。documents/pages/sessions/questionsは
  12/15/4/4 → 13/16/5/5、solutionsは0のまま。
- 原本JPEG SHA-256 `b2174b90e5f14718f75c06468378dc29f734700d840501fd3607145918daf686`。
  永続record SHA-256 `888c97b1823af82fe34ac84ab67d90202adbd36ca4fc72cac390fd37a7736041`。
  サーバPNGは3024×4032、SHA-256 `aec5c39eba94fabce32e25bfdf55cce93a667ff49e219a1a80185aa6fdebb528`。
  Pillow比較 → `rotated_original_equals_server_pixels: true`。回転以外の明るさ補正・切出しなし。
- 全画面輝度p05/p50/p95は1/35/80（背景込み。紙面ROIではない）。画像で見開き・広い背景・
  暗い紙面を確認。紙面左端は画面外へ続き、単ページ検証ではない。
  最終metadataは露出10,000,000 ns、ISO 50、ae_state=1。照度は測っていない。
- 現行 `HudView.drawGuide` は静的な方向目印でカメラ画角と未校正。
  `GlassCamera` は最大JPEGを取得し、目印に合わせたcropをしない。
  `reviewContrast` は確認表示だけ。PCの `capture_quality --tone` は本流未接続。
  `requestStill` はセッション構成直後に実行しAE収束待ちはない。暗さの根本原因かは未確定。
  「照明だけの問題」というソースコメントを撤回した。挙動・撮影条件は変更していない。
- 22:02:39.851 `REVIEW: Local session analysis finished` は答案成功ではない。
  `GET /v1/exam-sessions/5/answer-bundle` → HTTP 200、1 item、`status=failed`、`question_id=q5`。
  グラス表示「解析できません／送信結果の確認待ち。」。journalは `uncertain`。
  solver待機上限は既定180秒。22:04のスマホ画面では元のChatGPT応答が生成中だった。
  journal解除・再送・追加生成はしていない。
- `dumpsys media.camera` → `Active Camera Clients: []`。5秒間隔36標本の最大PSSは165,165 KiB。
  取りこぼしを含む標本最大であり、長時間メモリ試験ではない。

私有証拠: Git対象外 `data/device-setup/pr37-resume-20260922-214723`。
導入前tar・新session tar・原本record/JPEG・サーバPNG・logcat・画面・メモリ標本を保持。
recordのPillow直読は `UnidentifiedImageError`。既存 `CaptureReviewPersistence` の形式を照合し
JPEGを抽出した。原本の書換えなし。グラフは古いため該当ソースを直接照合した。

### 次に再開する順序

Runs on: Windows PC上の保存原本・現行ソースのみ。利用者がGPTを停止したため、実機試験・ブラウザ待機・追加送信を行わない。

利用者の最新訂正: OCR精度が低く、1ページだけでは設問に必要な資料も不足し得る。
「今やるべきは待つことではない」「実機試験も今やるべきではなく、それまでに画像の精度向上に
取り組むべき」「GPTは止めた」。これを以後の優先順位とする。

1. この利用者指摘と実測を先に読む。CI通過・導入成功を撮影品質の改善と扱わない。
2. 枠/画角と露出を別々に調べる。今回の原本でPC診断を行い、CQ-5〜9の未接続を解消する。
   表示枠の拡大や、照明・近寄る操作だけで解決したことにしない。
3. 実機・GPTには触れず、保存原本の切出し・明暗・OCR入力をPCで改善・比較する。
   TesseractはPCに既存導入済み（jpn / jpn_vertあり）。PCのOCR比較をグラスのML Kit精度と同一視しない。
4. 次の実機試験は、直した点・測る点を具体化してから再開する。スマホAP・長時間・録音・
   画質・全答案取得は未検証。LEDは外部観測しておらず、依頼もしない。

## 利用者訂正後の保存画像改善

Runs on: Windows PCのみ。撮影・導入・ブラウザ待機・GPT送信は再開していない。

`0fcd4da` に失敗試験・承認履歴・最新の停止指示を保存した後の変更。
原本5枚に `build_packet(..., rotation=270, tone=True)` を実行した。
従来の原寸タイルとgamma候補を保持し、全画面の原寸グレースケール補正を追加。
既存の四隅指定・射影変換にも同じ補正を接続し、未加工の派生画像も残した。
明るい上位1%だけを除いて白点を求め、黒側の少数の細線を百分位で潰さない。
濃淡幅16未満は増幅せず、全体のhold・品質未検証は維持する。

今回の画像の右紙面だけはPCで目視した四隅
`[[.402,.335],[.811,.340],[.795,.786],[.414,.813]]` で切り出した。
`paper-readable.png` は1238×1928。自動紙面検出の成功ではない。
出力: 私有証拠配下 `improved-packets/b2174b90e5f1-34u22117/`。
旧4枚の出力対応は `data/device-setup/pr37-resume-20260922-214723/improved-packets/saved-photo-results.json`。
SHA照合 → `original_hashes_unchanged 5 / 5`。見た目の明るさは改善したが、細字のぼけと欠けは残る。

### OCR比較と不採用の候補

Runs on: PCの既存Tesseract 5.5.0、`jpn_vert --psm 5`。ML Kit実推論ではない。

基準は今回の原本の正規化座標系でROI `[1740,1870,1985,2230]` にある33文字。
エージェントの目視転記であり、利用者確認済みの正解・独立test資料ではない。
NFKC後の英数字・日本語を対象に編集距離を数える探索的比較。全文正答率へ外挿しない。
半分画像はPillow BOX縮小で、Android decoder/RGB565の完全な再現ではない。

`py -3.12 data/device-setup/pr37-resume-20260922-214723/offline-quality/evaluate_reference.py`
→ 原寸の誤り4/33、原寸＋採用したPC明暗補正も4/33。半分は9/33、半分＋同補正も9/33。
黒白両端1%を切る別案は半分5/33だが、少数の細線を潰す合成反例があり採用しない。
射影変換4/33、同変換＋補正5/33、UnsharpMask候補は33/33。文字数増加を改善とは扱わない。

一時的にグラスOCRの復号Bitmapへ補正するコードも試作した。
no-opから `6 tests completed, 2 failed` を再現し、実装後は対象試験が通過した。
追加メモリを1行分に制限する試験と全Android buildも通過したが、上の実画像比較で精度向上を
示せなかったため、この自動適用は採用せず自分の試作差分だけをHEADへ戻した。
差分は私有 `data/device-setup/pr37-resume-20260922-214723/offline-quality/unadopted-android-contrast.patch` に保全。端末へ入れていない。
今後、明暗補正だけの試作を「画像/OCR改善済み」として実機試験へ進めない。

### 最終差分の検証と残る作業

Runs on: Windows PC。JDK/SDK/Gradleは前段と同じ。

- Python新機能の回帰は実装前 `5 failed, 34 deselected`、実装後の画像処理試験は `62 passed`。
- `py -3.12 -m pytest -q tests/test_capture_quality.py tests/test_capture_geometry.py tests/test_capture_geometry_core.py tests/test_capture_documentation.py tests/test_documentation_contract.py tests/test_versioning.py`
  → `95 passed in 6.18s`、exit 0。試作撤回・最終版pin反映後。
- `py -3.12 -m ruff check .` → `All checks passed!`、exit 0。
- `.\android-relay\gradlew.bat --no-daemon test testDebugUnitTest assembleDebug`
  → `BUILD SUCCESSFUL in 1m 2s`、199 tasks（29 executed / 170 up-to-date）、exit 0。
  試作撤回後にbuildし直した。JUnit集計391 / failures 0 / errors 0 / skipped 0。
- 実験中の全Python試験は `819 passed, 1 skipped, 1 warning in 102.40s`。
  最終差分の全体CI・commit/hashはPR本文で確定する。実機品質の合格ではない。
- 最終記録の相対パス2件を修正後、
  `py -3.12 -m pytest -q tests/test_capture_documentation.py tests/test_documentation_contract.py`
  → `24 passed in 0.87s`、exit 0。

再buildしたglassdoc APKは `aapt2 dump badging` で既存package/activityと一致、
`apksigner verify --verbose --print-certs` → `Verifies`、v2=true、上記certificateと一致。
`Get-FileHash -Algorithm SHA256` → `5bd97247394b24189b89788afe3d45f24af5a6f213f9cd2f40e905ffa4b68a80`。
これは停止後のPC build成果物であり、実機へ導入していない。

次は原寸の文字を保ったOCR入力と、参照資料に基づく紙面/全文評価を優先する。
現在のAndroid OCRは縮小入力のまま。単純な全画面原寸復号は既知のメモリ問題へ戻るため、
分割処理と文字・行の欠落/重複を同時に評価してから接続する。
自動画角合わせ、露出の原因解消、CQ-5〜9は未完。GPT待機や再撮影でこれを代替しない。

## 一次資料と対照撮影を判断へ反映する（後続で測定方法を訂正）

Runs on: この節の時点は一次資料調査・コード照合・端末read-only確認。以後の撮影結果と停止は次節を優先する。

PC処理は `5981c3a` でPRへ反映済み。`gh pr checks 37` → 全16 checks pass。
それを撮影品質解決と扱わない。利用者は「外部ソースや公式情報をもとに撮影情報を分析せず、
内部調査で決めつける」「実際に何枚か撮影する必要もあるのに求めない」と訂正した。
過去の研究資料はあったが、今回の判断前に一次資料を再照合して対照撮影へつなげていなかった。
停止指示を、必要な比較測定の設計・提案まで避ける理由にした点を是正する。

`verifying-premises` → `find-docs`を使用。Context7のCamera2 IDを解決してAE資料を取得し、
Android公式のAPI 21からの状態定義、Rokidの現行FAQ・独公式製品詳細・公式撮影記事を開いた。
旧global製品URLは404のため別の公式地域ページへ照合。公式資料・現物・推論は
[研究資料の2026-09-22節](../../docs/rokid-capture-research.md)で区別した。
固定焦点・34cm〜∞の公称範囲、撮影109°と表示30°、標準LLHDRを確認した。
この公称値は手元の細字可読性やCamera2での同じ処理を保証しない。

保存logcatのcapture_resultは4件すべてae_state=1。公式定義はSEARCHINGであり、
現行の即時撮影に対してAE未収束を検査すべき証拠。暗さの単一原因とは断定しない。
グラフcoverageは古かったためGlassCamera/CameraDiagnostics実ソースで照合した。
`adb devices -l` → RG_glasses `192.168.0.3:5555`、F-51F `192.168.0.6:38043`。
`adb -s 192.168.0.3:5555 shell getprop ro.build.version.incremental`
→ `1.25.015-20260903-150201`。共有DCIM/Cameraの存在と撮影前一覧だけを取得した。
一覧保存先はGit対象外 `data/device-setup/pr37-camera-baseline-path.txt` が指す。

同じページ・照明で標準カメラ40/50/60cm各2枚、計6枚を最初の対照基準として提案し、
直前の停止をこの撮影品質測定だけ解除する確認を出した。APK更新・通常読取・GPTは含めない。
6枚は距離による細字と撮影ばらつきの比較であり、統計的保証ではない。
承認後は1条件ずつ案内し、新規JPEGをコピーする。標準Hi Rokidの一括取込は写真削除を伴う
公式仕様のため使わない。次段のアプリ対照は同条件を揃え、送信を伴わない準備を先に行う。

利用者回答: 「6枚の比較撮影を進める」。上記の標準カメラ測定だけ承認された。
40cmの準備を案内し、変更可能な物理ボタン短押しの割当を確認中。
直前の `adb -s 192.168.0.3:5555 shell dumpsys media.camera` → `Active Camera Clients: []`。
資料試験 `py -3.12 -m pytest -q tests/test_capture_documentation.py tests/test_documentation_contract.py`
→ `24 passed in 0.84s`（承認追記前）。実機品質の合格ではない。

## 最新訂正: 5方向の点検と実際の席の制約

Runs on: Windows PC。追加撮影・導入・通常読取・GPT送信は停止。既存JPEGの読み取りと比較だけ。

利用者は短押し写真を確認し、最初の2枚と「少し離れて2枚」の撮影を報告した。
正確な測距を要求した案は撤回したが、その後も離れられる席を前提にしてしまった。
最新2枚を普段の着席位置と扱う根拠もない。利用者の訂正は「近づけても離れるのは条件次第で難しい」。
今後は目的達成・全体への影響・事実確認・未確認事項・指示漏れの5方向と、文字の判読を優先する。

### 原本と測定の限界

Runs on: 標準撮影は利用者の物理操作。回収・診断はPC。会場経路やアプリ画質の合格試験ではない。

私有出力先: `data/device-setup/pr37-camera-baseline-20260922-225825/`。
撮影前DCIM一覧との差分を明示serialの`adb -s 192.168.0.3:5555 pull`でコピーした。削除・Hi Rokid取込なし。
新規JPEGは準備時1枚、最初の報告に対応する時刻2枚、その後の区間5枚の計8枚。
報告枚数と一致しないため、末尾2枚だけを2組目や着席基準へ自動割当しない。
全8枚の距離・姿勢・撮影群を未確認へ訂正した。条件統制した6枚の実験完了とは呼ばない。
寸法は全件3024×4032、EXIF露光16.6〜25ms・ISO191〜318。暗いアプリ写真と同条件の対照ではない。
私有`pixel-audit/`の同一領域は原寸580×460と半分290×230。Pillow BOXで、Android復号／ML Kitではない。

`py -3.12 data/device-setup/pr37-camera-baseline-20260922-225825/audit_native.py`
→ `originals_unchanged 8 / 8`、`prior_hashes_match 3 / 3`。`native-metadata.json`へ全件のSHA・EXIF・未確認条件を保存。
文字数や輝度をOCR精度へ置き換えず、最新の2枚を校正に使わない。元JPEG・OCR本文・派生画像はGit対象外。

### 本流点検の結果と再開順

Runs on: PCの現行ソース `5981c3a`。グラフ2026-09-14のcoverageは古いため対象ソースへフォールバック。

[研究資料](../../docs/rokid-capture-research.md)に5方向の事実・根拠・未確認を記録した。
主な不足は、表示だけのguide/spread、背景込み半分OCR、撮影前の紙面／細字判定なし、
OCRゼロの自動撮影反復、品質ゲートなしの保存・送信、選択肢の偽問題化、全問待ち後の1回bundle取得。
`segment_problems`の合成入力「問1＋(A)＋(B)」→3問題。実写真での誤分割原因を確定したものではない。
既存の完了録音復元・文書作成冪等性・終了保存UI待ち・AP経路の未検証を消さない。

次は通常姿勢の制約を保ち、同一原本の全体の収まり／原寸細字／OCR入力の処理差を比較する（CQ-5）。
その後にCQ-6〜8の撮影・登録境界、RP-11/12の資料と分割、RP-15の答案追加取得へ戻る。
撮影方法は「さらに離れる」を必須にせず、対応可能な倍率・cropと単頁／見開きを判読で選ぶ。
実機でのzoom範囲・同時preview・露出収束・ML Kit精度は未確認。新たな撮影はまだ依頼しない。
本変更は点検・測定設計の訂正であり、製品コードの品質改善・実機検証を完了したものではない。

検証: `py -3.12 -m pytest -q tests/test_capture_documentation.py tests/test_documentation_contract.py`
→ `24 passed in 4.09s`、exit 0。`py -3.12 -m ruff check .` → `All checks passed!`、exit 0。
`git diff --check` → 空白エラーなし、exit 0（WindowsのLF/CRLF変換警告のみ）。
変更は既存の研究・plan・todo・本進捗の4ファイル。製品コード未変更につきAndroid再build・実機再試験なし。

## PR38: 同一文字の比較と露出準備（2026-09-23）

Runs on: Windows PC `C:\rokid-docscan-starter`。実機導入・撮影・通常読取・GPT送信は再開していない。

利用者「マージしました。新しくPRを作成し、必要な作業を行ってください。作業の方向性もぶれないように
整理してから行ってください」に基づく。PR37のmerge commitは `c8835ac0cbdc3d1863ff29153a19322a32d9efab`、
旧headとのtree差分なしを確認して `feature/capture-quality-readiness` を作成。
`0619251` にplan/todoのQN-1〜3と合格範囲を先に保存・pushし、
[PR38](https://github.com/TroroOrosi/rokid-docscan-starter/pull/38)をdraft作成した。
対象remoteは `https://github.com/TroroOrosi/rokid-docscan-starter.git`。このPRの通常commit/pushは依頼範囲。
最終commitはPR本文で確定する。冒頭の「別PR対象外」はPR37実装時点の履歴であり、今回の依頼が更新する。

### 変更と5方向の再点検

Runs on: 現ソースのCamera2準備経路とPC上の既存画像。物理カメラの改善は未検証。

| 方向 | このPRの到達点と残る境界 |
|---|---|
| 目的達成 | 原寸／半分／補間を同じ33文字で比較。誤り6/29/7/7。画素を保持する優先度の根拠であり全文精度ではない。露出未収束でも即時JPEGを要求する箇所を修正。 |
| 全体への影響 | 撮影入口GlassCameraだけに測光を接続。最大JPEG・回転・burst・retry・操作・正式登録・凍結relayは不変。露出準備の時間・電力・メモリが増え得るため実機受け入れは保留。 |
| 事実確認 | Camera2公式のAE/同時出力/ImageReader契約、保存dumpのzoomRatioRange=[1,8]・YUV640×480、原本hash8/8を照合。「列挙範囲未確認」を訂正。 |
| 未確認事項 | 最新2枚は席の基準ではない。ML Kit精度、紙面／細字／数式全体、実カメラの収束と最終JPEG、同時出力PSS、スマホAP経路は未確認。 |
| 指示漏れ | 後退・正確な測距を必須にしない。CQ-5〜9、資料不足・過去ページ訂正・分割RP-11/12、答案追加取得RP-15、録音復元・冪等性・終了保存待ちを未完で保持。 |

実装は列挙からJPEGと同じ縦横比、640×480画素以下のYUVを選び、AE CONVERGED後にJPEGを1回要求する。
測光状態の変化と経過時間だけを数値診断へ記録。null/SEARCHING/LOCKED/FLASH_REQUIREDは合格にしない。
全体15秒の期限を延長せず、timeoutはUNKNOWNを保ち再要求しない。測光Imageは即close、
成功・失敗・明示closeで全資源を解放。世代違い・重複・測光停止echoから撮影を増やさない。
previewの露出収束を画質合格・最終JPEGの収束保証にはしない。依存・schema・署名鍵の変更なし。

比較の原本hash・座標・方式・参照の限界・一次資料URLは
[研究の2026-09-23節](../../docs/rokid-capture-research.md)に集約。
一律拡大は原寸より良くならず不採用。原寸全文Bitmap化と自動明暗補正も採用しない。
私有出力は `data/device-setup/pr37-camera-baseline-20260922-225825/text-comparison/`。
元画像・OCR本文・参照本文をGitへ追加していない。

### PC検証

Runs on: ASCIIパスの本checkout、JDK 17.0.20.1+1 / SDK Platform 36・build-tools 36.0.0 / Gradle wrapper 9.4.1。

- 回帰RED: `.\android-relay\gradlew.bat --no-daemon :glassdoc:testDebugUnitTest --tests '*GlassCameraExposureTest'`
  → 模擬HALの準備を修正した後、旧実装の即時JPEGで `3 tests completed, 3 failed`、`BUILD FAILED in 23s`。
- 最初のGREEN: `:glassdoc:testDebugUnitTest --tests '*GlassCamera*Test'` → `BUILD SUCCESSFUL in 26s`。
- 追加した試験のCameraCharacteristics二重setが全体試験で失敗。模擬カメラを置き換えるよう試験側を修正し、
  `test testDebugUnitTest assembleDebug` → `BUILD SUCCESSFUL in 38s`、199 tasks、JUnit400件／失敗0。
- `py -3.12 -m pytest -q` → `819 passed, 1 skipped, 1 warning in 111.57s`、exit 0。
  LIVE=0、新規TEMPのROKID_DATA_DIR。skipは実送信、warningは既存Starlette/httpx非推奨。
- `py -3.12 -m ruff check .` → `All checks passed!`、exit 0。
- `compare_text.py` → 6/33・29/33・7/33・7/33、`original_unchanged: true`、exit 0。
  全8原本のSHA再照合 → `originals_unchanged 8 / 8`、exit 0。

最終コード（AE状態変化の数値診断を追加後）:

- `.\android-relay\gradlew.bat --no-daemon test testDebugUnitTest assembleDebug`
  → `BUILD SUCCESSFUL in 46s`、`199 actionable tasks: 7 executed, 192 up-to-date`、exit 0。
  JUnit XML集計 → `tests:400, failures:0, errors:0, skipped:0`。
- 研究資料の私有パス2件を修正し、
  `py -3.12 -m pytest -q tests/test_capture_documentation.py tests/test_documentation_contract.py tests/test_versioning.py`
  → `33 passed in 0.90s`、exit 0。`git diff --check` → 空白エラーなし、exit 0。
- `aapt2 dump badging android-relay/glassdoc/build/outputs/apk/debug/glassdoc-debug.apk`
  → package `dev.rokid.docscanglass.doc`、activity `dev.rokid.docscanglass.doc.DocScanGlassActivity`。
- `apksigner verify --verbose --print-certs <同APK>` → `Verifies`、v2=true、certificate SHA-256
  `906307478018e09e2937cfd8042a674d27598767577e08a304472aae407ccacc`。既存署名と一致。
- `Get-FileHash -Algorithm SHA256 <同APK>` →
  `4c96a139e1fe916ce4417e345038fe78634529689229f841a14dab873d80510f`。

これは本checkoutのPC成果物。端末にあるAPKの置換や、新しい実機動作の確認ではない。

グラフ索引は古く、coverageの変更済み／未追跡ファイルを直接読んだ。差分レビュー用graphも旧SHAのため、
未追跡ExposureTestを含む実ソースとGlassCameraのActivity生成箇所で補った。
Agent Skills router → planning/incremental/TDD、verifying-premises/find-docs、code-review-and-quality、
progress-checkpointを使用。サブエージェントやクラウドCodexへ再委任していない。

### 次に戻る作業

Runs on: まずWindows PC。実機作業はここに記載しただけでは再開しない。

1. QNのPC成果とCQ全体の未完を区別する。原寸領域OCRを既存メモリ上限で扱う方法を、領域境界の欠落・
   重複・文字順と一緒に比較する。33文字だけで既定方式を承認しない。
2. 同じ原本の紙面・文字の証拠を、候補保全／正式登録の全経路へ接続する（CQ-6〜8）。
   RP-11/12/15の資料不足・分割・答案追加取得を作業表から落とさない。
3. 実機でしか答えられない問いは、通常の着席姿勢・同じ紙位置で標準／Camera2を比較できる
   撮影だけの経路を準備してから具体化する。新しいAPKは未導入。測距・後退を必須にしない。

## 2026-09-23 目的と手段を分けた全工程の再点検（最新）

Runs on: Windows PC。実機操作・撮影・導入・GPT送信は実施していない。停止指示を維持する。

利用者の最新訂正: 「全体を見ろ」。OCRは判読性／画像登録の評価に使う手段であり、GPTへの
全文入力が目的ではない。音声もGPTへ原音を渡し、ローカル文字起こしを必須にしない。
前のQNだけでは全体の無駄を除去できていなかった。以下が旧OCR優先・ASR必須方針に優先する。

### 本流を追った結果と今回の変更

Runs on: 本checkoutのJava/Python実ソースとオフライン試験。graphは古いためcoverageで変更済み・未追跡を確認し直接読んだ。

| 工程 | 確認した事実・今回の対応 | 残る成立条件 |
|---|---|---|
| 姿勢・撮影 | HUDの未校正「40〜60cm離す」を除去。前のAE収束待ちは維持 | 普段の席での画角・細字・明るさ。3枚ごとの再測光・撮影の時間／電力は未測定 |
| OCR・登録 | 実際は`handlePhoto`→OCR callback→`stageCaptureReview`→確認3秒→`confirmPendingCaptureNow`→保存／送信。OCRより先に本登録する順序ではないが、判読合否で登録を止めていない | CQ-5〜8。ゼロOCR候補の破棄・反復、全画面縮小、紙面／図表の判定不足。認識終了と品質合格を同一にしない |
| 資料入力 | `document.md`、OCR本文／補正文、ASR文字起こし、本文400文字のlocatorを主経路から除去。全画像・原音を保持 | 画像結合後のモデル内部縮小と原音利用能力／正答は未測定 |
| 準備・送信 | 内容hashで入力を識別。同一会話の確認済み原本は画像を再符号化せず既存添付を使う。原本変更・会話変更・未確認時は再準備 | 毎問の原本hash読取は残す。端末速度改善の秒数は未測定。画像全体を永続メモリcacheしない |
| リスニング | 主経路のASR設定・推論・完了待ちを除去。チャンク保存・hash／sample／時計・欠番・再送・原音結合は維持。通常の音声upload入口もASRを起動しない | 原音を扱わない現行API adapterへ、文字起こし無しのまま自動fallbackしない。音声欠損で質問を続けない |
| 設問・解答 | OCRが取りこぼした選択肢数でGPTの原本ラベルを範囲外とし再質問する処理を止めた | `segment_problems`のOCR依存は残る。`問1…\n(A)…\n(B)…`が3問になる問題は未修正。原本上の解答欄との対応が必要 |
| 表示・復旧 | 既存の小問別保存、CLOSED、原音／写真再送と送信結果不明時の停止を維持 | `finalize-reading`が全問を同期処理してから返し、Activityはbundleを1回取得する。RP-15の逐次表示は未完 |
| 運用・開発 | 同じ準備処理を小問ごとに実行しない回帰を追加。全体レビューから外していた入口・fallbackも修正 | AP通し・長時間・容量・着脱復旧は未検証。CIのpush＋pull_request二重起動は別の低優先課題として残す |

図表や選択肢の構文を新しい推測で分類し直す、未校正confidence閾値を品質合格にする、停止中の実機で
設計不足を埋める、という変更は行っていない。既存8枚の距離・姿勢・撮影群は引き続き不明。
非ブラウザの互換経路は既存ASRを保持する。新依存・DB schema・撮影寸法／retry／gesture変更なし。

### 5方向の判定

Runs on: Windows PCの差分・現行ソース・既存測定記録。実資料の新しい外部送信はない。

- **目的達成:** 原本から記入用答案を得る目的に対し、不要なOCR入力・ASR待ち・再符号化・再質問を除去。
  文字の判読、必要資料、全小問対応、表示までの達成は未完了。PRをDraftのままにする。
- **全体への影響:** ChatGPT入口、旧画像／音声入口、音声受信・完了、fallback、HUDの再開文言まで確認。
  原本保存・整合性・再送・送信結果不明時の停止を弱めず、画像の大問絞り込みによる共通資料欠落も除去。
- **事実確認:** 登録前にOCR処理自体は存在するが品質ゲートではない。画像hash変更で会話を変え、
  OCR/ASR文字列変更だけでは会話を変えない回帰を実行。モデルが原本を読める／高精度とは断言しない。
- **未確認事項:** 実ML Kitの判読、校正、登録ゲート、OCR依存の設問分割、途中答案、原音利用、AP通し・電池・熱。
  Tesseractの33文字比較、PC試験、buildをこれらの実証にしない。
- **指示漏れ:** 全体の目的から要否を見直す指示を局所最適へ狭めたことを訂正。停止・後退不能・未校正距離を
  守り、旧ASR準備を主経路の前提として再要求しない。計画・task・runbookを同じ方針へ更新。

### PCでの確認

Runs on: `C:\rokid-docscan-starter`。Python 3.12、JDK 17.0.20.1+1、SDK Platform 36／build-tools 36.0.0、wrapper Gradle 9.4.1。

- 初回の回帰: `py -3.12 -m pytest -q tests/test_source_bundle.py tests/test_chatgpt_web_solver.py tests/test_listening_chunks.py`
  → `11 failed, 63 passed`。OCR資料、再生成、ASR必須を旧実装で再現し、修正後`74 passed`。
- 別入口の欠損原本／OCR本文回帰 → `3 failed`から修正。OCR由来の再質問、音声を失うfallbackも各1件REDから修正。
- 最終 `py -3.12 -m pytest -q` → `825 passed, 1 skipped, 1 warning in 102.51s`、exit 0。
  LIVE=0、新規TEMPのROKID_DATA_DIR。skipは実送信、warningは既存Starlette/httpx非推奨。
- `py -3.12 -m ruff check .` → `All checks passed!`。`git diff --check` → whitespace errorなし、exit 0。
- 最終 `.\android-relay\gradlew.bat --no-daemon test testDebugUnitTest assembleDebug`
  → `BUILD SUCCESSFUL in 1m 20s`、`199 actionable tasks: 19 executed, 180 up-to-date`。
  JUnit XML集計 → `tests:400, failures:0, errors:0, skipped:0`。
- `aapt2 dump badging <glassdoc-debug.apk>` → package `dev.rokid.docscanglass.doc`、activity `dev.rokid.docscanglass.doc.DocScanGlassActivity`。
  `apksigner verify --verbose --print-certs <同APK>` → `Verifies`、v2=true、既存証明書SHA-256
  `906307478018e09e2937cfd8042a674d27598767577e08a304472aae407ccacc`と一致。
- `Get-FileHash -Algorithm SHA256 <同APK>` → `f8ce7cefabac0c2c55b9a226418b57f56e51d391270d89d1cdb75381e02f9135`。
  APKは本checkoutで生成した未導入成果物。前節のAPK hashと混同しない。
- 未修正の分割を `segment_problems([(0, '問1 Choose one\n(A) apple\n(B) orange')])` で再現:
  `problem_count: 3 extra_labels: ['(A)', '(B)']`。これを修正済み・品質合格としていない。

### 再開時の判断順

Runs on: まずWindows PCの現行本流と保存原本。以下は実機・GPT送信の再開許可ではない。

1. 「OCRすること」ではなく、保存した原本の判読性を登録前に評価できるかをCQ-5〜8で確かめる。
   校正されていない指標を閾値だけ足してゲートにしない。候補保全・正式登録の区別を全経路へ接続する。
2. OCRを正解問題一覧の根拠にし続けない。原本上の小問／解答欄・共通資料を基準にRP-12を設計し、
   既存の小問別保存をRP-15の追加取得へ届ける。入力の不足をGPTの待ち時間で補わない。
3. 原音利用・実画像の判読など実機／実モデルでしか確かめられない問いは、停止を維持したまま
   同一条件で比較できる手順と合格基準を具体化する。距離を測らせたり、後退を前提にしたりしない。

## 2026-09-23 実機前のリポジトリ全体整理を保存（最新）

Runs on: Windows PCのみ。対象branchはfeature/capture-quality-readiness、継続先はPR #38。

利用者の依頼は「実機確認を行う前にリポジトリ全体や目的・機能の整理を行い保存」。
基準実装 `7a05928` を変えず、既存文書の役割・現状・履歴を整理した。

- `docs/requirements-audit.md`: 目的と使用条件、取得から終了・会場運用までの10項目、採否、
  CQ/RPへの対応、測定前の順序と5方向の点検を現行入口にする。旧FS/R/S/Xの対応と当時の証拠は保持。
- `docs/implementation-surfaces.md`: Androidだけでなく、サーバ、scripts、試験、CI、設定、
  作業資料まで所在を分類。部品があることと本流への接続・実機合格を区別する。
- `docs/exam-solver-architecture.md`: 全画像・原音経路と品質／小問／配送の未接続を冒頭へ。
  旧OCR優先／ASR／phone HUDの構成説明は履歴へ分離。README・CLAUDE・plan・todo・索引・決定記録も整合。
- 現行taskにも残っていた「全文OCR＋関連画像を比較基準」「ASR状態を準備条件」を修正。
  原本・原音、必要な小問、保存済み答案の表示を基準にする。CQ-5～9と未完RPは完了にしていない。

検査:

- `py -3.12 -m pytest -q tests/test_documentation_contract.py tests/test_surface_inventory.py tests/test_capture_documentation.py tests/test_versioning.py`
  → 初回 `38 passed in 1.20s`、最終 `38 passed in 2.85s`、exit 0。
- `git diff --check` → whitespace errorなし、exit 0。
- グラフcoverageの鮮度は古いため、現行ソース・tracked file一覧と照合。
  Python／scriptの宣言一覧は `py -3.12 -X utf8 -` でASTを読むだけとし、CLI・サーバ・実providerは起動していない。
- 文書のみの変更。全pytest／Android build／APK照合は前節の `7a05928` の証拠を保持し、今回は再実行しない。

### 次回の入口と停止条件

Runs on: Windows PCの現行ソース・保存原本。実機操作・追加撮影・APK導入・GPT送信は停止を維持。

まず全体整理を読み、判読・登録（CQ-5～8）→資料・小問・逐次答案（RP-11/12/14/15/16）→
中断・終了の接続へ戻る。実機だけで分かる疑問は、対象・通常姿勢・比較箇所・原本対応・判定／中止条件を
明記した限定測定にする。保存8枚の距離・姿勢を推定し直さず、最新2枚を着席基準にしない。
今回の保存は実装完了・画質改善・会場受け入れを意味しない。
