package dev.rokid.docscanglass.doc;

import java.nio.ByteBuffer;
import java.util.Arrays;
import java.util.function.LongSupplier;

/** Bounded page evidence, never an image-quality or whole-sheet coverage certificate. */
final class LumaPageEvidence {
    static final int WIDTH = 64, HEIGHT = 48, CELLS = WIDTH * HEIGHT;
    static final int MAX_PIXELS = 1_048_576, MAX_OFFSETS = 8_192;
    static final long COMPARE_INTERVAL_MILLIS = 200, MAX_COMPARE_NANOS = 40_000_000;
    private static final long MAX_PHASE_NANOS = 4_000_000;
    private final LongSupplier nanos;
    LumaPageEvidence() { this(System::nanoTime); }
    LumaPageEvidence(LongSupplier nanos) { this.nanos = nanos; }
    private Frame first, second, reference, latest;
    private final byte[] motionReference = new byte[CELLS];
    private final byte[] detailMotion = new byte[4 * CELLS];
    private final int[] windows = new int[48]; // Same paper fraction: 8x8 base cells or 16x16 detail cells.
    private boolean hasMotion, valid, capacityFallback = true;
    private long motionChangedAt, lastFrameAt, comparedAt = Long.MIN_VALUE;
    private String status = "unobserved";
    private int evaluatedOffsets;
    private boolean phaseAborted;

    private static final class Frame {
        final int width, height, stride, padX, padY;
        final int[] integral;
        final int[] xs = new int[WIDTH + 1], ys = new int[HEIGHT + 1];
        final int[] areas = new int[CELLS];
        final byte[] means = new byte[CELLS], details = new byte[4 * CELLS];
        final int[] detailXs = new int[2 * WIDTH + 1], detailYs = new int[2 * HEIGHT + 1];
        final int[] detailAreas = new int[4 * CELLS];
        int total;
        Frame(int width, int height) {
            this.width = width; this.height = height;
            padX = (width + 15) / 16; padY = (height + 11) / 12;
            stride = width + 2 * padX + 1;
            integral = new int[stride * (height + 2 * padY + 1)];
            for (int x = 0; x <= WIDTH; x++) xs[x] = x * width / WIDTH + padX;
            for (int y = 0; y <= HEIGHT; y++) ys[y] = y * height / HEIGHT + padY;
            for (int y = 0; y < HEIGHT; y++) for (int x = 0; x < WIDTH; x++)
                areas[y * WIDTH + x] = (xs[x + 1] - xs[x]) * (ys[y + 1] - ys[y]);
            for (int x = 0; x <= 2 * WIDTH; x++) detailXs[x] = x * width / (2 * WIDTH) + padX;
            for (int y = 0; y <= 2 * HEIGHT; y++) detailYs[y] = y * height / (2 * HEIGHT) + padY;
            for (int y = 0; y < 2 * HEIGHT; y++) for (int x = 0; x < 2 * WIDTH; x++)
                detailAreas[y * 2 * WIDTH + x] = (detailXs[x + 1] - detailXs[x]) * (detailYs[y + 1] - detailYs[y]);
        }
        void read(ByteBuffer pixels, int row, int step) {
            int origin = pixels.position(), paddedHeight = height + 2 * padY;
            for (int y = 0; y < paddedHeight; y++) {
                int source = origin + Math.max(0, Math.min(height - 1, y - padY)) * row;
                int sum = 0, top = y * stride, bottom = top + stride;
                integral[bottom] = 0;
                for (int x = 0; x < stride - 1; x++) {
                    sum += pixels.get(source + Math.max(0, Math.min(width - 1, x - padX)) * step) & 255;
                    integral[bottom + x + 1] = integral[top + x + 1] + sum;
                }
            }
            total = sum(0, 0);
            means(0, 0, means);
            for (int y = 0, i = 0; y < 2 * HEIGHT; y++) {
                int top = detailYs[y] * stride, bottom = detailYs[y + 1] * stride;
                for (int x = 0; x < 2 * WIDTH; x++, i++) {
                    int left = detailXs[x], right = detailXs[x + 1];
                    details[i] = (byte)((integral[bottom + right] - integral[top + right]
                            - integral[bottom + left] + integral[top + left]) / detailAreas[i]);
                }
            }
        }
        int sum(int dx, int dy) {
            int top = (padY + dy) * stride, bottom = (padY + height + dy) * stride;
            int left = padX + dx, right = padX + width + dx;
            return integral[bottom + right] - integral[top + right]
                    - integral[bottom + left] + integral[top + left];
        }
        void means(int dx, int dy, byte[] out) {
            for (int y = 0, i = 0; y < HEIGHT; y++) {
                int top = (ys[y] + dy) * stride, bottom = (ys[y + 1] + dy) * stride;
                for (int x = 0; x < WIDTH; x++, i++) {
                    int left = xs[x] + dx, right = xs[x + 1] + dx;
                    out[i] = (byte)((integral[bottom + right] - integral[top + right]
                            - integral[bottom + left] + integral[top + left]) / areas[i]);
                }
            }
        }
    }

