package dev.rokid.docscanrelay;

import java.util.Objects;
import org.json.JSONException;
import org.json.JSONObject;

/** An optional caller assertion for diagnostics, never a native-image quality receipt. */
public final class CaptureInspectionOrigin {
    /** The existing display/wear generation, sampled before issuing the native request. */
    public static final class Context {
        public final String deviceId;
        public final long generation;

        public Context(String deviceId, long generation) {
            if (deviceId == null || !deviceId.matches("[A-Za-z0-9_.:-]{1,128}") || generation < 0) {
                throw new IllegalArgumentException("invalid capture inspection context");
            }
            this.deviceId = deviceId;
            this.generation = generation;
        }

        @Override public boolean equals(Object other) {
            return other instanceof Context && generation == ((Context) other).generation
                    && deviceId.equals(((Context) other).deviceId);
        }

        @Override public int hashCode() { return Objects.hash(deviceId, generation); }
    }

    private final Context context;
    private final String localSessionId, captureId;
    private final long documentId;

    CaptureInspectionOrigin(Context context, CaptureProvenance source, long documentId) {
        if (context == null || source == null || documentId <= 0 || documentId > Integer.MAX_VALUE
                || !validUuid(source.localSessionId) || !validUuid(source.captureId)) {
            throw new IllegalArgumentException("invalid capture inspection origin");
        }
        this.context = context;
        this.localSessionId = source.localSessionId;
        this.captureId = source.captureId;
        this.documentId = documentId;
    }

    /** A stale/mismatched optional diagnostic must not change ordinary image upload behavior. */
    JSONObject forUpload(long documentId, CaptureProvenance source) throws JSONException {
        if (source == null || this.documentId != documentId || !localSessionId.equals(source.localSessionId)
                || !captureId.equals(source.captureId)) return null;
        return new JSONObject().put("schema", 1).put("device_id", context.deviceId)
                .put("generation", context.generation).put("local_session_id", localSessionId)
                .put("capture_id", captureId).put("document_id", documentId);
    }

    private static boolean validUuid(String value) {
        return value != null && value.matches("[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}");
    }
}
