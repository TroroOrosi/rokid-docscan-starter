package dev.rokid.docscanglass.doc;

/**
 * How alike two watch pictures are, as one number: the page taken last seen again after the head moved, or another
 * sheet? For the record only (register 2-38). Nothing is decided from the score.
 *
 * <p>A picture is a 128x96 grid of mean levels. Less its mean over 5 cells it is cut into 16x16-cell blocks. A block
 * with print (a spread of at least 2.5 levels) is looked for in the other picture within 6 cells each way by
 * zero-mean normalised correlation; a block whose search would leave the other picture is left out. Both pictures'
 * blocks are looked for and their best scores averaged; under six blocks nothing is known and the result is 0. This
 * is done around where each block was, and around the shift of the whole picture found at half size (64x48, less its
 * mean over 9 cells, up to a quarter of the picture each way). The better of the two results is the score.
 *
 * <p>Ported from the measurement of 2026-11-18 (data/gather-stage2/scripts/same_page_blocks_1118.py, and "blk2mean"
 * in same_page_report_1118.py beside it; untracked). One difference: the half-size grid is the mean of 2x2 cells of
 * this grid, where the script reduced the picture a second time. On frames of 35 worn clips a limit of about 0.625
 * told one page seen after the head moved from another sheet, with no margin. That limit is NOT validated for the
 * watch preview, which is the camera's own reduction at its own exposure and not a clip's frame.
 */
final class SamePage {
    static final int WIDTH = 128, HEIGHT = 96, CELLS = WIDTH * HEIGHT;
    private static final int BLOCK = 16, REACH = 6, AREA = BLOCK * BLOCK, LEAST = 6;
    /** Levels. In the measurement's clips a block of bare paper or desk had a spread of 1-2, a block with print 3.5-25. */
    private static final double FLOOR = 2.5;

    /** The mean of the blocks' best scores, at most 1; 0 when fewer than six blocks counted. */
    final float score;
    /** The blocks that counted, of both pictures together. */
    final int blocks;

    private SamePage(float score, int blocks) {
        this.score = score;
        this.blocks = blocks;
    }

    /** A picture's cells, and their sums and the sums of their squares over any rectangle from the corner. */
    private static final class Picture {
        final float[] cells;
        final int width;
        final double[] sums, squares;

        Picture(float[] cells, int width, int height) {
            this.cells = cells;
            this.width = width;
            sums = new double[(width + 1) * (height + 1)];
            squares = new double[sums.length];
            for (int y = 0; y < height; y++) {
                double sum = 0, square = 0;
                for (int x = 0, above = y * (width + 1) + 1, at = above + width + 1; x < width; x++, above++, at++) {
                    float cell = cells[y * width + x];
                    sum += cell;
                    square += cell * cell;
                    sums[at] = sums[above] + sum;
                    squares[at] = squares[above] + square;
                }
            }
        }

        double box(double[] total, int top, int left, int rows, int columns) {
            int stride = width + 1, from = top * stride + left, to = from + rows * stride;
            return total[to + columns] - total[from + columns] - total[to] + total[from];
        }
    }

    /** Two 128x96 grids of levels, a row after a row. */
    static SamePage of(byte[] earlier, byte[] later) {
        if (earlier.length != CELLS || later.length != CELLS) throw new IllegalArgumentException("not a 128x96 grid");
        float[] one = levels(earlier), other = levels(later);
        Picture a = new Picture(band(one, WIDTH, HEIGHT, 5), WIDTH, HEIGHT);
        Picture b = new Picture(band(other, WIDTH, HEIGHT, 5), WIDTH, HEIGHT);
        SamePage where = around(a, b, 0, 0);
        int[] shift = wholeShift(one, other);
        if (shift[0] == 0 && shift[1] == 0) return where;
        SamePage moved = around(a, b, 2 * shift[0], 2 * shift[1]);
        return moved.score > where.score ? moved : where;
    }

    /**
     * The watch picture as a grid: the mean of each cell, rounded, the cells' edges at the nearest pixel. Null for a
     * picture that is not there or has fewer pixels than the grid has cells either way.
     */
    static byte[] grid(byte[] luma, int length, int width, int height, int row, int step) {
        if (luma == null || width < WIDTH || height < HEIGHT || row <= 0 || step <= 0 || length > luma.length
                || (long) (height - 1) * row + (long) (width - 1) * step >= length) return null;
        int[] edges = new int[WIDTH + 1], sums = new int[WIDTH];
        for (int x = 0; x <= WIDTH; x++) edges[x] = (2 * x * width + WIDTH) / (2 * WIDTH);
        byte[] grid = new byte[CELLS];
        for (int cy = 0; cy < HEIGHT; cy++) {
            int top = (2 * cy * height + HEIGHT) / (2 * HEIGHT), bottom = (2 * (cy + 1) * height + HEIGHT) / (2 * HEIGHT);
            java.util.Arrays.fill(sums, 0);
            for (int y = top; y < bottom; y++) {
                for (int cx = 0, at = y * row + edges[0] * step; cx < WIDTH; cx++) {
                    int sum = 0;
                    for (int x = edges[cx]; x < edges[cx + 1]; x++, at += step) sum += luma[at] & 255;
                    sums[cx] += sum;
                }
            }
            for (int cx = 0; cx < WIDTH; cx++) {
                int area = (bottom - top) * (edges[cx + 1] - edges[cx]);
                grid[cy * WIDTH + cx] = (byte) ((sums[cx] + area / 2) / area);
            }
        }
        return grid;
    }

    private static float[] levels(byte[] grid) {
        float[] levels = new float[grid.length];
        for (int i = 0; i < grid.length; i++) levels[i] = grid[i] & 255;
        return levels;
    }

