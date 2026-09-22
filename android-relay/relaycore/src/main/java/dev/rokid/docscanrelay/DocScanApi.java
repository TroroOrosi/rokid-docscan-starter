package dev.rokid.docscanrelay;

import dev.rokid.docscanrelay.study.AnswerBundle;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.io.File;
import java.util.Objects;
import java.util.concurrent.TimeUnit;

import okhttp3.HttpUrl;
import okhttp3.MediaType;
import okhttp3.MultipartBody;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;

/** Synchronous server client. Call only from the controller's serial executor. */
public final class DocScanApi {
    private static final MediaType JSON =
            Objects.requireNonNull(MediaType.parse("application/json; charset=utf-8"));
    private static final MediaType JPEG =
            Objects.requireNonNull(MediaType.parse("image/jpeg"));
    private static final MediaType EMPTY =
            Objects.requireNonNull(MediaType.parse("application/octet-stream"));

    private final OkHttpClient http = new OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(4, TimeUnit.MINUTES)
            .writeTimeout(60, TimeUnit.SECONDS)
            .callTimeout(5, TimeUnit.MINUTES)
            .retryOnConnectionFailure(true)
            .build();
    private final String baseUrl;
    private final String apiKey;
    private final ClientIdentity client;

    public DocScanApi(String baseUrl, String apiKey, ClientIdentity client) {
        String normalized = baseUrl == null ? "" : baseUrl.trim();
        while (normalized.endsWith("/")) {
            normalized = normalized.substring(0, normalized.length() - 1);
        }
        HttpUrl parsed = HttpUrl.parse(normalized);
        if (parsed == null || (!"http".equals(parsed.scheme()) && !"https".equals(parsed.scheme()))) {
            throw new IllegalArgumentException(
                    "サーバURLは http:// または https:// で始めてください");
        }
        this.baseUrl = normalized;
        this.apiKey = apiKey == null ? "" : apiKey.trim();
        if (client == null) {
            throw new IllegalArgumentException("クライアント識別子が必要です");
        }
        this.client = client;
    }

    public JSONObject health() throws IOException, JSONException {
        return get("/health");
    }

    public JSONObject settings() throws IOException, JSONException {
        return get("/v1/settings");
    }

    public void requireLocalAsr() throws IOException, JSONException {
        if (!get("/v1/listening-ready").getBoolean("ready")) throw new IOException("端末内ASRが未設定です");
    }

    public JSONObject createDocument(String title) throws IOException, JSONException {
        JSONObject payload = new JSONObject()
                .put("title", title)
                .put("capture_device", client.captureDevice)
                .put("client_version", client.clientVersion)
                .put("sdk_hint", client.sdkHint);
        return postJson("/v1/documents", payload);
    }

    public JSONObject uploadPage(
            long documentId,
            int pageIndex,
            byte[] jpeg,
            String ocrText,
            int imageRotation
    ) throws IOException, JSONException {
        return uploadPage(documentId, pageIndex, jpeg, ocrText, imageRotation, 0);
    }

    public JSONObject uploadPage(long documentId, int pageIndex, byte[] jpeg, String ocrText,
                                 int imageRotation, long capturedAtMillis) throws IOException, JSONException {
        MultipartBody.Builder multipart = new MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart("page_index", Integer.toString(pageIndex))
                .addFormDataPart("image_rotation", Integer.toString(imageRotation))
                .addFormDataPart("captured_at_ms", Long.toString(capturedAtMillis))
                .addFormDataPart(
                        "image",
                        "page-" + (pageIndex + 1) + ".jpg",
                        RequestBody.create(jpeg, JPEG));
        if (ocrText != null && !ocrText.trim().isEmpty()) {
            multipart.addFormDataPart("ocr_text", ocrText.trim());
        }
        return execute(new Request.Builder()
                .url(baseUrl + "/v1/documents/" + documentId + "/pages")
                .post(multipart.build()));
    }

    public JSONObject scanStatus(long documentId) throws IOException, JSONException {
        return get("/v1/documents/" + documentId + "/scan-status");
    }

    public JSONObject finalizeDocument(long documentId) throws IOException, JSONException {
        return postEmpty("/v1/documents/" + documentId + "/finalize");
    }

    public JSONObject createExamSession(long documentId) throws IOException, JSONException {
        return createExamSession(documentId, false);
    }

    public JSONObject createExamSession(long documentId, boolean listening) throws IOException, JSONException {
        JSONObject payload = new JSONObject()
                .put("mode", "study")
                .put("document_id", documentId)
                .put("exam_type", listening ? "listening" : "written")
                .put("answer_format", "mark");
        return postJson("/v1/exam-sessions", payload);
    }

