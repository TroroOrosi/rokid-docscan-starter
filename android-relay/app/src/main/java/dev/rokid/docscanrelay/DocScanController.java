package dev.rokid.docscanrelay;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.IOException;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.function.BooleanSupplier;

/** Serial state machine for capture -> OCR -> upload -> solve -> HUD review. */
public final class DocScanController implements AutoCloseable {
    public interface Listener {
        void onUpdate(RelayState state, List<String> hudLines, String diagnostic);

        default void onCaptureReview(CaptureReviewStore.Pending pending) {
        }

        default void onCaptureReviewCleared() {
        }
    }

    private static final String PREFS = "docscan_relay";
    private static final String KEY_SERVER = "server";
    private static final String KEY_DOCUMENT = "document_id";
    private static final String KEY_NEXT_PAGE = "next_page";
    private static final String KEY_SESSION = "session_id";
    private static final String KEY_COMMITTED_PAGE = "committed_page_index";
    private static final String KEY_COMMITTED_JPEG_SHA256 = "committed_jpeg_sha256";
    private static final int NO_COMMITTED_PAGE = -1;
    private static final long CAPTURE_TIMEOUT_SECONDS = 30;
    private static final long SHUTTER_STABILIZATION_MILLIS = 1500;
    private static final long CUSTOM_VIEW_ACK_TIMEOUT_MILLIS = 3000;
    static final int PHOTO_WIDTH = 1920;
    static final int PHOTO_HEIGHT = 1080;
    static final int PHOTO_QUALITY = 80;

    private final RokidGlobalLink link;
    private final JapaneseOcr ocr;
    private final Listener listener;
    private final SharedPreferences preferences;
    private final ExecutorService serial = Executors.newSingleThreadExecutor();
    private final ScheduledExecutorService watchdog =
            Executors.newSingleThreadScheduledExecutor();
    private final CaptureLease captureLease = new CaptureLease();
    private final CaptureReviewStore captureReview = new CaptureReviewStore();
    private final CaptureReviewPersistence captureReviewPersistence;
    private final RetryCursor retryCursor = new RetryCursor();

    private volatile RelayState state = RelayState.DISCONNECTED;
    private DocScanApi api;
    private String configuredServer = "";
    private int imageRotation;
    private boolean linkReady;
    private long documentId;
    private int nextPageIndex;
    private int captureTargetPageIndex = -1;
    private CaptureReviewStore.Pending committedPendingLocked;
    private boolean committedRecoveryBlocked;
    private int armedPageIndex = -1;
    private boolean armedReplacingPending;
    private long aimingGeneration;
    private long captureGuideViewGeneration =
            RokidGlobalLink.NO_VIEW_GENERATION;
    private boolean captureGuideAcknowledged;
    private boolean stabilizationTimerScheduled;
    private long sessionId;
    private int reviewIndex;
    private int reviewViewPage;
    private int reviewProblemCount;
    private int reviewViewPageCount;
    private List<String> currentHudLines =
            List.of("DocScan", "接続を待っています", "");

    public DocScanController(
            Context context,
            RokidGlobalLink link,
            JapaneseOcr ocr,
            Listener listener
    ) {
        this.link = link;
        this.ocr = ocr;
        this.listener = listener;
        preferences = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        captureReviewPersistence = new CaptureReviewPersistence(
                new File(context.getFilesDir(), "pending-capture-v1.bin"));
        configuredServer = preferences.getString(KEY_SERVER, "");
        documentId = preferences.getLong(KEY_DOCUMENT, 0);
        nextPageIndex = preferences.getInt(KEY_NEXT_PAGE, 0);
        sessionId = preferences.getLong(KEY_SESSION, 0);
        FallbackCommitMarker fallbackCommitMarker = loadFallbackCommitMarker();
        CaptureReviewStore.Pending restored = captureReviewPersistence.loadOrNull();
        int recoveredCommittedPageIndex =
                captureReviewPersistence.consumeRecoveredCommittedPageIndex();
        boolean fallbackMatchesPending = false;
        if (fallbackCommitMarker != null) {
            committedRecoveryBlocked = true;
            recoveredCommittedPageIndex = Math.max(
                    recoveredCommittedPageIndex,
                    fallbackCommitMarker.pageIndex);
            if (restored == null || fallbackCommitMarker.matches(restored)) {
                fallbackMatchesPending = true;
                committedPendingLocked = restored;
            }
        }
        if (recoveredCommittedPageIndex >= 0) {
            committedRecoveryBlocked = true;
            nextPageIndex = Math.max(
                    nextPageIndex,
                    recoveredCommittedPageIndex + 1);
            boolean workflowPersisted = persistWorkflowSynchronously();
            if (workflowPersisted) {
                boolean recoveryCleaned =
                        fallbackCommitMarker != null && !fallbackMatchesPending;
                if (fallbackCommitMarker == null || fallbackMatchesPending) {
                    try {
                        captureReviewPersistence.clearAfterCommit();
                        recoveryCleaned = true;
                    } catch (IOException ignored) {
                        // Keep the fallback marker so another restart remains fail-closed.
                    }
                }
                boolean fallbackCleaned = clearFallbackOnlyAfterRecovery(
                        recoveryCleaned,
                        fallbackCommitMarker != null,
                        this::clearFallbackCommitMarkerSynchronously);
                if (recoveryCleaned && fallbackCleaned) {
                    if (fallbackMatchesPending) {
                        restored = null;
                    }
                    committedPendingLocked = null;
                    committedRecoveryBlocked = false;
                }
            }
        }
        if (restored != null) {
            captureReview.stage(
                    restored.pageIndex,
                    restored.jpeg,
                    restored.ocrText,
                    restored.rotationDegrees,
                    restored.ocrFailure);
            captureTargetPageIndex = restored.pageIndex;
            imageRotation = restored.rotationDegrees;
        }
    }

    public RelayState getState() {
        return state;
    }

    /**
     * Routes one deduplicated glasses gesture on the controller's serial
     * queue. Reading the state and applying the resulting command in the same
     * task prevents a queued action from being applied to a stale state.
     */
    public void onGlassesGesture(PressGestureInterpreter.Action gesture) {
        if (gesture == null) {
            return;
        }
        try {
            serial.execute(() -> handleGlassesGestureNow(gesture));
        } catch (RejectedExecutionException ignored) {
            // The activity is already closing.
        }
    }

    private void handleGlassesGestureNow(PressGestureInterpreter.Action gesture) {
        CaptureActionRouter.Command command = CaptureActionRouter.route(state, gesture);
        switch (command) {
            case ARM_NEXT:
                captureNextPageNow();
                break;
            case ARM_PREVIOUS:
                recapturePreviousPageNow();
                break;
            case ARM_RETAKE:
                retakePendingCaptureNow(null);
                break;
            case TAKE_PHOTO:
                triggerArmedCaptureNow();
                break;
            case CANCEL_AIMING:
                cancelAimingNow();
                break;
            case FINISH_READING:
                finishReadingNow();
                break;
            case CONFIRM_CAPTURE:
                confirmPendingCaptureNow();
                break;
            case NEXT_REVIEW:
                nextReviewItemNow();
                break;
            case PREVIOUS_REVIEW:
                previousReviewItemNow();
                break;
            case START_NEW_DOCUMENT:
                startNewDocumentNow();
                break;
            default:
                break;
        }
    }

