package dev.rokid.docscanglass.doc;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.ColorMatrixColorFilter;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.text.Layout;
import android.text.StaticLayout;
import android.text.TextPaint;
import android.view.View;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * The glasses display: black background, green monospace text, and either the
 * live camera image or the still that was just taken in a small corner.
 *
 * <p>It holds no session state. What to show is decided by the shared
 * {@code DocScanController} and arrives through {@link GlassesCaptureSurface},
 * which is what lets the glasses run the relay's pipeline unchanged.</p>
 */
final class HudView extends View {
    private static final int GREEN = Color.rgb(0x40, 0xFF, 0x5E);
    /**
     * Capture text and the aim mark sit in the operator's line of sight over
     * the page (2026-09-30: "the text made it hard to shoot"). They clear this
     * long after appearing; black is transparent on the glasses and draws no
     * power. The corner still under review remains visible until commit.
     */
    static final long FADE_MILLIS = 1500;
    private static final float CAPTURE_FRACTION = .30f;
    private static final float CAPTURE_MARGIN = 8f;

    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final TextPaint statusPaint = new TextPaint(Paint.ANTI_ALIAS_FLAG);
    private final Paint guidePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint previewPaint = new Paint(Paint.FILTER_BITMAP_FLAG);
    private final Paint livePaint = new Paint(Paint.FILTER_BITMAP_FLAG);

    private List<String> lines = Collections.emptyList();
    private Bitmap preview;
    private Bitmap livePreview;
    private boolean capturing;
    private boolean aiming;
    private double guideFraction = FramingGuide.UNCALIBRATED_FRACTION;
    private boolean spreadGuide;
    private Runnable visibleFrame;
    private Runnable hiddenFrame;
    private boolean frameReported;
    private boolean recording;

    void showRecording(boolean active) { recording = active; invalidate(); }

    void capturePreview(boolean active) {
        capturing = active;
        if (!active && livePreview != null) { livePreview.recycle(); livePreview = null; }
        invalidate();
    }

    void showLivePreview(Bitmap bitmap) {
        Bitmap previous = livePreview;
        livePreview = bitmap;
        if (previous != null && previous != bitmap && !previous.isRecycled()) previous.recycle();
        invalidate();
    }

    void onVisibleFrame(Runnable shown, Runnable hidden) {
        visibleFrame = shown;
        hiddenFrame = hidden;
        frameReported = false;
        invalidate();
    }

    @Override
    protected void onWindowVisibilityChanged(int visibility) {
        super.onWindowVisibilityChanged(visibility);
        if (visibility != VISIBLE && frameReported) {
            frameReported = false;
            if (hiddenFrame != null) hiddenFrame.run();
        }
    }

    @Override
    public void onWindowFocusChanged(boolean focused) {
        super.onWindowFocusChanged(focused);
        if (!focused && frameReported) {
            frameReported = false;
            if (hiddenFrame != null) hiddenFrame.run();
        }
        if (focused) invalidate();
    }

    HudView(Context context) {
        super(context);
        paint.setColor(GREEN);
        paint.setTypeface(Typeface.MONOSPACE);
        statusPaint.set(paint);
        guidePaint.setColor(GREEN);
        guidePaint.setStyle(Paint.Style.STROKE);
    }

    /** Operator-adjustable drawing scale, from {@code --ef guide}. */
    void calibrateGuide(double visibleFraction) {
        guideFraction = visibleFraction;
        invalidate();
    }

    void showSpreadGuide(boolean spread) {
        spreadGuide = spread;
        invalidate();
    }

    /** Text only: the states where there is nothing to look at. */
    void showLines(List<String> newLines) {
        set(newLines, null, false);
    }

    /** Aiming keeps the live image and its frame visible throughout capture. */
    void showAiming(List<String> newLines) {
        set(newLines, null, true);
    }

    private Runnable fade;

    /** Clear what is shown now after FADE_MILLIS, unless something else replaces it first. */
    void fadeSoon() {
        List<String> shown = lines;
        boolean guide = aiming;
        if (fade != null) removeCallbacks(fade);
        fade = () -> {
            if (preview == null && aiming == guide && lines.equals(shown)) {
                lines = Collections.emptyList();
                aiming = false;
                invalidate();
            }
        };
        postDelayed(fade, FADE_MILLIS);
    }

    /**
     * Review: the complete still stays in the capture corner, without instructions.
     *
     * <p>The captured image stays visible for review while the live stream
     * observes any page turn for the next capture.</p>
     */
    void showReview(Bitmap still, List<String> newLines) {
        previewPaint.setColorFilter(reviewContrast(still));
        set(newLines, still, false);
    }

    /** Change only the corner status: the same image/frame and its 3s clock stay valid. */
    void showReviewNotice(String notice) {
        if (preview == null || preview.isRecycled()) return;
        lines = List.of(notice);
        invalidate();
    }

    private void set(List<String> newLines, Bitmap still, boolean showGuide) {
        lines = newLines == null ? Collections.emptyList() : new ArrayList<>(newLines);
        preview = still;
        aiming = showGuide;
        invalidate();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        canvas.drawColor(Color.BLACK);
        if (!frameReported && isShown() && hasWindowFocus() && visibleFrame != null) {
            frameReported = true;
            Runnable rendered = visibleFrame;
            post(() -> {
                if (frameReported && rendered == visibleFrame && isShown() && hasWindowFocus()) {
                    rendered.run();
                }
            });
        }

        Bitmap still = preview;
        if (still != null && !still.isRecycled()) {
            drawPreview(canvas, still);
        } else if (capturing && livePreview != null && !livePreview.isRecycled()) {
            drawPreview(canvas, livePreview);
            drawGuide(canvas);
        } else if (aiming) {
            drawGuide(canvas);
        }
        if (recording && still == null) {
            RectF area = captureArea();
            canvas.drawCircle(area.right - 3f, area.top - 12f, 3f, paint);
        }
        if (lines.isEmpty()) {
            return;
        }

        boolean compact = aiming || still != null;
        if (compact) {
            drawCaptureStatus(canvas);
            return;
        }
        drawStatus(canvas);
    }

