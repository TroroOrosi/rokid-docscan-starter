# 再開入口：次のセッションはここだけ読めば始められる

最終更新: 2026-10-31続行 — 4d2814f実CI/Android success、3.10/3.11/3.12/phone各1762pass57skip。録画V1修正/独立R0・現full Android622pass、APK照合済/導入0。原動画受領V1/V2各72pass/関連309pass、別監査中。詳細phone-work-connected-root-20261030.json。
Runs on: PC開発・独立監査、phone F51F/ZY22LWGDCV。会場は常時オンphone AP＋装着glassesのみ、PC/USB/毎回接続不要。本人「確認せずそのまま」継続。phone b2eb＋2script/4run保全、最終X11 exec到達/X1なし。Loader差はログ定型のみ・APK一致、app_process/同UIDlookup正常。GPT3/Drive原PNG21/folder1、glasses/実紙受入0。

## 0. 読み方（前提と資料に引きずられないため）

- 最初に読むのは本ファイルだけ。`tasks/plan.md`・`tasks/todo.md`・`docs/requirements-audit.md`・archive・`docs/hardware-measurements.md` は過去の記録で、誤りを含む。
- 設計の前に、利用者の過去の指示を読む。Claudeの記録（このプロジェクトの `~/.claude/projects/` 配下）、Codexの記録（`~/.codex/sessions/**/rollout-*.jsonl`、role user）、
  承認済み計画 `C:\Users\pupu_\.claude\plans\zany-churning-goblet.md`。利用者の案は要件として扱う。9/29、送信設計の指示（9/13・9/14・9/15）を忘れて作り直していた。
- 判断は目的で行う。「その画像からGPTが正答し、グラスで読めるか」。規則より合理的な判断を優先する（利用者、9/28）。
- 会場の1セッション（撮影→送信→解析待ち→閲覧130分→終了→付け直し）を利用者の立場で通して考える。電池・画面・カメラ・録音・容量・PCなしを含める。
- 公式資料で分かることは検索で確かめる。GPTへの試験送信で確かめない。
- 1セッション1役割。実装は担当エージェントに任せ、別の担当が次の実機・GPT実行に照らして監査する。stubでの確認を目的の確認と書かない。
- 置き換えた経路は、そのフラグ・試験・文書ごと同じ変更で消す。記録だけのコミットは作らない。新しい文書を増やさない。
- PCだけで完結する作業は質問せずに終える。承認を求めるのは、実機・スマホ・GPT送信の直前と、下の「利用者の判断が要るもの」だけ。
- 利用者が伝えたことは事実として書く。「不明」「断定しない」と書かない（9/30、利用者が停止した4bを「誰が止めたか断定しない」と記録した）。
- 他のエージェント（Codex、別モデル）の記録を引き写さない。書く前に実物（共有チャット・ログ・コード・端末）で確かめる。監査の提案は利用者の決定ではない。
- 本ファイルは1回の実行につき4行まで。PID・ハッシュ・ログは `data/device-setup/reports/` に置く。Codexにも同じ規則を `AGENTS.md` で渡している。

## 1. 目的と合格

