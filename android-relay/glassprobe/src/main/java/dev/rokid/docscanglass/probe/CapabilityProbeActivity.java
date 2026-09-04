package dev.rokid.docscanglass.probe;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Context;
import android.content.pm.PackageManager;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.os.Bundle;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Looper;
import android.os.SystemClock;
import android.util.DisplayMetrics;
import android.util.Log;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowManager;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Settles, in one install, the four unverified points the glasses-side
 * architecture depends on.
 *
 * <ul>
 *   <li>P1 the real display metrics, read from inside an app rather than quoted
 *       from a datasheet;</li>
 *   <li>P2 whether the camera opens and how long one still takes;</li>
 *   <li>P3 whether the glasses reach the FastAPI server over their own Wi-Fi,
 *       which decides whether the phone stays in the loop at all;</li>
 *   <li>P4 whether {@code KEYCODE_BACK} can be consumed, since the firmware
 *       ends a one-finger double tap with it and an unconsumed BACK finishes
 *       the Activity on a single mis-tap.</li>
 * </ul>
 *
 * <p>Nothing runs on its own. P2 needs an explicit operator tap, and no probe
 * uploads, recognizes, or registers anything.
 *
 * <p>The server base URL arrives as an Intent extra so a different address
 * costs one adb command rather than a rebuild:
 *
 * <pre>
 * adb -s SERIAL shell am start \
 *   -n dev.rokid.docscanglass.probe/.CapabilityProbeActivity \
 *   --es server "http://HOST:8000"
 * </pre>
 */
public final class CapabilityProbeActivity extends Activity {

    private static final String TAG = "DocScanGlassProbe";
    private static final String EXTRA_SERVER = "server";
    private static final int CAMERA_PERMISSION_REQUEST = 7301;

    /**
     * Second BACK inside this window exits. Longer than the measured 970 ms
     * gesture-correlation bound so the confirming report cannot be swallowed.
     */
    private static final long EXIT_CONFIRM_WINDOW_MILLIS = 3_000;

    private static final String P1 = "P1 DISPLAY";
    private static final String P2 = "P2 CAMERA";
    private static final String P3 = "P3 NETWORK";
    private static final String P4 = "P4 BACK";

    private final ProbeReport report =
            new ProbeReport(Arrays.asList(P1, P2, P3, P4));
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService network = Executors.newSingleThreadExecutor();

    private HandlerThread cameraThread;
    private CameraProbe camera;
    private ReportView view;
    private String serverBaseUrl;
    private int backCount;
    private long exitArmedAtMillis = -1;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // The measured default screen-off is 20 s, which is shorter than one
        // camera probe plus one network probe.
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        view = new ReportView(this);
        setContentView(view);

        cameraThread = new HandlerThread("camera-probe");
        cameraThread.start();
        camera = new CameraProbe(
                this, new Handler(cameraThread.getLooper()), this::onCameraResult);

        serverBaseUrl = getIntent() == null ? null : getIntent().getStringExtra(EXTRA_SERVER);