    /** Latest native integrals plus both unregistered scales run at every valid preview: O(N + 15360). */
    boolean sample(ByteBuffer pixels, int width, int height, int row, int step, long now) {
        valid = false; evaluatedOffsets = 0;
        if (width < 2 * WIDTH || height < 2 * HEIGHT || (long)width * height > MAX_PIXELS) {
            fallback("size_budget"); return true;
        }
        int rx = (width + 15) / 16, ry = (height + 11) / 12;
        if ((long)(2 * rx + 1) * (2 * ry + 1) > MAX_OFFSETS) {
            fallback("offset_budget"); return true;
        }
        capacityFallback = false;
        if (pixels == null || row <= 0 || step <= 0 || (long)(width - 1) * step >= row
                || (long)pixels.position() + (long)(height - 1) * row + (long)(width - 1) * step >= pixels.limit()) {
            invalidate("invalid_plane"); return false;
        }
        if (first == null || first.width != width || first.height != height) {
            first = new Frame(width, height); second = new Frame(width, height);
            reference = latest = null; hasMotion = false; comparedAt = Long.MIN_VALUE;
        }
        Frame target = reference == first ? second : first;
        target.read(pixels, row, step); latest = target; valid = true; lastFrameAt = now;
        if (!hasMotion || differs(latest.means, motionReference) || differs(latest.details, detailMotion)) {
            System.arraycopy(latest.means, 0, motionReference, 0, CELLS);
            System.arraycopy(latest.details, 0, detailMotion, 0, 4 * CELLS);
            hasMotion = true; motionChangedAt = now;
        }
        status = "current"; return true;
    }

