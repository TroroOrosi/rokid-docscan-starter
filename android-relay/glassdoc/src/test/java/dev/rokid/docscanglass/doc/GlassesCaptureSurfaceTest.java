package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertTrue;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.BitmapFactory;
import android.graphics.BitmapRegionDecoder;
import android.graphics.Rect;
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
import org.robolectric.annotation.Implements;
import org.robolectric.annotation.Implementation;
import org.robolectric.shadow.api.Shadow;
import org.robolectric.shadows.ShadowLooper;
import org.robolectric.util.ReflectionHelpers;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
public class GlassesCaptureSurfaceTest {
    @Test @Config(shadows = RegionDecoder.class)
    public void nativeQualitySamplesExactSmallNativeRegionsWithoutChangingTheOriginal() {
        Bitmap bitmap = Bitmap.createBitmap(576, 384, Bitmap.Config.ARGB_8888);
        for (int y = 0; y < bitmap.getHeight(); y++) for (int x = 0; x < bitmap.getWidth(); x++) {
            int gray = 40 + (x * 3 + y * 7) % 160;
            bitmap.setPixel(x, y, Color.rgb(gray, gray, gray));
        }
        ByteArrayOutputStream encoded = new ByteArrayOutputStream();
        bitmap.compress(Bitmap.CompressFormat.JPEG, 100, encoded); bitmap.recycle();
        byte[] jpeg = encoded.toByteArray(), original = jpeg.clone();
        var source = dev.rokid.docscanrelay.CaptureProvenance.nativeStill(jpeg, 576, 384, 10L, 10L, 1L,
                10_000_000L, 100, 0, 2);
        GlassesCaptureSurface surface = new GlassesCaptureSurface(RuntimeEnvironment.getApplication(), null,
                new HudView(RuntimeEnvironment.getApplication()), new Handler(Looper.getMainLooper()), (g, p) -> { });
        var sample = surface.sampleNativeImage(jpeg, source);
        org.junit.Assert.assertNotNull(sample);
        assertEquals(576, sample.width); assertEquals(384, sample.height);
        Bitmap decoded = android.graphics.BitmapFactory.decodeByteArray(jpeg, 0, jpeg.length);
        byte[] pixels = ReflectionHelpers.getField(sample, "pixels");
        for (int region = 0; region < 9; region++) {
            int left = (2 * (region % 3) + 1) * 576 / 6 - 32;
            int top = (2 * (region / 3) + 1) * 384 / 6 - 32;
            int c = decoded.getPixel(left + 19, top + 23);
            int expected = (77 * Color.red(c) + 150 * Color.green(c) + 29 * Color.blue(c)) >> 8;
            assertEquals(expected, pixels[region * 4096 + 23 * 64 + 19] & 255);
        }
        decoded.recycle(); assertArrayEquals(original, jpeg);
        jpeg[20] ^= 1; org.junit.Assert.assertNull(surface.sampleNativeImage(jpeg, source));
        surface.close();
    }

    /** Robolectric 4.14's built-in region shadow returns a blank bitmap; only this decode boundary is replaced. */
    @Implements(BitmapRegionDecoder.class)
    public static class RegionDecoder {
        Bitmap original;
        @Implementation protected static BitmapRegionDecoder newInstance(byte[] bytes, int offset, int length, boolean shareable) {
            BitmapRegionDecoder result = Shadow.newInstanceOf(BitmapRegionDecoder.class);
            ((RegionDecoder)Shadow.extract(result)).original = BitmapFactory.decodeByteArray(bytes, offset, length);
            return result;
        }
        @Implementation protected int getWidth() { return original.getWidth(); }
        @Implementation protected int getHeight() { return original.getHeight(); }
        @Implementation protected Bitmap decodeRegion(Rect rect, BitmapFactory.Options options) {
            assertEquals(1, options.inSampleSize); assertEquals(64, rect.width()); assertEquals(64, rect.height());
            return Bitmap.createBitmap(original, rect.left, rect.top, rect.width(), rect.height());
        }
        @Implementation protected void recycle() { original.recycle(); }
    }

