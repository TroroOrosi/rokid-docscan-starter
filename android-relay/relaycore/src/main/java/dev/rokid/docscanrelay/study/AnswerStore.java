package dev.rokid.docscanrelay.study;

import android.util.AtomicFile;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileNotFoundException;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import org.json.JSONException;
import org.json.JSONObject;

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
            if (!found || offset < 0 || offset > 250_000) throw new IllegalArgumentException("invalid reader cursor");
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
        Saved old = load();
        if (old == null) return null;
        Saved resumed = new Saved(old.bundle, old.questionId, old.offset, false);
        write(resumed);
        return resumed;
    }

    public synchronized Saved load() throws IOException {
        try (FileInputStream input = file.openRead();
             ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
            byte[] chunk = new byte[8192];
            int count;
            while ((count = input.read(chunk)) != -1) {
                if (bytes.size() + count > AnswerBundle.MAX_JSON_BYTES + 4096) {
                    throw new IOException("saved reader state is too large");
                }
                bytes.write(chunk, 0, count);
            }
            JSONObject json = new JSONObject(new String(bytes.toByteArray(), StandardCharsets.UTF_8));
            if (!(json.get("closed") instanceof Boolean)) throw new JSONException("invalid completion state");
            return new Saved(AnswerBundle.fromJson(json.getJSONObject("bundle").toString()),
                    AnswerBundle.string(json, "question_id"),
                    Math.toIntExact(AnswerBundle.number(json, "offset")), json.getBoolean("closed"));
        } catch (FileNotFoundException absent) {
            return null;
        } catch (JSONException | IllegalArgumentException | ArithmeticException invalid) {
            throw new IOException("saved reader state is invalid", invalid);
        }
    }

    private void write(Saved saved) throws IOException {
        if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("reader storage unavailable");
        byte[] bytes;
        try {
            bytes = new JSONObject().put("bundle", new JSONObject(saved.bundle.toJson()))
                    .put("question_id", saved.questionId).put("offset", saved.offset)
                    .put("closed", saved.closed).toString().getBytes(StandardCharsets.UTF_8);
        } catch (JSONException | IllegalArgumentException invalid) {
            throw new IOException("reader state cannot be saved", invalid);
        }
        FileOutputStream output = null;
        try {
            output = file.startWrite();
            output.write(bytes);
            output.getFD().sync();
            file.finishWrite(output);
        } catch (IOException failure) {
            file.failWrite(output);
            throw failure;
        }
    }
}
