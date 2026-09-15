package dev.rokid.docscanglass.doc;

import android.app.Activity;
import android.content.ContentResolver;
import android.content.Context;
import android.content.SharedPreferences;
import android.os.PowerManager;
import android.provider.Settings;
import android.view.WindowManager;

/**
 * Turns the glasses display off at the end of a session, and says so honestly
 * when it cannot.
 *
 * <p>Measured 2026-09-10 on build {@code 1.25.015-20260903-150201}: this device
 * has no {@code android.software.device_admin} feature, so
 * {@code DevicePolicyManager.lockNow} is unavailable, and the CXR-L SDK exposes
 * no power or brightness call. What does work is the ordinary Android route --
 * shorten {@code Settings.System.SCREEN_OFF_TIMEOUT} and stop holding the
 * screen on. With 15 s the display reached {@code mScreenState=OFF} and the
 * device {@code mWakefulness=Asleep}. The stock timeout on these glasses is
 * ten days, so waiting for it is not an exit.</p>
 *
 * <p>A black screen is not "off". If the write is refused the caller is told
 * {@link Result#NOT_PERMITTED} and must show that, never a false confirmation.</p>
 */
final class DisplaySleep {
    /** Measured to sleep the display; short enough to feel like an exit. */
    static final int SHORT_TIMEOUT_MILLIS = 15_000;
    private static final String PREFS = "display-sleep";
    private static final String KEY_PREVIOUS = "previous_timeout_millis";

    enum Result {
        /** The timeout was shortened and the screen-on flag released. */
        SLEEPING,
        /** {@code WRITE_SETTINGS} is missing; the display stays lit. */
        NOT_PERMITTED
    }

    /** Seam: the one call that needs the permission, so tests can refuse it. */
    interface TimeoutWriter {
        boolean write(ContentResolver resolver, int millis);
    }

    private TimeoutWriter writer = (resolver, millis) ->
            Settings.System.putInt(resolver, Settings.System.SCREEN_OFF_TIMEOUT, millis);

    void writerForTest(TimeoutWriter replacement) {
        writer = replacement;
    }

    /**
     * Restores the operator's own timeout. Called on start, because folding the
     * temple arms force-stops the process before it can restore anything.
     */
    void restore(Context context) {
        SharedPreferences prefs = prefs(context);
        int previous = prefs.getInt(KEY_PREVIOUS, -1);
        if (previous < 0) {
            return;
        }
        if (write(context, previous)) {
            prefs.edit().remove(KEY_PREVIOUS).apply();
        }
    }

    /** Shortens the timeout and releases the screen, or reports why it did not. */
    Result sleep(Activity activity) {
        int previous = current(activity);
        if (!write(activity, SHORT_TIMEOUT_MILLIS)) {
            return Result.NOT_PERMITTED;
        }
        if (!prefs(activity).contains(KEY_PREVIOUS)) {
            prefs(activity).edit().putInt(KEY_PREVIOUS, previous).apply();
        }
        activity.getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        return Result.SLEEPING;
    }

    /** Public Android 12 wake-up path; the actual light state requires hardware observation. */
    @SuppressWarnings("deprecation")
    boolean wake(Activity activity) {
        restore(activity);
        activity.getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        PowerManager power = (PowerManager) activity.getSystemService(Context.POWER_SERVICE);
        if (power == null) return false;
        try {
            PowerManager.WakeLock wake = power.newWakeLock(
                    PowerManager.SCREEN_BRIGHT_WAKE_LOCK | PowerManager.ACQUIRE_CAUSES_WAKEUP,
                    "docscan:answer-display");
            wake.acquire(2000);
            wake.release();
            return true;
        } catch (SecurityException refused) {
            return false;
        }
    }

    private boolean write(Context context, int millis) {
        try {
            return writer.write(context.getContentResolver(), millis);
        } catch (SecurityException refused) {
            return false;
        }
    }

    private int current(Context context) {
        return Settings.System.getInt(
                context.getContentResolver(), Settings.System.SCREEN_OFF_TIMEOUT,
                SHORT_TIMEOUT_MILLIS);
    }

    private SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }
}
