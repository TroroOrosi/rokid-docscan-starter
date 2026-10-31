package dev.rokid.docscanrelay;

import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Iterator;
import java.util.Objects;
import java.util.UUID;
import org.json.JSONException;
import org.json.JSONObject;

/** Identity of an observed native original, not a verdict about its image quality. */
public final class CaptureProvenance {
    private static final int MAX_HTTP_BYTES = 8 * 1024;
    public final String sourceKind;
    public final String captureId;
    public final String jpegSha256;
    public final int width, height;
    public final Long imageTimestampNanos, resultTimestampNanos, frameNumber, exposureNanos;
    public final Integer sensitivityIso, afState, aeState;
    public final String localSessionId;
    public final int pageIndex, rotationDegrees;

    private CaptureProvenance(String sourceKind, String captureId, String jpegSha256, int width, int height,
            Long imageTimestampNanos, Long resultTimestampNanos, Long frameNumber, Long exposureNanos,
            Integer sensitivityIso, Integer afState, Integer aeState,
            String localSessionId, int pageIndex, int rotationDegrees) {
        this.sourceKind = sourceKind;
        this.captureId = captureId;
        this.jpegSha256 = jpegSha256;
        this.width = width;
        this.height = height;
        this.imageTimestampNanos = imageTimestampNanos;
        this.resultTimestampNanos = resultTimestampNanos;
        this.frameNumber = frameNumber;
        this.exposureNanos = exposureNanos;
        this.sensitivityIso = sensitivityIso;
        this.afState = afState;
        this.aeState = aeState;
        this.localSessionId = localSessionId;
        this.pageIndex = pageIndex;
        this.rotationDegrees = rotationDegrees;
    }

    /** Metadata belongs to this JPEG only when its sensor timestamp matches exactly. */
    public static CaptureProvenance nativeStill(byte[] jpeg, int width, int height,
            Long imageTimestamp, Long resultTimestamp, Long frameNumber, Long exposureNanos,
            Integer sensitivityIso, Integer afState, Integer aeState) {
        return captured("native_still", jpeg, width, height, imageTimestamp, resultTimestamp,
                frameNumber, exposureNanos, sensitivityIso, afState, aeState);
    }

    /** A reprocessed original must retain the selected source exposure's exact result. */
    public static CaptureProvenance zslReprocess(byte[] jpeg, int width, int height,
            Long imageTimestamp, Long resultTimestamp, Long frameNumber, Long exposureNanos,
            Integer sensitivityIso, Integer afState, Integer aeState) {
        if (positive(imageTimestamp) == null || !imageTimestamp.equals(positive(resultTimestamp))) {
            throw new IllegalArgumentException("ZSL source exposure must match its image");
        }
        return captured("zsl_reprocess", jpeg, width, height, imageTimestamp, resultTimestamp,
                frameNumber, exposureNanos, sensitivityIso, afState, aeState);
    }

    private static CaptureProvenance captured(String sourceKind, byte[] jpeg, int width, int height,
            Long imageTimestamp, Long resultTimestamp, Long frameNumber, Long exposureNanos,
            Integer sensitivityIso, Integer afState, Integer aeState) {
        if (jpeg == null || jpeg.length == 0 || width <= 0 || height <= 0) {
            throw new IllegalArgumentException("native original is required");
        }
        Long timestamp = positive(imageTimestamp);
        boolean matched = timestamp != null && timestamp.equals(positive(resultTimestamp));
        return new CaptureProvenance(sourceKind, UUID.randomUUID().toString(), sha256(jpeg), width, height,
                timestamp, matched ? timestamp : null,
                matched && frameNumber != null && frameNumber >= 0 ? frameNumber : null,
                matched ? positive(exposureNanos) : null,
                matched && sensitivityIso != null && sensitivityIso > 0 ? sensitivityIso : null,
                matched && afState != null && afState >= 0 ? afState : null,
                matched && aeState != null && aeState >= 0 ? aeState : null, null, -1, -1);
    }

