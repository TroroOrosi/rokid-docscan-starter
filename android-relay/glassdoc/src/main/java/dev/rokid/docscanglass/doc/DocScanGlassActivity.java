package dev.rokid.docscanglass.doc;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.util.Log;
import android.view.KeyEvent;
import android.view.WindowManager;
import android.widget.Toast;

import java.io.IOException;
import java.io.File;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

import dev.rokid.docscanglass.input.BackExitPolicy;
import dev.rokid.docscanglass.input.GlassKeyEvents;
import dev.rokid.docscanglass.input.GlassesInputAction;
import dev.rokid.docscanglass.input.GlassesInputNormalizer;
import dev.rokid.docscanglass.input.InputSignal;
import dev.rokid.docscanrelay.ClientIdentity;
import dev.rokid.docscanrelay.DocScanController;
import dev.rokid.docscanrelay.JapaneseOcr;
import dev.rokid.docscanrelay.RelayState;
import dev.rokid.docscanrelay.study.AnswerBundle;
import dev.rokid.docscanrelay.study.AnswerReader;
import dev.rokid.docscanrelay.study.AnswerStore;

/**
 * The glasses-side operator surface.
 *
 * <p>It owns three things and nothing else: the display, the camera, and the
 * gestures. Everything between a JPEG and an answer -- recognition, framing,
 * upload, review, the page state machine and its crash-safe persistence -- is
 * {@code DocScanController} from `:relaycore`, the same code the phone relay
 * runs and the same code its tests cover.</p>
 *
 * <p>An earlier version of this file reimplemented all of that from nothing.
 * It was killed by lowmemorykiller, uploaded pages upside down, created two
 * documents from two taps, and carried a framing check that measured worse
 * than the one the relay already had.</p>
 */