    /** A positive result requires completing every allowed coherent native-pixel offset. */
    boolean changed(boolean compensate, long now) {
        evaluatedOffsets = 0;
        if (!valid || latest == null || reference == null) return false;
        if (comparedAt != Long.MIN_VALUE && now - comparedAt < COMPARE_INTERVAL_MILLIS) {
            status = "throttled"; return false;
        }
        comparedAt = now;
        long started = nanos.getAsLong();
        if (!withinBudget(started)) return false;
        int rx = compensate ? (latest.width + 15) / 16 : 0;
        int ry = compensate ? (latest.height + 11) / 12 : 0;
        if (!differentAt(0, 0)) {
            if (withinBudget(started)) status = "same";
            return false;
        }
        // Centre first makes the common same-page case cheap; rings still exhaust the full rectangle.
        for (int radius = 1; radius <= Math.max(rx, ry); radius++)
            for (int dy = -Math.min(radius, ry); dy <= Math.min(radius, ry); dy++)
                for (int dx = -Math.min(radius, rx); dx <= Math.min(radius, rx); dx++) {
                    if (Math.max(Math.abs(dx), Math.abs(dy)) != radius) continue;
                    if (!withinBudget(started)) return false;
                    if (!differentAt(dx, dy)) {
                        if (withinBudget(started)) status = "same";
                        return false;
                    }
                }
        if (!withinBudget(started)) return false;
        status = "different"; return true;
    }
    private boolean withinBudget(long started) {
        if (Thread.currentThread().isInterrupted()) { status = "interrupted"; return false; }
        long elapsed = nanos.getAsLong() - started;
        if (elapsed < 0 || elapsed >= MAX_COMPARE_NANOS) { status = "time_budget"; return false; }
        return true;
    }
    private boolean differentAt(int dx, int dy) {
        evaluatedOffsets++;
        // Whole native-frame mean, including clamped edges, is O(1) per coherent offset.
        int offset = (latest.total - reference.sum(dx, dy)) / (latest.width * latest.height);
        int changed = 0;
        boolean local = false;
        Arrays.fill(windows, 0);
        for (int y = 0, i = 0; y < HEIGHT; y++) {
            int top = (reference.ys[y] + dy) * reference.stride;
            int bottom = (reference.ys[y + 1] + dy) * reference.stride;
            for (int x = 0; x < WIDTH; x++, i++) {
                int left = reference.xs[x] + dx, right = reference.xs[x + 1] + dx;
                int value = (reference.integral[bottom + right] - reference.integral[top + right]
                        - reference.integral[bottom + left] + reference.integral[top + left]) / reference.areas[i];
                if (Math.abs((latest.means[i] & 255) - value - offset) < PageChange.CHANGE_DELTA) continue;
                changed++;
                if (++windows[(y / 8) * 8 + x / 8] * 5 >= 64) local = true;
                // This offset cannot match once both lower bounds have been reached.
                if (changed * 8 >= CELLS && local) return true;
            }
        }
        // Both scales must match this identical offset; matches at different offsets never combine.
        return differentDetails(dx, dy, offset);
    }
    private boolean differentDetails(int dx, int dy, int offset) {
        int changed = 0; boolean local = false; Arrays.fill(windows, 0);
        for (int y = 0, i = 0; y < 2 * HEIGHT; y++) {
            int top = (reference.detailYs[y] + dy) * reference.stride;
            int bottom = (reference.detailYs[y + 1] + dy) * reference.stride;
            for (int x = 0; x < 2 * WIDTH; x++, i++) {
                int left = reference.detailXs[x] + dx, right = reference.detailXs[x + 1] + dx;
                int value = (reference.integral[bottom + right] - reference.integral[top + right]
                        - reference.integral[bottom + left] + reference.integral[top + left]) / reference.detailAreas[i];
                if (Math.abs((latest.details[i] & 255) - value - offset) < PageChange.CHANGE_DELTA) continue;
                changed++;
                if (++windows[(y / 16) * 8 + x / 16] * 5 >= 256) local = true;
                if (changed * 8 >= 4 * CELLS && local) return true;
            }
        }
        return false;
    }

