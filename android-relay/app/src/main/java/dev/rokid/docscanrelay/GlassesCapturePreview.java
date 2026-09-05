package dev.rokid.docscanrelay;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Matrix;
import android.util.Base64;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;

/**
 * Builds a small green-channel preview for the monochrome glasses display.
 *
 * <p>The CXR-L icon transport is another Binder call, so the full camera JPEG
 * must never be embedded in the CustomView payload. Dark details are inverted
 * to bright green while the light paper background becomes black/off.</p>
 */
final class GlassesCapturePreview {
    static final String ICON_NAME = "docscan_capture_preview";
    static final int MAX_DIMENSION = 288;
    static final int MAX_ICON_PAYLOAD_BYTES = 512 * 1024;

    private GlassesCapturePreview() {
    }

    static String iconJson(byte[] jpeg, int rotationDegrees) {
        Bitmap preview = decodeAndRotate(jpeg, rotationDegrees);
        if (preview == null) {
            throw new IllegalArgumentException("capture preview JPEG could not be decoded");
        }
        Bitmap green = null;
        try {
            int width = preview.getWidth();
            int height = preview.getHeight();
            int[] pixels = new int[width * height];
            preview.getPixels(pixels, 0, width, 0, 0, width, height);
            for (int i = 0; i < pixels.length; i++) {
                int color = pixels[i];
                int luminance = (
                        299 * Color.red(color)
                                + 587 * Color.green(color)
                                + 114 * Color.blue(color)
                ) / 1000;
                int inverted = 255 - luminance;
                int visibleGreen = inverted <= 24
                        ? 0
                        : Math.min(255, (inverted - 24) * 2);
                pixels[i] = Color.rgb(0, visibleGreen, 0);
            }
            green = Bitmap.createBitmap(pixels, width, height, Bitmap.Config.ARGB_8888);
            ByteArrayOutputStream encoded = new ByteArrayOutputStream();
            if (!green.compress(Bitmap.CompressFormat.PNG, 100, encoded)) {
                throw new IllegalStateException("capture preview PNG encoding failed");
            }
            String base64 = Base64.encodeToString(encoded.toByteArray(), Base64.NO_WRAP);
            String payload = "[{\"name\":\"" + ICON_NAME + "\",\"data\":\""
                    + base64 + "\"}]";
            int payloadBytes = payload.getBytes(StandardCharsets.UTF_8).length;
            if (payloadBytes > MAX_ICON_PAYLOAD_BYTES) {
                throw new IllegalStateException(
                        "capture preview icon exceeds safe Binder budget: "
                                + payloadBytes + " bytes");
            }
            return payload;
        } finally {
            if (green != null) {
                green.recycle();
            }
            preview.recycle();
        }
    }

    private static Bitmap decodeAndRotate(byte[] jpeg, int rotationDegrees) {
        if (jpeg == null || jpeg.length == 0) {
            return null;
        }
        int rotation = ((rotationDegrees % 360) + 360) % 360;
        if (rotation % 90 != 0) {
            throw new IllegalArgumentException("rotation must be a multiple of 90");
        }

        BitmapFactory.Options bounds = new BitmapFactory.Options();
        bounds.inJustDecodeBounds = true;
        BitmapFactory.decodeByteArray(jpeg, 0, jpeg.length, bounds);
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) {
            return null;
        }

        int sample = 1;
        while (Math.max(bounds.outWidth, bounds.outHeight) / (sample * 2)
                >= MAX_DIMENSION) {
            sample *= 2;
        }
        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inSampleSize = sample;
        Bitmap decoded = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.length, options);
        if (decoded == null) {
            return null;
        }

        Bitmap rotated = decoded;
        if (rotation != 0) {
            Matrix matrix = new Matrix();
            matrix.postRotate(rotation);
            rotated = Bitmap.createBitmap(
                    decoded, 0, 0, decoded.getWidth(), decoded.getHeight(), matrix, true);
            if (rotated != decoded) {
                decoded.recycle();
            }
        }

        int longest = Math.max(rotated.getWidth(), rotated.getHeight());
        if (longest <= MAX_DIMENSION) {
            return rotated;
        }
        float scale = MAX_DIMENSION / (float) longest;
        Bitmap scaled = Bitmap.createScaledBitmap(
                rotated,
                Math.max(1, Math.round(rotated.getWidth() * scale)),
                Math.max(1, Math.round(rotated.getHeight() * scale)),
                true);
        if (scaled != rotated) {
            rotated.recycle();
        }
        return scaled;
    }
}
