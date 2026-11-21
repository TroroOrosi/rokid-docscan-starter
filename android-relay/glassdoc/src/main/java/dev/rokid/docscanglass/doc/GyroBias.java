package dev.rokid.docscanglass.doc;

import java.util.Arrays;

/**
 * The gyroscope's zero offset, followed while the camera is open and taken out of each reading.
 *
 * <p>The sensor the glasses hand an app reads a turn when there is none, and more the longer they are worn: +0.014
 * rad/s about its y axis at a booklet's first page and +0.043 at its twelfth (2026-11-20; every worn booklet on record
 * climbs like that, the glasses lying on a desk reach 0.009). A frame counts as still under 2 px of smear, which is
 * 0.035 rad/s at 30 ms, so the offset alone used the limit up: 4 of 296 frames counted while the picture stood within
 * 28 px of its first frame for nine seconds, and the page was recorded three times.</p>
 *
 * <p>An offset drifts slowly (0.0003 rad/s a second at most on record) and a head does not turn one way for long, so:
 * twice a second the last two seconds of readings are looked at; when they are quiet on every axis their medians are
 * where the offset is taken to be, and the kept value moves towards them no faster than an offset drifts, by one
 * bounded step the first time and after a pause ({@link #STEP_SECONDS}). Replayed over the 231 clips on record, worn
 * and desk, this let every still frame of the page above count (60 after 92 frames) and shortened the recordings
 * to 0.89 of their frames; eight clips counted fewer frames in the same recording (3 to 10 of 60 on six pages of one
 * restless booklet, where the frames that changed sides move about 2 px in the picture either way). Of the frames
 * it newly called still on the page above, 94 in 100 moved under 2.2 px to the next frame in the picture itself
 * (docs/hardware-measurements.md M-45).</p>
 *
 * <p>It sees turning only. A paper pulled across the desk does not turn the head (register 2-41).</p>
 */
final class GyroBias {
    static final long WINDOW_NANOS = 2_000_000_000L;
    /** Readings between two looks, and the fewest a window may hold (200 a second arrive). */
    static final int EVERY = 100, LEAST = 300;
    /** A still worn head: the median distance of each axis from its median, rad/s. */
    static final float QUIET_RAD_S = 0.008f;
    /** Ten times the fastest drift seen would be 0.003; a third of that keeps a smooth pan of some seconds out. */
    static final float SLEW_RAD_S_PER_S = 0.001f;
    static final float MOST_RAD_S = 0.1f;
    /**
     * The longest time one look may make up for: 0.02 rad/s a step, 1.1 px in 30 ms. Quiet readings are a still head
     * with an offset or a head that pans evenly, and two seconds cannot tell which. Bounded so, a pan taken for the
     * offset leaves a head that then stands still under the 2 px a still frame may have; taken whole it would have
     * read as turning, and no frame of its page would count. Of 272 quiet windows worn on record none lay further
     * than 0.015 rad/s from the offset (one wearer), and the replay over 231 clips is the same with and without it.
     */
    static final float STEP_SECONDS = 20f;
    private static final int HELD = 512;

    private final long[] at = new long[HELD];
    private final float[][] axis = new float[3][HELD];
    private final float[][] sorted = new float[3][HELD];
    private final float[] value = new float[3];
    private int next, size, sinceLook;
    private long last = Long.MIN_VALUE, valueAt;
    private boolean known;

    /** One reading, in the order the sensor made them. Returns its speed with the offset taken out, rad/s. */
    synchronized float add(long timestampNanos, float x, float y, float z) {
        if (!Float.isFinite(x) || !Float.isFinite(y) || !Float.isFinite(z)) return Float.POSITIVE_INFINITY;
        float dx = x - value[0], dy = y - value[1], dz = z - value[2];
        float speed = (float) Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (timestampNanos <= last) return speed;
        last = timestampNanos;
        at[next] = timestampNanos;
        axis[0][next] = x; axis[1][next] = y; axis[2][next] = z;
        next = (next + 1) % HELD;
        if (size < HELD) size++;
        if (++sinceLook >= EVERY) {
            sinceLook = 0;
            look(timestampNanos);
        }
        return speed;
    }

    private void look(long now) {
        int count = 0;
        for (int i = 0; i < size; i++) {
            if (now - at[i] >= WINDOW_NANOS) continue;
            for (int a = 0; a < 3; a++) sorted[a][count] = axis[a][i];
            count++;
        }
        if (count < LEAST) return;
        float[] middle = new float[3];
        for (int a = 0; a < 3; a++) {
            Arrays.sort(sorted[a], 0, count);
            middle[a] = sorted[a][count / 2];
            if (Math.abs(middle[a]) > MOST_RAD_S) return;
        }
        for (int a = 0; a < 3; a++) {
            for (int i = 0; i < count; i++) sorted[a][i] = Math.abs(sorted[a][i] - middle[a]);
            Arrays.sort(sorted[a], 0, count);
            if (sorted[a][count / 2] > QUIET_RAD_S) return;
        }
        // The readings held all lie within two seconds of now: a pause shows as time since the value was last set.
        // Never at once, the first time and after a pause included: what STEP_SECONDS of drift come to, at most.
        float seconds = known ? Math.max(0f, (now - valueAt) / 1e9f) : STEP_SECONDS;
        float reach = SLEW_RAD_S_PER_S * Math.min(STEP_SECONDS, seconds);
        for (int a = 0; a < 3; a++) value[a] += Math.max(-reach, Math.min(reach, middle[a] - value[a]));
        known = true;
        valueAt = now;
    }

    synchronized boolean known() { return known; }

    /** The offset in use, rad/s about the sensor's x, y and z. */
    synchronized float[] value() { return value.clone(); }
}
