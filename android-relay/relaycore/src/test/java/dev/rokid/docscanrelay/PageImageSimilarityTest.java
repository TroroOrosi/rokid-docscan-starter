package dev.rokid.docscanrelay;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/**
 * Synthetic thumbnails at the size a 4032x3024 photo decodes to (63x47):
 * dark desk, light sheet, grey rectangles where the text blocks are. At this
 * scale a block of text is a grey area, not letters.
 */
public class PageImageSimilarityTest {
    private static final int W = 63;
    private static final int H = 47;
    private static final double[] SHEET = {0.10, 0.05, 0.90, 0.95, 200};
    private static final double[] HEADER = {0.15, 0.10, 0.85, 0.18, 110};
    private static final double[] BODY = {0.15, 0.24, 0.85, 0.52, 120};
    private static final double[] LOWER = {0.15, 0.58, 0.60, 0.90, 120};
    private static final double[] FIGURE = {0.65, 0.58, 0.85, 0.90, 80};
    private static final double[] LEFT_COLUMN = {0.15, 0.24, 0.48, 0.90, 120};
    private static final double[] RIGHT_COLUMN = {0.52, 0.24, 0.85, 0.90, 120};

    private static PageImageSimilarity.Luma page(int width, int height) {
        return render(width, height, SHEET, HEADER, BODY, LOWER, FIGURE);
    }

    @Test public void identicalThumbnailsAreTheSamePage() {
        assertTrue(PageImageSimilarity.isSamePage(page(W, H), page(W, H)));
    }

    @Test public void aDarkerOrBrighterShotOfTheSameSheetIsTheSamePage() {
        PageImageSimilarity.Luma page = page(W, H);
        // Glasses photos come out dark: the sheet at 57 or even 28 instead of 200.
        assertTrue(PageImageSimilarity.isSamePage(page, exposed(page, 0.27, 3)));
        assertTrue(PageImageSimilarity.isSamePage(page, exposed(page, 0.13, 2)));
        assertTrue(PageImageSimilarity.isSamePage(exposed(page, 0.13, 2), exposed(page, 1.2, 8)));
    }

    @Test public void aTextBlockMovedByAFewRowsIsADifferentPage() {
        double[] lowerMoved = {0.15, 0.66, 0.60, 0.98, 120}; // 8% of the frame, ~4 thumbnail rows
        assertFalse(PageImageSimilarity.isSamePage(
                page(W, H), render(W, H, SHEET, HEADER, BODY, lowerMoved, FIGURE)));
    }

    @Test public void aDifferentTextLayoutIsADifferentPage() {
        PageImageSimilarity.Luma twoColumns = render(W, H, SHEET, HEADER, LEFT_COLUMN, RIGHT_COLUMN);
        assertFalse(PageImageSimilarity.isSamePage(page(W, H), twoColumns));
        assertFalse(PageImageSimilarity.isSamePage(page(W, H), exposed(twoColumns, 0.27, 3)));
        assertFalse(PageImageSimilarity.isSamePage(page(W, H), render(W, H, SHEET)));
    }

    @Test public void thumbnailsOfDifferentSizesAreComparedOnTheSameGrid() {
        assertTrue(PageImageSimilarity.isSamePage(page(W, H), page(48, 36)));
        assertFalse(PageImageSimilarity.isSamePage(
                page(W, H), render(48, 36, SHEET, HEADER, LEFT_COLUMN, RIGHT_COLUMN)));
    }

    @Test public void aMissingThumbnailIsNeverTheSamePage() {
        assertFalse(PageImageSimilarity.isSamePage(null, page(W, H)));
        assertFalse(PageImageSimilarity.isSamePage(page(W, H), null));
    }

    @Test public void aFeaturelessFrameDoesNotTurnIntoNoise() {
        PageImageSimilarity.Luma black = new PageImageSimilarity.Luma(W, H, new int[W * H]);
        assertTrue(PageImageSimilarity.isSamePage(black, black));
        assertFalse(PageImageSimilarity.isSamePage(black, page(W, H)));
    }

    @Test public void aThumbnailMustMatchItsDimensions() {
        assertThrows(IllegalArgumentException.class, () -> new PageImageSimilarity.Luma(2, 2, new int[3]));
        assertThrows(IllegalArgumentException.class, () -> new PageImageSimilarity.Luma(0, 0, new int[0]));
    }

    /** Rectangles {left, top, right, bottom, grey} in frame fractions, later ones on top, over a desk at 40. */
    private static PageImageSimilarity.Luma render(int width, int height, double[]... rectangles) {
        int[] pixels = new int[width * height];
        for (int y = 0; y < height; y++) {
            for (int x = 0; x < width; x++) {
                double fx = (x + 0.5) / width;
                double fy = (y + 0.5) / height;
                int grey = 40;
                for (double[] r : rectangles) {
                    if (fx >= r[0] && fx < r[2] && fy >= r[1] && fy < r[3]) grey = (int) r[4];
                }
                pixels[y * width + x] = grey;
            }
        }
        return new PageImageSimilarity.Luma(width, height, pixels);
    }

    private static PageImageSimilarity.Luma exposed(PageImageSimilarity.Luma image, double gain, double offset) {
        int[] pixels = new int[image.pixels().length];
        for (int i = 0; i < pixels.length; i++) {
            pixels[i] = (int) Math.max(0, Math.min(255, Math.round(image.pixels()[i] * gain + offset)));
        }
        return new PageImageSimilarity.Luma(image.width(), image.height(), pixels);
    }
}
