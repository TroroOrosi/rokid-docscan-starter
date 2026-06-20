# 将来対応アーキテクチャ（Future-proof Design）

目的: **モデル（Gemini/OpenAI/ローカルOCR）や端末/SDK（Rokid CXR、Android XR、
iOS）が将来新しくなっても、サーバのコア（照合ロジック・API契約）を壊さずに
差し替えられる** 設計を、具体的なインターフェース付きで定義します。

設計原則は **ポート&アダプタ（Hexagonal）+ レジストリ + 契約バージョニング**。

```
            ┌──────────────────────────────────────────────┐
   端末 ───▶│  HTTP API (versioned contract /v1, versions{})│
            │      app/main.py  ← 安定した envelope          │
            └───────┬───────────────────────┬───────────────┘
                    │ port                   │ port
        ┌───────────▼─────────┐   ┌──────────▼───────────────┐
        │ Analyzer port       │   │ Matcher (deterministic)  │
        │ app/analyzers/base  │   │ app/matching.py          │
        └───────────┬─────────┘   └──────────────────────────┘
                    │ registry (差し替え点)
   ┌────────────────┼───────────────┬──────────────┐
   ▼                ▼               ▼              ▼
 local(今)        Gemini          OpenAI         Rizon/on-device(将来)
 offline          cloud           cloud          workflow / 端末OCR
```

---

## 1. ポート&アダプタ：Analyzer（実装済みの差し替え点）

サーバは具体ベンダを知らず、**安定インターフェース** だけに依存します。
（実コード: `app/analyzers/base.py`）

```python
# port (契約) — これは変えない。変える時は ANALYZER_API_VERSION を上げる。
class Analyzer(abc.ABC):
    name: str               # registry key: "local"|"gemini"|"openai"|"rizon"
    provider_version: str   # モデル/アダプタの識別子（レポートに出る）
    offline: bool           # 認証不要・ネット不要なら True

    @abc.abstractmethod
    def analyze(self, *, image_path=None, ocr_text=None,
                max_summary_len=48) -> AnalyzerResult: ...

@dataclass
class AnalyzerResult:
    text: str | None        # OCR テキスト
    summary: str            # HUD 用の短文
    language: str | None = None
    embedding: list[float] | None = None  # 将来の意味照合用
    extras: dict = {}
```

### 新しいモデルを足す＝アダプタを1つ書いて登録するだけ

```python
# app/analyzers/gemini.py （将来・本MVPには含めない）
class GeminiAnalyzer(Analyzer):
    name = "gemini"; provider_version = "gemini-x.y"; offline = False
    def __init__(self, client): self._c = client      # creds は外から注入
    def analyze(self, *, image_path=None, ocr_text=None, max_summary_len=48):
        # self._c.generate(...) を呼び、AnalyzerResult に詰める
        ...

# 起動時 or プラグインで:
register_analyzer(GeminiAnalyzer(client=build_client_from_env()))
```

`app/main.py` の `finalize` は `get_analyzer().analyze(...)` を呼ぶだけなので、
**エンドポイントは一切変更不要**。

---

## 2. モデルプロバイダ・レジストリ＋ルーティング（実装済み）

（実コード: `app/analyzers/registry.py`）

```python
register_analyzer(analyzer, replace=False)   # 追加
list_analyzers() -> [ {name, provider_version, offline}, ... ]
get_analyzer(prefer=None) -> Analyzer        # ルーティング
```

ルーティング優先順位（フェイルセーフ付き）:

1. リクエスト/呼び出しの `prefer`（例: 端末ヒント）
2. 環境変数 `ROKID_ANALYZER`
3. `DEFAULT_ANALYZER`（= `local`）
4. 要求アダプタが無い/creds 無し → **offline local に自動フォールバック**

これにより、クラウド障害・圏外でも HUD は返り続けます（D6 オフライン要件）。

---

## 3. デバイスバックエンド・レジストリ（クライアント側の将来設計）

サーバは HTTP 契約だけ公開するので端末非依存ですが、**コンパニオン側** も
同じ発想で抽象化します（jlink-ai 風の接続抽象。本MVPはサーバのみのため擬似コード）。

```kotlin
// クライアント側ポート（Android/iOS/Rokid/Android XR 共通）
interface GlassesBackend {
    val name: String                 // "cxr-l" | "rokidbrew" | "android-xr"
    val sdkVersion: String
    suspend fun capture(): Frame     // カメラ1フレーム
    suspend fun showHud(lines: List<String>)  // 3行HUD描画
    fun capabilities(): Set<Capability>        // ocrOnDevice, etc.
}

object DeviceRegistry {                // 端末を差し替える点
    private val backends = mutableMapOf<String, GlassesBackend>()
    fun register(b: GlassesBackend) { backends[b.name] = b }
    fun resolve(prefer: String?): GlassesBackend = /* prefer→env→default */
}
```

新端末（例: Android XR）対応＝ `GlassesBackend` を1つ実装して `register` する
だけ。上位の「capture → 端末OCR → POST /v1/match → showHud(hud.lines)」は不変。