    /**
     * Re-presents the current workflow view after the glasses' system
     * double-tap exits a CustomView to the default menu. This does not advance
     * state, register a photo, or request a photo.
     */
    public void restoreGlassesViewAfterMenuExit() {
        try {
            serial.execute(this::restoreGlassesViewAfterMenuExitNow);
        } catch (RejectedExecutionException ignored) {
            // The activity is already closing.
        }
    }

    private void restoreGlassesViewAfterMenuExitNow() {
        if (!linkReady || state == RelayState.DISCONNECTED) {
            return;
        }
        if (link.isCustomViewActuallyOpen()) {
            listener.onUpdate(
                    state,
                    currentHudLines,
                    "System-menu recovery skipped because the current "
                            + "DocScan CustomView is already open");
            return;
        }
        long restoredGeneration;
        CaptureReviewStore.Pending pending = captureReview.peek();
        if (state == RelayState.CAPTURE_REVIEW && pending != null) {
            restoredGeneration = link.showCaptureReview(
                    pending.jpeg,
                    pending.rotationDegrees,
                    currentHudLines);
        } else if ((state == RelayState.AIMING || state == RelayState.STABILIZING)
                && armedPageIndex >= 0) {
            if (state == RelayState.STABILIZING) {
                // A system-menu exit pauses the shutter countdown. Invalidate
                // any previously scheduled takePhoto and start a fresh delay
                // only after the restored guide is acknowledged by the glass.
                aimingGeneration++;
                stabilizationTimerScheduled = false;
            }
            restoredGeneration = link.showCaptureAiming(
                    armedPageIndex + 1,
                    armedReplacingPending,
                    state == RelayState.STABILIZING);
            if (restoredGeneration != RokidGlobalLink.NO_VIEW_GENERATION) {
                trackCaptureGuideOpen(restoredGeneration);
            }
        } else {
            restoredGeneration = link.showHud(currentHudLines);
        }
        boolean restored =
                restoredGeneration != RokidGlobalLink.NO_VIEW_GENERATION;
        if (!restored
                && (state == RelayState.AIMING || state == RelayState.STABILIZING)) {
            rollbackCaptureGuideFailure(
                    "System-menu recovery failed; armed capture cancelled safely");
            return;
        }
        listener.onUpdate(
                state,
                currentHudLines,
                restored
                        ? "Restored DocScan glasses view after system-menu exit"
                        : "System-menu recovery could not reopen the glasses view");
    }

    public boolean isCaptureReconnectRequired() {
        return captureLease.isTimedOut();
    }

    public boolean hasPendingCaptureReview() {
        return captureReview.hasPending();
    }

    public void onCustomViewAvailable(long generation, String purpose) {
        try {
            serial.execute(() -> onCustomViewAvailableNow(generation, purpose));
        } catch (RejectedExecutionException ignored) {
            // The activity is already closing.
        }
    }

    private void onCustomViewAvailableNow(long generation, String purpose) {
        if (generation != captureGuideViewGeneration
                || (state != RelayState.AIMING
                && state != RelayState.STABILIZING)) {
            return;
        }
        captureGuideAcknowledged = true;
        if (state != RelayState.STABILIZING
                || stabilizationTimerScheduled) {
            return;
        }
        stabilizationTimerScheduled = true;
        final long generationAtSchedule = aimingGeneration;
        watchdog.schedule(
                () -> enqueueStabilizedCapture(generationAtSchedule),
                SHUTTER_STABILIZATION_MILLIS,
                TimeUnit.MILLISECONDS);
        listener.onUpdate(
                state,
                currentHudLines,
                "Stabilization countdown started after glasses view acknowledgement"
                        + " generation=" + generation
                        + " purpose=" + purpose);
    }

    public void onCustomViewFailed(
            long generation,
            String purpose,
            String message,
            Throwable cause
    ) {
        try {
            serial.execute(() -> {
                if (generation != captureGuideViewGeneration
                        || (state != RelayState.AIMING
                        && state != RelayState.STABILIZING)) {
                    return;
                }
                String detail = message
                        + " generation=" + generation
                        + " purpose=" + purpose;
                if (cause != null && cause.getMessage() != null) {
                    detail += ": " + cause.getMessage();
                }
                rollbackCaptureGuideFailure(
                        detail + "; armed capture cancelled before takePhoto");
            });
        } catch (RejectedExecutionException ignored) {
            // The activity is already closing.
        }
    }

    public void showPendingCaptureReview() {
        serial.execute(() -> {
            CaptureReviewStore.Pending pending = captureReview.peek();
            if (pending == null) {
                return;
            }
            listener.onCaptureReview(pending);
            publishCaptureReview(pending, "Recovered unregistered photo after app restart");
        });
    }

    public void configure(String serverUrl, String apiKey, int rotationDegrees) {
        if (committedRecoveryBlocked && !retryCommittedRecoverySynchronously()) {
            throw new IllegalStateException(
                    "登録済み写真のローカル復旧が完了するまで設定を変更できません");
        }
        if (captureLease.isUnresolved()
                || state.isCaptureInProgress()
                || state == RelayState.AIMING
                || state == RelayState.FINALIZING) {
            throw new IllegalStateException(
                    "写真の確認または撮影処理中です。登録か撮り直しを選んでください");
        }
        DocScanApi candidate = new DocScanApi(serverUrl, apiKey);
        String previousServer = preferences.getString(KEY_SERVER, "");
        String normalizedServer = serverUrl.trim().replaceAll("/+$", "");
        if (captureReview.hasPending()
                && !normalizedServer.equals(previousServer)) {
            throw new IllegalStateException(
                    "未登録写真の送信先は変更できません。先に登録または破棄してください");
        }
        configuredServer = normalizedServer;
        imageRotation = JapaneseOcr.normalizeRotation(rotationDegrees);
        api = candidate;
        if (!captureReview.hasPending()
                && !previousServer.isEmpty()
                && !previousServer.equals(configuredServer)) {
            clearWorkflow();
        }
        preferences.edit().putString(KEY_SERVER, configuredServer).apply();
    }

    public void verifyServer() {
        serial.execute(() -> {
            if (!requireApi()) {
                return;
            }
            CaptureReviewStore.Pending pending = captureReview.peek();
            if (pending != null) {
                listener.onCaptureReview(pending);
                publishCaptureReview(pending, "Recovered unregistered photo review");
                return;
            }
            try {
                JSONObject health = api.health();
                JSONObject settings = api.settings();
                String status = health.optString("status", "");
                if (!"ok".equalsIgnoreCase(status)) {
                    throw new IllegalStateException("health.status=" + status);
                }
                int maxLines = settings.optJSONObject("hud") == null
                        ? -1
                        : settings.optJSONObject("hud").optInt("max_lines", -1);
                publish(
                        linkReady ? RelayState.READY : RelayState.DISCONNECTED,
                        List.of("サーバ接続 OK", "HUD " + maxLines + "行契約", "Hi Rokidを認可"),
                        "Server verified: " + configuredServer);
            } catch (Exception error) {
                fail("サーバへ接続できません", error);
            }
        });
    }