        recordDisplay();
        record(P2, ProbeReport.Status.PENDING, CameraProbe.describeCameras(this));
        startNetworkProbe();
        record(P4, ProbeReport.Status.PENDING, "double tap to test");
        Log.i(TAG, "capability probe started");
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        switch (keyCode) {
            // KEYCODE_BACK is absent on purpose: it must reach
            // Activity.onKeyDown so the framework tracks it and dispatches
            // onBackPressed on key up, where P4 is decided.
            case KeyEvent.KEYCODE_ENTER:
            case KeyEvent.KEYCODE_NUMPAD_ENTER:
            case KeyEvent.KEYCODE_DPAD_CENTER:
                requestCapture();
                return true;
            case KeyEvent.KEYCODE_DPAD_LEFT:
            case KeyEvent.KEYCODE_DPAD_RIGHT:
            case KeyEvent.KEYCODE_DPAD_UP:
            case KeyEvent.KEYCODE_DPAD_DOWN:
                startNetworkProbe();
                return true;
            default:
                return super.onKeyDown(keyCode, event);
        }
    }

    @Override
    public boolean onKeyUp(int keyCode, KeyEvent event) {
        switch (keyCode) {
            case KeyEvent.KEYCODE_ENTER:
            case KeyEvent.KEYCODE_NUMPAD_ENTER:
            case KeyEvent.KEYCODE_DPAD_CENTER:
            case KeyEvent.KEYCODE_DPAD_LEFT:
            case KeyEvent.KEYCODE_DPAD_RIGHT:
            case KeyEvent.KEYCODE_DPAD_UP:
            case KeyEvent.KEYCODE_DPAD_DOWN:
                return true;
            default:
                return super.onKeyUp(keyCode, event);
        }
    }

    @Override
    public void onRequestPermissionsResult(
            int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != CAMERA_PERMISSION_REQUEST) {
            return;
        }
        if (checkSelfPermission(Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_GRANTED) {
            camera.captureOnce();
            return;
        }
        record(P2, ProbeReport.Status.FAILED, "camera permission refused");
    }

    @Override
    protected void onDestroy() {
        camera.close();
        cameraThread.quitSafely();
        network.shutdownNow();
        super.onDestroy();
    }

    private void recordDisplay() {
        DisplayMetrics metrics = getResources().getDisplayMetrics();
        long freeMb = Runtime.getRuntime().maxMemory() / (1024L * 1024L);
        record(P1, ProbeReport.Status.OK,
                metrics.widthPixels + "x" + metrics.heightPixels
                        + " " + metrics.densityDpi + "dpi heap" + freeMb + "MB");
    }

    private void requestCapture() {
        record(P2, ProbeReport.Status.PENDING, "opening camera");
        if (checkSelfPermission(Manifest.permission.CAMERA)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(
                    new String[]{Manifest.permission.CAMERA}, CAMERA_PERMISSION_REQUEST);
            return;
        }
        camera.captureOnce();
    }

    private void onCameraResult(ProbeReport.Status status, String detail) {
        main.post(() -> record(P2, status, detail));
    }

    private void startNetworkProbe() {
        String base = serverBaseUrl;
        if (base == null || base.isBlank()) {
            record(P3, ProbeReport.Status.FAILED, "no --es server extra");
            return;
        }
        record(P3, ProbeReport.Status.PENDING, NetworkProbe.describeLink());
        network.execute(() -> {
            String link = NetworkProbe.describeLink();
            String health = NetworkProbe.get(base, "/health");
            String settings = NetworkProbe.get(base, "/v1/settings");
            String detail = health + " " + settings;
            ProbeReport.Status status =
                    health.contains(" 200 ") ? ProbeReport.Status.OK : ProbeReport.Status.FAILED;
            Log.i(TAG, "network probe link=" + link + " " + detail);
            main.post(() -> record(P3, status, detail));
        });
    }

    /**
     * P4. Deliberately does not call {@code super}: the default finishes the
     * Activity, which is exactly the behaviour under test. The glasses report
     * API 32, where {@code OnBackInvokedDispatcher} does not exist, so this is
     * the interception point available on the measured build.
     *
     * <p>Lint asks for the AndroidX OnBackPressedDispatcher instead. Its claim
     * that onBackPressed is no longer called holds only where
     * android.window.OnBackInvokedDispatcher exists, which is API 33; the
     * measured build is API 32. AndroidX would also need ComponentActivity,
     * which is more machinery than a throwaway spike aimed at one known
     * device warrants. Revisit the suppression when the glasses report API 33
     * or later.
     */
    @Override
    @SuppressLint("GestureBackNavigation")
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        backCount++;
        long now = SystemClock.elapsedRealtime();
        long armedAt = exitArmedAtMillis;
        if (armedAt >= 0 && now >= armedAt && now - armedAt <= EXIT_CONFIRM_WINDOW_MILLIS) {
            exitArmedAtMillis = -1;
            Log.i(TAG, "back confirmed after " + backCount + " reports; finishing");
            finish();
            return;
        }
        exitArmedAtMillis = now;
        record(P4, ProbeReport.Status.OK,
                "consumed x" + backCount + ", again to exit");
    }

    private void record(String key, ProbeReport.Status status, String detail) {
        report.record(key, status, detail);
        Log.i(TAG, "probe " + key + " " + status + " " + detail);
        if (view != null) {
            view.invalidate();
        }
    }

    /** Black background with green text: the only combination this display has. */
    private final class ReportView extends View {

        private static final int GREEN = Color.rgb(0x40, 0xFF, 0x5E);

        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);

        ReportView(Context context) {
            super(context);
            paint.setColor(GREEN);
            paint.setTypeface(android.graphics.Typeface.MONOSPACE);
        }

        @Override
        protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            canvas.drawColor(Color.BLACK);
            List<String> lines = new ArrayList<>(report.lines());
            lines.add("");
            lines.add("TAP capture / SWIPE retry net");
            lines.add("DOUBLE TAP twice to exit");

            float lineHeight = getHeight() / (float) (lines.size() + 1);
            paint.setTextSize(lineHeight * 0.62f);
            float y = lineHeight;
            for (String line : lines) {
                canvas.drawText(line, lineHeight * 0.2f, y, paint);
                y += lineHeight;
            }
        }
    }
}