    public JSONObject finalizeReading(long sessionId) throws IOException, JSONException {
        return postEmpty("/v1/exam-sessions/" + sessionId + "/finalize-reading");
    }

    /** Analysis outlives the usual five-minute upload deadline; server solver has its own brakes. */
    public JSONObject finalizeReadingLocal(long sessionId) throws IOException, JSONException {
        return execute(new Request.Builder().url(baseUrl + "/v1/exam-sessions/" + sessionId + "/finalize-reading")
                .post(RequestBody.create(new byte[0], EMPTY)), true);
    }

    public void uploadAudioChunk(long documentId, int sequence, long startSample, long capturedAt, File wav)
            throws IOException, JSONException {
        MultipartBody body = new MultipartBody.Builder().setType(MultipartBody.FORM)
                .addFormDataPart("sequence", Integer.toString(sequence))
                .addFormDataPart("start_sample", Long.toString(startSample))
                .addFormDataPart("captured_at_ms", Long.toString(capturedAt))
                .addFormDataPart("audio", "chunk.wav", RequestBody.create(wav, MediaType.get("audio/wav")))
                .build();
        execute(new Request.Builder().url(baseUrl + "/v1/documents/" + documentId + "/audio-chunks").post(body), true);
    }

    public void completeAudio(long documentId, int chunks, long samples) throws IOException, JSONException {
        postJson("/v1/documents/" + documentId + "/audio-complete",
                new JSONObject().put("expected_chunks", chunks).put("total_samples", samples));
    }

    public void attachDocumentAudio(long sessionId) throws IOException, JSONException {
        postEmpty("/v1/exam-sessions/" + sessionId + "/document-audio");
    }

    public void cancelRequests() { http.dispatcher().cancelAll(); }

    public JSONObject review(long sessionId, int index, int viewPage)
            throws IOException, JSONException {
        HttpUrl url = requireUrl(baseUrl + "/v1/exam-sessions/" + sessionId + "/review")
                .newBuilder()
                .addQueryParameter("index", Integer.toString(index))
                .addQueryParameter("view_page", Integer.toString(viewPage))
                .build();
        return execute(new Request.Builder().url(url).get());
    }

    /** One complete snapshot, so a reader works with no route to the server. */
    public AnswerBundle answerBundle(long sessionId) throws IOException, JSONException {
        return AnswerBundle.fromJson(
                get("/v1/exam-sessions/" + sessionId + "/answer-bundle").toString());
    }

    private JSONObject get(String path) throws IOException, JSONException {
        return execute(new Request.Builder().url(baseUrl + path).get());
    }

    private JSONObject postJson(String path, JSONObject payload)
            throws IOException, JSONException {
        return execute(new Request.Builder()
                .url(baseUrl + path)
                .post(RequestBody.create(payload.toString(), JSON)));
    }

    private JSONObject postEmpty(String path) throws IOException, JSONException {
        return execute(new Request.Builder()
                .url(baseUrl + path)
                .post(RequestBody.create(new byte[0], EMPTY)));
    }

    private JSONObject execute(Request.Builder builder) throws IOException, JSONException {
        return execute(builder, false);
    }

    private JSONObject execute(Request.Builder builder, boolean longRunning) throws IOException, JSONException {
        if (!apiKey.isEmpty()) {
            builder.header("Authorization", "Bearer " + apiKey);
        }
        builder.header("Accept", "application/json");
        OkHttpClient transport = longRunning ? http.newBuilder().readTimeout(0, TimeUnit.SECONDS)
                .callTimeout(0, TimeUnit.SECONDS).build() : http;
        try (Response response = transport.newCall(builder.build()).execute()) {
            String body = response.body() == null ? "" : response.body().string();
            if (!response.isSuccessful()) {
                String detail = body;
                try {
                    detail = new JSONObject(body).optString("detail", body);
                } catch (JSONException ignored) {
                    // Keep the raw response as diagnostic text.
                }
                throw new ApiException(response.code(), detail);
            }
            if (body.trim().isEmpty()) {
                return new JSONObject();
            }
            return new JSONObject(body);
        }
    }

    private static HttpUrl requireUrl(String value) {
        HttpUrl parsed = HttpUrl.parse(value);
        if (parsed == null) {
            throw new IllegalArgumentException("invalid URL: " + value);
        }
        return parsed;
    }

    public static final class ApiException extends IOException {
        private final int statusCode;

        ApiException(int statusCode, String detail) {
            super("HTTP " + statusCode + ": " + detail);
            this.statusCode = statusCode;
        }

        public int getStatusCode() {
            return statusCode;
        }
    }
}
