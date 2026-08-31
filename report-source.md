# Documentation evidence audit — canonical research ledger

Status: Internal dated evidence ledger, not an operator contract.

Date: 2026-08-31 (JST)

Scope: repository Markdown/documentation, the contracts they assert, and the
implementation/configuration that should support those assertions. This is an
internal research ledger. The reader-facing report is
`docs/documentation-evidence-audit-2026-08-31.md`.

## Evidence classes

- **P**: current primary/public source (official vendor documentation, source,
  Maven metadata, or product page).
- **L**: local implementation, tests, AAR bytecode, Git history, or sanitized
  repository evidence.
- **M**: device measurement described in the repository but lacking an attached
  raw-log artifact that this audit could independently replay.
- **I**: inference. It must not be stated as a vendor guarantee or verified
  hardware fact.

## Claim ledger

| ID | Claim under review | Evidence | Result |
|---|---|---|---|
| R01 | Consumer Rokid Glasses camera/privacy LED should be disabled | P: Rokid Japan FAQ says it cannot be turned off and covering it prevents camera startup | Contradicted; safety-critical |
| R02 | CXR-L CUSTOMVIEW delivers a usable operator tap to the phone relay | L/M: later 17-minute session found no tap-aligned delivery; public callback exposes close, not trustworthy user provenance | Not established; current tap state machine is unsafe to document as verified |
| R03 | Rokid platform cannot run a glasses-side app | P/L: official CXR-L CUSTOMAPP operations, CXR-S app model, AAR methods, current local `glassapp` module | Contradicted; installation on the measured device is still unverified/failed |
| R04 | `client-l:1.1.1` is the latest release | P: Maven metadata reports release 1.1.2 on 2026-08-28 | Stale; keep pin only as an explicitly tested/policy version |
| R05 | CXR-L has “always” exposed glass-app operations | L: verified in 1.0.1 and 1.1.1 only | Overbroad; say “at least 1.0.1 and 1.1.1” |
| R06 | CXR-L phone photo API provides preview/focus/cancel controls | P/L: official photo API and AAR expose JPEG callback/takePhoto but not those controls | Unsupported in this CXR-L surface; do not generalize to the whole platform |
| R07 | JPEG callback loss above about 512 KiB is a fixed, silent CXR-L limit | P/L/M: Binder has a shared bounded transaction buffer; exact observed loss cause was not captured | Plausible inference, not proven root cause or universal threshold |
| R08 | Raw/original JPEG is the authoritative stored page | L: server decodes, rotates, RGB-converts, and saves PNG; raw upload bytes are discarded | Contradicted by implementation |
| R09 | `ROKID_REAL_MODE=1` rejects placeholder analyzer/solver combinations | L: no config, guard, or test exists | Unimplemented invariant |
| R10 | Text/onboard-AI upload is the real-device primary route | L/P: current code and public CXR-L surface use glasses photo → phone OCR → server | Historical/compatibility route, not current primary route |
| R11 | Current Android relay version is 0.3.5 or 0.3.9 | L: Gradle says 0.3.15/versionCode 20 | Stale |
| R12 | Current CXR-L dependency is 1.0.1 | L: Gradle pins 1.1.1 | Stale |
| R13 | Rokid display is 480×398/eye, about 23° FOV | P: current official product page says 480×400 and 30°; official FAQ itself has a 480×640 inconsistency | Stale/ambiguous; bind specs to exact SKU and source date |
| R14 | Fixed focus and 34 cm–infinity are verified for this exact device | P: localized official page supports it; global current page omits it | Reasonable but SKU/source qualification required |
| R15 | OpenAI accepts OGG/FLAC transcription uploads | P/L: current official file-transcription list omits OGG/FLAC; code marks them supported | Contradicted |
| R16 | Google SDK automatically honors `GOOGLE_GEMINI_BASE_URL` | P/L: official SDK requires explicit HttpOptions/base_url; local code does not pass it | Contradicted |
| R17 | `google-genai>=0.3` guarantees `GEMINI_API_KEY` behavior documented by the repo | P: official changelog adds that env-key support in 1.19.0 | Contradicted lower bound |
| R18 | Provider defaults are current and stable | P: OpenAI GPT-4o is valid but older; Gemini 2.5 Flash is valid but no longer newest; Claude Opus 4.8 is legacy relative to current Anthropic models | Time-sensitive; query capability and pin/test |
| R19 | Cloud page/audio handling has an adequate privacy/retention contract | P/L: provider retention/training terms differ; local media has no TTL/delete endpoint/encryption policy | Incomplete and high-risk |
| R20 | Authentication docs enumerate all unauthenticated paths | L: `/docs`, `/openapi.json`, and `/redoc` are also exempt | Incomplete |
| R21 | ML Kit’s 16×16 guidance is a hard minimum and confidence <0.50 is a vendor threshold | P: 16×16 is “ideally”; no vendor-calibrated 0.50 cutoff | Overstated |
| R22 | AGP 9.2.1 / Gradle 9.4.1 / JDK 17 / SDK 36 toolchain is coherent | P/L | Supported |
| R23 | `refactor-instructions.md` is a current defect list | L: several named debts are now resolved and lint/tests pass | Historical snapshot; label with base commit/status |
| R24 | Current docs have durable citations | L/web: one linked community page is 404; old Rokid SDK URLs redirect to a generic portal; many claims have only link dumps | Inadequate provenance |

