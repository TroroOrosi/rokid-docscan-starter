package dev.rokid.docscanhost;

import android.os.SystemClock;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import org.json.JSONException;
import org.json.JSONObject;

final class LoopbackHealth implements HostMonitor.HealthCheck {
    interface ConnectionFactory { HttpURLConnection open() throws IOException; }

    private static final int BODY_LIMIT = 4096;
    private final ConnectionFactory connections;

    LoopbackHealth() {
        this(() -> (HttpURLConnection) new URL("http://127.0.0.1:8000/health").openConnection());
    }

    LoopbackHealth(ConnectionFactory connections) { this.connections = connections; }

    @Override public boolean healthy() {
        HttpURLConnection connection = null;
        long deadline = SystemClock.elapsedRealtime() + 4_000;
        try {
            connection = connections.open();
            connection.setConnectTimeout(2_000);
            connection.setReadTimeout(2_000);
            connection.setInstanceFollowRedirects(false);
            connection.setUseCaches(false);
            connection.setRequestMethod("GET");
            connection.setRequestProperty("Accept", "application/json");
            if (connection.getResponseCode() != 200 || connection.getContentLengthLong() > BODY_LIMIT) {
                return false;
            }
            try (InputStream input = connection.getInputStream();
                 ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[512];
                while (SystemClock.elapsedRealtime() <= deadline && !Thread.currentThread().isInterrupted()) {
                    int count = input.read(buffer);
                    if (SystemClock.elapsedRealtime() > deadline) return false;
                    if (count == -1) {
                        JSONObject body = new JSONObject(bytes.toString(StandardCharsets.UTF_8.name()));
                        return "ok".equals(body.opt("status"));
                    }
                    if (bytes.size() + count > BODY_LIMIT) return false;
                    bytes.write(buffer, 0, count);
                }
                return false;
            }
        } catch (IOException | JSONException error) {
            return false;
        } finally {
            if (connection != null) connection.disconnect();
        }
    }
}
