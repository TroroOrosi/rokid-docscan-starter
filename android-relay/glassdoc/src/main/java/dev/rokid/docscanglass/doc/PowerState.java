package dev.rokid.docscanglass.doc;

import android.content.Context;
import android.content.SharedPreferences;
import java.io.IOException;

/** One process-wide lock for Activity and wear-service generation/sequence allocation. */
final class PowerState {
    private static final Object LOCK = new Object();
    private final SharedPreferences preferences;
    PowerState(SharedPreferences preferences) { this.preferences = preferences; }
    static PowerState forContext(Context context) {
        return new PowerState(preferencesForContext(context));
    }
    static SharedPreferences preferencesForContext(Context context) {
        String name = DocScanGlassActivity.class.getName();
        String prefix = context.getPackageName() + ".";
        if (name.startsWith(prefix)) name = name.substring(prefix.length());
        return context.getSharedPreferences(name, Context.MODE_PRIVATE);
    }
    static final class Snapshot {
        final long generation, sequence, session;
        final String phase, display, entry;
        final Long answerRevision;
        Snapshot(long generation, long sequence, long session, String phase, String display, String entry, Long answerRevision) {
            this.generation = generation; this.sequence = sequence; this.session = session;
            this.phase = phase; this.display = display; this.entry = entry;
            this.answerRevision = answerRevision;
        }
    }
    Snapshot load() {
        synchronized (LOCK) {
            return new Snapshot(preferences.getLong("power_generation", 0), preferences.getLong("power_sequence", 0),
                    preferences.getLong("power_session", 0), preferences.getString("power_phase", "closed"),
                    preferences.getString("power_display", null), preferences.getString("power_entry", null),
                    preferences.getLong("power_ack_revision", -1) < 0 ? null : preferences.getLong("power_ack_revision", -1));
        }
    }
    Snapshot begin(long minimum) throws IOException {
        synchronized (LOCK) {
            Snapshot next = new Snapshot(Math.addExact(Math.max(load().generation, minimum), 1), 0, 0, "capturing", "wake", null, null);
            write(next); return next;
        }
    }
    Snapshot publish(long generation, long session, String phase, String display) throws IOException {
        synchronized (LOCK) {
            Snapshot old = load();
            return publish(generation, session, phase, display, old.session == session ? old.answerRevision : null);
        }
    }
    Snapshot publish(long generation, long session, String phase, String display, Long answerRevision) throws IOException {
        synchronized (LOCK) {
            if (answerRevision != null && (answerRevision < 0 || session <= 0)) throw new IllegalArgumentException("invalid received revision");
            Snapshot old = load();
            if (old.generation != generation) return null;
            Snapshot next = new Snapshot(generation, Math.addExact(old.sequence, 1), session, phase, display, null, answerRevision);
            write(next); return next;
        }
    }
    Snapshot wear(boolean initial, long coldGeneration) throws IOException {
        synchronized (LOCK) {
            Snapshot old = load();
            if (initial && !"chooser".equals(old.phase) && old.generation != coldGeneration) return null;
            Snapshot next = new Snapshot(Math.addExact(old.generation, 1), 1, 0, "chooser", "wake", "chooser", null);
            write(next); return next;
        }
    }
    private void write(Snapshot value) throws IOException {
        if (!preferences.edit().putLong("power_generation", value.generation).putLong("power_sequence", value.sequence)
                .putLong("power_session", value.session).putString("power_phase", value.phase)
                .putString("power_display", value.display).putString("power_entry", value.entry)
                .putLong("power_ack_revision", value.answerRevision == null ? -1 : value.answerRevision).commit()) {
            throw new IOException("display state unavailable");
        }
    }
}
