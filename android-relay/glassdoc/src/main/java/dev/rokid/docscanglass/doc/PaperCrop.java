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
        int[] box = boxOf(still);
        // The corner fits the image by its tighter side: under a tenth larger is not worth hiding the surroundings.
        if (box == null || Math.min(GRID_W * 10 / (box[2] - box[0]), GRID_H * 10 / (box[3] - box[1])) < 11) return still;
        int[] area = pixels(still, box);
        int x = area[0], y = area[1], w = area[2] - area[0], h = area[3] - area[1];
        try {
            Bitmap cropped = Bitmap.createBitmap(still, x, y, w, h);
            if (cropped != still) still.recycle();
            return cropped;
        } catch (OutOfMemoryError error) {
            return still;
        }
    }

    /** The paper of {@code image} in grid cells, or null when none stands out. */
    static int[] boxOf(Bitmap image) {
        int[] luma = lumaOf(image);
        return luma == null ? null : reviewBox(luma, GRID_W, GRID_H);
    }

    /** Past which sides of {@code image} its paper runs ({@link #past}), keeping what was {@code told}; null without an image. */
    static boolean[] pastOf(Bitmap image, boolean[] told) {
        int[] luma = lumaOf(image);
        return luma == null ? null : past(luma, GRID_W, GRID_H, told);
    }

    /**
     * {top, right, bottom, left}: the paper runs past that side of the frame, so what is printed beyond it is not in
     * the picture. Paper is what is at least 0.7 as bright as the frame's 90th percentile; a side is told when the
     * two outermost rows or columns are paper along three tenths of its length, and stays told ({@code told}, may
     * be null) down to two tenths. A frame whose brightest tenth is dark holds no paper. On the 35 frames of the
     * operator's trial of 2026-11-17 this told the sides each sheet was cut at (a dark desk); a view with no
     * paper's edge in it, a sheet that fills the frame or a bare desk, is told on every side.
     */
    static boolean[] past(int[] luma, int width, int height, boolean[] told) {
        int[] sorted = luma.clone();
        Arrays.sort(sorted);
        int paper = sorted[sorted.length * 90 / 100];
        boolean[] past = new boolean[4];
        if (paper < 48) return past;
        int floor = paper * 7 / 10, depth = 2;
        int top = 0, right = 0, bottom = 0, left = 0;
        for (int x = 0; x < width; x++) {
            int near = 0, far = 0;
            for (int d = 0; d < depth; d++) { near += luma[d * width + x]; far += luma[(height - 1 - d) * width + x]; }
            if (near >= floor * depth) top++;
            if (far >= floor * depth) bottom++;
        }
        for (int y = 0; y < height; y++) {
            int near = 0, far = 0;
            for (int d = 0; d < depth; d++) { near += luma[y * width + d]; far += luma[y * width + width - 1 - d]; }
            if (near >= floor * depth) left++;
            if (far >= floor * depth) right++;
        }
        int[] share = {top * 100 / width, right * 100 / height, bottom * 100 / width, left * 100 / height};
        for (int side = 0; side < 4; side++) past[side] = share[side] >= (told != null && told[side] ? 20 : 30);
        return past;
    }

    /** The image's brightness on the grid, or null when there is no image. */
    private static int[] lumaOf(Bitmap image) {
        if (image == null || image.isRecycled()) return null;
        Bitmap small;
        try {
            small = Bitmap.createScaledBitmap(image, GRID_W, GRID_H, true);
        } catch (OutOfMemoryError error) {
            return null;
        }
        int[] pixels = new int[GRID_W * GRID_H];
        small.getPixels(pixels, 0, GRID_W, 0, 0, GRID_W, GRID_H);
        if (small != image) small.recycle();
        int[] luma = new int[pixels.length];
        for (int i = 0; i < pixels.length; i++) {
            int p = pixels[i];
            luma[i] = (((p >> 16) & 0xFF) * 299 + ((p >> 8) & 0xFF) * 587 + (p & 0xFF) * 114) / 1000;
        }
        return luma;
    }

    /** {left, top, right, bottom} of a grid box in the pixels of {@code image}; null for no box. */
    static int[] pixels(Bitmap image, int[] box) {
        if (box == null) return null;
        int x = box[0] * image.getWidth() / GRID_W, y = box[1] * image.getHeight() / GRID_H;
        return new int[] {x, y, Math.max(x + 1, box[2] * image.getWidth() / GRID_W),
                Math.max(y + 1, box[3] * image.getHeight() / GRID_H)};
    }

    /** The box to keep showing: the live image follows the paper only once it has moved more than two cells. */
    static int[] steady(int[] shown, int[] found) {
        if (shown == null || found == null) return found;
        for (int i = 0; i < 4; i++) if (Math.abs(shown[i] - found[i]) > 2) return found;
        return shown;
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