目的：グラスで撮った問題ページの画像を、読める状態でChatGPTへ送り、小問ごとに解答用紙へ書く内容をグラスで読む。
合格：公式正解（`C:\rokid-exam-materials\kyotsu\seikai\`）と照合して正しい答えが、会場経路でグラスに表示される。一度も達成していない。

## 2. 利用者の決定（再質問しない）
- 10/30本人の最新指示: 「よいです。確認せずにそのまま進めてください。」。提示済可視起動を実行し、起動前guardの実測誤前提を最小修正・別監査後に続行。Work公開UIの通常確認/希望model・effort・Fast・既存Drive plugin選択も実施。Work=ChatGPTアプリ/Web、PC/有線/装着後接続不要、録画/静止画/AI/可変紙寸法・最小HUD・更新対応を教科計測より優先。固定順/全案自動採用にせず、画面以外の節電より精度速度。手動確認でPC作業を止めない。
- 10/1追加指示は旧待機規則より優先：装着直後に最初の画面、撮影／実写真3秒／答案表示以外は5秒無操作で消灯。合同英語は用紙を先に撮り、途中でも録音開始、撮影終了で画像だけ先に解答、原音完了後に同一chatへ音声を追加する。細字・数式・図表・縦書きの自動撮影を改善する。本人は共通テスト・東大二次の実紙試験を後日と指定し、今回はその精度を求める場合へ対応するPC実装を依頼した。最新追記は全機能の実装・確認後に準備を完了し、常時オンのスマホのテザリングへ接続したグラスを装着するだけでいつでも使える状態にすること。
- 最新指示（10/1）は以下の旧方式に優先：撮影・実画像3秒確認・答案閲覧中は点灯、解析待機・記入終了・終了時は消灯。写真へ案内文字を重ねず、答案は記入用全文と必要な導出・図を保つ固定一画面スライド、短答を詰めて操作を減らす。自動撮影の精度と表示枠より広く写る画角を修正し合理化する。本人は今回アプリを実行したがGPT出力が見えず、音量増加は本人の操作ミスで割当を明るさへ変更して解決、端末の自動消灯は「無し」にする予定。9/30のChromium永続profile/Boot/services/同一chatへの20添付以内順送信/自動撮影/記入終了後の終了操作を維持。本人はテザリング＋Wi-Fi中でsshd実行済み。旧初回導入と10/1新ネットワーク可視loginは承認済み・実行済みでlinker errorにより停止。その後libc++のみ29→30＋既存profile/SEND0で可視login retryのexact commandも本人「よいです」で承認・実行済み（両step exit0）。本人は「ログインしました」と報告、readonly画面取得exit0でログイン後ホームを確認（従来と違う理由を説明済み）。続くNew chatのexact commandは本人「はい」で承認・1回実行済み（5step/全体exit0）。続くモデルmenuのexact commandも本人「はい」で承認・1回実行済み（5step/全体exit0）。本人の最新説明「latestがモデル名はありませんが、実質的な最新のモデルということです。」を受け、readonly exit0で選択済みLatest＋Extra Highを確認、この組合せを維持する。services/headless・source更新・glasses変更・GPT送信は別承認。 10/2本人「はい」で旧phone-headless-stop-20261002.pyを1回実行host exit1（初期化NameError／browser前）、次の本人「はい」でv4を1回実行host exit1（browser後preflight）、readonlyで現在HTTP403／Cloudflare確認画面と判明。さらに最新本人「はい」でF-51F（ZY22LWGDCV）のphone-owned-browser-close-20261002.py --execute-approved-close-owned-browserを1回実行host exit1／native exit2 RuntimeError、Browser.close要求前に停止、GPT0。承認済み試行の自動再実行なし。続く本人「はい」で新phone-owned-browser-close-v2-20261002.py --execute-approved-close-owned-browserを1回実行host exit0／全4steps exit0、Browser.close1、対象消失・8000／9222閉・lock不在・protected／source／env／services不変。旧child exitcodeはunavailable、GPT0。可視起動は新phone-visible-browser-recovery-20261002.pyのPC preview／self-check12条件／明示ruffがexit0、V-EXIT-1修正済・独立Required0／Optional0まで準備済み。続く最新本人「はい」でF-51F（ZY22LWGDCV）のphone-visible-browser-recovery-20261002.py --execute-approved-visible-recoveryを1回実行host exit1／3identity exit0／native exit2、visible_startupで新child exit1 available=true、GPT0・UI入力0。再実行／headless起動・source／APK／Boot・services／SEND変更は未承認。 続く最新本人「はい」で復旧v2のphone-visible-browser-recovery-v2-20261003.py --execute-approved-visible-recoveryをexact承認し1回実行host exit0／全6steps exit0、X11＋CDP browser startup・preservedを確認、home3件のため認証／model／solver未確認、GPT0。承認は1回分消費済み、追加の起動／close／UI入力／モデル変更／GPT／source／APK／services／SEND変更は未承認。 続く最新本人「はい」でphone-visible-model-popup-verification-20261003.py --execute-approved-model-popup-verificationをexact承認し1回実行host exit1／steps0,0,0,2、ChatGptWebModelMismatchで停止。自身popup閉鎖・保全確認、モデル確認失敗、設定変更／GPT0。承認は消費済み、追加操作は未承認。本人は「モデル名が変更になったりUIが変更されても対応できるようになっていますか。」と質問した。 続く本人「はい」でphone-visible-model-popup-diagnosis-20261003.py --execute-approved-model-popup-diagnosisをexact承認し1回実行host exit0／4steps0、Latest checked／Extra Highとopened_menu_structure_unreadableを観測。自身popup閉鎖・保全確認、設定変更／GPT0。承認は消費済みで追加操作は未承認。 続く最新本人「はい」でphone-visible-model-popup-verification-v2-20261003.py --execute-approved-model-popup-verificationをexact承認し1回実行host exit0／4steps0、修正後functionでLatest＋Extra Highの選択・自身popup閉鎖・保全を確認。設定変更／GPT0、phone source／APK／Boot・services不変。承認は1回分消費済み、追加操作は未承認。 最新本人（10/3）は「起動しても前回設定したモデルになる」「今後モデルの表示名が変わる可能性がある」と述べ、急なWeb変更でも停止しない柔軟な使用を依頼した。旧未知表示名のみで停止する方針を更新し、保存選択・名称／UI変化へのPC対応を実装・別監査する。 続く本人「はい」でphone-headless-saved-login-verification-20261003.py --execute-approved-headless-saved-login-verificationをexact承認し1回実行host exit1／steps[0,0,0,0,2]、旧visible正常close後own headless1回起動、saved_login_public_stateでAssertionError、auth unknown／status未記録、model未到達。own child正常exit0・cleanup／保全確認、入力・GPT0。本人の可視ログイン報告は事実として維持。承認は1回分消費済み、修正版の再起動・UI入力・source／APK／Boot・services／SEND変更・GPT送信は未承認。 続く本人「はい」でphone-headless-saved-login-verification-v2-20261003.py --execute-approved-headless-saved-login-verificationをexact承認し1回実行host exit1／steps[0,0,0,2]、first_home_attachment_failed／attach_first_homeで停止、home5は許容、公開auth／HTTP／navigation／modelは未読。own headless1回起動・child正常exit0／cleanup・保全確認、入力・GPT0。本人の可視login報告は事実として維持。承認は1回分消費済み、追加実機・UI入力・source／APK／Boot・services／SEND変更・GPT送信は未承認。 続く本人「はい」でphone-headless-saved-login-verification-v3-20261003.py --execute-approved-headless-saved-login-verificationをexact承認し1回実行host exit1／steps[0,0,0,2]、同初回home接続は通過、home6／ready complete／visibility hidden／composer0／navigation1／HTTP状態取得不可、classify_public_auth_state・navigation_status_unavailableで停止。own child正常exit0／cleanup・保全、入力・GPT0、model未読。本人の可視login報告は事実として維持。承認は消費済み、再実行・追加起動／UI入力・source／APK／Boot・services／SEND変更・GPT送信は未承認。 続く本人「はい」でphone-headless-saved-login-verification-v4-20261003.py --execute-approved-headless-saved-login-verificationをexact承認し1回実行host exit1／steps[0,0,0,2]、initial_home_inventoryで7home中1homeだけhidden／interactive／challenge／HTTP403／composer0を公開読取、その後home_public_read_failed・CdpError、target未bind・model未読。own child正常exit0／cleanup・保全、入力・GPT0。本人の可視login報告は事実として維持。承認は消費済み、再実行・追加起動／UI入力・source／APK／Boot・services／SEND変更・GPT送信は未承認。 続く最新本人「はい」でv5のexact commandを承認。PC pin／prepare8／HEAD gate exit0、adb devices -l／mdns servicesもexit0だが対象0件のためv5を起動していない（承認未消費・実行0）。接続復帰後に同じ承認範囲で1回実行する。 続く本人「接続しました」でread-only devicesに同一F-51Fを確認し、保持済みv5 exact承認を1回実行（host1／steps0,0,0,2）。browser_absent_prerequisites／FileNotFoundErrorでheadless起動前停止、auth not_started・Input／close／GPT0。承認は消費済み、追加の実機・UI入力・source／APK／Boot・services／SEND変更・GPT送信は未承認。 actual v5は別監査Required0／Optional0。続くread-onlyで現在の期待X11 PID20968不在、profile／tmp／X1のUID・modeは既定、X1接続errno111を観測。pinned installed launcher SHA一致でDISPLAY／X11固定無しを確認。旧actualの欠落パスは記録されておらず遡及断定しない。確認用v6はinactive状態の前後保全へshared guardだけをPC修正、preview・生成guardの単一self-check・明示ruff exit0、独立Required0／Optional0・root記録済み。新v6は未承認・実機0、追加起動／GUI／GPT0。 続く最新本人「はい」でphone-headless-saved-login-verification-v6-20261003.py --execute-approved-headless-saved-login-verificationをexact承認し1回実行host1／steps0,0,0,2。inactive X11前後保全とheadless起動1・自身child正常exit0／cleanup／保全を確認、最初の8home public_evaluateでCdpError、公開auth行0・HTTP／login／visibility未読、target未bind・model／Input／GPT0。本人の可視login報告は事実として維持。承認は1回消費、追加起動／GUI／UI入力／source／APK／Boot・services／SEND変更／GPTは未承認。 actual v6別監査Required0／Optional0とroot照合を完了。PC診断で元query構文と4つのCdpError分岐を確認したが実機の元原因はまだ未分類。診断専用の新候補は最初のowned home1件・公開query1回のみ、モデル／Input／GPT0、認証・solver・U7判定は常にfalse。PC焦点self-check・明示ruff・独立監査Required0／Optional0を終えて新exact承認待ち。新候補の承認・実機実行は0で、追加実機／GPT／source／APK／Boot・services／SEND変更は未承認。 続く最新本人「はい」でphone-headless-public-evaluate-diagnosis-20261003.py --execute-approved-public-evaluate-diagnosisをexact承認。PC pin／prepare10／HEAD gate exit0、adb devices -l／mdns servicesもexit0だが対象0件のため診断を起動していない（承認未消費・実行0）。接続復帰後に同一F-51Fへ同じ承認範囲で1回実行する。GPT／モデル操作／source／APK／Boot・services／SEND変更は未承認。 続く本人「接続しました」でread-only devicesに同一F-51F（transport17）を確認し、保持済みphone-headless-public-evaluate-diagnosis-20261003.py --execute-approved-public-evaluate-diagnosisのexact承認を1回実行host1／steps0,0,0,2。home9／公開query1で固定CDP protocol_error -32000、公開state null、auth／model判定なし。自身PID18061のheadless起動1・child正常exit0／消失／cleanup／protected・services／inactive X11前後保全true、Input／GPT0。承認消費・追加実行なし、追加GUI／モデル操作／GPT／source／APK／Boot・services／SEND変更は未承認。本人の可視login報告は事実として維持。 続く最新本人「はい」でphone-headless-public-evaluate-diagnosis-v2-20261003.py --execute-approved-public-evaluate-diagnosisをexact承認し1回実行host1／steps0,0,0,2。home10の最初1件・公開query1で固定CDP protocol_error -32000／protocol_message_kind other、公開state null、auth／model判定なし。自身headless起動1・child正常exit0／消失／cleanup／protected・services／inactive X11前後保全true、Input／GPT0。承認は1回分消費済み、再実行・追加GUI／モデル操作／GPT／source／APK／Boot・services／SEND変更は未承認。本人の可視login報告は事実として維持。 続く最新本人「はい」でphone-headless-public-evaluate-diagnosis-v3-20261003.py --execute-approved-public-evaluate-diagnosisをexact承認し1回実行host1／steps0,0,0,2。home11の最初1件・公開query1でpinned CDP protocol_error true-int -32000／navigated_or_closed・string、公開state null、auth／model判定なし。自身PID30086/start173707420のheadless起動1・child正常exit0／消失／cleanup／protected・services／inactive X11前後保全true、Input／GPT0。承認は1回分消費済み、再実行・追加GUI／モデル操作／GPT／source／APK／Boot・services／SEND変更は未承認。本人の可視login報告は事実として維持。移動対閉鎖・引き金はまだ未区別。 続く最新本人「はい」でphone-headless-public-evaluate-navigation-wait-20261003.py --execute-approved-public-evaluate-navigation-waitをexact承認し1回実行host1／steps0,0,0,0,null。native0でhome12の最初同target公開read2／wait1・typed state取得、interactive／hidden／challenge true／HTTP403／composer0／login falseを観測、auth／modelの合格判定はしていない。自身PID4547/start174002762のheadless起動1・child正常exit0／消失／cleanup／protected-services／inactiveX11前後保全true、Input／GPT0。ホストsynthetic host_pipeline_stopped AssertionErrorとenvelope旧flag誤表記はPC不整合として調査する。承認は1回分消費済み、再実行・追加GUI／モデル操作／GPT／source／APK／Boot・services／SEND変更は未承認。本人の可視login報告と保存Latest＋Extra Highは事実として維持。 続く最新本人「はい」でphone-headless-owned-home-public-inventory-20261004.py --execute-approved-owned-home-public-inventoryをexact承認し1回実行host1／native2／results0,0,0,2。元home13中8件がtyped HTTP403／challenge／composer0、public read10／wait2。index8はquery0でoriginal_home_set_changed確認に停止、未読5／未着手4、個別assertと変化の原因は未記録。自身headless起動1・child正常exit0／消失／cleanup／protected・inactiveX11保全true、model／Input／GPT0。現承認は1回分消費済みで追加実機・GUI／source／APK／Boot・services／SEND変更・GPTは未承認、本人可視login／保存Latest＋Extra Highの事実維持。 続く最新本人「はい」でphone-visible-owned-home-public-probe-v2-20261004.py --execute-approved-visible-owned-home-public-probeをexact承認し1回実行shell host1／native2／results000002。新自身tabはtyped complete／visible／HTTP200／composer1／challengefalse／loginfalse（read24・loading待23）、個別close1の確認はAssertionErrorで未達、失敗assert未記録。自身browser child正常0／消失／保全、自身X11を起動保持（停止要求無し）、model／Input／GPT0。今回承認は1回消費済み、追加起動／GUI／source／APK／Boot・services／SEND変更・GPTは未承認。本人可視login／保存Latest＋Extra Highの事実維持。 続く最新本人「はい」でphone-headless-owned-new-tab-public-probe-20261004.py --execute-approved-headless-owned-new-tab-public-probeをexact承認し1回実行shell/native0・4results全0。新自身tabの公開read1はinteractive／visible／HTTP403／composer0／challengefalse／loginfalse、complete以降未観測。個別close1・消失確認と自身browser正常child0／消失／保全、既存X11保持を確認、model／Input／GPT0。今回承認は1回消費済み、追加実機／source／APK／Boot・services／SEND変更・GPTは未承認。本人可視login／Latest＋Extra High事実維持。 続く最新本人「はい」でphone-headless-owned-new-tab-public-probe-v2-20261004.py --execute-approved-headless-owned-new-tab-public-probeをexact承認し1回実行shell/native0・4results全0。public read2／wait1でinteractive→completeまで観測したがHTTP403／challenge true／composer0／loginfalse。自身tab close1／消失確認、自身browser正常child0／消失／保全、既存X11同binding保持、model／Input／GPT0。今回承認は1回消費済み。可視login／保存Latest＋Extra Highの本人報告は維持し、恒久拒否／login消失／headlessのみの原因とは判定しない。追加可視起動／UI／source／APK／Boot・services／SEND／GPTは未承認。 続く最新本人「はい」でphone-visible-owned-browser-resume-20261004.py --execute-approved-visible-owned-browser-resumeをexact承認し1回実行shell/native2／identity3行exit0。browser_absent_prerequisites／FileNotFoundErrorで起動前停止、browser_start0／bindingnull／handofffalse、CDP／close／model／Input／GPT0。原本は具体的な欠落path／call未記録。承認は1回消費済みで追加起動・再実行は未承認。後続readonly exit0で期待X11proc不在／X1connect errno111、同boot・UID、profile／launcher存在を観測（原本原因へ遡及適用しない）。本人可視login／Latest＋Extra Highを維持。 続く最新本人「はい」でphone-visible-owned-browser-resume-v2-20261004.py --execute-approved-visible-owned-browser-resumeをexact承認し1回実行shell/native0／5results全0。owned X11起動1→新しい出生bindingを渡して同profile可視browser起動1、owner／CDP／protected保全・CDPclientのみdisconnect／両者保持を確認。UI前景化／publicquery／newtab／model／Input／Browser.close／GPT0。承認1回消費済み、追加操作は未承認。その後本人はTermux:X11を開いた画面について「ChatGPTの入力欄が表示されています」と回答（事実。nativeのUI/auth/model未検証とは別の本人確認）。以前の可視login／Latest＋Extra Highを維持。 2026-10-04の保存選択確認exact質問に本人「はい」、指定v1を1回実行して承認消費（shell1／native2・[0,0,0,2]、public_read_revalidationで停止、Input／GPT0）。追加実機・後継v2は未承認。 続く最新本人「はい」で保存選択確認v2をexact承認し1回実行（shell1／native2・[0,0,0,2]）。public_auth_state_validation／returned_auth_shape invalidで停止、Input／GPT0、承認1回消費済み。追加実機と後継候補は未承認。 続く最新本人「はい」で保存選択v3 exact CLIを1回実行し承認消費（shell1）。先頭adb devices -lはexit0だが対象0でhost_assert停止、残2identity/native/Input/GPT未開始。追加connect/再CLIは未承認。 2026-10-04本人「はい」で固定mDNS connect→readonly identity→同v3 CLIを各1回承認し、connect already connected/exit0とCLI exit0・auth/Latest極高確認を実行して消費。Input4/GPT0、browser/X11・source/env/services/SEND0保全、追加source/APK/service/GPTは未承認。 続く2026-10-04本人「はい」で79ファイルのsource-only更新exact CLIを1回承認し実行（host/native0・identity3行0・native1回）。新版79hashとprotected/browser/X11の最終保全を確認、SEND0・Input/APK/services/GPT0、承認1回消費済み。API起動・APK・Boot/services・SEND変更・GPT送信は別承認。 続く2026-10-05本人「はい」でDB backup→SEND0 API起動exact CLIを1回承認・実行し消費（host/native0・4行全0/API1回・backup1回）。backup quick_check、AP health200、env0をreadonly確認、API/browser/X11保持、Input/APK/GPT/services0。本人はグラスについて「電源ON・テザリング接続中」と回答した。グラスADB接続・APK・watch・SEND変更・Boot/GPTは未承認。 続く本人「はい」で固定phone→glass接続exact CLIを1回実行し承認消費（shell1/host-native2、connect1・TimeoutExpired/read0、既存鍵/API SEND0/browser-X11/source-services保全true、GPT0）。本人は「グラスと接続済みです」と伝え、readonlyでPC USB1904092623381086・版31/0.24.1・同署名を確認した。USB新版APK更新/起動・watch/SEND/GPT/Bootは未承認。 続く本人「はい」でUSB更新/権限2/chooser1のef8c exact CLIを承認。readonly端末一覧のphone接続名が旧mDNSから192.168.0.5:40723へ変化し、旧known2guardに合わないため本体未起動・承認未消費・実機更新0。readonlyでglass1904/phoneZY22を確認。旧候補は変更せず、同じグラスだけを更新するv2のPC候補を準備・別監査する。新exact CLIは別承認、GPT0。 続く本人「はい」で新v2候補55d3のexact CLIを1回承認・実行し消費（f2fca0 exit0/17stage全0）。グラス1904へvc34/0.27を更新1、CAMERA/RECORD_AUDIO各grant1、chooser起動ack1。別actual監査R0/O0、旧ef8は未実行・承認未消費のまま。readonlyで新version/grants/WearService FG/currentAsleepを確認、物理画面・装着・5秒時間・実音・会場・正答/U7は未検証。追加watch/SEND/GPT/Bootは別exact承認。 続く本人「はい」で固定API復旧61804565のexact CLIを1回承認し、e9893f exit0/6stage全0で実行・消費。API/send0/保全と初期FG/CPUlockを確認、実施監査R0/O0。queryless state200と現在glass prefs一致は保存状態の一致で新着時刻は未測定。21時SmartBackground停止記録後もAPI8496は継続するが、FG/CPUlockは不在。既消費25、追加GUI/watch/保持復旧/SEND/GPT/Bootは別exact承認。 続く本人「はい」でc9c5のGUI/watch/wake1＋公開BatteryCare画面1をexact承認しc780dd exit0で1回実行・消費。SDK事前guardのGet-FileHash例外後にも続行したため実施監査R1/O0、六段階は全0・API保持/SEND0/GPT0。本人はTermux「常に許可する」を「設定しました」と回答し、「ログアウトしていたので、ログインしました」と報告、さらに再logoutしてagentがGoogleを押す復旧を依頼した。RO guest home/header Log in入口のPC準備・別監査R0/O0後、今回の本人「はい」でa251 exact CLIを1回承認・実行し84430f exit0で入口/Google各1を消費27へ追加。RO04013d exit0は既存composer一致1/profile可視/guest Log in0でログイン後home復旧を確認、追加click/Input/GPT0、別actual監査b441 R0/O0。既c9c5実施R1/旧ef8未消費は保持。23時SmartBackground killを2ad587 exit0で測定、本人のTermux常に許可設定を事実として保持。controller0035の限定PC解析と公開設定入口a4deのPC5case/別監査R0/O0を終え、前景変更1の新exact承認を待つ。設定toggle・追加wake・起動・GPT送信は含めない。
- 運用者決定（2026-10-13）: モデル表示がLatest→GPT-6へ変わったことは本人報告の事実。今後も名称に依存せず旧Latestと同じ先頭位置を指定する。実紙の対象は英語を除く共通7教科/東大理科4教科で、各教科の複数年度を数値・グラフ・頁数・時間で比較した後に実紙測定を行う。PC処理時間はGPT解析時間ではない。先のyesは旧a4 exactに対する承認で、接続先変更後の6013へは移さない。
- 会場：グラス（`:glassdoc`）→スマホAP→スマホ上のFastAPI→スマホChrome（CDP）→ChatGPT web→answer-bundle→AnswerView。PCは持ち込まない。
  スマホは画面点灯・伏せ置き・Chrome前景（9/15）。ChatGPT webの自動操作は規約違反と承知のうえで選んだ。APIキーは使わない。
- **1教科1チャット・1教科1通**（9/29）。冊子の全画像を1通で送り、1通の返答で小問の仕分けと全部の答えを受け取る。小問ごと・大問ごと・一覧だけの送信はしない。
  仕分けはGPTが行い、グラスのOCRは使わない（9/29）。前の返答が完了する前に次を送らない（9/13）。解析時間に打ち切りを設けない（9/29）。
- 添付は1通20ファイルまで。20枚を超えたら2枚ずつ、40枚以上は3枚ずつ結合（利用者の案、9/15。`app/source_bundle.py`）。
  PDFは使わない：Enterprise以外のプランはPDFの文字だけを読み、画像を捨てる（OpenAI File Uploads FAQ、9/29確認）。
- 送るのは原本の画像と原音。OCR本文や文字起こしは送らない（9/23）。明るさ・切出しの処理はしてよい（9/27）。
- 答えは解答用紙に書く内容の全文。記述式の数学は導出を含める。着席、B5、見開き撮影が既定。
- 操作：起動時に通常かリスニングの二択。自動撮影、実画像を3秒表示、単タップで取り直し、ダブルタップで撮影終了。セッション中スマホは触らない。
  撮影終了後は答えが出るまで画面オフ、閉じるときも画面オフ（9/15）。30秒進展がなければカメラ休止（9/9）。
- リスニングの実機試験は後回し。LEDの外部観測は不要。LEDを操作するコードは書かない。依頼済みの機能は省かない（5節）。
- 9/30の4b再実行：問題用紙が全て揃っていないため、送信確認までで停止する（利用者）。同じ不完全な2枚の再送で正答を試さない。

## 3. 過去の測定記録（以下の版・条件に限定。現行PC作業のログ・比較・監査は `data/device-setup/reports/venue-pc-20260930/`）

- 9/29 4a旧方式（`e0b8263`）：一覧だけの1通のあと小問ごとに送り、利用者が停止。これを受けて1教科1通へ作り直した（`4552ea1`〜`1134404`、監査2回を反映）。
- **9/29 4a（`1134404`、スマホのサーバ）：4問すべて正解**（④②④②＝101〜104）。送信1通（画像2枚）・返答1通・102.6秒。入力は公式PDFの描画でグラスの写真ではない。
  報告 `C:\rokid-exam-materials\reports\butsuri_kiso-p1-4-server.json`。正誤はベンチではなく手で照合した。
- 1通の経路の要点：完了は返答の中身（JSON）と停止ボタンで判定、上限150分。送信済みのチャットがある教科は二度と送らず読み返す。再開は3時間以内のセッションだけ。
  添付はJPEG q92を1ファイルずつ。PDF経路は削除（Enterprise以外は画像を捨てる）。失敗経路は単体試験・stubだけで確認。
  glassdoc debug APK vc23 SHA-256 `584e526c534849da4558457b7533c8ca6c6b5016bc1645c24e0b59d382621d69`（`e12e155` でビルド、以後Java変更なし、未導入）。
- スマホ版ChatGPTの停止ボタンは一致する（§F-6-10：送信直後から stop=1、返答欄は130.4秒後）。
- 未確認の前提：ChatGPT webが録音ファイルを聞くか（公式FAQに音声の記載なし）、実機でのJPEG添付。
- 実写22枚の測定（9/29、PC）：グラスOCRは撮影判断に使えない（7枚が0文字、紙の無い3枚を「完全」と判定）。紙の最大成分の面積0.06未満で紙なしを分けられた（該当3枚のみ）。
- **9/30 4b（`1134404`、グラスの見開き原本2枚）：不合格。** 送信1通・解析578秒・6問すべて `needs_input`（「ピンぼけで判読できない」）。
  送信・待機・理由表示・ベンチ終了は正常（セッション8、チャット `/c/6abbd310…`、送信記録idle）。報告 `data\device-setup\reports\glassdoc-kokugo-20260927-originals-server.json`。
  原因（写真を目視）：9/16の1枚は元からピンぼけで人も読めない（撮影側）。9/22の1枚は目では読めるが、見開き1枚だとモデルの縮小で1頁の画素が半分になる。
  APIの縮小規則（2048に収め短辺768）で再現すると見開きは842x768でカタカナが潰れ、頁ごとに切ると1頁768幅で読めた（ChatGPT webの規則は非公開）。
  「第一問」の漢数字が大問として認識されず、グラスで「全体」1群になっていた。
- **`f89a761`（APP 0.43.1 / API 1.29.1）**：見開きを綴じ目で右頁→左頁に分けて別画像で送る（`source_bundle._gutter`、分けられない写真は1枚のまま）。
  実物2枚で綴じ目を正しく検出（幅の0.489、0.470）。20ファイル上限と縦積み（2・3枚）は維持。漢数字の大問名を認識。
  検証：`py -3.12 -X utf8 -m pytest -q` → 964 passed, 2 skipped。`ruff` → All checks passed!。**分割頁の送信は下記4bで確認。判読・正答は未確認。**
  注意：分割で画像数が倍になり、見開き約30枚超（分割後60頁超）は3枚結合の上限を超えて失敗する（以前は見開きのまま送れた）。
- **9/30 4b（`f89a761`、分割あり）：送信だけ確認して利用者が停止**（問題用紙が揃っていないため）。写真2枚→**4画像**→1通（セッション9、チャット `/c/6abbe44b…`）。
  Codexが実施。配布tarのSHA-256とファイル内容を端末で照合、`solver_ready=true`、更新直後（送信前）は送信記録idle。**分割した頁が実際に送られることだけ確認。判読・正答・答案受信は未確認。**
  **生成は利用者がChatGPTの画面で停止した**（共有 `https://chatgpt.com/share/6abbf455-589c-83e8-9602-5b50b9fbd93f`、「Thinking を停止しました」）。
  停止までの約190秒、モデルは思考中にPythonで4画像を90度回転・拡大し、tesseractで縦書きを読もうとしていた。失敗ではない。
  ChatGPT webは添付画像を長辺2048へ縮小していた（page001R 1377x2428 → 1155x2048。計4枚とも長辺2048）。
  その後、ベンチとサーバを強制終了、`port_8000_closed=true`、送信記録は `uncertain`（session 9、`2217c5ce…`）のまま。証拠は `data/device-setup/reports/4b-f89a761-*`。
  ベンチのHTTP応答に断続的な `RemoteProtocolError`（4a・セッション8でも出ている。別接続の `/health` は200。原因未調査）。
