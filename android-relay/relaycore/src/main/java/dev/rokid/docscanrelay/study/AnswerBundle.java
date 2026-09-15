package dev.rokid.docscanrelay.study;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Complete, ordered snapshot for offline reading, including unanswered entries. */
public final class AnswerBundle {
    public static final int SCHEMA_VERSION = 1;
    public static final int MAX_JSON_BYTES = 2 * 1024 * 1024;
    public final String sessionId;
    public final String inputDigest;
    /** Result snapshot revision; input identity is independently fixed by inputDigest. */
    public final long revision;
    public final List<AnswerItem> items;

    public AnswerBundle(String sessionId, String inputDigest, long revision, List<AnswerItem> items) {
        this.sessionId = AnswerItem.identifier(sessionId);
        if (inputDigest == null || !inputDigest.matches("[a-f0-9]{64}") || revision < 1
                || items == null || items.isEmpty() || items.size() > 2000) {
            throw new IllegalArgumentException("invalid answer bundle");
        }
        this.inputDigest = inputDigest;
        this.revision = revision;
        Set<String> ids = new HashSet<>();
        Map<String, String> labels = new HashMap<>();
        long chars = 0;
        for (AnswerItem item : items) {
            if (item == null || !ids.add(item.questionId)) {
                throw new IllegalArgumentException("duplicate question identity");
            }
            String previous = labels.put(item.groupId, item.groupLabel);
            if (previous != null && !previous.equals(item.groupLabel)) {
                throw new IllegalArgumentException("inconsistent group label");
            }
            chars += item.answer.length() + item.issue.length();
        }
        if (chars > MAX_JSON_BYTES / 3) throw new IllegalArgumentException("answer bundle too large");
        this.items = Collections.unmodifiableList(new ArrayList<>(items));
    }

    public boolean fullyAnswered() {
        for (AnswerItem item : items) if (item.status != AnswerItem.Status.READY) return false;
        return true;
    }

    public boolean finished() {
        for (AnswerItem item : items) if (item.status == AnswerItem.Status.PENDING) return false;
        return true;
    }

    public AnswerBundle withAnswer(AnswerItem replacement) {
        List<AnswerItem> next = new ArrayList<>(items);
        for (int i = 0; i < next.size(); i++) {
            AnswerItem old = next.get(i);
            if (!old.questionId.equals(replacement.questionId)) continue;
            if (!old.groupId.equals(replacement.groupId) || !old.groupLabel.equals(replacement.groupLabel)
                    || !old.questionLabel.equals(replacement.questionLabel)) {
                throw new IllegalArgumentException("answer does not belong to this question");
            }
            next.set(i, replacement);
            return new AnswerBundle(sessionId, inputDigest, Math.addExact(revision, 1), next);
        }
        throw new IllegalArgumentException("unknown question identity");
    }

    public String toJson() {
        try {
            JSONArray array = new JSONArray();
            for (AnswerItem item : items) array.put(new JSONObject()
                    .put("group_id", item.groupId).put("group_label", item.groupLabel)
                    .put("question_id", item.questionId).put("question_label", item.questionLabel)
                    .put("answer", item.answer).put("status", item.status.name().toLowerCase(Locale.ROOT))
                    .put("issue", item.issue).put("diagrams", AnswerDiagram.encode(item.diagrams)));
            boolean hasDiagrams = false;
            for (AnswerItem item : items) hasDiagrams |= !item.diagrams.isEmpty();
            String json = new JSONObject().put("schema_version", hasDiagrams ? 2 : SCHEMA_VERSION)
                    .put("session_id", sessionId).put("input_digest", inputDigest)
                    .put("revision", revision).put("items", array).toString();
            if (json.getBytes(StandardCharsets.UTF_8).length > MAX_JSON_BYTES) {
                throw new IllegalArgumentException("answer bundle too large");
            }
            return json;
        } catch (JSONException impossible) {
            throw new IllegalStateException("could not encode answer bundle", impossible);
        }
    }

    public static AnswerBundle fromJson(String json) throws JSONException {
        if (json == null || json.length() > MAX_JSON_BYTES
                || json.getBytes(StandardCharsets.UTF_8).length > MAX_JSON_BYTES) {
            throw new IllegalArgumentException("answer bundle too large");
        }
        JSONObject root = new JSONObject(json);
        long schema = number(root, "schema_version");
        if (schema != SCHEMA_VERSION && schema != 2) {
            throw new IllegalArgumentException("unsupported answer schema");
        }
        JSONArray array = root.getJSONArray("items");
        if (array.length() > 2000) throw new IllegalArgumentException("too many answers");
        List<AnswerItem> items = new ArrayList<>();
        for (int i = 0; i < array.length(); i++) {
            JSONObject item = array.getJSONObject(i);
            items.add(new AnswerItem(string(item, "group_id"), string(item, "group_label"),
                    string(item, "question_id"), string(item, "question_label"), string(item, "answer"),
                    AnswerItem.Status.valueOf(string(item, "status").toUpperCase(Locale.ROOT)),
                    string(item, "issue"), AnswerDiagram.parse(item.has("diagrams")
                            ? item.getJSONArray("diagrams") : null)));
        }
        return new AnswerBundle(string(root, "session_id"), string(root, "input_digest"),
                number(root, "revision"), items);
    }

    static String string(JSONObject object, String key) throws JSONException {
        Object value = object.get(key);
        if (!(value instanceof String)) throw new JSONException("invalid string: " + key);
        return (String) value;
    }

    static long number(JSONObject object, String key) throws JSONException {
        Object value = object.get(key);
        if (!(value instanceof Integer) && !(value instanceof Long)) {
            throw new JSONException("invalid integer: " + key);
        }
        return ((Number) value).longValue();
    }
}