    void onCaptureLinkStateChanged(boolean ready, CaptureLinkEvent event) {
        try {
            serial.execute(() -> {
                linkReady = ready;
                if (!ready) {
                    clearArmedCapture();
                    event.resetCaptureIfSafe(captureLease::resetAfterBindingReset);
                    publish(
                            RelayState.DISCONNECTED,
                            List.of("Hi Rokid未接続", "ペアリングを確認", ""),
                            event.resetsCapture()
                                    ? "Rokid service binding reset; capture lease released"
                                    : "Rokid glasses unavailable; capture lease retained");
                    return;
                }
                if (captureLease.isUnresolved()) {
                    if (captureLease.isTimedOut()) {
                        publish(
                                RelayState.ERROR,
                                List.of(
                                        "撮影終了が未確認",
                                        "Hi Rokid認可・再接続",
                                        "追加処理を安全停止"),
                                "Duplicate connected callback ignored while "
                                        + "the capture lease is unresolved");
                    }
                    return;
                }
                CaptureReviewStore.Pending pending = captureReview.peek();
                if (pending != null) {
                    listener.onCaptureReview(pending);
                    publishCaptureReview(
                            pending,
                            "Rokid AIDL connected; restored pending photo review");
                    return;
                }
                // resume() publishes the one view that matches the durable
                // workflow. Avoid opening an intermediate READY HUD whose
                // delayed callbacks could race the real restored view.
                resume();
            });
        } catch (RejectedExecutionException ignored) {
            // The activity is already closing.
        }
    }

    public void resume() {
        serial.execute(() -> {
            if (!linkReady) {
                return;
            }
            if (committedRecoveryBlocked && !retryCommittedRecoverySynchronously()) {
                publishCommittedPendingLocked(
                        captureReview.peek(),
                        "Resume blocked until committed-photo recovery completes");
                return;
            }
            if (captureLease.isUnresolved()) {
                if (captureLease.isTimedOut()) {
                    publish(
                            RelayState.ERROR,
                            List.of(
                                    "復旧処理を保留",
                                    "撮影終了が未確認",
                                    "Hi Rokid認可・再接続"),
                            "Resume rejected while a CXR-L photo lease is unresolved");
                }
                return;
            }
            if (!requireApi()) {
                return;
            }
            CaptureReviewStore.Pending pending = captureReview.peek();
            if (pending != null) {
                listener.onCaptureReview(pending);
                publishCaptureReview(pending, "Recovered unregistered photo review");
                return;
            }
            try {
                if (sessionId > 0) {
                    handleFinalizedSession(
                            api.finalizeReading(sessionId),
                            "Recovered exam session " + sessionId);
                    return;
                }
                if (documentId > 0) {
                    JSONObject status = api.scanStatus(documentId);
                    JSONArray indexes = status.optJSONArray("page_indexes");
                    int max = -1;
                    if (indexes != null) {
                        for (int i = 0; i < indexes.length(); i++) {
                            max = Math.max(max, indexes.optInt(i, -1));
                        }
                    }
                    nextPageIndex = max + 1;
                    persistWorkflow();
                    if ("ready".equals(status.optString("status"))) {
                        sessionId = api.createExamSession(documentId)
                                .getLong("session_id");
                        persistWorkflow();
                        handleFinalizedSession(
                                api.finalizeReading(sessionId),
                                "Recovered finalized document " + documentId);
                        return;
                    }
                    publish(
                            RelayState.READING,
                            List.of(
                                    "読取を再開",
                                    nextPageIndex + "ページ登録済",
                                    "タップ: 次の撮影準備"),
                            "Recovered document " + documentId);
                    return;
                }
                publish(
                        RelayState.READY,
                        List.of("準備完了", "タップ: 1ページ目準備", "長押し: 読取完了"),
                        "Ready for a new document");
            } catch (Exception error) {
                fail("前回状態を復元できません", error);
            }
        });
    }

    public void captureNextPage() {
        serial.execute(this::captureNextPageNow);
    }

    private void captureNextPageNow() {
        armCaptureAt(
                captureTargetPageIndex >= 0
                        ? captureTargetPageIndex
                        : retryCursor.nextOr(nextPageIndex),
                false);
    }

    public void recapturePreviousPage() {
        serial.execute(this::recapturePreviousPageNow);
    }

    private void recapturePreviousPageNow() {
        int pageIndex = captureTargetPageIndex >= 0
                ? captureTargetPageIndex
                : retryCursor.previousOr(nextPageIndex);
        if (pageIndex < 0) {
            publish(
                    RelayState.READING,
                    List.of("再撮影対象なし", "タップ: 1ページ目準備", ""),
                    "No previous page");
            return;
        }
        armCaptureAt(pageIndex, false);
    }

    private void armCaptureAt(int pageIndex, boolean replacingPending) {
        if (committedRecoveryBlocked && !retryCommittedRecoverySynchronously()) {
            publishCommittedPendingLocked(
                    captureReview.peek(),
                    "Capture preparation blocked until committed-photo recovery completes");
            return;
        }
        if (!linkReady || !requireApi()) {
            return;
        }
        if (captureLease.isUnresolved()) {
            String reason = captureLease.isTimedOut()
                    ? "前回撮影の終了未確認。Hi Rokidを再接続"
                    : "前回撮影の結果を待っています";
            publish(
                    RelayState.ERROR,
                    List.of("撮影を安全停止", reason, "重複撮影は禁止"),
                    "Capture rejected while a CXR-L photo lease is unresolved");
            return;
        }
        if (state.isCaptureInProgress()
                || state == RelayState.FINALIZING) {
            publish(
                    state,
                    List.of("処理中", "完了まで待機", ""),
                    "Ignored capture preparation while processing");
            return;
        }
        CaptureReviewStore.Pending pending = captureReview.peek();
        if (pending != null
                && (!replacingPending || pending.pageIndex != pageIndex)) {
            publishCaptureReview(
                    pending,
                    "Capture rejected until the pending photo is registered or retaken");
            return;
        }
        captureTargetPageIndex = pageIndex;
        armedPageIndex = pageIndex;
        armedReplacingPending = replacingPending;
        aimingGeneration++;
        if (!publishCaptureAiming(
                RelayState.AIMING,
                pageIndex,
                replacingPending,
                false,
                "Manual shutter armed for page index " + pageIndex)) {
            rollbackCaptureGuideFailure(
                    "Capture preparation rolled back because its glasses guide did not open");
        }
    }

    public void triggerArmedCapture() {
        serial.execute(this::triggerArmedCaptureNow);
    }

    private void triggerArmedCaptureNow() {
        if (state != RelayState.AIMING || armedPageIndex < 0) {
            publish(
                    state,
                    List.of("撮影準備なし", "先に撮影準備を選択", ""),
                    "Manual shutter ignored without an armed page");
            return;
        }
        if (!publishCaptureAiming(
                RelayState.STABILIZING,
                armedPageIndex,
                armedReplacingPending,
                true,
                "Manual shutter accepted; waiting "
                        + SHUTTER_STABILIZATION_MILLIS
                        + "ms before takePhoto")) {
            rollbackCaptureGuideFailure(
                    "Manual shutter cancelled because the stabilization guide did not open");
        }
    }

    public void cancelAiming() {
        serial.execute(this::cancelAimingNow);
    }