- **9/30 修正（PC、未コミット→下記コミット）**：返答の各小問が印刷された解答番号（`answer_no`）を持ち、飛ばされた番号は `解答番号N` の `failed` 項目として残る。
  ベンチは `--answer-key`（JSON `{"101":"4"}`）で公式正解と全番号を照合し、1つでも違えば exit 2。鍵が無い場合も全問readyでなければ exit 2（旧: 1問readyで exit 0）。
  30秒1頁も登録されなければ自動撮影がカメラを休止し「撮影を休止／タップで再開」を出す。単タップがそのまま再開。録音は止めない。
  検証：`py -3.12 -X utf8 -m pytest -q` → 970 passed, 2 skipped。`ruff` → All checks passed!。`gradlew test testDebugUnitTest assembleDebug` → BUILD SUCCESSFUL、199 tasks。**実機・GPTでは未確認。**
  注意：`--key` はサーバのAPIキーで既に使われていたため、公式正解の受け取りは `--answer-key` にした（4節の記述を置き換えた）。
- **9/30 4c（スマホのサーバ `2e95baf`、物理基礎PDF全14頁＝見開き7枚、1通）：14/14正解**（101〜114、234.8秒）。入力はPDF描画でグラスの写真ではない。
  ベンチは当初12/14と判定したが、110と111を1項目「⑤,⑥」で返したのを照合が誤読していた（修正済み）。報告 `C:\rokid-exam-materials\reports\butsuri_kiso-14p-2e95baf.json`、正解 `C:\rokid-exam-materials\kyotsu\seikai\butsuri_kiso-key.json`。
  サーバは `127.0.0.1` にbindしており、グラスからは届かない。起動直後の約2分、セッション9の再開（読み返しのみ、送信なし）がブラウザを占有した。
