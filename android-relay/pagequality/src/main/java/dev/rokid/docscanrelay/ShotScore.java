package dev.rokid.docscanrelay;

import java.util.Locale;

/**
 * Ranks the shots of one automatic burst so the relay can register the best
 * without asking the operator anything.
 *
 * <p>The glasses give no live preview, and on the capture-review view a tap
 * closes the CustomView without delivering any AI event, so there is no
 * reliable way to let a human choose. What the phone does have, for every
 * shot, is the framing verdict and the recogniser's own account of how much it
 * read and how sure it was. Those are enough to prefer one frame over
 * another.</p>
 *
 * <p>Confidence alone is a trap: a frame that resolved three characters
 * perfectly outranks a full page read imperfectly. Character count alone is
 * the opposite trap, because a frame of confidently wrong glyphs is long. The
 * product of the two is used, which is simply the expected number of correct
 * characters.</p>
 *
 * <p>Free of Android and ML Kit types so the arithmetic is testable.</p>
 */
public final class ShotScore {
    /**
     * A clipped page keeps most of its text, so the raw product would happily
     * rank it first. It is multiplied down far enough that any comparable
     * whole-page frame wins, without discarding it outright: a burst where
     * every frame clipped should still yield its least-bad member.
     */
    private static final double CLIPPED_PENALTY = 0.2;

    /**
     * The bundled recogniser does not always populate confidence. Treating an
     * absent value as zero would rank such a frame below an empty one, so it
     * is scored as merely unremarkable.
     */
    private static final double ASSUMED_CONFIDENCE = 0.5;

    private ShotScore() {
    }

    /** Expected correct characters, penalised when the page ran off frame. */
    public static double of(PageFraming framing, int characters, float meanConfidence, boolean hasConfidence) {
        if (characters <= 0) {
            return 0;
        }
        double confidence = hasConfidence
                ? Math.max(0, Math.min(1, meanConfidence))
                : ASSUMED_CONFIDENCE;
        double score = characters * confidence;
        if (framing != null && framing.isFailing()) {
            score *= CLIPPED_PENALTY;
        }
        return score;
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