    private void cancelAimingNow() {
        if (state != RelayState.AIMING && state != RelayState.STABILIZING) {
            return;
        }
        clearArmedCapture();
        CaptureReviewStore.Pending pending = captureReview.peek();
        if (pending != null) {
            listener.onCaptureReview(pending);
            publishCaptureReview(pending, "Manual retake preparation cancelled");
            return;
        }
        publish(
                documentId > 0 ? RelayState.READING : RelayState.READY,
                List.of("撮影を取消", "タップ: 撮影準備", "長押し: 読取完了"),
                "Manual capture preparation/stabilization cancelled");
    }

    private void enqueueStabilizedCapture(long generation) {
        try {
            serial.execute(() -> {
                if (state != RelayState.STABILIZING
                        || generation != aimingGeneration
                        || !captureGuideAcknowledged
                        || !stabilizationTimerScheduled
                        || armedPageIndex < 0) {
                    return;
                }
                stabilizationTimerScheduled = false;
                captureGuideViewGeneration =
                        RokidGlobalLink.NO_VIEW_GENERATION;
                captureGuideAcknowledged = false;
                int pageIndex = armedPageIndex;
                boolean replacingPending = armedReplacingPending;
                armedPageIndex = -1;
                armedReplacingPending = false;
                requestPhotoAt(pageIndex, replacingPending);
            });
        } catch (RejectedExecutionException ignored) {
            // The activity closed during the stabilization delay.
        }
    }

    private boolean publishCaptureAiming(
            RelayState next,
            int pageIndex,
            boolean replacingPending,
            boolean stabilizing,
            String diagnostic
    ) {
        List<String> lines = stabilizing
                ? List.of(
                        "P" + (pageIndex + 1) + " シャッター受付",
                        "1.5秒そのまま静止",
                        "撮影まで動かない")
                : List.of(
                        "P" + (pageIndex + 1)
                                + (replacingPending ? " 撮り直し準備" : " 撮影準備"),
                        "40〜60cm・中心を＋へ",
                        "静止して長押し");
        long viewGeneration =
                link.showCaptureAiming(pageIndex + 1, replacingPending, stabilizing);
        if (viewGeneration == RokidGlobalLink.NO_VIEW_GENERATION) {
            listener.onUpdate(
                    state,
                    List.of("グラス表示を復元できません", "撮影は開始していません", ""),
                    diagnostic + "; openCustomView was not accepted");
            return false;
        }
        state = next;
        currentHudLines = lines;
        trackCaptureGuideOpen(viewGeneration);
        listener.onUpdate(next, lines, diagnostic);
        return true;
    }

    private void trackCaptureGuideOpen(long viewGeneration) {
        captureGuideViewGeneration = viewGeneration;
        captureGuideAcknowledged = false;
        stabilizationTimerScheduled = false;
        final long aimingGenerationAtRequest = aimingGeneration;
        watchdog.schedule(
                () -> enqueueCaptureGuideAckTimeout(
                        viewGeneration,
                        aimingGenerationAtRequest),
                CUSTOM_VIEW_ACK_TIMEOUT_MILLIS,
                TimeUnit.MILLISECONDS);
    }

    private void enqueueCaptureGuideAckTimeout(
            long viewGeneration,
            long aimingGenerationAtRequest
    ) {
        try {
            serial.execute(() -> {
                if (viewGeneration != captureGuideViewGeneration
                        || aimingGenerationAtRequest != aimingGeneration
                        || captureGuideAcknowledged
                        || (state != RelayState.AIMING
                        && state != RelayState.STABILIZING)) {
                    return;
                }
                link.fenceCustomViewEpoch(
                        viewGeneration,
                        "撮影ガイドの表示確認がタイムアウトしたため操作を安全停止しました");
                rollbackCaptureGuideFailure(
                        "Glasses capture guide acknowledgement timed out; "
                                + "takePhoto was not requested");
            });
        } catch (RejectedExecutionException ignored) {
            // The activity closed while the acknowledgement watchdog waited.
        }
    }

    private void rollbackCaptureGuideFailure(String diagnostic) {
        clearArmedCapture();
        CaptureReviewStore.Pending pending = captureReview.peek();
        if (pending != null) {
            listener.onCaptureReview(pending);
            publishCaptureReview(pending, diagnostic + "; previous photo retained");
            return;
        }
        publish(
                documentId > 0 ? RelayState.READING : RelayState.READY,
                List.of(
                        "撮影準備を取消",
                        "グラス表示を再度開いてください",
                        "写真は未登録"),
                diagnostic);
    }

    private void clearArmedCapture() {
        aimingGeneration++;
        armedPageIndex = -1;
        armedReplacingPending = false;
        captureGuideViewGeneration = RokidGlobalLink.NO_VIEW_GENERATION;
        captureGuideAcknowledged = false;
        stabilizationTimerScheduled = false;
    }

    private void requestPhotoAt(int pageIndex, boolean replacingPending) {
        if (state != RelayState.STABILIZING) {
            return;
        }
        if (!linkReady || !requireApi()) {
            return;
        }
        CaptureReviewStore.Pending pending = captureReview.peek();
        long attempt = CaptureLease.NO_TOKEN;
        boolean photoRequestMayBeActive = false;
        try {
            if (documentId == 0) {
                String stamp = new SimpleDateFormat(
                        "yyyy-MM-dd HH:mm:ss", Locale.JAPAN).format(new Date());
                documentId = api.createDocument("Rokid scan " + stamp)
                        .getLong("document_id");
                nextPageIndex = 0;
                persistWorkflow();
            }
            attempt = captureLease.begin(pageIndex);
            if (attempt == CaptureLease.NO_TOKEN) {
                throw new IllegalStateException("another photo request is still unresolved");
            }
            publish(
                    RelayState.CAPTURING,
                    List.of("撮影中", "40〜60cm離す", "用紙全体を入れて静止"),
                    "Requesting glasses photo for page index " + pageIndex);
            RokidGlobalLink.PhotoStartResult startResult =
                    link.takePhoto(PHOTO_WIDTH, PHOTO_HEIGHT, PHOTO_QUALITY);
            if (startResult == RokidGlobalLink.PhotoStartResult.REJECTED) {
                throw new IllegalStateException("takePhoto returned false");
            }
            photoRequestMayBeActive = true;
            if (startResult == RokidGlobalLink.PhotoStartResult.UNKNOWN) {
                throw new IllegalStateException(
                        "takePhoto acceptance is unknown after an IPC failure");
            }
            final long scheduledAttempt = attempt;
            watchdog.schedule(
                    () -> enqueueCaptureTimeout(scheduledAttempt),
                    CAPTURE_TIMEOUT_SECONDS,
                    TimeUnit.SECONDS);
        } catch (Exception error) {
            if (attempt != CaptureLease.NO_TOKEN) {
                if (photoRequestMayBeActive) {
                    captureLease.markStartUnknown(attempt);
                } else {
                    captureLease.abortBeforeStart(attempt);
                }
            }
            if (pending != null && !photoRequestMayBeActive) {
                publishCaptureReview(
                        pending,
                        "Retake did not start; previous review photo retained: "
                                + error.getMessage());
            } else {
                fail(
                        photoRequestMayBeActive
                                ? "撮影開始結果を確認できません。Hi Rokidを再接続してください"
                                : "撮影開始に失敗しました",
                        error);
            }
        }
    }

    public void onPhoto(byte[] jpeg) {
        try {
            serial.execute(() -> handlePhoto(jpeg));
        } catch (RejectedExecutionException ignored) {
            // The activity closed while the Binder callback was arriving.
        }
    }

