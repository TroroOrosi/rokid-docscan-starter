# Gathered Capture, Stage 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Status: 実施計画（2026-11-15、本人の了承「進めてよい」＝準備を先に進める、を受けて作成）。Task 1〜3 は準備で、本人の手は要らない。Task 4 以降は、冊子が置かれてから。
Runs on: 机上のグラス（計測アプリ）、スマホ（Termux、公式 Codex CLI での読み取り）、PC。掛けない。会場の構成ではない。

**Goal:** 本番の暗さに置いた実物の頁を、設計どおりに録って重ねた画像が、明るい所の1枚撮りと同じ程度に読めるか（設計の G4）を判定し、目標の光・ビットレート・録画の型を実測で決める。

**Architecture:** 1本の道具（scripts の下の gather_stage2.py）が、構図と明るさの確認、条件を変えた録画、PC での重ね合わせ、スマホでの読み取りと採点を順に行う。読ませる頁・指示文・採点は、これまでの判読実験（§M-22〜§M-25）と同じものを使い、結果を直接比べられるようにする。判定の基準は下に固定し、結果を見てから変えない。

**Tech Stack:** Python 3.12、numpy、Pillow、ffmpeg、adb、計測アプリ `:glassprobe`、スマホの公式 Codex CLI（`gpt-6.1-sol`、`xhigh`）。

**Spec:** `docs/superpowers/specs/2026-11-15-gathered-capture-design.md`（6.3、6.5、6.6、9章 G4、10章の段階2）。前提の測定は `docs/hardware-measurements.md` §M-24〜§M-26。

## Global Constraints

- 本人にお願いするのは1回：国語の冊子（9/22 に掛けて撮った冊子）の問1（漢字）の頁を開き、机上のグラスの正面 35〜40 cm に、頁がグラスの方を向くように立てかけて置く。明るい状態で置いて知らせ、こちらの確認の後に明かりを消して（本番と同じ暗さにして）知らせる。掛けない。
- 明るさは測って報告する：暗くした後の自動露光を読み、本人の 11/14 18:46 の写真（60 ms・ISO 4032〜5688）と §M-24 の机上（70 ms・ISO 800・増幅 7.7〜7.9 倍）と並べる。離れていたら、その旨を言って調整をお願いする。
- 冊子の文面・正しい読みの控え・指示文は追跡対象外の `data/` に置く（公開リポジトリに試験の文面を入れない）。
- 読み取りは各条件 12 回。1回の結果から結論を出さない。条件は下の表のとおりで、増やす時は実行前にここへ書く。
- 本番アプリ `:glassdoc` を止めない。ギャラリーに写真を足さない。端末上でダンプを早く閉じるフィルターへ流さない。機器は毎回名指しし、シリアルを確かめる。
- モデルへ送るのは、この頁の画像と、既存の書き写しの指示文だけ。本番の経路（サーバー、Chat、Work）は使わない。

## 条件と、先に決めておく判定

読ませる画像は、どれも頁の範囲で切り出し、正立させ、サーバーと同じ送り方（行に沿った分割、長辺 2540）にする。誤りは、基準の 199 文字に対する編集距離の割合。

| 記号 | 条件 | 何を見るか |
|---|---|---|
| B | 明るい状態の1枚撮り（自動露光、原寸、カメラ任せの処理） | 基準 |
| N | 暗い状態で、原寸の直接のフレーム 120 枚を足したもの（動かないので流れなし、圧縮なし） | この距離でレンズとセンサーが出せる上限 |
| A-288 / A-144 / A-72 / A-36 | 暗い状態、2400×1800・毎秒 30 枚・露光 30 ms・ビットレート高（指定 40 Mbit/s）の録画 10 秒から、先頭の 288／144／72／36 枚を重ねたもの | 提案の方式と、要る光の量 |
| A-low | 同じ型でビットレート低（指定 12 Mbit/s）、288 枚 | ビットレート |
| W-576 | 暗い状態、1920×1080・毎秒 60 枚・露光 16.7 ms・ビットレート高の録画 10 秒から 576 枚（A-288 とほぼ同じ光） | 2つ目の型 |

読み取りは 8 条件 × 12 回＝96 回。

1. **G4**：平均(A-288) − 平均(B) が 2.0 ポイント以内なら通過。
2. **エンコーダーと重ね合わせが細部を保つか**：平均(A-288) − 平均(N) が 2.0 ポイント以内なら「保つ」。B は良いのに N が悪い時は、暗さそのもの（光の量）が足りていない。N は良いのに A-288 が悪い時は、録画か重ね合わせで失っている（設計の予備案を検討する）。
3. **要る光**：A-36、A-72、A-144、A-288 のうち、平均が B から 2.0 ポイント以内に入る最も少ない枚数を目標にする。その時にモジュールが返す「明るさ÷雑音」を、設計 6.6 の「足りた」の基準にする。全く読めない（平均 50% 超）最も多い枚数の値を「撮れていない」の基準にする。
4. **ビットレート**：平均(A-low) − 平均(A-288) が 1.0 ポイント以内なら低い方を採る。
5. **2つ目の型**：平均(W-576) − 平均(A-288) が 2.0 ポイントを超えて悪ければ、1920×1080 は候補から外す。そうでなければ両方を残し、段階4の記録で決める。
6. どの比較も、12 回の平均の差が基準の内か外かだけで決める。基準ぎりぎり（差が基準±0.5 ポイント）の時は「決まらない」と書き、その条件だけ 12 回足す。