public final class DocScanGlassActivity extends Activity
        implements DocScanController.Listener, GlassesCaptureSurface.Listener {
    private static final String TAG = "DocScanGlassDoc";
    private static final String EXTRA_SERVER = "server";
    private static final String EXTRA_KEY = "key";
    private static final String EXTRA_GUIDE = "guide";
    private static final String EXTRA_SPREAD = "spread";
    private static final int CAMERA_PERMISSION_REQUEST = 7401;
    private static final int AUDIO_PERMISSION_REQUEST = 7402;
    private boolean listeningMode;
    private ListeningRecorder listening;
    private boolean finishingAudio;
    private long listeningDocument;

    /**
     * The sensor reports {@code SENSOR_ORIENTATION=270} and writes
     * {@code JPEG_ORIENTATION=0}, so a still arrives upside down. Measured on
     * 2026-09-04: rotating a stored page by 180 made the exam paper legible
     * where the recognizer had been reading it as noise.
     */
    private static final int MEASURED_ROTATION_DEGREES = 180;

    /** Long enough to read why the display stayed on before the session ends. */
    private static final long EXIT_NOTICE_MILLIS = 2_000;

    private final GlassesInputNormalizer normalizer = new GlassesInputNormalizer();
    private final BackExitPolicy backExit = new BackExitPolicy();
    private final DisplaySleep displaySleep = new DisplaySleep();
    private WearWatch wearWatch;
    private PowerManager.WakeLock analysisWakeLock;
    private boolean awaitingAnswers;
    private boolean sessionClosed;
    private final Handler main = new Handler(Looper.getMainLooper());

    private HandlerThread cameraThread;
    private GlassCamera camera;
    private GlassesCaptureSurface surface;
    private JapaneseOcr ocr;
    private DocScanController controller;
    private HudView hud;
    private AnswerView answers;
    private AnswerStore answerStore;
    private ConnectionSettings connectionSettings;
    // Off the main thread only for AnswerStore.save's per-gesture write --
    // load-then-rewrite-the-whole-bundle plus an fsync, too expensive for a
    // wearable's UI thread on every page turn. Single-threaded so writes
    // still commit in the order the gestures that queued them happened in;
    // daemon so it never has to be shut down from onDestroy, which this
    // change does not touch.
    private final ExecutorService answerPersistExecutor = Executors.newSingleThreadExecutor(
            runnable -> {
                Thread thread = new Thread(runnable, "answer-persist");
                thread.setDaemon(true);
                return thread;
            });
    // Screen ownership only. Always read/written on the main thread (onAction,
    // openAnswers/closeAnswers, and the main.post callback fetchAnswers posts
    // from its background thread) -- onUpdate's guard no longer reads it.
    private AnswerReader reader;
    // The session id fetchAnswers last ran for, or -1 for none yet. Keyed by
    // session, not a plain flag: SHORT_TAP in REVIEW starts a new document,
    // DocScanController#clearWorkflow resets sessionId to 0 and a later
    // capture assigns a new one, and that second session must fetch its own
    // answers too -- a plain "already fetched" boolean would leave it with
    // no reader and no error. volatile: read and written from the
    // controller's serial-executor thread, matching the convention
    // DocScanController itself uses for its own cross-thread fields. Also
    // reset back to -1 on a failed fetch (see fetchAnswers), so the next
    // REVIEW publish -- nextReviewItem/previousReviewItem republish it on
    // every page turn -- retries instead of forfeiting the session's
    // answers to one bad request.
    private volatile long answersFetchedForSession = -1;
    // True once this Activity instance has checked AnswerStore for a saved
    // reader without waiting on RelayState.REVIEW, which needs the network
    // to ever be published (see fetchAnswers's own comment). Read and
    // written only from onUpdate's calling thread -- the controller's
    // serial executor in production, whatever thread drives it directly in
    // tests -- the same single-caller convention answersFetchedForSession
    // already relies on.
    private boolean resolvedOfflineAnswersAtStartup;
    // True while the reader owned the screen when the most recent
    // KEYCODE_BACK DOWN was processed. Read again by the matching UP: onAction
    // (called from the DOWN phase, below) may itself close the reader --
    // setting `reader` to null -- as a side effect of that same press, so the
    // UP phase cannot recompute this from the live `reader` field. Always
    // read/written on the main thread (onKeyDown/onKeyUp).
    private boolean backOwnedByReader;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // A previous exit may have shortened the screen-off timeout to leave
        // the display asleep; give the operator their own value back first.
        displaySleep.restore(this);
        // Measured 2026-09-10: the stock timeout on these glasses is
        // 864000000 ms, ten days, so the screen never sleeps on its own. The
        // flag still matters, because DisplaySleep releases it to exit.
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        hud = new HudView(this);
        setContentView(hud);
        answerStore = new AnswerStore(getFilesDir());
        connectionSettings = new ConnectionSettings(new File(getNoBackupFilesDir(), "connection.bin"));
        // Putting the glasses back on wakes the display and the session with
        // it. Nothing restarts while they stay on the operator's face.
        wearWatch = new WearWatch(this, this::wornAgain);
        wearWatch.start();
        hud.calibrateGuide(getPreferences(MODE_PRIVATE).getFloat(
                EXTRA_GUIDE, (float) FramingGuide.UNCALIBRATED_FRACTION));
        hud.showSpreadGuide(getPreferences(MODE_PRIVATE).getBoolean(EXTRA_SPREAD, false));

        cameraThread = new HandlerThread("glass-camera");
        cameraThread.start();
        camera = new GlassCamera(this, new Handler(cameraThread.getLooper()), cameraCallback());
        surface = new GlassesCaptureSurface(this, camera, hud, main, this);
        ocr = new JapaneseOcr();
        controller = new DocScanController(
                this,
                surface,
                ocr,
                this,
                new ClientIdentity(
                        "rokid-glasses-camera2",
                        "glassdoc/" + BuildConfig.VERSION_NAME,
                        "camera2/no-cxr"));

        applyIntent(getIntent(), true);
        if (!hasCamera()) {
            requestPermissions(
                    new String[] {Manifest.permission.CAMERA}, CAMERA_PERMISSION_REQUEST);
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        applyIntent(intent, false);
    }

    private void applyIntent(Intent intent, boolean starting) {
        if (intent != null && intent.hasExtra(EXTRA_SPREAD)) {
            boolean spread = intent.getBooleanExtra(EXTRA_SPREAD, false);
            hud.showSpreadGuide(spread);
            getPreferences(MODE_PRIVATE).edit().putBoolean(EXTRA_SPREAD, spread).apply();
        }
        if (starting) {
            listeningMode = intent != null && intent.hasExtra("listening")
                    ? intent.getBooleanExtra("listening", false) : getPreferences(MODE_PRIVATE).getBoolean("listening", false);
            getPreferences(MODE_PRIVATE).edit().putBoolean("listening", listeningMode).apply();
            controller.setListeningMode(listeningMode);
        }
        if (intent != null && intent.hasExtra(EXTRA_GUIDE)) {
            float fraction = intent.getFloatExtra(
                    EXTRA_GUIDE, (float) FramingGuide.UNCALIBRATED_FRACTION);
            if (Float.isFinite(fraction)) {
                fraction = Math.max((float) FramingGuide.MIN_VISIBLE_FRACTION,
                        Math.min((float) FramingGuide.MAX_VISIBLE_FRACTION, fraction));
                hud.calibrateGuide(fraction);
                getPreferences(MODE_PRIVATE).edit().putFloat(EXTRA_GUIDE, fraction).apply();
            }
        }
        // A guide-only Intent must not reset an active capture or review.
        if (starting || (intent != null
                && (intent.hasExtra(EXTRA_SERVER) || intent.hasExtra(EXTRA_KEY)))) {
            String server = intent == null ? null : intent.getStringExtra(EXTRA_SERVER);
            String key = intent == null ? null : intent.getStringExtra(EXTRA_KEY);
            // Remove the delivered credential from this Activity's retained Intent.
            if (intent != null) intent.removeExtra(EXTRA_KEY);
            try {
                ConnectionSettings.Saved saved = server != null && key != null ? null : connectionSettings.load();
                if (saved != null) {
                    if (server == null) server = saved.server;
                    if (key == null) key = ConnectionSettings.normalizeServer(server).equals(saved.server) ? saved.key : "";
                }
                controller.configureAndResume(server, key, MEASURED_ROTATION_DEGREES);
            } catch (IOException | IllegalArgumentException error) {
                hud.showLines(List.of("接続設定を読み出せません", "初回設定を確認してください", ""));
            }
        }
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        // KEYCODE_BACK is absent on purpose: it has to reach the framework so
        // onBackPressed runs, which is where the two-stage exit is decided.
        if (normalize("DOWN", keyCode, event)) {
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    public boolean onKeyUp(int keyCode, KeyEvent event) {
        if (normalize("UP", keyCode, event)) {
            return true;
        }
        return super.onKeyUp(keyCode, event);
    }

    /**
     * The one-finger double tap, measured as {@code KEYCODE_NOTIFICATION}
     * twice then {@code KEYCODE_BACK}. Left unconsumed it ended the session on
     * a single mis-tap.
     *
     * <p>Lint asks for the AndroidX OnBackPressedDispatcher. Its claim that
     * onBackPressed is no longer called holds only where
     * android.window.OnBackInvokedDispatcher exists, which is API 33; the
     * measured build reports API 32. Revisit when the glasses report 33.</p>
     */
    @Override
    @SuppressLint("GestureBackNavigation")
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (backExit.onBack(SystemClock.elapsedRealtime()) == BackExitPolicy.Decision.EXIT) {
            exitSession();
            return;
        }
        hud.showLines(List.of("もう一度で終了", "", ""));
    }

    private void exitSession() {
            sessionClosed = true;
            if (reader != null) closeAnswers();
            releaseAnalysisWakeLock();
            Log.i(TAG, "exit confirmed");
            if (displaySleep.sleep(this) == DisplaySleep.Result.NOT_PERMITTED) {
                // Never claim an exit that left the display lit.
                Log.w(TAG, "display stays on: WRITE_SETTINGS is not granted");
                hud.showLines(List.of("終了しました", "消灯できません", "設定の許可が必要"));
                main.postDelayed(this::finish, EXIT_NOTICE_MILLIS);
                return;
            }
            finish();
    }

    /**
     * The glasses came back on after an exit that put the display to sleep.
     * The process is still alive -- only the screen slept -- so the operator's
     * own timeout goes back and the session is held awake again.
     */
    private void wornAgain() {
        if (awaitingAnswers || sessionClosed) return;
        Log.i(TAG, "worn again");
        displaySleep.restore(this);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    }

    @Override
    public void onRequestPermissionsResult(
            int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == CAMERA_PERMISSION_REQUEST && !hasCamera()) {
            hud.showLines(List.of("カメラ権限がありません", "", ""));
        }
        if (requestCode == AUDIO_PERMISSION_REQUEST) {
            if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) startListening();
            else controller.onListeningError();
        }
    }

    @Override
    protected void onDestroy() {
        sessionClosed = true;
        releaseAnalysisWakeLock();
        if (listening != null) listening.close();
        stopService(new Intent(this, ListeningService.class));
        // Folding the temple arms force-stops this process through the
        // assistserver third_app scene, so destruction is an ordinary end to a
        // session rather than an exceptional one. The controller persists its
        // pending capture, which is what makes that survivable.
        normalizer.reset();
        backExit.reset();
        if (wearWatch != null) {
            wearWatch.stop();
        }
        controller.close();
        surface.close();
        camera.close();
        ocr.close();
        cameraThread.quitSafely();
        super.onDestroy();
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        // A half-delivered gesture must not survive the assistant taking the
        // foreground and handing it back.
        normalizer.reset();
        backExit.reset();
        backOwnedByReader = false;
    }

    // --- input ------------------------------------------------------------

    private boolean normalize(String phase, int keyCode, KeyEvent event) {
        String name = KeyEvent.keyCodeToString(keyCode);
        // Compared against the raw keyCode, not the derived name: it is the
        // more fundamental fact ("KEYCODE_BACK" is keyCodeToString's own name
        // for exactly this constant) and does not depend on
        // KeyEvent.keyCodeToString resolving a symbolic name at all.
        boolean isBackKey = keyCode == KeyEvent.KEYCODE_BACK;
        if (isBackKey && "DOWN".equals(phase)) {
            // Captured before onAction (below) runs, and before it has a
            // chance to close the reader as a side effect of this very press.
            backOwnedByReader = reader != null || (controller != null
                    && controller.getState() != RelayState.REVIEW);
        }
        // KeyEvent uses uptime; convert to the controller's elapsed clock,
        // preserving the event's age if the main thread delivered it late.
        long elapsedMillis = event.getEventTime()
                + SystemClock.elapsedRealtime() - SystemClock.uptimeMillis();
        if (event.getRepeatCount() == 0) {
            Optional<GlassesInputAction> action = normalizer.accept(InputSignal.key(
                    elapsedMillis, phase, name, GlassKeyEvents.isKnown(name)));
            action.ifPresent(value -> onAction(value, elapsedMillis));
        }
        if (isBackKey && backOwnedByReader) {
            // The reader owned the screen when this press began: BACK is its
            // gesture, not the two-stage exit's. Consuming it here (for both
            // the DOWN and the matching UP) keeps it from also reaching
            // onBackPressed and arming the exit confirmation.
            return true;
        }
        // Consume every gesture key the firmware delivers except BACK, so the
        // system does not act on it behind the session.
        return !"KEYCODE_BACK".equals(name) && GlassKeyEvents.isKnown(name);
    }

    private void onAction(GlassesInputAction action, long elapsedMillis) {
        if (action != GlassesInputAction.BACK) {
            backExit.reset();
        }
        if (reader != null) {
            if (action == GlassesInputAction.BACK) {
                if (reader.screen() != AnswerReader.Screen.ANSWER) {
                    reader.back();
                    backExit.reset();
                    answers.refresh();
                } else if (backExit.onBack(elapsedMillis) == BackExitPolicy.Decision.EXIT) {
                    exitSession();
                } else {
                    answers.announceExit();
                }
                return;
            }
            if (!AnswerGestures.apply(reader, action)) {
                closeAnswers();
                return;
            }
            persistAnswerPosition(false);
            answers.refresh();
            return;
        }
        if (controller.getState() == RelayState.ERROR
                || (listeningMode && listening == null && controller.getState() != RelayState.REVIEW)) {
            if (action == GlassesInputAction.BACK) {
                if (backExit.onBack(elapsedMillis) == BackExitPolicy.Decision.EXIT) exitSession();
                else hud.showLines(List.of("もう一度ダブルタップで終了", "保存した資料は保持します", ""));
            }
            return;
        }
        if (listeningMode && controller.getState() == RelayState.LISTENING) {
            if (action == GlassesInputAction.BACK) finishAudio();
            return;
        }
        if (awaitingAnswers && action == GlassesInputAction.BACK) {
            if (backExit.onBack(elapsedMillis) == BackExitPolicy.Decision.EXIT) exitSession();
            return;
        }
        controller.onGlassesAction(action);
    }

    // --- camera -----------------------------------------------------------

    private GlassCamera.Callback cameraCallback() {
        return new GlassCamera.Callback() {
            @Override
            public void onCaptured(byte[] jpeg, int width, int height, long elapsedMillis) {
                Log.i(TAG, "captured " + width + "x" + height + " in " + elapsedMillis + " ms");
                controller.onPhoto(jpeg);
            }

            @Override
            public void onCaptureFailed(String reason) {
                controller.onPhotoError("撮影に失敗しました: " + reason, null);
            }
        };
    }

    private boolean hasCamera() {
        return checkSelfPermission(Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_GRANTED;
    }

    // --- controller callbacks --------------------------------------------

    @Override
    public void persistConfiguration(String server, String key) throws IOException {
        connectionSettings.save(server, key);
    }

    @Override
    public void onConfigurationRejected(String message) {
        main.post(() -> Toast.makeText(this, message, Toast.LENGTH_LONG).show());
    }

    @Override
    public void onViewShown(long generation, String purpose) {
        controller.onCustomViewAvailable(generation, purpose);
    }

    @Override
    public void onReviewHidden(long generation) {
        controller.onCaptureReviewHidden(generation);
    }

    @Override
    public void onUpdate(RelayState state, List<String> hudLines, String diagnostic) {
        Log.i(TAG, state + ": " + diagnostic);
        maybeOpenSavedAnswersOffline();
        if (state == RelayState.FINALIZING || state == RelayState.LISTENING) main.post(this::waitWithDisplayOff);
        if (state == RelayState.ERROR || state == RelayState.READING) {
            main.post(() -> { if (awaitingAnswers) wakeForResult(); });
        }
        if (state == RelayState.REVIEW) {
            long sessionId = controller.sessionId();
            if (sessionId != answersFetchedForSession) {
                answersFetchedForSession = sessionId;
                fetchAnswers(sessionId);
            }
        }
        // AIMING, STABILIZING and CAPTURE_REVIEW each own the screen through
        // their own surface call -- the guide brackets, and the still. Redrawing
        // plain text here would wipe them.
        if (state == RelayState.AIMING
                || state == RelayState.STABILIZING
                || state == RelayState.CAPTURE_REVIEW) {
            return;
        }
        main.post(() -> hud.showLines(GlassesHudText.adapt(hudLines)));
    }

    @Override public void onListeningReady(long documentId) {
        main.post(() -> {
            if (sessionClosed || (listening != null && listeningDocument == documentId)) return;
            if (listening != null) listening.close();
            listening = null;
            finishingAudio = false;
            listeningDocument = documentId;
            if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, AUDIO_PERMISSION_REQUEST);
                return;
            }
            startListening();
        });
    }

    private void startListening() {
        try {
            listening = new ListeningRecorder(getFilesDir(), listeningDocument, controller.api(), () -> {
                controller.onListeningError();
                main.post(() -> { wakeForResult(); stopService(new Intent(this, ListeningService.class)); });
            });
            startForegroundService(new Intent(this, ListeningService.class));
            listening.start();
            controller.startAutoCapture();
        } catch (Exception error) {
            if (listening != null) listening.close();
            listening = null;
            stopService(new Intent(this, ListeningService.class));
            controller.onListeningError();
            hud.showLines(List.of("録音を開始できません", "権限・前回録音を確認", "原音は削除していません"));
        }
    }

    private void finishAudio() {
        if (finishingAudio || listening == null) return;
        finishingAudio = true;
        waitWithDisplayOff();
        new Thread(() -> {
            try {
                listening.finishAndUpload();
                main.post(() -> {
                    stopService(new Intent(this, ListeningService.class));
                    if (!sessionClosed) controller.completeListening();
                });
            } catch (Exception error) {
                main.post(() -> {
                    if (sessionClosed) return;
                    finishingAudio = false;
                    wakeForResult();
                    hud.showLines(List.of("録音・文字起こしを確認", "原音は保存済み", "ダブルタップで再試行"));
                });
            }
        }, "listening-finish").start();
    }

    // --- answer reading -----------------------------------------------------

    /**
     * The saved reader has to survive a restart with no route to the server
     * at all, so it cannot wait for {@code RelayState.REVIEW} -- reaching
     * REVIEW itself needs the network (see {@link #fetchAnswers}'s own
     * comment). Runs once, on the very first {@code onUpdate} this Activity
     * instance observes, for whatever state that happens to be: reads
     * {@code controller.sessionId()} -- already restored from
     * SharedPreferences in the controller's constructor, before any network
     * call -- and opens the saved reader when it matches and is not CLOSED.
     *
     * <p>Claims the session ({@code answersFetchedForSession}) whenever a
     * match is found, closed or not, so the REVIEW-gated {@code fetchAnswers}
     * below never duplicates this or overwrites a CLOSED save with a fresh
     * fetch. When there is no match -- including no session yet -- nothing
     * changes, and the existing REVIEW-gated fetch stays fully in control,
     * exactly as before this method existed.</p>
     */
    private void maybeOpenSavedAnswersOffline() {
        if (resolvedOfflineAnswersAtStartup) {
            return;
        }
        resolvedOfflineAnswersAtStartup = true;
        long sessionId = controller.sessionId();
        if (sessionId <= 0) {
            return;
        }
        AnswerStore.Saved saved = loadSavedAnswers();
        if (saved == null || !saved.bundle.sessionId.equals(Long.toString(sessionId))) {
            return;
        }
        answersFetchedForSession = sessionId;
        if (!saved.closed) {
            main.post(() -> openAnswers(saved.bundle, saved.questionId, saved.offset));
        }
    }

    /**
     * A saved reader survives the process restart that folding the temple
     * arms causes, so the saved state is read before any network request.
     * Two things gate reusing it instead of fetching fresh: it must belong
     * to this session (AnswerStore.save rejects a mismatched sessionId as
     * stale, so an unchecked read here would show a previous document's
     * answers forever, on a device that has ever saved a bundle, since the
     * fetch that follows would never run either), and it must not be CLOSED
     * -- AnswerStore.resume() is the only thing allowed to clear CLOSED, and
     * that is a user-requested action this automatic path is not, so this
     * reads with load() and leaves resume() uncalled from production. There
     * is deliberately no gesture to reopen a CLOSED reader within the same
     * session; an operator who closes the reader gets the HUD until the
     * next document.
     *
     * Past the saved state, one request, then the reader works with no
     * route to the server: the exam venue has no Wi-Fi network, and the
     * glasses reach the server only while the phone's hotspot is up, which
     * may be true only before the exam starts.
     */
    private void fetchAnswers(long sessionId) {
        new Thread(() -> {
            AnswerStore.Saved saved = loadSavedAnswers();
            if (saved != null && saved.bundle.sessionId.equals(Long.toString(sessionId))) {
                // Saved state belongs to this session. CLOSED must stop here,
                // not fall through to a fresh fetch: a fetch would open a new
                // reader on the same session's answers, silently undoing the
                // close it was supposed to respect.
                if (!saved.closed) {
                    main.post(() -> openAnswers(saved.bundle, saved.questionId, saved.offset));
                }
                return;
            }
            if (sessionId <= 0) {
                return;
            }
            try {
                AnswerBundle bundle = controller.api().answerBundle(sessionId);
                answerStore.start(bundle);
                main.post(() -> openAnswers(bundle, bundle.items.get(0).questionId, 0));
            } catch (Exception error) {
                Log.w(TAG, "answer bundle unavailable", error);
                // The likeliest failure at a venue: the hotspot is not yet
                // up when REVIEW is first published. Roll the guard back to
                // its unfetched sentinel so the next REVIEW publish --
                // nextReviewItem/previousReviewItem republish it on every
                // page turn -- retries, instead of one failed request
                // forfeiting the whole session's answers with no operator
                // gesture to recover. While this fetch was in flight the
                // guard stayed equal to sessionId, so no concurrent retry
                // could start; only a fetch that already finished (here)
                // reopens the door.
                answersFetchedForSession = -1;
                main.post(() -> {
                    if (isFinishing() || isDestroyed()) {
                        return;
                    }
                    wakeForResult();
                    hud.showLines(List.of("答案を取得できません", "通信を確認", ""));
                });
            }
        }, "answer-bundle").start();
    }

    private AnswerStore.Saved loadSavedAnswers() {
        try {
            return answerStore.load();
        } catch (IOException error) {
            Log.w(TAG, "saved answer state unavailable", error);
            return null;
        }
    }

    private void openAnswers(AnswerBundle bundle, String questionId, int offset) {
        if (sessionClosed || isFinishing() || isDestroyed()) {
            // The fetch (or a resume) completed after the two-stage exit
            // already finished this Activity. Nothing to show, and nothing
            // left to leak a View or a reader into.
            return;
        }
        wakeForResult();
        answers = new AnswerView(this);
        // A placeholder viewport: AnswerView.onSizeChanged calls
        // reader.viewport with its own Paint as soon as it is laid out, and
        // the view owns the layout, so nothing here should guess at width --
        // it only has to be safe, not accurate. A measurer that always
        // reports zero width never exceeds the placeholder's width=1f, so
        // AnswerLayout.paginate never has to split a line mid-cluster; a
        // measurer keyed to UTF-16 length() (the previous placeholder)
        // measures >= 2 for any surrogate pair or combining mark, which is
        // always > 1f and throws IllegalArgumentException from inside this
        // main.post callback -- uncaught, and permanent, since the bundle
        // is already saved to disk by the time this runs and the next
        // launch takes the same saved-state branch into the same crash.
        reader = new AnswerReader(bundle, 1f, 2, text -> 0f);
        reader.restore(questionId, offset);
        answers.bind(reader);
        setContentView(answers);
    }

    private void closeAnswers() {
        persistAnswerPosition(true);
        reader = null;
        answers = null;
        setContentView(hud);
    }

    private void waitWithDisplayOff() {
        if (awaitingAnswers || sessionClosed || isFinishing()) return;
        awaitingAnswers = true;
        PowerManager power = (PowerManager) getSystemService(POWER_SERVICE);
        if (power != null) {
            analysisWakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "docscan:analysis");
            analysisWakeLock.acquire(); // held only until result, error or explicit exit
        }
        if (displaySleep.sleep(this) == DisplaySleep.Result.NOT_PERMITTED) {
            hud.showLines(List.of("解析中", "消灯には設定の許可が必要", ""));
        }
    }

    private void wakeForResult() {
        if (sessionClosed) return;
        if (awaitingAnswers && !displaySleep.wake(this)) {
            Log.w(TAG, "answer display wake request refused");
        }
        awaitingAnswers = false;
        releaseAnalysisWakeLock();
    }

    private void releaseAnalysisWakeLock() {
        if (analysisWakeLock != null && analysisWakeLock.isHeld()) analysisWakeLock.release();
        analysisWakeLock = null;
    }

    /**
     * Persistence must never throw into the UI, exactly as the fetch does
     * not. The write itself runs off the main thread on
     * {@code answerPersistExecutor} -- single-threaded, so writes still
     * commit in the order the gestures that queued them happened in. CLOSED
     * is queued on that same executor, not a separate path, so it can never
     * be overtaken by a position write queued earlier by a faster gesture;
     * and this method blocks on it (only for CLOSED) so the latch is
     * durable before {@code closeAnswers} swaps the screen back to the HUD.
     */
    private void persistAnswerPosition(boolean closed) {
        if (reader == null) {
            return;
        }
        AnswerBundle bundle = reader.bundle();
        String questionId = reader.current().questionId;
        int offset = reader.offset();
        Future<?> queued = answerPersistExecutor.submit(
                () -> writeAnswerPosition(bundle, questionId, offset, closed));
        if (closed) {
            try {
                queued.get();
            } catch (InterruptedException | ExecutionException error) {
                Log.w(TAG, "answer position not saved", error);
            }
        }
    }

    private void writeAnswerPosition(
            AnswerBundle bundle, String questionId, int offset, boolean closed) {
        try {
            answerStore.save(bundle, questionId, offset, closed);
        } catch (IOException error) {
            Log.w(TAG, "answer position not saved", error);
        }
    }
}
