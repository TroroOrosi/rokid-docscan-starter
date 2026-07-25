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
    private static final int VERSION = 1;
    private static final int COMMIT_MAGIC = 0x44534343; // DSCC
    private static final int COMMIT_VERSION = 1;
    private static final int SHA_256_BYTES = 32;
    private static final int MAX_TEXT_BYTES = 4 * 1024 * 1024;
    private static final int MAX_FAILURE_BYTES = 64 * 1024;
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
            writeBytes(data, pending.ocrText.getBytes(StandardCharsets.UTF_8));
            writeBytes(data, pending.ocrFailure.getBytes(StandardCharsets.UTF_8));
            writeBytes(data, pending.jpeg);
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
        try (DataInputStream data = new DataInputStream(
                new BufferedInputStream(new FileInputStream(file)))) {
            if (data.readInt() != MAGIC || data.readInt() != VERSION) {
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
            byte[] jpeg = readBytes(data, MAX_JPEG_BYTES);
            if (jpeg.length == 0 || data.read() != -1) {
                throw new IOException("invalid pending capture payload");
            }
            pending = new CaptureReviewStore.Pending(
                    pageIndex, jpeg, ocrText, rotationDegrees, ocrFailure);
        } catch (IOException | RuntimeException invalid) {
            try {
                clear();
            } catch (IOException ignored) {
                // A stale file still cannot be auto-uploaded; load remains fail-closed.
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
        int length;
        try {
            length = data.readInt();
        } catch (EOFException error) {
            throw new IOException("truncated pending capture", error);
        }
        if (length < 0 || length > maximum) {
            throw new IOException("pending capture field is too large: " + length);
        }
        byte[] value = new byte[length];
        data.readFully(value);
        return value;
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

    private static void moveReplacing(File source, File target) throws IOException {
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