    private void handlePhoto(byte[] jpeg) {
        CaptureLease.Completion completion = captureLease.complete();
        if (completion == null) {
            return;
        }
        if (completion.lateAfterTimeout) {
            CaptureReviewStore.Pending pending = captureReview.peek();
            if (pending != null) {
                publishCaptureReview(
                        pending,
                        "Late photo callback discarded; previous review photo retained");
            } else {
                publish(
                        RelayState.READING,
                        List.of("遅延写真を破棄", "撮影終了を確認", "再撮影できます"),
                        "Late photo callback discarded after timeout; capture lease released");
            }
            return;
        }
        if (jpeg == null || jpeg.length == 0) {
            CaptureReviewStore.Pending pending = captureReview.peek();
            if (pending != null) {
                publishCaptureReview(
                        pending,
                        "Retake returned an empty photo; previous review photo retained");
            } else {
                fail("グラスから空の写真が返されました", null);
            }
            return;
        }
        final int uploadIndex = completion.pageIndex;
        final int uploadRotation = imageRotation;
        publish(
                RelayState.OCR,
                List.of("文字認識中", "P" + (uploadIndex + 1), ""),
                "Photo received: " + jpeg.length + " bytes");
        ocr.recognize(jpeg, uploadRotation, new JapaneseOcr.Callback() {
            @Override
            public void onResult(String text) {
                serial.execute(
                        () -> stageCaptureReview(
                                uploadIndex, jpeg, text, uploadRotation, ""));
            }

            @Override
            public void onError(Throwable error) {
                String detail = error == null || error.getMessage() == null
                        ? "unknown OCR error"
                        : error.getMessage();
                serial.execute(
                        () -> stageCaptureReview(
                                uploadIndex, jpeg, "", uploadRotation, detail));
            }
        });
    }

    public void onPhotoError(String message, Throwable cause) {
        try {
            serial.execute(() -> {
                CaptureLease.Completion completion = captureLease.complete();
                if (completion == null) {
                    return;
                }
                Throwable detail = cause;
                if (detail == null && message != null && !message.trim().isEmpty()) {
                    detail = new IllegalStateException(message);
                }
                String userMessage = completion.lateAfterTimeout
                        ? "撮影終了を確認しました。短押しで再撮影できます"
                        : "撮影に失敗しました。短押しで再撮影できます";
                CaptureReviewStore.Pending pending = captureReview.peek();
                if (pending != null) {
                    publishCaptureReview(
                            pending,
                            userMessage + (detail == null ? "" : ": " + detail.getMessage()));
                } else {
                    fail(userMessage, detail);
                }
            });
        } catch (RejectedExecutionException ignored) {
            // The activity closed while the Binder callback was arriving.
        }
    }

    private void enqueueCaptureTimeout(long attempt) {
        try {
            serial.execute(() -> {
                if (!captureLease.markTimedOut(attempt)) {
                    return;
                }
                fail(
                        "写真が返りませんでした。安全のためHi Rokidを再接続してください",
                        null);
            });
        } catch (RejectedExecutionException ignored) {
            // The activity closed while the watchdog was expiring.
        }
    }

    private void stageCaptureReview(
            int pageIndex,
            byte[] jpeg,
            String ocrText,
            int rotationDegrees,
            String ocrFailure
    ) {
        CaptureReviewStore.Pending previous = captureReview.peek();
        CaptureReviewStore.Pending candidate = new CaptureReviewStore.Pending(
                pageIndex,
                jpeg,
                ocrText,
                rotationDegrees,
                ocrFailure);
        CaptureReviewStore.Pending pending;
        try {
            pending = CaptureReviewTransaction.replace(
                    captureReview,
                    candidate,
                    captureReviewPersistence::save);
        } catch (IOException error) {
            if (previous != null) {
                listener.onCaptureReview(previous);
                publishCaptureReview(
                        previous,
                        "Replacement photo could not be saved; previous review retained: "
                                + error.getMessage());
            } else {
                captureTargetPageIndex = pageIndex;
                publish(
                        RelayState.ERROR,
                        List.of(
                                "写真を安全保存できません",
                                "タップ: 同じページを再準備",
                                "登録はしていません"),
                        "Initial review photo rejected because durable save failed: "
                                + error.getMessage());
            }
            return;
        }
        listener.onCaptureReview(pending);
        String diagnostic = "Photo awaiting confirmation: page " + pageIndex
                + ", OCR characters: " + pending.ocrCharacters();
        if (pending.hasOcrFailure()) {
            diagnostic += ", OCR error: " + pending.ocrFailure;
        }
        publishCaptureReview(pending, diagnostic);
    }

    public void confirmPendingCapture() {
        serial.execute(this::confirmPendingCaptureNow);
    }

    private void confirmPendingCaptureNow() {
        CaptureReviewStore.Pending pending = captureReview.peek();
        if (committedRecoveryBlocked) {
            publishCommittedPendingLocked(
                    pending,
                    "Duplicate upload blocked while committed-photo recovery is incomplete");
            return;
        }
        if (pending == null) {
            publish(
                    RelayState.READING,
                    List.of("確認写真なし", "タップ: 撮影準備", ""),
                    "No pending photo to register");
            return;
        }
        if (pending == committedPendingLocked) {
            publishCommittedPendingLocked(
                    pending,
                    "Duplicate upload blocked after the server accepted this photo");
            return;
        }
        // Registration is destructive from the user's perspective. A command
        // routed before a nearby retake/cancel transition must never register
        // the photo after the controller has left the review state.
        if (state != RelayState.CAPTURE_REVIEW
                || captureLease.isUnresolved()
                || state.isCaptureInProgress()) {
            listener.onUpdate(
                    state,
                    List.of("登録を保留", "現在のグラス画面を優先", ""),
                    "Stale pending-photo confirmation ignored in state " + state);
            return;
        }
        if (api == null) {
            publishCaptureReview(
                    pending,
                    "Server configuration is required before this photo can be registered");
            return;
        }
        CaptureReviewStore.Confirmation confirmation = captureReview.confirm();
        if (confirmation == null) {
            return;
        }
        uploadCapturedPage(confirmation);
    }

    public void retakePendingCapture() {
        enqueuePendingRetake(null);
    }

    public void retakePendingCapture(int rotationDegrees) {
        enqueuePendingRetake(JapaneseOcr.normalizeRotation(rotationDegrees));
    }

    private void enqueuePendingRetake(Integer replacementRotation) {
        serial.execute(() -> retakePendingCaptureNow(replacementRotation));
    }

    private void retakePendingCaptureNow(Integer replacementRotation) {
        CaptureReviewStore.Pending pending = captureReview.peek();
        if (committedRecoveryBlocked) {
            publishCommittedPendingLocked(
                    pending,
                    "Retake blocked while committed-photo recovery is incomplete");
            return;
        }
        if (pending == null) {
            publish(
                    RelayState.READING,
                    List.of("確認写真なし", "タップ: 撮影準備", ""),
                    "No pending photo to retake");
            return;
        }
        if (pending == committedPendingLocked) {
            publishCommittedPendingLocked(
                    pending,
                    "Retake blocked because this photo was already accepted by the server");
            return;
        }
        if (state != RelayState.CAPTURE_REVIEW
                || captureLease.isUnresolved()
                || state.isCaptureInProgress()) {
            listener.onUpdate(
                    state,
                    List.of("再撮影準備を保留", "現在のグラス画面を優先", ""),
                    "Stale pending-photo retake ignored in state " + state);
            return;
        }
        if (replacementRotation != null) {
            imageRotation = replacementRotation;
        }
        armCaptureAt(pending.pageIndex, true);
    }

