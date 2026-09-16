package dev.rokid.docscanglass.doc;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.ColorMatrixColorFilter;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.view.View;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * The glasses display: black background, green monospace text, and either the
 * aiming mark or the still that was just taken.
 *
 * <p>It holds no session state. What to show is decided by the shared
 * {@code DocScanController} and arrives through {@link GlassesCaptureSurface},
 * which is what lets the glasses run the relay's pipeline unchanged.</p>
 */
final class HudView extends View {
    private static final int GREEN = Color.rgb(0x40, 0xFF, 0x5E);

    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint guidePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint previewPaint = new Paint(Paint.FILTER_BITMAP_FLAG);

    private List<String> lines = Collections.emptyList();
    private Bitmap preview;
    private boolean aiming;
    private double guideFraction = FramingGuide.UNCALIBRATED_FRACTION;
    private boolean spreadGuide;
    private Runnable visibleFrame;
    private Runnable hiddenFrame;
    private boolean frameReported;
    private boolean recording;

    void showRecording(boolean active) { recording = active; invalidate(); }

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

    /** Aiming: a direction cue, not an outline to fit the physical page into. */
    void showAiming(List<String> newLines) {
        set(newLines, null, true);
    }

    /**
     * Review: the still fills the upper band and the text sits under it.
     *
     * <p>This is the substitute for a viewfinder. A live preview would hold
     * the camera streaming, and the privacy indicator stays lit for exactly as
     * long as the camera streams.</p>
     */
    void showReview(Bitmap still, List<String> newLines) {
        previewPaint.setColorFilter(reviewContrast(still));
        set(newLines, still, false);
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

        float textTop = 0;
        Bitmap still = preview;
        if (still != null && !still.isRecycled()) {
            textTop = drawPreview(canvas, still);
        } else if (aiming) {
            drawGuide(canvas);
            textTop = Math.max(0, getHeight() - (lines.size() + 1) * 26f);
        }
        if (recording) {
            paint.setTextSize(22);
            canvas.drawText("REC", Math.max(8, getWidth() - 62), getHeight() - 8, paint);
        }
        if (lines.isEmpty()) {
            return;
        }

        float available = getHeight() - textTop;
        boolean compact = aiming || still != null;
        float lineHeight = compact ? 26f : available / (float) (lines.size() + 1);
        float textSize = compact ? 22f : lineHeight * 0.55f;
        paint.setTextSize(textSize);
        float widest = 0;
        for (String line : lines) {
            widest = Math.max(widest, paint.measureText(line == null ? "" : line));
        }
        float textWidth = Math.max(1, getWidth() - lineHeight * 0.4f);
        if (widest > textWidth) {
            paint.setTextSize(textSize * textWidth / widest);
        }
        float y = textTop + lineHeight;
        for (String line : lines) {
            canvas.drawText(line == null ? "" : line, lineHeight * 0.2f, y, paint);
            y += lineHeight;
        }
    }

    /** The display bounds are not a calibrated camera field of view. */
    private void drawGuide(Canvas canvas) {
        FramingGuide.Rect guide = FramingGuide.of(getWidth(), getHeight(), guideFraction, spreadGuide);
        if (guide.width() <= 0) {
            return;
        }
        float radius = Math.max(4f, Math.min(guide.width(), guide.height()) * 0.03f);
        float x = getWidth() / 2f;
        float y = getHeight() / 2f;
        guidePaint.setStrokeWidth(2f);
        canvas.drawLine(x - radius, y, x + radius, y, guidePaint);
        canvas.drawLine(x, y - radius, x, y + radius, guidePaint);
        paint.setTextSize(22);
        canvas.drawText(spreadGuide ? "B5 見開き" : "B5 1ページ", 8, 26, paint);
        canvas.drawText("紙面へ顔を向ける", 8, 54, paint);
    }

    /** Show the complete capture once, with no inset or label covering the paper. */
    private float drawPreview(Canvas canvas, Bitmap still) {
        float band = Math.max(1, getHeight() - (lines.size() + 1) * 26f);
        float scale = Math.min(
                getWidth() / (float) still.getWidth(), band / still.getHeight());
        float width = still.getWidth() * scale;
        float height = still.getHeight() * scale;
        RectF target = new RectF(
                (getWidth() - width) / 2f, (band - height) / 2f,
                (getWidth() + width) / 2f, (band + height) / 2f);
        canvas.save();
        canvas.clipRect(0, 0, getWidth(), band);
        canvas.drawBitmap(still, null, target, previewPaint);
        canvas.restore();
        return band;
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
