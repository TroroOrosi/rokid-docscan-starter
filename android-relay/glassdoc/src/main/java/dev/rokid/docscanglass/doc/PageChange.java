package dev.rokid.docscanglass.doc;

/** Temporal change latch: two visually similar pages are kept if a turn was seen. */
final class PageChange {
    // ponytail: coarse luminance change, tune on real page turns; optical flow if head motion proves ambiguous.
    static final int CHANGE_DELTA = 18;
    static final long STILL_MILLIS = 400;
    private byte[] previous;
    private long changedAt;
    private boolean pending = true;

    void observe(byte[] pixels, long now) {
        if (previous == null || previous.length != pixels.length) changedAt = now;
        else {
            int changed = 0;
            for (int i = 0; i < pixels.length; i++) {
                if (Math.abs((pixels[i] & 255) - (previous[i] & 255)) >= CHANGE_DELTA) changed++;
            }
            if (changed * 5 >= pixels.length) {
                pending = true;
                changedAt = now;
            }
        }
        previous = pixels;
    }

    boolean ready(long now) { return previous != null && pending && now - changedAt >= STILL_MILLIS; }
    void consumed() { pending = false; }
}
