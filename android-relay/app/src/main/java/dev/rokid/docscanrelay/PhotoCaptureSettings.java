package dev.rokid.docscanrelay;

import java.util.List;
import java.util.Locale;

/**
 * The {@code takePhoto(width, height, quality)} arguments used for one capture.
 *
 * <p>These are operator-adjustable because the usable capture size is a
 * property of the glasses firmware, not of this app. CXR-L delivers the JPEG
 * through {@code IImageStreamCallback.onImageReceived(byte[])}, so an oversized
 * photo exceeds the async Binder budget and no callback arrives at all. The
 * exact ceiling has to be measured on the target firmware, and every failed
 * probe costs a full re-authorization, so the sweep must be possible without
 * rebuilding the APK.</p>
 */
public final class PhotoCaptureSettings {
    /** Rejects values the 12MP sensor cannot produce before the IPC is spent. */
    static final int MAX_DIMENSION = 4096;

    public final int width;
    public final int height;
    public final int quality;

    private PhotoCaptureSettings(int width, int height, int quality) {
        this.width = width;
        this.height = height;
        this.quality = quality;
    }

    /** The documented baseline: known to return a callback on tested firmware. */
    public static final PhotoCaptureSettings DEFAULT =
            new PhotoCaptureSettings(1920, 1080, 80);

    /**
     * Probe order for the real-device capture sweep.
     *
     * <p>Measuring a real capture on 2026-08-28 removed the reason the old
     * ladder existed. Resolution was never the limit: the column pitch was 37px
     * against ML Kit's documented 16px floor. What is short is contrast
     * (41/255, against roughly 200 for a scan) and JPEG information
     * (0.071 bytes/pixel, against 0.2-0.5 for a document). So the ladder no
     * longer buys resolution by trading quality away, which would have made the
     * thin strokes worse while lengthening the measured 5.2s callback.</p>
     *
     * <p>It now moves one variable per probe: the baseline for reference, the
     * same frame at quality 95 to isolate compression, and 12MP at quality 80
     * last, reached only when raising quality and lighting have both failed.
     * The contrast probe is the baseline re-shot under strong even light, so it
     * is an operating condition rather than a preset and has no entry here.</p>
     */
    public static final List<PhotoCaptureSettings> SWEEP_PRESETS = List.of(
            DEFAULT,
            new PhotoCaptureSettings(1920, 1080, 95),
            new PhotoCaptureSettings(4032, 3024, 80));

    /**
     * The probe after {@code current}, wrapping at the end of the ladder.
     *
     * <p>A hand-entered value is not part of the ladder, so stepping from one
     * restarts the sweep rather than guessing where the operator left off.</p>
     */
    public static PhotoCaptureSettings nextPreset(PhotoCaptureSettings current) {
        String key = current == null ? "" : current.describe();
        for (int i = 0; i < SWEEP_PRESETS.size(); i++) {
            if (SWEEP_PRESETS.get(i).describe().equals(key)) {
                return SWEEP_PRESETS.get((i + 1) % SWEEP_PRESETS.size());
            }
        }
        return SWEEP_PRESETS.get(0);
    }

    public static PhotoCaptureSettings parse(String width, String height, String quality) {
        return new PhotoCaptureSettings(
                requireDimension(width, "幅"),
                requireDimension(height, "高さ"),
                requireQuality(quality));
    }

    /** Restores persisted values, falling back to {@link #DEFAULT} if unusable. */
    public static PhotoCaptureSettings ofOrDefault(int width, int height, int quality) {
        if (width <= 0 || width > MAX_DIMENSION
                || height <= 0 || height > MAX_DIMENSION
                || quality < 1 || quality > 100) {
            return DEFAULT;
        }
        return new PhotoCaptureSettings(width, height, quality);
    }

    public String describe() {
        return String.format(Locale.US, "%dx%d q%d", width, height, quality);
    }

    private static int requireDimension(String raw, String field) {
        int value = requireInt(raw, field);
        if (value <= 0 || value > MAX_DIMENSION) {
            throw new IllegalArgumentException(
                    field + "は1〜" + MAX_DIMENSION + "の範囲で指定してください");
        }
        return value;
    }

    private static int requireQuality(String raw) {
        int value = requireInt(raw, "品質");
        if (value < 1 || value > 100) {
            throw new IllegalArgumentException("品質は1〜100の範囲で指定してください");
        }
        return value;
    }

    private static int requireInt(String raw, String field) {
        String trimmed = raw == null ? "" : raw.trim();
        try {
            return Integer.parseInt(trimmed);
        } catch (NumberFormatException error) {
            throw new IllegalArgumentException(field + "は数値で指定してください", error);
        }
    }
}
