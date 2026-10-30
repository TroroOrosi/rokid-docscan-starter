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
import java.io.FileInputStream;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.BasicFileAttributes;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Set;
import java.util.HashSet;
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
import okio.BufferedSink;
import org.json.JSONArray;

/** Synchronous server client. Call from a background worker, never the UI/camera handler. */
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
    private final OkHttpClient videoHttp;
    private final Object videoCallLock = new Object();
    private final Set<okhttp3.Call> videoCalls = new HashSet<>();
    private boolean videoTransportClosed;

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
        // Explicit comparison copies must neither occupy ordinary photo work nor retry invisibly.
        videoHttp = http.newBuilder().dispatcher(new okhttp3.Dispatcher())
                .connectTimeout(5, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS)
                .writeTimeout(90, TimeUnit.SECONDS).callTimeout(120, TimeUnit.SECONDS)
                .retryOnConnectionFailure(false).followRedirects(false).followSslRedirects(false).build();
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
        return uploadPage(documentId, pageIndex, jpeg, ocrText, imageRotation, capturedAtMillis, null);
    }

    public JSONObject uploadPage(long documentId, int pageIndex, byte[] jpeg, String ocrText,
                                 int imageRotation, long capturedAtMillis, CaptureProvenance provenance)
            throws IOException, JSONException {
        JSONObject capture = provenance == null ? null : provenance.toUploadJson(jpeg, pageIndex, imageRotation);
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
        if (capture != null) multipart.addFormDataPart("capture_provenance", capture.toString());
        JSONObject response = execute(new Request.Builder()
                .url(baseUrl + "/v1/documents/" + documentId + "/pages")
                .post(multipart.build()));
        if (provenance != null) {
            if (!receiptInteger(response.opt("document_id"), documentId)
                    || !receiptInteger(response.opt("page_index"), pageIndex)
                    || !(response.opt("canonical_image_sha256") instanceof String)
                    || !((String)response.get("canonical_image_sha256")).matches("[0-9a-f]{64}")) {
                throw new JSONException("撮影情報の受領を確認できません");
            }
            provenance.requireUploadEcho(response.optJSONObject("capture_provenance"));
        }
        return response;
    }

    private static boolean receiptInteger(Object value, long expected) {
        return (value instanceof Integer || value instanceof Long) && ((Number)value).longValue() == expected;
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

    public String serverUrl() { return baseUrl; }

    /** Terminal for this client's comparison transport; ordinary page/state work is separate. */
    public void cancelCaptureVideoTransfers() {
        synchronized (videoCallLock) {
            videoTransportClosed=true;
            for (okhttp3.Call call:videoCalls) call.cancel();
        }
    }

    /** Side-effect-free inventory: the device-specific GET may resume answer generation. */
    public String captureVideoPeer(String deviceId, long sessionId, long generation) throws IOException, JSONException {
        if (deviceId == null || !deviceId.matches("[A-Za-z0-9_.:-]{1,100}") || sessionId <= 0
                || sessionId > Integer.MAX_VALUE || generation < 0) throw new JSONException("原動画の送信先が不正です");
        JSONObject inventory = executeVideo(new Request.Builder().url(baseUrl + "/v1/glasses/state").get(),
                512 * 1024, videoHttp.newBuilder().callTimeout(5, TimeUnit.SECONDS).build());
        JSONArray devices = inventory.optJSONArray("devices");
        if (devices == null || devices.length() > 256) throw new JSONException("原動画の送信先を確認できません");
        JSONObject owner = null;
        for (int i = 0; i < devices.length(); i++) {
            JSONObject state = devices.optJSONObject(i);
            if (state == null || !(state.opt("device_id") instanceof String))
                throw new JSONException("原動画の送信先を確認できません");
            if (deviceId.equals(state.opt("device_id"))) {
                if (owner != null) throw new ApiException(409, "ambiguous_video_owner");
                owner = state;
            } else if (receiptInteger(state.opt("session_id"), sessionId)
                    && !List.of("chooser", "writing_done", "closed").contains(state.opt("phase"))) {
                throw new ApiException(409, "ambiguous_video_owner");
            }
        }
        if (owner == null) throw new ApiException(503, "video_state_unavailable");
        Object peerGeneration = owner.opt("generation");
        if (!(peerGeneration instanceof Integer || peerGeneration instanceof Long))
            throw new JSONException("原動画の送信先を確認できません");
        if (((Number)peerGeneration).longValue() < generation)
            throw new ApiException(503, "video_state_unavailable");
        if (!receiptInteger(peerGeneration, generation)
                || !List.of("capturing", "analyzing", "waiting", "reading").contains(owner.opt("phase")))
            throw new ApiException(409, "stale_video_capture");
        if (owner.isNull("session_id")) throw new ApiException(503, "video_state_unavailable");
        if (!receiptInteger(owner.opt("session_id"), sessionId)) throw new ApiException(409, "stale_video_capture");
        Object ip = owner.opt("source_ip");
        if (!(ip instanceof String) || ((String)ip).isBlank() || ((String)ip).length() > 256
                || ((String)ip).indexOf('\0') >= 0) throw new JSONException("原動画の接続元を確認できません");
        return (String)ip;
    }

    /** Explicit comparison only; the producer's false auto-upload flag grants no permission. */
    public JSONObject uploadCaptureVideo(File original, String metadata, String expectedSourceIp)
            throws IOException, JSONException {
        if (metadata == null || metadata.getBytes(StandardCharsets.UTF_8).length > 512 * 1024)
            throw new JSONException("原動画の記録が不正です");
        JSONObject envelope = new JSONObject(metadata);
        requireVideoKeys(envelope, Set.of("schema", "session_id", "document_id", "journal"));
        JSONObject journal = envelope.optJSONObject("journal");
        if (!receiptInteger(envelope.opt("schema"), 1) || journal == null
                || !receiptInteger(journal.opt("schema"), 1)
                || !"raw_video_evaluation".equals(journal.opt("kind")) || !"complete".equals(journal.opt("state"))
                || !"original.mp4".equals(journal.opt("original"))
                || !"sealed_local_video_container_only".equals(journal.opt("complete_scope"))
                || !Boolean.FALSE.equals(journal.opt("auto_upload_allowed"))
                || !Boolean.FALSE.equals(journal.opt("all_pages_or_characters_verified")))
            throw new JSONException("原動画の封印を確認できません");
        long session = videoInteger(envelope, "session_id", 1, Integer.MAX_VALUE);
        long document = videoInteger(envelope, "document_id", 1, Integer.MAX_VALUE);
        long generation = videoInteger(journal, "generation", 0, Long.MAX_VALUE);
        long bytes = videoInteger(journal, "bytes", 1, 128L * 1024 * 1024);
        String device = videoText(journal, "device_id", "[A-Za-z0-9_.:-]{1,100}");
        String clip = videoText(journal, "clip_id", "video-[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}");
        String hash = videoText(journal, "sha256", "[a-f0-9]{64}");
        if (expectedSourceIp == null || expectedSourceIp.isBlank() || expectedSourceIp.length() > 256)
            throw new JSONException("原動画の接続元が未確認です");
        VideoFile source = new VideoFile(original, bytes, hash);
        MultipartBody body = new MultipartBody.Builder().setType(MultipartBody.FORM)
                .addFormDataPart("metadata", metadata).addFormDataPart("video", "original.mp4", source.body()).build();
        JSONObject receipt = executeVideo(new Request.Builder().url(baseUrl + "/v1/capture-videos").post(body),
                16 * 1024, videoHttp);
        source.unchanged();
        requireCaptureVideoReceipt(metadata, receipt, expectedSourceIp);
        return receipt;
    }

    /** Revalidate a durable receipt after restart against the exact saved envelope. */
    public static void requireCaptureVideoReceipt(String metadata, JSONObject receipt, String expectedSourceIp)
            throws JSONException {
        if (metadata == null || metadata.getBytes(StandardCharsets.UTF_8).length > 512 * 1024
                || expectedSourceIp == null || expectedSourceIp.isBlank()) throw new JSONException("原動画の受領が未確認です");
        JSONObject envelope = new JSONObject(metadata);
        requireVideoKeys(envelope, Set.of("schema", "session_id", "document_id", "journal"));
        JSONObject journal = envelope.getJSONObject("journal");
        if (!receiptInteger(envelope.opt("schema"),1) || !receiptInteger(journal.opt("schema"),1)
                || !"raw_video_evaluation".equals(journal.opt("kind")) || !"complete".equals(journal.opt("state"))
                || !Boolean.FALSE.equals(journal.opt("auto_upload_allowed"))
                || !Boolean.FALSE.equals(journal.opt("all_pages_or_characters_verified")))
            throw new JSONException("原動画の封印を確認できません");
        long session = videoInteger(envelope, "session_id", 1, Integer.MAX_VALUE);
        long document = videoInteger(envelope, "document_id", 1, Integer.MAX_VALUE);
        long generation = videoInteger(journal, "generation", 0, Long.MAX_VALUE);
        long bytes = videoInteger(journal, "bytes", 1, 128L * 1024 * 1024);
        String device = videoText(journal, "device_id", "[A-Za-z0-9_.:-]{1,100}");
        String clip = videoText(journal, "clip_id", "video-[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}");
        String hash = videoText(journal, "sha256", "[a-f0-9]{64}");
        requireVideoKeys(receipt, Set.of("schema", "kind", "status", "quality_status", "session_id", "document_id",
                "device_id", "generation", "clip_id", "sha256", "bytes", "source_ip", "all_pages_or_characters_verified",
                "auto_analysis_allowed", "receipt_id", "metadata_sha256"));
        if (!receiptInteger(receipt.opt("schema"), 1) || !receiptInteger(receipt.opt("session_id"), session)
                || !receiptInteger(receipt.opt("document_id"), document) || !receiptInteger(receipt.opt("generation"), generation)
                || !receiptInteger(receipt.opt("bytes"), bytes) || !"raw_video_receipt".equals(receipt.opt("kind"))
                || !"stored".equals(receipt.opt("status")) || !"unevaluated".equals(receipt.opt("quality_status"))
                || !device.equals(receipt.opt("device_id")) || !clip.equals(receipt.opt("clip_id"))
                || !hash.equals(receipt.opt("sha256")) || !expectedSourceIp.equals(receipt.opt("source_ip"))
                || !Boolean.FALSE.equals(receipt.opt("all_pages_or_characters_verified"))
                || !Boolean.FALSE.equals(receipt.opt("auto_analysis_allowed"))
                || !videoHash(clip.getBytes(StandardCharsets.US_ASCII)).equals(receipt.opt("receipt_id"))
                || !videoHash(metadata.getBytes(StandardCharsets.UTF_8)).equals(receipt.opt("metadata_sha256")))
            throw new JSONException("原動画の受領が一致しません");
    }

    private JSONObject executeVideo(Request.Builder builder, int maximum, OkHttpClient transport) throws IOException, JSONException {
        if (!apiKey.isEmpty()) builder.header("Authorization", "Bearer " + apiKey);
        builder.header("Accept", "application/json");
        final okhttp3.Call call;
        synchronized (videoCallLock) {
            if (videoTransportClosed) throw new IOException("原動画の比較転送は終了しています");
            call=transport.newCall(builder.build()); videoCalls.add(call);
        }
        try (Response response = call.execute()) {
            if (response.body() == null) throw new IOException("原動画の応答がありません");
            ByteArrayOutputStream bytes = new ByteArrayOutputStream(); byte[] buffer = new byte[4096]; int count;
            java.io.InputStream input = response.body().byteStream();
            while ((count = input.read(buffer)) != -1) {
                if (bytes.size() + count > maximum) throw new IOException("原動画の応答が大きすぎます");
                bytes.write(buffer, 0, count);
            }
            if (!response.isSuccessful()) throw new ApiException(response.code(), "capture_video_request_rejected");
            return new JSONObject(new String(bytes.toByteArray(), StandardCharsets.UTF_8));
        } finally { synchronized (videoCallLock) { videoCalls.remove(call); } }
    }
    private static void requireVideoKeys(JSONObject value, Set<String> expected) throws JSONException {
        Set<String> actual = new HashSet<>(); value.keys().forEachRemaining(actual::add);
        if (!actual.equals(expected)) throw new JSONException("原動画の受領形式が不正です");
    }
    private static long videoInteger(JSONObject value, String key, long minimum, long maximum) throws JSONException {
        Object number = value.opt(key);
        if (!(number instanceof Integer || number instanceof Long) || ((Number)number).longValue() < minimum
                || ((Number)number).longValue() > maximum) throw new JSONException("原動画の番号が不正です");
        return ((Number)number).longValue();
    }
    private static String videoText(JSONObject value, String key, String pattern) throws JSONException {
        Object text = value.opt(key);
        if (!(text instanceof String) || !((String)text).matches(pattern)) throw new JSONException("原動画の識別が不正です");
        return (String)text;
    }
    private static MessageDigest videoDigest() {
        try { return MessageDigest.getInstance("SHA-256"); }
        catch (NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
    }
    private static String videoHex(byte[] bytes) {
        StringBuilder value = new StringBuilder();
        for (byte item : bytes) value.append(String.format(java.util.Locale.ROOT, "%02x", item & 255));
        return value.toString();
    }
    private static String videoHash(byte[] bytes) { return videoHex(videoDigest().digest(bytes)); }
    private static final class VideoFile {
        final File file;
        final long size;
        final String hash;
        final BasicFileAttributes identity;
        VideoFile(File file, long size, String hash) throws IOException {
            if (file == null || !"original.mp4".equals(file.getName())) throw new IOException("原動画の参照が不正です");
            this.file = file; this.size = size; this.hash = hash;
            identity = attributes();
            MessageDigest digest = videoDigest(); long count = 0; byte[] buffer = new byte[64 * 1024]; int length;
            try (FileInputStream input = new FileInputStream(file)) {
                while ((length = input.read(buffer)) != -1) {
                    count += length; if (count > size) throw new IOException("原動画が変更されました");
                    digest.update(buffer, 0, length);
                }
            }
            if (count != size || !hash.equals(videoHex(digest.digest()))) throw new IOException("原動画が一致しません");
            unchanged();
        }
        BasicFileAttributes attributes() throws IOException {
            Path path = file.toPath().toAbsolutePath();
            for (Path part = path; part != null; part = part.getParent())
                if (Files.isSymbolicLink(part)) throw new IOException("原動画のリンクは使えません");
            BasicFileAttributes value = Files.readAttributes(path, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
            if (!value.isRegularFile() || value.size() != size) throw new IOException("原動画の長さが一致しません");
            return value;
        }
        void unchanged() throws IOException {
            BasicFileAttributes now = attributes();
            if (!Objects.equals(identity.fileKey(), now.fileKey()) || !identity.lastModifiedTime().equals(now.lastModifiedTime()))
                throw new IOException("原動画が変更されました");
        }
        RequestBody body() {
            return new RequestBody() {
                @Override public MediaType contentType() { return MediaType.get("video/mp4"); }
                @Override public long contentLength() { return size; }
                @Override public boolean isOneShot() { return true; }
                @Override public void writeTo(BufferedSink sink) throws IOException {
                    unchanged(); MessageDigest digest = videoDigest(); long count = 0; int length;
                    byte[] buffer = new byte[64 * 1024];
                    try (FileInputStream input = new FileInputStream(file)) {
                        while ((length = input.read(buffer)) != -1) {
                            count += length; if (count > size) throw new IOException("原動画が変更されました");
                            digest.update(buffer, 0, length); sink.write(buffer, 0, length);
                        }
                    }
                    unchanged();
                    if (count != size || !hash.equals(videoHex(digest.digest()))) throw new IOException("原動画が一致しません");
                }
            };
        }
    }

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
