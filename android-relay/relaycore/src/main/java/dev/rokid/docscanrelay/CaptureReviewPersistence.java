package dev.rokid.docscanrelay;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.EOFException;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/** Atomically persists one unregistered capture across activity/process restarts. */
final class CaptureReviewPersistence {
    private static final int MAGIC = 0x44534350; // DSCP
    /** 3 adds the glasses' shutter-request epoch; old records retain unknown (0). */
    private static final int VERSION = 3;
    private static final int COMMIT_MAGIC = 0x44534343; // DSCC
    private static final int COMMIT_VERSION = 1;
    private static final int SHA_256_BYTES = 32;
    private static final int MAX_TEXT_BYTES = 4 * 1024 * 1024;
    private static final int MAX_FAILURE_BYTES = 64 * 1024;
    private static final int MAX_FRAMING_BYTES = 256;
    private static final int MAX_JPEG_BYTES = 8 * 1024 * 1024;

    private final File file;
    private final File temporaryFile;
    private final File commitMarkerFile;
    private final File commitMarkerTemporaryFile;
    private int recoveredCommittedPageIndex = -1;

    CaptureReviewPersistence(File file) {
        if (file.getParentFile() == null) {
            throw new IllegalArgumentException("pending capture file needs a parent directory");
        }
        this.file = file;
        temporaryFile = new File(file.getParentFile(), file.getName() + ".tmp");
        commitMarkerFile = new File(file.getParentFile(), file.getName() + ".committed");
        commitMarkerTemporaryFile =
                new File(file.getParentFile(), file.getName() + ".committed.tmp");
    }

    synchronized void save(CaptureReviewStore.Pending pending) throws IOException {
        // Reject malformed candidates BEFORE touching the last recoverable original.
        if (pending == null || pending.pageIndex < 0 || pending.rotationDegrees < 0
                || pending.rotationDegrees >= 360 || pending.rotationDegrees % 90 != 0
                || pending.capturedAtMillis < 0 || pending.jpeg == null
                || pending.jpeg.length == 0 || pending.jpeg.length > MAX_JPEG_BYTES) {
            throw new IOException("invalid pending capture payload");
        }
        byte[] text = pending.ocrText.getBytes(StandardCharsets.UTF_8);
        byte[] failure = pending.ocrFailure.getBytes(StandardCharsets.UTF_8);
        byte[] framing = pending.framing.toToken().getBytes(StandardCharsets.UTF_8);
        if (text.length > MAX_TEXT_BYTES || failure.length > MAX_FAILURE_BYTES
                || framing.length > MAX_FRAMING_BYTES) {
            throw new IOException("pending capture field is too large");
        }
        File parent = file.getParentFile();
        if (parent == null || (!parent.isDirectory() && !parent.mkdirs())) {
            throw new IOException("pending capture directory is unavailable");
        }
        try (FileOutputStream output = new FileOutputStream(temporaryFile);
             DataOutputStream data = new DataOutputStream(new BufferedOutputStream(output))) {
            data.writeInt(MAGIC);
            data.writeInt(VERSION);
            data.writeInt(pending.pageIndex);
            data.writeInt(pending.rotationDegrees);
            writeBytes(data, text);
            writeBytes(data, failure);
            writeBytes(data, framing);
            writeBytes(data, pending.jpeg);
            data.writeLong(pending.capturedAtMillis);
            data.flush();
            output.getFD().sync();
        }
        moveReplacing(temporaryFile, file);
    }

    synchronized void markCommitted(CaptureReviewStore.Pending pending) throws IOException {
        if (pending.pageIndex < 0 || pending.jpeg == null || pending.jpeg.length == 0) {
            throw new IOException("invalid committed capture");
        }
        File parent = commitMarkerFile.getParentFile();
        if (parent == null || (!parent.isDirectory() && !parent.mkdirs())) {
            throw new IOException("pending capture directory is unavailable");
        }
        byte[] jpegSha256 = sha256(pending.jpeg);
        try (FileOutputStream output = new FileOutputStream(commitMarkerTemporaryFile);
             DataOutputStream data = new DataOutputStream(new BufferedOutputStream(output))) {
            data.writeInt(COMMIT_MAGIC);
            data.writeInt(COMMIT_VERSION);
            data.writeInt(pending.pageIndex);
            data.write(jpegSha256);
            data.flush();
            output.getFD().sync();
        }
        moveReplacing(commitMarkerTemporaryFile, commitMarkerFile);
    }

