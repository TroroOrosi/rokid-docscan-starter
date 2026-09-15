package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class FramingGuideTest {
    @Test public void singlePageUsesTheDisplayHeightWithoutALandscapeSensorInset() {
        FramingGuide.Rect page = FramingGuide.of(480, 640, FramingGuide.UNCALIBRATED_FRACTION);
        assertEquals(640, page.height());
        assertEquals(453, page.width());
    }

    @Test public void bothPaperShapesFitAndRemainCentredAtEveryScale() {
        for (boolean spread : new boolean[]{false, true}) {
            for (double scale : new double[]{0.2, 0.5, 0.8, 1.0}) {
                FramingGuide.Rect page = FramingGuide.of(480, 640, scale, spread);
                assertEquals(FramingGuide.PAPER_ASPECT * (spread ? 2 : 1),
                        page.width() / (double) page.height(), 0.02);
                assertTrue(page.left() >= 0 && page.right() <= 480);
                assertTrue(page.top() >= 0 && page.bottom() <= 640);
                assertEquals(480 - page.right(), page.left(), 1);
                assertEquals(640 - page.bottom(), page.top(), 1);
            }
        }
        assertEquals(480, FramingGuide.of(480, 640, 1, true).width());
    }

    @Test public void operatorScaleRemainsAvailableForMeasuredCalibration() {
        FramingGuide.Rect page = FramingGuide.of(480, 640, 1);
        FramingGuide.Rect half = FramingGuide.of(480, 640, 0.5);
        assertEquals(page.width() / 2.0, half.width(), 1);
        assertEquals(page.height() / 2.0, half.height(), 1);
        assertEquals(page.width(), FramingGuide.of(480, 640, 9).width());
        assertEquals(FramingGuide.of(480, 640, 0.2).height(),
                FramingGuide.of(480, 640, -1).height());
        assertEquals(0, FramingGuide.of(0, 640, 1).width());
        assertEquals(0, FramingGuide.of(480, 0, 1).height());
    }
}
