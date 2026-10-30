package dev.rokid.docscanrelay;

import static org.junit.Assert.*;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;
import org.json.JSONException;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

@RunWith(RobolectricTestRunner.class)
@Config(manifest = Config.NONE, sdk = 32)
public class DocScanApiCaptureTest {
    private static final byte[] ORIGINAL = {1, 2, 3};
    private static final String JPEG_SHA = "039058c6f2c0cb492c533b0a4d14ef77cc0f78abccced5287d84a1a2011cfb81";
    private static final String SESSION = "11111111-2222-3333-4444-555555555555";

    @Test public void nativeMultipartCarriesTheExactOriginalAndSevenExplicitUnknowns() throws Exception {
        CaptureProvenance source = CaptureProvenance.nativeStill(ORIGINAL, 4032, 3024,
                null, null, null, null, null, null, null).bind(SESSION, 2, 90);
        try (MockWebServer server = new MockWebServer()) {
            server.enqueue(new MockResponse().setBody(receipt(source).toString()));
            JSONObject response = api(server).uploadPage(17, 2, ORIGINAL, "", 90, 1234, source);
            RecordedRequest request = server.takeRequest();
            assertEquals("/v1/documents/17/pages", request.getPath());
            assertArrayEquals(ORIGINAL, part(request, "image"));
            assertEquals("90", new String(part(request, "image_rotation"), StandardCharsets.UTF_8));
            assertEquals("1234", new String(part(request, "captured_at_ms"), StandardCharsets.UTF_8));
            JSONObject sent = new JSONObject(new String(part(request, "capture_provenance"), StandardCharsets.UTF_8));
            assertEquals(16, sent.length());
            assertEquals(1, sent.getInt("schema"));
            assertEquals("native_still", sent.getString("source_kind"));
            assertEquals(source.captureId, sent.getString("capture_id"));
            assertEquals(JPEG_SHA, sent.getString("jpeg_sha256"));
            assertEquals(SESSION, sent.getString("local_session_id"));
            assertEquals(4032, sent.getInt("width")); assertEquals(3024, sent.getInt("height"));
            assertEquals(2, sent.getInt("page_index")); assertEquals(90, sent.getInt("rotation_degrees"));
            for (String key : List.of("image_timestamp_ns", "result_timestamp_ns", "frame_number",
                    "exposure_ns", "sensitivity_iso", "af_state", "ae_state")) {
                assertTrue("unknown metadata must be present: " + key, sent.has(key));
                assertSame(JSONObject.NULL, sent.get(key));
            }
            assertEquals("c".repeat(64), response.getString("canonical_image_sha256"));
            JSONObject invented = receipt(source);
            invented.getJSONObject("capture_provenance").put("af_state", 0);
            server.enqueue(new MockResponse().setBody(invented.toString()));
            assertThrows(JSONException.class, () -> api(server).uploadPage(17, 2, ORIGINAL, "", 90, 1234, source));
        }
    }

    @Test public void nativeReceiptRejectsMissingForeignOrCoercedIdentity() throws Exception {
        CaptureProvenance source = knownSource();
        String correct = receipt(source).toString();
        List<String> rejected = new ArrayList<>();
        rejected.add("{}");
        rejected.add(receipt(source).put("capture_provenance", JSONObject.NULL).toString());
        rejected.add(receipt(source).put("canonical_image_sha256", "C".repeat(64)).toString());
        rejected.add(receipt(source).put("canonical_image_sha256", 123).toString());
        rejected.add(correct.replace("\"document_id\":17", "\"document_id\":18"));
        rejected.add(correct.replace("\"page_index\":2", "\"page_index\":3"));
        rejected.add(correct.replace(source.captureId, UUID.randomUUID().toString()));
        rejected.add(correct.replace(SESSION, UUID.randomUUID().toString()));
        rejected.add(correct.replace(JPEG_SHA, "a".repeat(64)));
        rejected.add(correct.replace("\"native_still\"", "\"preview\""));
        for (String field : List.of("schema", "width", "height", "page_index", "rotation_degrees",
                "image_timestamp_ns", "result_timestamp_ns", "frame_number", "exposure_ns",
                "sensitivity_iso", "af_state", "ae_state", "document_id")) {
            rejected.add(correct.replaceAll("(\"" + field + "\":)([0-9]+)", "$1\"$2\""));
            rejected.add(correct.replaceAll("(\"" + field + "\":)([0-9]+)", "$1$2.0"));
            rejected.add(correct.replaceAll("(\"" + field + "\":)([0-9]+)", "$1true"));
            JSONObject changed = receipt(source);
            if (field.equals("document_id")) changed.put(field, 18);
            else {
                JSONObject capture = changed.getJSONObject("capture_provenance");
                capture.put(field, capture.getLong(field) + 1);
            }
            rejected.add(changed.toString());
        }
        JSONObject missing = receipt(source);
        missing.getJSONObject("capture_provenance").remove("ae_state");
        rejected.add(missing.toString());
        JSONObject extra = receipt(source);
        extra.getJSONObject("capture_provenance").put("generation", 1);
        rejected.add(extra.toString());
        JSONObject differentKey = receipt(source);
        differentKey.getJSONObject("capture_provenance").remove("ae_state");
        differentKey.getJSONObject("capture_provenance").put("generation", 1);
        rejected.add(differentKey.toString());
        JSONObject oversized = receipt(source);
        oversized.getJSONObject("capture_provenance").put("capture_id", "x".repeat(8192));
        rejected.add(oversized.toString());
        try (MockWebServer server = new MockWebServer()) {
            DocScanApi api = api(server);
            for (int index = 0; index < rejected.size(); index++) {
                server.enqueue(new MockResponse().setBody(rejected.get(index)));
                JSONException error = assertThrows("invalid receipt " + index, JSONException.class,
                        () -> api.uploadPage(17, 2, ORIGINAL, "", 90, 1234, source));
                assertTrue("receipt errors must be short Japanese without raw metadata",
                        List.of("撮影情報の受領を確認できません", "撮影情報が大きすぎます").contains(error.getMessage()));
                assertNotNull(server.takeRequest());
            }
            server.enqueue(new MockResponse().setBody(correct));
            api.uploadPage(17, 2, ORIGINAL, "", 90, 1234, source);
            JSONObject sent = new JSONObject(new String(part(server.takeRequest(), "capture_provenance"), StandardCharsets.UTF_8));
            assertEquals(9_007_199_254_740_993L, sent.getLong("image_timestamp_ns"));
            assertEquals(9_007_199_254_740_993L, sent.getLong("result_timestamp_ns"));
            assertEquals(rejected.size() + 1, server.getRequestCount());
        }
    }

