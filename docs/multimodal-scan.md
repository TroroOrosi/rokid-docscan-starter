# グラス撮影・画像資料・図付き解答・端末内ASR

Status: Current runbook for the implemented standalone route. 新しいAPKの実機受け入れは未実施。
Runs on: glassdoc → スマホAP → スマホFastAPI → スマホChrome CDP → ChatGPT Web。

## 操作

| 状態 | 単タップ | ダブルタップ | スワイプ |
|---|---|---|---|
| 自動撮影・待機 | 手動撮影。進行中の1枚があればその完了を待つ | 撮影を終了。最後の写真の確認・登録を待つ | — |
| 実画像の確認 | 取り直し | 撮影終了を予約 | — |
| 写真の送信失敗 | 取り直し | 保存した写真を再表示して再送 | — |
| 撮影終了・録音継続 | — | 録音終了、残りのASRを待つ | — |
| 解答表示 | 大問→小問を選択 | 2回で閲覧位置とCLOSEDを保存して終了 | 次／前のページ・設問 |
| エラー | — | 2回で終了 | — |

実画像を描画し、画面が見えると確認した時点から3秒後に登録します。画面が隠れた場合は
タイマーを止め、再表示後に3秒を取り直します。送信失敗は無限再試行せず操作を待ちます。
camera2は静止画を返す前に閉じます。タイムアウトはUNKNOWNを保持し、同じセッションで
追加撮影しません。LEDの物理状態は外部カメラで別途確認します。

照準の細い外枠はセンサー形状、内側の括弧は用紙形状です。設定時の`guide`値を保存します。
この図形だけでは実際の視野と撮影範囲の一致を証明できません。使用距離・眼位置で
撮影結果と枠を校正してください。画像の切り抜き、解像度変更、ズーム追加はしていません。

解析待ちと録音終了待ちはグラスの画面を休ませ、結果・エラーで復帰を要求します。
既存のSCREEN_OFF_TIMEOUT経路なので、瞬時の物理消灯ではありません。WRITE_SETTINGSが
許可されなければ画面に表示します。CPUのwake lockは待機中だけ保持します。
スマホは引き続きChromeを前景・画面点灯で保持します。

## 資料と図

- 画像の正本は向きを補正したPNGです。アップロードJPEGそのものはサーバに残しません。
- `ROKID_CHATGPT_INPUT_MODE=ocr-images`が既定です。全文OCRの`document.md`と、対象大問の
  ページ画像を同じチャットへ添付します。Markdownと画像にPage番号、本文にquestion_idと
  グラスの撮影要求時刻を付けます。旧写真は時刻不明として扱います。
- 同じ資料はチャット内で再添付しません。録音・文字起こし・ページ変更は新しい入力として
  識別します。添付確認が取れなければ質問を送信しません。
- `merged-images`は全体の2～3ページ結合、`pdf`は従来PDFとの比較用です。画像は縮小せず、
  20MB超のPNGは高品質JPEGで再符号化し、それでも超えれば停止します。
  添付はMarkdownと原音を含め最大20ファイル。画像だけで20枚とは数えません。
- 解答の図は線分・折れ線・円・文字の検証済みJSONです。グラスはCanvasで描き、説明と
  ラベル全文もページ送りで表示します。長いラベルは図内の`[番号]`で本文を参照します。
  図を含むanswer-bundleはschema 2、テキストのみは既存schema 1です。
- 非対応の図、資料不足、読めない原音を黙って完成答案にしません。`needs_input`の理由を
  保存し、グラスへ返します。表や任意SVGを描く機能は含みません。

精度比較は未実施です。同じ撮影PNG/OCR、同じ設問・モデルで3モードの添付数・容量・
準備時間・解答時間・文字/数式/図の誤読と最終正答を比較します。PDF抽出文字や合成画像の
試験は撮影OCRの精度を証明しません。既存`run_exam_deck.py`はPCの部品比較用です。

OpenAIの[添付FAQ](https://help.openai.com/en/articles/8555545-file-uploads-faq)、
[PDF画像の説明](https://help.openai.com/en/articles/10416312-visual-retrieval-with-pdfs-faq)、
[画像入力FAQ](https://help.openai.com/en/articles/8400551-chatgpt-image-inputs-faq)を参照しています。
PDF内画像の扱いはプランに依存します。原寸添付はモデル内部の縮小を防ぐ保証ではありません。

## 端末内ASRの準備

Runs on: スマホのTermux。以下は導入用手順で、本変更では実機へ実行していません。

既存のPython/FastAPI/CDP環境に加え、ビルド時にgit、cmake、clangが必要です。
`scripts/build_local_asr.sh`は固定したwhisper.cppを取得・ビルドし、SHA-256を照合して
英語base.enモデルとSilero VADを保存します。既存ソースの変更やハッシュ不一致では止まります。
ビルド項目は[固定した公式CMake](https://github.com/ggml-org/whisper.cpp/blob/2eeeba56e9edd762b4b38467bab96c2517163158/CMakeLists.txt)を参照しています。

```bash
# リポジトリルート、スマホで実行
bash scripts/build_local_asr.sh
export ROKID_WHISPER_CLI="$PWD/data/local-asr/whisper.cpp/build/bin/whisper-cli"
export ROKID_WHISPER_MODEL="$PWD/data/local-asr/ggml-base.en.bin"
export ROKID_WHISPER_VAD_MODEL="$PWD/data/local-asr/ggml-silero-v6.2.0.bin"
python scripts/benchmark_local_asr.py /path/to/mono-16k-pcm16.wav
```

これらをFastAPIプロセスへ引き継ぎます。`GET /v1/listening-ready`が未設定なら503を返し、
録音を開始しません。このチェックはファイル存在の確認で、推論速度の合格ではありません。
録音と並行処理できるかは実音声でreal_time_factor（処理秒÷音声秒）と待ち行列を測ります。
1未満が処理追従の目安ですが、撮影・OCR・Chromeとの同居時にも確認が必要です。

glassdocの起動設定`listening=true`で録音を選択し、マイク権限を許可します。選択は保存されます。
録音はグラスのAudioRecord、ASRはスマホで動きます。30秒ごとのPCM16 WAVに前の1秒を重ね、
撮影とは別の送信キューで処理します。Silero VADは発話に200msの余白を付け、ASRの区間を
元録音の時刻へ戻します。VADで原音を削除しません。

グラスの`files/listening-{document_id}`と、サーバの`data/audio/document-{document_id}`に
原音を保全します。欠番・サンプル数・ハッシュ・時計連続性を検査し、完了時に重複1秒を除いて
`original.wav`を作ります。末尾を含む全区間のASRが揃うまで最終解析へ進めません。
同一チャンクの再送は冪等で、異なる内容では上書きしません。

文字起こしには原音時刻、チャンク番号、低確信語の要確認フラグを残し、原音も添付します。
問題番号・本文とPage/question_idを対応させるのはsolverで、撮影時刻だけでは断定しません。
原音をモデルが読めない場合、発音・強勢など原音が必要な設問は資料不足にします。

録音中断は画面を復帰させて通知します。送信失敗は保存したチャンクから再試行できます。
プロセス死亡後の途切れた録音を連続録音として再開する機能はありません。既存録音を残して
開始を拒否します。失敗資料を確認し、新しい文書で録音し直す必要があります。
会場での連続運用、折りたたみ復帰、原音添付の認識品質は実機未検証です。

ChatGPT Web UIの自動操作はOpenAIの利用規約に反し、アカウント制限のリスクがあります。
これは利用者が選択した解答経路です。端末内ASRはクラウドASRへ自動フォールバックしません。
