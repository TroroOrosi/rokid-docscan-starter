package dev.rokid.docscanrelay;

/**
 * How a client describes itself to the server when it creates a document.
 *
 * <p>The phone relay and a glasses-side app run the same pipeline but are not
 * the same device: they capture through different hardware and link against
 * different SDKs. The pipeline therefore cannot name the client, and a library
 * module has no {@code BuildConfig.VERSION_NAME} to read anyway, so the app
 * that owns the capture surface supplies these three values.</p>
 */
public final class ClientIdentity {
    /** Reported as {@code capture_device}. */
    public final String captureDevice;

    /** Reported as {@code client_version}, conventionally {@code name/version}. */
    public final String clientVersion;

    /** Reported as {@code sdk_hint}: which SDK produced the capture. */
    public final String sdkHint;

    public ClientIdentity(String captureDevice, String clientVersion, String sdkHint) {
        this.captureDevice = required(captureDevice, "capture_device");
        this.clientVersion = required(clientVersion, "client_version");
        this.sdkHint = required(sdkHint, "sdk_hint");
    }

    private static String required(String value, String field) {
        String trimmed = value == null ? "" : value.trim();
        if (trimmed.isEmpty()) {
            throw new IllegalArgumentException(field + " は空にできません");
        }
        return trimmed;
    }
}