- **9/30 会場用の導入（利用者承認）**：会場にWi-Fiは無く、グラスはスマホのテザリング、スマホはモバイル通信（利用者、9/30）。スマホのサーバ `20ed671` を `0.0.0.0:8000` で起動（PID 20698）。
  グラスへ vc26 0.23.0 を導入、接続先 `http://gateway:8000`（Wi-Fiゲートウェイ＝スマホ）と鍵をアプリの初回設定ファイル（`ConnectionSettings.provisioning`）へ標準入力で投入、`manual=true` で起動。
  見張り役 `watch_glasses.py --serial auto`（PID 21730）は、グラスがテザリング経由で最初にサーバへ届くまで待機中。**テザリング上では未検証。**
  更新前バックアップ `~/rokid-backups/pre-20ed671-20260929T195841Z`。スマホを再起動するとadbのTCPが消え、PCが要る（グラスは `persist.adb.tcp.port=5555`）。
- 手動撮影モード（vc25、`manual=true`）：自動撮影を始めず1タップ1枚。整った用紙でない紙を今日撮るため（利用者、9/30）。欠落検出は末尾の抜けを検出できない。
- **9/30に確かめた欠陥2件（Codexの指摘を私が再現。上で修正済み）**：
  - **返答に無い小問は、黙って消える。** 冊子の解答欄と返答を照合する処理がどこにも無い（`chatgpt_web.py` の検査は `questions` キーと各答えの形だけ）。モデルが1問しか返しても「完了」になる。
  - **ベンチは1問でも ready なら exit 0**（`run_exam_deck.py:695`）。公式正解との照合もしない。4aの「4問すべて正解」は私が手で照合した結果であり、ベンチの判定ではない。
