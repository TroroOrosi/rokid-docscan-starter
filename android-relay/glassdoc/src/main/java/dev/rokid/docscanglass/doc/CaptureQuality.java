package dev.rokid.docscanglass.doc;

/**
 * What the still the operator just took is actually worth.
 *
 * <p>This exists because the operator cannot see through the camera. A live
 * viewfinder would answer that, but it holds the camera streaming, and the
 * privacy indicator is on for exactly as long as the camera streams -- 673 to
 * 1143 ms per single shot on this firmware. So the HUD reviews the still
 * instead, and this class turns four cheap image statistics into something the
 * operator can act on.
 *
 * <p>The thresholds are measured, not guessed. The first three pages
 * photographed on 2026-09-04 stored at mean luminance 16, 23 and 24 out of 255
 * against the roughly 200 a lit page reaches, and the recognizer returned
 * garbled text for two of them and nothing at all for the third.
 */
public final class CaptureQuality {

    /** Below this the page is too dark to recognize. Measured failures: 16-24. */
    public static final int MIN_MEAN_LUMINANCE = 70;

    /** Above this the page is blown out and the ink has gone with it. */
    public static final int MAX_MEAN_LUMINANCE = 240;

    /** Below this there is no ink in the frame, however well lit it is. */
    public static final int MIN_STDDEV = 12;

    /** Dark fraction along the border above which the page is cut. */
    public static final double MAX_EDGE_INK = 0.20;

    public enum Verdict {
        OK("PAGE OK", true),
        TOO_DARK("TOO DARK - MORE LIGHT", false),
        TOO_BRIGHT("TOO BRIGHT", false),
        NO_CONTRAST("NO TEXT SEEN", false),
        // Legible text, just cropped. Only the operator knows whether the cut
        // edge carried anything, so this warns rather than blocks.
        EDGE_CUT("PAGE CUT - STEP BACK", true);

        private final String hudLabel;
        private final boolean usable;

        Verdict(String hudLabel, boolean usable) {
            this.hudLabel = hudLabel;
            this.usable = usable;
        }

        public String hudLabel() {
            return hudLabel;
        }

        /** Whether uploading it is reasonable without the operator retaking it. */
        public boolean isUsable() {
            return usable;
        }
    }

    private CaptureQuality() {
    }

    /**
     * Exposure is judged before framing on purpose: a framing verdict computed
     * from an underexposed frame is not trustworthy, and the operator has to
     * fix the light first either way.
     *
     * @param meanLuminance 0-255 average over the frame
     * @param stddev luminance standard deviation over the frame
     * @param borderInkFraction dark fraction along the frame border
     * @param unusedReserved kept so the signature can carry a second framing
     *     statistic without a call-site change
     */
    public static Verdict judge(
            int meanLuminance, int stddev, double borderInkFraction, double unusedReserved) {
        if (meanLuminance < MIN_MEAN_LUMINANCE) {
            return Verdict.TOO_DARK;
        }
        if (meanLuminance > MAX_MEAN_LUMINANCE) {
            return Verdict.TOO_BRIGHT;
        }
        if (stddev < MIN_STDDEV) {
            return Verdict.NO_CONTRAST;
        }
        if (borderInkFraction > MAX_EDGE_INK) {
            return Verdict.EDGE_CUT;
        }
        return Verdict.OK;
    }
}
