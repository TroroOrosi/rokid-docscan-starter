package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/**
 * Where to draw the aiming rectangle.
 *
 * <p>The operator cannot see through the camera, and a live viewfinder is not
 * available for free: the privacy indicator is lit for exactly as long as the
 * camera streams. A guide drawn on the HUD costs no camera time at all, so it
 * is the one aiming aid that does not change what the indicator means.
 *
 * <p>It is only useful if it is calibrated. The display is 480x640 and the
 * camera is 4032x3024, and the first hardware run showed the camera seeing far
 * more than the page -- a desk and a map came with it. The visible fraction is
 * therefore a measured input, not a constant baked into the drawing code.
 */
public final class FramingGuideTest {

    private static final int DISPLAY_WIDTH = 480;
    private static final int DISPLAY_HEIGHT = 640;

    @Test
    public void isPageShapedRatherThanSensorShaped() {
        // The camera field is 4:3 landscape and the page is 1:1.41 portrait.
        // A portrait page can never fill a landscape guide, so aligning to a
        // sensor-shaped one tells the operator nothing about framing.
        FramingGuide.Rect guide = FramingGuide.of(DISPLAY_WIDTH, DISPLAY_HEIGHT, 1.0);

        double aspect = guide.width() / (double) guide.height();
        assertEquals("B5 portrait is 182:257", FramingGuide.PAPER_ASPECT, aspect, 0.01);
        assertTrue("portrait", guide.height() > guide.width());
    }

    @Test
    public void spreadFitsTwoB5PagesInsideTheSameSensorField() {
        for (double fraction : new double[]{0.2, 0.8, 1.0}) {
            FramingGuide.Rect field = FramingGuide.fieldOf(DISPLAY_WIDTH, DISPLAY_HEIGHT, fraction);
            FramingGuide.Rect spread = FramingGuide.of(DISPLAY_WIDTH, DISPLAY_HEIGHT, fraction, true);
            assertEquals(364.0 / 257.0, spread.width() / (double) spread.height(), 0.02);
            assertTrue(spread.left() >= field.left() && spread.right() <= field.right());
            assertTrue(spread.top() >= field.top() && spread.bottom() <= field.bottom());
            assertEquals(fraction * fraction * (4.0 / 3.0) / (364.0 / 257.0),
                    FramingGuide.expectedPageAreaFraction(fraction, true), 0.0001);
        }
    }

    @Test
    public void fitsInsideTheDisplayAtEveryCalibration() {
        for (double fraction : new double[]{0.1, 0.5, 0.8, 1.0}) {
            FramingGuide.Rect guide = FramingGuide.of(DISPLAY_WIDTH, DISPLAY_HEIGHT, fraction);

            assertTrue("left " + guide.left(), guide.left() >= 0);
            assertTrue("top " + guide.top(), guide.top() >= 0);
            assertTrue("right " + guide.right(), guide.right() <= DISPLAY_WIDTH);
            assertTrue("bottom " + guide.bottom(), guide.bottom() <= DISPLAY_HEIGHT);
        }
    }

    @Test
    public void isCentredOnTheDisplay() {
        FramingGuide.Rect guide = FramingGuide.of(DISPLAY_WIDTH, DISPLAY_HEIGHT, 0.8);

        assertEquals(DISPLAY_WIDTH - guide.right(), guide.left());
        assertEquals(DISPLAY_HEIGHT - guide.bottom(), guide.top());
        FramingGuide.Rect field = FramingGuide.fieldOf(DISPLAY_WIDTH, DISPLAY_HEIGHT, 0.8);
        assertEquals(FramingGuide.SENSOR_ASPECT, field.width() / (double)field.height(), .01);
        assertTrue(field.left() < guide.left() && field.right() > guide.right());
    }

    @Test
    public void aSmallerVisibleFractionDrawsASmallerGuide() {
        FramingGuide.Rect wide = FramingGuide.of(DISPLAY_WIDTH, DISPLAY_HEIGHT, 1.0);
        FramingGuide.Rect narrow = FramingGuide.of(DISPLAY_WIDTH, DISPLAY_HEIGHT, 0.5);

        assertTrue(narrow.width() < wide.width());
        assertTrue(narrow.height() < wide.height());
    }

    @Test
    public void clampsACalibrationOutsideTheUsableRange() {
        // A calibration typo must not draw a guide off the glass or an
        // invisible one; it is an operator-supplied number.
        FramingGuide.Rect tooBig = FramingGuide.of(DISPLAY_WIDTH, DISPLAY_HEIGHT, 9.0);
        FramingGuide.Rect tooSmall = FramingGuide.of(DISPLAY_WIDTH, DISPLAY_HEIGHT, -1.0);

        assertEquals(FramingGuide.of(DISPLAY_WIDTH, DISPLAY_HEIGHT,
                FramingGuide.MAX_VISIBLE_FRACTION).width(), tooBig.width());
        assertEquals(FramingGuide.of(DISPLAY_WIDTH, DISPLAY_HEIGHT,
                FramingGuide.MIN_VISIBLE_FRACTION).width(), tooSmall.width());
    }

    @Test
    public void survivesADisplayWithNoAreaRatherThanDividingByZero() {
        FramingGuide.Rect guide = FramingGuide.of(0, 0, 0.8);

        assertEquals(0, guide.width());
        assertEquals(0, guide.height());
    }

    @Test
    public void theDefaultIsTheUncalibratedStartingPointNotAGuess() {
        // Until a page is photographed against the guide, the honest default
        // is the whole display: it claims the camera sees at least this much,
        // which is true, rather than claiming a fit nobody measured.
        assertEquals(FramingGuide.MAX_VISIBLE_FRACTION,
                FramingGuide.UNCALIBRATED_FRACTION, 0.0001);
    }

    @Test
    public void reportsTheFractionOfTheCaptureThePageShouldFillWhenAligned() {
        // The calibration loop: shoot a page filling the guide, measure what
        // fraction of the still it occupies, feed that back as the fraction.
        // The guide is page-shaped inside a 4:3 field, so a page filling it
        // covers less of the still than the visible fraction alone suggests.
        double shapeLoss = FramingGuide.PAPER_ASPECT / FramingGuide.SENSOR_ASPECT;
        assertEquals(0.64 * shapeLoss,
                FramingGuide.expectedPageAreaFraction(0.8), 0.0001);
        assertEquals(shapeLoss,
                FramingGuide.expectedPageAreaFraction(1.0), 0.0001);
    }
}
