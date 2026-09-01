# Capability Map: Glasses app operation

Status: Accepted by the user on 2026-09-01.

## Modules

| Module id | Responsibility | Depends on |
|---|---|---|
| `glasses-input` | Normalize glasses KeyEvents and official system broadcasts into one deduplicated, side-effect-free operator action stream. | — |
| `custom-app-session` | Configure the phone CXR-L link as `CUSTOMAPP`, start the matching glasses Activity, initialize CXR-S, and expose scene-ready/lifecycle state. | — |
| `glasses-command-link` | Exchange versioned `Caps` messages and acknowledgements between phone CXR-L and glasses CXR-S. | `glasses-input`, `custom-app-session` |
| `glasses-capture-control` | Let explicit glasses actions prepare, trigger, cancel, retake, discard, and register while the phone retains CXR-L photography, OCR, and server communication. | `glasses-command-link` |
| `glasses-preview-review` | Deliver and acknowledge a bounded capture preview on the glasses before registration can upload the page. | `glasses-capture-control` |
| `glasses-hud-recovery` | Render the black/green/three-line operational HUD and recover from process/link/session loss without automatic capture or registration. | `custom-app-session`, `glasses-preview-review` |

Build order:

`glasses-input` + `custom-app-session` → `glasses-command-link` →
`glasses-capture-control` → `glasses-preview-review` →
`glasses-hud-recovery`

## Architecture boundary

- The glasses app is the primary operator control surface and HUD.
- The phone remains the CXR-L camera orchestrator, Japanese OCR runtime, and
  authenticated server client until a separately specified replacement passes
  the same safety and data-handling gates.
- A `CUSTOMAPP` scene must be ready before photo or custom-command operations.
- The operator must see a capture preview on the glasses before registration is
  enabled. No unshown page may be uploaded.
- Commands and acknowledgements are versioned, deduplicated, and scoped to a
  link/session generation. Reconnect never replays a destructive command.

## Explicit non-goals

- Do not call Android Camera APIs directly from the glasses app in this change.
- Do not store server or provider credentials on the glasses.
- Do not disable, obscure, spoof, or bypass the physical camera/privacy
  indicator.
- Do not infer operator intent from CUSTOMVIEW close, AI-exit, or lifecycle
  callbacks.
- Do not auto-capture, auto-register, or upload a page that has not been shown
  to the operator.

## Source and hardware evidence

- Rokid's official Custom App contract pairs phone CXR-L with glasses CXR-S,
  requires `CUSTOMAPP`, and treats a successful app-start callback as scene
  building completion:
  <https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/us/663f26766e7348059905815bc022e1f7.html?documentId=c4f8eb892e3944f381600ac71b2d3fd3>
- Rokid's official Custom Commands contract pairs phone `sendCustomCmd` with
  glasses `CXRServiceBridge.subscribe`, and glasses `sendMessage` with the
  phone command callback:
  <https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/us/663f26766e7348059905815bc022e1f7.html?documentId=96e04858ad0f4dca9a54c37f343876d4>
- Rokid's official key contract documents dynamic system-broadcast registration
  alongside Activity KeyEvent handling:
  <https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/us/663f26766e7348059905815bc022e1f7.html?documentId=4da5cf130f1d477ea9be76da0b4e5d40>
- On the measured `RG-glasses` Android 12 build
  `1.25.012-20260901-150201`, the installed tap probe launched in the
  foreground and received 33 physical `onKeyDown` events. This proves input
  delivery, not the command transport or production mapping.
