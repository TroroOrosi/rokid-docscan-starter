package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import android.os.Handler;
import android.os.Looper;
import android.util.Size;
import dev.rokid.docscanrelay.ClientIdentity;
import dev.rokid.docscanrelay.DocScanApi;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;
import okhttp3.mockwebserver.Dispatcher;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;
import okhttp3.mockwebserver.SocketPolicy;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

/** Real producer journal/private files + local HTTP; raw fixture bytes are not camera-quality proof. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
public class CaptureVideoTransferTest {
    private static final String LOCAL = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";
    private static final String IP = "192.168.43.88";
    private final File root;
    private final AtomicReference<CaptureVideoTransfer.Snapshot> current = new AtomicReference<>();
    private final List<String> paths = new ArrayList<>(), envelopes = new ArrayList<>();
    private boolean loseResponse;
    private Runnable afterPost;
    private Runnable onFinalPeer;
    private int peerChecks;
    private boolean invalidReceipt;
    public CaptureVideoTransferTest() throws Exception { root = Files.createTempDirectory("video-transfer").toFile(); }
    private CaptureVideoTransfer.Snapshot snapshot(MockWebServer server, long document, long session, long generation) {
        String url = server.url("/").toString().replaceAll("/+$", "");
        return new CaptureVideoTransfer.Snapshot(LOCAL, url, document, session, "device-test", generation,
                session, "analyzing", new DocScanApi(url, "fixture-key", new ClientIdentity("test", "test", "test")));
    }
    private static String hash(byte[] bytes) throws Exception {
        StringBuilder out = new StringBuilder();
        for (byte item : MessageDigest.getInstance("SHA-256").digest(bytes)) out.append(String.format("%02x", item & 255));
        return out.toString();
    }
    private void phone(MockWebServer server) {
        server.setDispatcher(new Dispatcher() { @Override public MockResponse dispatch(RecordedRequest request) {
            try {
                paths.add(request.getPath());
                if ("/v1/glasses/state".equals(request.getPath())) {
                    if (++peerChecks == 2 && onFinalPeer != null) onFinalPeer.run();
                    var now = current.get();
                    JSONObject peer = new JSONObject().put("device_id", now.device).put("generation", now.generation)
                            .put("session_id", now.session).put("phase", now.phase).put("source_ip", IP);
                    return new MockResponse().setBody(new JSONObject().put("devices", new JSONArray().put(peer)).toString());
                }
                if (!"/v1/capture-videos".equals(request.getPath())) return new MockResponse().setResponseCode(500);
                String body = request.getBody().readUtf8(); int header = body.indexOf("name=\"metadata\"");
                int start = body.indexOf("\r\n\r\n", header) + 4, end = body.indexOf("\r\n--", start);
                String metadata = body.substring(start, end); envelopes.add(metadata);
                if (afterPost != null) afterPost.run();
                if (loseResponse) { loseResponse = false; return new MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AFTER_REQUEST); }
                JSONObject value = new JSONObject(metadata), journal = value.getJSONObject("journal");
                JSONObject receipt = new JSONObject().put("schema", 1).put("kind", "raw_video_receipt")
                        .put("status", "stored").put("quality_status", "unevaluated")
                        .put("session_id", value.get("session_id")).put("document_id", value.get("document_id"))
                        .put("device_id", journal.get("device_id")).put("generation", journal.get("generation"))
                        .put("clip_id", journal.get("clip_id")).put("sha256", journal.get("sha256")).put("bytes", journal.get("bytes"))
                        .put("source_ip", IP).put("all_pages_or_characters_verified", false).put("auto_analysis_allowed", false)
                        .put("receipt_id", hash(journal.getString("clip_id").getBytes(StandardCharsets.US_ASCII)))
                        .put("metadata_sha256", hash(metadata.getBytes(StandardCharsets.UTF_8)));
                if (invalidReceipt) receipt.put("auto_analysis_allowed",true);
                return new MockResponse().setResponseCode(201).setBody(receipt.toString());
            } catch (Exception error) { return new MockResponse().setResponseCode(500); }
        }});
    }
    private CaptureVideoRecording sealed(CaptureVideoTransfer.Origin origin) throws Exception {
        var worker = new CaptureVideoRecordingTest.Worker();
        var port = new CaptureVideoRecordingTest.Port() {
            @Override public String prepare(File file, android.hardware.camera2.CameraCharacteristics c, Size jpeg,
                    CaptureVideoRecording.Options options, java.util.function.Consumer<String> fatal) throws java.io.IOException {
                assertEquals(origin != null,new File(file.getParentFile(),"comparison-origin.json").isFile());
                String encoder=super.prepare(file,c,jpeg,options,fatal);
                Files.write(file.toPath(),new byte[]{0,0,0,16,'f','t','y','p','i','s','o','m',1,2,3,4}); return encoder;
            }
            @Override public CaptureVideoRecording.FileInfo inspect(File file) {
                var info = super.inspect(file); info.durationUs = 1000L; return info;
            }
        };
        var video = new CaptureVideoRecording(root, new Handler(Looper.getMainLooper()),
                CaptureVideoRecording.Options.defaults("device-test", 4, 270), worker, () -> port);
        video.comparisonTransferOrigin(origin);
        video.prepare(null, new Size(4032,3024), () -> {}, message -> fail(message)); worker.drain();
        video.start(() -> {}, message -> fail(message)); worker.drain();
        video.finish(true, "capture_end", ok -> assertTrue(ok)); worker.drain(); return video;
    }
    @Test public void explicitOriginKeepsAutoUploadFalseAndFillsOnlyTheOriginalLocalSessionsFirstIds() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            phone(server); current.set(snapshot(server, 0, 0, 4));
            var video = sealed(CaptureVideoTransfer.origin(current.get(), videoOptions()));
            try (var transfer = new CaptureVideoTransfer(root, current::get, null)) {
                transfer.runPending(); assertTrue(paths.isEmpty());
                current.set(snapshot(server, 9, 7, 4)); transfer.runPending();
                assertEquals(List.of("/v1/glasses/state", "/v1/capture-videos", "/v1/glasses/state"), paths);
                JSONObject envelope = new JSONObject(envelopes.get(0));
                assertEquals(4, envelope.length()); assertEquals(9, envelope.getLong("document_id"));
                assertFalse(envelope.getJSONObject("journal").getBoolean("auto_upload_allowed"));
                File folder = video.originalFile().getParentFile();
                assertEquals("acked", json(new File(folder,"comparison-transfer.json")).getString("status"));
                byte[] original = Files.readAllBytes(video.originalFile().toPath());
                transfer.runPending(); assertEquals(3, paths.size());
                assertArrayEquals(original, Files.readAllBytes(video.originalFile().toPath()));
            }
        }
    }
    @Test public void lostResponseRetriesOnlyTheExactDurableEnvelopeAndRestartKeepsItsReceipt() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            phone(server); current.set(snapshot(server, 9, 7, 4));
            var video = sealed(CaptureVideoTransfer.origin(current.get(), videoOptions())); loseResponse = true;
            try (var transfer = new CaptureVideoTransfer(root, current::get, null)) {
                transfer.runPending(); assertEquals(1, envelopes.size());
                transfer.runPending(); assertEquals(2, envelopes.size()); assertEquals(envelopes.get(0), envelopes.get(1));
            }
            int requests = paths.size();
            try (var restarted = new CaptureVideoTransfer(root,current::get,null)) { restarted.runPending(); }
            assertEquals(requests, paths.size()); assertTrue(video.originalFile().isFile());
            assertEquals("acked", json(new File(video.originalFile().getParentFile(),"comparison-transfer.json")).getString("status"));
        }
    }
    @Test public void missingOrUnresolvedOriginIsNeverInventedFromALaterSession() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            phone(server); current.set(snapshot(server, 9, 7, 4));
            var ordinary = sealed(null);
            var unresolved = sealed(CaptureVideoTransfer.origin(null, videoOptions()));
            try (var transfer = new CaptureVideoTransfer(root,current::get,null)) { transfer.runPending(); }
            assertTrue(paths.isEmpty()); assertTrue(ordinary.originalFile().isFile()); assertTrue(unresolved.originalFile().isFile());
            assertFalse(json(new File(unresolved.originalFile().getParentFile(),"comparison-origin.json")).getBoolean("resolved"));
        }
    }
    @Test public void changedGenerationOrBoundIdsCannotRebindAnOriginal() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            phone(server); current.set(snapshot(server, 9, 7, 4));
            var video = sealed(CaptureVideoTransfer.origin(current.get(), videoOptions()));
            try (var transfer = new CaptureVideoTransfer(root,current::get,null)) {
                current.set(snapshot(server, 10, 8, 4)); transfer.runPending(); assertTrue(paths.isEmpty());
                current.set(snapshot(server, 9, 7, 5)); transfer.runPending(); assertTrue(paths.isEmpty());
                assertTrue(video.originalFile().isFile());
            }
        }
    }
    @Test public void lateJournalMutationCannotReceiveAnAcknowledgedStorageState() throws Exception {
        try (MockWebServer server=new MockWebServer()) {
            phone(server); current.set(snapshot(server,9,7,4));
            var video=sealed(CaptureVideoTransfer.origin(current.get(),videoOptions()));
            afterPost=() -> { try {
                JSONObject changed=json(video.journalFile()).put("reason","changed_after_seal");
                Files.write(video.journalFile().toPath(),changed.toString().getBytes(StandardCharsets.UTF_8));
            } catch(Exception error) { throw new RuntimeException(error); }};
            try (var transfer=new CaptureVideoTransfer(root,current::get,null)) { transfer.runPending(); }
            assertEquals("hold",json(new File(video.originalFile().getParentFile(),"comparison-transfer.json")).getString("status"));
            assertTrue(video.originalFile().isFile());
        }
    }
    @Test public void lateGenerationChangeRetainsReceiptWithoutAcknowledgingOrRebinding() throws Exception {
        try (MockWebServer server=new MockWebServer()) {
            phone(server); current.set(snapshot(server,9,7,4));
            var video=sealed(CaptureVideoTransfer.origin(current.get(),videoOptions()));
            afterPost=() -> current.set(snapshot(server,9,7,5));
            try (var transfer=new CaptureVideoTransfer(root,current::get,null)) { transfer.runPending(); }
            File folder=video.originalFile().getParentFile();
            assertEquals("hold",json(new File(folder,"comparison-transfer.json")).getString("status"));
            assertTrue(new File(folder,"comparison-receipt.json").isFile()); assertEquals(2,paths.size());
        }
    }
    @Test public void rejectedReceiptAndChangedRawFileStayHeldAndCannotRetryAsPages() throws Exception {
        try (MockWebServer server=new MockWebServer()) {
            phone(server); current.set(snapshot(server,9,7,4));
            var video=sealed(CaptureVideoTransfer.origin(current.get(),videoOptions())); invalidReceipt=true;
            try (var transfer=new CaptureVideoTransfer(root,current::get,null)) {
                transfer.runPending(); assertEquals(1,envelopes.size());
                transfer.runPending(); assertEquals(1,envelopes.size());
            }
            assertEquals("hold",json(new File(video.originalFile().getParentFile(),"comparison-transfer.json")).getString("status"));
            var changed=sealed(CaptureVideoTransfer.origin(current.get(),videoOptions()));
            Files.write(changed.originalFile().toPath(),new byte[]{9}); int before=paths.size();
            try (var transfer=new CaptureVideoTransfer(root,current::get,null)) { transfer.runPending(); }
            assertEquals(before,paths.size()); assertTrue(changed.originalFile().isFile());
        }
    }
    @Test public void durableAttemptBudgetIsFiniteAndMetadataNeverChangesAcrossUnknownResponses() throws Exception {
        try (MockWebServer server=new MockWebServer()) {
            phone(server); current.set(snapshot(server,9,7,4));
            var video=sealed(CaptureVideoTransfer.origin(current.get(),videoOptions()));
            try (var transfer=new CaptureVideoTransfer(root,current::get,null)) {
                for(int i=0;i<5;i++) { loseResponse=true; transfer.runPending(); }
            }
            assertEquals(3,envelopes.size()); assertEquals(envelopes.get(0),envelopes.get(2));
            assertEquals("hold",json(new File(video.originalFile().getParentFile(),"comparison-transfer.json")).getString("status"));
            assertTrue(paths.stream().allMatch(path -> path.equals("/v1/glasses/state") || path.equals("/v1/capture-videos")));
        }
    }
    @Test public void partialEnvelopeCannotBeRecreatedOrReboundAndOriginalSurvives() throws Exception {
        try (MockWebServer server=new MockWebServer()) {
            phone(server); current.set(snapshot(server,9,7,4));
            var video=sealed(CaptureVideoTransfer.origin(current.get(),videoOptions()));
            File envelope=new File(video.originalFile().getParentFile(),"comparison-envelope.json");
            Files.write(envelope.toPath(),"partial".getBytes(StandardCharsets.UTF_8));
            try (var transfer=new CaptureVideoTransfer(root,current::get,null)) { transfer.runPending(); }
            assertTrue(paths.isEmpty()); assertEquals("partial",new String(Files.readAllBytes(envelope.toPath()),StandardCharsets.UTF_8));
            assertTrue(video.originalFile().isFile());
        }
    }
    @Test public void comparisonTransferRequiresBothStrictLaunchFlagsAndNeverChangesNativeDefault() {
        assertFalse(DocScanGlassActivity.videoTransferEvaluation(new android.content.Intent()));
        assertEquals(GlassCamera.Mode.NATIVE_STILL,DocScanGlassActivity.evaluationMode(new android.content.Intent()));
        assertFalse(DocScanGlassActivity.videoTransferEvaluation(new android.content.Intent().putExtra("video_evaluation",true)));
        assertTrue(DocScanGlassActivity.videoTransferEvaluation(new android.content.Intent().putExtra("video_evaluation",true)
                .putExtra("video_transfer_evaluation",true)));
        assertThrows(IllegalArgumentException.class,() -> DocScanGlassActivity.evaluationMode(
                new android.content.Intent().putExtra("video_transfer_evaluation",true)));
        assertThrows(IllegalArgumentException.class,() -> DocScanGlassActivity.evaluationMode(
                new android.content.Intent().putExtra("video_evaluation",true).putExtra("video_transfer_evaluation","true")));
    }
    @Test public void dedicatedWorkerCoalescesRequestsAndNetworkNeverBecomesARecorderCloseBarrier() throws Exception {
        try (MockWebServer server=new MockWebServer()) {
            phone(server); current.set(snapshot(server,9,7,4));
            var video=sealed(CaptureVideoTransfer.origin(current.get(),videoOptions()));
            var posting=new java.util.concurrent.CountDownLatch(1); var release=new java.util.concurrent.CountDownLatch(1);
            afterPost=() -> { posting.countDown(); try { release.await(5,java.util.concurrent.TimeUnit.SECONDS); }
                catch(InterruptedException interrupted) { Thread.currentThread().interrupt(); }};
            var transfer=new CaptureVideoTransfer(root,current::get,null);
            try {
                for(int i=0;i<10;i++) transfer.request();
                assertTrue(posting.await(5,java.util.concurrent.TimeUnit.SECONDS));
                assertTrue("sealed recorder did not wait for HTTP",video.finalizedSuccessfully());
                long began=System.nanoTime(); transfer.close();
                assertTrue(java.util.concurrent.TimeUnit.NANOSECONDS.toMillis(System.nanoTime()-began) < 1000);
                assertEquals(2,server.getRequestCount()); assertTrue(video.originalFile().isFile());
            } finally { transfer.close(); release.countDown(); }
        }
    }
    @Test public void malformedUtf8CannotNormalizeIntoThePreviouslySavedEnvelopeAndBeRetried() throws Exception {
        try (MockWebServer server=new MockWebServer()) {
            phone(server); current.set(snapshot(server,9,7,4));
            var video=sealed(CaptureVideoTransfer.origin(current.get(),videoOptions()));
            Files.write(video.journalFile().toPath(),json(video.journalFile()).put("reason","\ufffd").toString().getBytes(StandardCharsets.UTF_8));
            try (var transfer=new CaptureVideoTransfer(root,current::get,null)) {
                loseResponse=true; transfer.runPending(); assertEquals(1,envelopes.size());
                File envelope=new File(video.originalFile().getParentFile(),"comparison-envelope.json");
                byte[] before=Files.readAllBytes(envelope.toPath()); var changed=new java.io.ByteArrayOutputStream(); boolean replaced=false;
                for(int i=0;i<before.length;i++) {
                    if (!replaced && i+2<before.length && before[i]==(byte)0xef && before[i+1]==(byte)0xbf && before[i+2]==(byte)0xbd) {
                        changed.write(0xff); i+=2; replaced=true;
                    } else changed.write(before[i]);
                }
                assertTrue(replaced); byte[] corrupt=changed.toByteArray(); Files.write(envelope.toPath(),corrupt);
                transfer.runPending(); assertEquals(1,envelopes.size());
                assertArrayEquals(corrupt,Files.readAllBytes(envelope.toPath())); assertTrue(video.originalFile().isFile());
            }
        }
    }
    @Test public void finalPeerRawMutationCannotAcknowledgeChangedOriginal() throws Exception {
        try (MockWebServer server=new MockWebServer()) {
            phone(server); current.set(snapshot(server,9,7,4));
            var video=sealed(CaptureVideoTransfer.origin(current.get(),videoOptions()));
            byte[] changed=Files.readAllBytes(video.originalFile().toPath()); changed[changed.length-1]^=1;
            onFinalPeer=() -> { try { Files.write(video.originalFile().toPath(),changed); }
                catch(Exception error) { throw new RuntimeException(error); }};
            try (var transfer=new CaptureVideoTransfer(root,current::get,null)) {
                transfer.runPending(); assertEquals(2,peerChecks); assertEquals(1,envelopes.size());
                File folder=video.originalFile().getParentFile();
                assertEquals("hold",json(new File(folder,"comparison-transfer.json")).getString("status"));
                assertTrue(new File(folder,"comparison-receipt.json").isFile());
                assertEquals(envelopes.get(0),new String(Files.readAllBytes(new File(folder,"comparison-envelope.json").toPath()),StandardCharsets.UTF_8));
                assertArrayEquals(changed,Files.readAllBytes(video.originalFile().toPath()));
                transfer.runPending(); assertEquals(1,envelopes.size());
            }
        }
    }
    /** The receipt binds bytes and origin; it does not certify a physical filesystem inode. */
    @Test public void finalPeerSameBytesReplacementRemainsWithinContentHashContract() throws Exception {
        try (MockWebServer server=new MockWebServer()) {
            phone(server); current.set(snapshot(server,9,7,4));
            var video=sealed(CaptureVideoTransfer.origin(current.get(),videoOptions()));
            byte[] original=Files.readAllBytes(video.originalFile().toPath());
            var timestamp=Files.getLastModifiedTime(video.originalFile().toPath());
            File retained=new File(video.originalFile().getParentFile(),"original-retained.mp4");
            onFinalPeer=() -> { try {
                Files.move(video.originalFile().toPath(),retained.toPath());
                Files.write(video.originalFile().toPath(),original); Files.setLastModifiedTime(video.originalFile().toPath(),timestamp);
            } catch(Exception error) { throw new RuntimeException(error); }};
            try (var transfer=new CaptureVideoTransfer(root,current::get,null)) { transfer.runPending(); }
            File folder=video.originalFile().getParentFile();
            assertEquals(2,peerChecks); assertEquals(1,envelopes.size());
            assertEquals("acked",json(new File(folder,"comparison-transfer.json")).getString("status"));
            assertTrue(new File(folder,"comparison-receipt.json").isFile());
            assertArrayEquals(original,Files.readAllBytes(video.originalFile().toPath()));
            assertArrayEquals(original,Files.readAllBytes(retained.toPath()));
        }
    }
    private static CaptureVideoRecording.Options videoOptions() { return CaptureVideoRecording.Options.defaults("device-test",4,270); }
    private static JSONObject json(File file) throws Exception { return new JSONObject(new String(Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8)); }
}
