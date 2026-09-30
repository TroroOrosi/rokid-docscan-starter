package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import dev.rokid.docscanrelay.study.AnswerBundle;
import dev.rokid.docscanrelay.study.AnswerItem;
import java.io.IOException;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

// Robolectric, like study.AnswerBundleTest: the plain unit-test Android stub
// jar throws "not mocked" for org.json.JSONObject.toString()/optString().
@RunWith(RobolectricTestRunner.class)
@Config(manifest = Config.NONE, sdk = 28)
public class DocScanApiAnswerBundleTest {
    private static final String BODY = "{\"schema_version\":1,"
            + "\"session_id\":\"7\",\"input_digest\":\"" + "a".repeat(64) + "\","
            + "\"revision\":3,\"items\":[{\"group_id\":\"g1\",\"group_label\":\"第1問\","
            + "\"question_id\":\"q10\",\"question_label\":\"問1\",\"answer\":\"x = 2\","
            + "\"status\":\"ready\",\"issue\":\"\"},{\"group_id\":\"g1\","
            + "\"group_label\":\"第1問\",\"question_id\":\"q11\",\"question_label\":\"問2\","
            + "\"answer\":\"\",\"status\":\"pending\",\"issue\":\"未解答\"}]}";

    private DocScanApi api(MockWebServer server) {
        return new DocScanApi(
                server.url("/").toString().replaceAll("/$", ""),
                "",
                new ClientIdentity("test", "test/1", "test"));
    }

    @Test
    public void parsesTheBundleAndAsksTheRightPath() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            server.enqueue(new MockResponse().setBody(BODY));

            AnswerBundle bundle = api(server).answerBundle(7);

            RecordedRequest request = server.takeRequest();
            assertEquals("/v1/exam-sessions/7/answer-bundle", request.getPath());
            assertEquals("GET", request.getMethod());
            assertEquals("7", bundle.sessionId);
            assertEquals(3, bundle.revision);
            assertEquals(2, bundle.items.size());
            assertEquals("x = 2", bundle.items.get(0).answer);
            assertEquals(AnswerItem.Status.PENDING, bundle.items.get(1).status);
        }
    }

    @Test
    public void surfacesTheServerRefusal() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            server.enqueue(new MockResponse().setResponseCode(409)
                    .setBody("{\"detail\":\"call finalize-reading first\"}"));

            DocScanApi.ApiException error = assertThrows(
                    DocScanApi.ApiException.class, () -> api(server).answerBundle(7));

            assertEquals(409, error.getStatusCode());
            // ApiException composes "HTTP <code>: <detail>"
            // (DocScanApi.java:178), so match the detail, not the whole text.
            assertTrue(error.getMessage().contains("call finalize-reading first"));
        }
    }

    @Test public void stateNotificationCarriesAuthenticationAndNullableSessionIdentity() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            server.enqueue(new MockResponse().setBody("{}"));
            DocScanApi api = new DocScanApi(server.url("/").toString(), "test-secret",
                    new ClientIdentity("test", "test", "test"));
            api.glassesState("glasses-1", null, 2, 1, "capturing");
            RecordedRequest request = server.takeRequest();
            assertEquals("/v1/glasses/state", request.getPath());
            assertEquals("POST", request.getMethod());
            assertEquals("Bearer test-secret", request.getHeader("Authorization"));
            org.json.JSONObject state = new org.json.JSONObject(request.getBody().readUtf8());
            assertTrue(state.isNull("session_id"));
            assertEquals(2, state.getLong("generation"));
            assertEquals(1, state.getLong("sequence"));
            assertEquals("capturing", state.getString("phase"));
        }
    }
    @Test public void exitNotificationSurvivesCancellingThePhotoRequests() throws Exception {
        java.util.concurrent.CountDownLatch received = new java.util.concurrent.CountDownLatch(1);
        java.util.concurrent.CountDownLatch release = new java.util.concurrent.CountDownLatch(1);
        java.util.concurrent.ExecutorService notify = java.util.concurrent.Executors.newSingleThreadExecutor();
        try (MockWebServer server = new MockWebServer()) {
            server.setDispatcher(new okhttp3.mockwebserver.Dispatcher() {
                @Override public MockResponse dispatch(RecordedRequest request) throws InterruptedException {
                    received.countDown();
                    release.await(2, java.util.concurrent.TimeUnit.SECONDS);
                    return new MockResponse().setBody("{}");
                }
            });
            DocScanApi api = api(server);
            java.util.concurrent.Future<?> state = notify.submit(() -> {
                try { api.glassesState("glasses-1", 7L, 2, 3, "closed"); }
                catch (Exception error) { throw new RuntimeException(error); }
            });
            assertTrue(received.await(2, java.util.concurrent.TimeUnit.SECONDS));
            api.cancelRequests();
            release.countDown();
            state.get(2, java.util.concurrent.TimeUnit.SECONDS);
        } finally { release.countDown(); notify.shutdownNow(); }
    }

}
