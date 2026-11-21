package dev.rokid.docscanhost;

import static org.junit.Assert.*;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
public class LoopbackHealthTest {
    private static final class Response extends HttpURLConnection {
        int status = 200;
        String body = "{\"status\":\"ok\"}";
        boolean closed;
        Response() throws Exception { super(new URL("http://127.0.0.1:8000/health")); }
        public void connect() {}
        public void disconnect() { closed = true; }
        public boolean usingProxy() { return false; }
        public int getResponseCode() { return status; }
        public ByteArrayInputStream getInputStream() {
            return new ByteArrayInputStream(body.getBytes(StandardCharsets.UTF_8));
        }
    }

    @Test public void onlyBoundedHttp200StatusOkIsHealthyAndConnectionsClose() throws Exception {
        Response response = new Response();
        LoopbackHealth health = new LoopbackHealth(() -> response);
        assertTrue(health.healthy());
        assertTrue(response.closed);
        assertFalse(response.getInstanceFollowRedirects());
        assertEquals("GET", response.getRequestMethod());
        assertTrue(response.getConnectTimeout() > 0);
        assertTrue(response.getReadTimeout() > 0);
        response.status = 302;
        assertFalse(health.healthy());
        response.status = 200;
        response.body = "{\"status\":\"starting\"}";
        assertFalse(health.healthy());
        response.body = "{\"status\":\"ok\",\"extra\":\"" + "a".repeat(8192) + "\"}";
        assertFalse(health.healthy());
        response.body = "invalid json";
        assertFalse(health.healthy());
    }

    @Test public void networkErrorsAreUnavailable() {
        assertFalse(new LoopbackHealth(() -> { throw new IOException(); }).healthy());
    }
}
