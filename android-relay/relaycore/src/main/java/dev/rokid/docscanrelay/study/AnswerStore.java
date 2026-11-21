package dev.rokid.docscanrelay.study;

import android.util.AtomicFile;
import android.util.JsonReader;
import android.util.JsonToken;
import android.util.JsonWriter;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileNotFoundException;
import java.io.FileOutputStream;
import java.io.IOException;
import java.util.HashSet;
import java.util.Set;
import java.util.function.BooleanSupplier;
import org.json.JSONException;

/** Durable last-reader state. Closing is saved before the UI returns to mode selection. */
public final class AnswerStore {
    private final File directory;
    private final AtomicFile file;

    public static final class Saved {
        public final AnswerBundle bundle;
        public final String questionId;
        public final int offset;
        public final boolean closed;

        private Saved(AnswerBundle bundle, String questionId, int offset, boolean closed) {
            boolean found = false;
            for (AnswerItem item : bundle.items) if (item.questionId.equals(questionId)) found = true;
            if (!found || offset < 0 || offset > AnswerBundle.MAX_JSON_BYTES)
                throw new IllegalArgumentException("invalid reader cursor");
            this.bundle = bundle;
            this.questionId = questionId;
            this.offset = offset;
            this.closed = closed;
        }
    }

    public AnswerStore(File directory) {
        this.directory = directory;
        this.file = new AtomicFile(new File(directory, "answer-reader.json"));
    }

    /** Explicitly accepts the first result for a newly selected input/session. */
    public synchronized void start(AnswerBundle bundle) throws IOException {
        write(new Saved(bundle, bundle.items.get(0).questionId, 0, false));
    }

    public synchronized void save(AnswerBundle bundle, String questionId, int offset, boolean closed)
            throws IOException {
        Saved old = load();
        if (old == null || !old.bundle.sessionId.equals(bundle.sessionId)
                || !old.bundle.inputDigest.equals(bundle.inputDigest)
                || old.bundle.revision > bundle.revision || (old.closed && !closed)) {
            throw new IOException("reader state is stale or closed");
        }
        write(new Saved(bundle, questionId, offset, closed));
    }

    /** Only a user-requested resume is allowed to clear CLOSED. */
    public synchronized Saved resume() throws IOException {
        return resume(() -> true);
    }

    public synchronized Saved resume(BooleanSupplier isCurrent) throws IOException {
        requireCurrentResume(isCurrent);
        Saved old = load();
        requireCurrentResume(isCurrent);
        if (old == null) return null;
        Saved resumed = new Saved(old.bundle, old.questionId, old.offset, false);
        write(resumed, isCurrent);
        return resumed;
    }

    private static void requireCurrentResume(BooleanSupplier isCurrent) throws IOException {
        if (!isCurrent.getAsBoolean()) throw new IOException("reader resume no longer active");
    }

    public synchronized Saved load() throws IOException {
        try (FileInputStream input = file.openRead()) {
            JsonReader reader = AnswerJson.reader(input, AnswerBundle.MAX_JSON_BYTES + 4096);
            AnswerBundle bundle = null;
            String question = null;
            int offset = -1;
            Boolean closed = null;
            Set<String> fields = new HashSet<>();
            reader.beginObject();
            while (reader.hasNext()) {
                String name = reader.nextName();
                if (fields.size() >= 32 || !fields.add(name)) throw new IOException("invalid reader fields");
                switch (name) {
                    case "bundle": bundle = AnswerBundle.readJson(reader); break;
                    case "question_id": question = AnswerJson.string(reader); break;
                    case "offset": offset = Math.toIntExact(AnswerJson.integer(reader)); break;
                    case "closed":
                        if (reader.peek() != JsonToken.BOOLEAN) throw new IOException("invalid completion state");
                        closed = reader.nextBoolean();
                        break;
                    default: reader.skipValue();
                }
            }
            reader.endObject();
            AnswerJson.endDocument(reader);
            if (bundle == null || closed == null) throw new IOException("incomplete reader state");
            return new Saved(bundle, question, offset, closed);
        } catch (FileNotFoundException absent) {
            return null;
        } catch (JSONException | IllegalArgumentException | ArithmeticException | IllegalStateException invalid) {
            throw new IOException("saved reader state is invalid", invalid);
        }
    }

    private void write(Saved saved) throws IOException {
        write(saved, () -> true);
    }

    private void write(Saved saved, BooleanSupplier isCurrent) throws IOException {
        if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("reader storage unavailable");
        try { saved.bundle.checkSerializedSize(); }
        catch (JSONException invalid) { throw new IOException("reader state cannot be saved", invalid); }
        FileOutputStream output = null;
        try {
            output = file.startWrite();
            JsonWriter writer = AnswerJson.writer(output, AnswerBundle.MAX_JSON_BYTES + 4096);
            writer.beginObject().name("bundle");
            saved.bundle.writeJson(writer);
            writer.name("question_id").value(saved.questionId).name("offset").value(saved.offset)
                    .name("closed").value(saved.closed).endObject();
            writer.flush();
            output.getFD().sync();
            requireCurrentResume(isCurrent);
            file.finishWrite(output);
        } catch (IOException failure) {
            file.failWrite(output);
            throw failure;
        } catch (JSONException | IllegalArgumentException invalid) {
            file.failWrite(output);
            throw new IOException("reader state cannot be saved", invalid);
        }
    }
}
