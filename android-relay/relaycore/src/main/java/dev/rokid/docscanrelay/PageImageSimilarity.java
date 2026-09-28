package dev.rokid.docscanrelay;

/**
 * Decides whether a photo shows the page already registered when OCR read too
 * little for {@link PageTextSimilarity} to judge: a dark shot, a figure-only
 * page, an OCR failure.
 *
 * <p>Both thumbnails are averaged onto the same 32x24 grid and normalised to
 * zero mean and unit variance, so a darker or brighter exposure of the same
 * sheet compares equal; what remains is where the sheet and its text blocks
 * sit in the frame.</p>
 */
public final class PageImageSimilarity {
    /** A greyscale thumbnail, luminance 0-255, row-major. */
    public record Luma(int width, int height, int[] pixels) {
        public Luma {
            if (width <= 0 || height <= 0 || pixels == null || pixels.length != width * height) {
                throw new IllegalArgumentException("thumbnail size does not match its pixels");
            }
        }
    }

    static final int GRID_WIDTH = 32;
    static final int GRID_HEIGHT = 24;

    /**
     * Mean absolute difference of the normalised grids below which two photos
     * are the same page. Measured on {@code PageImageSimilarityTest}'s
     * synthetic 63x47 sheets: the same sheet darkened to 0.27x/0.13x or at
     * 48x36 differs by at most 0.057; one text block moved by 8% of the frame
     * differs by 0.133 and a two-column layout by 0.19. Set low, toward
     * "different page", as {@link PageTextSimilarity} is: registering a
     * near-duplicate is recoverable, skipping a turned page is not.
     *
     * <p>ponytail: calibrated on synthetic rectangles only. The same sheet
     * with the head moved by one thumbnail pixel (about 1.6% of the frame)
     * already measures 0.13, and two pages with the same block layout can
     * measure below this. Recalibrate on real glasses photos; if head motion
     * dominates, compare over small shifts instead of raising this.</p>
     */
    static final double SAME_PAGE_THRESHOLD = 0.08;

    /**
     * One grey level. A frame flatter than this has no picture to normalise;
     * dividing by the floor keeps its sensor noise from becoming a pattern.
     */
    private static final double MIN_SPREAD = 1.0;

    private PageImageSimilarity() {
    }

    /** False when either thumbnail is missing, so an unknown image is never skipped. */
    public static boolean isSamePage(Luma registered, Luma candidate) {
        return registered != null && candidate != null
                && difference(registered, candidate) < SAME_PAGE_THRESHOLD;
    }

    static double difference(Luma left, Luma right) {
        double[] a = normalised(grid(left));
        double[] b = normalised(grid(right));
        double sum = 0;
        for (int i = 0; i < a.length; i++) {
            sum += Math.abs(a[i] - b[i]);
        }
        return sum / a.length;
    }

    /** Area average onto the grid; a thumbnail smaller than the grid repeats its pixels. */
    private static double[] grid(Luma image) {
        double[] cells = new double[GRID_WIDTH * GRID_HEIGHT];
        for (int gy = 0; gy < GRID_HEIGHT; gy++) {
            int y0 = gy * image.height() / GRID_HEIGHT;
            int y1 = Math.max(y0 + 1, (gy + 1) * image.height() / GRID_HEIGHT);
            for (int gx = 0; gx < GRID_WIDTH; gx++) {
                int x0 = gx * image.width() / GRID_WIDTH;
                int x1 = Math.max(x0 + 1, (gx + 1) * image.width() / GRID_WIDTH);
                long sum = 0;
                for (int y = y0; y < y1; y++) {
                    for (int x = x0; x < x1; x++) {
                        sum += image.pixels()[y * image.width() + x];
                    }
                }
                cells[gy * GRID_WIDTH + gx] = (double) sum / ((y1 - y0) * (x1 - x0));
            }
        }
        return cells;
    }

    private static double[] normalised(double[] cells) {
        double mean = 0;
        for (double cell : cells) {
            mean += cell;
        }
        mean /= cells.length;
        double variance = 0;
        for (double cell : cells) {
            variance += (cell - mean) * (cell - mean);
        }
        double spread = Math.max(Math.sqrt(variance / cells.length), MIN_SPREAD);
        double[] result = new double[cells.length];
        for (int i = 0; i < cells.length; i++) {
            result[i] = (cells[i] - mean) / spread;
        }
        return result;
    }
}