- スマホの状態：サーバソースは `f89a761`、**プロセスは停止中**。更新前バックアップは `~/rokid-backups/pre-f89a761-4b-20260929T161503Z`（app・scripts・DB・browser-state・env）。試験時はChrome前景・Awake、Chrome `153.0.8010.52`、F-51F fingerprint `FCNT/F-51F/F-51F:16/W1VHS36H.80-34-2-2-1-5/64c964-a8f54:user/release-keys`。
  更新前のバックアップ `~/rokid-backups/pre-1134404-20260929T234008`。送信記録の解除は自動判定で拒否されるので、利用者が `!` で実行する。
  更新手順（9/29実績）：バックアップ（app・scripts・docscan.db・browser-state）→ `git archive <commit> app scripts | ssh ... 'cd ~/rokid-server; rm -rf app scripts; tar -x'`
  → 旧サーバ停止 → `nohup bash scripts/phone_serve.sh 127.0.0.1 > data/server-<commit>.log 2>&1 &`。PCからは `ssh -f -N -L 8000:127.0.0.1:8000 ...`（ssh `-i ~/.ssh/f51f_key -p 8022 u0_a26@192.168.0.6`）。
  ベンチの鍵は `ROKID_API_KEY` をスマホの env から読んで渡す（画面に出さない）。

