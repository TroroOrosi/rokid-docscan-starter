package dev.rokid.docscanglass.doc;

import android.content.Context;
import android.os.PowerManager;
import dev.rokid.docscanrelay.DocScanApi;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.charset.CodingErrorAction;
import java.nio.ByteBuffer;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Supplier;
import org.json.JSONException;
import org.json.JSONObject;

/** Opt-in comparison copies only. This never registers pages or requests analysis.
 * A receipt means storage, not decoded continuity, readable text, or booklet coverage.
 */
final class CaptureVideoTransfer implements AutoCloseable {
    private static final Object TRANSFER_LOCK = new Object();
    private static final String CLIP = "video-[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}";
    private static final int MAX_RECORD = 512 * 1024, MAX_ATTEMPTS = 3;
    private static final Set<String> ORIGIN_KEYS = Set.of("schema", "kind", "permission", "resolved",
            "local_session_id", "server", "device_id", "generation", "initial_document_id", "initial_session_id");
    private static final Set<String> STATE_KEYS = Set.of("schema", "status", "attempts", "metadata_sha256",
            "journal_sha256", "origin_sha256", "peer_source_ip", "reason");

    static final class Snapshot {
        final String localId, server, device, phase;
        final long document, session, generation, powerSession;
        final DocScanApi api;
        Snapshot(String localId, String server, long document, long session, String device, long generation,
                 long powerSession, String phase, DocScanApi api) {
            this.localId=localId; this.server=server; this.document=document; this.session=session;
            this.device=device; this.generation=generation; this.powerSession=powerSession; this.phase=phase; this.api=api;
        }
        boolean valid() {
            return localId != null && localId.matches("[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")
                    && api != null && api.serverUrl().equals(server) && device != null
                    && device.matches("[A-Za-z0-9_.:-]{1,100}") && generation >= 0
                    && document >= 0 && document <= Integer.MAX_VALUE && session >= 0 && session <= Integer.MAX_VALUE
                    && (powerSession == 0 || powerSession == session)
                    && phase != null && List.of("capturing", "analyzing", "waiting", "reading").contains(phase);
        }
    }

    /** Written before recorder.prepare; an unavailable origin stays unresolved forever. */
    static final class Origin {
        private final String json;
        private Origin(JSONObject value) { json=value.toString(); }
        void write(File directory) throws IOException { create(new File(directory,"comparison-origin.json"),json); }
    }
    static Origin origin(Snapshot snapshot, CaptureVideoRecording.Options options) {
        boolean resolved = snapshot != null && snapshot.valid() && options.deviceId.equals(snapshot.device)
                && options.generation == snapshot.generation;
        try {
            return new Origin(new JSONObject().put("schema",1).put("kind","capture_video_origin")
                    .put("permission","explicit_comparison_transfer_only").put("resolved",resolved)
                    .put("local_session_id",resolved ? snapshot.localId : JSONObject.NULL)
                    .put("server",resolved ? snapshot.server : JSONObject.NULL).put("device_id",options.deviceId)
                    .put("generation",options.generation).put("initial_document_id",resolved ? snapshot.document : 0)
                    .put("initial_session_id",resolved ? snapshot.session : 0));
        } catch (JSONException impossible) { throw new IllegalArgumentException(impossible); }
    }

    private final File root;
    private final Supplier<Snapshot> current;
    private final Context context;
    private final ScheduledExecutorService worker = Executors.newSingleThreadScheduledExecutor(task -> {
        Thread thread=new Thread(task,"glass-video-transfer"); thread.setDaemon(true); return thread;
    });
    private final AtomicBoolean queued = new AtomicBoolean();
    private volatile boolean closed;
    private volatile DocScanApi activeApi;