---

## 4. 契約のバージョニング（実装済み）

（実コード: `app/version.py`、各レスポンスの `versions` / `GET /v1/version`）

| 契約 | 定数 | 何が変わったら上げる |
|------|------|----------------------|
| API envelope | `API_VERSION` | レスポンス JSON 形 / パス |
| 照合アルゴリズム | `MATCHER_VERSION` | pHash/しきい値/スコアリング |
| HUD ペイロード | `HUD_CONTRACT_VERSION` | 行数・フィールド |
| Analyzer 契約 | `ANALYZER_API_VERSION` | `Analyzer`/`AnalyzerResult` 形 |

- パスは破壊的変更まで `/v1` を維持。破壊的変更は `/v2` を **並走** させる
  （`/v1` を残したまま追加）。
- クライアントは `versions` のメジャー差を見て「更新を促す」分岐が可能。
- `MATCHER_VERSION` を上げたら **再インデックス/再評価**（`scripts/evaluate.py`）を
  実施するルールにする（保存済み pHash と非互換になり得るため）。

---

## 5. フィーチャーフラグ（設定で挙動を切替）

外部依存を増やさず、環境変数ベースの軽量フラグで段階導入します。

| フラグ | 既定 | 役割 |
|--------|------|------|
| `ROKID_ANALYZER` | `local` | モデルルーティング（§2） |
| `ROKID_DATA_DIR` | `data` | ストレージ先（プライバシー/隔離） |
| `ROKID_ENABLE_EMBEDDING` | `0` | 将来の意味照合（embedding）を有効化 |
| `ROKID_HUD_LANG` | `ja` | HUD 文言の言語（D4） |

```python
# 擬似: フラグの読み出しは一箇所に集約（app/config.py を拡張）
ENABLE_EMBEDDING = os.environ.get("ROKID_ENABLE_EMBEDDING", "0") == "1"
HUD_LANG = os.environ.get("ROKID_HUD_LANG", "ja")
```

フラグはデフォルト OFF・後方互換を壊さない範囲でのみ追加します。

---

## 6. 移行戦略（将来の変化シナリオ別）

### (a) ローカル → クラウド OCR/要約（Gemini/OpenAI/Rizon）
1. `GeminiAnalyzer` 等を `app/analyzers/<vendor>.py` に実装。
2. 起動時に `register_analyzer(...)`、`ROKID_ANALYZER=gemini` で切替。
3. creds は環境変数/シークレットマネージャから注入（リポジトリには入れない）。
4. 圏外/失敗時は registry が `local` に自動フォールバック（§2）。
5. API/HUD 契約は不変 → クライアント変更不要。

### (b) 決定的照合 → 意味照合（embedding）併用
1. アダプタが `AnalyzerResult.embedding` を返す。
2. `ROKID_ENABLE_EMBEDDING=1` の時のみ、`matching` に embedding 距離項を **加点**
   として足す（pHash 主・embedding 従でフォールバック維持）。
3. `MATCHER_VERSION` を上げ、`scripts/evaluate.py` で再評価。

### (c) Rokid SDK 更新 / 新デバイス（Android XR 等）
1. クライアント側で新しい `GlassesBackend` を実装・登録（§3）。
2. `sdk_hint`/`client_version` をリクエストに付与（サーバはエコー＆ログ）。
3. サーバは無変更。HUD は3行契約のまま、描画層のみ更新（Compose Glimmer 等）。

### (d) HUD 仕様変更（行数・言語）
1. `HUD_CONTRACT_VERSION` を上げる。
2. 旧クライアントは旧契約のまま動かしたい場合、`build_hud` を契約バージョンで
   分岐（`hud_v1` / `hud_v2`）させ、リクエストの希望バージョンで選択。

---

## 7. 「壊さない」ための不変条件（チェックリスト）

- HUD は常に **ちょうど3行・短文**（描画層が前提にできる）。
- `/match` は HIT/LOW_CONF/NO_PAGE のいずれかを必ず返す（沈黙しない）。
- analyzer は空入力でも例外を出さず、ベストエフォートで返す。
- 新規プロバイダ/デバイスの追加は **registry への登録のみ**（コア無変更）。
- 破壊的変更は新バージョンを並走させ、旧契約を即削除しない。
- アルゴリズム変更時は `MATCHER_VERSION` 更新＋`scripts/evaluate.py` 再評価。

---

## 参考（出典）

- [CXR-L SDK（Android/iOS） — Rokid AR Platform](https://ar.rokid.com/sdk?lang=en)
- [awesome-rokid（RokidBrew 等コミュニティ）](https://github.com/Anezium/awesome-rokid)
- [Rokid agentic AI / Rizon・Agent Store](https://www.globenewswire.com/news-release/2026/05/21/3299397/0/en/rokid-accelerates-agentic-ai-roadmap-for-smart-glasses-following-google-gemini-updates-at-i-o.html)