## 4. 次の作業（Runs on: 開発PC＋接続F51F）：録画checkpoint→Android原動画転送。phone Java入口/実Loader診断をPC準備・別監査→限定実行→X11/browser→Work通常unmount実測/互換。原動画受領別監査・API版/全Python確認→AIfeedback・可変紙面を教科計測より先に継続。以下は旧経緯。

1. 済：独立監査2回（`4552ea1`、`4552ea1..e12e155`）の指摘を `61ad481`〜`1134404` で反映。
2. 済：4a（3節）。起動はスマホで `bash scripts/phone_serve.sh 127.0.0.1`、PCから `ssh -L 8000:127.0.0.1:8000` で投入した。
3. 済：4bは送信だけ確認して停止（3節）。同じ不完全な2枚を送り直さない。
4. 済：欠陥2件の修正とカメラ休止（3節）。受け入れ条件（4aの④②④②と正解101〜104で exit 0、1つ違えば exit 2）は
   `tests/test_run_exam_deck.py::test_the_bench_passes_only_when_every_official_answer_matches` で示した。監査は未実施。
5. **その後（実機、承認後）**：Runs on: スマホFastAPI＋スマホChrome、PCからHTTP。先にセッション9の送信記録 `uncertain` を利用者が解除する（下の判断1）。
   正解のある物理基礎の全14頁（`C:/rokid-exam-materials/kyotsu/butsuri_kiso.pdf`、正解 `C:/rokid-exam-materials/kyotsu/seikai/rika_kiso.pdf` 101〜114）を1通で送り、ベンチの `--answer-key`（JSONを先に作る）で全問を照合する。
   不完全な資料（国語の見開き2枚など）は送らない。
