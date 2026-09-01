package dev.rokid.docscanrelay;

import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Typeface;

import androidx.test.ext.junit.runners.AndroidJUnit4;

import org.junit.Test;
import org.junit.runner.RunWith;

import java.io.ByteArrayOutputStream;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

@RunWith(AndroidJUnit4.class)
public class JapaneseOcrInstrumentedTest {
    @Test
    public void bundledModelRecognizesSharpJapaneseTextOnThePhone() throws Exception {
        Bitmap bitmap = Bitmap.createBitmap(1600, 900, Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(bitmap);
        canvas.drawColor(Color.WHITE);

        Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        paint.setColor(Color.BLACK);
        paint.setTextSize(170);
        paint.setTypeface(Typeface.create("sans-serif", Typeface.BOLD));
        canvas.drawText("日本語 OCR テスト", 80, 300, paint);
        canvas.drawText("東京都 千代田区", 80, 620, paint);

        ByteArrayOutputStream encoded = new ByteArrayOutputStream();
        assertTrue(bitmap.compress(Bitmap.CompressFormat.PNG, 100, encoded));
        bitmap.recycle();

        CountDownLatch completed = new CountDownLatch(1);
        AtomicReference<String> recognized = new AtomicReference<>();
        AtomicReference<OcrQuality> quality = new AtomicReference<>();
        AtomicReference<Throwable> failure = new AtomicReference<>();
        try (JapaneseOcr ocr = new JapaneseOcr()) {
            ocr.recognize(encoded.toByteArray(), 0, new JapaneseOcr.Callback() {
                @Override
                public void onResult(String text, OcrQuality measured) {
                    recognized.set(text);
                    quality.set(measured);
                    completed.countDown();
                }

                @Override
                public void onError(Throwable error) {
                    failure.set(error);
                    completed.countDown();
                }
            });

            assertTrue("ML Kit callback timed out", completed.await(20, TimeUnit.SECONDS));
            assertNull("ML Kit returned an error", failure.get());
            assertTrue(
                    "The bundled Japanese model returned no Japanese text for a sharp image",
                    recognized.get() != null
                            && recognized.get().matches(
                            "(?s).*[\u3040-\u30ff\u3400-\u9fff].*"));
            assertTrue(
                    "The bundled recogniser reported no character count",
                    quality.get() != null && quality.get().characterCount() > 0);
        }
    }
}
