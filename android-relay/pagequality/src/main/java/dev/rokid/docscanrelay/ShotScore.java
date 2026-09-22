package dev.rokid.docscanrelay;

import java.util.Locale;

/** Relative OCR ranking within one burst, never a correctness probability. */
public final class ShotScore {
    /** Missing/nonfinite confidence supplies no calibrated evidence. */
    private static final double ASSUMED_CONFIDENCE = 0.5;

    private ShotScore() {
    }

    /** Any non-clipped candidate ranks above a suspected clipped one. */
    public static double of(PageFraming framing, int characters, float meanConfidence, boolean hasConfidence) {
        double confidence = hasConfidence && Float.isFinite(meanConfidence)
                ? Math.max(0, Math.min(1, meanConfidence))
                : ASSUMED_CONFIDENCE;
        double score = Math.max(0, characters) * confidence;
        // [-1, 0) preserves ranking among clipped shots, below every other score.
        return framing != null && framing.isFailing() ? -1.0 / (1.0 + score) : score;
    }

    /**
     * Whether {@code candidate} should replace the best shot so far.
     *
     * <p>Ties keep the incumbent: the earlier frame was taken while the
     * operator was still holding position for it.</p>
     */
    public static boolean isBetter(double candidate, double incumbent) {
        return candidate > incumbent;
    }

    public static String describe(double score) {
        return String.format(Locale.US, "score=%.1f", score);
    }
}
