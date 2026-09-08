package dev.rokid.docscanglass.doc;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;
import android.view.KeyEvent;
import android.view.WindowManager;

import java.util.List;
import java.util.Optional;

import dev.rokid.docscanglass.input.BackExitPolicy;
import dev.rokid.docscanglass.input.GlassKeyEvents;
import dev.rokid.docscanglass.input.GlassesInputAction;
import dev.rokid.docscanglass.input.GlassesInputNormalizer;
import dev.rokid.docscanglass.input.InputSignal;
import dev.rokid.docscanrelay.CaptureActionRouter;
import dev.rokid.docscanrelay.CaptureLinkEvent;
import dev.rokid.docscanrelay.ClientIdentity;
import dev.rokid.docscanrelay.DocScanController;
import dev.rokid.docscanrelay.JapaneseOcr;
import dev.rokid.docscanrelay.RelayState;

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

    private final GlassesInputNormalizer normalizer = new GlassesInputNormalizer();
    private final BackExitPolicy backExit = new BackExitPolicy();
    private final Handler main = new Handler(Looper.getMainLooper());

    private HandlerThread cameraThread;
    private GlassCamera camera;
    private GlassesCaptureSurface surface;
    private JapaneseOcr ocr;
    private DocScanController controller;
    private HudView hud;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // The measured default screen-off is 20 s, shorter than one capture
        // plus one upload.
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        hud = new HudView(this);
        setContentView(hud);
        if (getIntent() != null) {
            hud.calibrateGuide(getIntent().getFloatExtra(
                    EXTRA_GUIDE, (float) FramingGuide.UNCALIBRATED_FRACTION));
        }

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

        // There is no service to bind and no pairing to lose: the camera and
        // the display are in this process. The link is ready as soon as the
        // activity is.
        controller.onCaptureLinkStateChanged(true, CaptureLinkEvent.GLASSES_STATUS_CHANGED);

        String server = getIntent() == null ? null : getIntent().getStringExtra(EXTRA_SERVER);
        String key = getIntent() == null ? "" : getIntent().getStringExtra(EXTRA_KEY);
        try {
            controller.configure(server, key == null ? "" : key, MEASURED_ROTATION_DEGREES);
            controller.verifyServer();
        } catch (RuntimeException error) {
            hud.showLines(List.of("サーバ未設定", String.valueOf(error.getMessage()), ""));
            Log.w(TAG, "no usable server URL supplied", error);
        }
        if (!hasCamera()) {
            requestPermissions(
                    new String[] {Manifest.permission.CAMERA}, CAMERA_PERMISSION_REQUEST);
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
            finish();
            return;
        }
        hud.showLines(List.of("もう一度で終了", "", ""));
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
        RelayState state = controller.getState();
        CaptureActionRouter.Command command = CaptureActionRouter.route(state, action);
        Log.i(TAG, "action " + action + " in " + state + " -> " + command);
        apply(command);
    }

    private void apply(CaptureActionRouter.Command command) {
        switch (command) {
            case ARM_NEXT:
                controller.captureNextPage();
                break;
            case ARM_PREVIOUS:
                controller.recapturePreviousPage();
                break;
            case ARM_RETAKE:
                controller.retakePendingCapture();
                break;
            case TAKE_PHOTO:
                controller.triggerArmedCapture();
                break;
            case CANCEL_AIMING:
                controller.cancelAiming();
                break;
            case FINISH_READING:
                controller.finishReading();
                break;
            case CONFIRM_CAPTURE:
                controller.confirmPendingCapture();
                break;
            case NEXT_REVIEW:
                controller.nextReviewItem();
                break;
            case PREVIOUS_REVIEW:
                controller.previousReviewItem();
                break;
            case START_NEW_DOCUMENT:
                controller.startNewDocument();
                break;
            default:
                break;
        }
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
    public void onViewShown(long generation, String purpose) {
        controller.onCustomViewAvailable(generation, purpose);
    }

    @Override
    public void onUpdate(RelayState state, List<String> hudLines, String diagnostic) {
        Log.i(TAG, state + ": " + diagnostic);
        // AIMING, STABILIZING and CAPTURE_REVIEW each own the screen through
        // their own surface call -- the guide brackets, and the still. Redrawing
        // plain text here would wipe them.
        if (state == RelayState.AIMING
                || state == RelayState.STABILIZING
                || state == RelayState.CAPTURE_REVIEW) {
            return;
        }
        main.post(() -> hud.showLines(hudLines));
    }
}