6. Runs on: glassdoc＋スマホ。**承認後。** APK vc23を導入し、B5印刷の頁を着席で撮り、同じ経路で解かせる。
7. Runs on: 会場経路（スマホAP）。**承認後。** 撮影からグラス表示まで通す。最初の目的達成。

利用者の判断が要るもの（承認の境界に当たるものだけ）：
1. セッション9の送信記録 `uncertain` の解除。利用者が生成を停止したので返答は無い（共有チャットで確認済み）。解除は自動判定で拒否されるため利用者が `!` で実行する。
   解除しないと次の送信がすべて止まる。
2. 撮影の判断からOCRを外す（1枚撮影と「紙が写っているか」の判定。CLAUDE.mdは撮り直し方針の変更に確認を求める）。読めない撮り直しに上限を設ける。
3. 閲覧中は画面を消し、タップで点灯する（監査の提案。依頼済みではない）。4. 失敗した教科をグラス操作で送り直す（新しい操作割当＋新規送信）。
5. サーバの保存画像をPNGからJPEGへ（CLAUDE.mdの不変条件）。6. スマホ単体でadb（端末の安全設定）。7. 録音を聞けるかの短い試験送信1回。
8. 未使用のエンドポイント・モジュール・古い文書の削除、Codexが残した一時ファイル（PCの `data/device-setup/{apply-phone-f89a761-4b.py,probe-4b-counts.py,server-f89a761-4b.tar}`、
   スマホの `~/rokid-server/data/server-*.tar` と古い `*.pid`）の削除（9/28の取り決め）。
