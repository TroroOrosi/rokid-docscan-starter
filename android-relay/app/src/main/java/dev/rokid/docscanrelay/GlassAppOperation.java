package dev.rokid.docscanrelay;

/**
 * Records the outcome of one glasses-app install or launch.
 *
 * <p>Mirrors {@link GlassAppProbe}, which answers the same shape of question
 * for {@code queryGlassAppInstalled}, but keeps a success/failure result rather
 * than an installed flag, and keeps the deadline verdict provisional for the
 * same reason: Hi Rokid can refuse the transaction, accept it and never call
 * back, or answer late. Only the first two are real negatives.
 *
 * <p>The timeout is per operation because they are not comparable. An install
 * ships an APK over the phone-to-glasses link and then runs a package install
 * on the far side; a launch is a request to start an activity already present.
 */
final class GlassAppOperation {

    enum Verdict {
        IDLE,
        PENDING,
        SUCCEEDED,
        FAILED,
        CALL_FAILED,
        NO_RESPONSE
    }

    private final String name;
    private final long timeoutMillis;

    private Verdict outcome = Verdict.IDLE;
    private String detail = "";
    private long deadlineMillis;
    private String failure = "";

    GlassAppOperation(String name, long timeoutMillis) {
        if (name == null || name.trim().isEmpty()) {
            throw new IllegalArgumentException("operation needs a name");
        }
        if (timeoutMillis <= 0) {
            throw new IllegalArgumentException("operation timeout must be positive");
        }
        this.name = name;
        this.timeoutMillis = timeoutMillis;
    }

    synchronized void start(long nowMillis, String detail) {
        this.detail = detail == null ? "" : detail;
        this.deadlineMillis = nowMillis + timeoutMillis;
        this.outcome = Verdict.PENDING;
        this.failure = "";
    }

    /**
     * @return true when this result resolved the outstanding operation.
     */
    synchronized boolean onResult(long nowMillis, boolean succeeded) {
        if (outcome != Verdict.PENDING) {
            return false;
        }
        this.outcome = succeeded ? Verdict.SUCCEEDED : Verdict.FAILED;
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

    synchronized String summary(long nowMillis) {
        StringBuilder line = new StringBuilder("glass-app-")
                .append(name)
                .append(" target=")
                .append(detail)
                .append(" verdict=")
                .append(verdict(nowMillis));
        if (!failure.isEmpty()) {
            line.append(" failure=").append(failure);
        }
        return line.toString();
    }
}
