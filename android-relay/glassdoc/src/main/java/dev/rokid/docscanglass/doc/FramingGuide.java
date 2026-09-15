package dev.rokid.docscanglass.doc;

/**
 * Page-shaped aiming brackets. The scale is a drawing setting, not a camera
 * field-of-view measurement. Calibrate against actual captures at the user's
 * seated distance; sensor pixel dimensions do not locate the camera on the HUD.
 */
public final class FramingGuide {
    public static final double PAPER_ASPECT = 182.0 / 257.0;
    public static final double MIN_VISIBLE_FRACTION = 0.20;
    public static final double MAX_VISIBLE_FRACTION = 1.00;
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

    private FramingGuide() { }

    public static Rect of(int displayWidth, int displayHeight, double scale) {
        return of(displayWidth, displayHeight, scale, false);
    }

    /** Fit one B5 page or its open spread directly in the available display. */
    public static Rect of(int displayWidth, int displayHeight, double scale, boolean spread) {
        if (displayWidth <= 0 || displayHeight <= 0) return new Rect(0, 0, 0, 0);
        double fraction = Math.max(MIN_VISIBLE_FRACTION, Math.min(MAX_VISIBLE_FRACTION, scale));
        double aspect = PAPER_ASPECT * (spread ? 2 : 1);
        double boxHeight = Math.min(displayHeight, displayWidth / aspect) * fraction;
        int width = (int) Math.round(boxHeight * aspect);
        int height = (int) Math.round(boxHeight);
        int left = (displayWidth - width) / 2;
        int top = (displayHeight - height) / 2;
        return new Rect(left, top, left + width, top + height);
    }
}
