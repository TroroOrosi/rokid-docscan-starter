package dev.rokid.docscanrelay;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.util.Base64;

import androidx.test.ext.junit.runners.AndroidJUnit4;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;

@RunWith(AndroidJUnit4.class)
public class GlassesCapturePreviewInstrumentedTest {
    @Test
    public void createsARotatedGreenPreviewWithinTheBinderBudget() throws Exception {
        Bitmap source = Bitmap.createBitmap(1600, 900, Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(source);
        canvas.drawColor(Color.WHITE);
        Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        paint.setColor(Color.BLACK);
        paint.setTextSize(130);
        canvas.drawText("日本語 OCR", 100, 300, paint);
        canvas.drawRect(100, 420, 1500, 760, paint);

        ByteArrayOutputStream jpegBytes = new ByteArrayOutputStream();
        assertTrue(source.compress(Bitmap.CompressFormat.JPEG, 80, jpegBytes));
        source.recycle();
        byte[] jpeg = jpegBytes.toByteArray();
        byte[] unchanged = jpeg.clone();

        String iconsJson = GlassesCapturePreview.iconJson(jpeg, 90);

        assertArrayEquals("the upload JPEG must remain authoritative", unchanged, jpeg);
        assertTrue(
                iconsJson.getBytes(StandardCharsets.UTF_8).length
                        <= GlassesCapturePreview.MAX_ICON_PAYLOAD_BYTES);
        JSONArray icons = new JSONArray(iconsJson);
        assertEquals(1, icons.length());
        JSONObject icon = icons.getJSONObject(0);
        assertEquals(GlassesCapturePreview.ICON_NAME, icon.getString("name"));

        byte[] png = Base64.decode(icon.getString("data"), Base64.NO_WRAP);
        Bitmap preview = BitmapFactory.decodeByteArray(png, 0, png.length);
        assertNotNull(preview);
        assertTrue(preview.getHeight() > preview.getWidth());
        assertTrue(
                Math.max(preview.getWidth(), preview.getHeight())
                        <= GlassesCapturePreview.MAX_DIMENSION);

        int[] pixels = new int[preview.getWidth() * preview.getHeight()];
        preview.getPixels(
                pixels, 0, preview.getWidth(), 0, 0, preview.getWidth(), preview.getHeight());
        boolean foundVisibleGreen = false;
        for (int color : pixels) {
            assertEquals(0, Color.red(color));
            assertEquals(0, Color.blue(color));
            foundVisibleGreen |= Color.green(color) > 0;
        }
        preview.recycle();
        assertTrue("dark document details should be visible in green", foundVisibleGreen);
    }
}
