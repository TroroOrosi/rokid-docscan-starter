package dev.rokid.docscanrelay;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONObject;

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

/** Serial state machine for capture -> OCR -> upload -> solve -> HUD review. */
public final class DocScanController implements AutoCloseable {
    public interface Listener {
        void onUpdate(RelayState state, List<String> hudLines, String diagnostic);
    }

    private static final String PREFS = "docscan_relay";
    private static final String KEY_SERVER = "server";
    private static final String KEY_DOCUMENT = "document_id";
    private static final String KEY_NEXT_PAGE = "next_page";
    private static final String KEY_SESSION = "session_id";
    private static final long CAPTURE_TIMEOUT_SECONDS = 30;

    private final RokidGlobalLink link;
    private final JapaneseOcr ocr;
    private final Listener listener;
    private final SharedPreferences preferences;
    private final ExecutorService serial = Executors.newSingleThreadExecutor();
    private final ScheduledExecutorService watchdog =
            Executors.newSingleThreadScheduledExecutor();
    private final CaptureLease captureLease = new CaptureLease();
    private final RetryCursor retryCursor = new RetryCursor();

    private volatile RelayState state = RelayState.DISCONNECTED;
    private DocScanApi api;
    private String configuredServer = "";
    private int imageRotation;
    private boolean linkReady;
    private long documentId;
    private int nextPageIndex;
    private long sessionId;
    private int reviewIndex;
    private int reviewViewPage;
    private int reviewProblemCount;
    private int reviewViewPageCount;

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
        documentId = preferences.getLong(KEY_DOCUMENT, 0);
        nextPageIndex = preferences.getInt(KEY_NEXT_PAGE, 0);
        sessionId = preferences.getLong(KEY_SESSION, 0);
    }

    public RelayState getState() {
        return state;
    }

    public boolean isCaptureReconnectRequired() {
        return captureLease.isTimedOut();
    }

    public void configure(String serverUrl, String apiKey, int rotationDegrees) {
        if (captureLease.isUnresolved()
                || state.isCaptureInProgress()
                || state == RelayState.FINALIZING) {
            throw new IllegalStateException(
                    "撮影処理中のため設定を変更できません。完了を待つかHi Rokidを再接続してください");
        }
        DocScanApi candidate = new DocScanApi(serverUrl, apiKey);
        String previousServer = preferences.getString(KEY_SERVER, "");
        configuredServer = serverUrl.trim().replaceAll("/+$", "");
        imageRotation = JapaneseOcr.normalizeRotation(rotationDegrees);
        api = candidate;
        if (!previousServer.isEmpty() && !previousServer.equals(configuredServer)) {
            clearWorkflow();
        }
        preferences.edit().putString(KEY_SERVER, configuredServer).apply();
    }

    public void verifyServer() {
        serial.execute(() -> {
            if (!requireApi()) {
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

    public void setLinkReady(boolean ready) {
        try {
            serial.execute(() -> {
                linkReady = ready;
                if (!ready) {
                    captureLease.resetAfterDisconnect();
                    publish(
                            RelayState.DISCONNECTED,
                            List.of("Hi Rokid未接続", "ペアリングを確認", ""),
                            "Rokid link disconnected; capture lease reset");
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
                publish(
                        RelayState.READY,
                        List.of("接続完了", "短押し: 撮影", "長押し: 読取完了"),
                        "Rokid AIDL connected");
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
                                    "短押し: 次を撮影"),
                            "Recovered document " + documentId);
                    return;
                }
                publish(
                        RelayState.READY,
                        List.of("準備完了", "短押し: 1ページ目", "長押し: 読取完了"),
                        "Ready for a new document");
            } catch (Exception error) {
                fail("前回状態を復元できません", error);
            }
        });
    }

    public void captureNextPage() {
        serial.execute(() -> captureAt(retryCursor.nextOr(nextPageIndex)));
    }

    public void recapturePreviousPage() {
        serial.execute(() -> {
            int pageIndex = retryCursor.previousOr(nextPageIndex);
            if (pageIndex < 0) {
                publish(
                        RelayState.READING,
                        List.of("再撮影対象なし", "短押し: 1ページ目", ""),
                        "No previous page");
                return;
            }
            captureAt(pageIndex);
        });
    }

    private void captureAt(int pageIndex) {
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
        if (state == RelayState.CAPTURING
                || state == RelayState.OCR
                || state == RelayState.UPLOADING
                || state == RelayState.FINALIZING) {
            publish(state, List.of("処理中", "完了まで待機", ""), "Ignored overlapping capture");
            return;
        }
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
                    List.of("撮影中", "P" + (pageIndex + 1), "動かさないでください"),
                    "Requesting glasses photo for page index " + pageIndex);
            RokidGlobalLink.PhotoStartResult startResult =
                    link.takePhoto(1440, 1920, 85);
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
            fail(
                    photoRequestMayBeActive
                            ? "撮影開始結果を確認できません。Hi Rokidを再接続してください"
                            : "撮影開始に失敗しました",
                    error);
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
            publish(
                    RelayState.READING,
                    List.of("遅延写真を破棄", "撮影終了を確認", "再撮影できます"),
                    "Late photo callback discarded after timeout; capture lease released");
            return;
        }
        if (jpeg == null || jpeg.length == 0) {
            fail("グラスから空の写真が返されました", null);
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
                        () -> uploadCapturedPage(uploadIndex, jpeg, text, uploadRotation));
            }

            @Override
            public void onError(Throwable error) {
                // Keep the real photo as the authoritative input. The server's
                // configured vision analyzer may still recover OCR.
                serial.execute(
                        () -> uploadCapturedPage(uploadIndex, jpeg, "", uploadRotation));
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
                fail(userMessage, detail);
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

    private void uploadCapturedPage(
            int uploadIndex,
            byte[] jpeg,
            String ocrText,
            int uploadRotation
    ) {
        try {
            publish(
                    RelayState.UPLOADING,
                    List.of("送信中", "P" + (uploadIndex + 1), ""),
                    "OCR characters: " + ocrText.length());
            JSONObject response = api.uploadPage(
                    documentId, uploadIndex, jpeg, ocrText, uploadRotation);
            boolean replaced = response.optBoolean("replaced", false);
            if (!replaced) {
                nextPageIndex = Math.max(nextPageIndex, uploadIndex + 1);
            } else if (uploadIndex >= nextPageIndex) {
                nextPageIndex = uploadIndex + 1;
            }
            retryCursor.onUploaded(uploadIndex);
            persistWorkflow();
            List<String> lines = RelayMessages.forAiKeyScanAck(
                    extractLines(response.optJSONObject("scan_ack")));
            if (ocrText.trim().isEmpty()) {
                lines = List.of(
                        "写真は保存済み",
                        "端末OCRは空でした",
                        "再撮影かVision解析");
            }
            publish(
                    RelayState.READING,
                    lines,
                    "Uploaded page " + uploadIndex + (replaced ? " (replaced)" : ""));
        } catch (Exception error) {
            fail("写真の送信に失敗しました。再操作で再撮影します", error);
        }
    }

    public void finishReading() {
        serial.execute(() -> {
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
            if (state.isCaptureInProgress()) {
                publish(
                        state,
                        List.of("処理中", "写真の登録完了まで待機", ""),
                        "Finish ignored while capture pipeline is active");
                return;
            }
            if (documentId == 0 || nextPageIndex == 0) {
                publish(
                        RelayState.READING,
                        List.of("ページがありません", "短押しで撮影", ""),
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
        });
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
        serial.execute(() -> {
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
        });
    }

    public void previousReviewItem() {
        serial.execute(() -> {
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
        });
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
        serial.execute(() -> {
            if (captureLease.isUnresolved()) {
                publish(
                        RelayState.ERROR,
                        List.of("新規読取を保留", "撮影終了が未確認", "Hi Rokidを再接続"),
                        "Workflow reset rejected while a photo lease is unresolved");
                return;
            }
            if (state.isCaptureInProgress() || state == RelayState.FINALIZING) {
                publish(
                        state,
                        List.of("処理中", "完了まで待機", ""),
                        "Workflow reset rejected while processing is active");
                return;
            }
            clearWorkflow();
            publish(
                    linkReady ? RelayState.READY : RelayState.DISCONNECTED,
                    List.of("新規読取", "短押し: 撮影", "長押し: 完了"),
                    "Workflow cleared");
        });
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

    private void clearWorkflow() {
        documentId = 0;
        nextPageIndex = 0;
        sessionId = 0;
        reviewIndex = 0;
        reviewViewPage = 0;
        reviewProblemCount = 0;
        reviewViewPageCount = 0;
        retryCursor.clear();
        preferences.edit()
                .remove(KEY_DOCUMENT)
                .remove(KEY_NEXT_PAGE)
                .remove(KEY_SESSION)
                .apply();
    }

    @Override
    public void close() {
        captureLease.resetAfterDisconnect();
        watchdog.shutdownNow();
        serial.shutdownNow();
    }
}
