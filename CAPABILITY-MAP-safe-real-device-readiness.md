# Capability Map: Safe real-device readiness

Status: Accepted by the user on 2026-09-01, with the safety boundary below.

| Module id | Responsibility | Depends on |
|---|---|---|
| `evidence-contract` | Separate current contracts, historical measurements, and unverified hypotheses; keep every repository Markdown file truthful and versioned. | — |
| `safe-capture` | Keep one photo request in flight, treat timeout/disconnect as unknown, record content-free capture evidence, and require physical LED observation without modifying the indicator. | `evidence-contract` |
| `server-contract` | Make normalized PNG the documented authoritative server image, implement real-mode fail-closed behavior, and align provider/audio contracts with tested behavior. | `evidence-contract` |
| `android-readiness` | Verify toolchain, AAR provenance, APK identity/signatures, package/activity/session configuration, and build artifacts before device access. | `safe-capture` |
| `device-validation` | Inventory the phone read-only first, then install only verified artifacts and record actual results without promoting unobserved behavior. | all prior modules |

Build order:

`evidence-contract` → (`safe-capture`, `server-contract`) → `android-readiness` → `device-validation`

## Safety boundary

The supported application, diagnostic workflow, documentation, and real-device
test do not disable, obscure, spoof, or bypass a camera/privacy indicator. The
indicator is observed externally. This boundary applies regardless of whether a
vendor, community post, local script, privileged shell, or private API claims a
way to change it.
