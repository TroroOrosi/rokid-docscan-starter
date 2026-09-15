package dev.rokid.docscanrelay.study;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Validated, immutable vector data. Coordinates match app/answer_diagrams.py. */
public final class AnswerDiagram {
    public final String alt;
    public final float aspectRatio;
    private final String json;

    public AnswerDiagram(JSONObject value) throws JSONException {
        if (value.length() != 3) throw new JSONException("invalid diagram fields");
        alt = label(value, "alt", 500);
        aspectRatio = number(value.get("aspect_ratio"), .25f, 4f);
        JSONArray elements = value.getJSONArray("elements");
        if (elements.length() < 1 || elements.length() > 128) throw new JSONException("invalid elements");
        for (int i = 0; i < elements.length(); i++) {
            JSONObject e = elements.getJSONObject(i);
            String type = AnswerBundle.string(e, "type");
            String[] coordinates;
            int fields;
            switch (type) {
                case "line": coordinates = new String[]{"x1", "y1", "x2", "y2"}; fields = 5; break;
                case "circle": coordinates = new String[]{"cx", "cy", "r"}; fields = 4; break;
                case "text":
                    coordinates = new String[]{"x", "y"}; fields = 4;
                    label(e, "text", 80); break;
                case "polyline":
                    coordinates = new String[]{}; fields = 2;
                    JSONArray points = e.getJSONArray("points");
                    if (points.length() < 2 || points.length() > 256) throw new JSONException("invalid points");
                    for (int j = 0; j < points.length(); j++) {
                        JSONArray point = points.getJSONArray(j);
                        if (point.length() != 2) throw new JSONException("invalid point");
                        number(point.get(0), 0, 1); number(point.get(1), 0, 1);
                    }
                    break;
                default: throw new JSONException("unsupported diagram element");
            }
            if (e.length() != fields) throw new JSONException("invalid element fields");
            for (String key : coordinates) number(e.get(key), 0, 1);
            if (type.equals("circle")) {
                double r = e.getDouble("r"), cx = e.getDouble("cx"), cy = e.getDouble("cy");
                double rx = r / Math.max(1, aspectRatio), ry = r * Math.min(1, aspectRatio);
                if (r <= 0 || cx < rx || cx > 1-rx || cy < ry || cy > 1-ry)
                    throw new JSONException("circle outside diagram");
            }
        }
        json = value.toString();
    }

    private static String label(JSONObject value, String key, int max) throws JSONException {
        String text = AnswerBundle.string(value, key);
        if (text.trim().isEmpty() || text.length() > max) throw new JSONException("invalid label");
        return text;
    }

    private static float number(Object value, float min, float max) throws JSONException {
        if (!(value instanceof Number)) throw new JSONException("invalid coordinate");
        double n = ((Number) value).doubleValue();
        if (!Double.isFinite(n) || n < min || n > max) throw new JSONException("invalid coordinate");
        return (float) n;
    }

    public JSONObject toJson() {
        try { return new JSONObject(json); }
        catch (JSONException impossible) { throw new IllegalStateException(impossible); }
    }

    /** Full descriptions/labels remain reachable even when a label cannot fit in the figure. */
    public String readingText(int figureNumber) {
        StringBuilder text = new StringBuilder("\n図" + figureNumber + ": " + alt);
        try {
            JSONArray elements = toJson().getJSONArray("elements");
            for (int i = 0; i < elements.length(); i++) {
                JSONObject e = elements.getJSONObject(i);
                if (e.getString("type").equals("text")) {
                    text.append("\n[").append(i + 1).append("] ").append(e.getString("text"));
                }
            }
        } catch (JSONException impossible) { throw new IllegalStateException(impossible); }
        return text.toString();
    }

    @Override public boolean equals(Object value) {
        return value instanceof AnswerDiagram && json.equals(((AnswerDiagram)value).json);
    }
    @Override public int hashCode() { return json.hashCode(); }

    public static List<AnswerDiagram> parse(JSONArray array) throws JSONException {
        if (array == null) return Collections.emptyList();
        if (array.length() > 4) throw new JSONException("too many diagrams");
        List<AnswerDiagram> result = new ArrayList<>();
        for (int i = 0; i < array.length(); i++) result.add(new AnswerDiagram(array.getJSONObject(i)));
        return Collections.unmodifiableList(result);
    }

    public static JSONArray encode(List<AnswerDiagram> diagrams) {
        JSONArray array = new JSONArray();
        for (AnswerDiagram diagram : diagrams) array.put(diagram.toJson());
        return array;
    }
}
