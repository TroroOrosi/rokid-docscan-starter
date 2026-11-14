package dev.rokid.docscanglass.doc;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.DashPathEffect;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.view.View;
import dev.rokid.docscanrelay.study.AnswerLayout;
import dev.rokid.docscanrelay.study.AnswerDiagram;
import dev.rokid.docscanrelay.study.AnswerReader;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * The reading surface for a written answer: black background, green monospace,
 * filling the available height at a fixed readable type size.
 *
 * <p>The top row is the index -- which question this is and where in it the
 * reader stands -- and the rows under it are the answer itself. They never
 * share a row, because a heading read as part of the answer is a wrong answer.
 * The content description carries the original answer fragment, with no visual-wrap newlines.</p>
 *
 * <p>A narrower viewport re-flows through {@link AnswerReader#viewport}; it
 * never shrinks the type and never drops text. Every character of the answer
 * stays reachable by paging, which is what {@code AnswerLayout} guarantees by
 * keeping source offsets.</p>
 */
final class AnswerView extends View {
    private static final int GREEN = Color.rgb(0x40, 0xFF, 0x5E);
    private static final int INDEX_GREY = Color.rgb(0x8A, 0xC0, 0x96);
    private static final float SIDE_PADDING = 0.03f;

    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint indexPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint continuationPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path continuationPath = new Path();

    private AnswerReader reader;
    private List<String> body = Collections.emptyList();
    private List<Boolean> continuedFromPreviousLine = Collections.emptyList();
    private String index = "";

    AnswerView(Context context) {
        super(context);
        paint.setColor(GREEN);
        paint.setTypeface(Typeface.MONOSPACE);
        indexPaint.setColor(INDEX_GREY);
        indexPaint.setTypeface(Typeface.MONOSPACE);
        continuationPaint.setColor(INDEX_GREY);
        continuationPaint.setStyle(Paint.Style.STROKE);
        applyTextSize();
    }

    /** The answer type size. Fixed by the display height, never by the width. */
    float bodyTextSize() {
        return paint.getTextSize();
    }

    /** Shows this reader and follows it from here on. */
    void bind(AnswerReader newReader) {
        reader = newReader;
        applyViewport();
        refresh();
    }

    void announceExit() {
        index = "もう一度ダブルタップで終了";
        invalidate();
    }

    /** Failure stays in the index row; the answer text and position stay visible. */
    void announceSaveFailure() {
        index = "終了の保存失敗・再操作";
        invalidate();
    }

    /** Re-reads the reader after the host moved it. */
    void refresh() {
        if (reader == null || !reader.hasViewport()) {
            return;
        }
        String spoken;
        if (reader.screen() == AnswerReader.Screen.ANSWER) {
            AnswerLayout.Page page = reader.page();
            body = reader.diagram() == null ? new ArrayList<>(page.lines) : Collections.emptyList();
            continuedFromPreviousLine = reader.diagram() == null ? page.continuedFromPreviousLine : Collections.emptyList();
            spoken = reader.diagram() == null ? page.sourceText : reader.diagram().alt;
            index = reader.current().readingLabel() + "  " + reader.pageNumber() + "/" + reader.pageCount();
        } else {
            // On the index screens there is no answer to keep apart, so the
            // prompt belongs to the spoken text: it says what is being chosen.
            String prompt = reader.screen() == AnswerReader.Screen.GROUPS ? "大問を選択" : "小問を選択";
            body = List.of(prompt, reader.selectionLabel());
            continuedFromPreviousLine = Collections.emptyList();
            spoken = String.join("\n", body);
            index = reader.selectionNumber() + "/" + reader.selectionCount();
        }
        setContentDescription(spoken);
        invalidate();
    }

    @Override
    protected void onSizeChanged(int width, int height, int oldWidth, int oldHeight) {
        super.onSizeChanged(width, height, oldWidth, oldHeight);
        applyTextSize();
        applyViewport();
        refresh();
    }

    private void applyTextSize() {
        // The panel's height decides the type size; a narrow page or a margin re-flows instead.
        float height = panelHeight() > 0 ? panelHeight() : 640;
        paint.setTextSize(height * 0.05f);
        indexPaint.setTextSize(height * 0.035f);
        continuationPaint.setStrokeWidth(Math.max(1f, paint.getTextSize() * 0.04f));
    }

    /** Margins around this view place it for the wearer; sizes keep following the whole panel. */
    private int panelHeight() {
        return Math.max(getHeight(), getRootView().getHeight());
    }

    private void applyViewport() {
        if (reader == null || getWidth() <= 0 || getHeight() <= 0) {
            return;
        }
        int bodyLines = Math.max(1, (int)((getHeight() - bodyTop() - getWidth() * SIDE_PADDING) / lineHeight()));
        reader.viewport(textWidth(), bodyLines, paint::measureText);
    }

    private float lineHeight() {
        return Math.max(paint.getFontSpacing(), paint.getTextSize() * 1.25f);
    }

    private float bodyTop() {
        return getWidth() * SIDE_PADDING * 1.5f + indexPaint.getFontSpacing();
    }

    private float textWidth() {
        return Math.max(1f, getWidth() * (1 - 2 * SIDE_PADDING));
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        canvas.drawColor(Color.BLACK);
        float left = getWidth() * SIDE_PADDING;
        canvas.drawText(index, left, left - indexPaint.ascent(), indexPaint);
        if (reader != null && reader.hasViewport() && reader.diagram() != null) {
            drawDiagram(canvas, reader.diagram(), left, bodyTop());
            return;
        }
        float y = bodyTop() - paint.ascent();
        for (int row = 0; row < body.size(); row++) {
            String line = body.get(row);
            if (row < continuedFromPreviousLine.size() && continuedFromPreviousLine.get(row)) {
                drawContinuation(canvas, left, y);
            }
            canvas.drawText(line == null ? "" : line, left, y, paint);
            y += lineHeight();
        }
    }

    /** A small bent arrow in the existing gutter; never a character in the answer. */
    private void drawContinuation(Canvas canvas, float left, float baseline) {
        float right = left * .75f;
        float size = Math.min(left * .5f, paint.getTextSize() * .2f);
        float middle = baseline + (paint.ascent() + paint.descent()) * .5f;
        continuationPath.reset();
        continuationPath.moveTo(right - size, middle - size * .5f);
        continuationPath.lineTo(right - size, middle);
        continuationPath.lineTo(right, middle);
        continuationPath.moveTo(right - size * .4f, middle - size * .4f);
        continuationPath.lineTo(right, middle);
        continuationPath.lineTo(right - size * .4f, middle + size * .4f);
        canvas.drawPath(continuationPath, continuationPaint);
    }

    private void drawDiagram(Canvas canvas, AnswerDiagram diagram, float left, float top) {
        float width = textWidth(), height = getHeight() - top - left;
        if (width / height > diagram.aspectRatio) width = height * diagram.aspectRatio;
        else height = width / diagram.aspectRatio;
        left = (getWidth() - width) / 2;
        Paint vector = new Paint(paint);
        vector.setStrokeWidth(Math.max(2, panelHeight() * .004f));
        vector.setTextSize(Math.max(18, panelHeight() * .035f));
        try {
            JSONArray elements = diagram.toJson().getJSONArray("elements");
            for (int i = 0; i < elements.length(); i++) {
                JSONObject e = elements.getJSONObject(i);
                vector.setStyle(Paint.Style.STROKE);
                vector.setPathEffect(e.optBoolean("dashed", false)
                        ? new DashPathEffect(new float[]{vector.getStrokeWidth() * 4,
                                vector.getStrokeWidth() * 3}, 0) : null);
                switch (e.getString("type")) {
                    case "line":
                        canvas.drawLine(left + (float)e.getDouble("x1") * width,
                                top + (float)e.getDouble("y1") * height,
                                left + (float)e.getDouble("x2") * width,
                                top + (float)e.getDouble("y2") * height, vector); break;
                    case "circle":
                        if (e.has("filled") && !e.getBoolean("filled")) {
                            // An open endpoint must clear the curve beneath it. Ordinary
                            // geometric circles (without filled) keep their interiors.
                            Paint background = new Paint(vector);
                            background.setPathEffect(null);
                            background.setStyle(Paint.Style.FILL);
                            background.setColor(Color.BLACK);
                            canvas.drawCircle(left + (float)e.getDouble("cx") * width,
                                    top + (float)e.getDouble("cy") * height,
                                    (float)e.getDouble("r") * Math.min(width, height), background);
                        }
                        if (e.optBoolean("filled", false)) vector.setStyle(Paint.Style.FILL);
                        canvas.drawCircle(left + (float)e.getDouble("cx") * width,
                                top + (float)e.getDouble("cy") * height,
                                (float)e.getDouble("r") * Math.min(width, height), vector); break;
                    case "arc":
                        float cx = left + (float)e.getDouble("cx") * width;
                        float cy = top + (float)e.getDouble("cy") * height;
                        float radius = (float)e.getDouble("r") * Math.min(width, height);
                        canvas.drawArc(new RectF(cx - radius, cy - radius, cx + radius, cy + radius),
                                (float)e.getDouble("start_degrees"), (float)e.getDouble("sweep_degrees"),
                                false, vector); break;
                    case "polygon":
                    case "polyline":
                        Path path = new Path();
                        JSONArray points = e.getJSONArray("points");
                        for (int j = 0; j < points.length(); j++) {
                            JSONArray p = points.getJSONArray(j);
                            float x = left + (float)p.getDouble(0) * width;
                            float y = top + (float)p.getDouble(1) * height;
                            if (j == 0) path.moveTo(x, y); else path.lineTo(x, y);
                        }
                        if (e.getString("type").equals("polygon")) {
                            path.close();
                            if (e.optBoolean("hatched", false)) {
                                int save = canvas.save();
                                canvas.clipPath(path);
                                Paint hatch = new Paint(vector);
                                hatch.setPathEffect(null);
                                float spacing = Math.max(10, panelHeight() * .02f);
                                for (float x = left - height; x < left + width; x += spacing)
                                    canvas.drawLine(x, top + height, x + height, top, hatch);
                                canvas.restoreToCount(save);
                            }
                        }
                        canvas.drawPath(path, vector); break;
                    case "text":
                        vector.setStyle(Paint.Style.FILL);
                        String label = e.getString("text");
                        // A numbered marker refers to the full, paginated label before the figure.
                        if (label.contains("\n") || vector.measureText(label) > width * .45f) label = "[" + (i+1) + "]";
                        float x = Math.max(left, Math.min(left + (float)e.getDouble("x") * width,
                                left + width - vector.measureText(label)));
                        float y = Math.max(top - vector.ascent(), Math.min(top + (float)e.getDouble("y") * height,
                                top + height - vector.descent()));
                        canvas.drawText(label, x, y, vector);
                        break;
                }
            }
        } catch (JSONException impossible) { throw new IllegalStateException(impossible); }
    }
}