    private void uploadCapturedPage(CaptureReviewStore.Confirmation confirmation) {
        CaptureReviewStore.Pending pending = confirmation.pending();
        JSONObject response;
        try {
            publish(
                    RelayState.UPLOADING,
                    List.of("登録中", "P" + (pending.pageIndex + 1), ""),
                    "Confirmed photo upload; OCR characters: " + pending.ocrCharacters());
            response = api.uploadPage(
                    documentId,
                    pending.pageIndex,
                    pending.jpeg,
                    pending.ocrText,
                    pending.rotationDegrees);
        } catch (Exception error) {
            publishCaptureReview(
                    pending,
                    "Confirmed photo upload failed; retained for retry: " + error.getMessage());
            return;
        }

        // The server has committed this page. Persist that fact before
        // clearing the in-memory review so a failed delete or process death
        // can never resurrect it as an unregistered photo. SharedPreferences
        // is a separate synchronous fallback for storage-specific file errors.
        committedPendingLocked = pending;
        committedRecoveryBlocked = true;
        boolean fileCommitMarkerPersisted = false;
        String fileCommitMarkerError = "";
        try {
            captureReviewPersistence.markCommitted(pending);
            fileCommitMarkerPersisted = true;
        } catch (IOException markerError) {
            fileCommitMarkerError = markerError.getMessage();
        }
        boolean replaced = response.optBoolean("replaced", false);
        if (!replaced) {
            nextPageIndex = Math.max(nextPageIndex, pending.pageIndex + 1);
        } else if (pending.pageIndex >= nextPageIndex) {
            nextPageIndex = pending.pageIndex + 1;
        }
        retryCursor.onUploaded(pending.pageIndex);
        boolean fallbackPreferenceMarkerPersisted = false;
        boolean workflowPersisted;
        if (fileCommitMarkerPersisted) {
            workflowPersisted = persistWorkflowSynchronously();
        } else {
            workflowPersisted =
                    persistWorkflowAndFallbackMarkerSynchronously(pending);
            fallbackPreferenceMarkerPersisted = workflowPersisted;
            if (!fallbackPreferenceMarkerPersisted) {
                // If the combined write failed before reaching disk, a marker-
                // only retry still makes the pending photo restart-safe.
                fallbackPreferenceMarkerPersisted =
                        persistFallbackCommitMarkerSynchronously(pending);
            }
        }
        boolean durableCommitMarkerPersisted =
                fileCommitMarkerPersisted || fallbackPreferenceMarkerPersisted;
        List<String> lines = RelayMessages.forAiKeyScanAck(
                extractLines(response.optJSONObject("scan_ack")));
        if (pending.ocrText.trim().isEmpty()) {
            lines = List.of(
                    "写真を登録しました",
                    "端末OCRは空",
                    "タップ: 次の撮影準備");
        }
        String persistenceWarning = workflowPersisted
                ? ""
                : "; workflow cursor write failed; commit marker retained for restart recovery";
        boolean pendingCleared = false;
        if (workflowPersisted) {
            try {
                captureReviewPersistence.clearAfterCommit();
                pendingCleared = true;
            } catch (IOException error) {
                persistenceWarning =
                        "; committed restart-recovery marker retained after cleanup failure: "
                                + error.getMessage();
            }
        }
        if (workflowPersisted && pendingCleared) {
            boolean fallbackCleaned = !fallbackPreferenceMarkerPersisted
                    || clearFallbackCommitMarkerSynchronously();
            if (!fallbackCleaned) {
                persistenceWarning =
                        "; stale fallback commit marker could not be cleared after cleanup";
            } else {
                captureReview.clear(confirmation);
                captureTargetPageIndex = -1;
                committedPendingLocked = null;
                committedRecoveryBlocked = false;
                listener.onCaptureReviewCleared();
                publish(
                        RelayState.READING,
                        lines,
                        "Uploaded confirmed page " + pending.pageIndex
                                + (replaced ? " (replaced)" : "")
                                + persistenceWarning);
                return;
            }
        }
        String markerWarning = durableCommitMarkerPersisted
                ? "durable commit marker retained"
                : "neither commit marker could be saved"
                        + (fileCommitMarkerError.isEmpty()
                        ? ""
                        : ": " + fileCommitMarkerError);
        publishCommittedPendingLocked(
                pending,
                "Server accepted page " + pending.pageIndex
                        + " but local recovery is incomplete; "
                        + markerWarning
                        + persistenceWarning);
    }

    public void discardPendingCapture() {
        serial.execute(() -> {
            CaptureReviewStore.Pending pending = captureReview.peek();
            if (committedRecoveryBlocked) {
                publishCommittedPendingLocked(
                        pending,
                        "Discard blocked while committed-photo recovery is incomplete");
                return;
            }
            if (pending == null) {
                publish(
                        RelayState.READING,
                        List.of("確認写真なし", "タップ: 撮影準備", ""),
                        "No pending photo to discard");
                return;
            }
            if (pending == committedPendingLocked) {
                publishCommittedPendingLocked(
                        pending,
                        "Discard blocked because this photo was already accepted by the server");
                return;
            }
            if (captureLease.isUnresolved()
                    || state.isCaptureInProgress()
                    || state == RelayState.AIMING) {
                publish(
                        state,
                        List.of("処理中", "写真到着まで待機", "まだ破棄しません"),
                        "Pending photo discard ignored while capture is active");
                return;
            }
            try {
                captureReviewPersistence.clear();
            } catch (IOException error) {
                publishCaptureReview(
                        pending,
                        "Discard failed because restart recovery could not be cleared: "
                                + error.getMessage());
                return;
            }
            if (!captureReview.clear(pending)) {
                return;
            }
            captureTargetPageIndex = -1;
            listener.onCaptureReviewCleared();
            publish(
                    RelayState.READING,
                    List.of("写真を破棄しました", "タップ: 撮影準備", "長押し: 読取完了"),
                    "Discarded unregistered photo for page " + pending.pageIndex);
        });
    }

    private void publishCaptureReview(
            CaptureReviewStore.Pending pending,
            String diagnostic
    ) {
        if (committedRecoveryBlocked || pending == committedPendingLocked) {
            publishCommittedPendingLocked(pending, diagnostic);
            return;
        }
        clearArmedCapture();
        String secondLine = pending.ocrCharacters() == 0
                ? "OCR 0文字・写真を確認"
                : "OCR " + pending.ocrCharacters() + "文字・全体を確認";
        List<String> lines = List.of(
                "P" + (pending.pageIndex + 1) + " 未登録 / " + secondLine,
                "タップ: 同じページを撮り直す",
                "長押し: この写真を登録");
        state = RelayState.CAPTURE_REVIEW;
        currentHudLines = lines;
        link.showCaptureReview(
                pending.jpeg,
                pending.rotationDegrees,
                lines);
        listener.onUpdate(RelayState.CAPTURE_REVIEW, lines, diagnostic);
    }

