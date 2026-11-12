package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertNull;

import org.junit.Test;

public class PaperCropTest {
    private static int[] frame(int width, int height, int left, int top, int right, int bottom) {
        int[] luma = new int[width * height];
        for (int y = 0; y < height; y++) {
            for (int x = 0; x < width; x++) {
                luma[y * width + x] = x >= left && x < right && y >= top && y < bottom ? 200 : 40;
            }
        }
        return luma;
    }

    @Test public void aPageOnADarkDeskIsFramedWithAMargin() {
        int[] luma = frame(48, 64, 12, 16, 36, 48);
        assertArrayEquals(new int[] {11, 14, 37, 50}, PaperCrop.box(luma, 48, 64));
    }

    @Test public void anEvenFrameIsLeftWhole() {
        assertNull(PaperCrop.box(frame(48, 64, 0, 0, 0, 0), 48, 64));
    }

    @Test public void aPageThatFillsTheFrameIsLeftWhole() {
        assertNull(PaperCrop.box(frame(48, 64, 1, 1, 47, 63), 48, 64));
    }

    /** 2026-11-10, real photos: the facing page is dimmer, and the half-way threshold cut it off. */
    @Test public void theReviewBoxKeepsADimmerFacingPageThatTheHalfWayThresholdCuts() {
        int[] luma = frame(48, 64, 0, 0, 0, 0);
        for (int y = 20; y < 50; y++) for (int x = 2; x < 42; x++) luma[y * 48 + x] = x < 22 ? 200 : 110;
        int[] halfWay = PaperCrop.box(luma, 48, 64);
        org.junit.Assert.assertTrue("this fixture must reproduce the cut", halfWay[2] < 42);
        assertArrayEquals(new int[] {1, 18, 43, 52}, PaperCrop.reviewBox(luma, 48, 64));
    }

    @Test public void theReviewBoxStillLeavesAnEvenOrFullFrameWhole() {
        assertNull(PaperCrop.reviewBox(frame(48, 64, 0, 0, 0, 0), 48, 64));
        assertNull(PaperCrop.reviewBox(frame(48, 64, 1, 1, 47, 63), 48, 64));
    }

    @Test public void stillnessNeverTreatsElapsedWaitAsPermissionToShootWhileMoving() {
        org.junit.Assert.assertFalse(Stillness.ready(1_200, 1_000, 1_000));
        org.junit.Assert.assertTrue(Stillness.ready(1_300, 1_000, 1_000));
        org.junit.Assert.assertFalse(Stillness.ready(6_000, 1_000, 5_999));
        org.junit.Assert.assertFalse(Stillness.ready(60_000, 1_000, 59_999));
    }
}
