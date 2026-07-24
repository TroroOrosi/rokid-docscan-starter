package dev.rokid.docscanrelay;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;

import com.google.mlkit.vision.common.InputImage;
import com.google.mlkit.vision.text.TextRecognition;
import com.google.mlkit.vision.text.TextRecognizer;
import com.google.mlkit.vision.text.japanese.JapaneseTextRecognizerOptions;

/** Bundled, on-device OCR used before a captured page is uploaded. */
public final class JapaneseOcr implements AutoCloseable {
    public interface Callback {
        void onResult(String text);

        void onError(Throwable error);
    }

    private final TextRecognizer recognizer = TextRecognition.getClient(
            new JapaneseTextRecognizerOptions.Builder().build());

    public void recognize(byte[] encodedImage, int rotationDegrees, Callback callback) {
        Bitmap bitmap = BitmapFactory.decodeByteArray(encodedImage, 0, encodedImage.length);
        if (bitmap == null) {
            callback.onError(new IllegalArgumentException("写真をBitmapとして復号できません"));
            return;
        }
        int normalizedRotation = normalizeRotation(rotationDegrees);
        InputImage input = InputImage.fromBitmap(bitmap, normalizedRotation);
        recognizer.process(input)
                .addOnSuccessListener(result -> callback.onResult(result.getText().trim()))
                .addOnFailureListener(callback::onError)
                .addOnCompleteListener(ignored -> bitmap.recycle());
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
