package dev.rokid.docscanglass.doc;

import java.nio.ByteBuffer;

/** Temporal change latch: two visually similar pages are kept if a turn was seen. */
final class PageChange {
    // ponytail: coarse spatial change; head motion/gain changes still need real-page calibration.
    static final int CHANGE_DELTA = 18;
    static final long STILL_MILLIS = 400;
    // GlassCamera supplies a 32x24 grid. Two +/-1 sampling phases differ by at most 2.
    private static final int WIDTH = 32, HEIGHT = 24, JITTER_OFFSET = 2;
    private byte[] reference;
    private byte[] latest;
    private boolean capturedReference;
    private long changedAt;
    private boolean pending = true;
    private long sequence;
    private LumaPageEvidence fine = new LumaPageEvidence();
    private long lastFrameTimestamp, lastFrameAt;
    private String lastCause = "none";
    private int lastOffset, lastShare;
    /**
     * A reported exposure this many times the reference's, or as much less, is the camera's own change of level and
     * not the page's. On the glasses the watch preview's 60 ms against a photo's 30 ms with the gain at its cap is
     * 2.0, and each such step was counted as a page turn (2026-11-16, register 2-29). Smaller steps are compared as
     * before, so a wandering auto exposure does not retake the reference under a slow turn. Unmeasured between.
     */
    static final double EXPOSURE_STEP = 1.25;
    /** Cells this bright are clipped or nearly so and do not follow the exposure. */
    private static final int WHITE = 250;
    /** Exposure time x total gain the camera reported for the reference and for the latest frame; 0 when it did not say. */
    private long referenceLight, latestLight;
    private long exposureSteps;
    private String lastStep = "none";

    void observe(byte[] pixels, long now) { observe(pixels, now, false, 0); }

    void observeFrame(byte[] pixels, ByteBuffer luma, int width, int height, int row, int step,
            long timestamp, long now) {
        observeFrame(pixels, luma, width, height, row, step, timestamp, now, 0);
    }

    /** {@code light}: exposure time x total gain of the capture result that belongs to this frame, 0 when unknown. */
    void observeFrame(byte[] pixels, ByteBuffer luma, int width, int height, int row, int step,
            long timestamp, long now, long light) {
        if (timestamp <= 0 || timestamp <= lastFrameTimestamp || now < lastFrameAt) {
            fine.invalidate("stale_frame"); return;
        }
        lastFrameTimestamp = timestamp; lastFrameAt = now;
        if (!fine.sample(luma, width, height, row, step, now)) return;
        observe(pixels, now, true, light);
    }
    private void observe(byte[] pixels, long now, boolean fullFrame, long light) {
        boolean changed = reference == null || reference.length != pixels.length;
        String cause = changed ? "first" : "coarse";
        // The comparisons below allow one level offset for the whole frame. A change of exposure moves every cell in
        // proportion to its own level instead, so the bright fifth of a dark scene lands over the limit with nothing
        // moved. The reference is first brought to this frame's exposure; what then differs is the page.
        boolean reexposed = !changed && light > 0 && referenceLight > 0
                && Math.max(light, referenceLight) >= EXPOSURE_STEP * Math.min(light, referenceLight);
        if (reexposed) {
            double ratio = (double)light / referenceLight;
            int gain = levelGain(pixels, ratio);
            for (int i = 0; i < reference.length; i++) reference[i] = (byte)Math.min(255, ((reference[i] & 255) * gain + 512) >> 10);
            if (fullFrame) fine.reexpose(gain);
            referenceLight = light;
            lastStep = "exposure_ratio=" + Math.round(ratio * 100) / 100.0 + " level_gain=" + Math.round(gain * 100 / 1024.0) / 100.0;
        }
        if (!changed) {
            changed = differs(pixels, 0, 0);
            if (changed && capturedReference && pixels.length == WIDTH * HEIGHT) {
                // One coherent translation only, never a separate match for each pixel.
                // Unconsumed previewMotion still observes uncompensated movement.
                for (int dy = -JITTER_OFFSET; dy <= JITTER_OFFSET && changed; dy++) {
                    for (int dx = -JITTER_OFFSET; dx <= JITTER_OFFSET && changed; dx++) {
                        if (dx != 0 || dy != 0) changed = differs(pixels, dx, dy);
                    }
                }
            }
        }
        // A captured-page rescue needs one native phase to explain every point and both mean scales.
        boolean samePhase = fullFrame && changed && capturedReference && fine.sameNativePhase(pixels);
        if (samePhase) changed = false;
        if (fullFrame && !changed && !samePhase) { changed = fine.changed(capturedReference, now); cause = "fine"; }
        if (changed) {
            lastCause = cause;
            if (fullFrame) fine.acceptScene();
            pending = true;
            changedAt = now;
            sequence++;
            if (reference == null || reference.length != pixels.length) reference = pixels.clone();
            else System.arraycopy(pixels, 0, reference, 0, pixels.length);
            referenceLight = light;
        } else if (reexposed && !(fullFrame && fine.undecided())) {
            // The same page at the new exposure: the reference is what the camera really shows of it there.
            // A native comparison that was put off keeps the reference it has still to be made against.
            System.arraycopy(pixels, 0, reference, 0, pixels.length);
            if (fullFrame) fine.acceptScene();
        }
        if (reexposed) {
            exposureSteps++;
            lastStep += " left_level_shift=" + lastOffset + " left_cells_over_percent=" + lastShare + " turn=" + changed;
        }
        if (fullFrame) fine.prime();
        // Keep the spatial reference until positive change, shutter issue or a step of the camera's exposure.
        // Adjacent-only comparison loses slow turns; summing motion would count jitter.
        // Preview producers may reuse their array after this observation.
        if (latest == null || latest.length != pixels.length) latest = pixels.clone();
        else System.arraycopy(pixels, 0, latest, 0, pixels.length);
        latestLight = light;
    }

