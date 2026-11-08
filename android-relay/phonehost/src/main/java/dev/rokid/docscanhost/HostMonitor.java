package dev.rokid.docscanhost;

/** Serialized recovery decisions for the phone's existing glasses runtime. */
final class HostMonitor {
    static final long POLL_MILLIS = 15_000;
    static final long STARTUP_GRACE_MILLIS = 60_000;
    static final long RETRY_MILLIS = 60_000;

    enum Status {
        STOPPED("停止中"),
        STARTING("実行環境の起動を待っています"),
        READY("実行環境に接続しています"),
        COOLDOWN("実行環境の復旧を待っています"),
        RECOVERY_REQUESTED("実行環境の起動を要求しました"),
        PERMISSION_REQUIRED("Termuxのコマンド実行権限が必要です"),
        TERMUX_MISSING("Termuxを確認できません"),
        STORAGE_FAILED("監視設定を保存できませんでした"),
        START_FAILED("実行環境の起動要求に失敗しました");

        final String text;
        Status(String text) { this.text = text; }
    }

    static final class Snapshot {
        final boolean enabled;
        final long revision;
        final long lastAttemptElapsed;
        final int lastAttemptBoot;

        Snapshot(boolean enabled, long revision, long lastAttemptElapsed, int lastAttemptBoot) {
            this.enabled = enabled;
            this.revision = revision;
            this.lastAttemptElapsed = lastAttemptElapsed;
            this.lastAttemptBoot = lastAttemptBoot;
        }
    }

    static final class Result {
        final long revision;
        final Status status;
        Result(long revision, Status status) {
            this.revision = revision;
            this.status = status;
        }
    }

    interface Store {
        Snapshot read();
        boolean reserveAttempt(long elapsed, int boot);
    }

    interface Clock {
        long elapsedRealtime();
        int bootCount();
    }

    interface HealthCheck { boolean healthy(); }
    interface Launcher {
        Status availability();
        void launch();
    }

    private final Store store;
    private final Clock clock;
    private final HealthCheck health;
    private final Launcher launcher;
    private boolean running;
    private long lifecycle;
    private long revision = -1;
    private long startedAt;

    HostMonitor(Store store, Clock clock, HealthCheck health, Launcher launcher) {
        this.store = store;
        this.clock = clock;
        this.health = health;
        this.launcher = launcher;
    }

    synchronized boolean start() {
        synchronized (store) {
            Snapshot saved = store.read();
            if (!saved.enabled || (running && revision == saved.revision)) return false;
            revision = saved.revision;
            startedAt = clock.elapsedRealtime();
            running = true;
            lifecycle++;
            return true;
        }
    }

    synchronized void stop() {
        running = false;
        lifecycle++;
    }

    Result check() {
        final long token;
        final long checkedRevision;
        synchronized (this) {
            if (!running) return new Result(revision, Status.STOPPED);
            token = lifecycle;
            checkedRevision = revision;
        }
        boolean healthy;
        try { healthy = health.healthy(); }
        catch (RuntimeException error) { healthy = false; }
        synchronized (this) {
            if (!running || lifecycle != token) {
                return new Result(checkedRevision, Status.STOPPED);
            }
            // Disable and a concurrent enable change the durable revision. A result
            // from an earlier activation cannot issue a new command after either.
            synchronized (store) {
                Snapshot saved = store.read();
                if (!saved.enabled || saved.revision != checkedRevision) {
                    return new Result(checkedRevision, Status.STOPPED);
                }
                return new Result(checkedRevision, decide(saved, healthy));
            }
        }
    }

    private Status decide(Snapshot saved, boolean healthy) {
        if (healthy) return Status.READY;
        long now = clock.elapsedRealtime();
        if (now - startedAt < STARTUP_GRACE_MILLIS) return Status.STARTING;
        int boot = clock.bootCount();
        if (saved.lastAttemptBoot == boot && saved.lastAttemptElapsed >= 0) {
            // Rebase an inconsistent future marker once. Wall-clock changes are
            // irrelevant because reservations use uptime and the Android boot count.
            if (saved.lastAttemptElapsed > now) {
                return store.reserveAttempt(now, boot) ? Status.COOLDOWN : Status.STORAGE_FAILED;
            }
            if (now - saved.lastAttemptElapsed < RETRY_MILLIS) return Status.COOLDOWN;
        }
        try {
            Status available = launcher.availability();
            if (available != Status.READY) return available;
            // Persist before Binder dispatch so an uncertain return or process death
            // cannot immediately repeat the same request in the next process.
            if (!store.reserveAttempt(now, boot)) return Status.STORAGE_FAILED;
            launcher.launch();
            return Status.RECOVERY_REQUESTED;
        } catch (SecurityException error) {
            return Status.PERMISSION_REQUIRED;
        } catch (RuntimeException error) {
            return Status.START_FAILED;
        }
    }
}
