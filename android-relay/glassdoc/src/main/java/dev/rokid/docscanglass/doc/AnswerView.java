package dev.rokid.docscanglass.doc;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
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
 * three rows.
 *
 * <p>The top row is the index -- which question this is and where in it the
 * reader stands -- and the rows under it are the answer itself. They never
 * share a row, because a heading read as part of the answer is a wrong answer.
 * The content description carries only the answer rows.</p>
 *
 * <p>A narrower viewport re-flows through {@link AnswerReader#viewport}; it
 * never shrinks the type and never drops text. Every character of the answer
 * stays reachable by paging, which is what {@code AnswerLayout} guarantees by
 * keeping source offsets.</p>
 */
final class AnswerView extends View {
    private static final int GREEN = Color.rgb(0x40, 0xFF, 0x5E);
    private static final int INDEX_GREY = Color.rgb(0x8A, 0xC0, 0x96);
    /** One index row and two answer rows: the three-line display contract. */
    private static final int BODY_LINES = 2;
    private static final float SIDE_PADDING = 0.03f;

    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint indexPaint = new Paint(Paint.ANTI_ALIAS_FLAG);

    private AnswerReader reader;
    private List<String> body = Collections.emptyList();
    private String index = "";

    AnswerView(Context context) {
        super(context);
        paint.setColor(GREEN);
        paint.setTypeface(Typeface.MONOSPACE);
        indexPaint.setColor(INDEX_GREY);
        indexPaint.setTypeface(Typeface.MONOSPACE);
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
        if (reader == null) {
            return;
        }
        if (reader.screen() == AnswerReader.Screen.ANSWER) {
            AnswerLayout.Page page = reader.page();
            body = reader.diagram() == null ? new ArrayList<>(page.lines) : Collections.emptyList();
            index = reader.current().heading() + "  " + reader.pageNumber() + "/" + reader.pageCount();
        } else {
            // On the index screens there is no answer to keep apart, so the
            // prompt belongs to the spoken text: it says what is being chosen.
            String prompt = reader.screen() == AnswerReader.Screen.GROUPS ? "大問を選択" : "小問を選択";
            body = List.of(prompt, reader.selectionLabel());
            index = reader.selectionNumber() + "/" + reader.selectionCount();
        }
        setContentDescription(reader.diagram() == null ? String.join("\n", body) : reader.diagram().alt);
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
        // Height decides the type size; a narrow page re-flows instead.
        float height = getHeight() > 0 ? getHeight() : 640;
        paint.setTextSize(height * 0.05f);
        indexPaint.setTextSize(height * 0.035f);
    }

    private void applyViewport() {
        if (reader == null || getWidth() <= 0) {
            return;
        }
        reader.viewport(textWidth(), BODY_LINES, paint::measureText);
    }

    private float textWidth() {
        return Math.max(1f, getWidth() * (1 - 2 * SIDE_PADDING));
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        canvas.drawColor(Color.BLACK);
        float left = getWidth() * SIDE_PADDING;
        float row = paint.getTextSize() * 1.5f;
        float y = row;
        canvas.drawText(index, left, y, indexPaint);
        if (reader != null && reader.diagram() != null) {
            drawDiagram(canvas, reader.diagram(), left, row * 1.7f);
            return;
        }
        for (String line : body) {
            y += row;
            canvas.drawText(line == null ? "" : line, left, y, paint);
        }
    }

    private void drawDiagram(Canvas canvas, AnswerDiagram diagram, float left, float top) {
        float width = textWidth(), height = getHeight() - top - left;
        if (width / height > diagram.aspectRatio) width = height * diagram.aspectRatio;
        else height = width / diagram.aspectRatio;
        left = (getWidth() - width) / 2;
        Paint vector = new Paint(paint);
        vector.setStrokeWidth(Math.max(2, getHeight() * .004f));
        vector.setTextSize(Math.max(18, getHeight() * .035f));
        try {
            JSONArray elements = diagram.toJson().getJSONArray("elements");
            for (int i = 0; i < elements.length(); i++) {
                JSONObject e = elements.getJSONObject(i);
                vector.setStyle(Paint.Style.STROKE);
                switch (e.getString("type")) {
                    case "line":
                        canvas.drawLine(left + (float)e.getDouble("x1") * width,
                                top + (float)e.getDouble("y1") * height,
                                left + (float)e.getDouble("x2") * width,
                                top + (float)e.getDouble("y2") * height, vector); break;
                    case "circle":
                        canvas.drawCircle(left + (float)e.getDouble("cx") * width,
                                top + (float)e.getDouble("cy") * height,
                                (float)e.getDouble("r") * Math.min(width, height), vector); break;
                    case "polyline":
                        Path path = new Path();
                        JSONArray points = e.getJSONArray("points");
                        for (int j = 0; j < points.length(); j++) {
                            JSONArray p = points.getJSONArray(j);
                            float x = left + (float)p.getDouble(0) * width;
                            float y = top + (float)p.getDouble(1) * height;
                            if (j == 0) path.moveTo(x, y); else path.lineTo(x, y);
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