    // AGENT_APPROVED=1: explicit paper proposal stays within the existing small HUD preview.
    @Test public void paperCornersRotateWithTheWholeLiveImageAndDisappearOnUncertainty() {
        HudView hud = new HudView(RuntimeEnvironment.getApplication()); hud.layout(0, 0, 1000, 800);
        GlassesCaptureSurface surface = new GlassesCaptureSurface(RuntimeEnvironment.getApplication(), null, hud,
                new Handler(Looper.getMainLooper()), (generation, purpose) -> { });
        surface.showCaptureAiming(1, true, true);
        ReflectionHelpers.setField(surface, "rotationDegrees", 90);
        surface.showLivePreview(Bitmap.createBitmap(320, 240, Bitmap.Config.ARGB_8888),
                new PaperGeometry.Box(8, 6, 48, 36, 64, 48));
        ShadowLooper.runUiThreadTasksIncludingDelayedTasks();
        Bitmap live = ReflectionHelpers.getField(hud, "livePreview");
        assertEquals(240, live.getWidth()); assertEquals(320, live.getHeight());
        PaperGeometry.Box proposal = ReflectionHelpers.getField(hud, "paperProposal");
        assertArrayEquals(new int[]{12, 8, 42, 48}, proposal.edges());
        Bitmap screen = Bitmap.createBitmap(1000, 800, Bitmap.Config.ARGB_8888); hud.draw(new Canvas(screen));
        // Fit-centred 240x320 image: [752,552,932,792]. Rotated proposal: [797,582,909.5,732].
        assertTrue(Color.green(screen.getPixel(797, 582)) > 180);
        assertEquals("a corner guide must leave its side centre clear", 0, Color.green(screen.getPixel(850, 582)));
        assertEquals("the main field of view stays empty", Color.BLACK, screen.getPixel(500, 400));
        surface.showLivePreview(Bitmap.createBitmap(320, 240, Bitmap.Config.ARGB_8888), null);
        ShadowLooper.runUiThreadTasksIncludingDelayedTasks();
        org.junit.Assert.assertNull(ReflectionHelpers.getField(hud, "paperProposal"));
        surface.close(); screen.recycle();
    }

    @Test public void anUnresolvedSceneNoticeKeepsTheOriginalAndItsExistingVisibilityAcknowledgement() {
        Bitmap source = Bitmap.createBitmap(80, 120, Bitmap.Config.RGB_565);
        ByteArrayOutputStream encoded = new ByteArrayOutputStream();
        source.compress(Bitmap.CompressFormat.JPEG, 80, encoded); source.recycle();
        HudView hud = new HudView(RuntimeEnvironment.getApplication());
        GlassesCaptureSurface surface = new GlassesCaptureSurface(RuntimeEnvironment.getApplication(), null, hud,
                new Handler(Looper.getMainLooper()), (generation, purpose) -> { });
        long generation = surface.showCaptureReview(encoded.toByteArray(), 270, List.of());
        ShadowLooper.runUiThreadTasksIncludingDelayedTasks();
        Bitmap displayed = ReflectionHelpers.getField(hud, "preview");
        Object frame = ReflectionHelpers.getField(hud, "visibleFrame");
        ReflectionHelpers.setField(surface, "visibleReview", generation);
        surface.showCaptureReviewNotice("タップで撮り直し");
        ShadowLooper.runUiThreadTasksIncludingDelayedTasks();
        org.junit.Assert.assertSame(displayed, ReflectionHelpers.getField(hud, "preview"));
        org.junit.Assert.assertSame(frame, ReflectionHelpers.getField(hud, "visibleFrame"));
        assertTrue(surface.isCaptureReviewVisible(generation));
        assertEquals(List.of("タップで撮り直し"), ReflectionHelpers.getField(hud, "lines"));
        surface.close();
    }
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
