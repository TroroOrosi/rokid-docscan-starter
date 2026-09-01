# Spec: custom-app-session

Status: Draft for human review on 2026-09-02.
Module id: `custom-app-session` from
`CAPABILITY-MAP-glasses-app-operation.md`.

## Objective

Build the side-effect-free session foundation that lets the Android-phone
relay establish an official CXR-L `CUSTOMAPP` session for the already-installed
`dev.rokid.docscanglass` package, explicitly start
`dev.rokid.docscanglass.TapProbeActivity`, and expose trustworthy phone-side
link/scene state and glasses-side CXR-S connection state.

This module makes the glasses app the foreground operator surface but assigns
no capture, navigation, discard, registration, upload, OCR, or custom-command
meaning to input. The phone remains the camera orchestrator, OCR runtime, and
server client.

### State contract

The phone state is monotonic within one session generation:

```text
IDLE -> AUTHORIZING -> CONFIGURED -> CONNECTING
     -> LINK_READY -> STARTING_APP -> SCENE_READY
```

Any rejected call, negative callback, timeout, CXR disconnect, or Bluetooth
disconnect moves the current generation to a terminal/non-ready failure state.
Late callbacks from an older generation cannot make a newer generation ready.

- `LINK_READY` requires both `onCXRLConnected(true)` and
  `onGlassBtConnected(true)`.
- `SCENE_READY` requires `onOpenAppResult(true)` after `LINK_READY` for the
  exact configured entry Activity.
- `onGlassAppResume(boolean)` reports foreground/background lifecycle only. It
  never means capture, confirmation, or operator intent.
- Glasses-side CXR-S state is separately exposed as initializing, connecting,
  connected, or disconnected from `CXRServiceBridge.StatusListener`.
- Until `glasses-command-link` adds an acknowledged handshake, phone
  `SCENE_READY` and glasses CXR-S `CONNECTED` must not be collapsed into a
  claimed end-to-end ready state.

### Explicit operation contract

- One user action starts authorization/connection and one user action starts
  the configured glasses Activity after link-ready.
- The implementation does not automatically install, update, uninstall,
  restart, or stop a glasses package.
- Link loss clears readiness immediately and never replays app-start or a
  future destructive command.
- Session switching does not reuse a `CXRLink`; this module owns one
  `CUSTOMAPP` link per phone process and does not run the legacy `CUSTOMVIEW`
  session in parallel.

## Tech Stack

- Phone relay: Android Java 17, minSdk 31, compile/target SDK 36,
  `com.rokid.cxr:client-l:1.1.1`.
- Glasses app: Android Java 17, minSdk 28, compile/target SDK 36,
  `com.rokid.cxr:cxr-service-bridge:1.0`.
- Tests: JUnit 4.13.2 pure-Java state/adapter tests plus Android debug build and
  direct hardware acceptance.
- Supported measured target: Global Hi Rokid package
  `com.rokid.sprite.global.aiapp`, RG-glasses Android 12 build
  `1.25.012-20260901-150201`.

The stable CXR-S `1.0` coordinate is taken from Rokid Maven's current
`maven-metadata.xml`. An older official SDK-import page still shows a dated
snapshot. The stable artifact's public signatures and bundled ABIs must be
inspected after Gradle resolves it; the snapshot example is not silently used.

## Commands

Repository checks:

```powershell
py -3.12 -m pytest -q tests/test_documentation_contract.py -k "not classifies_every_markdown_file"
git diff --check
```

Android build and tests from the verified ASCII copy:

```powershell
.\gradlew.bat --no-daemon testDebugUnitTest assembleDebug :glassapp:lintDebug
```

Hardware verification always names the glasses serial explicitly; phone
wireless serials and authorization tokens are never written into repository
documents.

## Project Structure

```text
android-relay/app/src/main/java/dev/rokid/docscanrelay/
  CustomAppSession*       phone state machine and CXR-L adapter
  MainActivity.java       explicit operator controls and state display

android-relay/app/src/test/java/dev/rokid/docscanrelay/
  CustomAppSession*Test   pure-Java transition, timeout, and stale-callback tests

android-relay/glassapp/src/main/java/dev/rokid/docscanglass/
  GlassesCxrSession*      CXR-S lifecycle adapter with content-free status
  TapProbeActivity.java   existing HUD/input host and lifecycle owner

android-relay/glassapp/src/test/java/dev/rokid/docscanglass/
  GlassesCxrSession*Test  status mapping and lifecycle tests

docs/                    official-source and measured-hardware evidence
tasks/                   approved plan and dependency-ordered tasks
```

SDK calls stay behind small adapters. Pure state transitions do not depend on
Android, Binder, native libraries, Activities, or clocks.

## Code Style

Use explicit events and fail-closed transitions. An SDK boolean return means
only what the SDK documents; it is not promoted to a later readiness state.

```java
SessionState accept(SessionEvent event) {
    if (event.generation() != generation) {
        return state;
    }
    if (event == SessionEvent.CXR_DISCONNECTED
            || event == SessionEvent.BLUETOOTH_DISCONNECTED) {
        return SessionState.LINK_LOST;
    }
    return transitionTable.next(state, event);
}
```

- Classes and enums use domain names such as `CustomAppSessionState`, not SDK
  abbreviations without context.
- Logs contain state, generation, operation, and elapsed time only. They never
  contain authorization tokens, provider credentials, page data, image bytes,
  or command payloads.
- No callback directly performs a second state-changing SDK call. The
  controller first records the transition, then an explicit operation decides
  whether the next call is allowed.

## Testing Strategy

Use RED-GREEN-REFACTOR for every state or adapter behavior.

Pure-Java phone tests must cover:

