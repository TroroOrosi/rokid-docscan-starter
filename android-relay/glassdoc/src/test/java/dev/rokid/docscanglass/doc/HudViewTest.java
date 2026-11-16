package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertArrayEquals;
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

    /** Margins move the chooser and the review image; neither may become smaller than on the whole panel. */
    @Test public void marginsKeepTheChoicesReadableAndTheReviewImageItsSize() throws Exception {
        HudView view = new HudView(RuntimeEnvironment.getApplication());
        android.widget.FrameLayout panel = new android.widget.FrameLayout(RuntimeEnvironment.getApplication());
        panel.setPadding(0, 80, 0, 125);
        panel.addView(view);
        panel.measure(android.view.View.MeasureSpec.makeMeasureSpec(480, android.view.View.MeasureSpec.EXACTLY),
                android.view.View.MeasureSpec.makeMeasureSpec(640, android.view.View.MeasureSpec.EXACTLY));
        panel.layout(0, 0, 480, 640);
        assertEquals(435, view.getHeight());
        List<String> choices = List.of("　 通常の読取", "▶ 合同英語（読解＋音声）", "　 リスニング",
                "　 中断した読取", "　 前回の答案", "スワイプで選択・タップで開始");
        view.showLines(choices);
        Bitmap screen = Bitmap.createBitmap(480, 435, Bitmap.Config.ARGB_8888);
        TextCanvas canvas = new TextCanvas(screen);
        view.draw(canvas);
        assertEquals(String.join("", choices), canvas.text.toString());
        assertTrue("the choices must stay as readable as on the whole panel", canvas.smallestTextSize >= 18f);
        screen.recycle();

        java.lang.reflect.Method area = HudView.class.getDeclaredMethod("captureArea");
        area.setAccessible(true);
        android.graphics.RectF corner = (android.graphics.RectF) area.invoke(view);
        assertEquals("30% of the 640 px panel", 192f, corner.height(), .01f);
        assertEquals(435f - 8f, corner.bottom, .01f);
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

    /**
     * The camera sees about 77 by 94 degrees, several times the page the wearer looks at ("still too wide",
     * 2026-11-12). The corner keeps its size and shows the paper; the camera's limit is a line.
     */
    @Test public void theLiveCornerShowsThePaperAndTheCameraLimitOnlyWhereThePaperReachesIt() {
        HudView view = new HudView(RuntimeEnvironment.getApplication());
        view.layout(0, 0, 480, 640);
        view.capturePreview(true);
        view.showAiming(List.of());
        view.showLivePreview(liveFrame(40, 200));
        Bitmap screen = Bitmap.createBitmap(480, 640, Bitmap.Config.ARGB_8888);
        view.draw(new Canvas(screen));
        // A 160x120 sheet of the 240x320 frame, with its margin, across the 144 px corner [328,440,472,632].
        for (int x : new int[]{340, 400, 460}) {
            assertEquals("the sheet spans the corner", 200, Color.green(screen.getPixel(x, 536)));
        }
        for (int y = 440; y < 632; y++) {
            assertTrue("no camera limit where the sheet is inside the frame",
                    Color.red(screen.getPixel(329, y)) == 0 && Color.red(screen.getPixel(470, y)) == 0);
        }
        assertCornerOnly(screen);

        // The sheet now leaves the camera frame on its left: the limit shows on that side only.
        view.showLivePreview(liveFrame(0, 160));
        view.draw(new Canvas(screen));
        assertEquals("the camera limit is a line at the cut side", 0x40, Color.red(screen.getPixel(329, 536)));
        assertEquals(0, Color.red(screen.getPixel(470, 536)));
        assertCornerOnly(screen);
        view.capturePreview(false);
        screen.recycle();
    }

    @Test public void theLiveCornerDoesNotJumpForASmallMoveOrOneFrameWithoutPaper() throws Exception {
        HudView view = new HudView(RuntimeEnvironment.getApplication());
        view.layout(0, 0, 480, 640);
        view.capturePreview(true);
        view.showLivePreview(liveFrame(40, 200));
        java.lang.reflect.Field field = HudView.class.getDeclaredField("liveBox");
        field.setAccessible(true);
        int[] first = (int[]) field.get(view);
        view.showLivePreview(liveFrame(45, 205)); // one grid cell
        assertTrue("a small move keeps the shown box", first == field.get(view));
        Bitmap dark = Bitmap.createBitmap(240, 320, Bitmap.Config.ARGB_8888);
        dark.eraseColor(Color.rgb(0, 20, 0));
        view.showLivePreview(dark);
        assertTrue("one frame without paper keeps the shown box", first == field.get(view));
        view.showLivePreview(liveFrame(120, 240)); // sixteen cells
        assertTrue("a real move is followed", first != field.get(view));
        view.capturePreview(false);
        assertEquals(null, field.get(view));
    }

    /** A dark desk with a sheet of green 200 from {@code left} to {@code right}, rows 100 to 220. */
    private static Bitmap liveFrame(int left, int right) {
        Bitmap frame = Bitmap.createBitmap(240, 320, Bitmap.Config.ARGB_8888);
        frame.eraseColor(Color.rgb(0, 20, 0));
        Canvas canvas = new Canvas(frame);
        android.graphics.Paint paper = new android.graphics.Paint();
        paper.setColor(Color.rgb(0, 200, 0));
        canvas.drawRect(left, 100, right, 220, paper);
        return frame;
    }

    /** Lit pixels of one screen row inside the capture corner [328,440,472,632] of a 480x640 panel. */
    private static int litInRow(Bitmap screen, int y) {
        int lit = 0;
        for (int x = 328; x < 472; x++) if (Color.green(screen.getPixel(x, y)) > 200) lit++;
        return lit;
    }

    /** A capture display with the live image filling its corner [328,440,472,632], as the camera's frame does once turned upright. */
    private static HudView capturing() {
        HudView view = new HudView(RuntimeEnvironment.getApplication());
        view.layout(0, 0, 480, 640);
        view.capturePreview(true);
        Bitmap live = Bitmap.createBitmap(240, 320, Bitmap.Config.ARGB_8888);
        live.eraseColor(Color.rgb(0, 20, 0));
        view.showLivePreview(live);
        view.showAiming(List.of());
        return view;
    }

    /**
     * Lit pixels of the clip bar's four rows, 435 to 438. The corner's top edge is at 440 and the frame line drawn on
     * it takes rows 439 and 440: the bar stands on that line.
     */
    private static int[] barRows(HudView view, Bitmap screen) {
        TextCanvas canvas = new TextCanvas(screen);
        view.draw(canvas);
        assertEquals("no words", "", canvas.text.toString());
        assertCornerOnly(screen);
        assertEquals("nothing above the bar", 0, litInRow(screen, 434));
        return new int[]{litInRow(screen, 435), litInRow(screen, 436), litInRow(screen, 437), litInRow(screen, 438)};
    }

    /**
     * Worn on 2026-11-16 (M-33) nothing told the wearer that a clip was being recorded, or that it only counts frames
     * taken with the head still. A bar on the top edge of the small window, as wide as it: empty when the recording
     * starts, filled from the left as frames count. It stands still while the head moves; that is the whole cue.
     */
    @Test public void the_clip_bar_lies_on_the_top_edge_of_the_small_window_and_fills_from_the_left() {
        HudView view = capturing();
        Bitmap screen = Bitmap.createBitmap(480, 640, Bitmap.Config.ARGB_8888);

        view.showClipProgress(0, 60, true);
        assertArrayEquals("empty: one line as wide as the window, so that a clip which counts nothing still shows",
                new int[]{144, 0, 0, 0}, barRows(view, screen));
        assertEquals("the frame line it stands on is as it was", 144, litInRow(screen, 439));
        assertEquals("the image is not covered", 20, Color.green(screen.getPixel(400, 445)));

        view.showClipProgress(30, 60, true);
        assertArrayEquals("half of what the clip wants: half the width, four pixels high",
                new int[]{144, 72, 72, 72}, barRows(view, screen));
        assertTrue("filled from the left", Color.green(screen.getPixel(328, 437)) > 200 && Color.green(screen.getPixel(399, 437)) > 200);
        assertEquals(Color.BLACK, screen.getPixel(400, 437));
        assertEquals(20, Color.green(screen.getPixel(400, 445)));

        view.showClipProgress(60, 60, true);
        assertArrayEquals("full when the clip has what it wants", new int[]{144, 144, 144, 144}, barRows(view, screen));
        assertEquals("exactly as wide as the window", Color.BLACK, screen.getPixel(327, 437));
        assertEquals(Color.BLACK, screen.getPixel(472, 437));
        view.showClipProgress(75, 60, true);
        assertArrayEquals("never wider than the window", new int[]{144, 144, 144, 144}, barRows(view, screen));
        view.capturePreview(false);
        screen.recycle();
    }

    @Test public void the_clip_bar_is_absent_while_watching_and_on_the_still_route() {
        HudView view = capturing();
        Bitmap screen = Bitmap.createBitmap(480, 640, Bitmap.Config.ARGB_8888);
        view.showRecording(true); // the sound of a listening session is not a clip
        assertArrayEquals("no clip has reported: the still camera never does, and a clip camera that watches does not",
                new int[]{0, 0, 0, 0}, barRows(view, screen));
        view.showRecording(false);
        Bitmap still = page();
        view.showReview(still, List.of());
        assertArrayEquals("nor over the review of a still", new int[]{0, 0, 0, 0}, barRows(view, screen));
        view.showAiming(List.of());
        still.recycle();

        view.showClipProgress(0, 60, true);
        view.showClipProgress(45, 60, true);
        assertArrayEquals(new int[]{144, 108, 108, 108}, barRows(view, screen));
        view.showClipProgress(60, 60, false);
        assertArrayEquals("the recording has ended and the camera watches again", new int[]{0, 0, 0, 0}, barRows(view, screen));

        view.showClipProgress(10, 60, true);
        view.capturePreview(false);
        view.capturePreview(true);
        assertArrayEquals("a stopped capture forgets the bar", new int[]{0, 0, 0, 0}, barRows(view, screen));
        view.capturePreview(false);
        screen.recycle();
    }

    @Test public void the_clip_bar_is_absent_during_the_review_and_while_the_display_is_cleared() {
        HudView view = capturing();
        Bitmap screen = Bitmap.createBitmap(480, 640, Bitmap.Config.ARGB_8888);
        view.showClipProgress(30, 60, true);
        assertArrayEquals(new int[]{144, 72, 72, 72}, barRows(view, screen));

        view.setBlank(true); // the wearer's tap
        view.draw(new Canvas(screen));
        for (int y = 0; y < 640; y++) for (int x = 0; x < 480; x++) assertEquals(Color.BLACK, screen.getPixel(x, y));
        view.setBlank(false);
        assertArrayEquals("kept for the return", new int[]{144, 72, 72, 72}, barRows(view, screen));

        Bitmap photo = Bitmap.createBitmap(240, 320, Bitmap.Config.ARGB_8888);
        photo.eraseColor(Color.rgb(90, 90, 90));
        view.showReview(photo, List.of());
        assertArrayEquals("not over the three-second review", new int[]{0, 0, 0, 0}, barRows(view, screen));
        view.capturePreview(false);
        photo.recycle(); screen.recycle();
    }

    /** A capture display on which a recording has just ended with {@code counted} of the 60 frames it wants. */
    private static HudView afterClip(int counted) {
        HudView view = capturing();
        view.showClipProgress(0, 60, true);
        view.showClipProgress(counted, 60, true);
        view.showClipProgress(counted, 60, false);
        return view;
    }

    /** A page under review that fills the corner [328,440,472,632]: its first row is 440, under the bar's rows. */
    private static Bitmap page() {
        Bitmap photo = Bitmap.createBitmap(240, 320, Bitmap.Config.ARGB_8888);
        photo.eraseColor(Color.rgb(90, 90, 90));
        return photo;
    }

    /**
     * Of 17 worn clips (2026-11-16) the nine that counted 45 still frames or more all gave a usable page and the eight
     * that counted 28 or fewer did not, and nothing told the wearer which was which. A recording that ends under two
     * thirds of what it wants leaves its bar where it stopped, over that page's review: no word, and the page is
     * saved as always; the forward swipe that retakes it is the wearer's.
     */
    @Test public void a_clip_that_ended_short_keeps_its_bar_over_that_pages_review() {
        Bitmap screen = Bitmap.createBitmap(480, 640, Bitmap.Config.ARGB_8888), photo = page();
        for (int counted : new int[]{28, 39}) {
            HudView view = afterClip(counted);
            assertArrayEquals("gone with the recording, as before", new int[]{0, 0, 0, 0}, barRows(view, screen));
            view.showAiming(List.of()); // the page takes a moment to arrive: what the display is told meanwhile changes nothing
            view.showReview(photo, List.of());
            int filled = 144 * counted / 60;
            assertArrayEquals("where it stopped, " + counted + " of 60, with its line across the window",
                    new int[]{144, filled, filled, filled}, barRows(view, screen));
            assertEquals("nothing between the bar and the picture", 0, litInRow(screen, 439));
            assertTrue("the picture under review starts below the bar and is not covered",
                    Color.green(screen.getPixel(400, 440)) > 80 && Color.green(screen.getPixel(400, 440)) < 100);
            view.capturePreview(false);
        }
        photo.recycle(); screen.recycle();
    }

    @Test public void a_clip_that_reached_two_thirds_of_its_frames_shows_no_bar_in_its_review() {
        Bitmap screen = Bitmap.createBitmap(480, 640, Bitmap.Config.ARGB_8888), photo = page();
        for (int counted : new int[]{40, 45, 60}) {
            HudView view = afterClip(counted);
            view.showReview(photo, List.of());
            assertArrayEquals(counted + " of 60", new int[]{0, 0, 0, 0}, barRows(view, screen));
            view.capturePreview(false);
        }
        photo.recycle(); screen.recycle();
    }

    @Test public void the_short_clips_bar_goes_when_the_review_ends() {
        Bitmap screen = Bitmap.createBitmap(480, 640, Bitmap.Config.ARGB_8888), photo = page();
        HudView view = afterClip(28);
        view.showReview(photo, List.of());
        view.showReview(photo, List.of()); // the same page shown again keeps it
        assertArrayEquals(new int[]{144, 67, 67, 67}, barRows(view, screen));
        view.showAiming(List.of()); // saved, or the wearer's retake: a page is looked for
        assertArrayEquals(new int[]{0, 0, 0, 0}, barRows(view, screen));
        view.showReview(photo, List.of());
        assertArrayEquals("forgotten, not hidden: a review with no clip of its own has no bar",
                new int[]{0, 0, 0, 0}, barRows(view, screen));
        view.capturePreview(false);
        photo.recycle(); screen.recycle();
    }

    @Test public void the_short_clips_bar_goes_when_the_display_is_cleared() {
        Bitmap screen = Bitmap.createBitmap(480, 640, Bitmap.Config.ARGB_8888), photo = page();
        HudView view = afterClip(28);
        view.showReview(photo, List.of());
        assertArrayEquals(new int[]{144, 67, 67, 67}, barRows(view, screen));
        view.setBlank(true); // the wearer's tap: the page is held and gets its own review on return
        view.setBlank(false);
        assertArrayEquals(new int[]{0, 0, 0, 0}, barRows(view, screen));
        view.capturePreview(false);

        HudView cut = capturing(); // the tap came during the recording: the clip ends behind the cleared display
        cut.showClipProgress(10, 60, true);
        cut.setBlank(true);
        cut.showClipProgress(10, 60, false);
        cut.setBlank(false);
        cut.showReview(photo, List.of());
        assertArrayEquals(new int[]{0, 0, 0, 0}, barRows(cut, screen));
        cut.capturePreview(false);
        photo.recycle(); screen.recycle();
    }

    @Test public void the_short_clips_bar_goes_when_a_new_recording_starts() {
        Bitmap screen = Bitmap.createBitmap(480, 640, Bitmap.Config.ARGB_8888), photo = page();
        HudView view = afterClip(28);
        view.showReview(photo, List.of());
        assertArrayEquals(new int[]{144, 67, 67, 67}, barRows(view, screen));
        view.showClipProgress(0, 60, true);
        assertArrayEquals("neither the bar of the clip before nor that of the one being recorded",
                new int[]{0, 0, 0, 0}, barRows(view, screen));
        view.capturePreview(false);
        photo.recycle(); screen.recycle();
    }

    @Test public void the_short_clips_bar_goes_when_the_capture_is_not_active() {
        Bitmap screen = Bitmap.createBitmap(480, 640, Bitmap.Config.ARGB_8888), photo = page();
        HudView view = afterClip(28);
        view.showReview(photo, List.of());
        assertArrayEquals(new int[]{144, 67, 67, 67}, barRows(view, screen));
        view.capturePreview(false);
        assertArrayEquals(new int[]{0, 0, 0, 0}, barRows(view, screen));
        view.capturePreview(true);
        assertArrayEquals("a stopped capture forgets it", new int[]{0, 0, 0, 0}, barRows(view, screen));
        view.capturePreview(false);

        HudView cut = capturing(); // a tap or the ending double tap stops the camera first: the clip's end is reported after
        cut.showClipProgress(10, 60, true);
        cut.capturePreview(false);
        cut.showClipProgress(10, 60, false);
        cut.showReview(photo, List.of());
        cut.capturePreview(true);
        assertArrayEquals(new int[]{0, 0, 0, 0}, barRows(cut, screen));
        cut.capturePreview(false);
        photo.recycle(); screen.recycle();
    }

    /** Paper too far away fills little of the window; the four corners say so while the wearer can still move. */
    @Test public void the_far_mark_shows_only_while_waiting() {
        HudView view = new HudView(RuntimeEnvironment.getApplication());
        view.layout(0, 0, 480, 640);
        view.capturePreview(true);
        Bitmap live = Bitmap.createBitmap(320, 240, Bitmap.Config.ARGB_8888); // shown 144x108: the corners stay free
        live.eraseColor(Color.rgb(0, 20, 0));
        view.showLivePreview(live);
        Bitmap screen = Bitmap.createBitmap(480, 640, Bitmap.Config.ARGB_8888);
        int[][] corners = {{331, 443}, {468, 443}, {331, 628}, {468, 628}};
        view.draw(new Canvas(screen));
        for (int[] corner : corners) assertEquals(Color.BLACK, screen.getPixel(corner[0], corner[1]));

        view.showFar(true);
        TextCanvas canvas = new TextCanvas(screen);
        view.draw(canvas);
        assertEquals("no words", "", canvas.text.toString());
        for (int[] corner : corners) assertTrue("a mark at each corner", Color.green(screen.getPixel(corner[0], corner[1])) > 200);
        assertEquals("the image between them stays clear", 20, Color.green(screen.getPixel(400, 536)));
        assertCornerOnly(screen);

        Bitmap photo = Bitmap.createBitmap(320, 240, Bitmap.Config.ARGB_8888);
        photo.eraseColor(Color.rgb(90, 90, 90));
        view.showReview(photo, List.of());
        view.draw(new Canvas(screen));
        for (int[] corner : corners) assertEquals("not over the photo under review", Color.BLACK, screen.getPixel(corner[0], corner[1]));

        view.showAiming(List.of());
        view.showFar(false);
        view.draw(new Canvas(screen));
        for (int[] corner : corners) assertEquals(Color.BLACK, screen.getPixel(corner[0], corner[1]));
        view.showFar(true);
        view.capturePreview(false);
        view.capturePreview(true);
        view.draw(new Canvas(screen));
        for (int[] corner : corners) assertEquals("a stopped capture forgets the mark", Color.BLACK, screen.getPixel(corner[0], corner[1]));
        photo.recycle(); screen.recycle();
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
