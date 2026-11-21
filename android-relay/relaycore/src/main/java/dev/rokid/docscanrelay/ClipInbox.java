package dev.rokid.docscanrelay;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.util.Set;

/**
 * Clips the camera has finished, waiting for their page to be accepted.
 *
 * <p>A page reaches the controller as one JPEG frame, through the path every photo takes (review, save, upload).
 * The clip that frame was cut from is far too large for that path, so it waits here under the frame's capture id:
 * {@code <capture id>.mp4} and, once the clip is closed, {@code <capture id>.json}. The record is written last, so
 * a clip without one is still being written or was abandoned.</p>
 */
public final class ClipInbox {
    private static final String CAPTURE_ID = "[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}";
    private final File directory;

    public ClipInbox(File directory) {
        this.directory = directory;
    }

    /** Where the camera writes the clip of this capture. */
    public synchronized File reserve(String captureId) throws IOException {
        Files.createDirectories(directory.toPath());
        return clip(captureId);
    }

    /** The clip is closed and whole: its record makes it available. */
    public synchronized void offer(String captureId, byte[] record) throws IOException {
        File clip = clip(captureId);
        if (!clip.isFile() || clip.length() == 0 || record == null || record.length == 0) {
            throw new IOException("録画が保存されていません");
        }
        File temporary = new File(directory, captureId + ".json.tmp");
        try (FileOutputStream stream = new FileOutputStream(temporary)) {
            stream.write(record);
            stream.getFD().sync();
        }
        CaptureReviewPersistence.moveReplacing(temporary, record(captureId));
    }

    public synchronized boolean has(String captureId) {
        try {
            return clip(captureId).isFile() && record(captureId).isFile();
        } catch (IOException invalid) {
            return false;
        }
    }

    /** A retake or a photo that was never shown leaves its clip behind; nothing else would ever remove it. */
    public synchronized void discardExcept(Set<String> captureIds) {
        File[] files = directory.listFiles();
        if (files == null) return;
        for (File file : files) {
            String name = file.getName();
            int dot = name.indexOf('.');
            if (dot < 0 || !captureIds.contains(name.substring(0, dot))) file.delete();
        }
    }

    File clip(String captureId) throws IOException {
        return new File(directory, checked(captureId) + ".mp4");
    }

    File record(String captureId) throws IOException {
        return new File(directory, checked(captureId) + ".json");
    }

    private static String checked(String captureId) throws IOException {
        if (captureId == null || !captureId.matches(CAPTURE_ID)) throw new IOException("撮影の番号が不正です");
        return captureId;
    }
}
