package dev.rokid.docscanglass;

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

import dev.rokid.docscanglass.input.GlassKeyEvents;
import dev.rokid.docscanglass.input.InputCalibrationLog;
import dev.rokid.docscanglass.input.InputSignal;
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
    private final BroadcastReceiver officialKeyReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            String action = intent.getAction();
            if (action == null) {
                return;
            }
            recordCalibration(InputSignal.broadcast(
                    elapsed(), action, OfficialKeyBroadcasts.isOfficial(action)));
        }
    };

    private ProbeView view;
    private GestureDetector gestures;
    private long startedAtMillis;
    private boolean officialKeyReceiverRegistered;

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

    @Override
    protected void onDestroy() {
        if (officialKeyReceiverRegistered) {
            unregisterReceiver(officialKeyReceiver);
            officialKeyReceiverRegistered = false;
        }
        super.onDestroy();
    }

    private void registerOfficialKeyReceiver() {
        IntentFilter filter = new IntentFilter();
        for (String action : OfficialKeyBroadcasts.actions()) {
            filter.addAction(action);
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(officialKeyReceiver, filter, Context.RECEIVER_EXPORTED);
        } else {
            registerReceiver(officialKeyReceiver, filter);
        }
        officialKeyReceiverRegistered = true;
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
                // BACK included: consuming it would leave no way off this screen.
                return false;
        }
    }

    private void recordCalibration(InputSignal signal) {
        calibration.record(signal);
        Log.i(TAG, "input " + calibration.lines().get(0));
        if (view != null) {
            view.invalidate();
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
