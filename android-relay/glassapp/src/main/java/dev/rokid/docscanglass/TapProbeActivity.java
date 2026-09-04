package dev.rokid.docscanglass;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.os.Build;
import android.os.Bundle;
import android.os.SystemClock;
import android.util.Log;
import android.view.GestureDetector;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;

import dev.rokid.docscanglass.input.BackExitPolicy;
import dev.rokid.docscanglass.input.GlassKeyEvents;
import dev.rokid.docscanglass.input.InputCalibrationLog;
import dev.rokid.docscanglass.input.InputSignal;
import dev.rokid.docscanglass.input.GlassesInputAction;
import dev.rokid.docscanglass.input.GlassesInputNormalizer;
import dev.rokid.docscanglass.input.GlassesInputReceiver;
import dev.rokid.docscanglass.input.OfficialKeyBroadcasts;

import java.util.List;
import java.util.Locale;

/**
 * Asks one question on the glasses themselves: does an ordinary Android app
 * running here receive operator input?
 *
 * <p>Inside a CUSTOMVIEW overlay it does not. Measured 2026-08-29 over 17
 * minutes, an overlay delivered no event attributable to a tap: every
 * {@code AI-exit} was an echo of the relay's own view push, and every
 * {@code userInitiated=true} close was the glasses dismissing the view on a
 * ~30 s timer. That is a property of the overlay. This app is not an overlay.
 *
 * <p>The verdict is drawn on the glasses display and written to a content-free
 * diagnostic log. The calibration observes both the official custom-app key
 * broadcasts and Activity key events without assigning either path to a
 * document workflow action.
 *
 * <p>Both the touch path and the key path are recorded. The working reference
 * implementation handles the same gesture on either, which suggests the
 * touchpad can surface as {@code KEYCODE_DPAD_*} rather than as a
 * {@link MotionEvent} depending on firmware or focus. A probe that watched only
 * one path could report "no input" while input was arriving on the other.
 */
public final class TapProbeActivity extends Activity {

    private static final String TAG = "DocScanGlass";
    private static final int VISIBLE_EVENTS = 6;
    private static final int VISIBLE_CALIBRATION_EVENTS = 3;
    private static final float SWIPE_MIN_DISTANCE_DP = 40f;
    private static final float SWIPE_DOMINANCE = 1.3f;

