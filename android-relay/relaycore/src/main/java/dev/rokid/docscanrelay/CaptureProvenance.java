package dev.rokid.docscanrelay;

import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Objects;
import java.util.UUID;

/** Identity of an observed native original, not a verdict about its image quality. */
public final class CaptureProvenance {
    public final String sourceKind = "native_still";
    public final String captureId;
    public final String jpegSha256;
    public final int width, height;
    public final Long imageTimestampNanos, resultTimestampNanos, frameNumber, exposureNanos;
    public final Integer sensitivityIso, afState, aeState;
    public final String localSessionId;
    public final int pageIndex, rotationDegrees;

    private CaptureProvenance(String captureId, String jpegSha256, int width, int height,
            Long imageTimestampNanos, Long resultTimestampNanos, Long frameNumber, Long exposureNanos,
            Integer sensitivityIso, Integer afState, Integer aeState,
            String localSessionId, int pageIndex, int rotationDegrees) {
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
        if (jpeg == null || jpeg.length == 0 || width <= 0 || height <= 0) {
            throw new IllegalArgumentException("native original is required");
        }
        Long timestamp = positive(imageTimestamp);
        boolean matched = timestamp != null && timestamp.equals(positive(resultTimestamp));
        return new CaptureProvenance(UUID.randomUUID().toString(), sha256(jpeg), width, height,
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
        return new CaptureProvenance(captureId, jpegSha256, width, height, imageTimestampNanos,
                resultTimestampNanos, frameNumber, exposureNanos, sensitivityIso, afState, aeState,
                sessionId, pageIndex, rotationDegrees);
    }

    boolean matches(byte[] jpeg, int page, int rotation) {
        return jpeg != null && jpegSha256.equals(sha256(jpeg))
                && (localSessionId == null || (pageIndex == page && rotationDegrees == rotation));
    }

    void writeTo(DataOutputStream data) throws IOException {
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
                || (frame != null && (frame < 0 || !matched))
                || (exposure != null && (exposure <= 0 || !matched))
                || (iso != null && (iso <= 0 || !matched))
                || (af != null && (af < 0 || !matched)) || (ae != null && (ae < 0 || !matched))
                || (session.isEmpty() ? page != -1 || rotation != -1
                    : !validUuid(session) || page < 0 || !validRotation(rotation))) {
            throw new IOException("invalid native capture provenance");
        }
        return new CaptureProvenance(captureId, sha, width, height, timestamp, resultTimestamp,
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
        return captureId.equals(value.captureId) && jpegSha256.equals(value.jpegSha256)
                && width == value.width && height == value.height
                && Objects.equals(imageTimestampNanos, value.imageTimestampNanos)
                && Objects.equals(resultTimestampNanos, value.resultTimestampNanos)
                && Objects.equals(frameNumber, value.frameNumber) && Objects.equals(exposureNanos, value.exposureNanos)
                && Objects.equals(sensitivityIso, value.sensitivityIso) && Objects.equals(afState, value.afState)
                && Objects.equals(aeState, value.aeState) && Objects.equals(localSessionId, value.localSessionId)
                && pageIndex == value.pageIndex && rotationDegrees == value.rotationDegrees;
    }
    @Override public int hashCode() { return captureId.hashCode(); }
}
