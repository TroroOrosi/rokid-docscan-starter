package dev.rokid.docscanglass.doc;

import java.nio.ByteBuffer;
import java.util.Arrays;

/**
 * The distance between the lines of print in the watch picture: how near the page is, in the only terms the glasses
 * can measure it. The camera has no focus to set (fixed, sharp from 0.4 m; {@code dumpsys media.camera}), and worn on
 * 2026-11-17 the pages whose lines lay 44 px of the recorded frame and more apart could not be read at all (0 to 2% of
 * a known text found, twelve reads each), while 39 to 42 px gave 24 to 81% (M-43).
 *
 * <p>The middle 128x128 px of the picture under a Hann window, in a transform of that size; the strongest wave whose
 * period is 4 to 14 picture px (25 to 88 px of the frame through a 320-px picture), its place made finer by the
 * centre of mass of the 3x3 around it. Tried on 25 worn clips reduced to 320x240, it gave the full frame's figure
 * within 0.7 px; on print the peak stood 650 to 2,000 times over the band's median, on scenes without print 57 to
 * 331. Lines running either way are found: the wave's direction is not used. A 240-px window in a 256-point
 * transform was no nearer the full frame's figure and took the watch handler on the glasses from 31-48 ms a frame to
 * 70-95 ms.</p>
 *
 * <p>Not safe for two threads: one instance belongs to the thread that takes the watch frames.</p>
 */
final class PrintPitch {
    /** A peak this far over the band's median is print. */
    static final float SURE = 500f;
    private static final int N = 128, SIDE = 128;
    private static final float LOW = 4f, HIGH = 14f;
    private static final float[] WINDOW = new float[SIDE], COS = new float[N / 2], SIN = new float[N / 2];
    private static final int[] REVERSED = new int[N];

    static {
        for (int i = 0; i < SIDE; i++) WINDOW[i] = (float) (0.5 - 0.5 * Math.cos(2 * Math.PI * i / (SIDE - 1)));
        for (int i = 0; i < N / 2; i++) {
            COS[i] = (float) Math.cos(2 * Math.PI * i / N);
            SIN[i] = (float) -Math.sin(2 * Math.PI * i / N);
        }
        for (int i = 0; i < N; i++) REVERSED[i] = Integer.reverse(i) >>> (32 - 7);
    }

    private final float[] real = new float[N * N], imaginary = new float[N * N];
    private final float[] lineReal = new float[N], lineImaginary = new float[N];
    private final float[] band = new float[N * (N / 2 + 1)];
    /** Picture px between two lines of print, after {@link #measure} returned true. */
    float period;
    /** How far the strongest wave stands over the median of its band; print when at least {@link #SURE}. */
    float stands;

    /**
     * Measures the luminance plane {@code pixels} ({@code width} x {@code height}, rows {@code row} bytes apart,
     * pixels {@code step}). False when the picture is too small to hold the window; then nothing is known.
     */
    boolean measure(ByteBuffer pixels, int width, int height, int row, int step) {
        if (width < SIDE || height < SIDE) return false;
        int left = (width - SIDE) / 2, top = (height - SIDE) / 2;
        double sum = 0;
        for (int y = 0; y < SIDE; y++) for (int x = 0; x < SIDE; x++) sum += pixels.get((top + y) * row + (left + x) * step) & 255;
        float mean = (float) (sum / (SIDE * SIDE));
        Arrays.fill(real, 0f);
        Arrays.fill(imaginary, 0f);
        for (int y = 0; y < SIDE; y++) for (int x = 0; x < SIDE; x++) {
            real[y * N + x] = ((pixels.get((top + y) * row + (left + x) * step) & 255) - mean) * WINDOW[y] * WINDOW[x];
        }
        for (int y = 0; y < SIDE; y++) { // the rows below the window are zero and stay zero
            System.arraycopy(real, y * N, lineReal, 0, N);
            Arrays.fill(lineImaginary, 0f);
            transform(lineReal, lineImaginary);
            System.arraycopy(lineReal, 0, real, y * N, N);
            System.arraycopy(lineImaginary, 0, imaginary, y * N, N);
        }
        for (int x = 0; x <= N / 2; x++) { // the other half of the columns is this half's mirror
            for (int y = 0; y < N; y++) { lineReal[y] = real[y * N + x]; lineImaginary[y] = imaginary[y * N + x]; }
            transform(lineReal, lineImaginary);
            for (int y = 0; y < N; y++) real[y * N + x] = lineReal[y] * lineReal[y] + lineImaginary[y] * lineImaginary[y];
        }
        // real now holds the power of the waves (y: 0..N-1, x: 0..N/2)
        int count = 0, bestY = 0, bestX = 0;
        float best = -1f;
        for (int y = 0; y < N; y++) {
            float fy = (y < N / 2 ? y : y - N) / (float) N;
            for (int x = 0; x <= N / 2; x++) {
                float fx = x / (float) N;
                float radius = (float) Math.sqrt(fy * fy + fx * fx);
                if (radius < 1f / HIGH || radius > 1f / LOW) continue;
                float power = real[y * N + x];
                band[count++] = power;
                if (power > best) { best = power; bestY = y; bestX = x; }
            }
        }
        if (count == 0 || best <= 0f) { period = 0f; stands = 0f; return true; }
        Arrays.sort(band, 0, count);
        float median = band[count / 2];
        stands = median > 0f ? best / median : 0f;
        double weight = 0, atY = 0, atX = 0;
        for (int dy = -1; dy <= 1; dy++) for (int dx = -1; dx <= 1; dx++) {
            int y = bestY + dy, x = bestX + dx;
            float fy = ((bestY < N / 2 ? bestY : bestY - N) + dy) / (float) N, fx = x / (float) N;
            if (x < 0) { x = -x; y = -y; } // the mirror wave
            if (x > N / 2) continue;
            float power = real[((y % N) + N) % N * N + x];
            weight += power; atY += power * fy; atX += power * fx;
        }
        double radius = weight > 0 ? Math.hypot(atY / weight, atX / weight) : 0;
        period = radius > 0 ? (float) (1 / radius) : 0f;
        return true;
    }

    /** In place, radix 2, {@code N} long. */
    private static void transform(float[] re, float[] im) {
        for (int i = 0; i < N; i++) {
            int j = REVERSED[i];
            if (j > i) { float t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; }
        }
        for (int size = 2; size <= N; size <<= 1) {
            int half = size >> 1, stride = N / size;
            for (int start = 0; start < N; start += size) {
                for (int k = 0; k < half; k++) {
                    float c = COS[k * stride], s = SIN[k * stride];
                    int a = start + k, b = a + half;
                    float tr = re[b] * c - im[b] * s, ti = re[b] * s + im[b] * c;
                    re[b] = re[a] - tr; im[b] = im[a] - ti;
                    re[a] += tr; im[a] += ti;
                }
            }
        }
    }
}