    /** A narrow coarse-positive rescue, never a veto based only on fine means being SAME. */
    boolean sameNativePhase(byte[] coarse) {
        phaseAborted = false;
        if (!valid || reference == null || latest == null || coarse == null || coarse.length != 768) return false;
        long started = nanos.getAsLong();
        // Verify the caller sampled this same plane and origin before using its coarse values.
        for (int y = 0, i = 0; y < 24; y++) {
            if (!withinPhaseBudget(started)) return false;
            for (int x = 0; x < 32; x++, i++)
                if ((coarse[i] & 255) != phasePixel(latest, x * latest.width / 32, y * latest.height / 24)) return false;
        }
        // Eight inner-ring plus sixteen outer-ring phases. All scales must share this exact offset.
        for (int radius = 1; radius <= 2; radius++)
            for (int dy = -radius; dy <= radius; dy++)
                for (int dx = -radius; dx <= radius; dx++) {
                    if (Math.max(Math.abs(dx), Math.abs(dy)) != radius) continue;
                    if (!withinPhaseBudget(started)) return false;
                    int offset = (latest.total - reference.sum(dx, dy)) / (latest.width * latest.height);
                    if (samePhasePoints(coarse, dx, dy, offset, started)
                            && samePhaseMeans(false, dx, dy, offset, started)
                            && samePhaseMeans(true, dx, dy, offset, started)) {
                        if (!withinPhaseBudget(started)) return false;
                        status = "same"; return true;
                    }
                    if (phaseAborted) return false;
                }
        return false;
    }
    private boolean withinPhaseBudget(long started) {
        if (Thread.currentThread().isInterrupted()) { status = "interrupted"; phaseAborted = true; return false; }
        long elapsed = nanos.getAsLong() - started;
        if (elapsed < 0 || elapsed >= MAX_PHASE_NANOS) { status = "time_budget"; phaseAborted = true; return false; }
        return true;
    }
    private static int phasePixel(Frame frame, int x, int y) {
        int top = (frame.padY + y) * frame.stride, bottom = top + frame.stride;
        int left = frame.padX + x, right = left + 1;
        return frame.integral[bottom + right] - frame.integral[top + right]
                - frame.integral[bottom + left] + frame.integral[top + left];
    }
    private boolean samePhasePoints(byte[] coarse, int dx, int dy, int offset, long started) {
        for (int y = 0, i = 0; y < 24; y++) {
            if (!withinPhaseBudget(started)) return false;
            for (int x = 0; x < 32; x++, i++) {
                int value = phasePixel(reference, x * reference.width / 32 + dx, y * reference.height / 24 + dy);
                if (Math.abs((coarse[i] & 255) - value - offset) >= PageChange.CHANGE_DELTA) return false;
            }
        }
        return true;
    }
    private boolean samePhaseMeans(boolean detail, int dx, int dy, int offset, long started) {
        int width = detail ? 2 * WIDTH : WIDTH, height = detail ? 2 * HEIGHT : HEIGHT;
        int[] xs = detail ? reference.detailXs : reference.xs, ys = detail ? reference.detailYs : reference.ys;
        int[] areas = detail ? reference.detailAreas : reference.areas;
        byte[] values = detail ? latest.details : latest.means;
        for (int y = 0, i = 0; y < height; y++) {
            if (!withinPhaseBudget(started)) return false;
            int top = (ys[y] + dy) * reference.stride, bottom = (ys[y + 1] + dy) * reference.stride;
            for (int x = 0; x < width; x++, i++) {
                int left = xs[x] + dx, right = xs[x + 1] + dx;
                int value = (reference.integral[bottom + right] - reference.integral[top + right]
                        - reference.integral[bottom + left] + reference.integral[top + left]) / areas[i];
                if (Math.abs((values[i] & 255) - value - offset) >= PageChange.CHANGE_DELTA) return false;
            }
        }
        return true;
    }

    private boolean differs(byte[] a, byte[] b) {
        long sum = 0;
        for (int i = 0; i < a.length; i++) sum += (a[i] & 255) - (b[i] & 255);
        return differs(a, b, (int)(sum / a.length));
    }
    private boolean differs(byte[] a, byte[] b, int offset) {
        int changed = 0, scale = a.length == CELLS ? 1 : 2;
        boolean local = false;
        Arrays.fill(windows, 0);
        for (int i = 0; i < a.length; i++) {
            if (Math.abs((a[i] & 255) - (b[i] & 255) - offset) < PageChange.CHANGE_DELTA) continue;
            changed++;
            if (++windows[(i / (WIDTH * scale) / (8 * scale)) * 8 + (i % (WIDTH * scale) / (8 * scale))] * 5 >= 64 * scale * scale) local = true;
            if (changed * 8 >= a.length && local) return true;
        }
        return false;
    }
    void acceptScene() {
        if (valid) reference = latest;
        else reference = null;
    }
    void prime() { if (reference == null && valid) reference = latest; }
    void consumed() { acceptScene(); }
    boolean motionReady(long now) {
        return capacityFallback || valid && hasMotion && now >= lastFrameAt && now - lastFrameAt <= 500
                && now >= motionChangedAt && now - motionChangedAt >= PageChange.STILL_MILLIS;
    }
    void invalidate(String code) { valid = false; hasMotion = false; capacityFallback = false; status = code; }
    private void fallback(String code) {
        first = second = reference = latest = null; hasMotion = false;
        capacityFallback = true; status = code;
    }
    String status() { return status; }
    int evaluatedOffsets() { return evaluatedOffsets; }
    int retainedIntegralInts() { return first == null ? 0 : first.integral.length + second.integral.length; }
    int retainedArrayBytes() {
        if (first == null) return motionReference.length + detailMotion.length + windows.length * 4;
        return arrays(first) + arrays(second) + motionReference.length + detailMotion.length + windows.length * 4;
    }
    private static int arrays(Frame f) {
        return (f.integral.length + f.xs.length + f.ys.length + f.areas.length
                + f.detailXs.length + f.detailYs.length + f.detailAreas.length) * 4 + f.means.length + f.details.length;
    }
}