読み取りを伴わない測定：露光ごとの1枚の効き目（2400×1800 で 10・20・30 ms、1920×1080 で 8.3・16.7 ms、各 5 秒。モジュールの「明るさ÷雑音」を枚数ごとに出す）。始める条件の材料（冊子あり・なしの、自動露光の画像を 320×240 に縮めたもの。枠の中の明るい面の割合）。

## Review Focus

1. 冊子が斜め・遠い・近い：構図の確認が、頁の大きさ（文字の画素数の見込み）を数字で出し、足りない時は録らずに止まる。→ Task 2
2. 暗くした後の明るさが本番と違う：確認が露光値を本番の値と並べて出す。→ Task 2
3. 録画の一部が失敗（セッションの拒否、停止の遅れ）：その条件だけ録り直せる。全体をやり直さない。→ Task 2
4. スマホの読み取りが途中で止まる（利用上限、通信）：済んだ回を数え、残りだけ再開できる。→ Task 2
5. 先頭の枚数を限って重ねる時、記録の枚数との対応が崩れない。→ Task 1

---

### Task 1: 先頭の枚数を限って重ねる

**Files:** Modify: `app/gather.py`、`tests/test_gather.py`

**Interfaces:**
- Produces: `gather_clip(path, record=None, *, limit: int | None = None, ...)`：最初の `settle` 枚を除いた後の、先頭 `limit` 枚だけを使う（記録の対応は `settle` と同じ位置から同じ枚数）。コマンドは `--frames <n>`。

- [ ] **Step 1: 試験を足す**

```python
def test_only_the_first_frames_asked_for_are_used(tmp_path):
    path = clip(tmp_path, frames(scene(), [(0, 0)] * 40, 4.0))
    short = g.gather_clip(path, limit=10)
    assert (short.used, short.total) == (10, 10)
    record = {"frames": [{"smear_px": 0.5}] * 10 + [{"smear_px": 9.0}] * 30}
    assert g.gather_clip(path, record, limit=20).used == 10 - g.SETTLE   # frames 6..9 pass; 10..25 are smeared
    long = g.gather_clip(path)
    assert long.level_over_noise > short.level_over_noise
```

- [ ] **Step 2: 失敗を確かめる** — `TypeError: gather() got an unexpected keyword argument 'limit'`
- [ ] **Step 3: 書く**
- [ ] **Step 4:** `py -3.12 -m pytest -q tests/test_gather.py` → `19 passed`
- [ ] **Step 5: Commit** — `feat: gather only the first frames of a clip, to measure how much light a page needs`

### Task 2: 段階2の道具

**Files:** Create: scripts の下の gather_stage2.py。冊子の文面に関わるもの（指示文、出力の形、正しい読みの控え）は `data/` の下（追跡対象外）から読む。

**Interfaces（コマンド）:**
- `frame`：自動露光の1枚を撮り、露光値を本番の値と並べ、明るい面の枠と、その高さから見込まれる1文字の画素数を出す。見込みが 12 画素未満なら「近づける」と出して終了コード 1。
- `capture bright` / `capture dark [--only 記号]`：上の表の録画・撮影を行い、作業フォルダへ取り込む。`--only` で1条件だけ録り直せる。
- `gather --page l,t,w,h --rotate 度`：各条件を頁の画像にし、枚数ごとの「明るさ÷雑音」を表にする。
- `reads prepare|run|score`：条件ごとの入力を作り、スマホで並行に読ませ（済んだ回は飛ばす）、採点して上の判定 1〜5 を出す。
- 文面に触れない部分（明るい面の枠、判定の計算）は、ファイルの中の `demo()` で自己点検する。

- [ ] **Step 1: 書く**（`demo()` を先に書き、通す）
- [ ] **Step 2:** `py -3.12 scripts/gather_stage2.py demo` → `ok`。`py -3.12 -m ruff check scripts/gather_stage2.py` → `All checks passed!`
- [ ] **Step 3: Commit** — `test: one tool for stage 2 of the gathered capture (frame, capture, gather, reads)`

### Task 3: 今の机上の場面で通しの予行（冊子なし）

- [ ] `frame` → 冊子が無いので「頁が見つからない／小さい」で止まることを確かめる。
- [ ] `capture dark` → 全条件の録画と直接のフレームが取り込まれる。失敗した条件があれば原因を直す。
- [ ] `gather`（頁の範囲は仮に画面の中央）→ 全条件の画像と表が出る。
- [ ] `reads prepare` と、`reads run --reads 1 --only A-36`（1回だけ。経路の確認）→ `reads score` が表を出す（文字は写っていないので全て誤りになる。それで正しい）。
- [ ] 予行の結果（所要、失敗、直した点）を §M-27 の前書きとして記録し、本人へ置き方をお願いする。

### Task 4（冊子が置かれてから）: 明るい状態と暗い状態を録る

- [ ] 明るい状態：`frame`（構図と文字の大きさ）→ `capture bright`。問題があれば置き直しをお願いする。
- [ ] 暗い状態：`frame`（露光値を本番と並べる）→ `capture dark`。

### Task 5: 重ねて、読ませて、判定する

- [ ] `gather` → 画像を目で見る（頁の範囲、向き）。`reads prepare` → `reads run`（96 回、スマホで約 2〜3 時間）→ `reads score`。
- [ ] 上の判定 1〜6 をそのまま当てはめる。露光ごとの効き目と、始める条件の材料をまとめる。

### Task 6: 記録と報告

- [ ] §M-27、設計書の該当箇所（6.3 の値、6.6 の基準、9章の G4、11章）、進捗の記録を更新する。全体の試験。独立の読み手による点検。本人へ結果と、段階3へ進めるかを報告する。
