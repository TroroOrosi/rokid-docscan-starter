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
import android.media.AudioManager;
import android.provider.Settings;
import android.os.SystemClock;
import android.util.Log;
import android.view.KeyEvent;
import android.view.WindowManager;
import android.widget.Toast;

import java.io.IOException;
import java.io.File;
import java.util.List;
import java.util.ArrayList;
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
import dev.rokid.docscanrelay.DocScanApi;
import dev.rokid.docscanrelay.DocScanController;
import dev.rokid.docscanrelay.JapaneseOcr;
import dev.rokid.docscanrelay.RelayState;
import dev.rokid.docscanrelay.study.AnswerBundle;
import dev.rokid.docscanrelay.study.AnswerItem;
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
    /** Diagnostic override for this launch only; normal launches always capture automatically. */
    private static final String EXTRA_MANUAL = "manual";
    /** Open this server session's answers directly: checks the answer display without a capture. */
    private static final String EXTRA_ANSWERS = "answers";
    private static final int CAMERA_PERMISSION_REQUEST = 7401;
    private static final int AUDIO_PERMISSION_REQUEST = 7402;
    private boolean listeningMode;
    private boolean mixedMode;
    private boolean choosingSession;
    private int startupSelection;
    private AnswerStore.Saved startupAnswers;
    private List<DocScanController.SavedCapture> startupCaptures;
    private boolean viewingPreviousAnswers;
    private boolean startupStarting;
    private ListeningRecorder listening;
    private boolean finishingAudio;
    private boolean captureEndRequested;
    private boolean audioStopRequested;
    private long listeningDocument;
    private File listeningDirectory;
    private boolean resumingListening;

    /**
     * Stored JPEGs from 1.25.015-20260903-150201, checked 2026-09-16:
     * clockwise 270 makes the vertical Japanese page upright. The old
     * 180-degree setting left this capture sideways; sensor metadata alone
     * did not establish the correct paper orientation.
     */
    private static final int MEASURED_ROTATION_DEGREES = 270;

    private static final String WAKE_SESSION = "wake_session_id";
    private static final String WAKE_GENERATION = "wake_generation";
    private String deviceId;
    private volatile long powerGeneration;
    private volatile long powerSequence;
    private long powerSession;
    private String powerPhase = "capturing";
    private volatile boolean writingDone;
    private final ExecutorService stateExecutor = Executors.newSingleThreadExecutor(runnable -> {
        Thread thread = new Thread(runnable, "glasses-state");
        thread.setDaemon(true);
        return thread;
    });

    private final GlassesInputNormalizer normalizer = new GlassesInputNormalizer();
    private final BackExitPolicy backExit = new BackExitPolicy();
    private final DisplaySleep displaySleep = new DisplaySleep();
    private boolean awaitingAnswers;
    private volatile boolean sessionClosed;
    private final Handler main = new Handler(Looper.getMainLooper());
    private static final long DISPLAY_IDLE_MILLIS = 5_000;
    private Runnable displayIdle;
    private long displayIdleToken;
    private boolean idleAsleep;
    private boolean captureDisplayActive;
    private String displayRequest;
    private RelayState displayedState;

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
    // reset back to -1 on a failed fetch, so the next matching phone
    // notification can retry after the connection recovers.
    private volatile long answersFetchedForSession = -1;
    private volatile long answersFetchedRevision;
    private long answersFetchSession = -1, answersFetchGeneration = -1, answersFetchRevision = -1;
    private long pendingAnswerRevision = -1;
    private long acknowledgedSession, acknowledgedRevision = -1;
    // Wakes the display once per run of failed fetches, not once per retry.
    private volatile boolean answerFetchFailing;
    // True once this Activity instance has checked AnswerStore for a saved
    // reader without waiting on RelayState.REVIEW, which needs the network
    // to ever be published (see fetchAnswers's own comment). Read and
    // written only from onUpdate's calling thread -- the controller's
    // serial executor in production, whatever thread drives it directly in
    // tests -- the same single-caller convention answersFetchedForSession
    // already relies on.
    private boolean resolvedOfflineAnswersAtStartup;
    // True while the app owned the screen when the most recent
    // KEYCODE_BACK DOWN was processed. Read again by the matching UP: onAction
    // (called from the DOWN phase, below) may itself close the reader --
    // setting `reader` to null -- as a side effect of that same press, so the
    // UP phase cannot recompute this from the live `reader` field. Always
    // read/written on the main thread (onKeyDown/onKeyUp).
    private boolean backOwnedByReader;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        muteOutput();
        deviceId = Settings.Secure.getString(getContentResolver(), Settings.Secure.ANDROID_ID);
        if (deviceId == null || deviceId.isEmpty()) {
            deviceId = getPreferences(MODE_PRIVATE).getString("device_id", "");
            if (deviceId.isEmpty()) deviceId = java.util.UUID.randomUUID().toString();
            getPreferences(MODE_PRIVATE).edit().putString("device_id", deviceId).commit();
        }
        powerGeneration = getPreferences(MODE_PRIVATE).getLong("power_generation", 0);
        powerSequence = getPreferences(MODE_PRIVATE).getLong("power_sequence", 0);
        powerSession = getPreferences(MODE_PRIVATE).getLong("power_session", 0);
        powerPhase = getPreferences(MODE_PRIVATE).getString("power_phase", "capturing");
        displayRequest = getPreferences(MODE_PRIVATE).getString("power_display", null);
        acknowledgedSession = powerSession;
        acknowledgedRevision = getPreferences(MODE_PRIVATE).getLong("power_ack_revision", -1);
        if (getIntent() != null && getIntent().getBooleanExtra("wear_origin", false)) {
            if (!acceptsWearEntry(getIntent())) { displaySleep.sleep(this); finish(); return; }
            setIntent(new Intent(this, DocScanGlassActivity.class).putExtra("chooser", true));
        }
        boolean restoringWake = acceptsWake(getIntent());
        if (getIntent() != null && getIntent().hasExtra(WAKE_SESSION) && !restoringWake) {
            Log.i(TAG, "stale answer wake rejected before opening a screen");
            displaySleep.sleep(this);
            finish();
            return;
        }
        if (!restoringWake) beginPowerGeneration();
        // Hold only the active app window; the operator's display timeout stays intact.
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        hud = new HudView(this);
        setContentView(hud);
        answerStore = new AnswerStore(getFilesDir());
        connectionSettings = new ConnectionSettings(new File(getNoBackupFilesDir(), "connection.bin"));
        choosingSession = true;
        resolvedOfflineAnswersAtStartup = true;
        hud.calibrateGuide(getPreferences(MODE_PRIVATE).getFloat(
                EXTRA_GUIDE, (float) FramingGuide.UNCALIBRATED_FRACTION));
        hud.showSpreadGuide(getPreferences(MODE_PRIVATE).getBoolean(EXTRA_SPREAD, true));

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
        startupSelection = mixedMode ? 1 : listeningMode ? 2 : 0;
        startupAnswers = loadSavedAnswers();
        long answersSession = getIntent() == null ? 0 : getIntent().getLongExtra(EXTRA_ANSWERS, 0);
        if (restoringWake) {
            choosingSession = false;
            awaitingAnswers = true;
            receiveWake(getIntent());
        } else if (answersSession > 0) {
            choosingSession = false;
            viewingPreviousAnswers = true;
            hud.showLines(List.of("答案を取得中", "", ""));
            fetchAnswers(answersSession);
        } else {
            showStartupChoices();
        }
        if (!hasCamera()) {
            requestPermissions(
                    new String[] {Manifest.permission.CAMERA}, CAMERA_PERMISSION_REQUEST);
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        if (intent != null && intent.getBooleanExtra("wear_origin", false)) {
            if (!acceptsWearEntry(intent)) return;
            intent = new Intent(this, DocScanGlassActivity.class).putExtra("chooser", true);
        }
        setIntent(intent);
        muteOutput();
        if (intent != null && intent.hasExtra(WAKE_SESSION)) { receiveWake(intent); return; }
        if (intent != null && intent.getBooleanExtra("chooser", false)) {
            stopCaptureHardware();
            persistAnswerPosition(false);
            setIntent(new Intent(this, DocScanGlassActivity.class).putExtra("chooser", true));
            recreate();
            return;
        }
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
            mixedMode = intent != null && intent.hasExtra("mixed") ? intent.getBooleanExtra("mixed", false)
                    : "mixed".equals(getPreferences(MODE_PRIVATE).getString("exam_type", ""));
            if (mixedMode) listeningMode = true;
            getPreferences(MODE_PRIVATE).edit().putBoolean("listening", listeningMode).apply();
            if (!choosingSession) controller.setListeningMode(listeningMode);
            boolean manual = intent != null && intent.getBooleanExtra(EXTRA_MANUAL, false);
            getPreferences(MODE_PRIVATE).edit().remove(EXTRA_MANUAL).apply();
            controller.setManualCapture(manual);
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
                if (server == null && key == null) {
                    ConnectionSettings.Saved setup = connectionSettings.provisioning();
                    if (setup != null) { server = setup.server; key = setup.key; }
                }
                ConnectionSettings.Saved saved = server != null && key != null ? null : connectionSettings.load();
                if (saved != null) {
                    if (server == null) server = saved.server;
                    if (key == null) key = ConnectionSettings.normalizeServer(server).equals(saved.server) ? saved.key : "";
                }
                if (choosingSession) controller.configureForLocalStart(server, key, MEASURED_ROTATION_DEGREES);
                else controller.configureAndResume(server, key, MEASURED_ROTATION_DEGREES);
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
        onAction(GlassesInputAction.BACK, SystemClock.elapsedRealtime());
    }

    private void exitSession() {
            if (!choosingSession && !viewingPreviousAnswers && !controller.closeLocalSession()) {
                backExit.reset();
                hud.showLines(List.of("終了を保存できません", "原本は保持しています", "もう一度操作してください"));
                return;
            }
            if (reader != null && !closeAnswers()) return;
            sessionClosed = true;
            stopCaptureHardware();
            notifyPhase("closed", activeSession());
            Log.i(TAG, "exit confirmed");
            displaySleep.sleep(this);
            startActivity(new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            finish();
    }

    @Override protected void onResume() {
        super.onResume();
        muteOutput();
        if (sessionClosed || writingDone || idleAsleep || isFinishing() || isDestroyed()
                || !isCurrentPowerGeneration(powerGeneration)) displaySleep.sleep(this);
        else getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        if (deviceId != null && !isFinishing() && !isDestroyed()) {
            try { startForegroundService(new Intent(this, WearService.class)); }
            catch (RuntimeException error) { Log.w(TAG, "wear monitoring unavailable: " + error.getClass().getSimpleName()); }
        }
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
        cancelDisplayIdle();
        if (listening != null) listening.close();
        stopService(new Intent(this, ListeningService.class));
        // Folding the temple arms force-stops this process through the
        // assistserver third_app scene, so destruction is an ordinary end to a
        // session rather than an exceptional one. The controller persists its
        // pending capture, which is what makes that survivable.
        normalizer.reset();
        backExit.reset();
        if (controller != null) controller.close();
        if (surface != null) surface.close();
        if (camera != null) camera.close();
        if (ocr != null) ocr.close();
        if (cameraThread != null) cameraThread.quitSafely();
        stateExecutor.shutdown();
        answerPersistExecutor.shutdown();
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
            backOwnedByReader = !sessionClosed;
        }
        // KeyEvent uses uptime; convert to the controller's elapsed clock,
        // preserving the event's age if the main thread delivered it late.
        long elapsedMillis = event.getEventTime()
                + SystemClock.elapsedRealtime() - SystemClock.uptimeMillis();
        if (event.getRepeatCount() == 0) {
            if (keyCode == KeyEvent.KEYCODE_NOTIFICATION && "DOWN".equals(phase)
                    && !choosingSession && reader == null && !sessionClosed) {
                controller.onGlassesGestureStarted(elapsedMillis);
            }
            Optional<GlassesInputAction> action = normalizer.accept(InputSignal.key(
                    elapsedMillis, phase, name, GlassKeyEvents.isKnown(name)));
            if (BuildConfig.DEBUG) Log.i(TAG, "input phase=" + phase + " key=" + name
                    + " event=" + elapsedMillis + " action=" + action.orElse(null));
            action.ifPresent(value -> onAction(value, elapsedMillis));
        }
        if (isBackKey && backOwnedByReader) {
            // DOWN and its matching UP belong to one app gesture. Do not let
            // the framework's onBackPressed count that same gesture again.
            return true;
        }
        // Consume every gesture key the firmware delivers except BACK, so the
        // system does not act on it behind the session.
        return !"KEYCODE_BACK".equals(name) && GlassKeyEvents.isKnown(name);
    }

    private void onAction(GlassesInputAction action, long elapsedMillis) {
        if (sessionClosed) return;
        muteOutput();
        if (!writingDone) {
            if (displayProtected()) keepDisplayActive();
            else {
                keepDisplayActive();
                notifyPhase(choosingSession ? "chooser" : awaitingAnswers ? "analyzing" : "waiting", activeSession(), "wake");
                scheduleDisplayIdle();
            }
        }
        if (action != GlassesInputAction.BACK) {
            backExit.reset();
        }
        if (choosingSession) {
            if (startupStarting) return;
            if (action == GlassesInputAction.SWIPE_FORWARD || action == GlassesInputAction.SWIPE_BACK) {
                int step = action == GlassesInputAction.SWIPE_FORWARD ? 1 : -1;
                int count = startupCaptures == null ? startupOptions().size() : startupCaptures.size();
                startupSelection = Math.floorMod(startupSelection + step, count);
                showStartupChoices();
            } else if (action == GlassesInputAction.SHORT_TAP) {
                startSelectedSession();
            } else if (action == GlassesInputAction.BACK) {
                if (startupCaptures != null) {
                    startupCaptures = null;
                    startupSelection = 3;
                    backExit.reset();
                    showStartupChoices();
                } else if (backExit.onBack(elapsedMillis) == BackExitPolicy.Decision.EXIT) exitSession();
                else hud.showLines(List.of("もう一度で終了", "タップで選択中の読取を開始", ""));
            }
            return;
        }
        if (reader != null) {
            if (action == GlassesInputAction.SHORT_TAP) { if (mixedMode) toggleAudio(); return; }
            if (action == GlassesInputAction.BACK) {
                if (reader.screen() != AnswerReader.Screen.ANSWER) {
                    reader.back();
                    backExit.reset();
                    answers.refresh();
                } else {
                    boolean interim = reader.bundle().intermediate();
                    if (!closeAnswers(!interim)) return;
                    if (interim) {
                        backExit.reset();
                        awaitingAnswers = true;
                        enterIdleDisplay("waiting", activeSession());
                        hud.showLines(List.of("読解の記入終了", "音声答案を待っています", "タップで録音開始・終了"));
                        return;
                    }
                    writingDone = true;
                    backExit.reset(); // the completion gesture never arms the exit window
                    stopCaptureHardware();
                    notifyPhase("writing_done", activeSession());
                    awaitingAnswers = false;
                    getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                    hud.showLines(List.of("記入終了", "", ""));
                    displaySleep.sleep(this);
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
        if (writingDone) {
            if (action == GlassesInputAction.BACK) {
                if (backExit.onBack(elapsedMillis) == BackExitPolicy.Decision.EXIT) exitSession();
                // Stay asleep while arming the second confirmation.
            }
            return;
        }
        if (mixedMode) {
            boolean swipe = action == GlassesInputAction.SWIPE_FORWARD || action == GlassesInputAction.SWIPE_BACK;
            if (awaitingAnswers && swipe) {
                AnswerStore.Saved saved = loadSavedAnswers();
                if (saved != null && !saved.closed && saved.bundle.sessionId.equals(Long.toString(activeSession()))) {
                    openAnswers(saved.bundle, saved.questionId, saved.offset);
                }
                return;
            }
            if (swipe || (awaitingAnswers && action == GlassesInputAction.SHORT_TAP)) { toggleAudio(); return; }
        }
        if (controller.getState() == RelayState.ERROR
                || (listeningMode && !mixedMode && listening == null && controller.getState() != RelayState.REVIEW)) {
            if (action == GlassesInputAction.BACK) {
                if (backExit.onBack(elapsedMillis) == BackExitPolicy.Decision.EXIT) exitSession();
                else hud.showLines(List.of("もう一度ダブルタップで終了", "保存した資料は保持します", ""));
            }
            return;
        }
        // Feedback only; the serial controller still owns finish/retake and the deadline.
        if (action == GlassesInputAction.BACK && surface != null
                && controller.getState() == RelayState.CAPTURE_REVIEW) {
            surface.showCaptureEndRequested();
        }
        if (listeningMode && !mixedMode && action == GlassesInputAction.BACK && (!awaitingAnswers || !audioStopRequested)) {
            boolean stopAudio = captureEndRequested || controller.getState() == RelayState.LISTENING;
            captureEndRequested = true;
            controller.onGlassesAction(action, elapsedMillis);
            if (stopAudio) finishAudio();
            return;
        }
        if (awaitingAnswers && action == GlassesInputAction.BACK) {
            if (backExit.onBack(elapsedMillis) == BackExitPolicy.Decision.EXIT) exitSession();
            else {
                displaySleep.wake(this);
                hud.showLines(List.of("もう一度ダブルタップで終了", "保存した資料は保持します", "結果を待っています"));
            }
            return;
        }
        controller.onGlassesAction(action, elapsedMillis);
    }

    private List<String> startupOptions() {
        List<String> options = new ArrayList<>(List.of("通常の読取", "合同英語（読解＋音声）", "リスニング"));
        if (controller.hasSavedWorkflow()) options.add("中断した読取");
        if (startupAnswers != null) options.add("前回の答案");
        return options;
    }

    private void showStartupChoices() {
        enterIdleDisplay("chooser", 0);
        if (startupCaptures != null) {
            DocScanController.SavedCapture selected = startupCaptures.get(startupSelection);
            hud.showLines(List.of("中断した読取 " + (startupSelection + 1) + "/" + startupCaptures.size(),
                    selected.label, "スワイプで選択・タップで再開", "ダブルタップで戻る"));
            return;
        }
        List<String> options = startupOptions();
        startupSelection = Math.floorMod(startupSelection, options.size());
        List<String> lines = new ArrayList<>();
        for (int index = 0; index < options.size(); index++) {
            lines.add((index == startupSelection ? "▶ " : "　 ") + options.get(index));
        }
        lines.add("スワイプで選択・タップで開始");
        hud.showLines(lines);
    }

    private void startSelectedSession() {
        String selected = startupCaptures == null ? startupOptions().get(startupSelection) : "中断記録";
        backExit.reset();
        if ("中断した読取".equals(selected)) {
            startupCaptures = controller.savedCaptures();
            if (startupCaptures.isEmpty()) startupCaptures = null;
            startupSelection = 0;
            showStartupChoices();
            return;
        }
        if ("前回の答案".equals(selected)) {
            try {
                AnswerStore.Saved saved = answerStore.resume();
                if (saved == null) return;
                beginPowerGeneration();
                choosingSession = false;
                viewingPreviousAnswers = true;
                openAnswers(saved.bundle, saved.questionId, saved.offset);
            } catch (IOException error) { hud.showLines(List.of("前回答案を開けません", "原本は保持しています", "")); }
            return;
        }
        if (!hasCamera()) {
            requestPermissions(new String[]{Manifest.permission.CAMERA}, CAMERA_PERMISSION_REQUEST);
            return;
        }
        viewingPreviousAnswers = false;
        startupStarting = true;
        if (startupCaptures != null) {
            DocScanController.SavedCapture saved = startupCaptures.get(startupSelection);
            listeningMode = saved.listening;
            mixedMode = saved.mixed;
            controller.resumeLocalSession(saved.id, this::onStartupSelected);
        } else {
            mixedMode = startupSelection == 1;
            listeningMode = mixedMode || startupSelection == 2;
            String examType = mixedMode ? "mixed" : listeningMode ? "listening" : "written";
            getPreferences(MODE_PRIVATE).edit().putBoolean("listening", listeningMode).putString("exam_type", examType).apply();
            controller.startLocalSession(examType, this::onStartupSelected);
        }
    }

    private void onStartupSelected(boolean accepted) {
        main.post(() -> {
            if (sessionClosed) return;
            startupStarting = false;
            if (!accepted) {
                hud.showLines(List.of("開始・再開できません", "接続先と保存記録を確認", "ダブルタップで戻る"));
                return;
            }
            beginPowerGeneration();
            choosingSession = false;
            startupCaptures = null;
            notifyPhase("capturing", controller.sessionId());
            answersFetchedForSession = -1;
            answersFetchedRevision = 0;
            onUpdate(controller.getState(), List.of("読取を開始", "", ""), "Local selection accepted");
        });
    }

    // --- camera -----------------------------------------------------------

    private GlassCamera.Callback cameraCallback() {
        return new GlassCamera.Callback() {
            @Override
            public void onCaptured(byte[] jpeg, int width, int height, long elapsedMillis) {
                Log.i(TAG, "captured " + width + "x" + height + " in " + elapsedMillis + " ms");
                controller.onPhoto(jpeg);
            }

            @Override public void onPreview(android.graphics.Bitmap frame) {
                if (surface == null) frame.recycle();
                else surface.showLivePreview(frame);
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

    @Override public void onAutoCaptureChanged(boolean running) {
        main.post(() -> {
            if (sessionClosed || writingDone) return;
            captureDisplayActive = running;
            if (running) {
                keepDisplayActive();
                notifyPhase("capturing", controller.sessionId(), "wake");
            } else if (!displayProtected()) enterIdleDisplay(awaitingAnswers ? "analyzing" : "waiting", activeSession());
        });
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
        if (sessionClosed || writingDone || choosingSession) return;
        main.post(() -> {
            if (sessionClosed || writingDone || choosingSession || displayedState == state) return;
            displayedState = state;
            if (displayProtected()) keepDisplayActive();
            else enterIdleDisplay(awaitingAnswers ? "analyzing" : "waiting", activeSession());
        });
        maybeOpenSavedAnswersOffline();
        if (state == RelayState.LISTENING) {
            main.post(() -> {
                if (audioStopRequested && !finishingAudio) {
                    wakeForResult();
                    hud.showLines(List.of("録音・転送を確認", "原音は保存済み", "ダブルタップで再試行"));
                } else {
                    hud.showLines(GlassesHudText.adapt(hudLines));
                    waitWithDisplayOff();
                }
            });
            return;
        }
        if (state == RelayState.FINALIZING) main.post(this::waitWithDisplayOff);
        if (state == RelayState.ERROR || state == RelayState.READING) {
            main.post(() -> { if (awaitingAnswers) wakeForResult(); });
        }
        if (state == RelayState.REVIEW) {
            main.post(() -> {
                if (reader == null) waitWithDisplayOff();
                if (reader != null) notifyPhase("reading", controller.sessionId());
            });
            return;
        }
        // AIMING, STABILIZING and CAPTURE_REVIEW each own the screen through
        // their own surface call -- the guide brackets, and the still. Redrawing
        // plain text here would wipe them.
        if (state == RelayState.AIMING
                || state == RelayState.STABILIZING
                || state == RelayState.CAPTURE_REVIEW) {
            return;
        }
        main.post(() -> {
            hud.showLines(GlassesHudText.adapt(hudLines));
            // Waiting to shoot: nothing here needs reading, and the page is behind it.
            if (state == RelayState.READY || state == RelayState.READING) hud.fadeSoon();
        });
    }

    @Override public void onListeningReady(File directory, long documentId, boolean resume) {
        main.post(() -> {
            if (sessionClosed) return;
            if (directory.equals(listeningDirectory)) {
                listeningDocument = documentId;
                if (listening != null && documentId > 0) {
                    try {
                        listening.bindDocument(documentId);
                        if (audioStopRequested && !finishingAudio) finishAudio();
                    }
                    catch (IOException error) { controller.onListeningError(); }
                }
                return;
            }
            if (listening != null) listening.close();
            listening = null;
            finishingAudio = false;
            captureEndRequested = false;
            audioStopRequested = false;
            listeningDocument = documentId;
            listeningDirectory = directory;
            resumingListening = resume;
            if (mixedMode && !resume) return; // images start now; the operator starts audio when it begins
            if (!resume && checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, AUDIO_PERMISSION_REQUEST);
                return;
            }
            startListening();
        });
    }

    private void startListening() {
        try {
            listening = new ListeningRecorder(listeningDirectory, listeningDocument, controller.api(), () -> {
                controller.onListeningError();
                main.post(() -> { wakeForResult(); stopService(new Intent(this, ListeningService.class)); });
            });
            if (resumingListening) {
                if (!listening.restore()) {
                    if (!mixedMode) throw new IOException("再開する録音がありません");
                    listening.close(); listening = null; resumingListening = false; return;
                }
                if (listening.isInterrupted()) controller.onListeningError();
                finishAudio();
                return;
            }
            startForegroundService(new Intent(this, ListeningService.class));
            ListeningRecorder recording = listening;
            listening.start(active -> main.post(() -> {
                if (sessionClosed || listening != recording) return;
                hud.showRecording(active);
                if (active) {
                    startService(new Intent(this, ListeningService.class).putExtra(ListeningService.RECORDING, true));
                    if (!mixedMode) controller.startAutoCapture();
                } else if (finishingAudio && !recording.isInterrupted()) {
                    startService(new Intent(this, ListeningService.class).putExtra(ListeningService.FINISHING, true));
                } else stopService(new Intent(this, ListeningService.class));
            }));
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
        audioStopRequested = true;
        listening.requestStop();
        try { startForegroundService(new Intent(this, ListeningService.class).putExtra(ListeningService.FINISHING, true)); }
        catch (RuntimeException error) { finishingAudio = false; controller.onListeningError(); return; }
        if (controller.getState() == RelayState.LISTENING || controller.getState() == RelayState.FINALIZING) waitWithDisplayOff();
        ListeningRecorder recording = listening;
        new Thread(() -> {
            try {
                recording.finishAndUpload();
                main.post(() -> {
                    if (sessionClosed || listening != recording) return;
                    stopService(new Intent(this, ListeningService.class));
                    controller.completeListening();
                });
            } catch (Exception error) {
                main.post(() -> {
                    if (sessionClosed || listening != recording) return;
                    finishingAudio = false;
                    if (error instanceof ListeningRecorder.DocumentPending && listeningDocument > 0) { finishAudio(); return; }
                    if (!(error instanceof ListeningRecorder.DocumentPending)) stopService(new Intent(this, ListeningService.class));
                    wakeForResult();
                    if (controller.getState() == RelayState.LISTENING || controller.getState() == RelayState.ERROR) {
                        hud.showLines(List.of("録音・転送を確認", "原音は保存済み", "ダブルタップで再試行"));
                    }
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
        fetchAnswers(sessionId, 0);
    }

    private void toggleAudio() {
        if (!mixedMode || sessionClosed || writingDone || listeningDirectory == null) return;
        if (listening != null) {
            if (!finishingAudio) finishAudio();
            return;
        }
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, AUDIO_PERMISSION_REQUEST);
            return;
        }
        startListening();
    }

    private synchronized void fetchAnswers(long sessionId, long requestedRevision) {
        long generationAtRequest = powerGeneration;
        if (answersFetchGeneration == generationAtRequest && answersFetchSession == sessionId) {
            pendingAnswerRevision = Math.max(pendingAnswerRevision, requestedRevision);
            return;
        }
        answersFetchGeneration = generationAtRequest;
        answersFetchSession = sessionId;
        answersFetchRevision = requestedRevision;
        pendingAnswerRevision = -1;
        new Thread(() -> {
            try {
            AnswerStore.Saved saved = loadSavedAnswers();
            if (saved != null && saved.bundle.sessionId.equals(Long.toString(sessionId))) {
                // Saved state belongs to this session. CLOSED must stop here,
                // not fall through to a fresh fetch: a fetch would open a new
                // reader on the same session's answers, silently undoing the
                // close it was supposed to respect.
                if (!saved.closed && saved.bundle.revision >= requestedRevision) {
                    main.post(() -> {
                        if (isCurrentPowerGeneration(generationAtRequest)) openAnswers(saved.bundle, saved.questionId, saved.offset);
                    });
                }
                if (saved.closed || saved.bundle.revision >= requestedRevision) return;
            }
            if (sessionId <= 0) {
                return;
            }
            try {
                // configureForLocalStart is asynchronous; a fetch at launch can beat it.
                DocScanApi api = controller.api();
                for (int waited = 0; api == null && waited < 50; waited++) {
                    Thread.sleep(100);
                    api = controller.api();
                }
                if (api == null) throw new IllegalStateException("server not configured");
                AnswerBundle bundle = api.answerBundle(sessionId);
                if (!isCurrentPowerGeneration(generationAtRequest) || writingDone || sessionClosed) return;
                if (bundle.revision < requestedRevision) throw new IOException("requested answer revision unavailable");
                answerFetchFailing = false;
                String question = bundle.items.get(0).questionId;
                int offset = 0;
                if (saved != null && saved.bundle.sessionId.equals(bundle.sessionId)) {
                    AnswerReader validation = new AnswerReader(saved.bundle, 1f, 2, text -> 0f, true);
                    validation.restore(saved.questionId, saved.offset);
                    if (!validation.accept(bundle)) throw new IOException("answer identity changed");
                    question = validation.current().questionId;
                    offset = validation.offset();
                    answerStore.save(bundle, question, offset, false);
                } else answerStore.start(bundle);
                String restoreQuestion = question;
                int restoreOffset = offset;
                main.post(() -> {
                    if (isCurrentPowerGeneration(generationAtRequest)) openAnswers(bundle, restoreQuestion, restoreOffset);
                });
            } catch (Exception error) {
                if (!isCurrentPowerGeneration(generationAtRequest) || writingDone || sessionClosed) return;
                Log.w(TAG, "answer bundle unavailable", error);
                // A matching phone notification may retry after the connection recovers.
                answersFetchedForSession = -1;
                // 409 "being made": the server is still analysing; one message
                // carries the whole booklet and its answers arrive together. Keep
                // the display asleep for that. Any other 409 (nothing detected,
                // locked, not finalized) will not end by waiting: wake and say so.
                boolean conflict = error instanceof DocScanApi.ApiException
                        && ((DocScanApi.ApiException) error).getStatusCode() == 409;
                boolean analysing = conflict && String.valueOf(error.getMessage()).contains("being made");
                String reason = String.valueOf(error.getMessage());
                main.post(() -> {
                    if (!isCurrentPowerGeneration(generationAtRequest) || writingDone || sessionClosed
                            || isFinishing() || isDestroyed()) return;
                    if (!analysing && !answerFetchFailing) wakeForResult();
                    answerFetchFailing = !analysing;
                    hud.showLines(analysing ? List.of("解析中", "答案を待っています", "")
                            : conflict ? List.of("解答がありません", noAnswerReason(reason), "")
                            : List.of("答案を取得できません", "通信を確認", ""));
                });
            }
            } finally {
                main.post(() -> {
                    synchronized (DocScanGlassActivity.this) {
                        if (answersFetchGeneration != generationAtRequest || answersFetchSession != sessionId
                                || answersFetchRevision != requestedRevision) return;
                        long newer = pendingAnswerRevision;
                        answersFetchSession = -1;
                        pendingAnswerRevision = -1;
                        if (newer > requestedRevision && isCurrentPowerGeneration(generationAtRequest)
                                && !writingDone && !sessionClosed && !isDestroyed()) fetchAnswers(sessionId, newer);
                    }
                });
            }
        }, "answer-bundle").start();
    }

    /** The server's 409 detail as one short HUD line. */
    static String noAnswerReason(String detail) {
        if (detail.contains("no problems")) return "問題を検出できません";
        if (detail.contains("locked")) return "本番モードでは表示不可";
        if (detail.contains("finalize-reading")) return "撮影が終わっていません";
        return "サーバを確認";
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
        if (sessionClosed || writingDone || isFinishing() || isDestroyed() || !isCurrentPowerGeneration(powerGeneration)) {
            // The fetch (or a resume) completed after the two-stage exit
            // already finished this Activity. Nothing to show, and nothing
            // left to leak a View or a reader into.
            return;
        }
        if (reader != null && reader.bundle().sessionId.equals(bundle.sessionId)
                && reader.bundle().inputDigest.equals(bundle.inputDigest) && reader.bundle().revision >= bundle.revision) {
            acknowledgeDisplayedAnswers();
            retryAcknowledgement();
            return;
        }
        wakeForResult();
        try { answersFetchedForSession = Long.parseLong(bundle.sessionId); } catch (NumberFormatException ignored) { }
        answersFetchedRevision = bundle.revision;
        if (reader != null && reader.accept(bundle)) {
            persistAnswerPosition(false);
            answers.refresh();
            acknowledgeDisplayedAnswers();
            if (hasWrittenAnswers()) { keepDisplayActive(); notifyPhase("reading", activeSession()); }
            else enterIdleDisplay("waiting", activeSession());
            return;
        }
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
        reader = new AnswerReader(bundle, 1f, 2, text -> 0f, true);
        reader.restore(questionId, offset);
        answers.bind(reader);
        setContentView(answers);
        acknowledgeDisplayedAnswers();
        if (hasWrittenAnswers()) {
            keepDisplayActive();
            notifyPhase("reading", activeSession());
        } else enterIdleDisplay("waiting", activeSession());
    }

    private boolean closeAnswers() {
        return closeAnswers(true);
    }

    private boolean closeAnswers(boolean terminal) {
        if (!persistAnswerPosition(terminal, true)) {
            // A failed durable CLOSED write is not an exit. Keep the answer
            // and the same input route so the operator can retry explicitly.
            backExit.reset();
            if (answers != null) answers.announceSaveFailure();
            return false;
        }
        reader = null;
        answers = null;
        setContentView(hud);
        return true;
    }

    private void waitWithDisplayOff() {
        if (sessionClosed || writingDone || isFinishing()) return;
        if (reader != null && hasWrittenAnswers()) return;
        awaitingAnswers = true;
        stopCaptureHardware();
        enterIdleDisplay("analyzing", controller.sessionId());
        hud.showLines(List.of("解析中", "", ""));
    }

    private void wakeForResult() {
        if (sessionClosed || writingDone) return;
        if (awaitingAnswers && !displaySleep.wake(this)) Log.w(TAG, "answer display wake request refused");
        keepDisplayActive();
        awaitingAnswers = false;
        if (!displayProtected()) {
            notifyPhase("waiting", activeSession(), "wake");
            scheduleDisplayIdle();
        }
    }

    private void stopCaptureHardware() {
        captureDisplayActive = false;
        if (camera != null) camera.pausePreview();
        if (hud != null) hud.capturePreview(false);
    }

    private boolean displayProtected() {
        if ((reader != null && hasWrittenAnswers()) || captureDisplayActive) return true;
        RelayState state = controller == null ? null : controller.getState();
        return state == RelayState.AIMING || state == RelayState.STABILIZING
                || state == RelayState.CAPTURING || state == RelayState.CAPTURE_REVIEW;
    }

    private boolean hasWrittenAnswers() {
        if (reader == null) return false;
        for (AnswerItem item : reader.bundle().items) if (!item.answer.isBlank() || !item.diagrams.isEmpty()) return true;
        return false;
    }

    private void acknowledgeDisplayedAnswers() {
        if (reader == null || answerStore == null) return;
        AnswerBundle shown = reader.bundle();
        AnswerStore.Saved saved = loadSavedAnswers();
        if (saved == null || saved.closed || saved.bundle.revision < shown.revision
                || !saved.bundle.sessionId.equals(shown.sessionId) || !saved.bundle.inputDigest.equals(shown.inputDigest)) return;
        try {
            long session = Long.parseLong(shown.sessionId);
            if (session <= 0) return;
            acknowledgedRevision = acknowledgedSession == session ? Math.max(acknowledgedRevision, shown.revision) : shown.revision;
            acknowledgedSession = session;
        } catch (NumberFormatException ignored) { }
    }

    private void retryAcknowledgement() {
        if (deviceId != null && acknowledgedSession == powerSession && acknowledgedRevision >= 0)
            transmitState(powerGeneration, powerSequence, powerPhase, powerSession, displayRequest, acknowledgedRevision);
    }

    private void cancelDisplayIdle() {
        displayIdleToken++;
        if (displayIdle != null) main.removeCallbacks(displayIdle);
        displayIdle = null;
    }

    private void keepDisplayActive() {
        cancelDisplayIdle();
        if (idleAsleep) displaySleep.wake(this);
        idleAsleep = false;
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    }

    private void enterIdleDisplay(String phase, long session) {
        boolean entering = !phase.equals(powerPhase) || session != powerSession;
        if (entering || (displayIdle == null && !idleAsleep)) {
            keepDisplayActive();
            scheduleDisplayIdle();
        }
        notifyPhase(phase, session, idleAsleep ? "sleep" : "wake");
    }

    private void scheduleDisplayIdle() {
        cancelDisplayIdle();
        long token = displayIdleToken;
        long generation = powerGeneration;
        displayIdle = () -> {
            if (token != displayIdleToken || generation != powerGeneration || sessionClosed || writingDone
                    || isFinishing() || isDestroyed() || displayProtected()) return;
            displayIdle = null;
            idleAsleep = true;
            displaySleep.sleep(this);
            notifyPhase(List.of("chooser", "analyzing", "waiting").contains(powerPhase) ? powerPhase : "waiting", activeSession(), "sleep");
        };
        main.postDelayed(displayIdle, DISPLAY_IDLE_MILLIS);
    }

    private long activeSession() {
        if (reader != null) {
            try { return Long.parseLong(reader.bundle().sessionId); } catch (NumberFormatException ignored) { }
        }
        return powerSession > 0 ? powerSession : controller == null ? 0 : controller.sessionId();
    }

    private void beginPowerGeneration() {
        cancelDisplayIdle();
        idleAsleep = false;
        try { powerGeneration = new PowerState(getPreferences(MODE_PRIVATE)).begin(powerGeneration).generation; }
        catch (IOException error) { sessionClosed = true; displaySleep.sleep(this); finish(); return; }
        powerSequence = 0;
        powerSession = 0;
        acknowledgedSession = 0;
        acknowledgedRevision = -1;
        powerPhase = "capturing";
        writingDone = false;
        awaitingAnswers = false;
    }

    private boolean acceptsWearEntry(Intent intent) {
        PowerState.Snapshot current = new PowerState(getPreferences(MODE_PRIVATE)).load();
        return intent != null && intent.getBooleanExtra("wear_origin", false)
                && intent.getBooleanExtra("chooser", false) && intent.getLongExtra("wear_generation", -1) == current.generation
                && "chooser".equals(current.entry) && "chooser".equals(current.phase)
                && current.session == 0 && "wake".equals(current.display);
    }

    private boolean acceptsWake(Intent intent) {
        return intent != null && intent.hasExtra(WAKE_SESSION) && !sessionClosed && !writingDone
                && isCurrentPowerGeneration(powerGeneration)
                && List.of("analyzing", "waiting", "reading").contains(powerPhase) && powerSession > 0
                && intent.getIntExtra(WAKE_SESSION, 0) == powerSession
                && intent.getLongExtra(WAKE_GENERATION, -1) == powerGeneration;
    }

    private boolean isCurrentPowerGeneration(long generation) {
        return generation == powerGeneration && new PowerState(getPreferences(MODE_PRIVATE)).load().generation == generation;
    }

    private void receiveWake(Intent intent) {
        if (!acceptsWake(intent)) return;
        long revision = intent.getLongExtra("answer_revision", 0);
        if (answersFetchedForSession == powerSession && revision <= answersFetchedRevision) {
            retryAcknowledgement();
            return;
        }
        // Keep the phone's snapshot advisory: only this still-active run may turn the display on.
        setTurnScreenOn(true);
        choosingSession = false;
        answersFetchedForSession = powerSession;
        fetchAnswers(powerSession, revision);
    }

    private void notifyPhase(String phase, long session) {
        notifyPhase(phase, session, phase.equals("capturing") || phase.equals("reading") ? "wake" : null);
    }

    private void notifyPhase(String phase, long session, String request) {
        Long ack = session > 0 && acknowledgedSession == session && acknowledgedRevision >= 0 ? acknowledgedRevision : null;
        if (phase.equals(powerPhase) && session == powerSession && powerSequence > 0
                && java.util.Objects.equals(displayRequest, request)
                && java.util.Objects.equals(new PowerState(getPreferences(MODE_PRIVATE)).load().answerRevision, ack)) return;
        displayRequest = request;
        powerPhase = phase;
        powerSession = session;
        long gen = powerGeneration;
        long seq;
        try {
            PowerState.Snapshot next = new PowerState(getPreferences(MODE_PRIVATE)).publish(gen, session, phase, request, ack);
            if (next == null) return;
            seq = powerSequence = next.sequence;
        } catch (IOException error) { Log.w(TAG, "display state not saved"); return; }
        if (deviceId != null) transmitState(gen, seq, phase, session, request, ack);
    }

    private void transmitState(long gen, long seq, String phase, long session, String request, Long ack) {
        try { stateExecutor.execute(() -> {
            if (!isCurrentPowerGeneration(gen) || seq != powerSequence) return;
            PowerManager power = (PowerManager)getSystemService(POWER_SERVICE);
            PowerManager.WakeLock stateLock = power == null ? null
                    : power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "docscan:state-notify");
            try {
                if (stateLock != null) stateLock.acquire(5_000);
                DocScanApi api = controller.api();
                if (api == null) throw new IOException("server not configured");
                api.glassesState(deviceId, session > 0 ? session : null, gen, seq, phase, request, null, ack);
            } catch (Exception error) {
                Log.w(TAG, "state notification paused: " + error.getClass().getSimpleName());
                main.postDelayed(() -> {
                    if (!isDestroyed() && isCurrentPowerGeneration(gen) && seq == powerSequence) transmitState(gen, seq, phase, session, request, ack);
                }, 5000);
            } finally {
                if (stateLock != null && stateLock.isHeld()) stateLock.release();
            }
        }); } catch (java.util.concurrent.RejectedExecutionException ignored) { }
    }

    /** Mute output streams only. Recording deliberately never changes microphone mute. */
    private void muteOutput() {
        AudioManager audio = (AudioManager) getSystemService(AUDIO_SERVICE);
        if (audio == null) return;
        for (int stream : new int[]{AudioManager.STREAM_SYSTEM, AudioManager.STREAM_MUSIC,
                AudioManager.STREAM_RING, AudioManager.STREAM_NOTIFICATION, AudioManager.STREAM_ALARM,
                AudioManager.STREAM_VOICE_CALL, AudioManager.STREAM_DTMF}) {
            try { audio.setStreamVolume(stream, 0, 0); }
            catch (SecurityException denied) { Log.w(TAG, "output mute refused for stream=" + stream); }
        }
        try { Settings.System.putInt(getContentResolver(), Settings.System.SOUND_EFFECTS_ENABLED, 0); }
        catch (SecurityException denied) { Log.w(TAG, "touch sound setting refused"); }
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
    private boolean persistAnswerPosition(boolean closed) {
        return persistAnswerPosition(closed, closed);
    }

    private boolean persistAnswerPosition(boolean closed, boolean wait) {
        if (reader == null) {
            return true;
        }
        AnswerBundle bundle = reader.bundle();
        String questionId = reader.current().questionId;
        int offset = reader.offset();
        Future<Boolean> queued = answerPersistExecutor.submit(
                () -> writeAnswerPosition(bundle, questionId, offset, closed));
        if (wait) {
            try {
                return queued.get();
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
                Log.w(TAG, "answer position save interrupted", error);
                return false;
            } catch (ExecutionException error) {
                Log.w(TAG, "answer position not saved", error);
                return false;
            }
        }
        return true; // ordinary position accepted by the queue, not yet durable
    }

    private boolean writeAnswerPosition(
            AnswerBundle bundle, String questionId, int offset, boolean closed) {
        try {
            answerStore.save(bundle, questionId, offset, closed);
            return true;
        } catch (IOException error) {
            Log.w(TAG, "answer position not saved", error);
            return false;
        }
    }
}
