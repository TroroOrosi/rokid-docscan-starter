package dev.rokid.docscanrelay;

import static org.junit.Assert.*;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.List;
import okhttp3.OkHttpClient;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;
import org.robolectric.util.ReflectionHelpers;

/** Real HTTP/file streaming with a local server; no phone or recorded-camera acceptance. */
@RunWith(RobolectricTestRunner.class)
@Config(manifest = Config.NONE, sdk = 32)
public class DocScanApiCaptureVideoTest {
    private static final String CLIP = "video-11111111-2222-3333-4444-555555555555";
    private static final byte[] RAW = {0,0,0,20,'f','t','y','p','i','s','o','m',1,2,3,4};
    private static final String IP = "192.168.43.88";

    private static String hash(byte[] bytes) throws Exception {
        StringBuilder out = new StringBuilder();
        for (byte value : MessageDigest.getInstance("SHA-256").digest(bytes)) out.append(String.format("%02x", value & 255));
        return out.toString();
    }
    private static DocScanApi api(MockWebServer server) {
        return new DocScanApi(server.url("/").toString(), "fixture-key", new ClientIdentity("test", "test", "test"));
    }
    private static File raw() throws Exception {
        File file = Files.createTempDirectory("capture-video-api").resolve("original.mp4").toFile();
        Files.write(file.toPath(), RAW); return file;
    }
    private static String envelope() throws Exception {
        // The transport's source bindings; the phone validates the complete producer journal.
        return new JSONObject().put("schema", 1).put("session_id", 7).put("document_id", 9)
                .put("journal", new JSONObject().put("schema", 1).put("kind", "raw_video_evaluation")
                        .put("state", "complete").put("device_id", "device-test").put("generation", 9007199254740993L)
                        .put("clip_id", CLIP).put("bytes", RAW.length).put("sha256", hash(RAW))
                        .put("original", "original.mp4").put("auto_upload_allowed", false)
                        .put("all_pages_or_characters_verified", false).put("complete_scope", "sealed_local_video_container_only"))
                .toString();
    }
    private static JSONObject receipt(String metadata) throws Exception {
        return new JSONObject().put("schema", 1).put("kind", "raw_video_receipt").put("status", "stored")
                .put("quality_status", "unevaluated").put("session_id", 7).put("document_id", 9)
                .put("device_id", "device-test").put("generation", 9007199254740993L).put("clip_id", CLIP)
                .put("sha256", hash(RAW)).put("bytes", RAW.length).put("source_ip", IP)
                .put("all_pages_or_characters_verified", false).put("auto_analysis_allowed", false)
                .put("receipt_id", hash(CLIP.getBytes(StandardCharsets.US_ASCII)))
                .put("metadata_sha256", hash(metadata.getBytes(StandardCharsets.UTF_8)));
    }
    private static JSONObject peer(long generation, Object session, String phase) throws Exception {
        return new JSONObject().put("device_id", "device-test").put("generation", generation)
                .put("session_id", session).put("phase", phase).put("source_ip", IP);
    }
    @Test public void comparisonMultipartPreservesExactEnvelopeAndOriginalAndAcceptsIdempotentReceipt() throws Exception {
        String metadata = " \n" + envelope() + "\n"; File file = raw();
        try (MockWebServer server = new MockWebServer()) {
            DocScanApi api = api(server);
            for (int status : List.of(201, 200)) {
                server.enqueue(new MockResponse().setResponseCode(status).setBody(receipt(metadata).toString()));
                assertEquals("unevaluated", api.uploadCaptureVideo(file, metadata, IP).getString("quality_status"));
                RecordedRequest request = server.takeRequest();
                assertEquals("/v1/capture-videos", request.getPath());
                assertEquals("Bearer fixture-key", request.getHeader("Authorization"));
                assertNull(request.getHeader("Forwarded")); assertNull(request.getHeader("X-Forwarded-For"));
                String body = request.getBody().readUtf8();
                int metadataHeader = body.indexOf("name=\"metadata\"");
                int metadataStart = body.indexOf("\r\n\r\n", metadataHeader) + 4;
                assertEquals(metadata, body.substring(metadataStart, metadataStart + metadata.length()));
                assertTrue(body.contains("name=\"video\"; filename=\"original.mp4\""));
                assertTrue(body.contains("Content-Type: video/mp4"));
                assertTrue(body.contains(new String(RAW, StandardCharsets.UTF_8)));
                assertFalse(body.contains("name=\"image\""));
            }
            assertArrayEquals(RAW, Files.readAllBytes(file.toPath()));
            OkHttpClient transport = ReflectionHelpers.getField(api, "videoHttp");
            assertFalse(transport.retryOnConnectionFailure()); assertFalse(transport.followRedirects());
            assertTrue(transport.callTimeoutMillis() > 0 && transport.callTimeoutMillis() <= 120_000);
        }
    }
    @Test public void receiptRequiresExactKeysTypedIdentityHashesPeerAndUnevaluatedFlags() throws Exception {
        String metadata = envelope();
        try (MockWebServer server = new MockWebServer()) {
            DocScanApi api = api(server); File file = raw();
            for (String field : List.of("schema", "session_id", "document_id", "generation", "bytes")) {
                for (Object invalid : List.of("1", true, -1)) {
                    server.enqueue(new MockResponse().setBody(receipt(metadata).put(field, invalid).toString()));
                    assertThrows(JSONException.class, () -> api.uploadCaptureVideo(file, metadata, IP)); server.takeRequest();
                }
                JSONObject correct = receipt(metadata);
                String decimal = correct.toString().replace("\"" + field + "\":" + correct.get(field),
                        "\"" + field + "\":" + correct.get(field) + ".0");
                server.enqueue(new MockResponse().setBody(decimal));
                assertThrows(JSONException.class, () -> api.uploadCaptureVideo(file, metadata, IP)); server.takeRequest();
            }
            for (String field : List.of("receipt_id", "metadata_sha256", "sha256", "clip_id", "source_ip",
                    "quality_status", "auto_analysis_allowed", "all_pages_or_characters_verified")) {
                JSONObject wrong = receipt(metadata).put(field, field.endsWith("allowed") || field.endsWith("verified") ? true : "foreign");
                server.enqueue(new MockResponse().setBody(wrong.toString()));
                assertThrows(JSONException.class, () -> api.uploadCaptureVideo(file, metadata, IP)); server.takeRequest();
            }
            for (boolean extra : List.of(false, true)) {
                JSONObject wrong = receipt(metadata); if (extra) wrong.put("extra", 1); else wrong.remove("status");
                server.enqueue(new MockResponse().setBody(wrong.toString()));
                assertThrows(JSONException.class, () -> api.uploadCaptureVideo(file, metadata, IP)); server.takeRequest();
            }
        }
    }
    @Test public void mismatchedOrUnsealedOriginalCannotMakeAnHttpRequest() throws Exception {
        String metadata = envelope(); File file = raw();
        try (MockWebServer server = new MockWebServer()) {
            DocScanApi api = api(server);
            Files.write(file.toPath(), new byte[]{9,8,7});
            assertThrows(java.io.IOException.class, () -> api.uploadCaptureVideo(file, metadata, IP));
            Files.write(file.toPath(), RAW);
            JSONObject unsealed = new JSONObject(metadata); unsealed.getJSONObject("journal").put("state", "unknown");
            assertThrows(JSONException.class, () -> api.uploadCaptureVideo(file, unsealed.toString(), IP));
            assertEquals(0, server.getRequestCount());
        }
    }
    @Test public void peerCheckUsesTheSideEffectFreeWholeStateInventoryAndRejectsOtherOwners() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            DocScanApi api = api(server);
            server.enqueue(new MockResponse().setBody(new JSONObject().put("devices", new JSONArray()
                    .put(peer(9007199254740993L, 7, "analyzing"))).toString()));
            assertEquals(IP, api.captureVideoPeer("device-test", 7, 9007199254740993L));
            assertEquals("/v1/glasses/state", server.takeRequest().getPath());
            for (JSONObject wrong : List.of(peer(9007199254740994L, 7, "reading"), peer(9007199254740993L, 8, "reading"),
                    peer(9007199254740993L, 7, "closed"), peer(9007199254740993L, 7, "writing_done"))) {
                server.enqueue(new MockResponse().setBody(new JSONObject().put("devices", new JSONArray().put(wrong)).toString()));
                DocScanApi.ApiException error = assertThrows(DocScanApi.ApiException.class,
                        () -> api.captureVideoPeer("device-test", 7, 9007199254740993L));
                assertEquals(409, error.getStatusCode()); server.takeRequest();
            }
            server.enqueue(new MockResponse().setBody(new JSONObject().put("devices", new JSONArray()
                    .put(peer(9007199254740993L, 7, "reading"))
                    .put(peer(9007199254740993L, 7, "capturing").put("device_id", "other"))).toString()));
            assertEquals(409, assertThrows(DocScanApi.ApiException.class,
                    () -> api.captureVideoPeer("device-test", 7, 9007199254740993L)).getStatusCode());
            server.takeRequest();
            server.enqueue(new MockResponse().setBody("{\"devices\":[]}"));
            assertEquals(503, assertThrows(DocScanApi.ApiException.class,
                    () -> api.captureVideoPeer("device-test", 7, 9007199254740993L)).getStatusCode());
        }
    }
    @Test public void largeOriginalStreamsAsAFileAndRedirectsCannotReplayItToAnotherRoute() throws Exception {
        File file=raw(); MessageDigest digest=MessageDigest.getInstance("SHA-256");
        byte[] chunk=new byte[64*1024]; java.util.Arrays.fill(chunk,(byte)57);
        try (var output=new java.io.FileOutputStream(file)) {
            output.write(RAW); digest.update(RAW);
            for(int i=0;i<144;i++) { output.write(chunk); digest.update(chunk); }
        }
        StringBuilder sha=new StringBuilder(); for(byte item:digest.digest()) sha.append(String.format("%02x",item & 255));
        JSONObject data=new JSONObject(envelope()); data.getJSONObject("journal").put("bytes",file.length()).put("sha256",sha.toString());
        String metadata=data.toString(); JSONObject ack=receipt(metadata).put("bytes",file.length()).put("sha256",sha.toString());
        try (MockWebServer server=new MockWebServer()) {
            server.setBodyLimit(0); DocScanApi api=api(server);
            server.enqueue(new MockResponse().setBody(ack.toString()));
            assertEquals(file.length(),api.uploadCaptureVideo(file,metadata,IP).getLong("bytes"));
            RecordedRequest request=server.takeRequest(); assertTrue(request.getBodySize() > file.length());
            assertEquals(0,request.getBody().size()); assertEquals("/v1/capture-videos",request.getPath());
            server.enqueue(new MockResponse().setResponseCode(307).addHeader("Location",server.url("/v1/exam-sessions/7/finalize-reading")));
            assertEquals(307,assertThrows(DocScanApi.ApiException.class,() -> api.uploadCaptureVideo(file,metadata,IP)).getStatusCode());
            assertEquals("/v1/capture-videos",server.takeRequest().getPath()); assertEquals(2,server.getRequestCount());
            assertTrue(file.isFile());
        }
    }
    @Test public void closedComparisonTransportCannotStartANewVideoCallAndLeavesOrdinaryRequestsUsable() throws Exception {
        try (MockWebServer server=new MockWebServer()) {
            DocScanApi api=api(server); String metadata=envelope(); File file=raw();
            server.enqueue(new MockResponse().setBody(receipt(metadata).toString()));
            api.cancelCaptureVideoTransfers();
            assertThrows(java.io.IOException.class,() -> api.uploadCaptureVideo(file,metadata,IP));
            assertEquals(0,server.getRequestCount());
            assertEquals("stored",api.health().getString("status"));
            assertEquals("/health",server.takeRequest().getPath());
        }
    }
}