    synchronized CaptureReviewStore.Pending loadOrNull() {
        if (!file.isFile()) {
            clearCommitMarkerQuietly();
            return null;
        }
        CaptureReviewStore.Pending pending;
        try {
            pending = readPending();
        } catch (IOException | RuntimeException invalid) {
            try {
                clear();
            } catch (IOException ignored) {
                // Frozen relay recovery: invalid pending records are not uploaded.
            }
            return null;
        }
        CommitMarker marker = loadCommitMarkerOrNull();
        if (marker == null) {
            return pending;
        }
        if (marker.pageIndex == pending.pageIndex
                && MessageDigest.isEqual(marker.jpegSha256, sha256(pending.jpeg))) {
            recoveredCommittedPageIndex = marker.pageIndex;
            try {
                clearAfterCommit();
            } catch (IOException ignored) {
                // Keep the matching marker so a later restart still suppresses this upload.
            }
            return null;
        }
        clearCommitMarkerQuietly();
        return pending;
    }

    /** Read a retained image without deleting it or consuming acknowledgement markers. */
    synchronized CaptureReviewStore.Pending readPending() throws IOException {
        return readRecord(null);
    }

    /** Validate and compare a retained record without allocating a second full JPEG. */
    synchronized boolean matches(CaptureReviewStore.Pending expected) throws IOException {
        if (expected == null || expected.jpeg == null) return false;
        CaptureReviewStore.Pending stored = readRecord(expected.jpeg);
        return stored != null && stored.pageIndex == expected.pageIndex
                && stored.rotationDegrees == expected.rotationDegrees
                && stored.capturedAtMillis == expected.capturedAtMillis
                && stored.ocrText.equals(expected.ocrText)
                && stored.ocrFailure.equals(expected.ocrFailure)
                && stored.framing.toToken().equals(expected.framing.toToken());
    }

    private CaptureReviewStore.Pending readRecord(byte[] expectedJpeg) throws IOException {
        try (DataInputStream data = new DataInputStream(
                new BufferedInputStream(new FileInputStream(file)))) {
            if (data.readInt() != MAGIC) {
                throw new IOException("unsupported pending capture format");
            }
            // Version 1 predates the framing check. Its photo is still valid
            // and must survive the upgrade; it simply carries no verdict.
            int recordVersion = data.readInt();
            if (recordVersion < 1 || recordVersion > VERSION) {
                throw new IOException("unsupported pending capture format");
            }
            int pageIndex = data.readInt();
            int rotationDegrees = data.readInt();
            if (pageIndex < 0
                    || rotationDegrees < 0
                    || rotationDegrees >= 360
                    || rotationDegrees % 90 != 0) {
                throw new IOException("invalid pending capture metadata");
            }
            String ocrText = new String(
                    readBytes(data, MAX_TEXT_BYTES), StandardCharsets.UTF_8);
            String ocrFailure = new String(
                    readBytes(data, MAX_FAILURE_BYTES), StandardCharsets.UTF_8);
            PageFraming framing = recordVersion == 1
                    ? PageFraming.UNKNOWN
                    : PageFraming.fromToken(new String(
                            readBytes(data, MAX_FRAMING_BYTES),
                            StandardCharsets.UTF_8));
            int jpegLength = readLength(data, MAX_JPEG_BYTES);
            if (jpegLength == 0) throw new IOException("invalid pending capture payload");
            byte[] jpeg;
            if (expectedJpeg == null) {
                jpeg = new byte[jpegLength];
                data.readFully(jpeg);
            } else {
                // Even a mismatch must consume/validate the entire record: a corrupt
                // tail must not silently look like an ordinary different revision.
                boolean same = jpegLength == expectedJpeg.length;
                byte[] buffer = new byte[Math.min(8192, jpegLength)];
                for (int offset = 0; offset < jpegLength;) {
                    int count = Math.min(buffer.length, jpegLength - offset);
                    data.readFully(buffer, 0, count);
                    if (same) {
                        for (int i = 0; i < count; i++) {
                            if (buffer[i] != expectedJpeg[offset + i]) { same = false; break; }
                        }
                    }
                    offset += count;
                }
                jpeg = same ? expectedJpeg : null;
            }
            long capturedAt = recordVersion >= 3 ? data.readLong() : 0;
            if (capturedAt < 0 || data.read() != -1) {
                throw new IOException("invalid pending capture payload");
            }
            if (jpeg == null) return null;
            return new CaptureReviewStore.Pending(
                    pageIndex, jpeg, ocrText, rotationDegrees, ocrFailure, framing, capturedAt);
        }
    }