    @Test public void aDifferentOriginalOrAssociationIsRejectedBeforeAnyHttp() throws Exception {
        CaptureProvenance source = knownSource();
        CaptureProvenance unbound = CaptureProvenance.nativeStill(ORIGINAL, 4032, 3024,
                null, null, null, null, null, null, null);
        try (MockWebServer server = new MockWebServer()) {
            DocScanApi api = api(server);
            assertThrows(IllegalArgumentException.class, () -> api.uploadPage(17, 2, ORIGINAL, "", 90, 1, unbound));
            assertThrows(IllegalArgumentException.class, () -> api.uploadPage(17, 2, new byte[]{3, 2, 1}, "", 90, 1, source));
            assertThrows(IllegalArgumentException.class, () -> api.uploadPage(17, 1, ORIGINAL, "", 90, 1, source));
            assertThrows(IllegalArgumentException.class, () -> api.uploadPage(17, 2, ORIGINAL, "", 270, 1, source));
            assertEquals(0, server.getRequestCount());
        }
    }

    @Test public void oldPhotosAndBothLegacyOverloadsNeedNoNativeReceipt() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            DocScanApi api = api(server);
            for (int call = 0; call < 3; call++) server.enqueue(new MockResponse().setBody("{}"));
            api.uploadPage(17, 2, ORIGINAL, "", 90);
            api.uploadPage(17, 2, ORIGINAL, "", 90, 1234);
            api.uploadPage(17, 2, ORIGINAL, "", 90, 1234, null);
            for (int call = 0; call < 3; call++) {
                RecordedRequest request = server.takeRequest();
                assertFalse(request.getBody().clone().readUtf8().contains("name=\"capture_provenance\""));
                assertArrayEquals(ORIGINAL, part(request, "image"));
            }
        }
    }

    private static CaptureProvenance knownSource() {
        return CaptureProvenance.nativeStill(ORIGINAL, 4032, 3024,
                9_007_199_254_740_993L, 9_007_199_254_740_993L, 5L, 25_000_000L, 400, 0, 2)
                .bind(SESSION, 2, 90);
    }

    private static JSONObject receipt(CaptureProvenance source) throws JSONException {
        JSONObject nativeCapture = new JSONObject().put("schema", 1).put("source_kind", "native_still")
                .put("capture_id", source.captureId).put("jpeg_sha256", JPEG_SHA)
                .put("width", 4032).put("height", 3024).put("local_session_id", SESSION)
                .put("page_index", 2).put("rotation_degrees", 90)
                .put("image_timestamp_ns", source.imageTimestampNanos == null ? JSONObject.NULL : source.imageTimestampNanos)
                .put("result_timestamp_ns", source.resultTimestampNanos == null ? JSONObject.NULL : source.resultTimestampNanos)
                .put("frame_number", source.frameNumber == null ? JSONObject.NULL : source.frameNumber)
                .put("exposure_ns", source.exposureNanos == null ? JSONObject.NULL : source.exposureNanos)
                .put("sensitivity_iso", source.sensitivityIso == null ? JSONObject.NULL : source.sensitivityIso)
                .put("af_state", source.afState == null ? JSONObject.NULL : source.afState)
                .put("ae_state", source.aeState == null ? JSONObject.NULL : source.aeState);
        return new JSONObject().put("document_id", 17).put("page_index", 2)
                .put("capture_provenance", nativeCapture).put("canonical_image_sha256", "c".repeat(64));
    }

    private static DocScanApi api(MockWebServer server) {
        return new DocScanApi(server.url("/").toString(), "", new ClientIdentity("test", "test", "test"));
    }

    private static byte[] part(RecordedRequest request, String name) {
        String boundary = request.getHeader("Content-Type").split("boundary=", 2)[1];
        String body = request.getBody().clone().readString(StandardCharsets.ISO_8859_1);
        int header = body.indexOf("Content-Disposition: form-data; name=\"" + name + "\"");
        assertTrue("multipart field missing: " + name, header >= 0);
        int start = body.indexOf("\r\n\r\n", header) + 4;
        int end = body.indexOf("\r\n--" + boundary, start);
        assertTrue(end >= start);
        return body.substring(start, end).getBytes(StandardCharsets.ISO_8859_1);
    }
}
