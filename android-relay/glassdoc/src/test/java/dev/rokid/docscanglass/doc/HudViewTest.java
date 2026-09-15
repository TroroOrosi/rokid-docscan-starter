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
                Color.green(screen.getPixel(160, 100)) < 50);
        assertEquals(0, Color.red(screen.getPixel(280, 100)));
        assertEquals("display correction must not mutate the saved photograph",
                Color.rgb(70, 70, 70), photo.getPixel(120, 120));
        view.showAiming(List.of("P1 撮影", "用紙全体を中央へ", "タップで撮影"));
        view.draw(new Canvas(screen));
        for (int y = 120; y < 400; y++) for (int x = 100; x < 380; x++) {
            assertEquals("aiming instructions must leave the paper visible", Color.BLACK, screen.getPixel(x, y));
        }
        assertEquals("bottom bracket belongs inside the viewport", 255, Color.green(screen.getPixel(40, 638)));
        view.showSpreadGuide(true);
        view.draw(new Canvas(screen));
        assertEquals("right spread bracket belongs inside the viewport", 255, Color.green(screen.getPixel(478, 180)));
        photo.recycle();
        screen.recycle();
    }
}
