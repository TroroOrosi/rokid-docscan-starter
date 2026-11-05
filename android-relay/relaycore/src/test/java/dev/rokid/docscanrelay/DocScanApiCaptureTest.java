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

    @Test public void optionalInspectionOriginKeepsTheOriginalReceiptContract() throws Exception {
        CaptureProvenance source = knownSource();
        CaptureInspectionOrigin origin = new CaptureInspectionOrigin(
                new CaptureInspectionOrigin.Context("glasses:1", Long.MAX_VALUE), source, 17);
        try (MockWebServer server = new MockWebServer()) {
            // The diagnostic is disabled/unbound, or absent on an old server: image ACK still succeeds.
            server.enqueue(new MockResponse().setBody(receipt(source).put("capture_inspection",
                    new JSONObject().put("status", "unbound").put("applicable", false)).toString()));
            api(server).uploadPage(17, 2, ORIGINAL, "", 90, 1234, source, origin);
            RecordedRequest request = server.takeRequest();
            JSONObject sent = new JSONObject(new String(part(request, "inspection_origin"), StandardCharsets.UTF_8));
            assertEquals(6, sent.length());
            assertEquals(1, sent.getInt("schema"));
            assertEquals("glasses:1", sent.getString("device_id"));
            assertEquals(Long.MAX_VALUE, sent.getLong("generation"));
            assertEquals(17, sent.getLong("document_id"));
            assertEquals(SESSION, sent.getString("local_session_id"));
            assertEquals(source.captureId, sent.getString("capture_id"));
            assertArrayEquals(ORIGINAL, part(request, "image"));
            assertTrue(part(request, "inspection_origin").length <= 2048);
            JSONObject badImageReceipt = receipt(source);
            badImageReceipt.remove("canonical_image_sha256");
            badImageReceipt.put("capture_inspection", new JSONObject().put("status", "queued"));
            server.enqueue(new MockResponse().setBody(badImageReceipt.toString()));
            assertThrows(JSONException.class,
                    () -> api(server).uploadPage(17, 2, ORIGINAL, "", 90, 1234, source, origin));
        }
    }

    @Test public void aForeignOrMissingDiagnosticOriginIsOmittedWithoutBlockingTheImage() throws Exception {
        CaptureProvenance source = knownSource();
        CaptureInspectionOrigin.Context context = new CaptureInspectionOrigin.Context("glasses", 0);
        CaptureInspectionOrigin foreignDocument = new CaptureInspectionOrigin(context, source, 18);
        CaptureInspectionOrigin foreignCapture = new CaptureInspectionOrigin(context, knownSource(), 17);
        try (MockWebServer server = new MockWebServer()) {
            for (CaptureInspectionOrigin origin : new CaptureInspectionOrigin[]{null, foreignDocument, foreignCapture}) {
                server.enqueue(new MockResponse().setBody(receipt(source).toString()));
                api(server).uploadPage(17, 2, ORIGINAL, "", 90, 1234, source, origin);
                RecordedRequest request = server.takeRequest();
                assertFalse(request.getBody().clone().readUtf8().contains("name=\"inspection_origin\""));
                assertArrayEquals(ORIGINAL, part(request, "image"));
            }
        }
        assertThrows(IllegalArgumentException.class, () -> new CaptureInspectionOrigin(context, source, 0));
        assertThrows(IllegalArgumentException.class,
                () -> new CaptureInspectionOrigin(context, source, 1L + Integer.MAX_VALUE));
        assertThrows(IllegalArgumentException.class, () -> new CaptureInspectionOrigin.Context("bad device", 1));
        assertThrows(IllegalArgumentException.class, () -> new CaptureInspectionOrigin.Context("glasses", -1));
    }

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

    @Test public void zslMultipartRequiresTheSameKindAndExactSourceExposureInItsReceipt() throws Exception {
        CaptureProvenance source = CaptureProvenance.zslReprocess(ORIGINAL, 4032, 3024,
                9_007_199_254_740_993L, 9_007_199_254_740_993L, null, null, null, null, null)
                .bind(SESSION, 2, 90);
        try (MockWebServer server = new MockWebServer()) {
            server.enqueue(new MockResponse().setBody(receipt(source).toString()));
            api(server).uploadPage(17, 2, ORIGINAL, "", 90, 1234, source);
            RecordedRequest request = server.takeRequest();
            assertArrayEquals(ORIGINAL, part(request, "image"));
            JSONObject sent = new JSONObject(new String(
                    part(request, "capture_provenance"), StandardCharsets.UTF_8));
            assertEquals(16, sent.length());
            assertEquals("zsl_reprocess", sent.getString("source_kind"));
            assertEquals(9_007_199_254_740_993L, sent.getLong("image_timestamp_ns"));
            assertEquals(9_007_199_254_740_993L, sent.getLong("result_timestamp_ns"));
            for (String key : List.of("frame_number", "exposure_ns", "sensitivity_iso", "af_state", "ae_state")) {
                assertSame(JSONObject.NULL, sent.get(key));
            }
            for (String field : List.of("source_kind", "result_timestamp_ns")) {
                JSONObject wrong = receipt(source);
                wrong.getJSONObject("capture_provenance").put(field,
                        field.equals("source_kind") ? "native_still" : JSONObject.NULL);
                server.enqueue(new MockResponse().setBody(wrong.toString()));
                assertThrows(JSONException.class, () -> api(server).uploadPage(
                        17, 2, ORIGINAL, "", 90, 1234, source));
                assertNotNull(server.takeRequest());
            }
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
        JSONObject nativeCapture = new JSONObject().put("schema", 1).put("source_kind", source.sourceKind)
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

    // AGENT_APPROVED=1: diagnostic feedback never changes the native image receipt.
    @Test public void diagnosticResultRequiresTheExactCaptureAndKeepsNoIssueNeutral() throws Exception {
        CaptureProvenance source = knownSource();
        var context = new CaptureInspectionOrigin.Context("glasses:1", 42);
        var binding = CaptureInspectionFeedback.Binding.fromReceipt(context, source, 17,
                receipt(source).put("capture_inspection", feedbackRegistration("queued")));
        assertNotNull(binding);
        JSONObject completed = feedbackReply(receipt(source).getJSONObject("capture_provenance"), context, 17, "c".repeat(64), "issue");
        assertEquals(CaptureInspectionFeedback.Outcome.ISSUE, binding.decode(completed));
        completed.getJSONObject("result").getJSONArray("parts").getJSONObject(0)
                .getJSONArray("observations").getJSONObject(0).put("status", "no_issue_observed");
        assertEquals(CaptureInspectionFeedback.Outcome.NO_ISSUE_OBSERVED, binding.decode(completed));
        assertEquals("", new CaptureInspectionFeedback.Notice(binding, CaptureInspectionFeedback.Outcome.NO_ISSUE_OBSERVED).text());
        assertEquals("P3 要確認", new CaptureInspectionFeedback.Notice(binding, CaptureInspectionFeedback.Outcome.ISSUE).text());
        assertEquals("P3 未確認", new CaptureInspectionFeedback.Notice(binding, CaptureInspectionFeedback.Outcome.UNKNOWN).text());
        for (String key : List.of("device_id", "generation", "document_id", "local_session_id", "capture_id", "canonical_image_sha256")) {
            JSONObject wrong = new JSONObject(completed.toString());
            Object old = wrong.getJSONObject("owner").get(key);
            wrong.getJSONObject("owner").put(key, old instanceof Number ? ((Number) old).longValue() + 1 : "different");
            assertThrows(key, JSONException.class, () -> binding.decode(wrong));
        }
        JSONObject wrongHash = new JSONObject(completed.toString());
        wrongHash.getJSONObject("result").getJSONArray("parts").getJSONObject(0)
                .getJSONObject("owner").put("canonical_image_sha256", "d".repeat(64));
        assertThrows(JSONException.class, () -> binding.decode(wrongHash));
        completed.put("applicable", false);
        assertEquals(CaptureInspectionFeedback.Outcome.UNKNOWN, binding.decode(completed));
    }

    @Test public void diagnosticClaimsAndTypedIdentityCannotAuthorizeOrSilentlyCoerce() throws Exception {
        CaptureProvenance source = knownSource(); var context = new CaptureInspectionOrigin.Context("glasses:1", 42);
        var binding = CaptureInspectionFeedback.Binding.fromReceipt(context, source, 17,
                receipt(source).put("capture_inspection", feedbackRegistration("queued")));
        for (String key : List.of("generation", "document_id")) for (Object replacement : List.of("42", 42.0, true)) {
            JSONObject wrong = feedbackReply(receipt(source).getJSONObject("capture_provenance"), context, 17, "c".repeat(64), "issue");
            wrong.getJSONObject("owner").put(key, replacement);
            assertThrows(JSONException.class, () -> binding.decode(wrong));
        }
        for (String key : List.of("can_authorize_capture", "all_pages_or_characters_verified", "auto_registration_allowed")) {
            JSONObject wrong = feedbackReply(receipt(source).getJSONObject("capture_provenance"), context, 17, "c".repeat(64), "issue");
            wrong.put(key, true);
            assertThrows(JSONException.class, () -> binding.decode(wrong));
        }
        JSONObject noViewer = feedbackReply(receipt(source).getJSONObject("capture_provenance"), context, 17, "c".repeat(64), "no_issue_observed");
        noViewer.getJSONObject("result").getJSONArray("parts").getJSONObject(0).getJSONArray("observations")
                .getJSONObject(0).put("image_viewer_used", false);
        assertThrows(JSONException.class, () -> binding.decode(noViewer));
        assertNull(CaptureInspectionFeedback.Binding.fromReceipt(context, source, 17, receipt(source)));
        assertNull(CaptureInspectionFeedback.Binding.fromReceipt(context, source, 17,
                receipt(source).put("capture_inspection", feedbackRegistration("disabled").put("inspection_id", JSONObject.NULL))));
    }

    @Test public void inspectionGetIsAuthenticatedBoundedAndDoesNotRetryOrFollowRedirects() throws Exception {
        CaptureProvenance source = knownSource(); var context = new CaptureInspectionOrigin.Context("glasses:1", 42);
        var binding = CaptureInspectionFeedback.Binding.fromReceipt(context, source, 17,
                receipt(source).put("capture_inspection", feedbackRegistration("queued")));
        try (MockWebServer server = new MockWebServer()) {
            DocScanApi destination = new DocScanApi(server.url("/").toString(), "test-key", new ClientIdentity("test", "test", "test"));
            server.enqueue(new MockResponse().setBody(feedbackReply(receipt(source).getJSONObject("capture_provenance"), context, 17, "c".repeat(64), "issue").toString()));
            assertEquals(CaptureInspectionFeedback.Outcome.ISSUE, binding.decode(destination.captureInspection(binding).execute()));
            RecordedRequest request = server.takeRequest();
            assertEquals("GET", request.getMethod());
            assertEquals("Bearer test-key", request.getHeader("Authorization"));
            assertEquals("glasses:1", request.getRequestUrl().queryParameter("device_id"));
            assertEquals("42", request.getRequestUrl().queryParameter("generation"));
            assertEquals(source.captureId, request.getRequestUrl().queryParameter("capture_id"));
            server.enqueue(new MockResponse().setBody(" ".repeat(CaptureInspectionFeedback.MAX_RESPONSE_BYTES + 1)));
            assertThrows(java.io.IOException.class, () -> destination.captureInspection(binding).execute());
            server.enqueue(new MockResponse().setResponseCode(302).setHeader("Location", server.url("/unexpected")));
            assertThrows(java.io.IOException.class, () -> destination.captureInspection(binding).execute());
            assertEquals(3, server.getRequestCount());
        }
    }

    @Test public void finiteDiagnosticReaderStopsPendingWorkAndDiscardsLateCaptureResults() throws Exception {
        CaptureProvenance source = knownSource(); var context = new CaptureInspectionOrigin.Context("glasses:1", 42);
        var binding = CaptureInspectionFeedback.Binding.fromReceipt(context, source, 17,
                receipt(source).put("capture_inspection", feedbackRegistration("queued")));
        var notices = new java.util.concurrent.LinkedBlockingQueue<CaptureInspectionFeedback.Notice>();
        var reads = new java.util.concurrent.atomic.AtomicInteger();
        try (var feedback = new CaptureInspectionFeedback(java.util.concurrent.Executors.newSingleThreadScheduledExecutor(),
                System::nanoTime, 2, 1, 5000)) {
            feedback.start(binding, ignored -> new CaptureInspectionFeedback.Query() {
                public JSONObject execute() throws Exception {
                    reads.incrementAndGet();
                    return feedbackReply(receipt(source).getJSONObject("capture_provenance"), context, 17, "c".repeat(64), "issue")
                            .put("status", "queued").put("applicable", false).put("result", JSONObject.NULL);
                }
                public void cancel() { }
            }, () -> true, notices::add);
            assertEquals(CaptureInspectionFeedback.Outcome.UNKNOWN, notices.poll(3, java.util.concurrent.TimeUnit.SECONDS).outcome);
            assertEquals(2, reads.get());
        }
        java.util.concurrent.CountDownLatch reading = new java.util.concurrent.CountDownLatch(1), finish = new java.util.concurrent.CountDownLatch(1);
        var current = new java.util.concurrent.atomic.AtomicBoolean(true);
        var cancellations = new java.util.concurrent.atomic.AtomicInteger(); notices.clear();
        try (var feedback = new CaptureInspectionFeedback()) {
            feedback.start(binding, ignored -> new CaptureInspectionFeedback.Query() {
                public JSONObject execute() throws Exception {
                    reading.countDown(); finish.await(2, java.util.concurrent.TimeUnit.SECONDS);
                    return feedbackReply(receipt(source).getJSONObject("capture_provenance"), context, 17, "c".repeat(64), "issue");
                }
                public void cancel() { cancellations.incrementAndGet(); finish.countDown(); }
            }, current::get, notices::add);
            assertTrue(reading.await(2, java.util.concurrent.TimeUnit.SECONDS));
            current.set(false); feedback.clear();
            assertNull(notices.poll(100, java.util.concurrent.TimeUnit.MILLISECONDS));
            assertEquals(1, cancellations.get());
        }
    }

    static JSONObject feedbackRegistration(String status) throws JSONException {
        return new JSONObject().put("inspection_id", "a".repeat(64)).put("status", status).put("reason", JSONObject.NULL)
                .put("scope", "diagnostic_only").put("applicable", false)
                .put("all_pages_or_characters_verified", false).put("auto_registration_allowed", false);
    }

    static JSONObject feedbackReply(JSONObject capture, CaptureInspectionOrigin.Context context, long document,
                                    String canonical, String observation) throws JSONException {
        JSONObject owner = new JSONObject().put("kind", "native_capture").put("policy", "bounded_diagnostic_v1")
                .put("source_ip", "testclient").put("device_id", context.deviceId).put("generation", context.generation)
                .put("document_id", document).put("local_session_id", capture.getString("local_session_id"))
                .put("capture_id", capture.getString("capture_id")).put("capture_provenance", capture)
                .put("canonical_image_sha256", canonical);
        JSONObject part = new JSONObject().put("inspection_id", "b".repeat(64)).put("manifest_sha256", "d".repeat(64))
                .put("owner", new JSONObject(owner.toString())).put("scope", "bounded_regions_only")
                .put("independently_verified", false).put("calibrated", false)
                .put("all_pages_or_characters_verified", false).put("auto_registration_allowed", false)
                .put("observations", new org.json.JSONArray().put(new JSONObject().put("image_id", "source_original")
                        .put("status", observation).put("image_viewer_used", true)
                        .put("reasons", new org.json.JSONArray().put("private AI reason must never reach HUD"))));
        return feedbackRegistration("completed").put("applicable", true).put("can_authorize_capture", false)
                .put("owner", owner).put("result", new JSONObject().put("parts", new org.json.JSONArray().put(part))
                        .put("all_pages_or_characters_verified", false).put("auto_registration_allowed", false));
    }

    @Test public void replacingTheLatestDiagnosticKeepsOneInFlightAndNeverEmitsTheOldReply() throws Exception {
        var context = new CaptureInspectionOrigin.Context("glasses:1", 42);
        CaptureProvenance first = knownSource(), second = knownSource();
        var a = CaptureInspectionFeedback.Binding.fromReceipt(context, first, 17, receipt(first).put("capture_inspection", feedbackRegistration("queued")));
        var b = CaptureInspectionFeedback.Binding.fromReceipt(context, second, 17, receipt(second).put("capture_inspection", feedbackRegistration("queued")));
        var entered = new java.util.concurrent.CountDownLatch(1); var release = new java.util.concurrent.CountDownLatch(1);
        var running = new java.util.concurrent.atomic.AtomicInteger(); var peak = new java.util.concurrent.atomic.AtomicInteger();
        var notices = new java.util.concurrent.LinkedBlockingQueue<CaptureInspectionFeedback.Notice>();
        try (var feedback = new CaptureInspectionFeedback()) {
            CaptureInspectionFeedback.Reader reader = binding -> new CaptureInspectionFeedback.Query() {
                public JSONObject execute() throws Exception {
                    peak.accumulateAndGet(running.incrementAndGet(), Math::max);
                    try {
                        if (binding == a) { entered.countDown(); release.await(2, java.util.concurrent.TimeUnit.SECONDS); }
                        return feedbackReply(receipt(binding.source).getJSONObject("capture_provenance"), context, 17, "c".repeat(64), "issue");
                    } finally { running.decrementAndGet(); }
                }
                public void cancel() { release.countDown(); }
            };
            feedback.start(a, reader, () -> true, notices::add); assertTrue(entered.await(2, java.util.concurrent.TimeUnit.SECONDS));
            feedback.start(b, reader, () -> true, notices::add);
            assertSame(b, notices.poll(2, java.util.concurrent.TimeUnit.SECONDS).binding);
            assertEquals(1, peak.get()); assertNull(notices.poll(100, java.util.concurrent.TimeUnit.MILLISECONDS));
        }
    }

    @Test public void processingDiagnosticWaitsForItsBoundCompletedResult() throws Exception {
        for (String pending : List.of("processing", "deferred_answers", "deferred_queue_full")) {
            CaptureProvenance source = knownSource();
            var context = new CaptureInspectionOrigin.Context("glasses:1", 42);
            var binding = CaptureInspectionFeedback.Binding.fromReceipt(context, source, 17,
                    receipt(source).put("capture_inspection", feedbackRegistration("queued")));
            var notices = new java.util.concurrent.LinkedBlockingQueue<CaptureInspectionFeedback.Notice>();
            try (MockWebServer server = new MockWebServer();
                    var feedback = new CaptureInspectionFeedback(java.util.concurrent.Executors.newSingleThreadScheduledExecutor(),
                            System::nanoTime, 8, 1, 5000)) {
                DocScanApi destination = new DocScanApi(server.url("/").toString(), "test-key", new ClientIdentity("test", "test", "test"));
                JSONObject completed = feedbackReply(receipt(source).getJSONObject("capture_provenance"), context, 17, "c".repeat(64), "issue");
                // WorkStore.prepare_capture_inspection writes processing before running Work.
                server.enqueue(new MockResponse().setBody(new JSONObject(completed.toString())
                        .put("status", pending).put("applicable", false).put("result", JSONObject.NULL).toString()));
                server.enqueue(new MockResponse().setBody(completed.toString()));
                feedback.start(binding, destination::captureInspection, () -> true, notices::add);
                CaptureInspectionFeedback.Notice result = notices.poll(3, java.util.concurrent.TimeUnit.SECONDS);
                assertNotNull(result);
                assertEquals(CaptureInspectionFeedback.Outcome.ISSUE, result.outcome);
                assertSame(binding, result.binding);
                assertEquals(2, server.getRequestCount());
                assertNull(notices.poll(100, java.util.concurrent.TimeUnit.MILLISECONDS));
            }
        }
    }

    @Test public void elapsedDiagnosticBudgetDoesNotScheduleAnotherRead() throws Exception {
        CaptureProvenance source = knownSource(); var context = new CaptureInspectionOrigin.Context("glasses:1", 42);
        var binding = CaptureInspectionFeedback.Binding.fromReceipt(context, source, 17, receipt(source).put("capture_inspection", feedbackRegistration("queued")));
        var clock = new java.util.concurrent.atomic.AtomicLong(); var reads = new java.util.concurrent.atomic.AtomicInteger();
        var notices = new java.util.concurrent.LinkedBlockingQueue<CaptureInspectionFeedback.Notice>();
        try (var feedback = new CaptureInspectionFeedback(java.util.concurrent.Executors.newSingleThreadScheduledExecutor(), clock::get, 8, 0, 120_000)) {
            feedback.start(binding, ignored -> new CaptureInspectionFeedback.Query() {
                public JSONObject execute() throws Exception {
                    reads.incrementAndGet(); clock.set(java.util.concurrent.TimeUnit.SECONDS.toNanos(121));
                    return feedbackReply(receipt(source).getJSONObject("capture_provenance"), context, 17, "c".repeat(64), "issue")
                            .put("status", "queued").put("applicable", false).put("result", JSONObject.NULL);
                }
                public void cancel() { }
            }, () -> true, notices::add);
            assertEquals(CaptureInspectionFeedback.Outcome.UNKNOWN, notices.poll(2, java.util.concurrent.TimeUnit.SECONDS).outcome);
            assertEquals(1, reads.get());
        }
    }
}
