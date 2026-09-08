package dev.rokid.docscanglass.doc;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.view.View;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * The glasses display: black background, green monospace text, and either the
 * aiming brackets or the still that was just taken.
 *
 * <p>It holds no session state. What to show is decided by the shared
 * {@code DocScanController} and arrives through {@link GlassesCaptureSurface},
 * which is what lets the glasses run the relay's pipeline unchanged.</p>
 */
final class HudView extends View {
    private static final int GREEN = Color.rgb(0x40, 0xFF, 0x5E);

    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint guidePaint = new Paint(Paint.ANTI_ALIAS_FLAG);

    private List<String> lines = Collections.emptyList();
    private Bitmap preview;
    private boolean aiming;
    private double guideFraction = FramingGuide.UNCALIBRATED_FRACTION;

    HudView(Context context) {
        super(context);
        paint.setColor(GREEN);
        paint.setTypeface(Typeface.MONOSPACE);
        guidePaint.setColor(GREEN);
        guidePaint.setStyle(Paint.Style.STROKE);
    }

    /** The visible fraction measured for this device, from {@code --ef guide}. */
    void calibrateGuide(double visibleFraction) {
        guideFraction = visibleFraction;
    }

    /** Text only: the states where there is nothing to look at. */
    void showLines(List<String> newLines) {
        set(newLines, null, false);
    }

    /** Aiming: the brackets the operator aligns the page to. */
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

        float textTop = 0;
        Bitmap still = preview;
        if (still != null && !still.isRecycled()) {
            textTop = drawPreview(canvas, still);
        } else if (aiming) {
            drawGuide(canvas);
        }
        if (lines.isEmpty()) {
            return;
        }

        float available = getHeight() - textTop;
        float lineHeight = available / (float) (lines.size() + 1);
        paint.setTextSize(lineHeight * 0.55f);
        float y = textTop + lineHeight;
        for (String line : lines) {
            canvas.drawText(line == null ? "" : line, lineHeight * 0.2f, y, paint);
            y += lineHeight;
        }
    }

    /**
     * The aiming rectangle. Corner brackets rather than a closed box: on a
     * monochrome see-through display a full outline competes with the page
     * itself, and the corners are what the operator aligns to.
     */
    private void drawGuide(Canvas canvas) {
        FramingGuide.Rect guide = FramingGuide.of(getWidth(), getHeight(), guideFraction);
        if (guide.width() <= 0) {
            return;
        }
        float arm = Math.min(guide.width(), guide.height()) * 0.18f;
        guidePaint.setStrokeWidth(Math.max(2f, guide.width() * 0.008f));
        float[] corners = {
            guide.left(), guide.top(), 1, 1,
            guide.right(), guide.top(), -1, 1,
            guide.left(), guide.bottom(), 1, -1,
            guide.right(), guide.bottom(), -1, -1,
        };
        for (int i = 0; i < corners.length; i += 4) {
            float x = corners[i];
            float y = corners[i + 1];
            float dx = corners[i + 2];
            float dy = corners[i + 3];
            canvas.drawLine(x, y, x + arm * dx, y, guidePaint);
            canvas.drawLine(x, y, x, y + arm * dy, guidePaint);
        }
    }

    /** Draws the still letterboxed into the top band and returns its bottom. */
    private float drawPreview(Canvas canvas, Bitmap still) {
        float band = getHeight() * 0.62f;
        float scale = Math.min(
                getWidth() / (float) still.getWidth(), band / still.getHeight());
        float width = still.getWidth() * scale;
        float height = still.getHeight() * scale;
        RectF target = new RectF(
                (getWidth() - width) / 2f, 0, (getWidth() + width) / 2f, height);
        canvas.drawBitmap(still, null, target, null);
        return height;
    }
}
