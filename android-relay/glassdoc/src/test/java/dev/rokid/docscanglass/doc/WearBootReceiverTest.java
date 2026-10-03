package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import android.content.Intent;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.Shadows;
import org.robolectric.annotation.Config;

@RunWith(RobolectricTestRunner.class) @Config(sdk = 32, manifest = Config.NONE)
public class WearBootReceiverTest {
    @Test public void onlyBootStartsProximityMonitoringWithoutOpeningAnActivity() throws Exception {
        var app = RuntimeEnvironment.getApplication();
        var shadow = Shadows.shadowOf(app);
        long generation = PowerState.forContext(app).begin(0).generation;
        WearBootReceiver receiver = new WearBootReceiver();
        receiver.onReceive(app, new Intent("untrusted.action"));
        assertNull(shadow.getNextStartedService());
        receiver.onReceive(app, new Intent(Intent.ACTION_BOOT_COMPLETED));
        Intent service = shadow.getNextStartedService();
        assertNotNull(service);
        assertEquals(WearService.class.getName(), service.getComponent().getClassName());
        assertTrue(service.getBooleanExtra(WearService.COLD_BOOT, false));
        assertEquals(generation, service.getLongExtra("cold_generation", -1));
        assertNull(shadow.getNextStartedActivity());
    }
}
