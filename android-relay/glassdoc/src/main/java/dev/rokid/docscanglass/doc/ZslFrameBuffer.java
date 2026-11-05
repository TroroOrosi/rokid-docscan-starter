package dev.rokid.docscanglass.doc;

import android.hardware.camera2.CaptureResult;
import android.hardware.camera2.TotalCaptureResult;
import android.media.Image;
import java.util.TreeMap;
import java.util.function.Predicate;

/** Native owners only; no full-resolution Java pixel copies. One instance per camera session. */
final class ZslFrameBuffer implements AutoCloseable {
    static final int RING_IMAGES = 3;
    // Three rolling owners, one selected/worker owner and acquireLatest's two-image headroom.
    static final int READER_IMAGES = RING_IMAGES + 1 + 2;
    static final class Selection {
        final Image image;
        final TotalCaptureResult result;
        final long timestamp;
        Selection(Image image, TotalCaptureResult result, long timestamp) {
            this.image = image; this.result = result; this.timestamp = timestamp;
        }
    }
    private final TreeMap<Long, Image> images = new TreeMap<>();
    private final TreeMap<Long, TotalCaptureResult> results = new TreeMap<>();

    /** Consumes ownership even if timestamp extraction or map allocation fails. */
    void image(Image image) {
        boolean retained = false;
        try {
            long timestamp = image.getTimestamp();
            if (timestamp <= 0) return;
            Image previous = images.put(timestamp, image);
            retained = true;
            if (previous != null) previous.close();
            while (images.size() > RING_IMAGES) images.pollFirstEntry().getValue().close();
        } finally {
            if (!retained) image.close();
        }
    }
    void result(TotalCaptureResult result) {
        Long timestamp = result.get(CaptureResult.SENSOR_TIMESTAMP);
        if (timestamp == null || timestamp <= 0) return;
        results.put(timestamp, result);
        while (results.size() > READER_IMAGES) results.pollFirstEntry();
    }
    Selection latest(long minimum, long maximum, Predicate<TotalCaptureResult> eligible) {
        for (var entry : images.descendingMap().entrySet()) {
            long timestamp = entry.getKey();
            if (timestamp < minimum || timestamp > maximum) continue;
            TotalCaptureResult result = results.get(timestamp);
            if (result != null && eligible.test(result)) return new Selection(entry.getValue(), result, timestamp);
        }
        return null;
    }
    Selection take(Selection selection) {
        if (selection == null || images.get(selection.timestamp) != selection.image
                || results.get(selection.timestamp) != selection.result) return null;
        images.remove(selection.timestamp); results.remove(selection.timestamp);
        return selection;
    }
    int size() { return images.size(); }
    @Override public void close() {
        Throwable failure = null;
        for (Image image : images.values()) {
            try { image.close(); } catch (RuntimeException | OutOfMemoryError error) { failure = error; }
        }
        images.clear(); results.clear();
        if (failure instanceof RuntimeException error) throw error;
        if (failure instanceof OutOfMemoryError error) throw error;
    }
}
