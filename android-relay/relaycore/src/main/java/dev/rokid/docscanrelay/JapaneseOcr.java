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

    // The chooser does not need a native recognizer. Open it only for actual OCR.
    private TextRecognizer recognizer;
    private boolean closed;

    private synchronized TextRecognizer recognizer() {
        if (closed) throw new IllegalStateException("OCRは終了しています");
        if (recognizer == null) recognizer = TextRecognition.getClient(
                new JapaneseTextRecognizerOptions.Builder().build());
        return recognizer;
    }

    public void recognize(byte[] encodedImage, int rotationDegrees, Callback callback) {
        Bitmap bitmap;
        try {
            synchronized (this) {
                if (closed) throw new IllegalStateException("OCRは終了しています");
            }
            bitmap = encodedImage == null ? null : decodeSubsampled(encodedImage);
        } catch (OutOfMemoryError error) {
            callback.onError(memoryError());
            return;
        } catch (RuntimeException error) {
            callback.onError(error);
            return;
        }
        if (bitmap == null) {
            callback.onError(new IllegalArgumentException("写真をBitmapとして復号できません"));
            return;
        }
        int normalizedRotation = normalizeRotation(rotationDegrees);
        boolean quarterTurned = normalizedRotation == 90 || normalizedRotation == 270;
        int uprightWidth = quarterTurned ? bitmap.getHeight() : bitmap.getWidth();
        int uprightHeight = quarterTurned ? bitmap.getWidth() : bitmap.getHeight();
        com.google.android.gms.tasks.Task<Text> task;
        try {
            InputImage input = InputImage.fromBitmap(bitmap, normalizedRotation);
            task = recognizer().process(input);
        } catch (RuntimeException | OutOfMemoryError error) {
            bitmap.recycle();
            callback.onError(error instanceof OutOfMemoryError ? memoryError() : error);
            return;
        }
        task.addOnCompleteListener(completed -> {
            String text = null;
            OcrQuality quality = null;
            PageFraming framing = null;
            Throwable failure = null;
            try {
                if (completed.isSuccessful()) {
                    Text result = completed.getResult();
                    text = result.getText().trim();
                    quality = measure(result);
                    framing = measureFraming(result, uprightWidth, uprightHeight);
                } else {
                    failure = completed.getException();
                    if (failure == null) failure = new IllegalStateException("OCRが中断されました");
                }
            } catch (RuntimeException | OutOfMemoryError error) {
                failure = error instanceof OutOfMemoryError ? memoryError() : error;
            } finally {
                // Release BEFORE the callback can queue preview/next-shot allocation.
                // A callback exception must not prevent disposal or call it twice.
                bitmap.recycle();
            }
            if (failure == null) callback.onResult(text, quality, framing);
            else callback.onError(failure);
        });
    }

    private static IllegalStateException memoryError() {
        return new IllegalStateException("OCRのメモリが不足しています。写真を保持して終了・再開してください");
    }

    /**
     * Measures recognized TEXT bounds, not physical paper corners. Blank margins,
     * missed lines, figures and an obstructed page cannot be certified by OCR.
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

    /**
     * Longest edge below which the decoder refuses to halve again.
     *
     * <p>Two measurements bound this. {@code docs/hardware-measurements.md} §C-2b
     * read a 37 px column pitch off a 1920x1080 capture of an A4 page at
     * 40-60 cm, against ML Kit's 16 px floor, and called 24 px the point
     * beyond which more resolution stops helping. The same page at 4032 px
     * therefore carries roughly 78 px per character, so halving it to 2016
     * leaves about 39 px, while quartering it would land near 19 px: above
     * the floor, but below where resolution still pays.</p>
     *
     * <p>The reason to subsample at all is memory. 4032x3024 decoded whole
     * needs about 48 MB, and the glasses run with {@code ro.config.low_ram},
     * where 118 MB RSS was enough for lowmemorykiller to act. The relay's
     * default 1920x1080 capture sits below this bound and is left untouched.</p>
     */
    static final int MIN_EDGE_PIXELS = 1200;

    /**
     * The {@code inSampleSize} for an image of this longest edge: the largest
     * power-of-two reduction that still leaves {@link #MIN_EDGE_PIXELS}.
     */
    static int sampleSizeFor(int longestEdge) {
        int sample = 1;
        while (longestEdge / (sample * 2) >= MIN_EDGE_PIXELS) {
            sample *= 2;
        }
        return sample;
    }

    /**
     * Reads the JPEG header first, so the reduction follows the real
     * dimensions rather than an assumption about which preset took the shot.
     */
    private static Bitmap decodeSubsampled(byte[] encodedImage) {
        BitmapFactory.Options bounds = new BitmapFactory.Options();
        bounds.inJustDecodeBounds = true;
        BitmapFactory.decodeByteArray(encodedImage, 0, encodedImage.length, bounds);

        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inSampleSize =
                sampleSizeFor(Math.max(bounds.outWidth, bounds.outHeight));
        // Recognition is on glyph shape and the HUD is monochrome green
        // regardless, so 16-bit colour halves the bitmap again for nothing.
        options.inPreferredConfig = Bitmap.Config.RGB_565;
        return BitmapFactory.decodeByteArray(
                encodedImage, 0, encodedImage.length, options);
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
    public synchronized void close() {
        if (closed) return;
        closed = true;
        if (recognizer != null) {
            recognizer.close();
            recognizer = null;
        }
    }
}