    private final TapLog log = new TapLog(VISIBLE_EVENTS);
    private final InputCalibrationLog calibration =
            new InputCalibrationLog(VISIBLE_EVENTS);
    private final GlassesInputNormalizer normalizer = new GlassesInputNormalizer();
    private final BackExitPolicy backExit = new BackExitPolicy();
    private final GlassesInputReceiver inputReceiver =
            new GlassesInputReceiver(this::recordCalibration);
    private final BroadcastReceiver officialKeyReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            inputReceiver.accept(elapsed(), intent.getAction());
        }
    };

    private ProbeView view;
    private GestureDetector gestures;
    private long startedAtMillis;
    private int normalizedCount;
    private String normalizedLine = "ACTION waiting";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        startedAtMillis = SystemClock.elapsedRealtime();
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        gestures = new GestureDetector(this, new GestureDetector.SimpleOnGestureListener() {
            @Override
            public boolean onDown(MotionEvent event) {
                return true;
            }

            @Override
            public boolean onSingleTapUp(MotionEvent event) {
                log.recordGestureTap(elapsed());
                report("gesture tap");
                return true;
            }

            @Override
            public boolean onFling(
                    MotionEvent from, MotionEvent to, float velocityX, float velocityY) {
                if (from == null) {
                    return false;
                }
                float dx = to.getX() - from.getX();
                float dy = to.getY() - from.getY();
                float minimum =
                        SWIPE_MIN_DISTANCE_DP * getResources().getDisplayMetrics().density;
                if (Math.abs(dx) < minimum || Math.abs(dx) <= Math.abs(dy) * SWIPE_DOMINANCE) {
                    return false;
                }
                log.recordSwipe(elapsed(), dx > 0 ? "RIGHT" : "LEFT");
                report("gesture swipe");
                return true;
            }
        });

        view = new ProbeView(this);
        setContentView(view);
        registerOfficialKeyReceiver();
        Log.i(TAG, "tap probe started");
    }

    @Override
    public boolean dispatchTouchEvent(MotionEvent event) {
        recordMotion(event, "touch");
        gestures.onTouchEvent(event);
        return true;
    }

    /**
     * A touchpad that reports as anything other than a touchscreen never
     * reaches {@link #dispatchTouchEvent}. Watching only that path could report
     * an absence of input that is really an absence of one source.
     */
    @Override
    public boolean dispatchGenericMotionEvent(MotionEvent event) {
        recordMotion(event, "generic");
        return super.dispatchGenericMotionEvent(event);
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        String keyName = KeyEvent.keyCodeToString(keyCode);
        long eventElapsed = elapsed();
        log.recordKey(eventElapsed, "DOWN", keyName);
        recordCalibration(InputSignal.key(
                eventElapsed, "DOWN", keyName, GlassKeyEvents.isKnown(keyName)));
        report("key down");
        return consumeProbeKey(keyCode) || super.onKeyDown(keyCode, event);
    }

    @Override
    public boolean onKeyUp(int keyCode, KeyEvent event) {
        String keyName = KeyEvent.keyCodeToString(keyCode);
        recordCalibration(InputSignal.key(
                elapsed(), "UP", keyName, GlassKeyEvents.isKnown(keyName)));
        return consumeProbeKey(keyCode) || super.onKeyUp(keyCode, event);
    }

    /**
     * Intercepts the measured one-finger double tap without ending the session.
     *
     * <p>Deliberately does not call {@code super}. The firmware ends that
     * gesture with {@code KEYCODE_BACK}, whose default handling finishes the
     * Activity, so one mis-tap ended the run. The glasses report Android 12 /
     * API 32, where {@code OnBackInvokedDispatcher} does not exist yet, so this
     * is the interception point available on the measured build.
     *
     * <p>Lint asks for the AndroidX OnBackPressedDispatcher instead. Its claim
     * that onBackPressed is no longer called holds only where
     * android.window.OnBackInvokedDispatcher exists, which is API 33; the
     * measured build is API 32. AndroidX would also need ComponentActivity,
     * and this module carries no dependencies on purpose so that a negative
     * hardware result cannot be blamed on a library. Revisit the suppression
     * when the glasses report API 33 or later.
     */
    @Override
    @SuppressLint("GestureBackNavigation")
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (backExit.onBack(elapsed()) == BackExitPolicy.Decision.EXIT) {
            Log.i(TAG, "back confirmed; finishing");
            finish();
            return;
        }
        normalizedLine = "BACK - again to exit";
        Log.i(TAG, "back armed; a second BACK within "
                + BackExitPolicy.CONFIRM_WINDOW_MILLIS + " ms exits");
        if (view != null) {
            view.invalidate();
        }
    }

    @Override
    protected void onDestroy() {
        inputReceiver.unregister(() -> unregisterReceiver(officialKeyReceiver));
        normalizer.reset();
        backExit.reset();
        super.onDestroy();
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        normalizer.reset();
        backExit.reset();
        Log.i(TAG, "focus changed hasFocus=" + hasFocus + " input state reset");
    }

    private void registerOfficialKeyReceiver() {
        IntentFilter filter = new IntentFilter();
        for (String action : OfficialKeyBroadcasts.actions()) {
            filter.addAction(action);
        }
        inputReceiver.register(() -> {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                registerReceiver(officialKeyReceiver, filter, Context.RECEIVER_EXPORTED);
            } else {
                registerReceiver(officialKeyReceiver, filter);
            }
        });
    }

    private boolean consumeProbeKey(int keyCode) {
        switch (keyCode) {
            case KeyEvent.KEYCODE_DPAD_CENTER:
            case KeyEvent.KEYCODE_ENTER:
            case KeyEvent.KEYCODE_NUMPAD_ENTER:
            case KeyEvent.KEYCODE_BUTTON_A:
            case KeyEvent.KEYCODE_DPAD_LEFT:
            case KeyEvent.KEYCODE_DPAD_RIGHT:
                return true;
            default:
                // BACK is deliberately not consumed here. It has to reach
                // Activity.onKeyDown so the framework starts tracking it and
                // dispatches onBackPressed on key up, which is where the
                // double-tap exit is decided.
                return false;
        }
    }

    private void recordCalibration(InputSignal signal) {
        calibration.record(signal);
        Log.i(TAG, "input " + calibration.lines().get(0));
        normalizer.accept(signal).ifPresent(this::recordNormalizedAction);
        if (view != null) {
            view.invalidate();
        }
    }

    private void recordNormalizedAction(GlassesInputAction action) {
        normalizedCount++;
        normalizedLine = "ACTION #" + normalizedCount + " " + action;
        Log.i(TAG, "normalized #" + normalizedCount + " action=" + action);
        if (action != GlassesInputAction.BACK) {
            // Any other deliberate action means the operator is not leaving.
            backExit.reset();
        }
    }

    private void recordMotion(MotionEvent event, String path) {
        int masked = event.getActionMasked();
        log.recordTouch(
                elapsed(),
                MotionEvent.actionToString(masked),
                masked == MotionEvent.ACTION_DOWN,
                event.getX(),
                event.getY(),
                event.getPointerCount());
        report(path + " source=0x" + Integer.toHexString(event.getSource()));
    }

    private void report(String what) {
        Log.i(TAG, what + " :: " + log.counters());
        if (view != null) {
            view.invalidate();
        }
    }

    private long elapsed() {
        return SystemClock.elapsedRealtime() - startedAtMillis;
    }

    /**
     * Draws the verdict at a size derived from the view, because the glasses
     * display resolution is not documented and this repo has never measured it.
     */
    private final class ProbeView extends View {

        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);

        ProbeView(Context context) {
            super(context);
            setBackgroundColor(Color.BLACK);
            paint.setColor(Color.GREEN);
        }

        @Override
        protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            float rowHeight = Math.max(getHeight() / 12f, 12f);
            float left = rowHeight * 0.3f;
            paint.setTextSize(rowHeight * 0.8f);

            float y = rowHeight;
            canvas.drawText(
                    String.format(Locale.US, "TAP PROBE %dx%d", getWidth(), getHeight()),
                    left,
                    y,
                    paint);

            y += rowHeight;
            canvas.drawText(log.counters(), left, y, paint);

            y += rowHeight;
            canvas.drawText(
                    log.receivedAnything() ? "INPUT REACHES APP" : "waiting for input",
                    left,
                    y,
                    paint);

            y += rowHeight;
            canvas.drawText(normalizedLine, left, y, paint);

            List<String> lines = log.lines();
            int shown = 0;
            for (String line : lines) {
                if (shown++ >= VISIBLE_CALIBRATION_EVENTS) {
                    break;
                }
                y += rowHeight;
                canvas.drawText(line, left, y, paint);
            }

            shown = 0;
            for (String line : calibration.lines()) {
                if (shown++ >= VISIBLE_CALIBRATION_EVENTS) {
                    break;
                }
                y += rowHeight;
                canvas.drawText(line, left, y, paint);
            }
        }
    }
}