    synchronized int consumeRecoveredCommittedPageIndex() {
        int recovered = recoveredCommittedPageIndex;
        recoveredCommittedPageIndex = -1;
        return recovered;
    }

    synchronized void clearAfterCommit() throws IOException {
        deleteAll(temporaryFile, file);
        deleteAll(commitMarkerTemporaryFile, commitMarkerFile);
    }

    synchronized void clear() throws IOException {
        deleteAll(temporaryFile, file, commitMarkerTemporaryFile, commitMarkerFile);
    }

    private static void writeBytes(DataOutputStream data, byte[] value) throws IOException {
        data.writeInt(value.length);
        data.write(value);
    }

    private static byte[] readBytes(DataInputStream data, int maximum) throws IOException {
        byte[] value = new byte[readLength(data, maximum)];
        data.readFully(value);
        return value;
    }

    private static int readLength(DataInputStream data, int maximum) throws IOException {
        int length;
        try {
            length = data.readInt();
        } catch (EOFException error) {
            throw new IOException("truncated pending capture", error);
        }
        if (length < 0 || length > maximum) {
            throw new IOException("pending capture field is too large: " + length);
        }
        return length;
    }

    private CommitMarker loadCommitMarkerOrNull() {
        try {
            Files.deleteIfExists(commitMarkerTemporaryFile.toPath());
        } catch (IOException ignored) {
            // A complete marker, if present, is still authoritative.
        }
        if (!commitMarkerFile.isFile()) {
            return null;
        }
        try (DataInputStream data = new DataInputStream(
                new BufferedInputStream(new FileInputStream(commitMarkerFile)))) {
            if (data.readInt() != COMMIT_MAGIC || data.readInt() != COMMIT_VERSION) {
                throw new IOException("unsupported commit marker format");
            }
            int pageIndex = data.readInt();
            if (pageIndex < 0) {
                throw new IOException("invalid committed page index");
            }
            byte[] jpegSha256 = new byte[SHA_256_BYTES];
            data.readFully(jpegSha256);
            if (data.read() != -1) {
                throw new IOException("invalid commit marker payload");
            }
            return new CommitMarker(pageIndex, jpegSha256);
        } catch (IOException | RuntimeException invalid) {
            clearCommitMarkerQuietly();
            return null;
        }
    }

    private void clearCommitMarkerQuietly() {
        try {
            Files.deleteIfExists(commitMarkerTemporaryFile.toPath());
        } catch (IOException ignored) {
            // Best effort: a mismatched marker never suppresses the pending capture.
        }
        try {
            Files.deleteIfExists(commitMarkerFile.toPath());
        } catch (IOException ignored) {
            // Best effort: a mismatched marker never suppresses the pending capture.
        }
    }

    private static byte[] sha256(byte[] value) {
        try {
            return MessageDigest.getInstance("SHA-256").digest(value);
        } catch (NoSuchAlgorithmException error) {
            throw new IllegalStateException("SHA-256 is unavailable", error);
        }
    }

    static void moveReplacing(File source, File target) throws IOException {
        try {
            Files.move(
                    source.toPath(),
                    target.toPath(),
                    StandardCopyOption.ATOMIC_MOVE,
                    StandardCopyOption.REPLACE_EXISTING);
        } catch (AtomicMoveNotSupportedException ignored) {
            Files.move(
                    source.toPath(),
                    target.toPath(),
                    StandardCopyOption.REPLACE_EXISTING);
        }
    }

    private static void deleteAll(File... targets) throws IOException {
        IOException failure = null;
        for (File target : targets) {
            try {
                Files.deleteIfExists(target.toPath());
            } catch (IOException error) {
                if (failure == null) {
                    failure = error;
                } else {
                    failure.addSuppressed(error);
                }
            }
        }
        if (failure != null) {
            throw failure;
        }
    }

    private static final class CommitMarker {
        final int pageIndex;
        final byte[] jpegSha256;

        CommitMarker(int pageIndex, byte[] jpegSha256) {
            this.pageIndex = pageIndex;
            this.jpegSha256 = jpegSha256;
        }
    }
}