（9/30訂正：Opus 5が「判断待ち8項目は監査の提案で、カメラ休止と消灯は依頼済み」と書き、撮影からOCRを外す件を承認不要に移した。
カメラ休止と解析中の消灯は依頼済みだが、閲覧中の消灯は依頼に無く、OCRの除去と撮り直しの上限はCLAUDE.mdにより確認が要る。）

## 5. 依頼済み機能（全55項目の要約。細目は承認済み計画）

| 群 | 機能 | 現状 |
|---|---|---|
| 起動 | 二択で即開始、前回選択の強調、中断再開と前回答案は任意、HTTPを待たない開始 | 実装。実機は一部 |
| 撮影 | 自動撮影、単タップ手動、実画像3秒・取り直し、無操作で保存して次頁、ダブルタップ終了 | 実装。撮影の判断がOCR依存で機能していない（9/29実測。置換は判断2） |
| 撮影 | B5、見開き／単ページ、画角、露出、着席、傾き、同じ紙と似た別紙、図だけの頁、過去頁の訂正 | 露出は送信側で補正。重複判定は機能していない。傾き・過去頁は無 |
| 保存・転送 | 保存してから独立送信、容量不足で写真を止める | 前者は実装、後者は無（グラスに125MBが残る） |
| リスニング | 連続録音、二段階終了、末尾回収・再送 | 実装。マイク未試験。GPTが音声を聞くか未確認 |
| 資料→GPT | 原本だけ、1教科1チャット・1通、モデルの仕分け、添付上限と結合 | 実装（9/29） |
| 答案 | 記入用の全文と導出、試験形式別、図、表、資料不足の明示 | 導出は実装。表は部分的 |
| 閲覧 | 位置保持、大問→小問メニュー、BACKで一段戻る、前回答案をオフラインで | 実装。解析中の消灯は実装。閲覧中の消灯は未実装で、依頼済みではない（判断3） |
| 終了 | ダブルタップ2回で閉じて消灯、解析中の消灯と復帰、遅着で再点灯しない、再装着でchooser | 解析中は画面オフ（9/29）。即消灯は未達 |
| 会場 | スマホAP、スマホ操作0回、Chrome前景、PCなしで再起動 | AP経由は未実施。スマホ再起動後はadbにPCが要る（判断6） |
| 目標 | 撮影10分・解析10分・閲覧130分、150分で電池10%、1秒消灯・3秒、精度目標、反復 | 未測定 |

記録が1か所にしか無い要求：撮影終了の保留を表示、`(1)`形式の誤分割、1頁に収まらない共通資料、hotspotを切った状態での閲覧、
音声案内を録音に入れない、取消後もOCR 0文字で確認画像を待つ、操作応答p95 150ms以内、実写200頁で欠けた画像の誤採用0（`tasks/plan.md:632,638`）。

## 6. 古い資料のうち誤り・古いもの

- CQ-5〜9（OCRの校正、品質ゲート部品）は目的に対して優先度が低い。撮影判断からOCRを外す件（判断2）と合わせて扱う。
- `plan.md` と `todo.md` の `<details>` は履歴。そこに書かれた「現行」「再開」は作業指示ではない。

## 7. 状態

- CI：`9325ff1` で CI・Android relay とも success（36612357532、36612357069）。PR #38 は Draft。mainへの統合は4aで正答を確認してから提案する。

## 8. 設置物一覧（9/28に実機・ディスク・ブランチと照合）

| 場所 | 物 | 扱い |
|---|---|---|
| グラス `1904092623381086` | `dev.rokid.docscanglass.doc` 0.14.2（vc17） | 使用中。4でvc23へ更新 |
| グラス | `:glassdoc` 内 `files/local-scans` 15回分125MB | 残す。古い回を消す仕組みは無い（容量不足の機能と合わせて扱う） |
| スマホ F-51F | `dev.rokid.docscanrelay` 0.3.16、`com.termux` 0.118.3、`com.rokid.sprite.global.aiapp` | 凍結の予備経路／サーバ実行環境／Hi Rokid |
| スマホ Termux | `~/rokid-server`（9/30に`f89a761`へ更新）、env、旧ローカルモデルの重み（9/14不採用） | 重みは容量を確認してから、承認を得て消す |
| PC | `C:\rokid-docscan-starter`、`C:\Users\Public\rokid-build-tools-20260901`（JDK17） | 使用中 |
| PC | `data\device-setup\`（Git管理外の原本・APK・ログ） | 原本は残す。古いAPKは整理の役割で扱う |
| リポジトリ | `:glassapp`、`:glassprobe`（アプリは削除済み、CIで毎回ビルド） | 削除候補（判断8） |
| GitHub | `main`、`feature/capture-quality-readiness` のみ | 統合済みブランチ5本は9/28削除 |
