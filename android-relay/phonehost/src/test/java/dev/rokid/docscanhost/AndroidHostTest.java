package dev.rokid.docscanhost;

import static org.junit.Assert.*;

import android.app.Application;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.ServiceInfo;
import android.view.View;
import java.util.ArrayList;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.android.controller.ServiceController;
import org.robolectric.android.controller.ActivityController;
import org.robolectric.annotation.Config;
import org.robolectric.Shadows;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
public class AndroidHostTest {
    private Application app;
    private HostPreferences store;

    @Before public void setup() {
        app = RuntimeEnvironment.getApplication();
        app.getSharedPreferences("host-monitor", Context.MODE_PRIVATE).edit().clear().commit();
        HostPreferences.resetForTest();
        store = HostPreferences.get(app);
    }

    @Test public void enabledRevisionAndCooldownSurviveAStoreReload() {
        assertFalse(store.read().enabled);
        assertTrue(store.setEnabled(true));
        long firstRevision = store.read().revision;
        assertTrue(store.reserveAttempt(90_000, 5));
        HostPreferences.resetForTest();
        HostMonitor.Snapshot restored = HostPreferences.get(app).read();
        assertTrue(restored.enabled);
        assertEquals(firstRevision, restored.revision);
        assertEquals(90_000, restored.lastAttemptElapsed);
        assertEquals(5, restored.lastAttemptBoot);
        assertTrue(HostPreferences.get(app).setEnabled(false));
        assertTrue(HostPreferences.get(app).read().revision > firstRevision);
        HostPreferences.resetForTest();
        assertFalse(HostPreferences.get(app).read().enabled);
    }

    @Test public void recoveryIntentUsesOnlyTheFixedBackgroundBootstrap() {
        Intent intent = TermuxLauncher.command();
        assertEquals("com.termux", intent.getComponent().getPackageName());
        assertEquals("com.termux.app.RunCommandService", intent.getComponent().getClassName());
        assertEquals("com.termux.RUN_COMMAND", intent.getAction());
        assertEquals("/data/data/com.termux/files/usr/bin/bash",
                intent.getStringExtra("com.termux.RUN_COMMAND_PATH"));
        assertArrayEquals(new String[]{"/data/data/com.termux/files/home/.termux/boot/20-rokid-services"},
                intent.getStringArrayExtra("com.termux.RUN_COMMAND_ARGUMENTS"));
        assertTrue(intent.getBooleanExtra("com.termux.RUN_COMMAND_BACKGROUND", false));
        assertEquals(3, intent.getExtras().size());
        assertEquals(0, intent.getFlags());
    }

    private void installTermux() {
        ServiceInfo service = new ServiceInfo();
        service.packageName = "com.termux";
        service.name = "com.termux.app.RunCommandService";
        service.enabled = true;
        service.exported = true;
        service.permission = TermuxLauncher.PERMISSION;
        service.applicationInfo = new ApplicationInfo();
        service.applicationInfo.packageName = service.packageName;
        service.applicationInfo.enabled = true;
        Shadows.shadowOf(app.getPackageManager()).addOrUpdateService(service);
    }

    @Test public void launcherRequiresInstalledTermuxAndPermissionBeforeDispatch() {
        TermuxLauncher launcher = new TermuxLauncher(app);
        assertEquals(HostMonitor.Status.TERMUX_MISSING, launcher.availability());
        installTermux();
        assertEquals(HostMonitor.Status.PERMISSION_REQUIRED, launcher.availability());
        Shadows.shadowOf(app).grantPermissions(TermuxLauncher.PERMISSION);
        assertEquals(HostMonitor.Status.READY, launcher.availability());
        launcher.launch();
        Intent dispatched = Shadows.shadowOf(app).getNextStartedService();
        assertNotNull(dispatched);
        assertEquals(TermuxLauncher.command().getComponent(), dispatched.getComponent());
        assertTrue(dispatched.getBooleanExtra("com.termux.RUN_COMMAND_BACKGROUND", false));
    }