    private void publishCommittedPendingLocked(
            CaptureReviewStore.Pending pending,
            String diagnostic
    ) {
        clearArmedCapture();
        String firstLine = pending == null
                ? "写真は登録済み"
                : "P" + (pending.pageIndex + 1) + " は登録済み";
        publish(
                RelayState.ERROR,
                List.of(
                        firstLine,
                        "二重登録を防止中",
                        "短押し: 復旧して次へ"),
                diagnostic + "; committed capture remains locked");
    }

    public void finishReading() {
        serial.execute(this::finishReadingNow);
    }

    private void finishReadingNow() {
        if (committedRecoveryBlocked) {
            publishCommittedPendingLocked(
                    captureReview.peek(),
                    "Finish blocked until committed-photo recovery completes");
            return;
        }
        if (!requireApi()) {
            return;
        }
        if (captureLease.isUnresolved()) {
            publish(
                    RelayState.ERROR,
                    List.of("読取完了を保留", "撮影終了が未確認", "Hi Rokidを再接続"),
                    "Finish rejected while a CXR-L photo lease is unresolved");
            return;
        }
        if (state.isCaptureInProgress() || state == RelayState.AIMING) {
            publish(
                    state,
                    List.of("処理中", "写真の登録完了まで待機", ""),
                    "Finish ignored while capture pipeline is active");
            return;
        }
        CaptureReviewStore.Pending pending = captureReview.peek();
        if (pending != null) {
            publishCaptureReview(
                    pending,
                    "Finish rejected until the pending photo is registered or retaken");
            return;
        }
        if (documentId == 0 || nextPageIndex == 0) {
            publish(
                    RelayState.READING,
                    List.of("ページがありません", "タップで撮影準備", ""),
                    "Finish rejected: empty document");
            return;
        }
        try {
            publish(
                    RelayState.FINALIZING,
                    List.of("読取完了処理", "カメラ停止", "解析中"),
                    "Finalizing document " + documentId);
            api.scanStatus(documentId);
            api.finalizeDocument(documentId);
            if (sessionId == 0) {
                sessionId = api.createExamSession(documentId).getLong("session_id");
                persistWorkflow();
            }
            JSONObject finished = api.finalizeReading(sessionId);
            handleFinalizedSession(
                    finished,
                    "Finalized exam session " + sessionId);
        } catch (Exception error) {
            fail("読取完了処理に失敗しました", error);
        }
    }

    private void handleFinalizedSession(JSONObject finished, String diagnostic) {
        if ("reading".equals(finished.optString("status"))) {
            retryCursor.begin(nextPageIndex);
            publish(
                    RelayState.READING,
                    extractLines(finished.optJSONObject("reading_ack")),
                    diagnostic + "; no problems detected, retry starts at page 0");
            return;
        }
        retryCursor.clear();
        reviewIndex = 0;
        reviewViewPage = 0;
        loadReview();
    }

    public void nextReviewItem() {
        serial.execute(this::nextReviewItemNow);
    }

    private void nextReviewItemNow() {
        if (state != RelayState.REVIEW) {
            return;
        }
        if (reviewViewPage + 1 < reviewViewPageCount) {
            reviewViewPage++;
        } else if (reviewIndex + 1 < reviewProblemCount) {
            reviewIndex++;
            reviewViewPage = 0;
        }
        loadReview();
    }

    public void previousReviewItem() {
        serial.execute(this::previousReviewItemNow);
    }

    private void previousReviewItemNow() {
        if (state != RelayState.REVIEW) {
            return;
        }
        if (reviewViewPage > 0) {
            reviewViewPage--;
        } else if (reviewIndex > 0) {
            reviewIndex--;
            reviewViewPage = 0;
        }
        loadReview();
    }

    private void loadReview() {
        try {
            JSONObject response = api.review(sessionId, reviewIndex, reviewViewPage);
            JSONObject view = response.getJSONObject("glasses_view");
            reviewIndex = response.optInt("index", reviewIndex);
            reviewProblemCount = response.optInt("problem_count", 1);
            reviewViewPage = view.optInt("view_page", reviewViewPage);
            reviewViewPageCount = view.optInt("total_view_pages", 1);
            publish(
                    RelayState.REVIEW,
                    extractLines(view),
                    "Review " + (reviewIndex + 1) + "/" + reviewProblemCount
                            + ", page " + (reviewViewPage + 1) + "/" + reviewViewPageCount);
        } catch (Exception error) {
            fail("解答表示を取得できません", error);
        }
    }

    public void startNewDocument() {
        serial.execute(this::startNewDocumentNow);
    }

    private void startNewDocumentNow() {
        if (committedRecoveryBlocked) {
            publishCommittedPendingLocked(
                    captureReview.peek(),
                    "Workflow reset blocked until committed-photo recovery completes");
            return;
        }
        if (captureLease.isUnresolved()) {
            publish(
                    RelayState.ERROR,
                    List.of("新規読取を保留", "撮影終了が未確認", "Hi Rokidを再接続"),
                    "Workflow reset rejected while a photo lease is unresolved");
            return;
        }
        if (state.isCaptureInProgress()
                || state == RelayState.AIMING
                || state == RelayState.FINALIZING) {
            publish(
                    state,
                    List.of("処理中", "完了まで待機", ""),
                    "Workflow reset rejected while processing is active");
            return;
        }
        CaptureReviewStore.Pending pending = captureReview.peek();
        if (pending != null) {
            publishCaptureReview(
                    pending,
                    "Workflow reset rejected until the pending photo is decided");
            return;
        }
        clearWorkflow();
        publish(
                linkReady ? RelayState.READY : RelayState.DISCONNECTED,
                List.of("新規読取", "タップ: 撮影準備", "長押し: 完了"),
                "Workflow cleared");
    }

    private boolean requireApi() {
        if (api != null) {
            return true;
        }
        fail("先にサーバURLを設定してください", null);
        return false;
    }

    private void publish(RelayState next, List<String> lines, String diagnostic) {
        state = next;
        List<String> safeLines = lines == null || lines.isEmpty()
                ? List.of(next.name(), "", "")
                : lines;
        currentHudLines = safeLines;
        link.showHud(safeLines);
        listener.onUpdate(next, safeLines, diagnostic);
    }

    private void fail(String userMessage, Throwable error) {
        String detail = error == null ? userMessage : userMessage + ": " + error.getMessage();
        publish(
                RelayState.ERROR,
                List.of("エラー", userMessage, "スマホ画面を確認"),
                detail);
    }

    private static List<String> extractLines(JSONObject payload) {
        if (payload == null) {
            return List.of("処理完了", "", "");
        }
        JSONArray array = payload.optJSONArray("lines");
        if (array == null) {
            return List.of("処理完了", "", "");
        }
        List<String> lines = new ArrayList<>(3);
        for (int i = 0; i < Math.min(3, array.length()); i++) {
            lines.add(array.optString(i, ""));
        }
        return lines;
    }

    private void persistWorkflow() {
        preferences.edit()
                .putLong(KEY_DOCUMENT, documentId)
                .putInt(KEY_NEXT_PAGE, nextPageIndex)
                .putLong(KEY_SESSION, sessionId)
                .apply();
    }

