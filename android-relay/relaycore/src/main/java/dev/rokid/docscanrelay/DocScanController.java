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

import dev.rokid.docscanglass.input.GlassesInputAction;

/** Serial state machine for capture -> OCR -> upload -> solve -> HUD review. */
public final class DocScanController implements AutoCloseable {
    public interface Listener {
        void onUpdate(RelayState state, List<String> hudLines, String diagnostic);

        default void onCaptureReview(CaptureReviewStore.Pending pending) {
        }

        default void onCaptureReviewCleared() {
        }

        default void onAutoCaptureChanged(boolean running) {
        }

        default void onConfigurationRejected(String message) {
        }

        /** Persist accepted settings before changing the active destination. Never log the key. */
        default void persistConfiguration(String server, String key) throws IOException { }

        default void onListeningReady(long documentId) { }
    }

    private static final String PREFS = "docscan_relay";
    private static final String KEY_SERVER = "server";
    private static final String KEY_DOCUMENT = "document_id";
    private static final String KEY_NEXT_PAGE = "next_page";
    private static final String KEY_SESSION = "session_id";
    private static final String KEY_LOCAL_SESSION = "local_session";
    private static final String KEY_COMMITTED_PAGE = "committed_page_index";
    private static final String KEY_COMMITTED_JPEG_SHA256 = "committed_jpeg_sha256";
    private static final int NO_COMMITTED_PAGE = -1;
    private static final long CAPTURE_TIMEOUT_SECONDS = 30;
    private static final long SHUTTER_STABILIZATION_MILLIS = 1500;
    private static final long CUSTOM_VIEW_ACK_TIMEOUT_MILLIS = 3000;
    // This firmware delivers one tap and nothing else, and the tap is already
    // the retake. Registration therefore has to be the outcome of doing
    // nothing, or it is unreachable from the glasses. A page the framing check
    // passed commits quickly; anything it could not vouch for waits long
    // enough to be tapped away.
    private static final long AUTO_COMMIT_COMPLETE_MILLIS = 4000;
    private static final long AUTO_COMMIT_UNVERIFIED_MILLIS = 12000;
    // Hands-free reading. On the capture-review view a tap closes the
    // CustomView without delivering any AI event, so that state has no usable
    // glasses input at all and no amount of gesture work will give it one.
    // Instead of asking, the relay shoots the same page several times, keeps
    // the frame the recogniser did best on, and registers it.
    private static final int AUTO_BURST_SHOTS = 3;
    // Continuous scanning is what the operator asked for, so the intervals
    // are only long enough to let the camera settle between frames and to
    // let a page be turned. They are not a throttle.
    private static final long AUTO_SHOT_INTERVAL_MILLIS = 400;
    private static final long AUTO_PAGE_TURN_MILLIS = 2500;
    /** Give up on a page that keeps reading as the one already registered. */
    private static final int AUTO_DUPLICATE_BURST_LIMIT = 20;
    /** An unreadable burst is retried at once; nothing was captured to keep. */
    private static final long AUTO_RETRY_IMMEDIATE_MILLIS = 200;
    /**
     * Unreadable bursts keep retrying at full speed for this long before the
     * interval opens up slightly. This is a thermal and battery guard, not a
     * privacy one: the LED stays lit for exactly as long as the camera runs,
     * which is the whole point of it.
     */
    private static final int AUTO_UNREADABLE_RETRY_LIMIT = 40;
    private static final long AUTO_UNREADABLE_BACKOFF_MILLIS = 1200;
    private static final String KEY_PHOTO_WIDTH = "photo_width";
    private static final String KEY_PHOTO_HEIGHT = "photo_height";
    private static final String KEY_PHOTO_QUALITY = "photo_quality";

    private final CaptureSurface link;
    private final ClientIdentity client;
    private final JapaneseOcr ocr;
    private final Listener listener;
    private final SharedPreferences preferences;
    private final ExecutorService serial = Executors.newSingleThreadExecutor();
    private final ScheduledExecutorService watchdog =
            Executors.newSingleThreadScheduledExecutor();
    private final CaptureLease captureLease = new CaptureLease();
    private final CaptureReviewStore captureReview = new CaptureReviewStore();
    private CaptureReviewPersistence captureReviewPersistence;
    private final File localRoot;
    private volatile LocalCaptureSession localSession;
    private String localRestoreError;
    private final ExecutorService localNetwork = Executors.newSingleThreadExecutor();
    private boolean localNetworkBusy;
    private boolean localUploadBlocked;
    private volatile boolean closed;
    private final RetryCursor retryCursor = new RetryCursor();

    private volatile RelayState state = RelayState.DISCONNECTED;
    private volatile PhotoCaptureSettings photoSettings = PhotoCaptureSettings.DEFAULT;
    private volatile long photoRequestedAtMillis;
    private volatile String lastOcrQuality = "";
    private volatile DocScanApi api;
    private String configuredServer = "";
    // Deliberately process-local, as on the phone relay.
    private String configuredKey = "";
    private int imageRotation;
    private boolean linkReady;
    private volatile long documentId;
    private volatile boolean listeningMode;
    private boolean listeningComplete;
    private boolean listeningFailed;
    private int nextPageIndex;
    private int captureTargetPageIndex = -1;
    private CaptureReviewStore.Pending committedPendingLocked;
    private boolean committedRecoveryBlocked;
    private int armedPageIndex = -1;
    private boolean armedReplacingPending;
    private long aimingGeneration;
    private long captureGuideViewGeneration =
            CaptureSurface.NO_VIEW_GENERATION;
    private boolean captureGuideAcknowledged;
    private boolean stabilizationTimerScheduled;
    private long reviewGeneration;
    private long reviewViewGeneration = CaptureSurface.NO_VIEW_GENERATION;
    private boolean autoCommitArmed;
    private boolean autoCommitScheduled;
    private long reviewDeadlineMillis;
    private boolean autoCaptureEnabled;
    private boolean manualCaptureRequested;
    private boolean ocrInFlight;
    private boolean finishCaptureRequested;
    private long autoRunGeneration;
    private static final long LOCAL_REVIEW_MILLIS = 3000;
    private int autoShotsRemaining;
    private int autoShotsTaken;
    private CaptureReviewStore.Pending autoBest;
    private double autoBestScore;
    private String lastRegisteredPageText = "";
    private int duplicateBurstsSeen;
    private int unreadableBurstsSeen;
    private volatile long sessionId;
    private int reviewIndex;
    private int reviewViewPage;
    private int reviewProblemCount;
    private int reviewViewPageCount;
    private List<String> currentHudLines =
            List.of("DocScan", "接続を待っています", "");

