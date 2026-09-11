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
import android.os.SystemClock;
import android.util.Log;
import android.view.KeyEvent;
import android.view.WindowManager;
import android.widget.Toast;

import java.io.IOException;
import java.util.List;
import java.util.Optional;

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
    private static final int CAMERA_PERMISSION_REQUEST = 7401;

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
    private final Handler main = new Handler(Looper.getMainLooper());

    private HandlerThread cameraThread;
    private GlassCamera camera;
    private GlassesCaptureSurface surface;
    private JapaneseOcr ocr;
    private DocScanController controller;
    private HudView hud;
    private AnswerView answers;
    private AnswerStore answerStore;
    // Screen ownership only. Always read/written on the main thread (onAction,
    // openAnswers/closeAnswers, and the main.post callback fetchAnswers posts
    // from its background thread) -- onUpdate's guard no longer reads it.
    private AnswerReader reader;
    // Set once, the first time a REVIEW state is seen, and never cleared, so
    // fetchAnswers runs exactly once per Activity instance -- closing the
    // reader must not make onUpdate try again. volatile: read and written
    // from the controller's serial-executor thread, matching the convention
    // DocScanController itself uses for its own cross-thread fields.
    private volatile boolean answersFetched;

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
        // Putting the glasses back on wakes the display and the session with
        // it. Nothing restarts while they stay on the operator's face.
        wearWatch = new WearWatch(this, this::wornAgain);
        wearWatch.start();
        hud.calibrateGuide(getPreferences(MODE_PRIVATE).getFloat(
                EXTRA_GUIDE, (float) FramingGuide.UNCALIBRATED_FRACTION));

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
            controller.configureAndResume(
                    intent == null ? null : intent.getStringExtra(EXTRA_SERVER),
                    intent == null ? null : intent.getStringExtra(EXTRA_KEY),
                    MEASURED_ROTATION_DEGREES);
        }
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        // KEYCODE_BACK is absent on purpose: it has to reach the framework so
        // onBackPressed runs, which is where the two-stage exit is decided.
        if (normalize("DOWN", keyCode)) {
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    public boolean onKeyUp(int keyCode, KeyEvent event) {
        if (normalize("UP", keyCode)) {
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
            Log.i(TAG, "exit confirmed");
            if (displaySleep.sleep(this) == DisplaySleep.Result.NOT_PERMITTED) {
                // Never claim an exit that left the display lit.
                Log.w(TAG, "display stays on: WRITE_SETTINGS is not granted");
                hud.showLines(List.of("終了しました", "消灯できません", "設定の許可が必要"));
                main.postDelayed(this::finish, EXIT_NOTICE_MILLIS);
                return;
            }
            finish();
            return;
        }
        hud.showLines(List.of("もう一度で終了", "", ""));
    }

    /**
     * The glasses came back on after an exit that put the display to sleep.
     * The process is still alive -- only the screen slept -- so the operator's
     * own timeout goes back and the session is held awake again.
     */
    private void wornAgain() {
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
    }

    @Override
    protected void onDestroy() {
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
    }

    // --- input ------------------------------------------------------------

    private boolean normalize(String phase, int keyCode) {
        String name = KeyEvent.keyCodeToString(keyCode);
        Optional<GlassesInputAction> action = normalizer.accept(InputSignal.key(
                SystemClock.elapsedRealtime(), phase, name, GlassKeyEvents.isKnown(name)));
        action.ifPresent(this::onAction);
        // Consume every gesture key the firmware delivers except BACK, so the
        // system does not act on it behind the session.
        return !"KEYCODE_BACK".equals(name) && GlassKeyEvents.isKnown(name);
    }

    private void onAction(GlassesInputAction action) {
        if (action != GlassesInputAction.BACK) {
            backExit.reset();
        }
        if (reader != null) {
            if (!AnswerGestures.apply(reader, action)) {
                closeAnswers();
                return;
            }
            persistAnswerPosition(false);
            answers.refresh();
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
    public void onConfigurationRejected(String message) {
        main.post(() -> Toast.makeText(this, message, Toast.LENGTH_LONG).show());
    }

    @Override
    public void onViewShown(long generation, String purpose) {
        controller.onCustomViewAvailable(generation, purpose);
    }

    @Override
    public void onUpdate(RelayState state, List<String> hudLines, String diagnostic) {
        Log.i(TAG, state + ": " + diagnostic);
        if (state == RelayState.REVIEW && !answersFetched) {
            answersFetched = true;
            fetchAnswers(controller.sessionId());
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

    // --- answer reading -----------------------------------------------------

    /**
     * A saved reader survives the process restart that folding the temple
     * arms causes, so a resume is tried before any network request. Past
     * that, one request, then the reader works with no route to the server:
     * the exam venue has no Wi-Fi network, and the glasses reach the server
     * only while the phone's hotspot is up, which may be true only before
     * the exam starts.
     */
    private void fetchAnswers(long sessionId) {
        new Thread(() -> {
            AnswerStore.Saved saved = resumeSavedAnswers();
            if (saved != null) {
                main.post(() -> openAnswers(saved.bundle, saved.questionId, saved.offset));
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
                main.post(() -> hud.showLines(
                        List.of("答案を取得できません", "通信を確認", "")));
            }
        }, "answer-bundle").start();
    }

    private AnswerStore.Saved resumeSavedAnswers() {
        try {
            return answerStore.resume();
        } catch (IOException error) {
            Log.w(TAG, "saved answer state unavailable", error);
            return null;
        }
    }

    private void openAnswers(AnswerBundle bundle, String questionId, int offset) {
        answers = new AnswerView(this);
        // A placeholder viewport: AnswerView.onSizeChanged calls
        // reader.viewport with its own Paint as soon as it is laid out, and
        // the view owns the layout, so nothing here should guess at width.
        reader = new AnswerReader(bundle, 1f, 2, text -> text.length());
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

    /** Persistence must never throw into the UI, exactly as the fetch does not. */
    private void persistAnswerPosition(boolean closed) {
        if (reader == null) {
            return;
        }
        try {
            answerStore.save(reader.bundle(), reader.current().questionId, reader.offset(), closed);
        } catch (IOException error) {
            Log.w(TAG, "answer position not saved", error);
        }
    }
}
