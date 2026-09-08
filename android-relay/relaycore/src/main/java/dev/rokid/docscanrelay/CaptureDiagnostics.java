package dev.rokid.docscanrelay;

import java.util.Locale;

/**
 * One-line capture measurements for the operator running a real-device sweep.
 *
 * <p>The decisive number during a capture sweep is the size of the JPEG that
 * CXR-L handed back, because the callback travels as an {@code oneway} Binder
 * transaction and an oversized payload is dropped silently instead of raising
 * an error. Without that number a failed probe is indistinguishable from a
 * firmware refusal, so these strings go to both logcat and the phone screen —
 * the operator wearing the glasses cannot read an adb session.</p>
 */
public final class CaptureDiagnostics {
    /**
     * The practical ceiling for an async callback: the per-process Binder
     * buffer is about 1MB and the kernel keeps half of it for async work.
     */
    public static final int ASYNC_BINDER_BUDGET_BYTES = 512 * 1024;

    private CaptureDiagnostics() {
    }

    public static String photoReceived(
            PhotoCaptureSettings settings, int bytes, long elapsedMillis) {
        String line = String.format(
                Locale.US,
                "%s %dKB 予算%d%% %ss",
                settings.describe(),
                Math.round(bytes / 1024.0),
                Math.round(bytes * 100.0 / ASYNC_BINDER_BUDGET_BYTES),
                seconds(elapsedMillis));
        return bytes > ASYNC_BINDER_BUDGET_BYTES ? line + " 予算超過" : line;
    }

    public static String photoNoCallback(PhotoCaptureSettings settings, long elapsedMillis) {
        return settings.describe() + " 応答なし " + seconds(elapsedMillis) + "s";
    }

    public static String serviceIdentity(String version, int versionCode) {
        String trimmed = version == null ? "" : version.trim();
        if (trimmed.isEmpty()) {
            return "CXR-L 不明";
        }
        return "CXR-L " + trimmed + " (code " + versionCode + ")";
    }

    private static String seconds(long millis) {
        return String.format(Locale.US, "%.1f", millis / 1000.0);
    }
}