    @Test public void activityEnableAndStopUseTheDurableChoice() {
        installTermux();
        Shadows.shadowOf(app).grantPermissions(TermuxLauncher.PERMISSION);
        ActivityController<MainActivity> controller = Robolectric.buildActivity(MainActivity.class).setup();
        MainActivity activity = controller.get();
        ArrayList<View> matches = new ArrayList<>();
        activity.getWindow().getDecorView().findViewsWithText(matches, "監視を開始", View.FIND_VIEWS_WITH_TEXT);
        assertEquals(1, matches.size());
        assertTrue(matches.get(0).performClick());
        assertTrue(store.read().enabled);
        long enabledRevision = store.read().revision;
        Intent started = Shadows.shadowOf(app).getNextStartedService();
        assertEquals(HostMonitorService.class.getName(), started.getComponent().getClassName());
        matches.clear();
        activity.getWindow().getDecorView().findViewsWithText(matches, "監視を停止", View.FIND_VIEWS_WITH_TEXT);
        assertEquals(1, matches.size());
        assertTrue(matches.get(0).performClick());
        assertFalse(store.read().enabled);
        assertTrue(store.read().revision > enabledRevision);
        assertEquals(HostMonitorService.class.getName(),
                Shadows.shadowOf(app).getNextStoppedService().getComponent().getClassName());
        controller.pause().stop().destroy();
    }

    @Test public void openingTheActivityResumesAnEnabledMonitorWithoutChangingItsRevision() {
        assertTrue(store.setEnabled(true));
        long revision = store.read().revision;
        ActivityController<MainActivity> controller = Robolectric.buildActivity(MainActivity.class).setup();
        Intent resumed = Shadows.shadowOf(app).getNextStartedService();
        assertNotNull(resumed);
        assertEquals(HostMonitorService.class.getName(), resumed.getComponent().getClassName());
        assertEquals(revision, store.read().revision);
        controller.pause().stop().destroy();
        assertTrue(store.setEnabled(false));
        ActivityController<MainActivity> disabled = Robolectric.buildActivity(MainActivity.class).setup();
        assertNull(Shadows.shadowOf(app).getNextStartedService());
        assertFalse(store.read().enabled);
        disabled.pause().stop().destroy();
    }

    @Test public void bootRequiresAnEnabledChoiceAndTheActualBootAction() {
        HostBootReceiver receiver = new HostBootReceiver();
        receiver.onReceive(app, new Intent(Intent.ACTION_BOOT_COMPLETED));
        assertNull(Shadows.shadowOf(app).getNextStartedService());
        assertTrue(store.setEnabled(true));
        receiver.onReceive(app, new Intent("other"));
        assertNull(Shadows.shadowOf(app).getNextStartedService());
        receiver.onReceive(app, new Intent(Intent.ACTION_BOOT_COMPLETED));
        Intent started = Shadows.shadowOf(app).getNextStartedService();
        assertNotNull(started);
        assertEquals(HostMonitorService.class.getName(), started.getComponent().getClassName());
    }

    public static class HealthyService extends HostMonitorService {
        int monitors;
        @Override HostMonitor createMonitor() {
            monitors++;
            return new HostMonitor(HostPreferences.get(this), new HostMonitor.Clock() {
                public long elapsedRealtime() { return 0; }
                public int bootCount() { return 1; }
            }, () -> true, new HostMonitor.Launcher() {
                public HostMonitor.Status availability() { return HostMonitor.Status.READY; }
                public void launch() { throw new AssertionError("healthy server cannot launch"); }
            });
        }
    }

    @Test public void stickyAndRepeatedStartsUseOneMonitorAndRespectDisabledState() {
        ServiceController<HealthyService> controller = Robolectric.buildService(HealthyService.class).create();
        HealthyService service = controller.get();
        assertEquals(Service.START_NOT_STICKY, service.onStartCommand(null, 0, 1));
        assertTrue(store.setEnabled(true));
        assertEquals(Service.START_STICKY, service.onStartCommand(new Intent(), 0, 2));
        assertEquals(Service.START_STICKY, service.onStartCommand(null, 0, 3));
        assertEquals(1, service.monitors);
        assertNotNull(Shadows.shadowOf(service).getLastForegroundNotification());
        assertTrue(store.setEnabled(false));
        assertEquals(Service.START_NOT_STICKY, service.onStartCommand(null, 0, 4));
        controller.destroy();
    }
}
