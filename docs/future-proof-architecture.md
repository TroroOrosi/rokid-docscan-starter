# 将来対応アーキテクチャ（Future-proof Design）

Status: Conceptual extension guide. Current code, tests, and the contracts in
`docs/README.md` take precedence where examples here have aged.

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
 local(既定)   openai/gemini/claude(実装済)   Rizon/on-device(将来)
 offline          cloud           cloud          workflow / 端末OCR
```

> **同梱済みの実アダプタは `openai`（OpenAI GPT）/ `gemini`（Google）/ `claude`（Anthropic）**
> で、`ROKID_*=openai|gemini|claude` で全ポートを実 AI 化できます（§5 フラグ表・§6(a)）。
> なお exam の解答主経路はグラス搭載 AI（GPT/Gemini）の ingest（`POST /solutions`）であり、
> サーバ側アダプタは任意の高性能化経路。追加ベンダは同じ `Analyzer`/`Solver`/… ポートに
> アダプタを1つ実装して `register_*()` するだけ。

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
# app/analyzers/example_vendor.py （追加ベンダ例。openai/gemini/claude は同梱済み）
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
同じ発想で抽象化します（jlink-ai 風の接続抽象。本リポジトリはサーバのみのため擬似コード）。

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
だけ。上位の「視認＝その場認識 → POST /v1/match（テキスト） → showHud(hud.lines)」は不変。

---

## 4. 契約のバージョニング（実装済み）

（実コード: `app/version.py`、各レスポンスの `versions` / `GET /v1/version`）

| 契約 | 定数 | 何が変わったら上げる |
|------|------|----------------------|
| API envelope | `API_VERSION` | レスポンス JSON 形 / パス |
| 照合アルゴリズム | `MATCHER_VERSION` | pHash/しきい値/スコアリング |
| HUD ペイロード | `HUD_CONTRACT_VERSION` | 行数・フィールド |
| Analyzer 契約 | `ANALYZER_API_VERSION` | `Analyzer`/`AnalyzerResult` 形 |
| Solver 契約 | `SOLVER_API_VERSION` | `Solver`/`SolveResult` 形 |
| Explainer 契約 | `EXPLAINER_API_VERSION` | `Explainer`/`ExplainResult` 形 |
| Extractor 契約 | `EXTRACTOR_API_VERSION` | `MediaExtractor`/`ExtractorResult` 形 |
| HUD ステージview | `GLASSES_VIEW_CONTRACT_VERSION` | 段階view/`capture_ack` 形 |
| Overlay | `OVERLAY_CONTRACT_VERSION` | 解答欄box/tracking metadata 形 |

- 同じ API メジャーでは既存フィールドの意味を再解釈しない。新しい意味は新フィールドを
  加算してクライアントを移行する。
- パスや既存フィールドの意味の破壊的変更は `/v2` を **並走** させる
  （`/v1` を残したまま追加）。
- クライアントは `versions` のメジャー差を見て「更新を促す」分岐が可能。
- `MATCHER_VERSION` を上げたら **再インデックス/再評価**（`scripts/evaluate.py`）を
  実施するルールにする（保存済み pHash と非互換になり得るため）。

---

## 5. フィーチャーフラグ（設定で挙動を切替）

外部依存を増やさず、環境変数ベースの軽量フラグで段階導入します。

| フラグ | 既定 | 役割 |
|--------|------|------|
| `ROKID_ANALYZER` | `local` | 解析ルーティング（`openai\|gemini\|claude` で実 AI 要約） |
| `ROKID_SOLVER` | `local` | ソルバールーティング（`openai\|gemini\|claude` で実解答） |
| `ROKID_SOLVER_TIERS` | （単一） | 二段フォールバックの tier 順（csv、末尾に local を自動付与） |
| `ROKID_EXPLAINER` | `local` | 解説ルーティング（`openai\|gemini\|claude` で実解説） |
| `ROKID_EXTRACTOR` | `local` | メディア抽出ルーティング（`openai\|gemini\|claude` で実抽出） |
| `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`GOOGLE_API_KEY` | （なし） | 実アダプタの API キー（未設定なら local） |
| `ROKID_LLM_MODEL` | openai `gpt-4o` / gemini `gemini-2.5-flash` / anthropic `claude-opus-4-8` | モデル id（任意上書き） |
| `ROKID_LLM_MAX_TOKENS` | `1024` | 実アダプタの応答トークン上限 |
| `ROKID_KEYMAP` | （なし） | gesture→KeyCode の上書き（JSON、`/v1/settings.input`） |
| `ROKID_API_KEY` | （なし） | 設定時に Bearer 認証を要求（発見系は開放） |
| `ROKID_ALLOW_REAL_EXAM_SOLVE` | `0` | 本番試験モードの解答ロック解除（不正防止） |
| `ROKID_DATA_DIR` | `data` | ストレージ先（プライバシー/隔離） |
| `ROKID_ENABLE_EMBEDDING` | `0` | RAG の意味検索（embedding）を有効化（未接続時は lexical） |
| `ROKID_HUD_LANG` | `ja` | HUD 文言の言語（D4、**将来拡張・未実装**） |