- `LINK_READY` only after both link callbacks are true, in either order;
- start rejection before link-ready;
- `SCENE_READY` only after the matching generation receives
  `onOpenAppResult(true)`;
- negative, timed-out, duplicated, reordered, and stale callbacks;
- disconnect/background/resume behavior with no automatic restart or replay;
- exact-once controller close and callback cleanup.

Pure-Java glasses tests must cover:

- SDK initializing/connecting/connected/disconnected mapping;
- repeated callbacks without duplicate state emissions;
- lifecycle teardown without a camera, message subscription, or device-link
  disconnect side effect.

Integration verification must prove:

1. both APKs build and all existing tests remain green;
2. the phone requests only the session permission needed here
   (`DEVICE_MANAGE`) through `AuthorizationHelper`;
3. Global Hi Rokid is selected, both link-ready callbacks arrive, and the
   exact glasses Activity is started;
4. `onOpenAppResult(true)` produces phone `SCENE_READY`;
5. the glasses logs a CXR-S lifecycle state on the recorded hardware tuple;
6. background/foreground and one app-process restart never cause automatic
   capture, upload, registration, install, uninstall, or command replay.

An Android build proves compilation only. Hardware behavior remains unverified
until the physical checklist and content-free logs are recorded.

## Boundaries

### Always do

- Use the official CXR-L `CXRLink` API with `CUSTOMAPP` configured before
  `connect(token)`.
- Use exactly one shared `CXRLink` per phone process; future custom commands
  must reuse this same instance.
- Use `AuthorizationHelper` so its Hi Rokid/Global selection state and granted
  `GlassPermission` set match the connection.
- Treat `connect(token) == true` as “request initiated,” never as link-ready.
- Keep phone scene-ready and glasses bridge-connected as distinct states until
  an acknowledged command handshake exists.
- Preserve system-owned BACK behavior and all `glasses-input` fail-closed
  normalization guarantees.
- Update APP/version documentation and retain exact hardware/artifact evidence.

### Ask first

- Automatically installing, updating, uninstalling, stopping, or restarting
  the glasses app.
- Switching the session back to `CUSTOMVIEW` or running both session types in
  parallel.
- Requesting CAMERA or MICROPHONE through the new SDK flow before the owning
  capture/audio module is specified.
- Changing package name, Activity name, SDK version, or native ABI policy.

### Never do

- Call Android Camera APIs from the glasses app or invoke CXR-L `takePhoto` in
  this module.
- Send/parse `Caps`, subscribe to a command channel, or assign business meaning
  to normalized input in this module.
- Auto-capture, auto-register, upload, or infer intent from app resume, exit,
  close, AI, focus, or disconnect callbacks.
- Disable, obscure, spoof, or bypass the privacy LED or other firmware capture
  indicators.
- Log authorization tokens, credentials, page contents, image bytes, or command
  payloads.
- Commit or redistribute Rokid AAR files.

## Success Criteria

- A tested phone controller exposes generation-scoped `CUSTOMAPP` lifecycle
  state and rejects invalid, stale, duplicated, and out-of-order transitions.
- The phone uses `client-l:1.1.1` `CXRLink`, configures
  `CXRSessionType.CUSTOMAPP` with `dev.rokid.docscanglass`, and reaches
  `LINK_READY` only from the two documented callbacks.
- An explicit start operation launches
  `dev.rokid.docscanglass.TapProbeActivity`; only
  `onOpenAppResult(true)` reaches phone `SCENE_READY`.
- The glasses app uses the resolved stable CXR-S `1.0` artifact and exposes
  content-free bridge lifecycle without connecting separately or subscribing
  to commands.
- Link loss, focus changes, Activity/process restart, and background/resume
  clear or preserve state according to this contract without automatic SDK
  side effects.
- No camera, custom-command, upload, OCR, registration, install, uninstall, or
  privacy-indicator operation is introduced.
- Full Android unit/build/lint gates and direct phone/glasses hardware
  acceptance pass; exact versions, hashes, callbacks, and device-dependent
  behavior are recorded.

## Open Questions

Human review must confirm the deliberate first increment: use the app already
installed on the glasses and omit runtime APK install/update/uninstall. Remote
deployment can be specified later as a separate, explicit operator operation
if it is still needed after session start is proven.

## Official Sources and Version Evidence

- Rokid Android Authentication (Hi Rokid selection, permissions, token):
  <https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/us/663f26766e7348059905815bc022e1f7.html?documentId=0065a874c3444a6abb9b037cb3d8ac0c>
- Rokid Android Connection and Session (one `CXRLink`, link-ready conjunction,
  configure before connect):
  <https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/us/663f26766e7348059905815bc022e1f7.html?documentId=087ed65478614cc7bb56c6b8fc630d75>
- Rokid Glasses Custom App (Activity start and scene-ready callback):
  <https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/us/663f26766e7348059905815bc022e1f7.html?documentId=c4f8eb892e3944f381600ac71b2d3fd3>
- Rokid CXR-S Connection Manager (`CXRServiceBridge.StatusListener`):
  <https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/us/663f26766e7348059905815bc022e1f7.html?documentId=cdd74f29cab24dd59b9e23da50c93f40>
- Rokid Maven CXR-S metadata (stable `1.0`):
  <https://maven.rokid.com/repository/maven-public/com/rokid/cxr/cxr-service-bridge/maven-metadata.xml>

The linked `client-l:1.1.1` AAR was also inspected locally with `javap`. Its
actual bytecode selects `com.rokid.sprite.global.aiapp` when
`AuthorizationHelper.isConnectHiRokid()` is true, and its public API exposes
`CUSTOMAPP`, `configCXRSession`, link callbacks, app callbacks, and app control.
This supersedes the older repository note claiming the upper API targets only
the mainland-China package.
