package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import android.graphics.Bitmap;
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
