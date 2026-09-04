package dev.rokid.docscanglass.doc;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Rect;
import android.util.Log;

import dev.rokid.docscanrelay.PageFraming;

import com.google.mlkit.vision.common.InputImage;
import com.google.mlkit.vision.text.Text;
import com.google.mlkit.vision.text.TextRecognition;
import com.google.mlkit.vision.text.TextRecognizer;
import com.google.mlkit.vision.text.japanese.JapaneseTextRecognizerOptions;

/**
 * Bundled Japanese recognition, on the glasses.
 *
 * <p>The same recognizer the phone relay uses, moved to where the photograph is
 * taken. The server's {@code add_page} would accept an image with no text, but
 * finalization fails when no image-capable analyzer is configured, and the
 * analyzer this repository runs against reports {@code placeholder-1.0.0}. So
 * the text is produced here and the documented contract -- upload the JPEG and
 * the OCR -- holds with no cloud key.
 *
 * <p>Decoding matters on this device. The stills are 4032x3024, which is
 * 48 MB as ARGB_8888 against a 256 MB heap on a build that reports
 * {@code ro.config.low_ram=true}. The bitmap handed to ML Kit is therefore
 * subsampled. The measured column pitch of a photographed page is 37 px against
 * ML Kit's documented 16 px floor, so halving twice still leaves glyphs above
 * the floor while cutting the bitmap to about 3 MB.
 */
final class PageOcr {

    private static final String TAG = "DocScanGlassDoc";

    /**
     * Longest edge handed to the recognizer. 4032 / 4 = 1008, which keeps the
     * measured 37 px column pitch at about 9 px -- below ML Kit's floor -- so
     * the divisor is bounded to 2 and the target is expressed in pixels
     * instead.
     */
    private static final int MAX_EDGE_PIXELS = 2048;

    interface Callback {
        /**
         * @param framing which sides of the page the recognized text runs off,
         *     computed from the same line boxes the text came from
         */
        void onRecognized(String text, PageFraming framing);

        void onRecognitionFailed(String reason);
    }

    private final TextRecognizer recognizer =
            TextRecognition.getClient(new JapaneseTextRecognizerOptions.Builder().build());

    /** Runs asynchronously; the callback arrives on ML Kit's own executor. */
    void recognize(byte[] jpeg, Callback callback) {
        Bitmap bitmap;
        try {
            bitmap = decodeSubsampled(jpeg);
        } catch (RuntimeException error) {
            callback.onRecognitionFailed("decode " + error.getClass().getSimpleName());
            return;
        }
        if (bitmap == null) {
            callback.onRecognitionFailed("decode returned null");
            return;
        }
        recognizer.process(InputImage.fromBitmap(
                bitmap, ReviewFrame.MEASURED_ROTATION_DEGREES))
                .addOnSuccessListener(text -> {
                    PageFraming framing = frame(text, bitmap.getWidth(), bitmap.getHeight());
                    bitmap.recycle();
                    String recognized = flatten(text);
                    Log.i(TAG, "ocr " + recognized.length() + " chars, framing "
                            + framing.describe());
                    callback.onRecognized(recognized, framing);
                })
                .addOnFailureListener(error -> {
                    bitmap.recycle();
                    callback.onRecognitionFailed("ocr " + error.getClass().getSimpleName());
                });
    }

    void close() {
        recognizer.close();
    }

    /**
     * Reads the header first so the sample size is chosen from the real
     * dimensions rather than from an assumption about the sensor.
     */
    private static Bitmap decodeSubsampled(byte[] jpeg) {
        BitmapFactory.Options bounds = new BitmapFactory.Options();
        bounds.inJustDecodeBounds = true;
        BitmapFactory.decodeByteArray(jpeg, 0, jpeg.length, bounds);

        int sample = 1;
        int longest = Math.max(bounds.outWidth, bounds.outHeight);
        while (longest / (sample * 2) >= MAX_EDGE_PIXELS) {
            sample *= 2;
        }

        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inSampleSize = sample;
        // RGB_565 halves the bitmap again. Recognition is on glyph shape, and
        // the display is monochrome green regardless.
        options.inPreferredConfig = Bitmap.Config.RGB_565;
        return BitmapFactory.decodeByteArray(jpeg, 0, jpeg.length, options);
    }

    /**
     * Feeds the recognized line boxes to the relay's framing check, which is
     * the one the operator judged better on hardware. It knows which side is
     * cut, because it looks at where the text is, not at how dark the border is.
     */
    private static PageFraming frame(Text text, int width, int height) {
        PageFraming.Builder builder = PageFraming.builder(width, height);
        for (Text.TextBlock block : text.getTextBlocks()) {
            for (Text.Line line : block.getLines()) {
                Rect box = line.getBoundingBox();
                if (box != null) {
                    builder.addLineBounds(box.left, box.top, box.right, box.bottom);
                }
            }
        }
        return builder.build();
    }

    /** One line per recognized line, in reading order, with no padding. */
    private static String flatten(Text text) {
        StringBuilder joined = new StringBuilder();
        for (Text.TextBlock block : text.getTextBlocks()) {
            for (Text.Line line : block.getLines()) {
                if (joined.length() > 0) {
                    joined.append('\n');
                }
                joined.append(line.getText());
            }
        }
        return joined.toString().trim();
    }
}