    CaptureVideoTransfer(File filesDir, Supplier<Snapshot> current, Context context) {
        root=new File(filesDir,"video-evaluations"); this.current=current;
        this.context=context == null ? null : context.getApplicationContext();
    }
    void request() { request(0); }
    private void request(int retry) {
        if (closed || !queued.compareAndSet(false,true)) return;
        try { worker.schedule(() -> {
            boolean pending=false;
            try { pending=runPending(); }
            finally { queued.set(false); }
            if (pending && retry < 2) request(retry+1);
        }, retry == 0 ? 0 : 5, TimeUnit.SECONDS); }
        catch (java.util.concurrent.RejectedExecutionException ending) { queued.set(false); }
    }
    /** One bounded sweep, also used by the local HTTP integration tests. */
    boolean runPending() {
        synchronized (TRANSFER_LOCK) {
            if (closed) return false;
            File[] folders=root.listFiles(); if (folders == null) return false;
            boolean pending=false;
            for (File folder:folders) {
                if (closed) break;
                if (!folder.getName().matches(CLIP)) continue;
                try { pending |= transfer(folder); }
                catch (IOException | JSONException | RuntimeException invalid) {
                    // A partial/invalid local record is retained for diagnosis, never reconstructed.
                    android.util.Log.w("GlassVideoTransfer","comparison retained: " + invalid.getClass().getSimpleName());
                }
            }
            return pending;
        }
    }

