package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RectF;
import java.util.Arrays;
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
    @Test public void waitingStatusLeavesTheCentreClearWithoutEnlargingShortMessages() {
        for (int[] size : new int[][]{{480, 640}, {640, 480}}) {
            HudView view = new HudView(RuntimeEnvironment.getApplication());
            view.layout(0, 0, size[0], size[1]);
            view.showLines(List.of("解析中", "答案を待っています", ""));
            Bitmap screen = Bitmap.createBitmap(size[0], size[1], Bitmap.Config.ARGB_8888);
            TextCanvas canvas = new TextCanvas(screen);
            view.draw(canvas);
            assertEquals("status content must remain visible", "解析中答案を待っています", canvas.text.toString());
            assertStatusOnly(screen);
            assertTrue("short status must not be enlarged across the display", canvas.largestTextSize <= 20f);
            screen.recycle();
        }
    }

    @Test public void compactStatusKeepsEveryChoiceAndTheInstructionReadable() {
        List<String> choices = List.of("　 通常の読取", "▶ 合同英語（読解＋音声）", "　 リスニング",
                "　 中断した読取", "　 前回の答案", "スワイプで選択・タップで開始");
        assertReadableStatus(choices);
    }

    @Test public void compactFailureWrapsTheCompleteReasonAndRecoveryAction() {
        assertReadableStatus(List.of("開始・再開できません",
                "接続先と保存記録を確認してください。撮影した問題用紙と原音は保存されています。",
                "ダブルタップで戻る"));
    }

    private static void assertReadableStatus(List<String> lines) {
        for (int[] size : new int[][]{{480, 640}, {640, 480}}) {
            HudView view = new HudView(RuntimeEnvironment.getApplication());
            view.layout(0, 0, size[0], size[1]);
            view.showLines(lines);
            Bitmap screen = Bitmap.createBitmap(size[0], size[1], Bitmap.Config.ARGB_8888);
            TextCanvas canvas = new TextCanvas(screen);
            view.draw(canvas);
            assertEquals("no choice, failure detail or action may be omitted", String.join("", lines), canvas.text.toString());
            if (size[0] == 480) {
                assertTrue("ordinary choices and wrapped failure details must stay readable", canvas.smallestTextSize >= 18f);
            }
            assertStatusOnly(screen);
            screen.recycle();
        }
    }

    @Test public void emptyAndSmallStatusKeepDrawingWithinTheDisplay() {
        HudView view = new HudView(RuntimeEnvironment.getApplication());
        view.layout(0, 0, 96, 64);
        List<List<String>> emptyInputs = Arrays.asList(null, List.of(), Arrays.asList(null, "", null));
        for (List<String> input : emptyInputs) {
            view.showLines(input);
            Bitmap screen = Bitmap.createBitmap(96, 64, Bitmap.Config.ARGB_8888);
            TextCanvas canvas = new TextCanvas(screen);
            view.draw(canvas);
            assertEquals("empty or null status must not leave a stale text draw", "", canvas.text.toString());
            for (int y = 0; y < 64; y++) for (int x = 0; x < 96; x++) {
                assertEquals(Color.BLACK, screen.getPixel(x, y));
            }
            screen.recycle();
        }
        for (int[] size : new int[][]{{96, 64}, {64, 96}}) {
            view.layout(0, 0, size[0], size[1]);
            view.showLines(Arrays.asList(null, "解析中", ""));
            Bitmap screen = Bitmap.createBitmap(size[0], size[1], Bitmap.Config.ARGB_8888);
            TextCanvas canvas = new TextCanvas(screen);
            view.draw(canvas);
            assertEquals("small views may shrink text but must keep the complete status", "解析中", canvas.text.toString());
            assertStatusOnly(screen);
            screen.recycle();
        }
    }

    private static void assertStatusOnly(Bitmap screen) {
        int visible = 0;
        for (int y = 0; y < screen.getHeight(); y++) for (int x = 0; x < screen.getWidth(); x++) {
            if (screen.getPixel(x, y) != Color.BLACK) {
                visible++;
                assertTrue("status must stay in a small lower-left area, leaving the page ahead clear",
                        x <= screen.getWidth() * .65f && y >= screen.getHeight() * .65f);
            }
        }
        assertTrue("the compact status must actually be drawn", visible > 0);
    }

    private static final class TextCanvas extends Canvas {
        final StringBuilder text = new StringBuilder();
        float smallestTextSize = Float.MAX_VALUE;
        float largestTextSize;

        TextCanvas(Bitmap bitmap) { super(bitmap); }

        private void record(CharSequence drawn, float x, float y, Paint paint) {
            text.append(drawn);
            smallestTextSize = Math.min(smallestTextSize, paint.getTextSize());
            largestTextSize = Math.max(largestTextSize, paint.getTextSize());
            String value = drawn.toString();
            Rect ink = new Rect();
            paint.getTextBounds(value, 0, value.length(), ink);
            if (!ink.isEmpty()) {
                Rect clip = new Rect();
                assertTrue("text ink must have a visible canvas clip", getClipBounds(clip));
                RectF positionedInk = new RectF(ink);
                positionedInk.offset(x, y);
                assertTrue("text ink must fit its clip: view=" + getWidth() + "x" + getHeight()
                                + ", size=" + paint.getTextSize() + ", ink=" + positionedInk
                                + ", clip=" + clip + ", origin=" + x + "," + y + ", text=" + value,
                        new RectF(clip).contains(positionedInk));
            }
        }

        @Override public void drawText(String text, float x, float y, Paint paint) {
            record(text, x, y, paint);
            super.drawText(text, x, y, paint);
        }

        @Override public void drawText(CharSequence text, int start, int end, float x, float y, Paint paint) {
            record(text.subSequence(start, end), x, y, paint);
            super.drawText(text, start, end, x, y, paint);
        }

        @Override public void drawTextRun(char[] text, int index, int count, int contextIndex, int contextCount,
                                          float x, float y, boolean isRtl, Paint paint) {
            record(new String(text, index, count), x, y, paint);
            super.drawTextRun(text, index, count, contextIndex, contextCount, x, y, isRtl, paint);
        }

        @Override public void drawTextRun(CharSequence text, int start, int end, int contextStart, int contextEnd,
                                          float x, float y, boolean isRtl, Paint paint) {
            record(text.subSequence(start, end), x, y, paint);
            super.drawTextRun(text, start, end, contextStart, contextEnd, x, y, isRtl, paint);
        }
    }

    @Test public void ordinaryCaptureStatusDoesNotCoverTheExistingLiveImage() {
        HudView view = new HudView(RuntimeEnvironment.getApplication());
        view.layout(0, 0, 480, 640);
        Bitmap camera = Bitmap.createBitmap(320, 240, Bitmap.Config.ARGB_8888);
        camera.eraseColor(Color.rgb(0, 80, 0));
        view.showLivePreview(camera);
        view.capturePreview(true);
        view.showAiming(List.of());
        Bitmap before = Bitmap.createBitmap(480, 640, Bitmap.Config.ARGB_8888);
        view.draw(new Canvas(before));
        view.showLines(List.of("撮影中", "", ""));
        Bitmap after = Bitmap.createBitmap(480, 640, Bitmap.Config.ARGB_8888);
        view.draw(new Canvas(after));
        for (int y = 440; y < 640; y++) for (int x = 320; x < 480; x++) {
            assertEquals("ordinary status must neither move nor obscure the live image and its frame",
                    before.getPixel(x, y), after.getPixel(x, y));
        }
        view.capturePreview(false);
        before.recycle();
        after.recycle();
    }

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

    // AGENT_APPROVED=1: diagnostic notice stays outside the photo and never replaces review/answers.
    @Test public void nativeDiagnosticNoticeIsSmallCaptureOnlyAndRechecksItsOwnerAtDraw() {
        HudView view = new HudView(RuntimeEnvironment.getApplication()); view.layout(0, 0, 480, 640);
        Bitmap screen = Bitmap.createBitmap(480, 640, Bitmap.Config.ARGB_8888);
        Bitmap photo = Bitmap.createBitmap(320, 240, Bitmap.Config.ARGB_8888); photo.eraseColor(Color.GREEN);
        var current = new java.util.concurrent.atomic.AtomicBoolean(true);
        view.capturePreview(true); view.showAiming(List.of());
        view.showInspectionNotice("P3 要確認", current::get);
        TextCanvas aiming = new TextCanvas(screen); view.draw(aiming);
        assertEquals("P3 要確認", aiming.text.toString()); assertTrue(aiming.largestTextSize <= 16f);
        view.showReview(photo, List.of());
        TextCanvas review = new TextCanvas(screen); view.draw(review); assertEquals("", review.text.toString());
        view.showAiming(List.of()); current.set(false);
        TextCanvas stale = new TextCanvas(screen); view.draw(stale); assertEquals("", stale.text.toString());
        current.set(true); view.showInspectionNotice("P3 未確認", current::get);
        view.capturePreview(false); view.showLines(List.of("答案"));
        TextCanvas answer = new TextCanvas(screen); view.draw(answer); assertEquals("答案", answer.text.toString());
        photo.recycle(); screen.recycle();
    }

    @Test public void nativeDiagnosticIsVisibleDuringTheRealFutureWaitAfterReviewCommit() {
        HudView view = new HudView(RuntimeEnvironment.getApplication()); view.layout(0,0,480,640);
        Bitmap original = Bitmap.createBitmap(320,240,Bitmap.Config.ARGB_8888);
        Bitmap screen = Bitmap.createBitmap(480,640,Bitmap.Config.ARGB_8888);
        view.capturePreview(true); view.showReview(original,List.of());
        // commitLocalPhoto -> publish(READING) -> showHud. futureWatching continues the existing preview.
        view.showLines(List.of("1枚保存済み")); view.showInspectionNotice("P1 要確認",()->true);
        TextCanvas waiting = new TextCanvas(screen); view.draw(waiting);
        assertTrue("feedback must draw in the normal future-observation branch",waiting.text.toString().contains("P1 要確認"));
        view.capturePreview(false);
        TextCanvas stopped = new TextCanvas(screen); view.draw(stopped);
        assertTrue("stopping capture must hide the notice",!stopped.text.toString().contains("P1 要確認"));
        original.recycle();screen.recycle();
    }
}
