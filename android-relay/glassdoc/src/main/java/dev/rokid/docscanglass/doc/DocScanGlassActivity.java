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
import dev.rokid.docscanrelay.ClipInbox;
import dev.rokid.docscanrelay.DocScanApi;
import dev.rokid.docscanrelay.DocScanController;
import dev.rokid.docscanrelay.CaptureInspectionOrigin;
import dev.rokid.docscanrelay.JapaneseOcr;
import dev.rokid.docscanrelay.RelayState;
import dev.rokid.docscanrelay.UseLog;
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
    /** Saved pixels kept dark below and above every screen, from {@code --ei}; they fit the panel to the wearer. */
    private static final String EXTRA_BOTTOM_MARGIN = "bottom_margin";
    private static final String EXTRA_TOP_MARGIN = "top_margin";
    /** Both at this limit still leave 160 px of the measured 640 px panel. */
    static final int MAX_MARGIN = 240;
    /** The wearer does not see the lowest part of the panel; used until a margin has been saved. */
    static final int DEFAULT_BOTTOM_MARGIN = 125;
    /**
     * How a page is taken, from {@code --es capture clip|still}, saved: {@code clip} records a few seconds of the
     * page for the phone to add together, in ordinary written reading only. Stills until the desk checks of the
     * clip route have passed.
     */
    private static final String EXTRA_CAPTURE = "capture";
    /**
     * Saved from {@code --ef far_share}: turns on ClipCamera's "paper too far" mark with this provisional limit.
     * Off until one is saved, and after {@code --ef far_share 0}: the rule does not measure distance, and worn on
     * 2026-11-16 the mark stood for 38 of 67 s while the distance was fine (register 2-24).
     */
    private static final String EXTRA_FAR_SHARE = "far_share";
    /**
     * Saved from {@code --ei long_above}: the gain, in hundredths, that a 30 ms clip may need before ClipCamera takes
     * 60 ms instead. Until one is saved, and after {@code --ei long_above 0}, no clip takes 60 ms: see longExposure.
     */
    private static final String EXTRA_LONG_ABOVE = "long_above";
    /**
     * From {@code --ei clip_frames}, for this launch only and never saved: how many still frames a clip gathers before
     * it ends, between the route's own 60 and 250. For desk checks: a desk holds still, so every clip ends at 60 frames
     * (about 36 MB), and the clips a worn head makes, which run their ten seconds (137 to 156 MB), could not be made
     * there. At 250 a clip runs its ten seconds and is still kept (two thirds of 250 are reached).
     */
    private static final String EXTRA_CLIP_FRAMES = "clip_frames";
    static int clipFrames(Intent intent, int usual) {
        return Math.max(usual, Math.min(intent == null ? usual : intent.getIntExtra(EXTRA_CLIP_FRAMES, usual), 250));
    }
    /**
     * A new reading is not started with less than this free where its pages and clips are kept. Clips stay on the
     * glasses until the phone holds them, one that ran its ten seconds is up to 156 MB, and nothing checked the space:
     * a full store ended the capture as a camera whose state is not known. A reading taken up again is not refused:
     * sending what it holds is what frees the space. Nor is one refused when the system cannot tell
     * ({@code File.getUsableSpace} then says 0): not knowing is no reason to turn the wearer away at the venue, where
     * nobody can do anything about it, and a store that is really full ends the capture as it did before.
     */
    static final long MIN_FREE_BYTES_FOR_READING = 700L << 20;
    static boolean roomForReading(long usableBytes) { return usableBytes <= 0 || usableBytes >= MIN_FREE_BYTES_FOR_READING; }
    /** What can still be written where the readings and the clips' inbox are kept; replaced in tests. */
    java.util.function.LongSupplier freeBytes = () -> getFilesDir().getUsableSpace();
    // For the use log, the main thread: when the wake that asks for answers came, and from when the answers now
    // being handed to the reader are counted (0: nothing to write).
    private long wakeAtMillis, answersAskedAtMillis;
    /** Diagnostic override for this launch only; normal launches always capture automatically. */
    private static final String EXTRA_MANUAL = "manual";
    private static final String EXTRA_ZSL_EVALUATION = "zsl_evaluation";
    private static final String EXTRA_VIDEO_EVALUATION = "video_evaluation";
    private static final String EXTRA_VIDEO_TRANSFER_EVALUATION = "video_transfer_evaluation";
    private static final String EXTRA_PAPER_GEOMETRY_EVALUATION = "paper_geometry_evaluation"; // AGENT_APPROVED=1
    private static final String EXTRA_NATIVE_SELECTION = "native_selection";
    /** This launch only: after each ordinary still, the same scene again with one camera setting changed per still. */
    private static final String EXTRA_SETTINGS_BRACKET = "settings_bracket";
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
    /** When the double tap that ends a capture was passed on, on the gestures' own clock; see onAction. */
    private long endAskedAtMillis = -1;
    /** Screens of the app between their creation and their destruction; a confirmed wear asks (PowerState.wearEntry). */
    private static final java.util.concurrent.atomic.AtomicInteger LIVING = new java.util.concurrent.atomic.AtomicInteger();
    static boolean screenAlive() { return LIVING.get() > 0; }
    private static final long END_GRACE_MILLIS = 5_000;
    private volatile boolean sessionClosed;
    private final Handler main = new Handler(Looper.getMainLooper());
    private static final long DISPLAY_IDLE_MILLIS = 5_000;
    /**
     * The chooser is read and chosen from, so it stays longer than a waiting screen. In real use on 2026-11-13 it
     * appeared when the glasses were put on and was gone five seconds later, before its six lines could be read; the
     * next double tap then only brought the display back, and it was set to thirty seconds. Worn on 2026-11-17
     * the operator set it to ten. A tap still turns it off at once.
     */
    private static final long CHOOSER_IDLE_MILLIS = 10_000;
    /** Set by a new Intent until the resume that follows it: that resume was not the wearer's touch. */
    private boolean intentBeforeResume;
    private boolean rearmExitOnFocus;
    private Runnable displayIdle;
    private long displayIdleToken;
    private boolean idleAsleep;
    private boolean captureDisplayActive;
    private String displayRequest;
    private RelayState displayedState;

    private HandlerThread cameraThread;
    /** The camera in use: the still camera until an ordinary written session starts with {@code capture=clip} saved. */
    private PageCamera camera;
    private GlassCamera stillCamera;
    private ClipCamera clipCamera;
    private ClipInbox clipInbox;
    /** No evaluation launch: only then may clips replace stills. */
    private boolean ordinaryCamera;
    private volatile boolean evaluationRestarting;
    private volatile boolean comparisonTransferEnabled;
    private volatile CaptureVideoTransfer videoTransfer;
    private GlassesCaptureSurface surface;
    private JapaneseOcr ocr;
    private DocScanController controller;
    private HudView hud;
    private AnswerView answers;
    private AnswerStore answerStore;
    private ConnectionSettings connectionSettings;
    // Reads and per-gesture writes share one queue so large saved answers
    // stay off the UI thread and position writes commit in gesture order.
    private final ExecutorService answerPersistExecutor = Executors.newSingleThreadExecutor(
            runnable -> {
                Thread thread = new Thread(runnable, "answer-persist");
                thread.setDaemon(true);
                return thread;
            });
    private final Object answerPositionLock = new Object();
    // Only an unstarted cursor write can absorb later moves of this exact bundle.
    // Every read, resume and waited/terminal save cuts this pending tail.
    private PendingAnswerPosition pendingAnswerPosition;
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
    private AnswerBundle acknowledgementPending;
    private long savedReadingLoadGeneration = -1;
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
        LIVING.incrementAndGet();
        // Beside head-motion.bin, where adb can read it: logcat alone was lost at a restart of the glasses, twice.
        File shared = getExternalFilesDir(null);
        UseLog.open(shared != null ? shared : getFilesDir());
        UseLog.i(TAG, "start version=" + BuildConfig.VERSION_NAME + " free_mb=" + UseLog.freeMegabytes(getFilesDir())
                + " ext_free_mb=" + UseLog.freeMegabytes(shared));
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
            if (!displaySleep.wake(this)) Log.w(TAG, "wear display wake request refused");
            setIntent(new Intent(this, DocScanGlassActivity.class).putExtra("chooser", true));
        }
        boolean restoringWake = acceptsWake(getIntent());
        if (getIntent() != null && getIntent().hasExtra(WAKE_SESSION) && !restoringWake) {
            UseLog.i(TAG, "wake revision=" + getIntent().getLongExtra("answer_revision", -1) + " accepted=false");
            UseLog.i(TAG, "stale answer wake rejected before opening a screen");
            displaySleep.sleep(this);
            finish();
            return;
        }
        if (!restoringWake) beginPowerGeneration();
        // Hold only the active app window; the operator's display timeout stays intact.
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        hud = new HudView(this);
        setContentView(hud);
        placeScreens();
        answerStore = new AnswerStore(getFilesDir());
        connectionSettings = new ConnectionSettings(new File(getNoBackupFilesDir(), "connection.bin"));
        choosingSession = true;
        resolvedOfflineAnswersAtStartup = true;
        hud.calibrateGuide(getPreferences(MODE_PRIVATE).getFloat(
                EXTRA_GUIDE, (float) FramingGuide.UNCALIBRATED_FRACTION));
        hud.showSpreadGuide(getPreferences(MODE_PRIVATE).getBoolean(EXTRA_SPREAD, true));

        final GlassCamera.Mode cameraMode;
        final CaptureVideoRecording.Options recordingOptions;
        final boolean paperGeometry;
        final boolean nativeSelection;
        final boolean settingsBracket;
        try {
            cameraMode = evaluationMode(getIntent());
            recordingOptions = videoOptions(getIntent(), deviceId, powerGeneration);
            comparisonTransferEnabled = videoTransferEvaluation(getIntent());
            paperGeometry = paperGeometryEvaluation(getIntent());
            nativeSelection = nativeSelection(getIntent());
            settingsBracket = settingsBracket(getIntent());
        } catch (IllegalArgumentException invalid) {
            hud.showLines(List.of("撮影評価を開始できません", invalid.getMessage(), ""));
            Log.w(TAG, "explicit camera evaluation rejected: " + invalid.getMessage());
            finish(); return;
        }
        cameraThread = new HandlerThread("glass-camera");
        cameraThread.start();
        stillCamera = new GlassCamera(this, new Handler(cameraThread.getLooper()), cameraCallback(),
                cameraMode, null, null, recordingOptions, null, paperGeometry);
        stillCamera.nativeSelection(nativeSelection);
        stillCamera.settingsBracket(settingsBracket);
        camera = stillCamera;
        ordinaryCamera = cameraMode == GlassCamera.Mode.NATIVE_STILL && !paperGeometry && !nativeSelection && !settingsBracket;
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
        controller.setCaptureInspectionContextProvider(this::captureInspectionContext);

        if (comparisonTransferEnabled) videoTransfer=new CaptureVideoTransfer(getFilesDir(),this::comparisonVideoSnapshot,this);

        applyIntent(getIntent(), true);
        startupSelection = mixedMode ? 1 : listeningMode ? 2 : 0;
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
            loadStartupAnswers();
        }
        if (!hasCamera()) {
            requestPermissions(
                    new String[] {Manifest.permission.CAMERA}, CAMERA_PERMISSION_REQUEST);
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        intentBeforeResume = true;
        if (intent != null && intent.getBooleanExtra("wear_origin", false)) {
            if (!acceptsWearEntry(intent)) return;
            if (!displaySleep.wake(this)) Log.w(TAG, "wear display wake request refused");
            intent = new Intent(this, DocScanGlassActivity.class).putExtra("chooser", true);
        }
        if (intent != null && intent.hasExtra(WAKE_SESSION)) {
            setIntent(intent); muteOutput(); receiveWake(intent); return;
        }
        if (intent != null && (intent.hasExtra(EXTRA_VIDEO_EVALUATION) || intent.hasExtra(EXTRA_ZSL_EVALUATION)
                || intent.hasExtra(EXTRA_VIDEO_TRANSFER_EVALUATION) || intent.hasExtra(EXTRA_PAPER_GEOMETRY_EVALUATION)
                || intent.hasExtra(EXTRA_NATIVE_SELECTION) || intent.hasExtra(EXTRA_SETTINGS_BRACKET)
                || (still() != null && (still().paperGeometryEvaluation() || still().settingsBracket())))) {
            if (evaluationRestarting) return;
            try { evaluationMode(intent); videoOptions(intent, deviceId == null ? "evaluation" : deviceId, powerGeneration); }
            catch (IllegalArgumentException invalid) {
                Log.w(TAG, "explicit camera evaluation rejected: " + invalid.getMessage());
                if (hud != null) hud.showLines(List.of("撮影評価を開始できません", invalid.getMessage(), ""));
                return;
            }
            evaluationRestarting = true;
            setIntent(intent);
            stopCaptureHardware();
            Runnable restart = () -> main.post(() -> { if (!isFinishing() && !isDestroyed()) recreate(); });
            if (camera != null) camera.close(restart); else restart.run();
            return;
        }
        comparisonTransferEnabled = false;
        if (videoTransfer != null) { videoTransfer.close(); videoTransfer=null; }
        setIntent(intent);
        muteOutput();
        if (intent != null && intent.getBooleanExtra("chooser", false)) {
            stopCaptureHardware();
            persistAnswerPosition(false);
            setIntent(new Intent(this, DocScanGlassActivity.class).putExtra("chooser", true));
            recreate();
            return;
        }
        applyIntent(intent, false);
    }

    /** The chooser, capture and answers all live in the content frame, so one padding moves them together. */
    private void placeScreens() {
        android.view.View content = findViewById(android.R.id.content);
        content.setBackgroundColor(android.graphics.Color.BLACK); // black draws nothing on the glasses
        content.setPadding(0, getPreferences(MODE_PRIVATE).getInt(EXTRA_TOP_MARGIN, 0),
                0, getPreferences(MODE_PRIVATE).getInt(EXTRA_BOTTOM_MARGIN, DEFAULT_BOTTOM_MARGIN));
    }

    static String captureOption(android.content.SharedPreferences saved) {
        return "clip".equals(saved.getString(EXTRA_CAPTURE, "still")) ? "clip" : "still";
    }

    /** Clips only where nothing else depends on the still camera: mixed English, listening and every evaluation keep it. */
    static boolean clipRoute(String capture, boolean ordinaryCamera, boolean mixed, boolean listening) {
        return "clip".equals(capture) && ordinaryCamera && !mixed && !listening;
    }

    /** The still camera when it is the one in use: only it has the evaluation launches. */
    private GlassCamera still() {
        return camera instanceof GlassCamera ? (GlassCamera) camera : null;
    }

    /**
     * The session's kind is chosen on the chooser, after the cameras and the surface were built in onCreate, so the
     * camera is chosen here, just before the session starts. Neither camera has been opened by then.
     */
    private void chooseCamera() {
        if (stillCamera == null || cameraThread == null) return;
        boolean clips = clipRoute(captureOption(getPreferences(MODE_PRIVATE)), ordinaryCamera, mixedMode, listeningMode);
        if (clips && clipCamera == null) {
            clipInbox = new ClipInbox(new File(getFilesDir(), "clip-inbox"));
            ClipCamera.Options options = new ClipCamera.Options();
            options.rotationDegrees = MEASURED_ROTATION_DEGREES;
            options.targetFrames = clipFrames(getIntent(), options.targetFrames);
            options.farShare = getPreferences(MODE_PRIVATE).getFloat(EXTRA_FAR_SHARE, options.farShare);
            options.longExposureNanos = longExposure(getPreferences(MODE_PRIVATE), options.longExposureNanos);
            options.longAboveBoost = getPreferences(MODE_PRIVATE).getInt(EXTRA_LONG_ABOVE, options.longAboveBoost);
            clipCamera = new ClipCamera(this, new Handler(cameraThread.getLooper()), cameraCallback(), clipInbox,
                    new ClipEncoder.Hardware(), options);
            clipCamera.marks(surface);
        }
        PageCamera chosen = clips ? clipCamera : stillCamera;
        if (chosen != camera) {
            camera.pausePreview();
            camera = chosen;
            surface.camera(chosen);
        }
        controller.setClipInbox(clips ? clipInbox : null);
        UseLog.i(TAG, "capture=" + (clips ? "clip" : "still"));
    }

    /**
     * The long exposure a clip may take in a dark scene: none until a gain was saved with {@code --ei long_above}.
     * On a worn head 6 and 1 of some 133 frames were still enough at 60 ms, where four in ten were at 30 ms (M-31):
     * the long exposure read a dark page well only from glasses lying still (M-30).
     */
    static long longExposure(android.content.SharedPreferences saved, long whenSaved) {
        return saved.contains(EXTRA_LONG_ABOVE) ? whenSaved : 0;
    }

    private void applyIntent(Intent intent, boolean starting) {
        if (intent != null && intent.hasExtra(EXTRA_CAPTURE)) {
            getPreferences(MODE_PRIVATE).edit().putString(EXTRA_CAPTURE,
                    "clip".equals(intent.getStringExtra(EXTRA_CAPTURE)) ? "clip" : "still").apply();
        }
        if (intent != null && intent.getExtras() != null && intent.getExtras().get(EXTRA_FAR_SHARE) instanceof Float) {
            float share = intent.getFloatExtra(EXTRA_FAR_SHARE, 0f);
            if (Float.isFinite(share)) {
                getPreferences(MODE_PRIVATE).edit().putFloat(EXTRA_FAR_SHARE, Math.max(0f, Math.min(1f, share))).apply();
            }
        }
        if (intent != null && intent.getExtras() != null && intent.getExtras().get(EXTRA_LONG_ABOVE) instanceof Integer) {
            int above = intent.getIntExtra(EXTRA_LONG_ABOVE, 0);
            if (above <= 0) {
                getPreferences(MODE_PRIVATE).edit().remove(EXTRA_LONG_ABOVE).apply();
            } else {
                getPreferences(MODE_PRIVATE).edit().putInt(EXTRA_LONG_ABOVE, Math.max(ClipCamera.MIN_BOOST, above)).apply();
            }
        }
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
        for (String margin : new String[]{EXTRA_TOP_MARGIN, EXTRA_BOTTOM_MARGIN}) {
            if (intent == null || intent.getExtras() == null || !(intent.getExtras().get(margin) instanceof Integer)) continue;
            getPreferences(MODE_PRIVATE).edit().putInt(margin,
                    Math.max(0, Math.min(MAX_MARGIN, intent.getIntExtra(margin, 0)))).apply();
            placeScreens();
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
            UseLog.i(TAG, "exit confirmed");
            displaySleep.sleep(this);
            startActivity(new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            finish();
    }

    @Override protected void onResume() {
        super.onResume();
        muteOutput();
        boolean live = !(sessionClosed || writingDone || isFinishing() || isDestroyed()
                || !isCurrentPowerGeneration(powerGeneration));
        boolean resumedByIntent = intentBeforeResume;
        intentBeforeResume = false;
        if (!live) {
            displaySleep.sleep(this);
            // After the writing is done the display is off, and the touch that wakes a sleeping display never reaches
            // the app: "two double taps within three seconds" took three on the glasses (route check, 2026-11-13).
            // This resume is that waking touch, so it counts as the first of the two.
            // A resume that a notification brought (a late answer wake from the phone) is not a touch and arms nothing.
            if (writingDone && !resumedByIntent && !sessionClosed && !isFinishing() && !isDestroyed()) {
                backExit.reset();
                backExit.onBack(SystemClock.elapsedRealtime());
                rearmExitOnFocus = true; // the focus comes back after this resume and clears a half-made exit
            }
        } else if (idleAsleep) {
            // The system display is on again. A touch on a sleeping display is consumed by the wake and never reaches
            // this app: the Activity is only restarted and resumed (glasses, 2026-11-13, events written to the
            // touchpad's own input device). Until then the flag stayed set after such a wake and the next tap was
            // spent as "turn the display back on", so the display-off worked once only. This resume is the notice.
            keepDisplayActive();
            if (!displayProtected()) {
                notifyPhase(choosingSession ? "chooser" : awaitingAnswers ? "analyzing" : "waiting", activeSession(), "wake");
                scheduleDisplayIdle();
            }
            if (choosingSession) askRoutes(); // the chooser is in view again without a gesture: a showing like any other
        } else getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
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
        LIVING.decrementAndGet();
        sessionClosed = true;
        if (videoTransfer != null) videoTransfer.close();
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
        // The video evaluation and the clip camera both close in steps on the camera's thread (the clip camera only
        // after its session is idle), so that thread is let go by their own last step.
        boolean closesInSteps = (still() != null && still().videoEvaluation()) || camera instanceof ClipCamera;
        if (closesInSteps) camera.close(() -> { if (cameraThread != null) cameraThread.quitSafely(); });
        else if (camera != null) camera.close();
        if (ocr != null) ocr.close();
        if (!closesInSteps && cameraThread != null) cameraThread.quitSafely();
        stateExecutor.shutdown();
        synchronized (answerPositionLock) {
            pendingAnswerPosition = null;
            answerPersistExecutor.shutdown();
        }
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
        if (hasFocus && rearmExitOnFocus && writingDone && !sessionClosed) backExit.onBack(SystemClock.elapsedRealtime());
        if (hasFocus) rearmExitOnFocus = false;
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
        // Every gesture, in every build: the "input" line of normalize() is a debuggable build's alone, so a use left no
        // trace of when the wearer tapped, and "from the double tap to the answers" had no beginning.
        UseLog.i(TAG, "gesture kind=" + action + " phase=" + screen()
                + " state=" + (controller == null ? "-" : controller.getState()) + " asleep=" + idleAsleep
                + " paused=" + (controller != null && controller.isCapturePaused()));
        if (sessionClosed) return;
        muteOutput();
        boolean wasAsleep = idleAsleep;
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
        // The gesture that turns the display back on does nothing else, on every screen (operator, 2026-11-12).
        // Until 2026-11-13 only the chooser held to it: a waking tap also toggled the mixed recording and a waking
        // double tap armed the exit. The chooser redraws its choices below; a finished writing session stays asleep.
        if (wasAsleep && !choosingSession && !writingDone) {
            // The answers reach the glasses when the phone's watcher wakes them. Should that wake not come, the
            // gesture that brings a waiting display back asks once itself; only once the server has the booklet
            // (a question before that would be answered "not finished" and end the wait).
            if (!mixedMode && !listeningMode && reader == null && controller.getState() == RelayState.REVIEW) {
                long session = activeSession();
                if (session > 0) fetchAnswers(session);
            }
            return;
        }
        if (choosingSession) {
            if (startupStarting) return;
            // One rule on every screen (operator, 2026-11-12): a tap turns the display off or on, a swipe
            // moves, a double tap decides. The gesture that turns the display back on does nothing else.
            if (wasAsleep || startupNotice) { startupNotice = false; showStartupChoices(); return; }
            if (action == GlassesInputAction.SWIPE_FORWARD || action == GlassesInputAction.SWIPE_BACK) {
                int step = action == GlassesInputAction.SWIPE_FORWARD ? 1 : -1;
                int count = startupCaptures == null ? startupOptions().size() : startupCaptures.size() + 1;
                startupSelection = Math.floorMod(startupSelection + step, count);
                showStartupChoices();
            } else if (action == GlassesInputAction.SHORT_TAP) {
                sleepDisplayNow();
            } else if (action == GlassesInputAction.BACK) {
                startSelectedSession();
            }
            return;
        }
        if (reader != null) {
            // One tap clears the answers from view and the next gesture of any kind brings them back
            // (operator, 2026-11-12). Mixed English keeps its tap for the recording.
            if (answersHidden) { showAnswers(true); return; }
            if (action == GlassesInputAction.SHORT_TAP) {
                if (mixedMode) toggleAudio(); else showAnswers(false);
                return;
            }
            if (action == GlassesInputAction.BACK) {
                if (reader.screen() != AnswerReader.Screen.ANSWER) {
                    reader.back();
                    backExit.reset();
                    answers.refresh();
                } else {
                    if (startRetakeFromAnswers(elapsedMillis)) return;
                    boolean interim = reader.bundle().intermediate();
                    if (!closeAnswers(!interim)) return;
                    if (interim) {
                        backExit.reset();
                        awaitingAnswers = true;
                        enterIdleDisplay("waiting", activeSession());
                        hud.showLines(List.of("読解の記入終了", "音声答案を待っています", "タップで録音開始・終了"));
                        return;
                    }
                    markWritingDone();
                }
                return;
            }
            if (!reader.hasViewport()) return;
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
        if (action == GlassesInputAction.BACK && retakeAskedAtMillis >= 0 && elapsedMillis >= retakeAskedAtMillis
                && elapsedMillis - retakeAskedAtMillis < RETAKE_GRACE_MILLIS) return;
        if (mixedMode) {
            boolean swipe = action == GlassesInputAction.SWIPE_FORWARD || action == GlassesInputAction.SWIPE_BACK;
            if (awaitingAnswers && swipe) {
                openSavedReadingAnswers();
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
        if (action == GlassesInputAction.BACK && surface != null && !controller.isCapturePaused()
                && controller.getState() == RelayState.CAPTURE_REVIEW) {
            surface.showCaptureEndRequested();
        }
        // The page being taken comes in first (a clip up to ten seconds, then its review): said at once, or the
        // wearer double-taps again and those taps land on the waiting screen, where two of them leave the app.
        if (action == GlassesInputAction.BACK && !mixedMode && !listeningMode && !controller.isCapturePaused()
                && controller.getState() == RelayState.CAPTURING) {
            hud.showLines(List.of("終了待ち", "", ""));
        }
        if (listeningMode && !mixedMode && action == GlassesInputAction.BACK && (!awaitingAnswers || !audioStopRequested)) {
            boolean stopAudio = captureEndRequested || controller.getState() == RelayState.LISTENING;
            captureEndRequested = true;
            controller.onGlassesAction(action, elapsedMillis);
            if (stopAudio) finishAudio();
            return;
        }
        // After the end nothing is being captured, whether the display says that it waits or that a fetch failed:
        // no gesture reaches the capture controller from here. A forward swipe on a failed fetch's message used to
        // arrive there as a tap and start a new document, leaving the reading whose answers were on their way.
        RelayState controllerState = controller.getState();
        boolean afterEnd = !mixedMode && !listeningMode && reader == null && (awaitingAnswers
                || controllerState == RelayState.REVIEW || controllerState == RelayState.FINALIZING
                || controllerState == RelayState.UPLOADING);
        if (afterEnd && action == GlassesInputAction.BACK && endAskedAtMillis >= 0 && elapsedMillis >= endAskedAtMillis
                && elapsedMillis - endAskedAtMillis < END_GRACE_MILLIS) {
            // A double tap made again right after the end is that end: the first got no sign for seconds, and two
            // more within three seconds would leave the app (the operator's booklet of 2026-11-17 10:11).
            backExit.reset();
            return;
        }
        if ((awaitingAnswers || afterEnd) && action == GlassesInputAction.BACK) {
            if (backExit.onBack(elapsedMillis) == BackExitPolicy.Decision.EXIT) exitSession();
            else {
                displaySleep.wake(this);
                hud.showLines(List.of("もう一度ダブルタップで終了", "保存した資料は保持します", "結果を待っています"));
            }
            return;
        }
        if (afterEnd) {
            // Waiting for the answers there is nothing to capture: a tap turns the display off as on every screen,
            // and no gesture reaches the capture controller (a forward swipe used to arrive there as a tap).
            if (action == GlassesInputAction.SHORT_TAP) sleepDisplayNow();
            return;
        }
        if (!mixedMode && !listeningMode) {
            // Operator, 2026-11-12: one tap pauses the display and the camera, the next resumes. The forward
            // swipe takes over what the tap did: a photo while waiting, a retake during the 3-second review.
            // The display follows in the turn of the tap. Worn on 2026-11-16 it stayed on until the page in hand
            // was saved, up to 13 s; the wearer tapped again and that was read as the double tap that ends the
            // capture. So behind a cleared display a double tap only brings it back, as a tap does.
            boolean paused = controller.isCapturePaused();
            if (action == GlassesInputAction.SHORT_TAP || (paused && action == GlassesInputAction.BACK)) {
                controller.toggleCapturePause();
                showOrBlank();
                return;
            }
            if (paused) return;
            if (action == GlassesInputAction.SWIPE_FORWARD) action = GlassesInputAction.SHORT_TAP;
            if (action == GlassesInputAction.BACK) endAskedAtMillis = elapsedMillis;
        }
        controller.onGlassesAction(action, elapsedMillis);
    }

    /** For the use log: the screen a gesture met, as this class tells them apart. */
    private String screen() {
        return sessionClosed ? "closed" : choosingSession ? "chooser" : reader != null ? "reading"
                : writingDone ? "writing_done" : awaitingAnswers ? "waiting" : "capturing";
    }

    private boolean answersHidden;

    private void showAnswers(boolean visible) {
        answersHidden = !visible;
        answers.setVisibility(visible ? android.view.View.VISIBLE : android.view.View.INVISIBLE);
    }

    private List<String> startupOptions() {
        List<String> options = new ArrayList<>(List.of("通常の読取", "合同英語（読解＋音声）", "リスニング"));
        if (controller.hasSavedWorkflow()) options.add("中断した読取");
        if (startupAnswers != null) options.add("前回の答案");
        options.add(EXIT_OPTION);
        return options;
    }

    private void showStartupChoices() {
        enterIdleDisplay("chooser", 0);
        if (startupCaptures != null) {
            startupSelection = Math.floorMod(startupSelection, startupCaptures.size() + 1);
            if (startupSelection == startupCaptures.size()) {
                hud.showLines(List.of("中断した読取", "▶ 一覧へ戻る", "スワイプ選択・ダブルタップ決定"));
                return;
            }
            DocScanController.SavedCapture selected = startupCaptures.get(startupSelection);
            hud.showLines(List.of("中断した読取 " + (startupSelection + 1) + "/" + startupCaptures.size(),
                    selected.label, "スワイプ選択・ダブルタップ再開"));
            return;
        }
        List<String> options = startupOptions();
        startupSelection = Math.floorMod(startupSelection, options.size());
        List<String> lines = new ArrayList<>();
        for (int index = 0; index < options.size(); index++) {
            lines.add((index == startupSelection ? "▶ " : "　 ") + options.get(index));
        }
        lines.add("スワイプ選択・ダブルタップ開始");
        hud.showChoices(lines, routeLine);
        askRoutes();
    }

    private static final String EXIT_OPTION = "アプリを終了";
    private boolean startupNotice;
    /** The chooser's line on the answer routes (RouteCheck); empty until a saved server has been asked. */
    private String routeLine = "";
    /** This showing of the chooser has had its one question; a showing ends when the display goes off. */
    private boolean routeAsked;
    private boolean routeInFlight;

    /**
     * Whether answers can come, asked of the saved server once for each showing of the chooser and never while a
     * reply is still on its way: one reading of what it keeps and, when that is missing or over thirty minutes old,
     * one check made now (RouteCheck.ask: two bounded requests at most, on a thread of their own, so neither the
     * state notices to the phone nor the start of a capture waits behind them).
     *
     * <p>The reply changes that one line and nothing else. It is not input: it does not bring a cleared display back
     * or restart the chooser's ten seconds, and nothing holds the processor for it. Once the chooser has been
     * left it is dropped. Without a saved server nothing is asked and the chooser has no such line.</p>
     */
    private void askRoutes() {
        if (routeAsked || routeInFlight) return;
        routeAsked = routeInFlight = true;
        controller.afterConfiguration(api -> main.post(() -> {
            if (api == null || !choosingSession) { routeInFlight = false; return; }
            showRoute(RouteCheck.ASKING);
            Thread asking = new Thread(() -> {
                String line = RouteCheck.ask(api, System.currentTimeMillis() / 1000);
                main.post(() -> {
                    routeInFlight = false;
                    if (choosingSession) showRoute(line);
                });
            }, "route-check");
            asking.setDaemon(true);
            asking.start();
        }));
    }

    private void showRoute(String line) {
        routeLine = line; // kept for the next drawing of the list
        hud.showRoute(line); // drawn only while the list is what is shown and the display is not cleared
    }

    /** The idle sleep, now: what the display does by itself after five seconds on these screens. */
    private void sleepDisplayNow() {
        scheduleDisplayIdle(); // its run blanks the view at once; the system's own sleep arrives through the phone
        Runnable sleep = displayIdle;
        if (sleep == null) return;
        main.removeCallbacks(sleep);
        sleep.run();
    }

    private void startSelectedSession() {
        if (startupCaptures != null && startupSelection >= startupCaptures.size()) {
            startupCaptures = null;
            startupSelection = 3;
            showStartupChoices();
            return;
        }
        String selected = startupCaptures == null ? startupOptions().get(startupSelection) : "中断記録";
        backExit.reset();
        if (EXIT_OPTION.equals(selected)) { exitSession(); return; }
        if ("中断した読取".equals(selected)) {
            startupCaptures = controller.savedCaptures();
            if (startupCaptures.isEmpty()) startupCaptures = null;
            startupSelection = 0;
            showStartupChoices();
            return;
        }
        if ("前回の答案".equals(selected)) {
            resumePreviousAnswers();
            return;
        }
        if (!hasCamera()) {
            requestPermissions(new String[]{Manifest.permission.CAMERA}, CAMERA_PERMISSION_REQUEST);
            return;
        }
        long usable = startupCaptures == null ? freeBytes.getAsLong() : Long.MAX_VALUE; // a reading taken up again is not refused
        if (!roomForReading(usable)) {
            UseLog.i(TAG, "start_refused free_mb=" + (usable >> 20));
            startupNotice = true; // the next gesture of any kind shows the choices again
            hud.showLines(List.of("空き容量不足 " + (usable >> 20) + "MB", "読取を開始できません", "操作すると一覧へ戻ります"));
            return;
        }
        viewingPreviousAnswers = false;
        startupStarting = true;
        if (startupCaptures != null) {
            DocScanController.SavedCapture saved = startupCaptures.get(startupSelection);
            listeningMode = saved.listening;
            mixedMode = saved.mixed;
            chooseCamera();
            controller.resumeLocalSession(saved.id, this::onStartupSelected);
        } else {
            mixedMode = startupSelection == 1;
            listeningMode = mixedMode || startupSelection == 2;
            String examType = mixedMode ? "mixed" : listeningMode ? "listening" : "written";
            getPreferences(MODE_PRIVATE).edit().putBoolean("listening", listeningMode).putString("exam_type", examType).apply();
            chooseCamera();
            controller.startLocalSession(examType, this::onStartupSelected);
        }
    }

    private void onStartupSelected(boolean accepted) {
        main.post(() -> {
            if (sessionClosed) return;
            startupStarting = false;
            if (!accepted) {
                startupNotice = true; // the next gesture of any kind shows the choices again
                hud.showLines(List.of("開始・再開できません", "接続先と保存記録を確認", "操作すると一覧へ戻ります"));
                return;
            }
            UseLog.i(TAG, "reading_start free_mb=" + (freeBytes.getAsLong() >> 20) + " resumed=" + (startupCaptures != null));
            beginPowerGeneration();
            choosingSession = false;
            startupAnswers = null;
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
            @Override public CaptureVideoTransfer.Origin comparisonVideoOrigin(CaptureVideoRecording.Options options) {
                return comparisonTransferEnabled ? CaptureVideoTransfer.origin(comparisonVideoSnapshot(),options) : null;
            }
            @Override public void onVideoSealed() {
                CaptureVideoTransfer transfer=videoTransfer; if (transfer != null) transfer.request();
            }
            @Override public void onCaptured(GlassCamera.Captured captured) {
                UseLog.i(TAG, "captured " + captured.width + "x" + captured.height
                        + " in " + captured.elapsedMillis + " ms");
                controller.onPhoto(captured.jpeg, captured.provenance, captured.associationResolved);
            }

            @Override
            public void onCaptured(byte[] jpeg, int width, int height, long elapsedMillis) {
                UseLog.i(TAG, "captured " + width + "x" + height + " in " + elapsedMillis + " ms");
                controller.onPhoto(jpeg);
            }

            @Override public void onPreview(android.graphics.Bitmap frame) {
                onPreview(frame, null);
            }

            @Override public void onPreview(android.graphics.Bitmap frame, PaperGeometry.Box proposal) {
                if (surface == null) frame.recycle();
                else surface.showLivePreview(frame, proposal);
            }

            @Override
            public void onCaptureFailed(String reason) {
                controller.onPhotoError("撮影に失敗しました: " + reason, null);
            }

            @Override
            public void onCaptureNotReady() {
                controller.onPhotoNotStarted();
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
            if (sessionClosed || writingDone || !isCurrentPowerGeneration(powerGeneration)) return;
            captureDisplayActive = running;
            if (running) {
                keepDisplayActive();
                notifyPhase("capturing", controller.sessionId(), "wake");
            } else if (!displayProtected()) enterIdleDisplay(awaitingAnswers ? "analyzing" : "waiting", activeSession());
        });
    }

    /**
     * The capture had ended and the display had gone dark for the wait: the phone found pages that are not whole,
     * and they are taken again before the booklet goes out. The capture's display comes back as at its start; the
     * controller then shows the pages' numbers and watches for the first of them.
     */
    @Override public void onRetakeRequested(List<Integer> pageNumbers) {
        main.post(() -> {
            if (sessionClosed || writingDone || !isCurrentPowerGeneration(powerGeneration)) return;
            UseLog.i(TAG, "retake_shown pages=" + pageNumbers);
            leaveAnswersForRetake();
            awaitingAnswers = false;
            endAskedAtMillis = -1; // a double tap from here on is a new end, not the echo of the one before
            backExit.reset();
            captureDisplayActive = true;
            if (!displaySleep.wake(this)) Log.w(TAG, "retake display wake request refused");
            keepDisplayActive();
            notifyPhase("capturing", controller.sessionId(), "wake");
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
        // The file keeps the diagnostic up to where the message of an exception could begin (UseLog.head).
        UseLog.file(TAG, state + ": " + UseLog.head(diagnostic));
        if (sessionClosed || writingDone || choosingSession) return;
        main.post(() -> {
            if (sessionClosed || writingDone || choosingSession) return;
            showOrBlank(); // the controller ends the wearer's pause itself when the capture fails
            if (displayedState == state) return;
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
                    hud.showLines(GlassesHudText.adapt(hudLines, mixedMode || listeningMode));
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
            hud.showLines(GlassesHudText.adapt(hudLines, mixedMode || listeningMode));
            // Waiting to shoot: nothing here needs reading, and the page is behind it. The numbers of the pages
            // to take again stay: they are what the wearer goes by.
            if ((state == RelayState.READY || state == RelayState.READING) && !controller.isRetaking()) hud.fadeSoon();
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
        long asked = wakeAtMillis != 0 ? wakeAtMillis : SystemClock.elapsedRealtime();
        wakeAtMillis = 0;
        new Thread(() -> {
            try {
            AnswerStore.Saved saved = loadSavedAnswers();
            if (saved != null && saved.bundle.sessionId.equals(Long.toString(sessionId))) {
                controller.answersSaved(sessionId); // saved before a kill could take the mark off: settled here
                // Saved state belongs to this session. CLOSED must stop here,
                // not fall through to a fresh fetch: a fetch would open a new
                // reader on the same session's answers, silently undoing the
                // close it was supposed to respect.
                if (!saved.closed && saved.bundle.revision >= requestedRevision) {
                    main.post(() -> {
                        answersAskedAtMillis = asked;
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
                long getting = SystemClock.elapsedRealtime();
                AnswerBundle bundle;
                try {
                    bundle = api.answerBundle(sessionId);
                } catch (Exception failed) {
                    UseLog.i(TAG, "answers_get ms=" + (SystemClock.elapsedRealtime() - getting) + " bytes=-1 revision=-1 result="
                            + UseLog.failure(failed));
                    throw failed;
                }
                UseLog.i(TAG, "answers_get ms=" + (SystemClock.elapsedRealtime() - getting) + " bytes=" + api.lastAnswerBundleBytes()
                        + " revision=" + bundle.revision + " result=ok");
                if (!isCurrentPowerGeneration(generationAtRequest) || writingDone || sessionClosed) return;
                if (bundle.revision < requestedRevision) throw new IOException("requested answer revision unavailable");
                answerFetchFailing = false;
                String question = bundle.items.get(0).questionId;
                int offset = 0;
                long saving = SystemClock.elapsedRealtime();
                if (saved != null && saved.bundle.sessionId.equals(bundle.sessionId)
                        && saved.bundle.inputDigest.equals(bundle.inputDigest)) {
                    AnswerReader validation = new AnswerReader(saved.bundle, true);
                    validation.restore(saved.questionId, saved.offset);
                    if (!validation.accept(bundle)) throw new IOException("answer identity changed");
                    question = validation.current().questionId;
                    offset = validation.offset();
                    answerStore.save(bundle, question, offset, false);
                } else answerStore.start(bundle);
                UseLog.i(TAG, "answers_saved ms=" + (SystemClock.elapsedRealtime() - saving));
                controller.answersSaved(sessionId); // from here 前回の答案 has them: the reading no longer waits
                String restoreQuestion = question;
                int restoreOffset = offset;
                main.post(() -> {
                    answersAskedAtMillis = asked;
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
                        else wakeAtMillis = 0; // a wake that came meanwhile asked for nothing newer
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

    private void loadStartupAnswers() {
        long generation = powerGeneration;
        queueAnswerPersistence(() -> {
            AnswerStore.Saved saved = loadSavedAnswers();
            main.post(() -> {
                if (!isCurrentPowerGeneration(generation) || sessionClosed || isFinishing() || isDestroyed()
                        || !choosingSession || startupStarting) return;
                startupAnswers = saved;
                showStartupChoices();
            });
        });
    }

    private void openSavedReadingAnswers() {
        long generation = powerGeneration;
        long session = activeSession();
        if (savedReadingLoadGeneration == generation) return;
        savedReadingLoadGeneration = generation;
        queueAnswerPersistence(() -> {
            AnswerStore.Saved saved = loadSavedAnswers();
            main.post(() -> {
                if (savedReadingLoadGeneration != generation) return;
                savedReadingLoadGeneration = -1;
                if (!isCurrentPowerGeneration(generation) || sessionClosed || writingDone
                        || isFinishing() || isDestroyed() || !awaitingAnswers || reader != null
                        || activeSession() != session) return;
                if (saved != null && !saved.closed && saved.bundle.sessionId.equals(Long.toString(session))) {
                    openAnswers(saved.bundle, saved.questionId, saved.offset);
                }
            });
        });
    }

    private void resumePreviousAnswers() {
        long generation = powerGeneration;
        startupStarting = true;
        queueAnswerPersistence(() -> {
            AnswerStore.Saved saved = null;
            try { saved = answerStore.resume(() -> isCurrentPowerGeneration(generation)
                    && !sessionClosed && !isFinishing() && !isDestroyed()); }
            catch (IOException error) { Log.w(TAG, "previous answers unavailable", error); }
            AnswerStore.Saved resumed = saved;
            main.post(() -> {
                if (!isCurrentPowerGeneration(generation) || sessionClosed || isFinishing() || isDestroyed()
                        || !choosingSession) return;
                startupStarting = false;
                if (resumed == null) {
                    hud.showLines(List.of("前回答案を開けません", "原本は保持しています", ""));
                    return;
                }
                beginPowerGeneration();
                choosingSession = false;
                startupAnswers = null;
                viewingPreviousAnswers = true;
                openAnswers(resumed.bundle, resumed.questionId, resumed.offset);
            });
        });
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
            answersAskedAtMillis = 0; // they are on the display already: nothing is drawn for this
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
            noteAnswersDrawn(answers);
            acknowledgeDisplayedAnswers();
            if (hasWrittenAnswers()) { keepDisplayActive(); notifyPhase("reading", activeSession()); }
            else enterIdleDisplay("waiting", activeSession());
            return;
        }
        answers = new AnswerView(this);
        // AnswerView supplies the actual font and viewport after its first layout.
        reader = new AnswerReader(bundle, true);
        reader.restore(questionId, offset);
        answers.bind(reader);
        AnswerReader openedReader = reader;
        answers.addOnLayoutChangeListener((view, left, top, right, bottom,
                                          oldLeft, oldTop, oldRight, oldBottom) -> {
            if (view != answers || reader != openedReader || writingDone || sessionClosed
                    || isFinishing() || isDestroyed() || !isCurrentPowerGeneration(powerGeneration)) return;
            acknowledgeDisplayedAnswers();
        });
        setContentView(answers);
        noteAnswersDrawn(answers);
        acknowledgeDisplayedAnswers();
        if (hasWrittenAnswers()) {
            keepDisplayActive();
            notifyPhase("reading", activeSession());
        } else enterIdleDisplay("waiting", activeSession());
    }

    /**
     * For the use log: one line once the answers handed over just now have been laid out and drawn, counted from the
     * wake that asked for them, or from the start of their fetch where no wake did. Answers opened from the chooser
     * write none.
     */
    private void noteAnswersDrawn(AnswerView view) {
        long asked = answersAskedAtMillis;
        answersAskedAtMillis = 0;
        if (asked == 0) return;
        view.getViewTreeObserver().addOnPreDrawListener(new android.view.ViewTreeObserver.OnPreDrawListener() {
            @Override public boolean onPreDraw() {
                view.getViewTreeObserver().removeOnPreDrawListener(this);
                // Laid out here; the post runs when this frame has been drawn.
                view.post(() -> UseLog.i(TAG, "answers_drawn ms=" + (SystemClock.elapsedRealtime() - asked)));
                return true;
            }
        });
    }

    /** A double tap made again this soon after the one that began a retake is that same double tap. */
    private static final long RETAKE_GRACE_MILLIS = 1500;
    private long retakeAskedAtMillis = -1;

    /**
     * The answers end with pages to take again (the bundle's {@code retake}: what only the reading could tell): a
     * double tap takes them, where it otherwise ends the writing (the operator, 2026-11-19). The answers stay saved;
     * the capture comes back with those pages' numbers (onRetakeRequested), and the booklet is read again with what
     * is taken. A second double tap before any page is taken leaves the retake and ends the writing (onRetakeLeft).
     * False when there is nothing to take again or this reading cannot take pages (answers opened from the chooser).
     */
    private boolean startRetakeFromAnswers(long elapsedMillis) {
        if (mixedMode || listeningMode || reader == null || controller == null) return false;
        if (retakeAskedAtMillis >= 0 && elapsedMillis >= retakeAskedAtMillis
                && elapsedMillis - retakeAskedAtMillis < RETAKE_GRACE_MILLIS) return true;
        List<Integer> indexes = new ArrayList<>();
        for (int number : reader.retakePages()) indexes.add(number - 1);
        if (indexes.isEmpty() || !controller.canRetakeAnswered(indexes)) return false;
        UseLog.i(TAG, "retake_from_answers pages=" + reader.retakePages());
        retakeAskedAtMillis = elapsedMillis;
        backExit.reset();
        controller.retakeAnswered(indexes);
        return true;
    }

    /** The reader leaves the display for a retake; its place is kept as well as it can be, the answers stay open. */
    private void leaveAnswersForRetake() {
        if (reader == null) return;
        persistAnswerPosition(false);
        reader = null;
        answersHidden = false;
        answers = null;
        setContentView(hud);
    }

    /** The wearer has finished writing: nothing more is shown for this reading, and the display sleeps. */
    private void markWritingDone() {
        writingDone = true;
        backExit.reset(); // the completion gesture never arms the exit window
        stopCaptureHardware();
        notifyPhase("writing_done", activeSession());
        awaitingAnswers = false;
        getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        hud.showLines(List.of("記入終了", "", ""));
        displaySleep.sleep(this);
    }

    /**
     * The retake begun from the answers was left by a double tap before any page of it was taken: that double tap
     * ends the writing, as it did on the answers before pages were listed there. The saved answers are closed first,
     * as the reader closes them.
     */
    @Override public void onRetakeLeft() {
        main.post(() -> {
            if (sessionClosed || writingDone || !isCurrentPowerGeneration(powerGeneration)) return;
            UseLog.i(TAG, "retake_left_ends_writing");
            retakeAskedAtMillis = -1;
            queueAnswerPersistence(() -> {
                try {
                    AnswerStore.Saved saved = loadSavedAnswers();
                    if (saved != null && !saved.closed) answerStore.save(saved.bundle, saved.questionId, saved.offset, true);
                } catch (Exception failed) {
                    Log.w(TAG, "answers could not be closed after a retake was left", failed);
                }
                main.post(() -> {
                    if (sessionClosed || writingDone || !isCurrentPowerGeneration(powerGeneration)) return;
                    markWritingDone();
                });
            });
        });
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
        if (reader != null && reader.hasViewport()) recordAcknowledgedRevision(reader.bundle());
        reader = null;
        answersHidden = false;
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
        if (sessionClosed || writingDone || isFinishing() || isDestroyed()
                || !isCurrentPowerGeneration(powerGeneration)) return;
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

    /**
     * Something final to read: an answer, a figure, or the reason an item has neither. Worn on 2026-11-17 a booklet
     * came back as nine reasons ("cannot be read") and no answer; counted as nothing to read, the reader went dark
     * five seconds after each touch. An item still being made is not something to read, and neither are the reasons
     * of a mixed reading that still waits for its recording: the recording goes on behind a sleeping screen.
     */
    private boolean hasWrittenAnswers() {
        if (reader == null) return false;
        boolean last = !reader.bundle().intermediate();
        for (AnswerItem item : reader.bundle().items) {
            if (!item.answer.isBlank() || !item.diagrams.isEmpty()) return true;
            if (last && (item.status == AnswerItem.Status.NEEDS_INPUT || item.status == AnswerItem.Status.FAILED)
                    && !item.issue.isBlank()) return true;
        }
        return false;
    }

    private void acknowledgeDisplayedAnswers() {
        if (reader == null || !reader.hasViewport() || answerStore == null) return;
        AnswerReader displayedReader = reader;
        AnswerBundle shown = reader.bundle();
        long session;
        try {
            session = Long.parseLong(shown.sessionId);
        } catch (NumberFormatException ignored) { return; }
        if (session <= 0 || acknowledgementPending == shown
                || (acknowledgedSession == session && acknowledgedRevision >= shown.revision)) return;
        long generation = powerGeneration;
        acknowledgementPending = shown;
        queueAnswerPersistence(() -> {
            AnswerStore.Saved saved = loadSavedAnswers();
            main.post(() -> {
                if (acknowledgementPending != shown) return;
                acknowledgementPending = null;
                if (!isCurrentPowerGeneration(generation) || sessionClosed || writingDone
                        || isFinishing() || isDestroyed() || reader != displayedReader || reader.bundle() != shown
                        || !reader.hasViewport()) return;
                if (saved == null || saved.closed || saved.bundle.revision < shown.revision
                        || !saved.bundle.sessionId.equals(shown.sessionId)
                        || !saved.bundle.inputDigest.equals(shown.inputDigest)) return;
                recordAcknowledgedRevision(shown);
                notifyPhase(powerPhase, powerSession, displayRequest);
            });
        });
    }

    private void recordAcknowledgedRevision(AnswerBundle shown) {
        try {
            long session = Long.parseLong(shown.sessionId);
            if (session <= 0) return;
            acknowledgedRevision = acknowledgedSession == session
                    ? Math.max(acknowledgedRevision, shown.revision) : shown.revision;
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
        if (sessionClosed || writingDone || isFinishing() || isDestroyed()
                || !isCurrentPowerGeneration(powerGeneration)) return;
        cancelDisplayIdle();
        if (idleAsleep) displaySleep.wake(this);
        idleAsleep = false;
        showOrBlank();
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    }

    /** Nothing is drawn while the display idles, nor while the wearer has paused the capture with a tap. */
    private void showOrBlank() {
        if (hud != null) hud.setBlank(idleAsleep || (controller != null && controller.isCapturePaused()));
    }

    private void enterIdleDisplay(String phase, long session) {
        // Entering: another phase, or another reading. Not the same phase's display already asleep when only the
        // reading's id becomes known: on 2026-11-19 the display lit for five seconds some seventy seconds after
        // each end, when the phone had made the session, with nothing new to show (the id is still sent below).
        boolean entering = !phase.equals(powerPhase) || (session != powerSession && !(idleAsleep && powerSession == 0));
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
                    || !isCurrentPowerGeneration(generation) || isFinishing() || isDestroyed() || displayProtected()) return;
            displayIdle = null;
            idleAsleep = true;
            routeAsked = false; // this showing of the chooser is over: the next one asks about the routes again
            // Off as the wearer sees it, whether or not the system's sleep follows: until 2026-11-13 the idle left
            // the screen drawn, so a display the phone had not put to sleep looked on while a tap only "woke" it.
            if (hud != null) hud.setBlank(true);
            displaySleep.sleep(this);
            notifyPhase(List.of("chooser", "analyzing", "waiting").contains(powerPhase) ? powerPhase : "waiting", activeSession(), "sleep");
        };
        main.postDelayed(displayIdle, choosingSession ? CHOOSER_IDLE_MILLIS : DISPLAY_IDLE_MILLIS);
    }

    private long activeSession() {
        if (reader != null) {
            try { return Long.parseLong(reader.bundle().sessionId); } catch (NumberFormatException ignored) { }
        }
        return powerSession > 0 ? powerSession : controller == null ? 0 : controller.sessionId();
    }

    static GlassCamera.Mode evaluationMode(Intent intent) {
        boolean zsl = evaluationFlag(intent, EXTRA_ZSL_EVALUATION);
        boolean video = evaluationFlag(intent, EXTRA_VIDEO_EVALUATION);
        videoTransferEvaluation(intent);
        paperGeometryEvaluation(intent);
        nativeSelection(intent);
        settingsBracket(intent);
        if (zsl && video) throw new IllegalArgumentException("ZSLと録画評価は同時指定できません");
        return video ? GlassCamera.Mode.VIDEO_EVALUATION : zsl ? GlassCamera.Mode.ZSL_EVALUATION_YUV : GlassCamera.Mode.NATIVE_STILL;
    }

    static boolean paperGeometryEvaluation(Intent intent) {
        boolean enabled = evaluationFlag(intent, EXTRA_PAPER_GEOMETRY_EVALUATION);
        if (enabled && (evaluationFlag(intent, EXTRA_ZSL_EVALUATION) || evaluationFlag(intent, EXTRA_VIDEO_EVALUATION)))
            throw new IllegalArgumentException("paper geometry comparison requires native stills");
        return enabled;
    }

    /** Explicit, nonpersistent capability gate until two-shot physical latency/quality is measured. */
    static boolean nativeSelection(Intent intent) {
        boolean enabled = evaluationFlag(intent, EXTRA_NATIVE_SELECTION);
        if (enabled && (evaluationFlag(intent, EXTRA_ZSL_EVALUATION) || evaluationFlag(intent, EXTRA_VIDEO_EVALUATION)
                || evaluationFlag(intent, EXTRA_PAPER_GEOMETRY_EVALUATION)))
            throw new IllegalArgumentException("native selection requires native stills");
        return enabled;
    }

    /** Explicit, nonpersistent: the extra stills are private comparison files and never pages. */
    static boolean settingsBracket(Intent intent) {
        boolean enabled = evaluationFlag(intent, EXTRA_SETTINGS_BRACKET);
        if (enabled && (evaluationFlag(intent, EXTRA_ZSL_EVALUATION) || evaluationFlag(intent, EXTRA_VIDEO_EVALUATION)
                || evaluationFlag(intent, EXTRA_PAPER_GEOMETRY_EVALUATION) || evaluationFlag(intent, EXTRA_NATIVE_SELECTION)))
            throw new IllegalArgumentException("settings bracket requires ordinary native stills");
        return enabled;
    }

    static boolean videoTransferEvaluation(Intent intent) {
        boolean enabled=evaluationFlag(intent,EXTRA_VIDEO_TRANSFER_EVALUATION);
        if (enabled && !evaluationFlag(intent,EXTRA_VIDEO_EVALUATION))
            throw new IllegalArgumentException("原動画の比較転送には録画評価の明示指定が必要です");
        return enabled;
    }

    private CaptureVideoTransfer.Snapshot comparisonVideoSnapshot() {
        if (!comparisonTransferEnabled || sessionClosed || writingDone || evaluationRestarting || controller == null) return null;
        DocScanController.LocalCaptureBinding binding=controller.localCaptureBinding();
        PowerState.Snapshot power=new PowerState(getPreferences(MODE_PRIVATE)).load();
        if (binding == null || power.generation != powerGeneration) return null;
        return new CaptureVideoTransfer.Snapshot(binding.localId,binding.server,binding.documentId,binding.sessionId,
                deviceId,power.generation,power.session,power.phase,binding.api);
    }

    CaptureInspectionOrigin.Context captureInspectionContext() {
        if (deviceId == null || sessionClosed || writingDone || evaluationRestarting || isFinishing() || isDestroyed()) return null;
        PowerState.Snapshot power = new PowerState(getPreferences(MODE_PRIVATE)).load();
        if (power.generation != powerGeneration || List.of("closed", "writing_done").contains(power.phase)) return null;
        try { return new CaptureInspectionOrigin.Context(deviceId, powerGeneration); }
        catch (IllegalArgumentException unavailable) { return null; }
    }

    static CaptureVideoRecording.Options videoOptions(Intent intent, String deviceId, long generation) {
        if (!evaluationFlag(intent, EXTRA_VIDEO_EVALUATION))
            return CaptureVideoRecording.Options.defaults("inactive-evaluation", generation, MEASURED_ROTATION_DEGREES);
        return new CaptureVideoRecording.Options(deviceId, generation, MEASURED_ROTATION_DEGREES,
                intent.hasExtra("video_codec") ? intent.getStringExtra("video_codec") : "avc",
                evaluationInteger(intent, "video_width", 4032), evaluationInteger(intent, "video_height", 3024),
                evaluationInteger(intent, "video_fps", 30), evaluationInteger(intent, "video_bitrate", 20_000_000));
    }

    private static boolean evaluationFlag(Intent intent, String key) {
        if (intent == null || !intent.hasExtra(key)) return false;
        Object value = intent.getExtras().get(key);
        if (!(value instanceof Boolean)) throw new IllegalArgumentException("evaluation flag must be boolean: " + key);
        return (Boolean)value;
    }

    private static int evaluationInteger(Intent intent, String key, int fallback) {
        if (!intent.hasExtra(key)) return fallback;
        Object value = intent.getExtras().get(key);
        if (!(value instanceof Integer)) throw new IllegalArgumentException("evaluation value must be integer: " + key);
        return (Integer)value;
    }

    private void beginPowerGeneration() {
        cancelDisplayIdle();
        idleAsleep = false;
        try { powerGeneration = new PowerState(getPreferences(MODE_PRIVATE)).begin(powerGeneration).generation; }
        catch (IOException error) { sessionClosed = true; displaySleep.sleep(this); finish(); return; }
        powerSequence = 0;
        if (still() != null) still().videoGeneration(powerGeneration);
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
        boolean accepted = acceptsWake(intent);
        UseLog.i(TAG, "wake revision=" + (intent == null ? -1 : intent.getLongExtra("answer_revision", -1))
                + " accepted=" + accepted);
        if (!accepted) return;
        long revision = intent.getLongExtra("answer_revision", 0);
        if (answersFetchedForSession == powerSession && revision <= answersFetchedRevision) {
            retryAcknowledgement();
            return;
        }
        // Keep the phone's snapshot advisory: only this still-active run may turn the display on.
        setTurnScreenOn(true);
        choosingSession = false;
        answersFetchedForSession = powerSession;
        wakeAtMillis = SystemClock.elapsedRealtime();
        fetchAnswers(powerSession, revision);
    }

    private void notifyPhase(String phase, long session) {
        notifyPhase(phase, session, phase.equals("capturing") || phase.equals("reading") ? "wake" : null);
    }

    private void notifyPhase(String phase, long session, String request) {
        if (!isCurrentPowerGeneration(powerGeneration)) return;
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
        } catch (IOException error) { UseLog.w(TAG, "display state not saved"); return; }
        UseLog.i(TAG, "display_request generation=" + gen + " sequence=" + seq
                + " phase=" + phase + " request=" + request);
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
                CaptureVideoTransfer transfer=videoTransfer; if (transfer != null) transfer.request();
            } catch (Exception error) {
                UseLog.w(TAG, "state notification paused: " + error.getClass().getSimpleName());
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
     * commit in gesture order. Consecutive unstarted cursor writes for the
     * same immutable bundle retain only the latest cursor. Reads, resumes,
     * waited writes and CLOSED remain separate FIFO barriers. CLOSED
     * is queued on that same executor, not a separate path, so it can never
     * be overtaken by a position write queued earlier by a faster gesture;
     * and this method blocks on waited writes so the CLOSED latch is
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
        Future<Boolean> queued;
        synchronized (answerPositionLock) {
            if (!closed && !wait && pendingAnswerPosition != null
                    && pendingAnswerPosition.bundle == bundle) {
                pendingAnswerPosition.questionId = questionId;
                pendingAnswerPosition.offset = offset;
                return true;
            }
            pendingAnswerPosition = null;
            PendingAnswerPosition position = new PendingAnswerPosition(bundle, questionId, offset, closed);
            if (!closed && !wait) pendingAnswerPosition = position;
            try { queued = answerPersistExecutor.submit(position); }
            catch (java.util.concurrent.RejectedExecutionException error) {
                pendingAnswerPosition = null;
                Log.w(TAG, "answer position queue closed", error);
                return false;
            }
        }
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

    private void queueAnswerPersistence(Runnable task) {
        synchronized (answerPositionLock) {
            pendingAnswerPosition = null;
            answerPersistExecutor.execute(task);
        }
    }

    private final class PendingAnswerPosition implements java.util.concurrent.Callable<Boolean> {
        private final AnswerBundle bundle;
        private final boolean closed;
        private String questionId;
        private int offset;

        private PendingAnswerPosition(AnswerBundle bundle, String questionId, int offset, boolean closed) {
            this.bundle = bundle;
            this.questionId = questionId;
            this.offset = offset;
            this.closed = closed;
        }

        @Override public Boolean call() {
            String savedQuestion;
            int savedOffset;
            synchronized (answerPositionLock) {
                if (pendingAnswerPosition == this) pendingAnswerPosition = null;
                savedQuestion = questionId;
                savedOffset = offset;
            }
            return writeAnswerPosition(bundle, savedQuestion, savedOffset, closed);
        }
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
