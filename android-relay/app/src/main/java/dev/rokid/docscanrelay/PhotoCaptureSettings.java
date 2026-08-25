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
     * <p>The baseline comes first to establish a reference frame. The 12MP
     * probe at quality 50 comes second on purpose: its payload is comparable to
     * the baseline, so if that request produces no callback the cause cannot be
     * the Binder payload budget, and one attempt settles whether the ceiling is
     * about bytes or about resolution. The remaining entries walk quality back
     * up at 12MP, then step down in resolution for the fallback branch.</p>
     */
    public static final List<PhotoCaptureSettings> SWEEP_PRESETS = List.of(
            DEFAULT,
            new PhotoCaptureSettings(4032, 3024, 50),
            new PhotoCaptureSettings(4032, 3024, 60),
            new PhotoCaptureSettings(4032, 3024, 70),
            new PhotoCaptureSettings(3264, 2448, 50),
            new PhotoCaptureSettings(3264, 2448, 60),
            new PhotoCaptureSettings(2560, 1920, 60),
            new PhotoCaptureSettings(2560, 1440, 60));

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
