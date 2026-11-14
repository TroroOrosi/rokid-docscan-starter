package dev.rokid.docscanrelay.study;

import android.util.JsonReader;
import android.util.JsonToken;
import android.util.JsonWriter;
import java.io.FilterInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.io.OutputStreamWriter;
import java.io.Reader;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.Iterator;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Bounded UTF-8 streams shared by the network snapshot and its atomic offline save. */
final class AnswerJson {
    private AnswerJson() {}

    static JsonReader reader(InputStream source, int limit) {
        InputStream bounded = new FilterInputStream(source) {
            private int remaining = limit;

            @Override public int read() throws IOException {
                int value = super.read();
                if (value != -1 && remaining-- == 0) throw new IOException("answer JSON too large");
                return value;
            }

            @Override public int read(byte[] bytes, int offset, int length) throws IOException {
                int count = in.read(bytes, offset, Math.min(length, remaining + 1));
                if (count > remaining) throw new IOException("answer JSON too large");
                if (count > 0) remaining -= count;
                return count;
            }
        };
        Reader utf8 = new InputStreamReader(bounded, StandardCharsets.UTF_8.newDecoder()
                .onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT));
        // Bound tokens while JsonReader is filling a string, before nextString can
        // allocate an oversized value. Escaped characters count as decoded UTF-16.
        Reader tokens = new Reader() {
            private boolean quoted;
            private boolean escaped;
            private int unicodeDigits;
            private int characters;
            private int literalCharacters;
            private int nesting;

            @Override public int read(char[] buffer, int offset, int length) throws IOException {
                int count = utf8.read(buffer, offset, length);
                for (int i = offset; i < offset + count; i++) {
                    char value = buffer[i];
                    if (quoted) {
                        if (unicodeDigits > 0) {
                            unicodeDigits--;
                        } else if (escaped) {
                            escaped = false;
                            if (value == 'u') unicodeDigits = 4;
                            characters++;
                        } else if (value == '\\') {
                            escaped = true;
                        } else if (value == '"') {
                            quoted = false;
                        } else {
                            characters++;
                        }
                        if (characters > AnswerBundle.MAX_TEXT_CHARS)
                            throw new IOException("answer string too large");
                    } else if (value == '"') {
                        quoted = true;
                        characters = 0;
                        literalCharacters = 0;
                    } else if (value == '{' || value == '[') {
                        if (++nesting > 16) throw new IOException("answer JSON nesting too deep");
                        literalCharacters = 0;
                    } else if (value == '}' || value == ']') {
                        nesting--;
                        literalCharacters = 0;
                    } else if (" \t\r\n,:".indexOf(value) >= 0) {
                        literalCharacters = 0;
                    } else if (++literalCharacters > 128) {
                        throw new IOException("answer scalar too large");
                    }
                }
                return count;
            }

            @Override public void close() throws IOException { utf8.close(); }
        };
        return new JsonReader(tokens);
    }

    /** A null destination counts the canonical wire bytes without retaining them. */
    static JsonWriter writer(OutputStream destination, int limit) {
        OutputStream bounded = new OutputStream() {
            private int remaining = limit;

            @Override public void write(int value) throws IOException {
                if (remaining-- == 0) throw new IOException("answer JSON too large");
                if (destination != null) destination.write(value);
            }

            @Override public void write(byte[] bytes, int offset, int length) throws IOException {
                if (length > remaining) throw new IOException("answer JSON too large");
                remaining -= length;
                if (destination != null) destination.write(bytes, offset, length);
            }

            @Override public void flush() throws IOException {
                if (destination != null) destination.flush();
            }
        };
        return new JsonWriter(new OutputStreamWriter(bounded, StandardCharsets.UTF_8));
    }

    static String string(JsonReader reader) throws IOException {
        if (reader.peek() != JsonToken.STRING) throw new IOException("invalid answer string");
        return reader.nextString();
    }

    static long integer(JsonReader reader) throws IOException {
        if (reader.peek() != JsonToken.NUMBER) throw new IOException("invalid answer integer");
        String value = reader.nextString();
        if (!value.matches("-?(0|[1-9][0-9]*)")) throw new IOException("invalid answer integer");
        try { return Long.parseLong(value); }
        catch (NumberFormatException invalid) { throw new IOException("invalid answer integer", invalid); }
    }

    static void endDocument(JsonReader reader) throws IOException {
        if (reader.peek() != JsonToken.END_DOCUMENT) throw new IOException("trailing answer JSON");
    }

    /** Only one item is materialized at a time, never a second whole-booklet tree. */
    static JSONObject item(JsonReader reader) throws IOException, JSONException {
        Object value = value(reader, 0, new int[]{400_000});
        if (!(value instanceof JSONObject)) throw new JSONException("invalid answer item");
        return (JSONObject) value;
    }

    private static Object value(JsonReader reader, int depth, int[] remaining) throws IOException, JSONException {
        if (depth > 10 || --remaining[0] < 0) throw new IOException("answer item nesting too large");
        switch (reader.peek()) {
            case BEGIN_OBJECT:
                JSONObject object = new JSONObject();
                reader.beginObject();
                while (reader.hasNext()) {
                    String name = reader.nextName();
                    if (object.length() >= 32 || object.has(name)) throw new IOException("invalid answer fields");
                    object.put(name, value(reader, depth + 1, remaining));
                }
                reader.endObject();
                return object;
            case BEGIN_ARRAY:
                JSONArray array = new JSONArray();
                reader.beginArray();
                while (reader.hasNext()) {
                    if (array.length() >= 1000) throw new IOException("answer array too large");
                    array.put(value(reader, depth + 1, remaining));
                }
                reader.endArray();
                return array;
            case STRING: return reader.nextString();
            case BOOLEAN: return reader.nextBoolean();
            case NULL:
                reader.nextNull();
                return JSONObject.NULL;
            case NUMBER:
                String number = reader.nextString();
                try {
                    if (number.matches("-?(0|[1-9][0-9]*)")) {
                        long integer = Long.parseLong(number);
                        if (integer >= Integer.MIN_VALUE && integer <= Integer.MAX_VALUE) return (int) integer;
                        return integer;
                    }
                    double decimal = Double.parseDouble(number);
                    if (!Double.isFinite(decimal)) throw new NumberFormatException("nonfinite number");
                    return decimal;
                } catch (NumberFormatException invalid) {
                    throw new IOException("invalid answer number", invalid);
                }
            default: throw new IOException("invalid answer value");
        }
    }

    static void writeValue(JsonWriter writer, Object value) throws IOException, JSONException {
        if (value instanceof JSONObject) {
            JSONObject object = (JSONObject) value;
            writer.beginObject();
            Iterator<String> names = object.keys();
            while (names.hasNext()) {
                String name = names.next();
                writer.name(name);
                writeValue(writer, object.get(name));
            }
            writer.endObject();
        } else if (value instanceof JSONArray) {
            JSONArray array = (JSONArray) value;
            writer.beginArray();
            for (int i = 0; i < array.length(); i++) writeValue(writer, array.get(i));
            writer.endArray();
        } else if (value instanceof String) {
            writer.value((String) value);
        } else if (value instanceof Number) {
            writer.value((Number) value);
        } else if (value instanceof Boolean) {
            writer.value((Boolean) value);
        } else if (value == JSONObject.NULL) {
            writer.nullValue();
        } else {
            throw new JSONException("invalid answer value");
        }
    }
}
