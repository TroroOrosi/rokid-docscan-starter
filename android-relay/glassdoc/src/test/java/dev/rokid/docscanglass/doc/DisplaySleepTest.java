package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;

import android.app.Activity;
import android.content.Context;
import android.provider.Settings;
import android.view.WindowManager;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.Shadows;
import org.robolectric.annotation.Config;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
public class DisplaySleepTest {
    private Activity activity() {
        return Robolectric.buildActivity(Activity.class).create().get();
    }

    private int timeout() {
        return Settings.System.getInt(
                RuntimeEnvironment.getApplication().getContentResolver(),
                Settings.System.SCREEN_OFF_TIMEOUT, -2);
    }

    private void setTimeout(int millis) {
        Settings.System.putInt(
                RuntimeEnvironment.getApplication().getContentResolver(),
                Settings.System.SCREEN_OFF_TIMEOUT, millis);
    }

    @Test public void sleepReleasesTheWindowWithoutChangingAnyOperatorTimeout() {
        for (int timeout : new int[]{-1, 0, 60_000, 864_000_000}) {
            setTimeout(timeout);
            Activity activity = activity();
            activity.getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            activity.setTurnScreenOn(true);

            new DisplaySleep().sleep(activity);

            assertEquals(timeout, timeout());
            assertEquals(0, activity.getWindow().getAttributes().flags
                    & WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            assertFalse(Shadows.shadowOf(activity).getTurnScreenOn());
        }
    }

    @Test public void wakingCannotRestoreAStaleTimeoutOverTheOperatorsNewChoice() {
        Context context = RuntimeEnvironment.getApplication();
        context.getSharedPreferences("display-sleep", Context.MODE_PRIVATE).edit()
                .putInt("previous_timeout_millis", 15_000).commit();
        setTimeout(0);
        Activity activity = activity();

        assertTrue(new DisplaySleep().wake(activity));

        assertEquals(0, timeout());
        assertNotEquals(0, activity.getWindow().getAttributes().flags
                & WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    }

    @Test public void repeatedSleepAndWakeKeepTheOperatorsSetting() {
        setTimeout(864_000_000);
        Activity activity = activity();
        DisplaySleep sleep = new DisplaySleep();
        sleep.sleep(activity);
        sleep.sleep(activity);
        assertTrue(sleep.wake(activity));
        setTimeout(0);
        sleep.sleep(activity);
        assertTrue(new DisplaySleep().wake(activity));
        assertEquals(0, timeout());
    }
}