    public DocScanController(
            Context context,
            CaptureSurface link,
            JapaneseOcr ocr,
            Listener listener,
            ClientIdentity client
    ) {
        this.link = link;
        this.ocr = ocr;
        this.listener = listener;
        this.client = client;
        preferences = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        localRoot = new File(context.getFilesDir(), "local-scans");
        String localId = preferences.getString(KEY_LOCAL_SESSION, "");
        if (link.supportsLocalCaptureReview() && !localId.isEmpty()) {
            try { localSession = LocalCaptureSession.load(localRoot, localId); }
            catch (IOException error) { localRestoreError = "保存した読取記録を復元できません"; }
        }
        captureReviewPersistence = new CaptureReviewPersistence(
                localSession == null ? new File(context.getFilesDir(), "pending-capture-v1.bin")
                        : new File(localSession.directory(), "pending.bin"));
        configuredServer = preferences.getString(KEY_SERVER, "");
        photoSettings = PhotoCaptureSettings.ofOrDefault(
                preferences.getInt(KEY_PHOTO_WIDTH, PhotoCaptureSettings.DEFAULT.width),
                preferences.getInt(KEY_PHOTO_HEIGHT, PhotoCaptureSettings.DEFAULT.height),
                preferences.getInt(KEY_PHOTO_QUALITY, PhotoCaptureSettings.DEFAULT.quality));
        documentId = preferences.getLong(KEY_DOCUMENT, 0);
        nextPageIndex = preferences.getInt(KEY_NEXT_PAGE, 0);
        sessionId = preferences.getLong(KEY_SESSION, 0);
        FallbackCommitMarker fallbackCommitMarker = localSession == null ? loadFallbackCommitMarker() : null;
        CaptureReviewStore.Pending restored = null;
        if (localSession != null) {
            documentId = localSession.documentId();
            nextPageIndex = localSession.pageCount();
            sessionId = localSession.sessionId();
            listeningMode = localSession.listening();
            try {
                if (new File(localSession.directory(), "pending.bin").exists()) {
                    restored = captureReviewPersistence.readPending();
                    if (localSession.contains(restored)) {
                        restored = null; // Commit reached disk before pending-file cleanup was interrupted.
                        captureReviewPersistence.clearAfterCommit();
                    }
                }
            } catch (IOException error) { localRestoreError = "保存写真を復元できません。原本は保持しています"; }
        } else if (localRestoreError == null) restored = captureReviewPersistence.loadOrNull();
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
            captureReview.stage(restored);
            captureTargetPageIndex = restored.pageIndex;
            imageRotation = restored.rotationDegrees;
        }
    }

    public RelayState getState() {
        return state;
    }

    /** The finalized exam session, or 0 before one exists. */
    public long sessionId() {
        return sessionId;
    }

    /** The configured client, so a caller never builds an unconfigured one. */
    public DocScanApi api() {
        return api;
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
        applyGlassesCommandNow(CaptureActionRouter.route(state, gesture));
    }

    /** Routes local, normalized input against the state at execution time. */
    public void onGlassesAction(GlassesInputAction action) {
        if (action == null) {
            return;
        }
        try {
            serial.execute(() -> {
                if (link.supportsLocalCaptureReview() && state != RelayState.REVIEW) {
                    if (action == GlassesInputAction.BACK) {
                        finishLocalCaptureNow();
                    } else if (action == GlassesInputAction.SHORT_TAP) {
                        manualCaptureNow();
                    }
                    return;
                }
                applyGlassesCommandNow(CaptureActionRouter.route(state, action));
            });
        } catch (RejectedExecutionException ignored) {
            // The activity is already closing.
        }
    }

    private void applyGlassesCommandNow(CaptureActionRouter.Command command) {
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

    public long documentId() { return documentId; }

    /** The startup screen can offer recovery without making an HTTP request. */
    public boolean hasLocalSession() { return localSession != null || localRestoreError != null; }
    public boolean hasSavedWorkflow() { return !savedCaptures().isEmpty(); }
    public boolean isListeningMode() { return listeningMode; }

    public static final class SavedCapture {
        public final String id;
        public final String label;
        public final boolean listening;
        private SavedCapture(String id, String label, boolean listening) {
            this.id = id; this.label = label; this.listening = listening;
        }
    }

    /** Only unfinished records; starting a new scan never hides an earlier one. */
    public List<SavedCapture> savedCaptures() {
        List<SavedCapture> result = new ArrayList<>();
        File[] directories = localRoot.listFiles(File::isDirectory);
        if (directories != null) {
            java.util.Arrays.sort(directories, java.util.Comparator.comparingLong(File::lastModified).reversed());
            for (File directory : directories) {
                if (!directory.getName().matches("[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}")) continue;
                try {
                    LocalCaptureSession saved = LocalCaptureSession.load(localRoot, directory.getName());
                    if (!saved.unfinished()) continue;
                    String date = new SimpleDateFormat("M/d HH:mm", Locale.JAPAN)
                            .format(new Date(new File(directory, "state.properties").lastModified()));
                    result.add(new SavedCapture(saved.id(), date + (saved.listening() ? " 音声 " : " 通常 ")
                            + saved.pageCount() + "枚", saved.listening()));
                } catch (IOException error) {
                    result.add(new SavedCapture(directory.getName(), "保存記録の復旧が必要", false));
                }
            }
        }
        if (localSession == null && localRestoreError == null && (captureReview.hasPending() || documentId > 0)) {
            result.add(new SavedCapture("", "以前の読取", listeningMode));
        }
        return result;
    }

    /** Persist the operator's explicit exit before the Activity disappears. */
    public boolean closeLocalSession() {
        try {
            if (localSession != null) localSession.close();
            closed = true;
            if (api != null && link.supportsLocalCaptureReview()) api.cancelRequests();
            return true;
        } catch (IOException error) { return false; }
    }

    public void configureForLocalStart(String server, String key, int rotation) {
        configureAsync(server, key, rotation, false);
    }

    public void startLocalSession(boolean listening) {
        startLocalSession(listening, accepted -> { });
    }

    public void startLocalSession(boolean listening, java.util.function.Consumer<Boolean> selection) {
        serial.execute(() -> {
            if (!link.supportsLocalCaptureReview() || !requireApi() || captureLease.isUnresolved()
                    || state.isCaptureInProgress() || state == RelayState.AIMING || state == RelayState.FINALIZING
                    || localNetworkBusy || closed) { selection.accept(false); return; }
            boolean accepted = false;
            try {
                LocalCaptureSession next = LocalCaptureSession.create(localRoot, configuredServer, listening);
                if (!preferences.edit().putString(KEY_LOCAL_SESSION, next.id()).remove(KEY_DOCUMENT)
                        .remove(KEY_NEXT_PAGE).remove(KEY_SESSION).remove(KEY_COMMITTED_PAGE)
                        .remove(KEY_COMMITTED_JPEG_SHA256).commit()) throw new IOException("読取記録を選択できません");
                // The previous session and its pending file stay in their original directory.
                localSession = next;
                localRestoreError = null;
                localUploadBlocked = false;
                captureReviewPersistence = new CaptureReviewPersistence(new File(next.directory(), "pending.bin"));
                captureReview.clear();
                committedPendingLocked = null;
                committedRecoveryBlocked = false;
                documentId = sessionId = 0;
                nextPageIndex = 0;
                captureTargetPageIndex = -1;
                retryCursor.clear();
                autoCaptureEnabled = false;
                autoShotsRemaining = 0;
                autoBest = null;
                lastRegisteredPageText = "";
                listeningMode = listening;
                listeningComplete = listeningFailed = finishCaptureRequested = false;
                listener.onCaptureReviewCleared();
                accepted = true;
                selection.accept(true);
                publish(RelayState.READY, List.of("読取を開始", "用紙全体を入れてください", ""), "Started local capture session");
                startLocalCapture();
            } catch (Exception error) { fail("読取を開始できません", error); if (!accepted) selection.accept(false); }
        });
    }

    public void resumeLocalSession() {
        resumeLocalSession(localSession == null ? "" : localSession.id());
    }

    public void resumeLocalSession(String id) {
        resumeLocalSession(id, accepted -> { });
    }

    public void resumeLocalSession(String id, java.util.function.Consumer<Boolean> selection) {
        serial.execute(() -> {
            if (closed || localNetworkBusy || captureLease.isUnresolved() || state.isCaptureInProgress()
                    || state == RelayState.AIMING || state == RelayState.FINALIZING || !requireApi()) {
                selection.accept(false); return;
            }
            boolean accepted = false;
            try {
                if (id.isEmpty()) {
                    if (localRestoreError != null) { fail(localRestoreError, null); selection.accept(false); return; }
                    accepted = true;
                    selection.accept(true);
                    resumeNow(); return;
                }
                LocalCaptureSession saved = LocalCaptureSession.load(localRoot, id);
                if (!saved.server().equals(configuredServer)) {
                    fail("中断資料と接続先が異なります", null); selection.accept(false); return;
                }
                File pendingFile = new File(saved.directory(), "pending.bin");
                CaptureReviewPersistence persistence = new CaptureReviewPersistence(pendingFile);
                CaptureReviewStore.Pending pending = pendingFile.exists() ? persistence.readPending() : null;
                if (pending != null && saved.contains(pending)) pending = null;
                if (!preferences.edit().putString(KEY_LOCAL_SESSION, saved.id()).commit()) {
                    throw new IOException("読取記録を選択できません");
                }
                saved.resume();
                localSession = saved;
                localRestoreError = null;
                localUploadBlocked = false;
                captureReviewPersistence = persistence;
                captureReview.clear();
                if (pending != null) captureReview.stage(pending);
                captureTargetPageIndex = pending == null ? -1 : pending.pageIndex;
                if (pending != null) imageRotation = pending.rotationDegrees;
                documentId = saved.documentId();
                sessionId = saved.sessionId();
                nextPageIndex = saved.pageCount();
                committedPendingLocked = null;
                committedRecoveryBlocked = false;
                retryCursor.clear();
                listeningComplete = listeningFailed = finishCaptureRequested = false;
                listeningMode = saved.listening();
                accepted = true;
                selection.accept(true);
                if (saved.phase() == LocalCaptureSession.Phase.REVIEW) {
                    publish(RelayState.REVIEW, List.of("答案を再開", "", ""), "Resumed saved answer session");
                    return;
                }
                if (saved.phase() == LocalCaptureSession.Phase.ANALYSIS) {
                    finishCaptureRequested = true;
                    publish(RelayState.FINALIZING, List.of("解析を再開", "資料は保存済み", ""), "Resumed saved analysis");
                } else if (captureReview.hasPending()) {
                    publishCaptureReview(captureReview.peek(), "Resumed local pending photo", true);
                } else {
                    publish(RelayState.READING, List.of("読取を再開", nextPageIndex + "枚保存済み", ""), "Resumed local capture");
                    startLocalCapture();
                }
                queueLocalUpload();
            } catch (Exception error) { fail("読取を復元できません", error); if (!accepted) selection.accept(false); }
        });
    }

    public void setListeningMode(boolean enabled) { listeningMode = enabled && link.supportsLocalCaptureReview(); }

    public void completeListening() {
        serial.execute(() -> { if (!listeningFailed) { listeningComplete = true; finishReadingNow(); } });
    }

    public void onListeningError() {
        try { serial.execute(() -> {
            listeningFailed = true;
            autoCaptureEnabled = false;
            autoRunGeneration++;
            reviewGeneration++;
            autoCommitArmed = false;
            publish(RelayState.ERROR, List.of("録音が中断されました", "原音は保存済み", "終了して録音を確認"),
                    "Listening stopped; original audio retained");
        }); } catch (RejectedExecutionException ignored) { }
    }

    private void startLocalCapture() throws Exception {
        if (!link.supportsLocalCaptureReview()) return;
        if (listeningMode) {
            api.requireLocalAsr();
            if (documentId == 0) {
                documentId = api.createDocument("Rokid listening").getLong("document_id");
                if (localSession != null) localSession.bindDocument(documentId);
                persistWorkflow();
            }
            listener.onListeningReady(documentId);
        } else startAutoCaptureNow();
    }

    private void manualCaptureNow() {
        if ((finishCaptureRequested && state != RelayState.CAPTURE_REVIEW) || captureLease.isTimedOut()
                || state == RelayState.FINALIZING || state == RelayState.UPLOADING) return;
        if (state == RelayState.CAPTURE_REVIEW) finishCaptureRequested = false;
        manualCaptureRequested = true;
        autoRunGeneration++;
        autoCommitArmed = false;
        reviewGeneration++;
        // A tap during a burst selects the in-flight still; it never starts a second photo.
        if (state == RelayState.CAPTURING || ocrInFlight) return;
        if (reviewBufferedBurst()) return;
        autoShotsRemaining = 0;
        autoBest = null;
        if (state == RelayState.CAPTURE_REVIEW) {
            retakePendingCaptureNow(null);
        } else if (state != RelayState.AIMING && state != RelayState.STABILIZING) {
            captureNextPageNow();
        } else if (state == RelayState.AIMING && captureGuideAcknowledged) {
            triggerArmedCaptureNow();
        }
    }

    private void finishLocalCaptureNow() {
        finishCaptureRequested = true;
        autoRunGeneration++;
        if (captureLease.isUnresolved() || ocrInFlight
                || state == RelayState.UPLOADING || state == RelayState.FINALIZING) return;
        if (reviewBufferedBurst()) return;
        if (state == RelayState.CAPTURE_REVIEW) {
            if (!autoCommitArmed) publishCaptureReview(captureReview.peek(), "Retry retained photo after operator action", true);
            return; // keep the last full review window
        }
        clearArmedCapture();
        autoShotsRemaining = 0;
        if (captureReview.peek() != null) {
            publishCaptureReview(captureReview.peek(), "Review last photo before finishing", true);
            return;
        }
        state = RelayState.READING;
        finishReadingNow();
    }

    private boolean reviewBufferedBurst() {
        if (state != RelayState.OCR || ocrInFlight || autoBest == null) return false;
        CaptureReviewStore.Pending shot = autoBest;
        autoBest = null;
        autoShotsRemaining = 0;
        stageCaptureReview(shot, null);
        return true;
    }

    /** A hidden/covered still must receive a fresh uninterrupted review window. */
    public void onCaptureReviewHidden(long generation) {
        try { serial.execute(() -> {
            if (generation == reviewViewGeneration && state == RelayState.CAPTURE_REVIEW) {
                reviewGeneration++;
                autoCommitScheduled = false;
                reviewDeadlineMillis = 0;
            }
        }); } catch (RejectedExecutionException ignored) { /* Activity is closing. */ }
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
        // Deliberately not consulting isCustomViewOpened() here. This runs only
        // when an AI-exit arrived and no open callback followed within 650 ms,
        // so our own bookkeeping already proves the view is not confirmed open.
        // The service disagrees: every close callback on this firmware reports
        // remoteStillOpen=true, including the ones the user caused by leaving
        // for the default screen. Trusting it stranded the operator on the home
        // screen, because recovery skipped itself every single time.
        long restoredGeneration;
        CaptureReviewStore.Pending pending = captureReview.peek();
        if (state == RelayState.CAPTURE_REVIEW && pending != null) {
            publishCaptureReview(
                    pending,
                    "Re-presented pending review after a lifecycle close; no operator action inferred");
            return;
        }
        if ((state == RelayState.AIMING || state == RelayState.STABILIZING)
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
            if (restoredGeneration != CaptureSurface.NO_VIEW_GENERATION) {
                trackCaptureGuideOpen(restoredGeneration);
            }
        } else {
            restoredGeneration = link.showHud(currentHudLines);
        }
        boolean restored =
                restoredGeneration != CaptureSurface.NO_VIEW_GENERATION;
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
        if (state == RelayState.CAPTURE_REVIEW) {
            scheduleAutoCommitOnAck(generation, purpose);
            return;
        }
        if (generation != captureGuideViewGeneration
                || (state != RelayState.AIMING
                && state != RelayState.STABILIZING)) {
            return;
        }
        captureGuideAcknowledged = true;
        if (state == RelayState.AIMING && link.supportsLocalCaptureReview()
                && (autoCaptureEnabled || manualCaptureRequested)) {
            triggerArmedCaptureNow();
            return;
        }
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
            publishCaptureReview(
                    pending,
                    "Recovered unregistered photo after app restart",
                    true);
        });
    }

    /**
     * Starts/reconfigures an in-process surface. Configuration precedes link
     * readiness and restoration in one task; no intermediate READY can hide
     * the saved workflow. Null overrides preserve the available configuration.
     */
    public void configureAndResume(String serverOverride, String keyOverride, int rotationDegrees) {
        configureAsync(serverOverride, keyOverride, rotationDegrees, true);
    }

    private void configureAsync(String serverOverride, String keyOverride, int rotationDegrees, boolean resume) {
        try {
            serial.execute(() -> {
                String server = serverOverride == null ? configuredServer : serverOverride;
                String normalizedServer = server.trim().replaceAll("/+$", "");
                String key = keyOverride == null
                        ? (normalizedServer.equals(configuredServer) ? configuredKey : "")
                        : keyOverride;
                try {
                    configure(server, key, rotationDegrees, !resume && link.supportsLocalCaptureReview());
                } catch (RuntimeException error) {
                    if (api == null) {
                        fail("サーバ設定を確認してください", error);
                    } else {
                        // A rejected Intent cannot cancel a live capture or
                        // hide its pending photo. Report outside the workflow.
                        listener.onConfigurationRejected(error.getMessage());
                    }
                    return;
                }
                linkReady = true;
                if (!resume) return;
                if (!captureReview.hasPending() && documentId == 0 && sessionId == 0) {
                    try {
                        if (!"ok".equalsIgnoreCase(api.health().optString("status", ""))) {
                            throw new IllegalStateException("health status is not ok");
                        }
                        api.settings();
                    } catch (Exception error) {
                        fail("サーバへ接続できません", error);
                        return;
                    }
                }
                resumeNow();
            });
        } catch (RejectedExecutionException ignored) {
            // The activity is already closing.
        }
    }

    public void configure(String serverUrl, String apiKey, int rotationDegrees) {
        configure(serverUrl, apiKey, rotationDegrees, false);
    }

    private void configure(String serverUrl, String apiKey, int rotationDegrees, boolean localStartup) {
        boolean beforeSelection = localStartup && (state == RelayState.DISCONNECTED || state == RelayState.ERROR);
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
        DocScanApi candidate = new DocScanApi(serverUrl, apiKey, client);
        String previousServer = preferences.getString(KEY_SERVER, "");
        String normalizedServer = serverUrl.trim().replaceAll("/+$", "");
        if (localStartup && localSession == null && !normalizedServer.equals(previousServer)
                && (captureReview.hasPending() || documentId > 0 || sessionId > 0)) {
            throw new IllegalStateException("以前の読取の接続先を維持して復元してください");
        }
        if (!beforeSelection && captureReview.hasPending()
                && !normalizedServer.equals(previousServer)) {
            throw new IllegalStateException(
                    "未登録写真の送信先は変更できません。先に登録または破棄してください");
        }
        if (!beforeSelection && localSession != null && !localSession.server().equals(normalizedServer)) {
            throw new IllegalStateException("保存資料の接続先を変更できません。別の読取記録として設定してください");
        }
        try {
            listener.persistConfiguration(normalizedServer, apiKey);
        } catch (IOException error) {
            throw new IllegalStateException("接続設定を保存できません");
        }
        configuredServer = normalizedServer;
        configuredKey = apiKey == null ? "" : apiKey.trim();
        imageRotation = JapaneseOcr.normalizeRotation(rotationDegrees);
        api = candidate;
        if (!beforeSelection && !captureReview.hasPending()
                && !previousServer.isEmpty()
                && !previousServer.equals(configuredServer)) {
            clearWorkflow();
        }
        preferences.edit().putString(KEY_SERVER, configuredServer).apply();
    }

    public PhotoCaptureSettings captureSettings() {
        return photoSettings;
    }

    /**
     * Changes the {@code takePhoto} arguments used by the next capture.
     *
     * <p>The usable capture size depends on the glasses firmware and can only
     * be found by probing on the device, so this is adjustable at runtime: a
     * rebuild between probes would cost a reinstall and a Hi Rokid
     * re-authorization for every step of the sweep.</p>
     */
    public void applyCaptureSettings(PhotoCaptureSettings settings) {
        if (settings == null) {
            throw new IllegalArgumentException("撮影設定が指定されていません");
        }
        if (captureLease.isUnresolved() || state.isCaptureInProgress()) {
            throw new IllegalStateException(
                    "撮影処理中です。完了してから撮影設定を変更してください");
        }
        photoSettings = settings;
        preferences.edit()
                .putInt(KEY_PHOTO_WIDTH, settings.width)
                .putInt(KEY_PHOTO_HEIGHT, settings.height)
                .putInt(KEY_PHOTO_QUALITY, settings.quality)
                .apply();
        listener.onUpdate(state, currentHudLines, "撮影設定 " + settings.describe());
    }

    /** Advances the capture sweep by one probe without needing a rebuild. */
    public PhotoCaptureSettings applyNextCapturePreset() {
        PhotoCaptureSettings next = PhotoCaptureSettings.nextPreset(photoSettings);
        applyCaptureSettings(next);
        return next;
    }

    public void verifyServer() {
        serial.execute(() -> {
            if (!requireApi()) {
                return;
            }
            CaptureReviewStore.Pending pending = captureReview.peek();
            if (pending != null) {
                listener.onCaptureReview(pending);
                publishCaptureReview(
                        pending,
                        "Recovered unregistered photo review",
                        true);
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

    public void onCaptureLinkStateChanged(boolean ready, CaptureLinkEvent event) {
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
                resumeNow();
            });
        } catch (RejectedExecutionException ignored) {
            // The activity is already closing.
        }
    }

    public void resume() {
        serial.execute(this::resumeNow);
    }

    private void resumeNow() {
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
            publishCaptureReview(
                    pending,
                    "Recovered unregistered photo review",
                    true);
            return;
        }
        try {
            if (sessionId > 0) {
                handleFinalizedSession(
                        resumeAnalysis(),
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
                    sessionId = api.createExamSession(documentId, listeningMode)
                            .getLong("session_id");
                    persistWorkflow();
                    handleFinalizedSession(
                            resumeAnalysis(),
                            "Recovered finalized document " + documentId);
                    return;
                }
                publish(
                        RelayState.READING,
                        List.of(
                                "読取を再開",
                                nextPageIndex + "ページ登録済",
                                "撮影準備はスマホ"),
                        "Recovered document " + documentId);
                startLocalCapture();
                return;
            }
            publish(
                    RelayState.READY,
                    List.of("準備完了", "撮影準備はスマホ", "読取完了はスマホ"),
                    "Ready for a new document");
            startLocalCapture();
        } catch (Exception error) {
            fail("前回状態を復元できません", error);
        }
    }

    private JSONObject resumeAnalysis() throws Exception {
        if (listeningMode) api.attachDocumentAudio(sessionId);
        publish(RelayState.FINALIZING, List.of("解析を再開", "カメラ停止", ""), "Resuming analysis");
        return link.supportsLocalCaptureReview() ? api.finalizeReadingLocal(sessionId) : api.finalizeReading(sessionId);
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
                    List.of("再撮影対象なし", "撮影準備はスマホ", ""),
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
        if (!requireLink()) {
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
        if (state == RelayState.CAPTURE_REVIEW && captureReview.peek() != null) {
            // Pressing the shutter while looking at a photo can only mean
            // "take another one". Answering "撮影準備なし" was a dead end that
            // made the operator hunt for the right button.
            if (autoCaptureEnabled) {
                beginAutoBurst();
            } else {
                retakePendingCaptureNow(null);
            }
            return;
        }
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
                List.of("撮影を取消", "撮影準備はスマホ", "読取完了はスマホ"),
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
                        CaptureSurface.NO_VIEW_GENERATION;
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
                        "確認画面まで静止",
                        "約5秒 動かない")
                : List.of(
                        "P" + (pageIndex + 1)
                                + (replacingPending ? " 撮り直し準備" : " 撮影準備"),
                        "40〜60cm・中心を＋へ",
                        "シャッターはスマホ");
        long viewGeneration =
                link.showCaptureAiming(pageIndex + 1, replacingPending, stabilizing);
        if (viewGeneration == CaptureSurface.NO_VIEW_GENERATION) {
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
        captureGuideViewGeneration = CaptureSurface.NO_VIEW_GENERATION;
        captureGuideAcknowledged = false;
        stabilizationTimerScheduled = false;
    }

    private void requestPhotoAt(int pageIndex, boolean replacingPending) {
        if (state != RelayState.STABILIZING) {
            return;
        }
        if (!requireLink()) {
            return;
        }
        CaptureReviewStore.Pending pending = captureReview.peek();
        long attempt = CaptureLease.NO_TOKEN;
        boolean photoRequestMayBeActive = false;
        try {
            if (documentId == 0 && localSession == null) {
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
            PhotoCaptureSettings settings = photoSettings;
            publish(
                    RelayState.CAPTURING,
                    List.of("撮影中", "40〜60cm離す", "用紙全体を入れて静止"),
                    "Requesting glasses photo for page index " + pageIndex
                            + " (" + settings.describe() + ")");
            photoRequestedAtMillis = System.currentTimeMillis();
            CaptureSurface.PhotoStartResult startResult =
                    link.takePhoto(settings.width, settings.height, settings.quality);
            if (startResult == CaptureSurface.PhotoStartResult.REJECTED) {
                throw new IllegalStateException("takePhoto returned false");
            }
            photoRequestMayBeActive = true;
            if (startResult == CaptureSurface.PhotoStartResult.UNKNOWN) {
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
        if (link.supportsLocalCaptureReview() && captureLease.isTimedOut()) return;
        CaptureLease.Completion completion = captureLease.complete();
        if (listeningFailed) return;
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
            listener.onUpdate(
                    state,
                    currentHudLines,
                    CaptureDiagnostics.photoReceived(photoSettings, 0, captureElapsedMillis()));
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
                CaptureDiagnostics.photoReceived(
                        photoSettings, jpeg.length, captureElapsedMillis()));
        ocrInFlight = true;
        ocr.recognize(jpeg, uploadRotation, new JapaneseOcr.Callback() {
            @Override
            public void onResult(String text, OcrQuality quality, PageFraming framing) {
                lastOcrQuality = quality == null ? "" : quality.describe();
                serial.execute(
                        () -> stageCaptureReview(
                                uploadIndex, jpeg, text, uploadRotation, "", framing, quality));
            }

            @Override
            public void onError(Throwable error) {
                lastOcrQuality = "";
                String detail = error == null || error.getMessage() == null
                        ? "unknown OCR error"
                        : error.getMessage();
                serial.execute(
                        () -> stageCaptureReview(
                                uploadIndex,
                                jpeg,
                                "",
                                uploadRotation,
                                detail,
                                PageFraming.UNKNOWN,
                                null));
            }
        });
    }

    public void onPhotoError(String message, Throwable cause) {
        try {
            serial.execute(() -> {
                if (link.supportsLocalCaptureReview() && captureLease.isUnresolved()) {
                    captureLease.markUnknown();
                    autoCaptureEnabled = false;
                    autoRunGeneration++;
                    autoShotsRemaining = 0;
                    autoBest = null;
                    fail("カメラ状態が不明です。アプリを終了して再起動してください", null);
                    return;
                }
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
                    fail(userMessage, detail, !linkReady ? RelayState.DISCONNECTED
                            : documentId > 0 ? RelayState.READING : RelayState.READY);
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
                // The request that produced no callback is the measurement the
                // capture sweep is after, so it has to survive the failure.
                fail(
                        "写真が返りませんでした。安全のためHi Rokidを再接続してください",
                        new IllegalStateException(CaptureDiagnostics.photoNoCallback(
                                photoSettings, captureElapsedMillis())));
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
            String ocrFailure,
            PageFraming framing,
            OcrQuality quality
    ) {
        stageCaptureReview(new CaptureReviewStore.Pending(pageIndex, jpeg, ocrText,
                rotationDegrees, ocrFailure, framing, photoRequestedAtMillis), quality);
    }

    private void stageCaptureReview(CaptureReviewStore.Pending candidate, OcrQuality quality) {
        ocrInFlight = false;
        if (listeningFailed || closed) return;
        if (autoShotsRemaining > 0) {
            acceptAutoShot(candidate, quality);
            return;
        }
        int pageIndex = candidate.pageIndex;
        CaptureReviewStore.Pending previous = captureReview.peek();
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
                                "再撮影はスマホ",
                                "登録はしていません"),
                        "Initial review photo rejected because durable save failed: "
                                + error.getMessage());
            }
            return;
        }
        listener.onCaptureReview(pending);
        String diagnostic = "Photo awaiting confirmation: page " + pageIndex
                + ", " + photoSettings.describe()
                + ", framing: " + pending.framing
                + ", OCR characters: " + pending.ocrCharacters();
        if (!lastOcrQuality.isEmpty()) {
            diagnostic += " (" + lastOcrQuality + ")";
        }
        if (pending.hasOcrFailure()) {
            diagnostic += ", OCR error: " + pending.ocrFailure;
        }
        publishCaptureReview(pending, diagnostic, true);
    }

    public void confirmPendingCapture() {
        serial.execute(this::confirmPendingCaptureNow);
    }

    private void confirmPendingCaptureNow() {
        if (closed) return;
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
                    List.of("確認写真なし", "撮影準備はスマホ", ""),
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
        if (link.supportsLocalCaptureReview() && (reviewDeadlineMillis == 0
                || android.os.SystemClock.elapsedRealtime() < reviewDeadlineMillis
                || !link.isCaptureReviewVisible(reviewViewGeneration))) return;
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
        if (localSession != null) commitLocalPhoto(confirmation);
        else uploadCapturedPage(confirmation);
    }

    private void commitLocalPhoto(CaptureReviewStore.Confirmation confirmation) {
        CaptureReviewStore.Pending pending = confirmation.pending();
        try {
            localSession.commit(pending);
        } catch (IOException error) {
            publishCaptureReview(pending, "Local photo save failed; previous revision retained");
            return;
        }
        nextPageIndex = localSession.pageCount();
        retryCursor.onUploaded(pending.pageIndex);
        captureReview.clear(confirmation);
        captureTargetPageIndex = -1;
        autoCommitArmed = false;
        reviewGeneration++;
        try { captureReviewPersistence.clearAfterCommit(); }
        catch (IOException ignored) { /* Recovery compares the retained pending file with the committed revision. */ }
        lastRegisteredPageText = pending.ocrText;
        manualCaptureRequested = false;
        listener.onCaptureReviewCleared();
        publish(RelayState.READING, List.of(nextPageIndex + "枚保存済み", "次のページへ", "ダブルタップで撮影終了"),
                "Photo committed locally; network upload queued");
        queueLocalUpload();
        if (finishCaptureRequested) finishReadingNow();
        else if (autoCaptureEnabled) scheduleAuto(this::beginAutoBurst, AUTO_PAGE_TURN_MILLIS);
    }

    private void queueLocalUpload() {
        if (localNetworkBusy || localUploadBlocked || localSession == null || closed) return;
        LocalCaptureSession saved = localSession;
        DocScanApi destination = api;
        if (destination == null || !saved.server().equals(configuredServer)) return;
        localNetworkBusy = true;
        localNetwork.execute(() -> {
            boolean failed = false;
            boolean analysisStarted = false;
            boolean httpInProgress = false;
            boolean retryable = false;
            JSONObject finished = null;
            try {
                LocalCaptureSession.Page page = saved.nextUnsent();
                if (page != null && saved.documentId() == 0) {
                    // An ambiguous create can leave an empty server document; images only use the durably bound ID.
                    httpInProgress = true;
                    JSONObject created = destination.createDocument("Rokid scan");
                    httpInProgress = false;
                    saved.bindDocument(created.getLong("document_id"));
                }
                while (!closed && page != null) {
                    CaptureReviewStore.Pending photo = saved.read(page);
                    httpInProgress = true;
                    destination.uploadPage(saved.documentId(), photo.pageIndex, photo.jpeg, photo.ocrText,
                            photo.rotationDegrees, photo.capturedAtMillis);
                    httpInProgress = false;
                    saved.acknowledge(page);
                    page = saved.nextUnsent();
                }
                if (!closed && saved.phase() == LocalCaptureSession.Phase.ANALYSIS && saved.documentId() > 0) {
                    analysisStarted = true;
                    destination.finalizeDocument(saved.documentId());
                    if (saved.sessionId() == 0) saved.bindSession(destination.createExamSession(saved.documentId(), saved.listening()).getLong("session_id"));
                    if (saved.listening()) destination.attachDocumentAudio(saved.sessionId());
                    finished = destination.finalizeReadingLocal(saved.sessionId());
                    if (!closed) saved.setPhase("reading".equals(finished.optString("status"))
                            ? LocalCaptureSession.Phase.CAPTURE : LocalCaptureSession.Phase.REVIEW);
                }
            } catch (Exception error) {
                failed = true;
                retryable = error instanceof IOException && httpInProgress && !analysisStarted;
                if (error instanceof DocScanApi.ApiException) {
                    int status = ((DocScanApi.ApiException) error).getStatusCode();
                    retryable &= status == 408 || status == 429 || status >= 500;
                }
            }
            final boolean retry = retryable;
            final boolean stopped = failed && !retryable;
            final boolean analysisFailed = failed && analysisStarted;
            final JSONObject result = finished;
            try { serial.execute(() -> {
                localNetworkBusy = false;
                if (closed || localSession != saved) return;
                documentId = saved.documentId();
                sessionId = saved.sessionId();
                persistWorkflow();
                if (stopped) {
                    localUploadBlocked = true;
                    fail(analysisFailed ? "解析を停止しました。資料は保存済みです"
                            : "保存・送信処理を停止しました。原本は保持しています", null);
                } else if (result != null) handleFinalizedSession(result, "Local session analysis finished");
                else if (retry) {
                    listener.onUpdate(state, currentHudLines, "Network work paused; local images retained for retry");
                    if (state == RelayState.FINALIZING) publish(state,
                            List.of("接続を待っています", "資料は保存済み", "ダブルタップ2回で終了"), "Waiting to retry saved session");
                    watchdog.schedule(() -> {
                        try { serial.execute(this::queueLocalUpload); } catch (RejectedExecutionException ignored) { }
                    }, 5, TimeUnit.SECONDS);
                } else {
                    try {
                        if (saved.nextUnsent() != null || saved.phase() == LocalCaptureSession.Phase.ANALYSIS) queueLocalUpload();
                    } catch (IOException error) { fail("保存ページを読み出せません", null); }
                }
            }); } catch (RejectedExecutionException ignored) { }
        });
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
                    List.of("確認写真なし", "撮影準備はスマホ", ""),
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
                    pending.rotationDegrees,
                    pending.capturedAtMillis);
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
                    "撮影準備はスマホ");
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
                lastRegisteredPageText = pending.ocrText;
                manualCaptureRequested = false;
                if (link.supportsLocalCaptureReview() && finishCaptureRequested) {
                    finishReadingNow();
                } else if (autoCaptureEnabled) {
                    scheduleAuto(this::beginAutoBurst, AUTO_PAGE_TURN_MILLIS);
                }
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
                        List.of("確認写真なし", "撮影準備はスマホ", ""),
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
                    List.of("写真を破棄しました", "撮影準備はスマホ", "読取完了はスマホ"),
                    "Discarded unregistered photo for page " + pending.pageIndex);
        });
    }

    private void publishCaptureReview(
            CaptureReviewStore.Pending pending,
            String diagnostic
    ) {
        publishCaptureReview(pending, diagnostic, false);
    }

    /**
     * Shows the unregistered photo.
     *
     * <p>Local glasses require a visible still before their three-second timer.
     * The frozen phone relay keeps explicit confirmation.</p>
     */
    private void publishCaptureReview(
            CaptureReviewStore.Pending pending,
            String diagnostic,
            boolean armAutoCommit
    ) {
        if (committedRecoveryBlocked || pending == committedPendingLocked) {
            publishCommittedPendingLocked(pending, diagnostic);
            return;
        }
        clearArmedCapture();
        // Any earlier countdown belongs to a view that is being replaced.
        reviewGeneration++;
        autoCommitScheduled = false;
        reviewDeadlineMillis = 0;
        autoCommitArmed = link.supportsLocalCaptureReview() && armAutoCommit;
        reviewViewGeneration = CaptureSurface.NO_VIEW_GENERATION;
        // The operator cannot see the camera's field of view, so the framing
        // verdict leads: a page that ran outside the frame must read as a
        // failure, not as a photo that is merely waiting to be registered.
        String page = "P" + (pending.pageIndex + 1);
        String ocrLine = "OCR " + pending.ocrCharacters() + "文字";
        List<String> lines = pending.isFramingFailing()
                ? List.of(
                        reviewHeadline(pending.pageIndex + 1, pending.framing),
                        "撮り直しはスマホ",
                        ocrLine)
                : List.of(
                        reviewHeadline(pending.pageIndex + 1, pending.framing),
                        ocrLine + "・確認はスマホ",
                        "登録はスマホのボタン");
        if (link.supportsLocalCaptureReview()) {
            lines = armAutoCommit
                    ? List.of(page + " 撮影確認", "3秒以内のタップで撮り直し",
                            pending.isFramingFailing() ? "範囲を確認してください" : "無操作で確定")
                    : List.of(page + " 写真を保全しています", "ダブルタップで再送", "タップで撮り直し");
        }
        state = RelayState.CAPTURE_REVIEW;
        currentHudLines = lines;
        long viewGeneration = link.showCaptureReview(
                pending.jpeg,
                pending.rotationDegrees,
                lines);
        reviewViewGeneration = viewGeneration;
        listener.onUpdate(RelayState.CAPTURE_REVIEW, lines, diagnostic);
    }

    // ---- hands-free automatic reading -------------------------------------

    public void startAutoCapture() {
        serial.execute(this::startAutoCaptureNow);
    }

    public void stopAutoCapture() {
        serial.execute(() -> stopAutoCaptureNow("Automatic reading stopped by the operator"));
    }

    public boolean isAutoCaptureEnabled() {
        return autoCaptureEnabled;
    }

    private void startAutoCaptureNow() {
        if (!link.supportsLocalCaptureReview()) {
            publish(state, currentHudLines, "Automatic capture is disabled; use explicit phone controls");
            return;
        }
        if (autoCaptureEnabled || captureLease.isUnresolved()
                || (state != RelayState.READY && state != RelayState.READING)) return;
        finishCaptureRequested = false;
        manualCaptureRequested = false;
        autoCaptureEnabled = true;
        autoRunGeneration++;
        listener.onAutoCaptureChanged(true);
        beginAutoBurst();
    }

    private void stopAutoCaptureNow(String reason) {
        if (!autoCaptureEnabled && autoShotsRemaining == 0) {
            return;
        }
        autoCaptureEnabled = false;
        autoRunGeneration++;
        autoShotsRemaining = 0;
        autoShotsTaken = 0;
        autoBest = null;
        autoBestScore = 0;
        listener.onAutoCaptureChanged(false);
        publish(
                documentId > 0 ? RelayState.READING : RelayState.READY,
                List.of("自動読取を停止", "読取完了はスマホ", ""),
                reason);
    }

    private void beginAutoBurst() {
        if (!autoCaptureEnabled || finishCaptureRequested || captureLease.isUnresolved()) {
            return;
        }
        autoShotsRemaining = AUTO_BURST_SHOTS;
        autoShotsTaken = 0;
        autoBest = null;
        autoBestScore = 0;
        // The first shot, like a manual shot, waits for a visible guide acknowledgement.
        armCaptureAt(nextPageIndex, false);
    }

    private void takeAutoShotNow() {
        if (!autoCaptureEnabled || autoShotsRemaining <= 0) {
            return;
        }
        if (!linkReady || !requireApi()) {
            stopAutoCaptureNow("Automatic reading stopped because the glasses link is not ready");
            return;
        }
        if (captureLease.isUnresolved()) {
            stopAutoCaptureNow(
                    "Automatic reading stopped because a CXR-L photo lease is unresolved");
            return;
        }
        int pageIndex = nextPageIndex;
        int shot = autoShotsTaken + 1;
        // requestPhotoAt only fires from STABILIZING, and it publishes its own
        // "撮影中" view. Pushing another one here would double the view swaps
        // per shot, and each swap costs the glasses several hundred ms.
        state = RelayState.STABILIZING;
        listener.onUpdate(
                state,
                currentHudLines,
                "Automatic burst shot " + shot + "/" + AUTO_BURST_SHOTS
                        + " for page index " + pageIndex);
        requestPhotoAt(pageIndex, false);
    }

    private void scheduleAuto(Runnable action, long delayMillis) {
        long generation = autoRunGeneration;
        try {
            watchdog.schedule(
                    () -> {
                        try {
                            serial.execute(() -> {
                                if (autoCaptureEnabled && !finishCaptureRequested
                                        && generation == autoRunGeneration) action.run();
                            });
                        } catch (RejectedExecutionException ignored) {
                            // The activity closed while the cycle was waiting.
                        }
                    },
                    delayMillis,
                    TimeUnit.MILLISECONDS);
        } catch (RejectedExecutionException ignored) {
            // The activity is already closing.
        }
    }

    /**
     * Keeps the best frame of the burst and presents it for review.
     * The photo is only persisted when it wins, so a burst
     * costs one durable write rather than {@link #AUTO_BURST_SHOTS}.
     */
    private void acceptAutoShot(CaptureReviewStore.Pending shot, OcrQuality quality) {
        if (manualCaptureRequested || finishCaptureRequested) {
            autoShotsRemaining = 0;
            autoBest = null;
            stageCaptureReview(shot, quality);
            return;
        }
        autoShotsTaken++;
        autoShotsRemaining--;
        double score = ShotScore.of(
                shot.framing,
                shot.ocrCharacters(),
                quality == null ? 0f : quality.meanConfidence(),
                quality != null && quality.hasConfidence());
        listener.onUpdate(
                RelayState.OCR,
                currentHudLines,
                "Automatic burst shot " + autoShotsTaken + "/" + AUTO_BURST_SHOTS
                        + " " + ShotScore.describe(score)
                        + " framing=" + shot.framing
                        + " OCR characters: " + shot.ocrCharacters()
                        + (quality == null ? "" : " (" + quality.describe() + ")"));
        if (autoBest == null || ShotScore.isBetter(score, autoBestScore)) {
            autoBest = shot;
            autoBestScore = score;
        }
        if (!autoCaptureEnabled) {
            autoShotsRemaining = 0;
            return;
        }
        if (autoShotsRemaining > 0) {
            scheduleAuto(this::takeAutoShotNow, AUTO_SHOT_INTERVAL_MILLIS);
            return;
        }
        finishAutoBurst();
    }

    private void finishAutoBurst() {
        CaptureReviewStore.Pending best = autoBest;
        autoBest = null;
        autoBestScore = 0;
        if (best == null || best.ocrCharacters() == 0 || best.hasOcrFailure()
                || best.isFramingFailing()) {
            // Nothing was read, so there is nothing to register and nothing to
            // wait for: go straight back and shoot again. Only after several
            // consecutive failures does the interval open up, because a camera
            // firing continuously keeps the privacy LED lit and heats the
            // glasses.
            unreadableBurstsSeen++;
            boolean backOff = unreadableBurstsSeen > AUTO_UNREADABLE_RETRY_LIMIT;
            publishAutoWaiting(
                    "読み取れません",
                    backOff ? "位置を調整してください" : "すぐに撮り直します",
                    "Automatic burst produced no readable frame ("
                            + unreadableBurstsSeen + " in a row); retrying "
                            + (backOff ? "after backing off" : "immediately"));
            scheduleAuto(
                    this::beginAutoBurst,
                    backOff
                            ? AUTO_UNREADABLE_BACKOFF_MILLIS
                            : AUTO_RETRY_IMMEDIATE_MILLIS);
            return;
        }
        unreadableBurstsSeen = 0;
        if (PageTextSimilarity.isSamePage(lastRegisteredPageText, best.ocrText)) {
            duplicateBurstsSeen++;
            if (duplicateBurstsSeen >= AUTO_DUPLICATE_BURST_LIMIT) {
                stopAutoCaptureNow(
                        "Automatic reading stopped after " + duplicateBurstsSeen
                                + " bursts that read as the page already registered");
                return;
            }
            publishAutoWaiting(
                    "同じページです",
                    "次のページへ",
                    "Automatic burst skipped as a duplicate of the registered page");
            scheduleAuto(this::beginAutoBurst, AUTO_PAGE_TURN_MILLIS);
            return;
        }
        duplicateBurstsSeen = 0;
        try {
            CaptureReviewTransaction.replace(
                    captureReview,
                    best,
                    captureReviewPersistence::save);
        } catch (IOException error) {
            stopAutoCaptureNow(
                    "Automatic reading stopped because the chosen photo could not be saved: "
                            + error.getMessage());
            return;
        }
        listener.onCaptureReview(best);
        publishCaptureReview(best, "Review selected automatic frame", true);
    }

    private void publishAutoWaiting(String first, String second, String diagnostic) {
        publish(
                documentId > 0 ? RelayState.READING : RelayState.READY,
                List.of(first, second, link.supportsLocalCaptureReview()
                        ? "タップ撮影・ダブルタップ終了" : "停止はスマホ"),
                diagnostic);
    }

    /**
     * First HUD line of the review.
     *
     * <p>Only a page the check actually vouched for may be called 合格. An
     * unjudgeable frame said "合格 判定情報なし" on hardware, which claims a
     * pass and denies one in the same breath.</p>
     */
    static String reviewHeadline(int pageNumber, PageFraming framing) {
        String verdict;
        switch (framing.verdict()) {
            case COMPLETE:
                verdict = "合格 ";
                break;
            case CLIPPED:
                verdict = "不合格 ";
                break;
            default:
                // describe() already states that it could not be judged.
                verdict = "";
                break;
        }
        return "P" + pageNumber + " " + verdict + framing.describe();
    }

    static long autoCommitDelayMillis(CaptureReviewStore.Pending pending) {
        return pending.framing.verdict() == PageFraming.Verdict.COMPLETE
                ? AUTO_COMMIT_COMPLETE_MILLIS
                : AUTO_COMMIT_UNVERIFIED_MILLIS;
    }

    /**
     * Whether a countdown that has just expired may still register its photo.
     *
     * <p>A tap leaves {@code CAPTURE_REVIEW}, and any newer review view bumps
     * the generation, so both are enough to retire a timer that is already in
     * flight. Kept static so the arithmetic is covered without a Context.</p>
     */
    static boolean shouldAutoCommit(
            RelayState state,
            long generationAtSchedule,
            long currentGeneration,
            boolean armed
    ) {
        return state == RelayState.CAPTURE_REVIEW && armed
                && generationAtSchedule == currentGeneration;
    }

    /**
     * Starts the registration countdown once the glasses confirm the review
     * view is on screen. Without that acknowledgement nothing is uploaded.
     */
    private void scheduleAutoCommitOnAck(long generation, String purpose) {
        if (!link.supportsLocalCaptureReview() || !"capture-review".equals(purpose)
                || !link.isCaptureReviewVisible(generation) || !autoCommitArmed
                || autoCommitScheduled
                || generation != reviewViewGeneration) {
            return;
        }
        CaptureReviewStore.Pending pending = captureReview.peek();
        if (pending == null) {
            autoCommitArmed = false;
            return;
        }
        autoCommitScheduled = true;
        long delayMillis = LOCAL_REVIEW_MILLIS;
        reviewDeadlineMillis = android.os.SystemClock.elapsedRealtime() + delayMillis;
        final long generationAtSchedule = reviewGeneration;
        watchdog.schedule(
                () -> enqueueAutoCommit(generationAtSchedule),
                delayMillis,
                TimeUnit.MILLISECONDS);
        listener.onUpdate(
                state,
                currentHudLines,
                "Auto-registration countdown started after review view"
                        + " acknowledgement generation=" + generation
                        + " purpose=" + purpose
                        + " delay=" + delayMillis + "ms"
                        + " framing=" + pending.framing);
    }

    private void enqueueAutoCommit(long generationAtSchedule) {
        try {
            serial.execute(() -> {
                if (!link.isCaptureReviewVisible(reviewViewGeneration) || !shouldAutoCommit(
                        state,
                        generationAtSchedule,
                        reviewGeneration,
                        autoCommitArmed)) {
                    return;
                }
                if (link.supportsLocalCaptureReview() && (reviewDeadlineMillis == 0
                        || android.os.SystemClock.elapsedRealtime() < reviewDeadlineMillis)) return;
                autoCommitArmed = false;
                confirmPendingCaptureNow();
            });
        } catch (RejectedExecutionException ignored) {
            // The activity closed while the countdown was running.
        }
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
        if (link.supportsLocalCaptureReview()) {
            autoCaptureEnabled = false;
            autoRunGeneration++;
        }
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
        if ((documentId == 0 && localSession == null) || nextPageIndex == 0) {
            publish(
                    RelayState.READING,
                    List.of("ページがありません", "撮影準備はスマホ", ""),
                    "Finish rejected: empty document");
            return;
        }
        if (listeningMode && !listeningComplete) {
            if (localSession != null) {
                try { localSession.setPhase(LocalCaptureSession.Phase.LISTENING); }
                catch (IOException error) { fail("録音状態を保存できません", null); return; }
            }
            publish(RelayState.LISTENING, List.of("撮影完了・録音継続", "音声終了後ダブルタップ", "カメラ停止"),
                    "Waiting for complete listening recording");
            return;
        }
        if (localSession != null) {
            try {
                localSession.setPhase(LocalCaptureSession.Phase.ANALYSIS);
                publish(RelayState.FINALIZING, List.of("解析中", "資料は保存済み", "カメラ停止"), "Local capture finished; analysis queued");
                queueLocalUpload();
            } catch (IOException error) { fail("解析開始を保存できません", null); }
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
                sessionId = api.createExamSession(documentId, listeningMode).getLong("session_id");
                persistWorkflow();
            }
            if (listeningMode) api.attachDocumentAudio(sessionId);
            JSONObject finished = link.supportsLocalCaptureReview()
                    ? api.finalizeReadingLocal(sessionId) : api.finalizeReading(sessionId);
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
        if (localSession != null) {
            publish(RelayState.REVIEW, List.of("答案を取得", "", ""), diagnostic);
            return;
        }
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
                List.of("新規読取", "撮影準備はスマホ", "完了はスマホ"),
                "Workflow cleared");
        if (linkReady && link.supportsLocalCaptureReview()) {
            try { startLocalCapture(); }
            catch (Exception error) { fail("新規読取を開始できません", error); }
        }
    }

    private boolean requireApi() {
        if (api != null) {
            return true;
        }
        fail("先にサーバURLを設定してください", null);
        return false;
    }

    /**
     * Reports why a command cannot run instead of returning in silence.
     *
     * <p>The old {@code !linkReady || !requireApi()} short-circuited before
     * {@code requireApi} could speak, so with the glasses disconnected every
     * phone button did nothing and said nothing. That is what "the manual
     * buttons do not work" turned out to be.</p>
     */
    private boolean requireLink() {
        if (!linkReady) {
            publish(
                    RelayState.DISCONNECTED,
                    List.of("グラス未接続", "Hi Rokid認可・再接続", ""),
                    "Command ignored because the glasses link is not ready");
            return false;
        }
        return requireApi();
    }

    private long captureElapsedMillis() {
        long requestedAt = photoRequestedAtMillis;
        return requestedAt == 0 ? 0 : System.currentTimeMillis() - requestedAt;
    }

    private void publish(RelayState next, List<String> lines, String diagnostic) {
        if (closed) return;
        state = next;
        List<String> safeLines = lines == null || lines.isEmpty()
                ? List.of(next.name(), "", "")
                : lines;
        currentHudLines = safeLines;
        link.showHud(safeLines);
        listener.onUpdate(next, safeLines, diagnostic);
    }

    private void fail(String userMessage, Throwable error) {
        fail(userMessage, error, RelayState.ERROR);
    }

    private void fail(String userMessage, Throwable error, RelayState next) {
        String detail = error == null ? userMessage : userMessage + ": " + error.getMessage();
        // A hands-free cycle must not keep shooting into a fault; the operator
        // is not watching the phone and would never see it.
        if (autoCaptureEnabled) {
            autoCaptureEnabled = false;
            autoShotsRemaining = 0;
            autoShotsTaken = 0;
            autoBest = null;
            autoBestScore = 0;
            listener.onAutoCaptureChanged(false);
        }
        publish(
                next,
                List.of("エラー", userMessage,
                        next == RelayState.READY || next == RelayState.READING
                                ? "撮影準備はスマホ" : "スマホ画面を確認"),
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
        manualCaptureRequested = false;
        finishCaptureRequested = false;
        listeningComplete = false;
        listeningFailed = false;
        autoCaptureEnabled = false;
        autoRunGeneration++;
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
        closed = true;
        if (link.supportsLocalCaptureReview() && api != null) api.cancelRequests();
        clearArmedCapture();
        captureLease.resetAfterBindingReset();
        watchdog.shutdownNow();
        serial.shutdownNow();
        localNetwork.shutdownNow();
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
