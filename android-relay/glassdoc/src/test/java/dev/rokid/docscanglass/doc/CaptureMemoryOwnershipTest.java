package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import android.graphics.Bitmap;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Looper;
import java.io.ByteArrayOutputStream;
import java.util.List;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.GraphicsMode;
import org.robolectric.annotation.LooperMode;
import org.robolectric.shadows.ShadowLooper;
import org.robolectric.util.ReflectionHelpers;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@LooperMode(LooperMode.Mode.PAUSED)
public class CaptureMemoryOwnershipTest {
    private static byte[] jpeg() {
        Bitmap bitmap = Bitmap.createBitmap(80, 120, Bitmap.Config.RGB_565);
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        bitmap.compress(Bitmap.CompressFormat.JPEG, 80, bytes);
        bitmap.recycle();
        return bytes.toByteArray();
    }
    private static GlassesCaptureSurface surface(HudView hud, Handler handler) {
        return new GlassesCaptureSurface(RuntimeEnvironment.getApplication(), null, hud,
                handler, (generation, purpose) -> { });
    }
    @Test public void closedSurfaceRefusesReviewWithoutCreatingAnAcknowledgableGeneration() {
        HudView hud = new HudView(RuntimeEnvironment.getApplication());
        GlassesCaptureSurface surface = surface(hud, new Handler(Looper.getMainLooper()));
        surface.close();
        assertEquals(GlassesCaptureSurface.NO_VIEW_GENERATION,
                surface.showCaptureReview(jpeg(), 270, List.of("P1")));
    }
    @Test public void closeDetachesTheRecycledBitmapFromTheView() {
        HudView hud = new HudView(RuntimeEnvironment.getApplication());
        GlassesCaptureSurface surface = surface(hud, new Handler(Looper.getMainLooper()));
        surface.showCaptureReview(jpeg(), 270, List.of("P1"));
        ShadowLooper.runUiThreadTasksIncludingDelayedTasks();
        Bitmap displayed = ReflectionHelpers.getField(hud, "preview");
        assertNotNull(displayed);
        surface.close();
        assertTrue(displayed.isRecycled());
        assertNull(ReflectionHelpers.getField(hud, "preview"));
    }
    @Test public void rejectedUiPostDoesNotPromiseAReviewView() throws Exception {
        HandlerThread thread = new HandlerThread("rejected-review");
        thread.start();
        Handler handler = new Handler(thread.getLooper());
        thread.quit();
        thread.join(2000);
        HudView hud = new HudView(RuntimeEnvironment.getApplication());
        GlassesCaptureSurface surface = surface(hud, handler);
        assertEquals(GlassesCaptureSurface.NO_VIEW_GENERATION,
                surface.showCaptureReview(jpeg(), 270, List.of("P1")));
        surface.close();
    }
}
