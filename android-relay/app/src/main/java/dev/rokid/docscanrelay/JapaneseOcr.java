package dev.rokid.docscanrelay;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Rect;

import com.google.mlkit.vision.common.InputImage;
import com.google.mlkit.vision.text.Text;
import com.google.mlkit.vision.text.TextRecognition;
import com.google.mlkit.vision.text.TextRecognizer;
import com.google.mlkit.vision.text.japanese.JapaneseTextRecognizerOptions;

/** Bundled, on-device OCR used before a captured page is uploaded. */
public final class JapaneseOcr implements AutoCloseable {
    public interface Callback {
        void onResult(String text, OcrQuality quality, PageFraming framing);

        void onError(Throwable error);
    }

    private final TextRecognizer recognizer = TextRecognition.getClient(
            new JapaneseTextRecognizerOptions.Builder().build());

    public void recognize(byte[] encodedImage, int rotationDegrees, Callback callback) {
        Bitmap bitmap;
        try {
            bitmap = BitmapFactory.decodeByteArray(encodedImage, 0, encodedImage.length);
        } catch (OutOfMemoryError error) {
            // A 12MP capture needs about 48MB for the decoded bitmap. Losing
            // the process here would also lose the photo, so the capture is
            // reported as an OCR failure and stays available for review.
            callback.onError(new IllegalStateException(
                    "写真が大きすぎてメモリに展開できません。撮影解像度を下げてください"));
            return;
        }
        if (bitmap == null) {
            callback.onError(new IllegalArgumentException("写真をBitmapとして復号できません"));
            return;
        }
        int normalizedRotation = normalizeRotation(rotationDegrees);
        // ML Kit reports bounding boxes in the upright image it was handed, so
        // a quarter turn swaps the dimensions the framing check measures
        // against.
        boolean quarterTurned = normalizedRotation == 90 || normalizedRotation == 270;
        int uprightWidth = quarterTurned ? bitmap.getHeight() : bitmap.getWidth();
        int uprightHeight = quarterTurned ? bitmap.getWidth() : bitmap.getHeight();
        InputImage input = InputImage.fromBitmap(bitmap, normalizedRotation);
        recognizer.process(input)
                .addOnSuccessListener(
                        result -> callback.onResult(
                                result.getText().trim(),
                                measure(result),
                                measureFraming(result, uprightWidth, uprightHeight)))
                .addOnFailureListener(callback::onError)
                .addOnCompleteListener(ignored -> bitmap.recycle());
    }

    /**
     * Judges whether the page is wholly inside the frame from where the
     * recognised lines sit.
     */
    private static PageFraming measureFraming(Text result, int width, int height) {
        PageFraming.Builder framing = PageFraming.builder(width, height);
        for (Text.TextBlock block : result.getTextBlocks()) {
            for (Text.Line line : block.getLines()) {
                Rect bounds = line.getBoundingBox();
                if (bounds == null) {
                    continue;
                }
                framing.addLineBounds(
                        bounds.left, bounds.top, bounds.right, bounds.bottom);
            }
        }
        return framing.build();
    }

    /**
     * Collects per-symbol confidence so a capture that returned text can still
     * be reported as unreliable.
     *
     * <p>Confidence is only populated by the bundled recogniser, so the builder
     * tolerates its absence rather than assuming it.</p>
     */
    private static OcrQuality measure(Text result) {
        OcrQuality.Builder quality = OcrQuality.builder();
        for (Text.TextBlock block : result.getTextBlocks()) {
            for (Text.Line line : block.getLines()) {
                for (Text.Element element : line.getElements()) {
                    for (Text.Symbol symbol : element.getSymbols()) {
                        quality.addSymbol(symbol.getText(), symbol.getConfidence());
                    }
                }
            }
        }
        return quality.build();
    }

    static int normalizeRotation(int degrees) {
        int normalized = ((degrees % 360) + 360) % 360;
        if (normalized < 45) {
            return 0;
        }
        if (normalized < 135) {
            return 90;
        }
        if (normalized < 225) {
            return 180;
        }
        if (normalized < 315) {
            return 270;
        }
        return 0;
    }

    @Override
    public void close() {
        recognizer.close();
    }
}
