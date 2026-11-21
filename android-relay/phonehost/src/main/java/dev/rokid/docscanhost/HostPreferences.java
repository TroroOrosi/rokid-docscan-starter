package dev.rokid.docscanhost;

import android.content.Context;
import android.content.SharedPreferences;

/** One process-wide lock orders durable choices and command reservations. */
final class HostPreferences implements HostMonitor.Store {
    private static HostPreferences instance;
    private final SharedPreferences preferences;
    private HostMonitor.Snapshot snapshot;

    static synchronized HostPreferences get(Context context) {
        if (instance == null) instance = new HostPreferences(context.getApplicationContext());
        return instance;
    }

    static synchronized void resetForTest() { instance = null; }

    private HostPreferences(Context context) {
        preferences = context.getSharedPreferences("host-monitor", Context.MODE_PRIVATE);
        snapshot = new HostMonitor.Snapshot(preferences.getBoolean("enabled", false),
                preferences.getLong("revision", 0), preferences.getLong("last-attempt-elapsed", -1),
                preferences.getInt("last-attempt-boot", -1));
    }

    @Override public synchronized HostMonitor.Snapshot read() { return snapshot; }

    synchronized boolean setEnabled(boolean enabled) {
        long revision = snapshot.revision + 1;
        boolean saved = preferences.edit().putBoolean("enabled", enabled)
                .putLong("revision", revision).commit();
        // A failed write must stop this process's old work, even though durability
        // cannot be promised. The activity reports that storage failure explicitly.
        snapshot = new HostMonitor.Snapshot(saved && enabled, revision,
                snapshot.lastAttemptElapsed, snapshot.lastAttemptBoot);
        return saved;
    }

    @Override public synchronized boolean reserveAttempt(long elapsed, int boot) {
        if (!preferences.edit().putLong("last-attempt-elapsed", elapsed)
                .putInt("last-attempt-boot", boot).commit()) return false;
        snapshot = new HostMonitor.Snapshot(snapshot.enabled, snapshot.revision, elapsed, boot);
        return true;
    }
}
