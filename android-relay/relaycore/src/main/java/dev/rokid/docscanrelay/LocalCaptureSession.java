package dev.rokid.docscanrelay;

import java.io.*;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Properties;
import java.util.UUID;

/** A glasses session exists before HTTP: immutable image revisions plus one atomic state file. */
final class LocalCaptureSession {
    enum Phase { CAPTURE, LISTENING, ANALYSIS, REVIEW, CLOSED }
    private final File directory;
    private Properties state;

    private LocalCaptureSession(File directory, Properties state) {
        this.directory = directory;
        this.state = state;
    }

    static LocalCaptureSession create(File root, String server, boolean listening) throws IOException {
        if (server == null || server.trim().isEmpty() || server.length() > 4096) throw new IOException("接続先が未設定です");
        File directory = new File(root, UUID.randomUUID().toString());
        Properties state = new Properties();
        state.setProperty("version", "1");
        state.setProperty("server", server);
        state.setProperty("listening", Boolean.toString(listening));
        state.setProperty("document", "0");
        state.setProperty("session", "0");
        state.setProperty("count", "0");
        state.setProperty("phase", Phase.CAPTURE.name());
        state.setProperty("resume_phase", Phase.CAPTURE.name());
        LocalCaptureSession result = new LocalCaptureSession(directory, state);
        result.save(state);
        return result;
    }

    static LocalCaptureSession load(File root, String id) throws IOException {
        if (id == null || !id.matches("[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}")) throw new IOException("記録IDが不正です");
        File directory = new File(root, id);
        File file = new File(directory, "state.properties");
        if (!file.isFile() || file.length() > 512 * 1024) throw new IOException("保存記録を読み出せません");
        Properties state = new Properties();
        try (InputStream input = new FileInputStream(file)) {
            state.load(input);
            if (!"1".equals(state.getProperty("version")) || state.getProperty("server", "").trim().isEmpty()
                    || !("true".equals(state.getProperty("listening")) || "false".equals(state.getProperty("listening")))) {
                throw new IOException("保存記録の形式が不正です");
            }
            LocalCaptureSession result = new LocalCaptureSession(directory, state);
            if (result.documentId() < 0 || result.sessionId() < 0 || result.pageCount() < 0 || result.pageCount() > 1000) {
                throw new IOException("保存記録の番号が不正です");
            }
            result.phase();
            Phase.valueOf(state.getProperty("resume_phase"));
            for (int index = 0; index < result.pageCount(); index++) result.page(index);
            return result;
        } catch (IllegalArgumentException | NullPointerException invalid) {
            throw new IOException("保存記録の形式が不正です");
        }
    }

    String id() { return directory.getName(); }
    File directory() { return directory; }
    synchronized String server() { return state.getProperty("server"); }
    synchronized boolean listening() { return Boolean.parseBoolean(state.getProperty("listening")); }
    synchronized int pageCount() { return Integer.parseInt(state.getProperty("count")); }
    synchronized long documentId() { return Long.parseLong(state.getProperty("document")); }
    synchronized long sessionId() { return Long.parseLong(state.getProperty("session")); }
    synchronized Phase phase() { return Phase.valueOf(state.getProperty("phase")); }
    synchronized boolean unfinished() {
        return (phase() == Phase.CLOSED ? Phase.valueOf(state.getProperty("resume_phase")) : phase()) != Phase.REVIEW;
    }

    synchronized void bindDocument(long id) throws IOException { bind("document", id); }
    synchronized void bindSession(long id) throws IOException { bind("session", id); }
    private void bind(String field, long id) throws IOException {
        long previous = Long.parseLong(state.getProperty(field));
        if (id <= 0 || (previous != 0 && previous != id)) throw new IOException("送信先の記録IDは変更できません");
        update(field, Long.toString(id));
    }

    synchronized void setPhase(Phase phase) throws IOException {
        if (phase == Phase.CLOSED || phase() == Phase.CLOSED) throw new IOException("明示的な終了・再開が必要です");
        update("phase", phase.name());
    }

    synchronized void close() throws IOException {
        if (phase() == Phase.CLOSED) return;
        Properties next = copy();
        next.setProperty("resume_phase", phase().name());
        next.setProperty("phase", Phase.CLOSED.name());
        save(next);
    }

