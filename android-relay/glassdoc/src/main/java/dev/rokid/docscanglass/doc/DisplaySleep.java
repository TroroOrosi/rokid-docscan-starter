package dev.rokid.docscanglass.doc;

import android.app.Activity;
import android.content.Context;
import android.os.PowerManager;
import android.view.WindowManager;

/**
 * Releases the app's display hold without changing the operator's timeout.
 * The authenticated phone watcher requests actual sleep; releasing this
 * window alone does not establish that the display is off.
 */
final class DisplaySleep {
    /** The phone's sleep request must not fight an app-owned screen hold. */
    void sleep(Activity activity) {
        // A late start/resume must not reuse an earlier accepted answer's wake request.
        activity.setTurnScreenOn(false);
        activity.getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    }

    /** Public Android 12 wake-up path; the actual light state requires hardware observation. */
    @SuppressWarnings("deprecation")
    boolean wake(Activity activity) {
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

}