    /**
     * How this frame's levels run against the reference's, in 1024ths: the slope of the best line through the cells
     * that are not clipped, held between no change and the reported change of exposure. A tone curve makes it less
     * than the exposure's ratio; the offset beside it is the one the comparisons subtract anyway.
     */
    private int levelGain(byte[] pixels, double ratio) {
        long n = 0, sx = 0, sy = 0, sxx = 0, sxy = 0;
        for (int i = 0; i < pixels.length; i++) {
            int x = reference[i] & 255, y = pixels[i] & 255;
            if (x >= WHITE || y >= WHITE) continue;
            n++; sx += x; sy += y; sxx += x * x; sxy += x * y;
        }
        long spread = n * sxx - sx * sx;
        // A flat reference has no slope to measure: its level alone says, or the camera's word where it is black.
        double slope = spread > 0 ? (double)(n * sxy - sx * sy) / spread : sx > 0 ? (double)sy / sx : ratio;
        // Past 255 every cell that is not black is white, and a level times the gain still fits an int.
        return (int)Math.round(1024 * Math.min(255, Math.max(Math.min(1, ratio), Math.min(Math.max(1, ratio), slope))));
    }

    private boolean differs(byte[] pixels, int dx, int dy) {
        long sum = 0;
        for (int i = 0; i < pixels.length; i++) sum += (pixels[i] & 255) - (reference[index(i, dx, dy)] & 255);
        int exposureOffset = (int) (sum / pixels.length);
        int changed = 0;
        for (int i = 0; i < pixels.length; i++) {
            if (Math.abs((pixels[i] & 255) - (reference[index(i, dx, dy)] & 255) - exposureOffset) >= CHANGE_DELTA) changed++;
        }
        if (dx == 0 && dy == 0) { lastOffset = exposureOffset; lastShare = changed * 100 / pixels.length; }
        return changed * 5 >= pixels.length;
    }

    private int index(int i, int dx, int dy) {
        if (dx == 0 && dy == 0) return i;
        // Clamp rather than dropping edge samples: outer-page changes remain observable.
        return Math.max(0, Math.min(HEIGHT - 1, i / WIDTH + dy)) * WIDTH
                + Math.max(0, Math.min(WIDTH - 1, i % WIDTH + dx));
    }

    boolean ready(long now) { return reference != null && pending && now - changedAt >= STILL_MILLIS; }
    void consumed() {
        pending = false;
        fine.consumed();
        if (latest != null) {
            System.arraycopy(latest, 0, reference, 0, latest.length);
            referenceLight = latestLight;
            capturedReference = true;
        }
    }
    boolean hasCapturedPage() { return capturedReference; }
    /** The last counted change: which comparison decided it, the mean level shift and the share of cells over the limit. */
    String lastChange() { return "cause=" + lastCause + " level_shift=" + lastOffset + " cells_over_percent=" + lastShare; }
    /** How often the reference was brought to another exposure; the last time's reported ratio, fitted gain and what was left. */
    long exposureSteps() { return exposureSteps; }
    String lastExposureStep() { return lastStep; }
    boolean fineMotionReady(long now) { return fine.motionReady(now); }
    String fineStatus() { return fine.status(); }
    void restartStream() {
        fine = new LumaPageEvidence(); lastFrameTimestamp = lastFrameAt = 0;
    }
    long sequence() { return sequence; }
}
