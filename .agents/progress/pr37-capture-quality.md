# PR #37 撮影品質部品の統合

Status: Internal progress。2026-09-22、31ファイル要件を現行ブランチへ統合しローカル試験を実施。本流品質ゲートと実機受け入れは未完。
Runs on: Windows PC `C:\rokid-docscan-starter`。保存済み写真とローカル試験のみ。

## 再開点と権限

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

## 次の作業

Runs on: 当面の実装・検証はWindows PC。会場本流はglassdoc → スマホAP → スマホAPIであり、PC試験はその実機受け入れを代替しない。

1. PR #37本文のcommit・push・CI結果を読む。ソースが同一なら上記ローカル全体試験・APK検査を繰り返さない。
2. [tasks/todo.md](../../tasks/todo.md) CQ-5: 保存原本から紙面・文字・数式・図表の根拠を生成し、参照ラベルで校正する。自動profile承認はしない。
3. CQ-6: 新鮮な撮影前プレビュー、紙面四隅・余白・安定、同時出力/メモリ。撮影後burstを撮影前検査と呼ばない。
4. CQ-7: 同じ本撮影原本で再検査しcapture_id/source_sha256/rotation/policy/profile版を対応付ける。
5. CQ-8: 手動・自動・終了時・復元時の候補保全と正式登録を分離し、confirm/upload/サーバの全境界に同じゲートを接続する。遅延・timeout・不明はhold。
6. CQ-9: 3秒を品質承認にせず、HUDへ理由を出す。実機対応範囲内の調整と再撮影上限は既存停止・事前承認条件を守って扱う。

別の既知課題（完了録音の原本欠落、文書作成request ID/冪等性、長時間HTTPと進捗、答案追加更新、終了時UI待ち）は未解決のまま維持する。
CQ-5〜9とこれらの課題を、この31ファイル対応の完了へ含めない。
