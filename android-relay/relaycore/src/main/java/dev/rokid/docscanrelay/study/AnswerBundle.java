package dev.rokid.docscanrelay.study;

import android.util.JsonReader;
import android.util.JsonWriter;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.StringWriter;
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
    // Two Work stages may each return 8 MiB. Explicit mathematical scripts can
    // expand an ASCII digit to a three-byte Unicode glyph during display conversion.
    public static final int MAX_JSON_BYTES = 64 * 1024 * 1024;
    public static final int MAX_TEXT_CHARS = 24 * 1024 * 1024;
    public final String sessionId;
    public final String inputDigest;
    /** Result snapshot revision; input identity is independently fixed by inputDigest. */
    public final long revision;
    public final String analysisStage;
    public final String availableStage;
    public final List<AnswerItem> items;
    /** Capture pages (1-based) the wearer should photograph again; empty for none. */
    public final List<Integer> retake;
    /** A second read is still being compared with these answers. */
    public final boolean comparing;

    public AnswerBundle(String sessionId, String inputDigest, long revision, List<AnswerItem> items) {
        this(sessionId, inputDigest, revision, items, "single", "complete");
    }

    public AnswerBundle(String sessionId, String inputDigest, long revision, List<AnswerItem> items,
                        String analysisStage, String availableStage) {
        this(sessionId, inputDigest, revision, items, analysisStage, availableStage, Collections.emptyList(), false);
    }

    public AnswerBundle(String sessionId, String inputDigest, long revision, List<AnswerItem> items,
                        String analysisStage, String availableStage, List<Integer> retake, boolean comparing) {
        this.sessionId = AnswerItem.identifier(sessionId);
        if (inputDigest == null || !inputDigest.matches("[a-f0-9]{64}") || revision < 1
                || items == null || items.isEmpty() || items.size() > 2000) {
            throw new IllegalArgumentException("invalid answer bundle");
        }
        if (retake == null || retake.size() > 100
                || retake.stream().anyMatch(page -> page == null || page < 1 || page > 1000)) {
            throw new IllegalArgumentException("invalid retake page");
        }
        this.retake = Collections.unmodifiableList(new ArrayList<>(retake));
        this.inputDigest = inputDigest;
        this.revision = revision;
        if (!List.of("single", "reading", "awaiting_audio", "listening", "complete").contains(analysisStage)
                || !List.of("none", "reading", "complete").contains(availableStage)) {
            throw new IllegalArgumentException("invalid answer stage");
        }
        this.analysisStage = analysisStage;
        this.availableStage = availableStage;
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
            // An older server says it with a notice item, which is not shown.
            comparing = comparing || (item.notice() && item.questionId.equals("read-comparing"));
        }
        if (chars > MAX_TEXT_CHARS) throw new IllegalArgumentException("answer bundle too large");
        this.items = Collections.unmodifiableList(new ArrayList<>(items));
        this.comparing = comparing;
    }

    public boolean fullyAnswered() {
        for (AnswerItem item : items) if (item.status != AnswerItem.Status.READY) return false;
        return true;
    }

    public boolean finished() {
        for (AnswerItem item : items) if (item.status == AnswerItem.Status.PENDING) return false;
        return true;
    }

    public boolean intermediate() { return !"single".equals(analysisStage) && !"complete".equals(availableStage); }

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
            return new AnswerBundle(sessionId, inputDigest, Math.addExact(revision, 1), next, analysisStage,
                    availableStage, retake, comparing);
        }
        throw new IllegalArgumentException("unknown question identity");
    }

    public String toJson() {
        StringWriter text = new StringWriter();
        try {
            JsonWriter writer = new JsonWriter(text);
            writeJson(writer);
            writer.flush();
            String json = text.toString();
            if (json.getBytes(StandardCharsets.UTF_8).length > MAX_JSON_BYTES)
                throw new IllegalArgumentException("answer bundle too large");
            return json;
        } catch (IOException | JSONException impossible) {
            throw new IllegalStateException("could not encode answer bundle", impossible);
        }
    }

    void writeJson(JsonWriter writer) throws IOException, JSONException {
        int schema = SCHEMA_VERSION;
        for (AnswerItem item : items) for (AnswerDiagram diagram : item.diagrams)
            schema = Math.max(schema, diagram.schemaVersion);
        writer.beginObject().name("schema_version").value(schema)
                .name("session_id").value(sessionId).name("input_digest").value(inputDigest)
                .name("revision").value(revision).name("analysis_stage").value(analysisStage)
                .name("available_stage").value(availableStage).name("retake").beginArray();
        for (Integer page : retake) writer.value(page);
        writer.endArray().name("comparing").value(comparing).name("items").beginArray();
        for (AnswerItem item : items) {
            writer.beginObject().name("group_id").value(item.groupId).name("group_label").value(item.groupLabel)
                    .name("question_id").value(item.questionId).name("question_label").value(item.questionLabel)
                    .name("answer").value(item.answer).name("status").value(item.status.name().toLowerCase(Locale.ROOT))
                    .name("issue").value(item.issue).name("other").value(item.other).name("seen").value(item.seen)
                    .name("uncertain").value(item.uncertain)
                    .name("diagrams");
            AnswerJson.writeValue(writer, AnswerDiagram.encode(item.diagrams));
            writer.name("answer_no").beginArray();
            for (Integer number : item.answerNumbers) writer.value(number);
            writer.endArray().endObject();
        }
        writer.endArray().endObject();
    }

    void checkSerializedSize() throws IOException, JSONException {
        JsonWriter writer = AnswerJson.writer(null, MAX_JSON_BYTES);
        writeJson(writer);
        writer.flush();
    }

    public static AnswerBundle fromJson(String json) throws JSONException {
        if (json == null || json.length() > MAX_JSON_BYTES)
            throw new IllegalArgumentException("answer bundle too large");
        try { return fromStream(new ByteArrayInputStream(json.getBytes(StandardCharsets.UTF_8))); }
        catch (IOException invalid) { throw new JSONException("invalid answer JSON: " + invalid.getMessage()); }
    }

    public static AnswerBundle fromStream(InputStream source) throws IOException, JSONException {
        JsonReader reader = AnswerJson.reader(source, MAX_JSON_BYTES);
        AnswerBundle bundle = readJson(reader);
        AnswerJson.endDocument(reader);
        bundle.checkSerializedSize();
        return bundle;
    }

    static AnswerBundle readJson(JsonReader reader) throws IOException, JSONException {
        String session = null, digest = null, stage = "single", available = "complete";
        long schema = 0, revision = 0;
        List<Integer> retake = new ArrayList<>();
        boolean comparing = false;
        List<AnswerItem> items = null;
        long characters = 0;
        Set<String> fields = new HashSet<>();
        reader.beginObject();
        while (reader.hasNext()) {
            String name = reader.nextName();
            if (fields.size() >= 32 || !fields.add(name)) throw new IOException("invalid answer fields");
            switch (name) {
                case "schema_version": schema = AnswerJson.integer(reader); break;
                case "session_id": session = AnswerJson.string(reader); break;
                case "input_digest": digest = AnswerJson.string(reader); break;
                case "revision": revision = AnswerJson.integer(reader); break;
                case "analysis_stage": stage = AnswerJson.string(reader); break;
                case "available_stage": available = AnswerJson.string(reader); break;
                case "retake":
                    reader.beginArray();
                    while (reader.hasNext()) {
                        long page = AnswerJson.integer(reader);
                        if (retake.size() >= 100 || page < 1 || page > 1000) throw new JSONException("invalid retake page");
                        retake.add((int) page);
                    }
                    reader.endArray();
                    break;
                case "comparing": comparing = AnswerJson.flag(reader); break;
                case "items":
                    items = new ArrayList<>();
                    reader.beginArray();
                    while (reader.hasNext()) {
                        if (items.size() >= 2000) throw new JSONException("too many answers");
                        JSONObject item = AnswerJson.item(reader);
                        AnswerItem answer = new AnswerItem(string(item, "group_id"), string(item, "group_label"),
                                string(item, "question_id"), string(item, "question_label"), string(item, "answer"),
                                AnswerItem.Status.valueOf(string(item, "status").toUpperCase(Locale.ROOT)),
                                string(item, "issue"), AnswerDiagram.parse(item.has("diagrams")
                                        ? item.getJSONArray("diagrams") : null), answerNumbers(item),
                                item.has("other") ? string(item, "other") : "", item.has("seen") && flag(item, "seen"),
                                item.has("uncertain") && flag(item, "uncertain"));
                        characters += answer.answer.length() + answer.issue.length();
                        if (characters > MAX_TEXT_CHARS) throw new IOException("answer text too large");
                        items.add(answer);
                    }
                    reader.endArray();
                    break;
                default: reader.skipValue();
            }
        }
        reader.endObject();
        if (schema != SCHEMA_VERSION && schema != 2 && schema != 3)
            throw new IllegalArgumentException("unsupported answer schema");
        return new AnswerBundle(session, digest, revision, items, stage, available, retake, comparing);
    }

    private static boolean flag(JSONObject object, String key) throws JSONException {
        Object value = object.get(key);
        if (!(value instanceof Boolean)) throw new JSONException("invalid flag: " + key);
        return (Boolean) value;
    }

    private static List<Integer> answerNumbers(JSONObject item) throws JSONException {
        List<Integer> numbers = new ArrayList<>();
        if (!item.has("answer_no")) return numbers;
        JSONArray array = item.getJSONArray("answer_no");
        for (int i = 0; i < array.length(); i++) {
            Object value = array.get(i);
            if (!(value instanceof Integer)) throw new JSONException("invalid answer number");
            numbers.add((Integer) value);
        }
        return numbers;
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