    private boolean persistWorkflowSynchronously() {
        return preferences.edit()
                .putLong(KEY_DOCUMENT, documentId)
                .putInt(KEY_NEXT_PAGE, nextPageIndex)
                .putLong(KEY_SESSION, sessionId)
                .commit();
    }

    private boolean persistWorkflowAndFallbackMarkerSynchronously(
            CaptureReviewStore.Pending pending
    ) {
        FallbackCommitMarker marker = FallbackCommitMarker.fromPendingOrNull(pending);
        if (marker == null) {
            return false;
        }
        try {
            return preferences.edit()
                    .putLong(KEY_DOCUMENT, documentId)
                    .putInt(KEY_NEXT_PAGE, nextPageIndex)
                    .putLong(KEY_SESSION, sessionId)
                    .putInt(KEY_COMMITTED_PAGE, marker.pageIndex)
                    .putString(KEY_COMMITTED_JPEG_SHA256, marker.jpegSha256)
                    .commit();
        } catch (RuntimeException writeFailure) {
            return false;
        }
    }

    static boolean clearFallbackOnlyAfterRecovery(
            boolean recoveryCleaned,
            boolean fallbackExists,
            BooleanSupplier clearFallback
    ) {
        if (!recoveryCleaned) {
            return false;
        }
        return !fallbackExists || clearFallback.getAsBoolean();
    }

    /**
     * Completes cleanup for a page the server already accepted. A mismatched
     * pending photo is preserved; only the stale fallback marker is removed.
     */
    private boolean retryCommittedRecoverySynchronously() {
        if (!committedRecoveryBlocked || !persistWorkflowSynchronously()) {
            return !committedRecoveryBlocked;
        }
        CaptureReviewStore.Pending locked = committedPendingLocked;
        boolean unrelatedPendingExists =
                locked == null && captureReview.hasPending();
        if (!unrelatedPendingExists) {
            try {
                captureReviewPersistence.clearAfterCommit();
            } catch (IOException cleanupFailure) {
                return false;
            }
        }
        boolean fallbackExists =
                preferences.contains(KEY_COMMITTED_PAGE)
                        || preferences.contains(KEY_COMMITTED_JPEG_SHA256);
        if (fallbackExists && !clearFallbackCommitMarkerSynchronously()) {
            return false;
        }
        if (locked != null && captureReview.clear(locked)) {
            captureTargetPageIndex = -1;
            listener.onCaptureReviewCleared();
        }
        committedPendingLocked = null;
        committedRecoveryBlocked = false;
        return true;
    }

    private FallbackCommitMarker loadFallbackCommitMarker() {
        boolean hasPage = preferences.contains(KEY_COMMITTED_PAGE);
        boolean hasHash = preferences.contains(KEY_COMMITTED_JPEG_SHA256);
        if (!hasPage && !hasHash) {
            return null;
        }
        FallbackCommitMarker marker;
        try {
            marker = FallbackCommitMarker.restoreOrNull(
                    preferences.getInt(KEY_COMMITTED_PAGE, NO_COMMITTED_PAGE),
                    preferences.getString(KEY_COMMITTED_JPEG_SHA256, ""));
        } catch (RuntimeException invalidPreference) {
            marker = null;
        }
        if (marker == null) {
            clearFallbackCommitMarkerSynchronously();
        }
        return marker;
    }

    private boolean persistFallbackCommitMarkerSynchronously(
            CaptureReviewStore.Pending pending
    ) {
        FallbackCommitMarker marker = FallbackCommitMarker.fromPendingOrNull(pending);
        if (marker == null) {
            return false;
        }
        try {
            return preferences.edit()
                    .putInt(KEY_COMMITTED_PAGE, marker.pageIndex)
                    .putString(KEY_COMMITTED_JPEG_SHA256, marker.jpegSha256)
                    .commit();
        } catch (RuntimeException writeFailure) {
            return false;
        }
    }

    private boolean clearFallbackCommitMarkerSynchronously() {
        try {
            return preferences.edit()
                    .remove(KEY_COMMITTED_PAGE)
                    .remove(KEY_COMMITTED_JPEG_SHA256)
                    .commit();
        } catch (RuntimeException writeFailure) {
            return false;
        }
    }

    private void clearWorkflow() {
        documentId = 0;
        nextPageIndex = 0;
        sessionId = 0;
        reviewIndex = 0;
        reviewViewPage = 0;
        reviewProblemCount = 0;
        reviewViewPageCount = 0;
        captureTargetPageIndex = -1;
        clearArmedCapture();
        retryCursor.clear();
        captureReview.clear();
        try {
            captureReviewPersistence.clear();
        } catch (IOException ignored) {
            // The pending photo is never auto-uploaded even if cleanup later retries.
        }
        listener.onCaptureReviewCleared();
        preferences.edit()
                .remove(KEY_DOCUMENT)
                .remove(KEY_NEXT_PAGE)
                .remove(KEY_SESSION)
                .apply();
    }

    @Override
    public void close() {
        clearArmedCapture();
        captureLease.resetAfterBindingReset();
        watchdog.shutdownNow();
        serial.shutdownNow();
    }

    static final class FallbackCommitMarker {
        private static final int SHA_256_HEX_LENGTH = 64;
        private static final char[] HEX = "0123456789abcdef".toCharArray();

        final int pageIndex;
        final String jpegSha256;

        private FallbackCommitMarker(int pageIndex, String jpegSha256) {
            this.pageIndex = pageIndex;
            this.jpegSha256 = jpegSha256;
        }

        static FallbackCommitMarker fromPendingOrNull(
                CaptureReviewStore.Pending pending
        ) {
            if (pending == null
                    || pending.pageIndex < 0
                    || pending.jpeg == null
                    || pending.jpeg.length == 0) {
                return null;
            }
            return new FallbackCommitMarker(
                    pending.pageIndex,
                    sha256Hex(pending.jpeg));
        }

        static FallbackCommitMarker restoreOrNull(
                int pageIndex,
                String jpegSha256
        ) {
            if (pageIndex < 0
                    || jpegSha256 == null
                    || jpegSha256.length() != SHA_256_HEX_LENGTH) {
                return null;
            }
            for (int i = 0; i < jpegSha256.length(); i++) {
                char character = jpegSha256.charAt(i);
                boolean hexadecimal = (character >= '0' && character <= '9')
                        || (character >= 'a' && character <= 'f')
                        || (character >= 'A' && character <= 'F');
                if (!hexadecimal) {
                    return null;
                }
            }
            return new FallbackCommitMarker(
                    pageIndex,
                    jpegSha256.toLowerCase(Locale.ROOT));
        }

        boolean matches(CaptureReviewStore.Pending pending) {
            return pending != null
                    && pageIndex == pending.pageIndex
                    && jpegSha256.equals(sha256Hex(pending.jpeg));
        }

        private static String sha256Hex(byte[] jpeg) {
            byte[] digest;
            try {
                digest = MessageDigest.getInstance("SHA-256").digest(jpeg);
            } catch (NoSuchAlgorithmException error) {
                throw new IllegalStateException("SHA-256 is unavailable", error);
            }
            char[] encoded = new char[digest.length * 2];
            for (int i = 0; i < digest.length; i++) {
                int value = digest[i] & 0xff;
                encoded[i * 2] = HEX[value >>> 4];
                encoded[i * 2 + 1] = HEX[value & 0x0f];
            }
            return new String(encoded);
        }
    }
}
