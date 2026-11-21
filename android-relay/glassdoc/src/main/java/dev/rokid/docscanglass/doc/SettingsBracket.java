package dev.rokid.docscanglass.doc;

import android.hardware.camera2.CaptureRequest;
import android.util.Log;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.json.JSONObject;

/**
 * Explicit comparison only ({@code settings_bracket=true}, never persisted): after an ordinary
 * still, the same scene is taken again with one setting changed per still, so one look at one
 * sheet answers what only the glasses can (2026-11-10 plan: sensitivity steps and clipping, the
 * gain of a second flicker period against its blur, noise reduction and edge modes, JPEG quality).
 *
 * <p>The extra stills are kept under the app's private {@code files/settings-bracket/} with a
 * journal of what was requested and what the camera reported. They are never pages: nothing here
 * is reviewed, registered or uploaded. A file is written before the next still is requested.</p>
 */
final class SettingsBracket {
    private static final String TAG = "DocScanGlassDoc";
    /** Usual, farther, nearer and one spare: a bound on storage, not a statistic. */
    static final int MAX_SETS = 4;
    static final long MIN_FREE_BYTES = 256L << 20;
    static final long SET_DEADLINE_MILLIS = 30_000;

    /** One still. A null field keeps what the ordinary still uses. */
    static final class Variant {
        final String name;
        final int periods, evSteps;
        final Integer noiseReduction, edge, jpegQuality;
        Variant(String name, int periods, int evSteps, Integer noiseReduction, Integer edge, Integer jpegQuality) {
            this.name = name; this.periods = periods; this.evSteps = evSteps;
            this.noiseReduction = noiseReduction; this.edge = edge; this.jpegQuality = jpegQuality;
        }
        void apply(CaptureRequest.Builder request) {
            if (noiseReduction != null) request.set(CaptureRequest.NOISE_REDUCTION_MODE, noiseReduction);
            if (edge != null) request.set(CaptureRequest.EDGE_MODE, edge);
            if (jpegQuality != null) request.set(CaptureRequest.JPEG_QUALITY, (byte)(int)jpegQuality);
        }
    }

    /** Processing variants are offered only where the camera lists both modes. */
    static List<Variant> variants(int[] noiseModes, int[] edgeModes) {
        List<Variant> list = new ArrayList<>();
        list.add(new Variant("ev+1", 1, 1, null, null, null));
        list.add(new Variant("ev+2", 1, 2, null, null, null));
        list.add(new Variant("two-periods", 2, 0, null, null, null));
        for (int mode : new int[]{CaptureRequest.NOISE_REDUCTION_MODE_OFF, CaptureRequest.NOISE_REDUCTION_MODE_HIGH_QUALITY}) {
            // OFF and HIGH_QUALITY share their numbers between the two keys (0 and 2).
            if (contains(noiseModes, mode) && contains(edgeModes, mode))
                list.add(new Variant(mode == CaptureRequest.NOISE_REDUCTION_MODE_OFF ? "nr-off-edge-off" : "nr-hq-edge-hq",
                        1, 0, mode, mode, null));
        }
        list.add(new Variant("jpeg-90", 1, 0, null, null, 90));
        return list;
    }

    private static boolean contains(int[] modes, int mode) {
        if (modes != null) for (int value : modes) if (value == mode) return true;
        return false;
    }

    private final File directory;
    private List<Variant> variants = List.of();
    private int sets, index;
    private long scene;
    private boolean running;

    SettingsBracket(File files, String run) {
        directory = new File(new File(files, "settings-bracket"), run);
    }

    boolean running() { return running; }
    long scene() { return scene; }
    Variant peek() { return running && index < variants.size() ? variants.get(index) : null; }

    /** Starts one set after an ordinary still; false when the bound or the storage says no. */
    boolean begin(long scene, List<Variant> offered, Map<String, Object> base) {
        if (running) end("superseded_by_next_ordinary_still");
        String refusal = sets >= MAX_SETS ? "set_limit" : !directory.mkdirs() && !directory.isDirectory() ? "directory_unavailable"
                : directory.getUsableSpace() < MIN_FREE_BYTES ? "low_storage" : null;
        if (refusal != null) { line(Map.of("kind", "refused", "scene", scene, "reason", refusal)); return false; }
        sets++; index = 0; this.scene = scene; variants = offered; running = true;
        Map<String, Object> entry = new java.util.LinkedHashMap<>(base);
        entry.put("kind", "base"); entry.put("set", sets); entry.put("scene", scene);
        entry.put("note", "delivered to the ordinary session; find it there by sha256");
        return line(entry) || fail();
    }

    void skip(String reason) {
        Variant variant = peek();
        if (variant == null) return;
        line(Map.of("kind", "skipped", "set", sets, "index", index + 1, "name", variant.name, "reason", reason));
        index++;
    }

    /** Writes the still, then its journal line. A failed write ends the set: nothing is requested after it. */
    boolean saved(byte[] jpeg, Map<String, Object> details) {
        Variant variant = peek();
        if (variant == null) return false;
        String name = String.format(java.util.Locale.ROOT, "set%d-%02d-%s.jpg", sets, index + 1, variant.name);
        File target = new File(directory, name);
        try {
            if (!target.createNewFile()) throw new IOException("exists");
            try (FileOutputStream out = new FileOutputStream(target)) { out.write(jpeg); out.getFD().sync(); }
        } catch (IOException | RuntimeException error) {
            end("write_failed_" + error.getClass().getSimpleName());
            return false;
        }
        Map<String, Object> entry = new java.util.LinkedHashMap<>(details);
        entry.put("kind", "variant"); entry.put("set", sets); entry.put("scene", scene);
        entry.put("index", index + 1); entry.put("name", variant.name); entry.put("file", name);
        entry.put("bytes", jpeg.length); entry.put("auto_upload_allowed", false);
        index++;
        return line(entry) || fail();
    }

    void end(String reason) {
        if (!running) return;
        running = false;
        line(Map.of("kind", "end", "set", sets, "scene", scene, "taken", index, "of", variants.size(), "reason", reason));
        Log.i(TAG, "settings_bracket set=" + sets + " taken=" + index + "/" + variants.size() + " end=" + reason);
    }

    private boolean fail() { running = false; return false; }

    private boolean line(Map<String, Object> entry) {
        try (FileOutputStream out = new FileOutputStream(new File(directory, "journal.jsonl"), true)) {
            JSONObject json = new JSONObject();
            for (Map.Entry<String, Object> field : entry.entrySet())
                json.put(field.getKey(), field.getValue() instanceof Map ? new JSONObject((Map<?, ?>)field.getValue())
                        : field.getValue() == null ? JSONObject.NULL : field.getValue());
            out.write((json + "\n").getBytes(StandardCharsets.UTF_8)); out.getFD().sync();
            return true;
        } catch (IOException | org.json.JSONException | RuntimeException error) {
            Log.w(TAG, "settings_bracket journal " + error.getClass().getSimpleName());
            return false;
        }
    }
}
