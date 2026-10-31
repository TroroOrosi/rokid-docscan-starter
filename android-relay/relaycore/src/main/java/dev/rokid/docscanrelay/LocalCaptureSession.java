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
    private boolean freshProcess = true;
    private Properties state;

    private LocalCaptureSession(File directory, Properties state) {
        this.directory = directory;
        this.state = state;
    }

    static LocalCaptureSession create(File root, String server, boolean listening) throws IOException {
        return create(root, server, listening ? "listening" : "written");
    }

    static LocalCaptureSession create(File root, String server, String examType) throws IOException {
        if (server == null || server.trim().isEmpty() || server.length() > 4096) throw new IOException("接続先が未設定です");
        if (!java.util.List.of("written", "listening", "mixed").contains(examType)) throw new IOException("試験形式が不正です");
        File directory = new File(root, UUID.randomUUID().toString());
        Properties state = new Properties();
        state.setProperty("version", "1");
        state.setProperty("server", server);
        state.setProperty("listening", Boolean.toString(!"written".equals(examType)));
        state.setProperty("exam_type", examType);
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
            result.freshProcess = false; // Optional extra requests are never reconstructed after restart.
            if (result.documentId() < 0 || result.sessionId() < 0 || result.pageCount() < 0 || result.pageCount() > 1000) {
                throw new IOException("保存記録の番号が不正です");
            }
            result.phase();
            if (!java.util.List.of("written", "listening", "mixed").contains(result.examType())
                    || result.listening() != !"written".equals(result.examType())) throw new IOException("試験形式が不正です");
            Phase.valueOf(state.getProperty("resume_phase"));
            for (int index = 0; index < result.pageCount(); index++) result.page(index);
            if (result.candidateCount() < 0 || result.candidateCount() > 2) throw new IOException("保存候補数が不正です");
            for (int index = 0; index < result.candidateCount(); index++) result.candidateName(index);
            if (Boolean.parseBoolean(state.getProperty("candidate.issued", "false"))
                    || Boolean.parseBoolean(state.getProperty("candidate.observing", "false"))) {
                // Observation/preparation may already have missed a scene before a native request exists.
                state.setProperty("capture.gap", "true");
            }
            return result;
        } catch (IllegalArgumentException | NullPointerException invalid) {
            throw new IOException("保存記録の形式が不正です");
        }
    }

    String id() { return directory.getName(); }
    File directory() { return directory; }
    synchronized String server() { return state.getProperty("server"); }
    synchronized boolean listening() { return Boolean.parseBoolean(state.getProperty("listening")); }
    synchronized String examType() { return state.getProperty("exam_type", listening() ? "listening" : "written"); }
    synchronized boolean mixed() { return "mixed".equals(examType()); }
    synchronized boolean audioComplete() { return Boolean.parseBoolean(state.getProperty("audio_complete", "false")); }
    synchronized void completeAudio() throws IOException { update("audio_complete", "true"); }
    synchronized boolean audioAttachPending() { return mixed() && audioComplete() && sessionId() > 0 && !Boolean.parseBoolean(state.getProperty("audio_attached", "false")); }
    synchronized void acknowledgeAudio() throws IOException { update("audio_attached", "true"); }
    synchronized int pageCount() { return Integer.parseInt(state.getProperty("count")); }
    synchronized int candidateCount() { return Integer.parseInt(state.getProperty("candidate.count", "0")); }
    synchronized boolean captureGap() { return Boolean.parseBoolean(state.getProperty("capture.gap", "false")); }
    synchronized void markCaptureGap() throws IOException {
        try { update("capture.gap", "true"); }
        finally { state.setProperty("capture.gap", "true"); }
    }
    synchronized void resolveCaptureGap() throws IOException {
        Properties next = copy();
        next.setProperty("capture.gap", "false");
        next.remove("candidate.issued");
        next.remove("candidate.observing");
        save(next);
    }

    synchronized void beginCandidateObservation() throws IOException {
        if (phase() != Phase.CAPTURE || captureGap()) throw new IOException("撮影候補の観測を開始できません");
        if (!Boolean.parseBoolean(state.getProperty("candidate.observing", "false"))) {
            update("candidate.observing", "true");
        }
    }

    /** Only the camera's successful idle barrier may resolve an uninterrupted observation. */
    synchronized void finishCandidateObservation() throws IOException {
        if (captureGap() || !Boolean.parseBoolean(state.getProperty("candidate.observing", "false"))) return;
        if (Boolean.parseBoolean(state.getProperty("candidate.issued", "false"))) {
            throw new IOException("撮影候補の原本保存が未確認です");
        }
        Properties next = copy();
        next.remove("candidate.observing");
        save(next);
    }

    synchronized void beginCandidate() throws IOException {
        if (phase() != Phase.CAPTURE || captureGap() || candidateCount() >= 2
                || Boolean.parseBoolean(state.getProperty("candidate.issued", "false"))) {
            throw new IOException("撮影候補を開始できません");
        }
        update("candidate.issued", "true");
    }
    synchronized long documentId() { return Long.parseLong(state.getProperty("document")); }
    synchronized long sessionId() { return Long.parseLong(state.getProperty("session")); }
    synchronized Phase phase() { return Phase.valueOf(state.getProperty("phase")); }
    synchronized boolean unfinished() {
        return candidateCount() > 0 || captureGap()
                || (phase() == Phase.CLOSED ? Phase.valueOf(state.getProperty("resume_phase")) : phase()) != Phase.REVIEW
                || (mixed() && !Boolean.parseBoolean(state.getProperty("audio_attached", "false")));
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
        checkProvenance(pending);
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
        String quality = "quality." + pending.pageIndex + ".";
        if (state.containsKey(quality + "attempted")) {
            String sha = pending.provenance == null ? "" : pending.provenance.jpegSha256;
            next.setProperty(quality + "committed", sha.equals(state.getProperty(quality + "a_sha")) ? "A"
                    : sha.equals(state.getProperty(quality + "b_sha")) ? "B" : "OTHER");
        }
        // The revision hash includes native provenance when present. Old revisions remain;
        // only the atomic manifest chooses the current original and its exact association.
        save(next);
    }

    /** Persist A and the one-extra reservation before any optional native request. Never uses next-page slots. */
    synchronized boolean beginQualitySelection(CaptureReviewStore.Pending a, CaptureSurface.NativeScene scene,
                                               long generation) throws IOException {
        String key = "quality." + a.pageIndex + ".";
        if (!freshProcess || phase() != Phase.CAPTURE || captureGap() || a.pageIndex != pageCount()
                || state.containsKey(key + "attempted") || generation <= 0 || scene == null
                || !scene.matches(a.provenance) || a.hasOcrFailure()) return false;
        String name = retainQualityOriginal(a);
        Properties next = copy();
        next.setProperty(key + "a", name);
        next.setProperty(key + "a_sha", a.provenance.jpegSha256);
        next.setProperty(key + "attempted", "true");
        next.setProperty(key + "generation", Long.toString(generation));
        next.setProperty(key + "camera", scene.camera());
        next.setProperty(key + "stream", Long.toString(scene.stream()));
        next.setProperty(key + "scene", Long.toString(scene.sequence()));
        next.setProperty(key + "decision", NativeImageQuality.Decision.UNKNOWN.name());
        save(next);
        return true;
    }

    /** Called at delivery, including after end/turn. It does not register or acknowledge a page. */
    synchronized void retainQualityAlternative(CaptureReviewStore.Pending a, CaptureReviewStore.Pending b) throws IOException {
        String key = "quality." + a.pageIndex + ".";
        if (!"true".equals(state.getProperty(key + "attempted")) || a.provenance == null
                || !a.provenance.jpegSha256.equals(state.getProperty(key + "a_sha"))
                || b.pageIndex != a.pageIndex
                || (b.provenance != null && (!"native_still".equals(b.provenance.sourceKind)
                || a.provenance.captureId.equals(b.provenance.captureId))) || state.containsKey(key + "b"))
            throw new IOException("native alternative identity");
        String name = retainQualityOriginal(b);
        Properties next = copy();
        next.setProperty(key + "b", name);
        next.setProperty(key + "b_sha", b.provenance == null ? "" : b.provenance.jpegSha256);
        next.setProperty(key + "decision", NativeImageQuality.Decision.UNKNOWN.name());
        save(next);
    }

    synchronized CaptureReviewStore.Pending qualityDecision(CaptureReviewStore.Pending a,
                                                            NativeImageQuality.Decision decision) throws IOException {
        String key = "quality." + a.pageIndex + ".";
        CaptureReviewStore.Pending original = qualityOriginal(a.pageIndex, false);
        if (a.provenance == null || !a.provenance.equals(original.provenance)) throw new IOException("native selection A changed");
        CaptureReviewStore.Pending chosen = original;
        if (decision == NativeImageQuality.Decision.SELECT_B) {
            if (phase() != Phase.CAPTURE || captureGap() || pageCount() != a.pageIndex)
                throw new IOException("native selection no longer pending");
            chosen = qualityOriginal(a.pageIndex, true);
            if (chosen.hasOcrFailure()) throw new IOException("native selection scene unknown");
        }
        Properties next = copy();
        next.setProperty(key + "decision", decision.name());
        save(next);
        return chosen;
    }

    synchronized CaptureReviewStore.Pending qualityOriginal(int page, boolean alternative) throws IOException {
        String name = state.getProperty("quality." + page + (alternative ? ".b" : ".a"), "");
        if (!name.matches("q-" + page + "-[0-9a-f]{64}\\.bin")) throw new IOException("native original reference");
        File file = new File(directory, name);
        if (!name.equals("q-" + page + "-" + digest(file) + ".bin")) throw new IOException("native original hash");
        CaptureReviewStore.Pending pending = new CaptureReviewPersistence(file).readPending();
        checkProvenance(pending);
        return pending;
    }

    private String retainQualityOriginal(CaptureReviewStore.Pending pending) throws IOException {
        checkProvenance(pending);
        File incoming = new File(directory, "incoming-" + UUID.randomUUID() + ".bin");
        CaptureReviewPersistence record = new CaptureReviewPersistence(incoming);
        record.save(pending);
        if (!record.matches(pending)) throw new IOException("native original persistence");
        String name = "q-" + pending.pageIndex + "-" + digest(incoming) + ".bin";
        CaptureReviewPersistence.moveReplacing(incoming, new File(directory, name));
        return name;
    }

    /** Candidate files use the unchanged review record; only accepted pages reach page.*. */
    synchronized void retainCandidate(CaptureReviewStore.Pending pending) throws IOException {
        checkProvenance(pending);
        File incoming = new File(directory, "incoming-" + UUID.randomUUID() + ".bin");
        CaptureReviewPersistence persistence = new CaptureReviewPersistence(incoming);
        persistence.save(pending);
        if (!persistence.matches(pending)) throw new IOException("撮影候補の保存検証に失敗しました");
        String name = "c-" + pending.pageIndex + "-" + digest(incoming) + ".bin";
        CaptureReviewPersistence.moveReplacing(incoming, new File(directory, name));
        Properties next = copy();
        next.remove("candidate.issued");
        if (candidateCount() >= 2) {
            // An unexpected late original is retained too, but cannot bypass the bounded review queue.
            next.setProperty("capture.gap", "true");
            next.setProperty("candidate.unresolved", name);
            save(next);
            throw new IOException("撮影候補が満杯です。原本は保持しています");
        }
        next.setProperty("candidate." + candidateCount(), name);
        next.setProperty("candidate.count", Integer.toString(candidateCount() + 1));
        if (pending.hasOcrFailure() || phase() != Phase.CAPTURE) next.setProperty("capture.gap", "true");
        save(next);
    }

    synchronized int nextCandidatePageIndex() throws IOException {
        int index = pageCount();
        if (candidateCount() > 0) index = Math.max(index, readCandidate(candidateCount() - 1).pageIndex + 1);
        File pendingFile = new File(directory, "pending.bin");
        if (pendingFile.isFile()) {
            CaptureReviewStore.Pending pending = new CaptureReviewPersistence(pendingFile).readPending();
            index = Math.max(index, pending.pageIndex + 1);
        }
        if (index >= 1000) throw new IOException("撮影候補のページ数が上限です");
        return index;
    }

    synchronized CaptureReviewStore.Pending promoteCandidate() throws IOException {
        if (phase() != Phase.CAPTURE || candidateCount() == 0) return null;
        File pendingFile = new File(directory, "pending.bin");
        if (pendingFile.isFile() && !contains(new CaptureReviewPersistence(pendingFile).readPending())) {
            throw new IOException("表示中の写真を先に確認してください");
        }
        CaptureReviewStore.Pending pending = readCandidate(0);
        if (pending.pageIndex != pageCount()) throw new IOException("撮影候補の順序を確認してください");
        new CaptureReviewPersistence(pendingFile).save(pending);
        removeFirstCandidate();
        return pending;
    }

    /** A crash between the pending rename and atomic state update must not show a candidate twice. */
    synchronized void reconcileCandidates() throws IOException {
        if (candidateCount() == 0) return;
        File pendingFile = new File(directory, "pending.bin");
        CaptureReviewPersistence displayed = new CaptureReviewPersistence(pendingFile);
        while (candidateCount() > 0) {
            CaptureReviewStore.Pending first = readCandidate(0);
            if (!contains(first) && (!pendingFile.isFile() || !displayed.matches(first))) break;
            removeFirstCandidate();
        }
    }

    private void removeFirstCandidate() throws IOException {
        Properties next = copy();
        int count = candidateCount();
        for (int index = 1; index < count; index++) next.setProperty("candidate." + (index - 1), candidateName(index));
        next.remove("candidate." + (count - 1));
        next.setProperty("candidate.count", Integer.toString(count - 1));
        save(next);
    }

    private String candidateName(int slot) throws IOException {
        String name = state.getProperty("candidate." + slot, "");
        if (slot < 0 || slot >= candidateCount() || !name.matches("c-[0-9]{1,3}-[0-9a-f]{64}\\.bin")) {
            throw new IOException("撮影候補の参照が不正です");
        }
        return name;
    }

    private CaptureReviewStore.Pending readCandidate(int slot) throws IOException {
        String name = candidateName(slot);
        File file = new File(directory, name);
        CaptureReviewStore.Pending pending = new CaptureReviewPersistence(file).readPending();
        if (!name.equals("c-" + pending.pageIndex + "-" + digest(file) + ".bin")) {
            throw new IOException("撮影候補の破損を検出しました");
        }
        checkProvenance(pending);
        return pending;
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
        checkProvenance(result);
        return result;
    }

    private void checkProvenance(CaptureReviewStore.Pending pending) throws IOException {
        CaptureProvenance source = pending.provenance;
        if (source != null && (!id().equals(source.localSessionId)
                || !source.matches(pending.jpeg, pending.pageIndex, pending.rotationDegrees))) {
            throw new IOException("保存画像の撮影元が一致しません");
        }
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
