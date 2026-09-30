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
    @Test public void reviewShowsTheWholePhotoWithoutAnOverviewCoveringIt() {
        Bitmap photo = Bitmap.createBitmap(800, 600, Bitmap.Config.ARGB_8888);
        photo.eraseColor(Color.rgb(10, 10, 10));
        Canvas source = new Canvas(photo);
        android.graphics.Paint paper = new android.graphics.Paint();
        paper.setColor(Color.rgb(90, 90, 90));
        source.drawRect(300, 150, 500, 450, paper);
        source.drawRect(0, 0, 60, 60, paper);
        HudView view = new HudView(RuntimeEnvironment.getApplication());
        view.layout(0, 0, 480, 640);
        view.showReview(photo, List.of("P1 撮影確認", "3秒以内のタップで撮り直し", "無操作で保存・次へ"));
        Bitmap screen = Bitmap.createBitmap(480, 640, Bitmap.Config.ARGB_8888);
        view.draw(new Canvas(screen));
        assertTrue("the paper must be visible", Color.green(screen.getPixel(240, 220)) > 180);
        assertTrue("the original top-left marker must be visible without a second image",
                Color.green(screen.getPixel(12, 100)) > 180);
        assertEquals("no inset may cover the original lower-right pixels",
                Color.BLACK, screen.getPixel(322, 410));
        assertEquals(Color.rgb(90, 90, 90), photo.getPixel(400, 300));
        photo.recycle();
        screen.recycle();
    }

    @Test public void darkReviewUsesTheAvailableHeightAndReadableGreenWithoutChangingThePhoto() {
        Bitmap photo = Bitmap.createBitmap(240, 480, Bitmap.Config.ARGB_8888);
        photo.eraseColor(Color.rgb(70, 70, 70));
        for (int y = 0; y < 480; y++) for (int x = 30; x < 70; x++) {
            photo.setPixel(x, y, Color.rgb(15, 15, 15));
        }
        HudView view = new HudView(RuntimeEnvironment.getApplication());
        view.layout(0, 0, 480, 640);
        view.showReview(photo, List.of("P1 撮影確認", "3秒以内のタップで撮り直し", "無操作で保存・次へ"));
        Bitmap screen = Bitmap.createBitmap(480, 640, Bitmap.Config.ARGB_8888);
        view.draw(new Canvas(screen));
        assertTrue("portrait preview must extend beyond the old 62% band",
                Color.green(screen.getPixel(280, 480)) > 180);
        assertTrue("dark paper should be bright enough to inspect",
                Color.green(screen.getPixel(280, 100)) > 180);
        assertTrue("ink should remain darker than paper",
                Color.green(screen.getPixel(150, 100)) < 50);
        assertEquals(0, Color.red(screen.getPixel(280, 100)));
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
        assertEquals("source pixels and frame share the same transform", 80, Color.green(screen.getPixel(240, 300)));
        assertTrue("the image boundary is visible", Color.green(screen.getPixel(0, 140)) > 200);
        view.capturePreview(false);
        view.showLines(List.of());
        view.draw(new Canvas(screen));
        assertEquals(Color.BLACK, screen.getPixel(240, 300));
        assertTrue(camera.isRecycled());
        screen.recycle();
    }
}
