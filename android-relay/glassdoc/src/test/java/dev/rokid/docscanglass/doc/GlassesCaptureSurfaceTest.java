package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertTrue;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.os.Handler;
import android.os.Looper;
import java.io.ByteArrayOutputStream;
import java.util.List;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.GraphicsMode;
import org.robolectric.shadows.ShadowLooper;
import org.robolectric.util.ReflectionHelpers;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
public class GlassesCaptureSurfaceTest {
    @Test public void liveAndReviewKeepTheSameFourCornersAfterEverySupportedRotation() {
        Bitmap source = Bitmap.createBitmap(320, 240, Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(source);
        Paint quadrant = new Paint();
        int[] values = {40, 80, 120, 160};
        for (int y = 0; y < 2; y++) for (int x = 0; x < 2; x++) {
            int gray = values[y * 2 + x];
            quadrant.setColor(Color.rgb(gray, gray, gray));
            canvas.drawRect(x * 160, y * 120, (x + 1) * 160, (y + 1) * 120, quadrant);
        }
        ByteArrayOutputStream encoded = new ByteArrayOutputStream();
        source.compress(Bitmap.CompressFormat.JPEG, 100, encoded);
        byte[] jpeg = encoded.toByteArray();
        byte[] original = jpeg.clone();
        HudView hud = new HudView(RuntimeEnvironment.getApplication());
        GlassesCaptureSurface surface = new GlassesCaptureSurface(
                RuntimeEnvironment.getApplication(), null, hud,
                new Handler(Looper.getMainLooper()), (generation, purpose) -> { });
        for (int rotation : new int[]{0, 90, 180, 270}) {
            ReflectionHelpers.setField(surface, "rotationDegrees", rotation);
            surface.showLivePreview(source.copy(Bitmap.Config.ARGB_8888, false));
            ShadowLooper.runUiThreadTasksIncludingDelayedTasks();
            Bitmap live = ReflectionHelpers.getField(hud, "livePreview");
            surface.showCaptureReview(jpeg, rotation, List.of());
            ShadowLooper.runUiThreadTasksIncludingDelayedTasks();
            Bitmap review = ReflectionHelpers.getField(hud, "preview");
            assertEquals(live.getWidth(), review.getWidth());
            assertEquals(live.getHeight(), review.getHeight());
            for (int x : new int[]{8, live.getWidth() - 9}) {
                for (int y : new int[]{8, live.getHeight() - 9}) {
                    assertEquals("rotation " + rotation + " must keep each full-frame corner",
                            Color.green(live.getPixel(x, y)), Color.green(review.getPixel(x, y)), 2);
                }
            }
            assertArrayEquals("display rotation must not mutate the uploaded original", original, jpeg);
        }
        surface.close();
        source.recycle();
    }

    @Test public void leavingReviewReleasesItsBitmapBeforeAnotherCaptureOrStatus() {
        Bitmap source = Bitmap.createBitmap(4032, 3024, Bitmap.Config.RGB_565);
        ByteArrayOutputStream encoded = new ByteArrayOutputStream();
        source.compress(Bitmap.CompressFormat.JPEG, 80, encoded);
        source.recycle();
        HudView hud = new HudView(RuntimeEnvironment.getApplication());
        GlassesCaptureSurface surface = new GlassesCaptureSurface(
                RuntimeEnvironment.getApplication(), null, hud,
                new Handler(Looper.getMainLooper()), (generation, purpose) -> { });
        for (boolean aiming : new boolean[]{true, false}) {
            surface.showCaptureReview(encoded.toByteArray(), 270, List.of("P1"));
            ShadowLooper.runUiThreadTasksIncludingDelayedTasks();
            Bitmap held = ReflectionHelpers.getField(hud, "preview");
            assertFalse(held.isRecycled());
            assertTrue("a full-frame HUD preview must stay within twice the 640px display edge",
                    Math.max(held.getWidth(), held.getHeight()) <= 1280);
            if (aiming) surface.showCaptureAiming(1, true, true);
            else surface.showHud(List.of("保存中"));
            ShadowLooper.runUiThreadTasksIncludingDelayedTasks();
            assertTrue("hidden review pixels must not overlap the next camera allocation",
                    held.isRecycled());
        }
        surface.close();
    }
}
