package dev.rokid.docscanrelay;

/** Conservative relative evidence on nine unchanged 64x64 native-pixel regions. No OCR or acceptance verdict. */
public final class NativeImageQuality {
    public static final int EDGE = 64, REGIONS = 9;
    public enum Decision { KEEP_A, SELECT_B, UNKNOWN }

    public static final class Sample {
        public final int width, height;
        private final byte[] pixels;
        public Sample(int width, int height, byte[] pixels) {
            if (width < EDGE * 3 || height < EDGE * 3 || pixels == null || pixels.length != REGIONS * EDGE * EDGE)
                throw new IllegalArgumentException("native region dimensions");
            this.width = width; this.height = height; this.pixels = pixels.clone();
        }
    }

    private record Metrics(double edge, double noise, double clipped, double[] cells) { }
    private NativeImageQuality() { }

    public static Decision choose(Sample a, Sample b) {
        if (a == null || b == null || a.width != b.width || a.height != b.height) return Decision.UNKNOWN;
        int informative = 0, improved = 0;
        for (int region = 0; region < REGIONS; region++) {
            Metrics x = measure(a.pixels, region), y = measure(b.pixels, region);
            if (!Double.isFinite(x.noise) || !Double.isFinite(y.noise)) return Decision.UNKNOWN;
            // Matching coarse native regions is required in addition to the camera's monotonic scene identity.
            double offset = 0;
            for (int i = 0; i < 16; i++) offset += y.cells[i] - x.cells[i];
            offset /= 16;
            if (Math.abs(offset) > 8) return Decision.UNKNOWN;
            double residual = 0;
            for (int i = 0; i < 16; i++) {
                double difference = Math.abs(y.cells[i] - x.cells[i] - offset);
                if (difference > 20) return Decision.UNKNOWN;
                residual += difference;
            }
            if (residual / 16 > 6 || y.clipped > x.clipped + .002
                    || y.noise > x.noise + 1.0) return Decision.UNKNOWN;
            if (x.edge >= 1) {
                informative++;
                if (y.edge < x.edge * .9) return Decision.UNKNOWN;
                if (y.edge >= x.edge * 1.2) improved++;
            }
        }
        if (informative < 6) return Decision.UNKNOWN;
        // A broad 20% margin, no degrading region, and no increased clipping/noise; thresholds are uncalibrated.
        return improved >= 6 ? Decision.SELECT_B : Decision.KEEP_A;
    }

    private static Metrics measure(byte[] pixels, int region) {
        int base = region * EDGE * EDGE, clipped = 0, flat = 0;
        double edge = 0, noise = 0;
        double[] cells = new double[16];
        for (int y = 0; y < EDGE; y++) for (int x = 0; x < EDGE; x++) {
            int value = pixels[base + y * EDGE + x] & 255;
            cells[y / 16 * 4 + x / 16] += value / 256d;
            if (value <= 4 || value >= 251) clipped++;
            if (x == 0 || y == 0 || x == EDGE - 1 || y == EDGE - 1) continue;
            int left = pixels[base + y * EDGE + x - 1] & 255, right = pixels[base + y * EDGE + x + 1] & 255;
            int up = pixels[base + (y - 1) * EDGE + x] & 255, down = pixels[base + (y + 1) * EDGE + x] & 255;
            edge += (Math.abs(right - left) + Math.abs(down - up)) / 2d;
            if (Math.abs(right - left) + Math.abs(down - up) < 8) {
                noise += Math.abs(4 * value - left - right - up - down) / 4d;
                flat++;
            }
        }
        return new Metrics(edge / ((EDGE - 2) * (EDGE - 2)), flat < 256 ? Double.POSITIVE_INFINITY : noise / flat,
                clipped / (double)(EDGE * EDGE), cells);
    }
}
