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

    void observe(byte[] pixels, long now) { observe(pixels, now, false); }

    void observeFrame(byte[] pixels, ByteBuffer luma, int width, int height, int row, int step,
            long timestamp, long now) {
        if (timestamp <= 0 || timestamp <= lastFrameTimestamp || now < lastFrameAt) {
            fine.invalidate("stale_frame"); return;
        }
        lastFrameTimestamp = timestamp; lastFrameAt = now;
        if (!fine.sample(luma, width, height, row, step, now)) return;
        observe(pixels, now, true);
    }
    private void observe(byte[] pixels, long now, boolean fullFrame) {
        boolean changed = reference == null || reference.length != pixels.length;
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
        if (fullFrame && !changed && !samePhase) changed = fine.changed(capturedReference, now);
        if (changed) {
            if (fullFrame) fine.acceptScene();
            pending = true;
            changedAt = now;
            sequence++;
            if (reference == null || reference.length != pixels.length) reference = pixels.clone();
            else System.arraycopy(pixels, 0, reference, 0, pixels.length);
        }
        if (fullFrame) fine.prime();
        // Keep the spatial reference until positive change or shutter issue.
        // Adjacent-only comparison loses slow turns; summing motion would count jitter.
        // Preview producers may reuse their array after this observation.
        if (latest == null || latest.length != pixels.length) latest = pixels.clone();
        else System.arraycopy(pixels, 0, latest, 0, pixels.length);
    }

    private boolean differs(byte[] pixels, int dx, int dy) {
        long sum = 0;
        for (int i = 0; i < pixels.length; i++) sum += (pixels[i] & 255) - (reference[index(i, dx, dy)] & 255);
        int exposureOffset = (int) (sum / pixels.length);
        int changed = 0;
        for (int i = 0; i < pixels.length; i++) {
            if (Math.abs((pixels[i] & 255) - (reference[index(i, dx, dy)] & 255) - exposureOffset) >= CHANGE_DELTA) changed++;
        }
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
            capturedReference = true;
        }
    }
    boolean fineMotionReady(long now) { return fine.motionReady(now); }
    String fineStatus() { return fine.status(); }
    void restartStream() {
        fine = new LumaPageEvidence(); lastFrameTimestamp = lastFrameAt = 0;
    }
    long sequence() { return sequence; }
}
