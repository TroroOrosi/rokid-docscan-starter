package dev.rokid.docscanrelay;

/**
 * Records the outcome of one {@code queryGlassAppInstalled} probe.
 *
 * <p>The AIDL bundled in client-l 1.0.1 and 1.1.1 declares
 * {@code queryGlassAppInstalled(String, IGlassAppCallback)}, but a declaration
 * is not an implementation. Hi Rokid can refuse the call at the Binder
 * boundary, or accept it and never invoke the callback; only a deadline tells
 * the second case from a slow answer. The deadline verdict is therefore
 * provisional: a callback arriving after it still proves the method is
 * implemented, which is the question this probe exists to answer.</p>
 */
final class GlassAppProbe {
    enum Verdict {
        IDLE,
        PENDING,
        ANSWERED,
        CALL_FAILED,
        NO_RESPONSE
    }

    private final long timeoutMillis;
    private Verdict outcome = Verdict.IDLE;
    private String packageName = "";
    private long deadlineMillis;
    private boolean installed;
    private String failure = "";

    GlassAppProbe(long timeoutMillis) {
        if (timeoutMillis <= 0) {
            throw new IllegalArgumentException("probe timeout must be positive");
        }
        this.timeoutMillis = timeoutMillis;
    }

    synchronized void start(long nowMillis, String packageName) {
        this.packageName = packageName;
        this.deadlineMillis = nowMillis + timeoutMillis;
        this.outcome = Verdict.PENDING;
        this.installed = false;
        this.failure = "";
    }

    /**
     * @return true when this result resolved the outstanding probe.
     */
    synchronized boolean onQueryResult(
            long nowMillis,
            String packageName,
            boolean installed
    ) {
        if (outcome != Verdict.PENDING || !this.packageName.equals(packageName)) {
            return false;
        }
        this.installed = installed;
        this.outcome = Verdict.ANSWERED;
        return true;
    }

    synchronized void onCallFailed(long nowMillis, String reason) {
        if (outcome != Verdict.PENDING) {
            return;
        }
        this.failure = reason;
        this.outcome = Verdict.CALL_FAILED;
    }

    synchronized Verdict verdict(long nowMillis) {
        if (outcome == Verdict.PENDING && nowMillis > deadlineMillis) {
            return Verdict.NO_RESPONSE;
        }
        return outcome;
    }

    synchronized boolean installed() {
        return installed;
    }

    synchronized String summary(long nowMillis) {
        StringBuilder line = new StringBuilder("glass-app-probe pkg=")
                .append(packageName)
                .append(" verdict=")
                .append(verdict(nowMillis))
                .append(" installed=")
                .append(installed);
        if (!failure.isEmpty()) {
            line.append(" failure=").append(failure);
        }
        return line.toString();
    }
}