    CaptureProvenance bind(String sessionId, int pageIndex, int rotationDegrees) {
        if (!validUuid(sessionId) || pageIndex < 0 || !validRotation(rotationDegrees)) {
            throw new IllegalArgumentException("invalid native capture association");
        }
        if (localSessionId != null) {
            if (!localSessionId.equals(sessionId) || this.pageIndex != pageIndex
                    || this.rotationDegrees != rotationDegrees) {
                throw new IllegalArgumentException("native capture association cannot change");
            }
            return this;
        }
        return new CaptureProvenance(sourceKind, captureId, jpegSha256, width, height, imageTimestampNanos,
                resultTimestampNanos, frameNumber, exposureNanos, sensitivityIso, afState, aeState,
                sessionId, pageIndex, rotationDegrees);
    }

    boolean matches(byte[] jpeg, int page, int rotation) {
        return jpeg != null && jpegSha256.equals(sha256(jpeg))
                && (localSessionId == null || (pageIndex == page && rotationDegrees == rotation));
    }

    JSONObject toUploadJson(byte[] jpeg, int page, int rotation) throws JSONException {
        if (!validUuid(localSessionId) || !matches(jpeg, page, rotation)) {
            throw new IllegalArgumentException("撮影情報と原本が一致しません");
        }
        JSONObject json = httpMetadata();
        requireHttpSize(json);
        return json;
    }

    void requireUploadEcho(JSONObject received) throws JSONException {
        JSONObject expected = httpMetadata();
        if (received == null || received.length() != expected.length()) {
            throw new JSONException("撮影情報の受領を確認できません");
        }
        requireHttpSize(received);
        for (Iterator<String> keys = expected.keys(); keys.hasNext();) {
            String key = keys.next();
            Object wanted = expected.get(key), actual = received.opt(key);
            boolean matches = wanted instanceof Number
                    ? (actual instanceof Integer || actual instanceof Long)
                        && ((Number)wanted).longValue() == ((Number)actual).longValue()
                    : wanted == JSONObject.NULL ? actual == JSONObject.NULL : wanted.equals(actual);
            if (!matches) throw new JSONException("撮影情報の受領を確認できません");
        }
    }

    private JSONObject httpMetadata() throws JSONException {
        return new JSONObject().put("schema", 1).put("source_kind", sourceKind)
                .put("capture_id", captureId).put("jpeg_sha256", jpegSha256)
                .put("width", width).put("height", height).put("local_session_id", localSessionId)
                .put("page_index", pageIndex).put("rotation_degrees", rotationDegrees)
                .put("image_timestamp_ns", nullable(imageTimestampNanos))
                .put("result_timestamp_ns", nullable(resultTimestampNanos))
                .put("frame_number", nullable(frameNumber)).put("exposure_ns", nullable(exposureNanos))
                .put("sensitivity_iso", nullable(sensitivityIso)).put("af_state", nullable(afState))
                .put("ae_state", nullable(aeState));
    }

    private static Object nullable(Object value) { return value == null ? JSONObject.NULL : value; }
    private static void requireHttpSize(JSONObject json) throws JSONException {
        if (json.toString().getBytes(StandardCharsets.UTF_8).length > MAX_HTTP_BYTES) {
            throw new JSONException("撮影情報が大きすぎます");
        }
    }

    void writeTo(DataOutputStream data) throws IOException {
        if (!sourceKind.equals("native_still")) {
            throw new IOException("capture producer requires pending record v5");
        }
        writeFields(data);
    }

    void writeToV5(DataOutputStream data) throws IOException {
        data.writeUTF(sourceKind);
        writeFields(data);
    }

    private void writeFields(DataOutputStream data) throws IOException {
        data.writeUTF(captureId);
        data.writeUTF(jpegSha256);
        data.writeInt(width);
        data.writeInt(height);
        writeLong(data, imageTimestampNanos);
        writeLong(data, resultTimestampNanos);
        writeLong(data, frameNumber);
        writeLong(data, exposureNanos);
        writeLong(data, sensitivityIso == null ? null : sensitivityIso.longValue());
        writeLong(data, afState == null ? null : afState.longValue());
        writeLong(data, aeState == null ? null : aeState.longValue());
        data.writeUTF(localSessionId == null ? "" : localSessionId);
        data.writeInt(pageIndex);
        data.writeInt(rotationDegrees);
    }