    /** Each cell less the mean of the {@code span} x {@code span} cells around it, the edge cells repeated outward. */
    private static float[] band(float[] cells, int width, int height, int span) {
        int reach = span / 2;
        float[] band = new float[cells.length];
        for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
            float sum = 0;
            for (int v = -reach; v <= reach; v++) {
                int line = Math.max(0, Math.min(height - 1, y + v)) * width;
                for (int u = -reach; u <= reach; u++) sum += cells[line + Math.max(0, Math.min(width - 1, x + u))];
            }
            band[y * width + x] = cells[y * width + x] - sum / (span * span);
        }
        return band;
    }

    /**
     * Each block of either picture that has print, looked for in the other one within its reach around the whole
     * shift ({@code down}, {@code right}): a's cell (y, x) is taken to lie on b's (y + down, x + right).
     */
    private static SamePage around(Picture a, Picture b, int down, int right) {
        double sum = 0;
        int counted = 0;
        for (int direction = 0; direction < 2; direction++) {
            Picture from = direction == 0 ? a : b, in = direction == 0 ? b : a;
            int dy = direction == 0 ? down : -down, dx = direction == 0 ? right : -right;
            for (int top = 0; top < HEIGHT; top += BLOCK) for (int left = 0; left < WIDTH; left += BLOCK) {
                int y0 = top + dy - REACH, x0 = left + dx - REACH;
                if (y0 < 0 || y0 + BLOCK + 2 * REACH > HEIGHT || x0 < 0 || x0 + BLOCK + 2 * REACH > WIDTH) continue;
                double mean = from.box(from.sums, top, left, BLOCK, BLOCK) / AREA;
                double energy = from.box(from.squares, top, left, BLOCK, BLOCK) - AREA * mean * mean;
                if (energy < FLOOR * FLOOR * AREA) continue; // bare paper or desk: says nothing
                double best = Double.NEGATIVE_INFINITY;
                for (int y = y0; y <= y0 + 2 * REACH; y++) for (int x = x0; x <= x0 + 2 * REACH; x++) {
                    double there = in.box(in.sums, y, x, BLOCK, BLOCK);
                    double spread = Math.max(in.box(in.squares, y, x, BLOCK, BLOCK) - there * there / AREA, 0);
                    double value = 0; // a place with a quarter of the floor's spread or less has nothing to be like
                    if (spread > FLOOR * FLOOR * AREA / 16) {
                        double cross = 0;
                        for (int v = 0; v < BLOCK; v++) {
                            float line = 0;
                            for (int u = 0, p = (top + v) * WIDTH + left, q = (y + v) * WIDTH + x; u < BLOCK; u++) {
                                line += from.cells[p + u] * in.cells[q + u];
                            }
                            cross += line;
                        }
                        value = (cross - mean * there) / Math.sqrt(Math.max(spread * energy, 1e-9));
                    }
                    if (value > best) best = value;
                }
                sum += best;
                counted++;
            }
        }
        return new SamePage(counted >= LEAST ? (float) (sum / counted) : 0f, counted);
    }

    /**
     * The shift of the whole picture in cells of the half-size grid, (down, right): the earlier picture's cell (y, x)
     * lies on the later one's (y + down, x + right). The best zero-mean normalised correlation over the overlap, of
     * every shift up to a quarter of the picture; an overlap with under half a level of spread has nothing to compare.
     */
    private static int[] wholeShift(float[] earlier, float[] later) {
        int width = WIDTH / 2, height = HEIGHT / 2;
        Picture a = new Picture(band(halved(earlier), width, height, width / 8 + 1), width, height);
        Picture b = new Picture(band(halved(later), width, height, width / 8 + 1), width, height);
        double best = Double.NEGATIVE_INFINITY;
        int down = 0, right = 0;
        // ponytail: every shift is summed cell by cell, about two million products. The script used an FFT; take one
        // if this ever has to run more often than once a page.
        for (int dy = -height / 4; dy <= height / 4; dy++) for (int dx = -width / 4; dx <= width / 4; dx++) {
            int top = Math.max(0, -dy), left = Math.max(0, -dx), rows = height - Math.abs(dy), columns = width - Math.abs(dx);
            int count = rows * columns;
            double sa = a.box(a.sums, top, left, rows, columns), sb = b.box(b.sums, top + dy, left + dx, rows, columns);
            double va = a.box(a.squares, top, left, rows, columns) - sa * sa / count;
            double vb = b.box(b.squares, top + dy, left + dx, rows, columns) - sb * sb / count;
            double value = 0;
            if (va >= 0.25 * count && vb >= 0.25 * count) {
                double cross = 0;
                for (int y = 0; y < rows; y++) {
                    float line = 0;
                    for (int x = 0, p = (top + y) * width + left, q = (top + dy + y) * width + left + dx; x < columns; x++) {
                        line += a.cells[p + x] * b.cells[q + x];
                    }
                    cross += line;
                }
                value = (cross - sa * sb / count) / Math.sqrt(Math.max(va, 1e-6) * Math.max(vb, 1e-6));
            }
            if (value > best) {
                best = value;
                down = dy;
                right = dx;
            }
        }
        return new int[]{down, right};
    }

    private static float[] halved(float[] cells) {
        float[] half = new float[CELLS / 4];
        for (int y = 0; y < HEIGHT / 2; y++) for (int x = 0; x < WIDTH / 2; x++) {
            int at = 2 * y * WIDTH + 2 * x;
            half[y * WIDTH / 2 + x] = (cells[at] + cells[at + 1] + cells[at + WIDTH] + cells[at + WIDTH + 1]) / 4;
        }
        return half;
    }
}
