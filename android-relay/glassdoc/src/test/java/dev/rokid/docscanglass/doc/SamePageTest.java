package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import java.util.Arrays;
import java.util.Random;

import org.junit.Test;

/** Synthetic pictures only: the frames the measure was found on are not in the repository. */
public final class SamePageTest {
    private static final int W = SamePage.WIDTH, H = SamePage.HEIGHT;

    /** Noise smoothed over three cells, about 30 levels of spread: detail in every block that survives halving. */
    private static byte[][] scene(long seed) {
        int width = 2 * W, height = 2 * H;
        Random random = new Random(seed);
        double[][] noise = new double[height + 2][width + 2];
        for (double[] row : noise) for (int x = 0; x < row.length; x++) row[x] = random.nextGaussian();
        byte[][] scene = new byte[height][width];
        for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
            double sum = 0;
            for (int v = 0; v < 3; v++) for (int u = 0; u < 3; u++) sum += noise[y + v][x + u];
            scene[y][x] = (byte) Math.max(0, Math.min(255, Math.round(128 + 10 * sum)));
        }
        return scene;
    }

    /** The 128x96 cells of a scene whose corner lies {@code top} cells down and {@code left} cells right. */
    private static byte[] view(byte[][] scene, int top, int left) {
        byte[] grid = new byte[SamePage.CELLS];
        for (int y = 0; y < H; y++) System.arraycopy(scene[top + y], left, grid, y * W, W);
        return grid;
    }

    @Test public void one_picture_is_the_same_page() {
        byte[] page = view(scene(1), 40, 60);
        SamePage same = SamePage.of(page, page.clone());
        assertEquals(1f, same.score, 0.001f);
        // 4 x 6 blocks can be looked for 6 cells each way without leaving the picture, in either direction.
        assertEquals(48, same.blocks);
    }

    @Test public void a_picture_moved_by_a_few_cells_is_found_by_each_block_within_its_reach() {
        byte[][] scene = scene(1);
        SamePage same = SamePage.of(view(scene, 40, 60), view(scene, 43, 56));
        assertTrue("3 cells down, 4 left: " + same.score, same.score > 0.9f);
        assertEquals(48, same.blocks);
    }

    @Test public void a_picture_moved_by_twenty_cells_is_found_around_the_whole_shift() {
        byte[][] scene = scene(1);
        byte[] page = view(scene, 40, 60);
        // No block finds itself 20 cells away within its 6: only the shift of the whole picture, found at half
        // size, brings it there.
        SamePage across = SamePage.of(page, view(scene, 40, 80));
        assertTrue("20 cells: " + across.score, across.score > 0.9f);
        assertTrue("blocks still in view: " + across.blocks, across.blocks >= 24);
        // An odd shift is not a whole cell at half size; the blocks' own reach takes up the rest. Both ways round.
        SamePage both = SamePage.of(view(scene, 50, 39), page);
        assertTrue("10 cells up, 21 right: " + both.score, both.score > 0.9f);
    }

    @Test public void another_picture_scores_low() {
        SamePage other = SamePage.of(view(scene(1), 40, 60), view(scene(2), 40, 60));
        // Each block still takes the best of 169 places, so unrelated detail does not score 0.
        assertTrue("two unrelated textures: " + other.score, other.score < 0.5f);
        assertTrue("with print to compare: " + other.blocks, other.blocks >= 24);
    }

    @Test public void flat_grids_have_no_block_that_counts() {
        byte[] flat = new byte[SamePage.CELLS];
        Arrays.fill(flat, (byte) 180);
        SamePage none = SamePage.of(flat, flat.clone());
        assertEquals(0, none.blocks);
        assertEquals("nothing is known", 0f, none.score, 0f);
    }

    @Test public void a_level_added_to_one_picture_does_not_change_the_score() {
        byte[][] scene = scene(3);
        byte[] page = view(scene, 40, 60), moved = view(scene, 44, 66), brighter = moved.clone();
        for (int i = 0; i < brighter.length; i++) brighter[i] = (byte) Math.min(255, (brighter[i] & 255) + 20);
        assertEquals(SamePage.of(page, moved).score, SamePage.of(page, brighter).score, 0.02f);
    }

    @Test public void the_grid_is_the_mean_of_each_cell_of_the_watch_picture() {
        // 320x240 in a buffer of wider rows, every second byte: the left half black, the right half at 200.
        int width = 320, height = 240, row = 704, step = 2;
        byte[] luma = new byte[row * height];
        Arrays.fill(luma, (byte) 77); // what lies between the pixels is not read
        for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) luma[y * row + x * step] = (byte) (x < 160 ? 0 : 200);
        byte[] grid = SamePage.grid(luma, luma.length, width, height, row, step);
        assertEquals(SamePage.CELLS, grid.length);
        for (int y = 0; y < H; y++) for (int x = 0; x < W; x++) {
            assertEquals("cell " + x + "," + y, x < 64 ? 0 : 200, grid[y * W + x] & 255);
        }
        // A cell is 2 or 3 pixels each way; one bright pixel in a cell of 3 x 3 is a ninth of it.
        luma[0] = (byte) 180;
        assertEquals(20, SamePage.grid(luma, luma.length, width, height, row, step)[0] & 255);
    }

    @Test public void a_picture_that_cannot_fill_the_grid_has_none() {
        assertNull("smaller than the grid", SamePage.grid(new byte[32 * 24], 32 * 24, 32, 24, 32, 1));
        assertNull("no picture yet", SamePage.grid(null, 0, 320, 240, 320, 1));
        assertNull("fewer bytes than the picture needs", SamePage.grid(new byte[320 * 240], 320 * 239, 320, 240, 320, 1));
        byte[] exact = new byte[W * H];
        new Random(5).nextBytes(exact);
        assertArrayEquals("a picture of the grid's own size is the grid", exact, SamePage.grid(exact, exact.length, W, H, W, 1));
    }

    /** Not a limit to hold: what one comparison costs on the machine that runs the tests, printed for the record. */
    @Test public void one_comparison_is_a_few_milliseconds_of_one_thread() {
        byte[][] scene = scene(1);
        byte[] page = view(scene, 40, 60), moved = view(scene, 50, 81), other = view(scene(2), 40, 60);
        for (int i = 0; i < 30; i++) SamePage.of(page, i % 2 == 0 ? moved : other); // the compiler's warm-up
        int runs = 100;
        long began = System.nanoTime();
        float sum = 0;
        for (int i = 0; i < runs; i++) sum += SamePage.of(page, i % 2 == 0 ? moved : other).score;
        double millis = (System.nanoTime() - began) / 1e6 / runs;
        System.out.println("same_page cost: " + Math.round(millis * 100) / 100.0 + " ms a comparison over " + runs
                + " (mean score " + sum / runs + ")");
        assertTrue("far from a frame's time even on a slow machine: " + millis + " ms", millis < 250);
    }
}
