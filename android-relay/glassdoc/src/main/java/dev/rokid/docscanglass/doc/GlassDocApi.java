package dev.rokid.docscanglass.doc;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.util.Objects;
import java.util.concurrent.TimeUnit;

import okhttp3.HttpUrl;
import okhttp3.MediaType;
import okhttp3.MultipartBody;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;

/**
 * Synchronous server client, spoken from the glasses.
 *
 * <p>Deliberately the same shape as the phone relay's {@code DocScanApi}: the
 * server contract has not changed, only which device speaks it. Measured
 * 2026-09-04, the glasses reach the server on their own Wi-Fi with
 * {@code /health} at 96-197 ms.
 *
 * <p>Call only from a background executor.
 */
final class GlassDocApi {

    private static final MediaType JSON =
            Objects.requireNonNull(MediaType.parse("application/json; charset=utf-8"));
    private static final MediaType JPEG =
            Objects.requireNonNull(MediaType.parse("image/jpeg"));

    private final OkHttpClient http = new OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(4, TimeUnit.MINUTES)
            .writeTimeout(60, TimeUnit.SECONDS)
            .callTimeout(5, TimeUnit.MINUTES)
            .retryOnConnectionFailure(true)
            .build();
    private final String baseUrl;

    GlassDocApi(String baseUrl) {
        String normalized = baseUrl == null ? "" : baseUrl.trim();
        while (normalized.endsWith("/")) {
            normalized = normalized.substring(0, normalized.length() - 1);
        }
        HttpUrl parsed = HttpUrl.parse(normalized);
        if (parsed == null || (!"http".equals(parsed.scheme()) && !"https".equals(parsed.scheme()))) {
            throw new IllegalArgumentException("server URL must start with http:// or https://");
        }
        this.baseUrl = normalized;
    }

    JSONObject health() throws IOException, JSONException {
        return execute(new Request.Builder().url(baseUrl + "/health").get());
    }

    long createDocument(String title) throws IOException, JSONException {
        JSONObject payload = new JSONObject()
                .put("title", title)
                .put("capture_device", "rokid-glasses-native")
                .put("client_version", "glassdoc/" + BuildConfig.VERSION_NAME)
                .put("sdk_hint", "camera2/mlkit-ja/direct-wifi");
        return execute(new Request.Builder()
                .url(baseUrl + "/v1/documents")
                .post(RequestBody.create(payload.toString(), JSON)))
                .getLong("document_id");
    }

    /**
     * Sends one page. Re-sending an existing {@code page_index} replaces that
     * page, which is what makes a retry after a failed upload safe.
     */
    JSONObject uploadPage(long documentId, PendingPage page)
            throws IOException, JSONException {
        MultipartBody.Builder multipart = new MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart("page_index", Integer.toString(page.pageIndex()))
                .addFormDataPart("image_rotation", Integer.toString(page.imageRotation()))
                .addFormDataPart(
                        "image",
                        "page-" + (page.pageIndex() + 1) + ".jpg",
                        RequestBody.create(page.jpeg(), JPEG));
        if (!page.ocrText().isEmpty()) {
            multipart.addFormDataPart("ocr_text", page.ocrText());
        }
        return execute(new Request.Builder()
                .url(baseUrl + "/v1/documents/" + documentId + "/pages")
                .post(multipart.build()));
    }

    JSONObject finalizeDocument(long documentId) throws IOException, JSONException {
        return execute(new Request.Builder()
                .url(baseUrl + "/v1/documents/" + documentId + "/finalize")
                .post(RequestBody.create(new byte[0], null)));
    }

    private JSONObject execute(Request.Builder builder) throws IOException, JSONException {
        try (Response response = http.newCall(builder.build()).execute()) {
            String body = response.body() == null ? "" : response.body().string();
            if (!response.isSuccessful()) {
                throw new ApiException(response.code(), body);
            }
            return body.isEmpty() ? new JSONObject() : new JSONObject(body);
        }
    }

    /** A server refusal, kept distinct from a transport failure. */
    static final class ApiException extends IOException {
        private final int statusCode;

        ApiException(int statusCode, String body) {
            super("HTTP " + statusCode + (body.isEmpty() ? "" : ": " + body));
            this.statusCode = statusCode;
        }

        int getStatusCode() {
            return statusCode;
        }
    }
}
