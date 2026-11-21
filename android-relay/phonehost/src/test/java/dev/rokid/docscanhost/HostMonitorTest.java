package dev.rokid.docscanhost;

import static org.junit.Assert.*;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.junit.Test;

public class HostMonitorTest {
    private static final class MemoryStore implements HostMonitor.Store {
        boolean enabled;
        long revision;
        long lastAttempt = -1;
        int lastBoot = -1;
        boolean writable = true;

        @Override public synchronized HostMonitor.Snapshot read() {
            return new HostMonitor.Snapshot(enabled, revision, lastAttempt, lastBoot);
        }

        @Override public synchronized boolean reserveAttempt(long elapsed, int boot) {
            if (!writable) return false;
            lastAttempt = elapsed;
            lastBoot = boot;
            return true;
        }

        synchronized void enabled(boolean value) {
            enabled = value;
            revision++;
        }
    }

    private static final class FakeClock implements HostMonitor.Clock {
        long elapsed;
        int boot = 1;
        @Override public long elapsedRealtime() { return elapsed; }
        @Override public int bootCount() { return boot; }
    }

    private static final class FakeLauncher implements HostMonitor.Launcher {
        HostMonitor.Status availability = HostMonitor.Status.READY;
        int launches;
        boolean deniedDuringLaunch;
        @Override public HostMonitor.Status availability() { return availability; }
        @Override public void launch() {
            launches++;
            if (deniedDuringLaunch) throw new SecurityException();
        }
    }

    private final MemoryStore store = new MemoryStore();
    private final FakeClock clock = new FakeClock();
    private final FakeLauncher launcher = new FakeLauncher();

    private HostMonitor monitor(HostMonitor.HealthCheck health) {
        return new HostMonitor(store, clock, health, launcher);
    }

    @Test public void disabledByDefaultAndHealthyServerNeverStartTermux() {
        HostMonitor monitor = monitor(() -> true);
        assertFalse(monitor.start());
        assertEquals(HostMonitor.Status.STOPPED, monitor.check().status);
        store.enabled(true);
        assertTrue(monitor.start());
        clock.elapsed = 600_000;
        assertEquals(HostMonitor.Status.READY, monitor.check().status);
        assertEquals(0, launcher.launches);
    }

    @Test public void unavailableServerHasStartupGraceAndPersistentCooldown() {
        store.enabled(true);
        HostMonitor monitor = monitor(() -> false);
        assertTrue(monitor.start());
        assertFalse(monitor.start());
        clock.elapsed = 59_999;
        assertEquals(HostMonitor.Status.STARTING, monitor.check().status);
        clock.elapsed = 60_000;
        assertEquals(HostMonitor.Status.RECOVERY_REQUESTED, monitor.check().status);
        assertEquals(1, launcher.launches);
        assertEquals(60_000, store.lastAttempt);
        clock.elapsed = 119_999;
        assertEquals(HostMonitor.Status.COOLDOWN, monitor.check().status);
        assertEquals(1, launcher.launches);
        clock.elapsed = 120_000;
        monitor.check();
        assertEquals(2, launcher.launches);
    }

    @Test public void restartRemembersEnabledChoiceAndAttempt() {
        store.enabled(true);
        HostMonitor first = monitor(() -> false);
        first.start();
        clock.elapsed = 60_000;
        first.check();
        first.stop();
        HostMonitor second = monitor(() -> false);
        second.start();
        clock.elapsed = 119_999;
        second.check();
        assertEquals(1, launcher.launches);
        clock.elapsed = 120_000;
        second.check();
        assertEquals(2, launcher.launches);
        store.enabled(false);
        HostMonitor disabledRestart = monitor(() -> false);
        assertFalse(disabledRestart.start());
        disabledRestart.check();
        assertEquals(2, launcher.launches);
    }

    @Test public void newBootDoesNotWaitForPreviousUptime() {
        store.enabled(true);
        store.reserveAttempt(9_000_000, 1);
        clock.boot = 2;
        HostMonitor monitor = monitor(() -> false);
        monitor.start();
        clock.elapsed = 60_000;
        assertEquals(HostMonitor.Status.RECOVERY_REQUESTED, monitor.check().status);
        assertEquals(1, launcher.launches);
    }

    @Test public void missingPermissionOrPackageNeverLaunches() {
        store.enabled(true);
        HostMonitor monitor = monitor(() -> false);
        monitor.start();
        clock.elapsed = 60_000;
        launcher.availability = HostMonitor.Status.PERMISSION_REQUIRED;
        assertEquals(HostMonitor.Status.PERMISSION_REQUIRED, monitor.check().status);
        launcher.availability = HostMonitor.Status.TERMUX_MISSING;
        clock.elapsed += 60_000;
        assertEquals(HostMonitor.Status.TERMUX_MISSING, monitor.check().status);
        assertEquals(0, launcher.launches);
        assertEquals(-1, store.lastAttempt);
    }

    @Test public void failedDispatchStillReservesCooldownAndFailedSaveNeverLaunches() {
        store.enabled(true);
        HostMonitor monitor = monitor(() -> false);
        monitor.start();
        clock.elapsed = 60_000;
        store.writable = false;
        assertEquals(HostMonitor.Status.STORAGE_FAILED, monitor.check().status);
        assertEquals(0, launcher.launches);
        store.writable = true;
        launcher.deniedDuringLaunch = true;
        assertEquals(HostMonitor.Status.PERMISSION_REQUIRED, monitor.check().status);
        assertEquals(1, launcher.launches);
        clock.elapsed += 15_000;
        assertEquals(HostMonitor.Status.COOLDOWN, monitor.check().status);
        assertEquals(1, launcher.launches);
    }

    @Test public void stopDuringHealthReadCannotDispatchRecovery() throws Exception {
        race(false);
    }

    @Test public void disableAndReenableDuringOldHealthReadCannotDispatchRecovery() throws Exception {
        race(true);
    }

    private void race(boolean reenable) throws Exception {
        CountDownLatch entered = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        store.enabled(true);
        HostMonitor monitor = monitor(() -> {
            entered.countDown();
            try { assertTrue(release.await(2, TimeUnit.SECONDS)); }
            catch (InterruptedException error) { throw new AssertionError(error); }
            return false;
        });
        monitor.start();
        clock.elapsed = 60_000;
        Thread worker = new Thread(monitor::check);
        worker.start();
        assertTrue(entered.await(2, TimeUnit.SECONDS));
        if (reenable) {
            store.enabled(false);
            store.enabled(true);
        } else {
            monitor.stop();
        }
        release.countDown();
        worker.join(2_000);
        assertFalse(worker.isAlive());
        assertEquals(0, launcher.launches);
    }
}
