package dev.rokid.docscanrelay;

import dev.rokid.docscanrelay.study.AnswerBundle;
import org.json.JSONException;
import org.json.JSONObject;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.LinkProperties;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.RouteInfo;

import java.io.IOException;
import java.io.File;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.UnknownHostException;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.TimeUnit;

import okhttp3.Dns;
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

    /**
     * The server host that means "whatever Wi-Fi this device is on, its
     * gateway". At the venue there is no Wi-Fi but the phone's own hotspot, so
     * the phone is the gateway and its address is chosen by the phone each
     * time the hotspot starts. Resolved per connection, so the saved server
     * URL (and every local session bound to it) never has to change.
     */
    public static final String GATEWAY_HOST = "gateway";

    private final OkHttpClient http;
    private final String baseUrl;
    private final String apiKey;
    private final ClientIdentity client;
    private final OkHttpClient stateHttp;

    public DocScanApi(String baseUrl, String apiKey, ClientIdentity client) {
        this(baseUrl, apiKey, client, null);
    }

    public DocScanApi(String baseUrl, String apiKey, ClientIdentity client, Context context) {
        Context app = context == null ? null : context.getApplicationContext();
        http = new OkHttpClient.Builder()
                .connectTimeout(15, TimeUnit.SECONDS)
                .readTimeout(4, TimeUnit.MINUTES)
                .writeTimeout(60, TimeUnit.SECONDS)
                .callTimeout(5, TimeUnit.MINUTES)
                .retryOnConnectionFailure(true)
                .dns(host -> GATEWAY_HOST.equals(host) && app != null
                        ? List.of(wifiGateway(app)) : Dns.SYSTEM.lookup(host))
                .build();
        // Exit notification must survive cancelling photo/audio work during Activity destruction.
        stateHttp = http.newBuilder().dispatcher(new okhttp3.Dispatcher())
                .callTimeout(5, TimeUnit.SECONDS).build();
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

    /** IPv4 default gateway of the Wi-Fi network this device is joined to. */
    @SuppressWarnings("deprecation") // getAllNetworks: the only list on API 28, the glasses' floor.
    static InetAddress wifiGateway(Context context) throws UnknownHostException {
        ConnectivityManager networks = context.getSystemService(ConnectivityManager.class);
        if (networks != null) {
            for (Network network : networks.getAllNetworks()) {
                NetworkCapabilities capabilities = networks.getNetworkCapabilities(network);
                LinkProperties link = networks.getLinkProperties(network);
                if (capabilities == null || link == null
                        || !capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) continue;
                for (RouteInfo route : link.getRoutes()) {
                    if (route.isDefaultRoute() && route.getGateway() instanceof Inet4Address) {
                        return route.getGateway();
                    }
                }
            }
        }
        throw new UnknownHostException("スマホのテザリングに接続されていません");
    }

    public JSONObject health() throws IOException, JSONException {
        return get("/health");
    }

    public JSONObject settings() throws IOException, JSONException {
        return get("/v1/settings");
    }

    public void requireLocalAsr() throws IOException, JSONException {
        if (!get("/v1/listening-ready").getBoolean("ready")) throw new IOException("録音の受信準備ができていません");
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
        return createExamSession(documentId, listening ? "listening" : "written");
    }

    public JSONObject createExamSession(long documentId, String examType) throws IOException, JSONException {
        if (!java.util.List.of("written", "listening", "mixed").contains(examType)) throw new IllegalArgumentException("invalid exam type");
        JSONObject payload = new JSONObject()
                .put("mode", "study")
                .put("document_id", documentId)
                .put("exam_type", examType)
                .put("answer_format", "mark");
        return postJson("/v1/exam-sessions", payload);
    }

    public JSONObject finalizeReading(long sessionId) throws IOException, JSONException {
        return postEmpty("/v1/exam-sessions/" + sessionId + "/finalize-reading");
    }

    /**
     * Returns once the deck is segmented; the server solves in the background.
     * The phone watcher notifies the glasses when the complete bundle is ready.
     */
    public JSONObject finalizeReadingLocal(long sessionId) throws IOException, JSONException {
        return execute(new Request.Builder().url(baseUrl + "/v1/exam-sessions/" + sessionId
                        + "/finalize-reading?solve=background")
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

    public void glassesState(String deviceId, Long sessionId, long generation, long sequence, String phase)
            throws IOException, JSONException {
        glassesState(deviceId, sessionId, generation, sequence, phase, null);
    }

    public void glassesState(String deviceId, Long sessionId, long generation, long sequence, String phase,
                             String displayRequest) throws IOException, JSONException {
        glassesState(deviceId, sessionId, generation, sequence, phase, displayRequest, null);
    }

    public void glassesState(String deviceId, Long sessionId, long generation, long sequence, String phase,
                             String displayRequest, String entryRequest) throws IOException, JSONException {
        glassesState(deviceId, sessionId, generation, sequence, phase, displayRequest, entryRequest, null);
    }

    public void glassesState(String deviceId, Long sessionId, long generation, long sequence, String phase,
                             String displayRequest, String entryRequest, Long ackAnswerRevision) throws IOException, JSONException {
        if ("sleep".equals(displayRequest) && ("capturing".equals(phase) || "reading".equals(phase))) {
            throw new IllegalArgumentException("an active display cannot request sleep");
        }
        if (entryRequest != null && (!"chooser".equals(entryRequest) || !"chooser".equals(phase)
                || sessionId != null || !"wake".equals(displayRequest))) throw new IllegalArgumentException("invalid wear entry");
        if (ackAnswerRevision != null && (ackAnswerRevision < 0 || sessionId == null)) {
            throw new IllegalArgumentException("invalid received answer revision");
        }
        JSONObject payload = new JSONObject().put("device_id", deviceId)
                .put("session_id", sessionId == null ? JSONObject.NULL : sessionId)
                .put("generation", generation).put("sequence", sequence).put("phase", phase)
                .put("display_request", displayRequest == null ? JSONObject.NULL : displayRequest)
                .put("entry_request", entryRequest == null ? JSONObject.NULL : entryRequest)
                .put("ack_answer_revision", ackAnswerRevision == null ? JSONObject.NULL : ackAnswerRevision);
        execute(new Request.Builder().url(baseUrl + "/v1/glasses/state")
                .post(RequestBody.create(payload.toString(), JSON)), stateHttp);
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
        return execute(builder, longRunning ? http.newBuilder().readTimeout(120, TimeUnit.SECONDS)
                .callTimeout(120, TimeUnit.SECONDS).build() : http);
    }

    private JSONObject execute(Request.Builder builder, OkHttpClient transport) throws IOException, JSONException {
        if (!apiKey.isEmpty()) {
            builder.header("Authorization", "Bearer " + apiKey);
        }
        builder.header("Accept", "application/json");
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
