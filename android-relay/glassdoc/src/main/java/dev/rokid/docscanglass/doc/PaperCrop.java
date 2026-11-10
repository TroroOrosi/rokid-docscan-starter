package dev.rokid.docscanglass.doc;

import android.graphics.Bitmap;
import java.util.Arrays;

/**
 * Display only: the review shows the paper, not the desk around it. The
 * operator found the review photo small and far away (2026-09-30); the camera
 * sees much more than the page. JPEG, OCR and upload stay the full frame.
 *
 * <p>The review must never hide part of the paper: that is what the wearer is
 * checking. On 19 saved booklet photographs (PC, 2026-11-10) the half-way
 * threshold of {@link #box} cut up to 12% of the frame width off a dimmer
 * facing page; {@link #reviewBox} lost at most 1%. Both are uncalibrated for
 * light desks, where no box stands out and the whole frame is shown.</p>
 */
final class PaperCrop {
    private static final int GRID_W = 48;
    private static final int GRID_H = 64;

    private PaperCrop() {
    }

    /** The paper region of {@code still}, or {@code still} itself when none stands out. */
    static Bitmap apply(Bitmap still) {
        if (still == null) return null;
        Bitmap small;
        try {
            small = Bitmap.createScaledBitmap(still, GRID_W, GRID_H, true);
        } catch (OutOfMemoryError error) {
            return still;
        }
        int[] pixels = new int[GRID_W * GRID_H];
        small.getPixels(pixels, 0, GRID_W, 0, 0, GRID_W, GRID_H);
        if (small != still) small.recycle();
        int[] luma = new int[pixels.length];
        for (int i = 0; i < pixels.length; i++) {
            int p = pixels[i];
            luma[i] = (((p >> 16) & 0xFF) * 299 + ((p >> 8) & 0xFF) * 587 + (p & 0xFF) * 114) / 1000;
        }
        int[] box = reviewBox(luma, GRID_W, GRID_H);
        // The corner fits the image by its tighter side: under a tenth larger is not worth hiding the surroundings.
        if (box == null || Math.min(GRID_W * 10 / (box[2] - box[0]), GRID_H * 10 / (box[3] - box[1])) < 11) return still;
        int x = box[0] * still.getWidth() / GRID_W;
        int y = box[1] * still.getHeight() / GRID_H;
        int w = Math.max(1, box[2] * still.getWidth() / GRID_W - x);
        int h = Math.max(1, box[3] * still.getHeight() / GRID_H - y);
        try {
            Bitmap cropped = Bitmap.createBitmap(still, x, y, w, h);
            if (cropped != still) still.recycle();
            return cropped;
        } catch (OutOfMemoryError error) {
            return still;
        }
    }

    /**
     * {left, top, right, bottom} of the bright region in grid cells, with a
     * small margin, or null when the paper does not stand out or already
     * fills the frame. A row or column belongs to the paper when a quarter of
     * it is brighter than halfway between the median and the 95th percentile.
     */
    static int[] box(int[] luma, int width, int height) {
        return box(luma, width, height, 2, 25);
    }

    /** As {@link #box}, a quarter of the way up from the median and 15% of a row or column: a dimmer page stays in. */
    static int[] reviewBox(int[] luma, int width, int height) {
        return box(luma, width, height, 4, 15);
    }

    private static int[] box(int[] luma, int width, int height, int divisor, int sharePercent) {
        int[] sorted = luma.clone();
        Arrays.sort(sorted);
        int median = sorted[sorted.length / 2];
        int bright = sorted[sorted.length * 95 / 100];
        if (bright - median < 20) return null;
        int threshold = median + (bright - median) / divisor;
        int left = -1, right = -1, top = -1, bottom = -1;
        for (int x = 0; x < width; x++) {
            int count = 0;
            for (int y = 0; y < height; y++) if (luma[y * width + x] >= threshold) count++;
            if (count * 100 >= height * sharePercent) { if (left < 0) left = x; right = x + 1; }
        }
        for (int y = 0; y < height; y++) {
            int count = 0;
            for (int x = 0; x < width; x++) if (luma[y * width + x] >= threshold) count++;
            if (count * 100 >= width * sharePercent) { if (top < 0) top = y; bottom = y + 1; }
        }
        if (left < 0 || top < 0) return null;
        int marginX = Math.max(1, width / 30);
        int marginY = Math.max(1, height / 30);
        left = Math.max(0, left - marginX);
        top = Math.max(0, top - marginY);
        right = Math.min(width, right + marginX);
        bottom = Math.min(height, bottom + marginY);
        long area = (long) (right - left) * (bottom - top);
        if (area * 100 < (long) width * height * 15 || area * 100 > (long) width * height * 90) {
            return null;
        }
        return new int[] {left, top, right, bottom};
    }
}
