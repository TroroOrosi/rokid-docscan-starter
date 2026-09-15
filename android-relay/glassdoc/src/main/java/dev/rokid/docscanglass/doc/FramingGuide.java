package dev.rokid.docscanglass.doc;

/**
 * The aiming rectangle drawn on the HUD before the shutter.
 *
 * <p>A live viewfinder would answer "what am I about to photograph?" directly,
 * but the privacy indicator is lit for exactly as long as the camera streams --
 * measured at 673-1143 ms for a single shot -- so a viewfinder trades a brief
 * indicator for a permanently lit one. A rectangle drawn on the HUD costs no
 * camera time at all, which makes it the one aiming aid that does not change
 * what the indicator means.
 *
 * <p>It only helps once it is calibrated. The display is 480x640 and the sensor
 * is 4032x3024, and the first hardware run showed the camera taking in a desk
 * and a map along with the page. How much of the display the camera actually
 * covers is therefore a measured input, supplied at run time:
 *
 * <pre>
 * adb -s SERIAL shell am start \
 *   -n dev.rokid.docscanglass.doc/.DocScanGlassActivity \
 *   --es server "http://HOST:8000" --ef guide 0.8
 * </pre>
 *
 * <p>Calibration loop: photograph a page that exactly fills the guide, read the
 * fraction of the still the page occupies, and pass that fraction back in.
 * {@link #expectedPageAreaFraction(double)} states what a correct calibration
 * predicts, so a run either confirms the number or corrects it.
 */
public final class FramingGuide {

    /** Sensor aspect ratio measured on this device: 4032x3024. */
    public static final double SENSOR_ASPECT = 4032.0 / 3024.0;

    /**
     * The page, as width over height. JIS B5 portrait is 182x257 mm.
     *
     * <p>A4 (210x297) and B4 (257x364) sit within 0.3% of the same figure --
     * the ISO and JIS series are both built on 1:root-2 -- so the guide shape
     * serves all three and only the shooting distance changes.</p>
     */
    public static final double PAPER_ASPECT = 182.0 / 257.0;

    public static final double MIN_VISIBLE_FRACTION = 0.20;
    public static final double MAX_VISIBLE_FRACTION = 1.00;

    /**
     * The starting point before anyone has photographed a page against the
     * guide. This is a drawing default, not a measured optical field of view.
     */
    public static final double UNCALIBRATED_FRACTION = MAX_VISIBLE_FRACTION;

    /** Integer pixel rectangle, so drawing and tests agree exactly. */
    public static final class Rect {
        private final int left;
        private final int top;
        private final int right;
        private final int bottom;

        Rect(int left, int top, int right, int bottom) {
            this.left = left;
            this.top = top;
            this.right = right;
            this.bottom = bottom;
        }

        public int left() {
            return left;
        }

        public int top() {
            return top;
        }

        public int right() {
            return right;
        }

        public int bottom() {
            return bottom;
        }

        public int width() {
            return right - left;
        }

        public int height() {
            return bottom - top;
        }
    }

    private FramingGuide() {
    }

    /**
     * @param visibleFraction how much of the display the camera covers, from
     *     the calibration run. Clamped, because it is operator-supplied.
     */
    public static Rect of(int displayWidth, int displayHeight, double visibleFraction) {
        if (displayWidth <= 0 || displayHeight <= 0) {
            return new Rect(0, 0, 0, 0);
        }
        double fraction = Math.max(MIN_VISIBLE_FRACTION,
                Math.min(MAX_VISIBLE_FRACTION, visibleFraction));

        // What the camera covers: the largest 4:3 box the display can show,
        // scaled by how much of it the camera actually reaches.
        double fieldWidth = Math.min(displayWidth, displayHeight * SENSOR_ASPECT);
        double visibleWidth = fieldWidth * fraction;
        double visibleHeight = visibleWidth / SENSOR_ASPECT;

        // The guide is the largest page-shaped rectangle inside that. The
        // field is landscape and the page is portrait, so height is always the
        // binding constraint; the min keeps that from being an assumption.
        double boxHeight = Math.min(visibleHeight, visibleWidth / PAPER_ASPECT);
        double boxWidth = boxHeight * PAPER_ASPECT;
        int width = (int) Math.round(boxWidth);
        int height = (int) Math.round(boxHeight);

        int left = (displayWidth - width) / 2;
        int top = (displayHeight - height) / 2;
        return new Rect(left, top, left + width, top + height);
    }

    /** Outer sensor-shaped coverage guide; must be calibrated at the working distance. */
    public static Rect fieldOf(int displayWidth, int displayHeight, double visibleFraction) {
        Rect page = of(displayWidth, displayHeight, visibleFraction);
        int height = page.height();
        int width = Math.min(displayWidth, (int)Math.round(height * SENSOR_ASPECT));
        int left = (displayWidth - width) / 2;
        return new Rect(left, page.top(), left + width, page.bottom());
    }

    /**
     * What fraction of the captured still a page filling the guide should
     * occupy, if {@code visibleFraction} is right. Compare against a real
     * capture to confirm or correct the calibration.
     */
    public static double expectedPageAreaFraction(double visibleFraction) {
        double fraction = Math.max(MIN_VISIBLE_FRACTION,
                Math.min(MAX_VISIBLE_FRACTION, visibleFraction));
        // The guide is page-shaped inside a 4:3 field, so a page filling it
        // covers less of the still than the visible fraction alone suggests.
        return fraction * fraction * PAPER_ASPECT / SENSOR_ASPECT;
    }
}
