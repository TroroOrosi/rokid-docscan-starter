package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import java.util.List;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.GraphicsMode;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
public class HudViewTest {
    @Test public void reviewStaysInTheCornerAndLeavesThePageInFrontOfTheOperatorClear() {
        Bitmap photo = Bitmap.createBitmap(240, 480, Bitmap.Config.ARGB_8888);
        photo.eraseColor(Color.rgb(90, 90, 90));
        HudView view = new HudView(RuntimeEnvironment.getApplication());
        view.layout(0, 0, 480, 640);
        view.showReview(photo, List.of());
        Bitmap screen = Bitmap.createBitmap(480, 640, Bitmap.Config.ARGB_8888);
        view.draw(new Canvas(screen));
        assertTrue("the complete photo fits in the lower-right corner",
                Color.green(screen.getPixel(400, 630)) > 80);
        assertEquals("the operator's central field of view stays clear",
                Color.BLACK, screen.getPixel(240, 320));
        assertCornerOnly(screen);
        view.showRecording(true);
        Bitmap recordingScreen = Bitmap.createBitmap(480, 640, Bitmap.Config.ARGB_8888);
        view.draw(new Canvas(recordingScreen));
        assertTrue("recording must not add text over the three-second photo review",
                screen.sameAs(recordingScreen));
        assertEquals(Color.rgb(90, 90, 90), photo.getPixel(120, 470));
        photo.recycle();
        screen.recycle();
        recordingScreen.recycle();
    }

    @Test public void compactReviewKeepsAllFourOriginalCornersWithoutCropping() {
        Bitmap photo = Bitmap.createBitmap(800, 600, Bitmap.Config.ARGB_8888);
        photo.eraseColor(Color.rgb(10, 10, 10));
        Canvas source = new Canvas(photo);
        android.graphics.Paint paper = new android.graphics.Paint();
        paper.setColor(Color.rgb(90, 90, 90));
        source.drawRect(0, 0, 60, 60, paper);
        source.drawRect(740, 0, 800, 60, paper);
        source.drawRect(0, 540, 60, 600, paper);
        source.drawRect(740, 540, 800, 600, paper);
        HudView view = new HudView(RuntimeEnvironment.getApplication());
        view.layout(0, 0, 480, 640);
        view.showReview(photo, List.of());
        Bitmap screen = Bitmap.createBitmap(480, 640, Bitmap.Config.ARGB_8888);
        view.draw(new Canvas(screen));
        for (int x : new int[]{333, 467}) for (int y : new int[]{487, 585}) {
            assertTrue("every original corner must remain visible",
                    Color.green(screen.getPixel(x, y)) > 180);
        }
        assertEquals("no second image covers the page", Color.BLACK, screen.getPixel(240, 320));
        assertCornerOnly(screen);
        assertEquals(Color.rgb(90, 90, 90), photo.getPixel(30, 30));
        photo.recycle();
        screen.recycle();
    }

    @Test public void darkCompactReviewKeepsTheDisplayCorrectionOffTheOriginalPhoto() {
        Bitmap photo = Bitmap.createBitmap(240, 480, Bitmap.Config.ARGB_8888);
        photo.eraseColor(Color.rgb(70, 70, 70));
        for (int y = 0; y < 480; y++) for (int x = 30; x < 70; x++) {
            photo.setPixel(x, y, Color.rgb(15, 15, 15));
        }
        HudView view = new HudView(RuntimeEnvironment.getApplication());
        view.layout(0, 0, 480, 640);
        view.showReview(photo, List.of());
        Bitmap screen = Bitmap.createBitmap(480, 640, Bitmap.Config.ARGB_8888);
        view.draw(new Canvas(screen));
        assertTrue("dark paper should be bright enough to inspect",
                Color.green(screen.getPixel(400, 480)) > 180);
        assertTrue("ink should remain darker than paper",
                Color.green(screen.getPixel(370, 480)) < 50);
        assertEquals(0, Color.red(screen.getPixel(400, 480)));
        assertCornerOnly(screen);
        assertEquals("display correction must not mutate the saved photograph",
                Color.rgb(70, 70, 70), photo.getPixel(120, 120));
        photo.recycle();
        screen.recycle();
    }

    @Test public void aimingFramesTheActualCameraImageAndRemovesItOutsideCapture() {
        HudView view = new HudView(RuntimeEnvironment.getApplication());
        view.layout(0, 0, 480, 640);
        Bitmap screen = Bitmap.createBitmap(480, 640, Bitmap.Config.ARGB_8888);
        Bitmap camera = Bitmap.createBitmap(320, 240, Bitmap.Config.ARGB_8888);
        camera.eraseColor(Color.rgb(0, 80, 0));
        view.showLivePreview(camera);
        view.capturePreview(true);
        view.showAiming(List.of());
        view.draw(new Canvas(screen));
        assertEquals("source pixels and frame share the same transform", 80, Color.green(screen.getPixel(400, 536)));
        assertTrue("the compact image boundary is visible", Color.green(screen.getPixel(328, 510)) > 200);
        assertEquals("the live image must not fill the operator's view", Color.BLACK, screen.getPixel(240, 300));
        assertCornerOnly(screen);
        view.capturePreview(false);
        view.showLines(List.of());
        view.draw(new Canvas(screen));
        assertEquals(Color.BLACK, screen.getPixel(240, 300));
        assertTrue(camera.isRecycled());
        screen.recycle();
    }

    @Test public void endingCaptureKeepsThePhotoStationaryAndTheNoticeOutsideIt() {
        HudView view = new HudView(RuntimeEnvironment.getApplication());
        view.layout(0, 0, 480, 640);
        Bitmap photo = Bitmap.createBitmap(240, 480, Bitmap.Config.ARGB_8888);
        photo.eraseColor(Color.rgb(90, 90, 90));
        view.showReview(photo, List.of());
        Bitmap before = Bitmap.createBitmap(480, 640, Bitmap.Config.ARGB_8888);
        view.draw(new Canvas(before));
        view.showReviewNotice("終了待ち");
        Bitmap after = Bitmap.createBitmap(480, 640, Bitmap.Config.ARGB_8888);
        view.draw(new Canvas(after));
        for (int y = 440; y < 640; y++) for (int x = 0; x < 480; x++) {
            assertEquals("a notice must neither move nor cover the actual photograph",
                    before.getPixel(x, y), after.getPixel(x, y));
        }
        assertCornerOnly(after);
        photo.recycle();
        before.recycle();
        after.recycle();
    }

    private static void assertCornerOnly(Bitmap screen) {
        for (int y = 0; y < screen.getHeight(); y++) for (int x = 0; x < screen.getWidth(); x++) {
            if (screen.getPixel(x, y) != Color.BLACK) {
                assertTrue("capture pixels and status must stay out of the central field of view",
                        x >= screen.getWidth() * .65f && y >= screen.getHeight() * .60f);
            }
        }
    }
}
