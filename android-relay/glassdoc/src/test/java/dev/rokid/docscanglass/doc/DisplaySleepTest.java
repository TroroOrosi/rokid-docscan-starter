package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;

import android.app.Activity;
import android.provider.Settings;
import android.view.WindowManager;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
public class DisplaySleepTest {
    private static final int TEN_DAYS = 864_000_000;

    private Activity activity() {
        return Robolectric.buildActivity(Activity.class).create().get();
    }

    private int timeout() {
        return Settings.System.getInt(
                RuntimeEnvironment.getApplication().getContentResolver(),
                Settings.System.SCREEN_OFF_TIMEOUT, -1);
    }

    private void setTimeout(int millis) {
        Settings.System.putInt(
                RuntimeEnvironment.getApplication().getContentResolver(),
                Settings.System.SCREEN_OFF_TIMEOUT, millis);
    }

    @Test public void sleepShortensTheTimeoutAndStopsHoldingTheScreenOn() {
        setTimeout(TEN_DAYS);
        Activity activity = activity();
        activity.getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        DisplaySleep sleep = new DisplaySleep();

        assertEquals(DisplaySleep.Result.SLEEPING, sleep.sleep(activity));

        assertEquals(DisplaySleep.SHORT_TIMEOUT_MILLIS, timeout());
        int flags = activity.getWindow().getAttributes().flags;
        assertEquals(0, flags & WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    }

    @Test public void theOperatorsOwnTimeoutComesBackOnTheNextStart() {
        setTimeout(TEN_DAYS);
        DisplaySleep sleep = new DisplaySleep();
        sleep.sleep(activity());
        assertEquals(DisplaySleep.SHORT_TIMEOUT_MILLIS, timeout());

        // A separate instance: folding the arms force-stops the process.
        new DisplaySleep().restore(RuntimeEnvironment.getApplication());

        assertEquals(TEN_DAYS, timeout());
    }

    @Test public void restoringTwiceDoesNotOverwriteALaterChoice() {
        setTimeout(TEN_DAYS);
        DisplaySleep sleep = new DisplaySleep();
        sleep.sleep(activity());
        sleep.restore(RuntimeEnvironment.getApplication());

        setTimeout(60_000);
        sleep.restore(RuntimeEnvironment.getApplication());

        assertEquals(60_000, timeout());
    }

    @Test public void aRefusedWriteIsReportedInsteadOfPretendingToSleep() {
        setTimeout(TEN_DAYS);
        DisplaySleep sleep = new DisplaySleep();
        sleep.writerForTest((resolver, millis) -> {
            throw new SecurityException("WRITE_SETTINGS not granted");
        });
        Activity activity = activity();
        activity.getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        assertEquals(DisplaySleep.Result.NOT_PERMITTED, sleep.sleep(activity));

        assertEquals(TEN_DAYS, timeout());
        int flags = activity.getWindow().getAttributes().flags;
        assertNotEquals(0, flags & WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    }

    @Test public void nothingIsRestoredWhenNothingWasShortened() {
        setTimeout(TEN_DAYS);
        new DisplaySleep().restore(RuntimeEnvironment.getApplication());
        assertEquals(TEN_DAYS, timeout());
    }
}