    synchronized void resume() throws IOException {
        if (phase() == Phase.CLOSED) update("phase", state.getProperty("resume_phase"));
    }

    static final class Page {
        final int index;
        final String fileName;
        Page(int index, String fileName) { this.index = index; this.fileName = fileName; }
    }

    synchronized Page page(int index) throws IOException {
        String name = state.getProperty("page." + index, "");
        if (index < 0 || index >= pageCount() || !name.matches("p-" + index + "-[0-9a-f]{64}\\.bin")) {
            throw new IOException("保存ページの参照が不正です");
        }
        return new Page(index, name);
    }

    synchronized Page nextUnsent() throws IOException {
        for (int index = 0; index < pageCount(); index++) {
            Page page = page(index);
            if (!page.fileName.equals(state.getProperty("ack." + index))) return page;
        }
        return null;
    }

    synchronized void commit(CaptureReviewStore.Pending pending) throws IOException {
        if (phase() == Phase.CLOSED || pending.pageIndex < 0 || pending.pageIndex > pageCount()
                || pending.pageIndex >= 1000) throw new IOException("この状態では写真を保存できません");
        File incoming = new File(directory, "incoming-" + UUID.randomUUID() + ".bin");
        new CaptureReviewPersistence(incoming).save(pending);
        if (!new CaptureReviewPersistence(incoming).matches(pending)) {
            throw new IOException("保存画像の検証に失敗しました");
        }
        String name = "p-" + pending.pageIndex + "-" + digest(incoming) + ".bin";
        CaptureReviewPersistence.moveReplacing(incoming, new File(directory, name));
        Properties next = copy();
        next.setProperty("page." + pending.pageIndex, name);
        next.setProperty("count", Integer.toString(Math.max(pageCount(), pending.pageIndex + 1)));
        // An old revision remains on disk. Only the atomic manifest chooses the current revision.
        save(next);
    }

    synchronized void acknowledge(Page page) throws IOException {
        if (page.fileName.equals(page(page.index).fileName)) update("ack." + page.index, page.fileName);
    }

    CaptureReviewStore.Pending read(Page page) throws IOException {
        if (!page.fileName.matches("p-" + page.index + "-[0-9a-f]{64}\\.bin")) throw new IOException("ページ参照が不正です");
        File file = new File(directory, page.fileName);
        if (!page.fileName.equals("p-" + page.index + "-" + digest(file) + ".bin")) throw new IOException("保存画像の破損を検出しました");
        CaptureReviewStore.Pending result = new CaptureReviewPersistence(file).readPending();
        if (result.pageIndex != page.index) throw new IOException("保存画像の番号が不正です");
        return result;
    }

    synchronized boolean contains(CaptureReviewStore.Pending pending) throws IOException {
        if (pending.pageIndex < 0 || pending.pageIndex >= pageCount()) return false;
        Page page = page(pending.pageIndex);
        File file = new File(directory, page.fileName);
        if (!page.fileName.equals("p-" + page.index + "-" + digest(file) + ".bin")) {
            throw new IOException("保存画像の破損を検出しました");
        }
        return new CaptureReviewPersistence(file).matches(pending);
    }

    private void update(String name, String value) throws IOException {
        Properties next = copy();
        next.setProperty(name, value);
        save(next);
    }
    private Properties copy() { Properties next = new Properties(); next.putAll(state); return next; }
    private void save(Properties next) throws IOException {
        Files.createDirectories(directory.toPath());
        File temporary = new File(directory, "state.properties.tmp");
        try (FileOutputStream stream = new FileOutputStream(temporary)) {
            next.store(stream, "DocScan local session");
            stream.getFD().sync();
        }
        CaptureReviewPersistence.moveReplacing(temporary, new File(directory, "state.properties"));
        state = next;
    }

    private static String digest(File file) throws IOException {
        if (file.length() > 16 * 1024 * 1024) throw new IOException("保存画像が大きすぎます");
        try (InputStream input = new FileInputStream(file)) {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] buffer = new byte[8192];
            int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
            StringBuilder hex = new StringBuilder(64);
            for (byte value : digest.digest()) hex.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
            return hex.toString();
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }
}