    static CaptureProvenance readFrom(DataInputStream data) throws IOException {
        return readFields(data, "native_still");
    }

    static CaptureProvenance readFromV5(DataInputStream data) throws IOException {
        String sourceKind = data.readUTF();
        if (!sourceKind.equals("native_still") && !sourceKind.equals("zsl_reprocess")) {
            throw new IOException("unsupported capture producer");
        }
        return readFields(data, sourceKind);
    }

    private static CaptureProvenance readFields(DataInputStream data, String sourceKind) throws IOException {
        String captureId = data.readUTF(), sha = data.readUTF();
        int width = data.readInt(), height = data.readInt();
        Long timestamp = readLong(data), resultTimestamp = readLong(data);
        Long frame = readLong(data), exposure = readLong(data);
        Integer iso = readInt(data), af = readInt(data), ae = readInt(data);
        String session = data.readUTF();
        int page = data.readInt(), rotation = data.readInt();
        boolean matched = timestamp != null && timestamp.equals(resultTimestamp);
        if (!validUuid(captureId) || !sha.matches("[0-9a-f]{64}") || width <= 0 || height <= 0
                || (timestamp != null && timestamp <= 0) || (resultTimestamp != null && !matched)
                || (sourceKind.equals("zsl_reprocess") && !matched)
                || (frame != null && (frame < 0 || !matched))
                || (exposure != null && (exposure <= 0 || !matched))
                || (iso != null && (iso <= 0 || !matched))
                || (af != null && (af < 0 || !matched)) || (ae != null && (ae < 0 || !matched))
                || (session.isEmpty() ? page != -1 || rotation != -1
                    : !validUuid(session) || page < 0 || !validRotation(rotation))) {
            throw new IOException("invalid native capture provenance");
        }
        return new CaptureProvenance(sourceKind, captureId, sha, width, height, timestamp, resultTimestamp,
                frame, exposure, iso, af, ae, session.isEmpty() ? null : session, page, rotation);
    }

    private static Long positive(Long value) { return value != null && value > 0 ? value : null; }
    private static boolean validRotation(int value) { return value >= 0 && value < 360 && value % 90 == 0; }
    private static boolean validUuid(String value) {
        return value != null && value.matches("[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}");
    }
    private static void writeLong(DataOutputStream data, Long value) throws IOException {
        data.writeBoolean(value != null);
        if (value != null) data.writeLong(value);
    }
    private static Long readLong(DataInputStream data) throws IOException {
        return data.readBoolean() ? data.readLong() : null;
    }
    private static Integer readInt(DataInputStream data) throws IOException {
        Long value = readLong(data);
        if (value == null) return null;
        if (value < Integer.MIN_VALUE || value > Integer.MAX_VALUE) throw new IOException("invalid capture metadata");
        return value.intValue();
    }
    private static String sha256(byte[] jpeg) {
        try {
            StringBuilder hex = new StringBuilder(64);
            for (byte value : MessageDigest.getInstance("SHA-256").digest(jpeg)) {
                hex.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
            }
            return hex.toString();
        } catch (NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
    }

    @Override public boolean equals(Object other) {
        if (!(other instanceof CaptureProvenance)) return false;
        CaptureProvenance value = (CaptureProvenance) other;
        return sourceKind.equals(value.sourceKind) && captureId.equals(value.captureId)
                && jpegSha256.equals(value.jpegSha256)
                && width == value.width && height == value.height
                && Objects.equals(imageTimestampNanos, value.imageTimestampNanos)
                && Objects.equals(resultTimestampNanos, value.resultTimestampNanos)
                && Objects.equals(frameNumber, value.frameNumber) && Objects.equals(exposureNanos, value.exposureNanos)
                && Objects.equals(sensitivityIso, value.sensitivityIso) && Objects.equals(afState, value.afState)
                && Objects.equals(aeState, value.aeState) && Objects.equals(localSessionId, value.localSessionId)
                && pageIndex == value.pageIndex && rotationDegrees == value.rotationDegrees;
    }
    @Override public int hashCode() { return Objects.hash(sourceKind, captureId); }
}