```python
# 擬似: フラグの読み出しは一箇所に集約（app/config.py を拡張）
ENABLE_EMBEDDING = os.environ.get("ROKID_ENABLE_EMBEDDING", "0") == "1"
HUD_LANG = os.environ.get("ROKID_HUD_LANG", "ja")
```

フラグはデフォルト OFF・後方互換を壊さない範囲でのみ追加します。

---

## 6. 移行戦略（将来の変化シナリオ別）

### (a) ローカル → クラウド 要約/解答/解説/抽出（実装済み: `openai`/`gemini`/`claude`）
1. **実アダプタ `openai`/`gemini`/`claude` は同梱済み**（`app/{analyzers,solvers,explainers,extractors}/llm_adapter.py` の `LLM*` がプロバイダ非依存で担う、
   共通クライアント `app/llm.py`）。追加ベンダは同ポートにアダプタを1つ実装するだけ。
2. `ROKID_ANALYZER/SOLVER/EXPLAINER/EXTRACTOR=openai|gemini|claude` で切替。
3. creds は `ANTHROPIC_API_KEY`（環境変数）から注入（リポジトリには入れない）。
   任意依存は `pip install anthropic`（遅延 import）。
4. 圏外/未設定/失敗時は registry が `local` に自動フォールバック（§2、solver は二段）。
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

### (e) 解答モードの高度化（Solver / メディア抽出 / RAG）
解答モード（Phase 1〜4）も Analyzer と同じポート方式なので、**実アダプタ登録だけ**で高度化できる：
1. **Solver**: 実アダプタ `app/solvers/llm_adapter.py`（`LLMSolver`・プロバイダ非依存）を同梱（`ROKID_SOLVER=openai|gemini|claude`）。
   追加ベンダは `app/solvers/<vendor>.py` に実装し `register_solver(...)`。`ROKID_SOLVER_TIERS` で
   tier 指定。`solve_with_fallback` がクラウド→ローカルの**二段フォールバック**を担保（圏外/失敗でも HUD は返る）。
2. **メディア抽出**: 実アダプタ `app/extractors/llm_adapter.py`（`LLMExtractor`）を同梱（`ROKID_EXTRACTOR=openai|gemini|claude`、数式→LaTeX 等）。
   追加モデルは `app/extractors/<vendor>.py` に実装し `register_extractor(...)`。`add_question` の `media` がそのまま高精度化。
3. **RAG（案10）**: `app/retrieval.py` は今は依存なしの lexical scorer。`ROKID_ENABLE_EMBEDDING=1` ＋
   embedding を返す analyzer を組み合わせれば**意味検索**へ差替（未接続時は lexical にフォールバック）。
   `context`/`evidence` は solver と HUD まで配線済みなので、検索器の差替だけで根拠提示が向上する。
4. **推論ログ（案9）**: `solutions.raw_reasoning` に保存し `GET …/reasoning` で参照。HUD は短縮版のまま。

### 境界（このリポジトリに入れないもの）
- **クラウド実接続・creds・実CV/実OCRモデル**: ポートの先（アダプタ）に隔離。リポジトリは offline・credential-free を維持。
- **6DoF 固定 AR**: 49g グラスはハード的に 6DoF/SLAM 非対応。`overlay` は `tracking:"2d_image_anchor"`・`fixed_ar:false`
  を公示し、真の紙面固定は将来のハード/トラッキングが整ってからの拡張とする（契約は前方互換で追加）。

---

## 7. 「壊さない」ための不変条件（チェックリスト）

- HUD は常に **ちょうど3行・短文**（描画層が前提にできる）。
- `/match` は HIT/LOW_CONF/NO_PAGE のいずれかを必ず返す（沈黙しない）。
- analyzer は空入力でも例外を出さず、ベストエフォートで返す。
- 新規プロバイダ/デバイスの追加は **registry への登録のみ**（コア無変更）。
- 同じ API メジャーでは既存フィールドを再解釈せず、新フィールドを加算する。
- 破壊的変更は新バージョンを並走させ、旧契約を即削除しない。
- アルゴリズム変更時は `MATCHER_VERSION` 更新＋`scripts/evaluate.py` 再評価。

---

## 参考（出典・ウェブ検証）

- [CXR SDK（CXR-M / CXR-S / CXR-L） — Rokid AR Platform](https://ar.rokid.com/sdk?lang=en)
- [buildwithfenna/rokid-docs（CXR SDK 詳解・Maven・AIDL）](https://github.com/buildwithfenna/rokid-docs)
- [awesome-rokid（コミュニティ SDK/ツール集）](https://github.com/Anezium/awesome-rokid)
- [Rokid、Gemini/ChatGPT をネイティブ統合（Rizon / Agent Store）](https://www.prnewswire.com/news-releases/rokid-integrates-googles-gemini-chatgpt-in-major-update-to-international-smart-glasses-in-open-ecosystem-push-302700875.html)
- CXR-L 単体アプリ ⇄ 本体 AI ⇄ 本サーバ の接続は [cxr-l-integration.md](cxr-l-integration.md)