## Primary sources used

- Rokid Japan FAQ: https://jp.rokid.com/blogs/faq-app/faq-057
- Rokid Glasses product page: https://global.rokid.com/products/rokid-glasses
- Rokid global FAQ: https://global.rokid.com/pages/faq
- Rokid CXR-L custom-app documentation:
  https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/us/663f26766e7348059905815bc022e1f7.html?documentId=c4f8eb892e3944f381600ac71b2d3fd3
- Rokid CXR-L photo-capture documentation:
  https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/us/663f26766e7348059905815bc022e1f7.html?documentId=0acb0e21b21447e1927a97b809b88654
- Rokid Maven metadata:
  https://maven.rokid.com/repository/maven-public/com/rokid/cxr/client-l/maven-metadata.xml
- Android Binder exception documentation:
  https://developer.android.com/reference/android/os/TransactionTooLargeException
- Android Gradle Plugin 9.2 release notes:
  https://developer.android.com/build/releases/agp-9-2-0-release-notes
- ML Kit Japanese text recognition:
  https://developers.google.com/ml-kit/vision/text-recognition/v2/android
- OpenAI speech-to-text:
  https://developers.openai.com/api/docs/guides/speech-to-text
- OpenAI API data controls:
  https://developers.openai.com/api/docs/guides/your-data
- Anthropic models:
  https://platform.claude.com/docs/en/models/overview
- Anthropic commercial data retention:
  https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data
- Gemini models and terms:
  https://ai.google.dev/gemini-api/docs/models
  https://ai.google.dev/gemini-api/terms
- FastAPI concurrency guidance: https://fastapi.tiangolo.com/async/
- FastAPI version pinning: https://fastapi.tiangolo.com/deployment/versions/

## Local verification record

- `py -3.12 -m pytest -q`: 447 passed, one Starlette/httpx deprecation warning.
- `ruff check .`: passed.
- Android build from the current checkout: not run because the repository path
  contains non-ASCII characters and the project bootstrap correctly refused it.
  The existing ASCII worktree was stale and was not used as evidence for HEAD.
- Relative Markdown links: no broken local targets found.
- External links checked: the community CXR-L article at
  `marcinmiazga.com/cxr-l-sdk/` returned 404. Older `ar.rokid.com` SDK links
  redirected to a generic portal and did not substantiate the linked claim.

## Open evidence gaps

- Attach sanitized raw logcat plus hashes for each claimed hardware behavior.
- Re-run the full physical checklist on one named APK/commit/firmware/service
  tuple. Compilation alone is not hardware verification.
- Verify the glasses-side app installation/signing/session route on hardware.
- Decide whether raw JPEG or normalized PNG is the authoritative evidence.
- Decide and implement the precise fail-closed semantics of real mode.
- Establish provider/tier-specific data classification, retention, deletion,
  and region requirements before sending real documents.
