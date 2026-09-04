package dev.rokid.docscanglass.doc;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Matrix;

/**
 * What the HUD shows the operator between the shutter and the upload.
 *
 * <p>The operator cannot see through the camera. A live viewfinder would fix
 * that, but the privacy indicator is lit for exactly as long as the camera
 * streams -- measured at 673-1143 ms for a single shot -- so a viewfinder would
 * trade a brief indicator for a permanently lit one. Reviewing the still costs
 * no extra camera time at all.
 *
 * <p>Also carries the four statistics {@link CaptureQuality} judges, computed
 * from the same small bitmap the HUD draws, so the check costs one decode.
 */
final class ReviewFrame {

    /**
     * Measured on hardware 2026-09-04. The glasses report
     * {@code SENSOR_ORIENTATION = 270}, and a still taken with
     * {@code JPEG_ORIENTATION = 0} stores 180 degrees from upright: the first
     * three pages uploaded upside down, which is why the recognizer returned
     * garbled text. The rotation is applied by the server, which owns the
     * normalized PNG, and here for recognition and review.
     */
    static final int MEASURED_ROTATION_DEGREES = 180;

    /** Fits the 480x640 display with room for the three text lines. */
    private static final int PREVIEW_LONGEST_EDGE = 480;

    /** Border band sampled for the framing check, as a fraction of each edge. */
    private static final double BORDER_FRACTION = 0.04;

    private final Bitmap preview;
    private final CaptureQuality.Verdict verdict;

    private ReviewFrame(Bitmap preview, CaptureQuality.Verdict verdict) {
        this.preview = preview;
        this.verdict = verdict;
    }

    Bitmap preview() {
        return preview;
    }

    CaptureQuality.Verdict verdict() {
        return verdict;
    }

    void recycle() {
        if (preview != null && !preview.isRecycled()) {
            preview.recycle();
        }
    }

    /** Decodes once, at preview size, and judges from the same pixels. */
    static ReviewFrame of(byte[] jpeg) {
        BitmapFactory.Options bounds = new BitmapFactory.Options();
        bounds.inJustDecodeBounds = true;
        BitmapFactory.decodeByteArray(jpeg, 0, jpeg.length, bounds);

        int sample = 1;
        int longest = Math.max(bounds.outWidth, bounds.outHeight);
        while (longest / (sample * 2) >= PREVIEW_LONGEST_EDGE) {
            sample *= 2;
        }
        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inSampleSize = sample;
        options.inPreferredConfig = Bitmap.Config.RGB_565;
        Bitmap decoded = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.length, options);
        if (decoded == null) {
            return new ReviewFrame(null, CaptureQuality.Verdict.NO_CONTRAST);
        }
        Bitmap upright = rotate(decoded);
        return new ReviewFrame(upright, judge(upright));
    }

    private static Bitmap rotate(Bitmap source) {
        if (MEASURED_ROTATION_DEGREES == 0) {
            return source;
        }
        Matrix matrix = new Matrix();
        matrix.postRotate(MEASURED_ROTATION_DEGREES);
        Bitmap rotated = Bitmap.createBitmap(
                source, 0, 0, source.getWidth(), source.getHeight(), matrix, false);
        if (rotated != source) {
            source.recycle();
        }
        return rotated;
    }

    private static CaptureQuality.Verdict judge(Bitmap bitmap) {
        int width = bitmap.getWidth();
        int height = bitmap.getHeight();
        int[] pixels = new int[width * height];
        bitmap.getPixels(pixels, 0, width, 0, 0, width, height);

        long sum = 0;
        long squares = 0;
        for (int pixel : pixels) {
            int luminance = luminanceOf(pixel);
            sum += luminance;
            squares += (long) luminance * luminance;
        }
        int count = pixels.length;
        double mean = sum / (double) count;
        double variance = Math.max(0, squares / (double) count - mean * mean);

        int bandX = Math.max(1, (int) (width * BORDER_FRACTION));
        int bandY = Math.max(1, (int) (height * BORDER_FRACTION));
        long borderPixels = 0;
        long borderInk = 0;
        for (int y = 0; y < height; y++) {
            boolean horizontalBand = y < bandY || y >= height - bandY;
            for (int x = 0; x < width; x++) {
                if (!horizontalBand && x >= bandX && x < width - bandX) {
                    continue;
                }
                borderPixels++;
                // "Ink" is anything clearly darker than the frame average; on a
                // page that fills the frame the border is paper, not text.
                if (luminanceOf(pixels[y * width + x]) < mean * 0.6) {
                    borderInk++;
                }
            }
        }
        double borderInkFraction = borderPixels == 0 ? 0 : borderInk / (double) borderPixels;
        return CaptureQuality.judge(
                (int) Math.round(mean), (int) Math.round(Math.sqrt(variance)),
                borderInkFraction, 0);
    }

    private static int luminanceOf(int pixel) {
        int r = (pixel >> 16) & 0xFF;
        int g = (pixel >> 8) & 0xFF;
        int b = pixel & 0xFF;
        return (r * 77 + g * 151 + b * 28) >> 8;
    }
}