    private void drawStatus(Canvas canvas) {
        StringBuilder text = new StringBuilder();
        for (String line : lines) {
            if (text.length() > 0) text.append('\n');
            if (line != null) text.append(line);
        }
        while (text.length() > 0 && text.charAt(text.length() - 1) == '\n') text.setLength(text.length() - 1);
        if (text.length() == 0 || getWidth() <= 0 || getHeight() <= 0) return;

        // Leave the centre clear and the existing lower-right camera image unobstructed.
        float bottom = Math.max(1f, getHeight() - CAPTURE_MARGIN);
        float height = Math.max(1f, getHeight() * .30f - CAPTURE_MARGIN);
        int width = Math.max(1, (int) (getWidth() * .60f - CAPTURE_MARGIN));
        statusPaint.setTextSize(18f);
        StaticLayout layout = statusLayout(text, width);
        while (layout.getHeight() > height && statusPaint.getTextSize() > 1f) {
            statusPaint.setTextSize(Math.max(1f, statusPaint.getTextSize() * height / layout.getHeight() - .5f));
            layout = statusLayout(text, width);
        }
        canvas.save();
        canvas.clipRect(CAPTURE_MARGIN, bottom - height, CAPTURE_MARGIN + width, bottom);
        canvas.translate(CAPTURE_MARGIN, bottom - layout.getHeight());
        layout.draw(canvas);
        canvas.restore();
    }

    private StaticLayout statusLayout(CharSequence text, int width) {
        return StaticLayout.Builder.obtain(text, 0, text.length(), statusPaint, width)
                .setAlignment(Layout.Alignment.ALIGN_NORMAL)
                .setIncludePad(true)
                .setBreakStrategy(Layout.BREAK_STRATEGY_SIMPLE)
                .setHyphenationFrequency(Layout.HYPHENATION_FREQUENCY_NONE)
                .build();
    }

    /** The display bounds are not a calibrated camera field of view. */
    private void drawGuide(Canvas canvas) {
        FramingGuide.Rect guide = FramingGuide.of(getWidth(), getHeight(), guideFraction, spreadGuide);
        if (guide.width() <= 0) {
            return;
        }
        guidePaint.setStrokeWidth(2f);
        Bitmap frame = livePreview;
        if (frame == null || frame.isRecycled()) return;
        RectF bounds = imageBounds(frame);
        canvas.drawRect(bounds, guidePaint);
    }

    /** Show the entire photograph in one corner; status never covers it. */
    private void drawPreview(Canvas canvas, Bitmap still) {
        RectF target = imageBounds(still);
        canvas.save();
        canvas.clipRect(captureArea());
        canvas.drawBitmap(still, null, target, still == livePreview ? livePaint : previewPaint);
        canvas.restore();
    }

    private RectF captureArea() {
        float right = Math.max(1, getWidth() - CAPTURE_MARGIN);
        float bottom = Math.max(1, getHeight() - CAPTURE_MARGIN);
        return new RectF(Math.max(0, right - getWidth() * CAPTURE_FRACTION),
                Math.max(0, bottom - getHeight() * CAPTURE_FRACTION), right, bottom);
    }

    private RectF imageBounds(Bitmap image) {
        RectF area = captureArea();
        float scale = Math.min(area.width() / image.getWidth(), area.height() / image.getHeight());
        float width = image.getWidth() * scale, height = image.getHeight() * scale;
        return new RectF(area.centerX() - width / 2f, area.centerY() - height / 2f,
                area.centerX() + width / 2f, area.centerY() + height / 2f);
    }

    private void drawCaptureStatus(Canvas canvas) {
        RectF area = captureArea();
        String text = lines.get(0) == null ? "" : lines.get(0);
        paint.setTextSize(18f);
        float available = Math.max(1, area.width() - 14f);
        float width = paint.measureText(text);
        if (width > available) paint.setTextSize(18f * available / width);
        canvas.drawText(text, area.left, area.top - 7f, paint);
    }

    /** Display-only green contrast stretch; JPEG, OCR and uploaded pixels stay untouched. */
    private static ColorMatrixColorFilter reviewContrast(Bitmap still) {
        int[] histogram = new int[256];
        int samples = 0;
        for (int y = 0; y < still.getHeight(); y += Math.max(1, still.getHeight() / 128)) {
            for (int x = 0; x < still.getWidth(); x += Math.max(1, still.getWidth() / 128)) {
                int pixel = still.getPixel(x, y);
                int gray = (int) (.213f * Color.red(pixel) + .715f * Color.green(pixel) + .072f * Color.blue(pixel));
                histogram[gray]++;
                samples++;
            }
        }
        // Ignore the extreme 1% so a lamp or one black corner cannot set the entire range.
        int low = 0, high = 255, count = 0;
        while (low < 255 && count + histogram[low] <= samples / 100) count += histogram[low++];
        count = 0;
        while (high > low && count + histogram[high] <= samples / 100) count += histogram[high--];
        if (high - low < 16) { low = 0; high = 255; }
        float scale = 255f / (high - low);
        return new ColorMatrixColorFilter(new float[]{
                0, 0, 0, 0, 0,
                .213f * scale, .715f * scale, .072f * scale, 0, -low * scale,
                0, 0, 0, 0, 0,
                0, 0, 0, 1, 0});
    }
}