    private boolean transfer(File folder) throws IOException, JSONException {
        requirePrivate(folder,true);
        File originFile=new File(folder,"comparison-origin.json"), journalFile=new File(folder,"journal.json");
        if (!originFile.exists() || !journalFile.exists()) return false;
        String originText=read(originFile); JSONObject origin=new JSONObject(originText); keys(origin,ORIGIN_KEYS);
        if (integer(origin,"schema") != 1 || !"capture_video_origin".equals(origin.opt("kind"))
                || !"explicit_comparison_transfer_only".equals(origin.opt("permission"))
                || !(origin.opt("resolved") instanceof Boolean)) throw new JSONException("invalid origin");
        if (!Boolean.TRUE.equals(origin.opt("resolved"))) return false;
        Snapshot now=current.get();
        if (!matches(origin,now)) return false;
        String journalText=read(journalFile); JSONObject journal=new JSONObject(journalText);
        if (!"complete".equals(journal.opt("state"))) return false;
        if (!"raw_video_evaluation".equals(journal.opt("kind")) || integer(journal,"schema") != 1
                || !folder.getName().equals(journal.opt("clip_id")) || !now.device.equals(journal.opt("device_id"))
                || now.generation != integer(journal,"generation") || !"original.mp4".equals(journal.opt("original"))
                || !Boolean.FALSE.equals(journal.opt("auto_upload_allowed"))
                || !Boolean.FALSE.equals(journal.opt("all_pages_or_characters_verified"))
                || !"sealed_local_video_container_only".equals(journal.opt("complete_scope")))
            throw new JSONException("invalid sealed journal");
        if (now.document == 0 || now.session == 0 || now.powerSession != now.session) return false;
        File envelopeFile=new File(folder,"comparison-envelope.json"), stateFile=new File(folder,"comparison-transfer.json");
        String journalHash=hash(journalText.getBytes(StandardCharsets.UTF_8));
        if (envelopeFile.exists() != stateFile.exists()) throw new IOException("partial comparison binding");
        if (!envelopeFile.exists()) {
            String metadata=new JSONObject().put("schema",1).put("session_id",now.session)
                    .put("document_id",now.document).put("journal",journal).toString();
            create(envelopeFile,metadata);
            create(stateFile,new JSONObject().put("schema",1).put("status","ready").put("attempts",0)
                    .put("metadata_sha256",hash(metadata.getBytes(StandardCharsets.UTF_8)))
                    .put("journal_sha256",journalHash).put("origin_sha256",hash(originText.getBytes(StandardCharsets.UTF_8)))
                    .put("peer_source_ip",JSONObject.NULL).put("reason","").toString());
        }
        String metadata=read(envelopeFile); JSONObject envelope=new JSONObject(metadata), state=new JSONObject(read(stateFile));
        keys(envelope,Set.of("schema","session_id","document_id","journal")); keys(state,STATE_KEYS);
        if (integer(state,"schema") != 1 || integer(envelope,"schema") != 1
                || integer(envelope,"session_id") != now.session || integer(envelope,"document_id") != now.document
                || !journalHash.equals(state.opt("journal_sha256"))
                || !hash(originText.getBytes(StandardCharsets.UTF_8)).equals(state.opt("origin_sha256"))
                || !hash(metadata.getBytes(StandardCharsets.UTF_8)).equals(state.opt("metadata_sha256"))
                || !journal.toString().equals(envelope.getJSONObject("journal").toString()))
            return hold(stateFile,state,"comparison_binding_changed");
        long attempts=integer(state,"attempts");
        if (attempts < 0 || attempts > MAX_ATTEMPTS || !List.of("ready","inflight","acked","hold").contains(state.opt("status")))
            throw new JSONException("invalid comparison state");
        File original=new File(folder,"original.mp4"); requirePrivate(original,false);
        long size=integer(journal,"bytes");
        if (size <= 0 || size > CaptureVideoRecording.MAX_BYTES || original.length() != size
                || !hash(original).equals(journal.opt("sha256"))) {
            return hold(stateFile,state,"source_changed");
        }
        if ("hold".equals(state.opt("status"))) return false;
        File receiptFile=new File(folder,"comparison-receipt.json");
        String savedIp=state.isNull("peer_source_ip") ? null : state.getString("peer_source_ip");
        if (receiptFile.exists()) {
            try { DocScanApi.requireCaptureVideoReceipt(metadata,new JSONObject(read(receiptFile)),savedIp); }
            catch (JSONException invalid) { return hold(stateFile,state,"receipt_mismatch"); }
            if ("acked".equals(state.opt("status"))) return false;
        } else if ("acked".equals(state.opt("status"))) return hold(stateFile,state,"receipt_missing");
        if (!receiptFile.exists() && attempts >= MAX_ATTEMPTS) return hold(stateFile,state,"attempt_budget");
        activeApi=now.api; PowerManager.WakeLock wake=null;
        try {
            if (closed) return false;
            if (context != null) {
                PowerManager power=context.getSystemService(PowerManager.class);
                if (power != null) { wake=power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"glassdoc:video-copy"); wake.acquire(150_000); }
            }
            String peer=now.api.captureVideoPeer(now.device,now.session,now.generation);
            if (!stillCurrent(origin,now)) return hold(stateFile,state,"origin_no_longer_current");
            if (!recordsUnchanged(folder,originText,journalText,metadata)) return hold(stateFile,state,"source_records_changed");
            if (savedIp != null && !savedIp.equals(peer)) return hold(stateFile,state,"source_ip_changed");
            if (savedIp == null) { savedIp=peer; state.put("peer_source_ip",peer); replace(stateFile,state.toString()); }
            if (!receiptFile.exists()) {
                state.put("status","inflight").put("attempts",attempts+1).put("reason","response_unknown");
                replace(stateFile,state.toString());
                JSONObject receipt=now.api.uploadCaptureVideo(original,metadata,savedIp);
                create(receiptFile,receipt.toString());
            }
            if (!stillCurrent(origin,now))
                return hold(stateFile,state,"origin_no_longer_current");
            if (!recordsUnchanged(folder,originText,journalText,metadata) || original.length() != size
                    || !hash(original).equals(journal.opt("sha256"))) return hold(stateFile,state,"source_records_changed");
            String confirmed=now.api.captureVideoPeer(now.device,now.session,now.generation);
            if (!savedIp.equals(confirmed) || !stillCurrent(origin,now))
                return hold(stateFile,state,"origin_no_longer_current");
            requirePrivate(original,false);
            if (original.length() != size || !hash(original).equals(journal.opt("sha256"))
                    || !recordsUnchanged(folder,originText,journalText,metadata)) return hold(stateFile,state,"source_records_changed");
            if (!stillCurrent(origin,now)) return hold(stateFile,state,"origin_no_longer_current");
            state.put("status","acked").put("reason","stored_unevaluated"); replace(stateFile,state.toString()); return false;
        } catch (DocScanApi.ApiException error) {
            if (error.getStatusCode() == 409 || error.getStatusCode() == 404 || error.getStatusCode() == 422
                    || error.getStatusCode() == 401 || error.getStatusCode() == 403)
                return hold(stateFile,state,"peer_rejected");
            return true;
        } catch (JSONException invalid) { return hold(stateFile,state,"receipt_or_peer_invalid"); }
        catch (IOException unavailable) {
            if (!recordsUnchanged(folder,originText,journalText,metadata) || original.length() != size
                    || !hash(original).equals(journal.opt("sha256"))) return hold(stateFile,state,"source_records_changed");
            if (!receiptFile.exists() && integer(state,"attempts") >= MAX_ATTEMPTS) return hold(stateFile,state,"attempt_budget");
            return !closed;
        }
        finally { activeApi=null; if (wake != null && wake.isHeld()) wake.release(); }
    }
    private static boolean matches(JSONObject origin, Snapshot now) throws JSONException {
        return now != null && now.valid() && now.localId.equals(origin.opt("local_session_id"))
                && now.server.equals(origin.opt("server")) && now.device.equals(origin.opt("device_id"))
                && now.generation == integer(origin,"generation")
                && (integer(origin,"initial_document_id") == 0 || now.document == integer(origin,"initial_document_id"))
                && (integer(origin,"initial_session_id") == 0 || now.session == integer(origin,"initial_session_id"));
    }
    private static boolean sameIds(Snapshot a, Snapshot b) {
        return b != null && a.document == b.document && a.session == b.session && b.powerSession == b.session;
    }
    private boolean stillCurrent(JSONObject origin,Snapshot before) throws JSONException {
        Snapshot after=current.get(); return !closed && matches(origin,after) && sameIds(before,after);
    }
    private boolean recordsUnchanged(File folder,String origin,String journal,String metadata) {
        try {
            return origin.equals(read(new File(folder,"comparison-origin.json")))
                    && journal.equals(read(new File(folder,"journal.json")))
                    && metadata.equals(read(new File(folder,"comparison-envelope.json")));
        } catch (IOException unavailable) { return false; }
    }
    private static boolean hold(File file, JSONObject state, String why) throws IOException, JSONException {
        state.put("status","hold").put("reason",why); replace(file,state.toString()); return false;
    }
    private void requirePrivate(File file, boolean directory) throws IOException {
        var path=file.toPath().toAbsolutePath().normalize();
        var base=root.toPath().toAbsolutePath().normalize();
        if (!path.startsWith(base)) throw new IOException("outside video originals");
        for (var part=path; part != null; part=part.getParent()) if (Files.isSymbolicLink(part)) throw new IOException("linked original");
        if (directory ? !Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS) : !Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS))
            throw new IOException("missing original record");
    }
    private String read(File file) throws IOException {
        requirePrivate(file,false);
        long size=file.length(); if (size < 1 || size > MAX_RECORD) throw new IOException("record budget");
        byte[] bytes=Files.readAllBytes(file.toPath()); if (bytes.length != size) throw new IOException("record changed");
        return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
    }
    private static void create(File file,String value) throws IOException {
        if (!file.createNewFile()) throw new IOException("comparison record already exists");
        try (FileOutputStream out=new FileOutputStream(file)) { out.write(value.getBytes(StandardCharsets.UTF_8)); out.getFD().sync(); }
    }
    private static void replace(File file,String value) throws IOException {
        File pending=File.createTempFile(file.getName()+"-",".pending",file.getParentFile());
        try (FileOutputStream out=new FileOutputStream(pending)) { out.write(value.getBytes(StandardCharsets.UTF_8)); out.getFD().sync(); }
        Files.move(pending.toPath(),file.toPath(),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
    }
    private static void keys(JSONObject value,Set<String> expected) throws JSONException {
        Set<String> actual=new HashSet<>(); value.keys().forEachRemaining(actual::add);
        if (!actual.equals(expected)) throw new JSONException("unexpected record keys");
    }
    private static long integer(JSONObject value,String key) throws JSONException {
        Object number=value.opt(key);
        if (!(number instanceof Integer || number instanceof Long)) throw new JSONException("invalid integer");
        return ((Number)number).longValue();
    }
    private static MessageDigest digest() { try { return MessageDigest.getInstance("SHA-256"); } catch (NoSuchAlgorithmException e) { throw new AssertionError(e); } }
    private static String hex(byte[] value) { StringBuilder out=new StringBuilder(); for (byte item:value) out.append(String.format("%02x",item & 255)); return out.toString(); }
    private static String hash(byte[] value) { return hex(digest().digest(value)); }
    private static String hash(File file) throws IOException {
        MessageDigest digest=digest(); byte[] buffer=new byte[64*1024]; int size; long total=0;
        try (FileInputStream input=new FileInputStream(file)) { while ((size=input.read(buffer)) != -1) {
            total+=size; if (total > CaptureVideoRecording.MAX_BYTES) throw new IOException("original budget"); digest.update(buffer,0,size);
        }} return hex(digest.digest());
    }
    @Override public void close() {
        closed=true; DocScanApi api=activeApi; if (api != null) api.cancelCaptureVideoTransfers(); worker.shutdownNow();
    }
}
