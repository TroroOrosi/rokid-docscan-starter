package dev.rokid.docscanglass.doc;

import android.graphics.ImageFormat;
import android.graphics.Rect;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.MediaCodecInfo;
import android.media.MediaCodecList;
import android.media.MediaExtractor;
import android.media.MediaFormat;
import android.media.MediaRecorder;
import android.os.Handler;
import android.os.SystemClock;
import android.util.Range;
import android.util.Size;
import android.view.Surface;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;
import java.util.concurrent.ExecutorService;
import java.util.function.Consumer;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Explicit hybrid evaluation only. Raw movies never enter the JPEG upload/review path.
 * All recorder, file, and container work runs on one worker, never on Camera2's handler.
 * A sealed container is not proof of frame continuity, readable text, or all-page coverage.
 */
final class CaptureVideoRecording {
    // Bounded clips for the local comparison tool, not limits on production booklet pages.
    static final long MAX_BYTES = 128L * 1024 * 1024;
    static final int MAX_DURATION_MILLIS = 60_000;
    private static final int MAX_EVENTS = 512;

    static final class Options {
        final String deviceId, codec;
        final long generation;
        final int rotation, width, height, fps, bitrate;
        Options(String deviceId, long generation, int rotation, String codec,
                int width, int height, int fps, int bitrate) {
            if (deviceId == null || !deviceId.matches("[A-Za-z0-9_.:-]{1,100}") || generation < 0
                    || !(rotation == 0 || rotation == 90 || rotation == 180 || rotation == 270)
                    || !("avc".equals(codec) || "hevc".equals(codec))
                    || width <= 0 || height <= 0 || (long)width * height > 25_000_000
                    || (long)width * 3 != (long)height * 4 || fps <= 0 || fps > 60
                    || bitrate <= 0 || bitrate > 200_000_000)
                throw new IllegalArgumentException("invalid explicit video evaluation profile");
            this.deviceId = deviceId; this.generation = generation; this.rotation = rotation;
            this.codec = codec; this.width = width; this.height = height; this.fps = fps; this.bitrate = bitrate;
        }
        static Options defaults(String deviceId, long generation, int rotation) {
            return new Options(deviceId, generation, rotation, "avc", 4032, 3024, 30, 20_000_000);
        }
        Options generation(long next) { return new Options(deviceId, next, rotation, codec, width, height, fps, bitrate); }
        String mime() { return "hevc".equals(codec) ? MediaFormat.MIMETYPE_VIDEO_HEVC : MediaFormat.MIMETYPE_VIDEO_AVC; }
    }
    static final class UnsupportedProfile extends IOException {
        UnsupportedProfile(String reason) { super(reason); }
    }
    static final class FileInfo {
        final String mime;
        final int width, height, rotation, videoTracks, audioTracks;
        Long durationUs;
        Integer bitrate, frameRate;
        FileInfo(String mime, int width, int height, int rotation, int videoTracks, int audioTracks) {
            this.mime=mime; this.width=width; this.height=height; this.rotation=rotation;
            this.videoTracks=videoTracks; this.audioTracks=audioTracks;
        }
        JSONObject json() throws JSONException {
            return new JSONObject().put("mime", mime).put("width", width).put("height", height)
                    .put("rotation_metadata", rotation).put("video_tracks", videoTracks).put("audio_tracks", audioTracks)
                    .put("duration_us", durationUs == null ? JSONObject.NULL : durationUs)
                    .put("bitrate_metadata", bitrate == null ? JSONObject.NULL : bitrate)
                    .put("frame_rate_metadata", frameRate == null ? JSONObject.NULL : frameRate);
        }
    }
    interface Port extends AutoCloseable {
        String prepare(File file, CameraCharacteristics characteristics, Size jpeg, Options options,
                Consumer<String> fatal) throws IOException;
        Surface surface();
        void start();
        void stop();
        FileInfo inspect(File file) throws IOException;
        @Override void close();
    }
    interface Factory { Port create(); }

    private final File directory, original, journal;
    private final Handler handler;
    private final Executor worker;
    private final Factory factory;
    private boolean ownsWorker;
    final Options options;
    private final List<Consumer<Boolean>> finishers = new ArrayList<>();
    private final List<JSONObject> events = new ArrayList<>();
    private Port port;
    private volatile Surface surface;
    private volatile boolean closing, failed, finished, success, recording;
    private boolean preparing, started, finishQueued, unsupported, eventBudgetExceeded, journalQueued, sealed;
    private String state = "new", reason = "", advertisedEncoder;
    private long firstSensor, lastSensor, largestPreviewGap, firstFrame = -1, lastFrame = -1;
    private long fileBytes;
    private String sha256;
    private FileInfo actual;
    private Consumer<String> failureListener;
    private Size maximumJpeg;
    private Integer sensorTimestampSource, videoStabilization, opticalStabilization;
    private Rect latestCrop;
    private CaptureVideoTransfer.Origin comparisonOrigin;

    CaptureVideoRecording(File filesDir, Handler handler, Options options) {
        this(filesDir, handler, options, Executors.newSingleThreadExecutor(task -> {
            Thread thread = new Thread(task, "glass-video-recorder"); thread.setDaemon(true); return thread;
        }), NativePort::new);
        ownsWorker = true;
    }
    CaptureVideoRecording(File filesDir, Handler handler, Options options, Executor worker, Factory factory) {
        this.handler=handler; this.options=options; this.worker=worker; this.factory=factory;
        directory = new File(new File(filesDir, "video-evaluations"), "video-" + UUID.randomUUID());
        original = new File(directory, "original.mp4"); journal = new File(directory, "journal.json");
    }
    File originalFile() { return original; }
    File journalFile() { return journal; }
    Surface surface() { return surface; }
    boolean recording() { return recording && !closing && !failed; }
    boolean finalizedSuccessfully() { return finished && success; }

    void comparisonTransferOrigin(CaptureVideoTransfer.Origin origin) {
        if (preparing || closing) throw new IllegalStateException("recording origin must precede prepare");
        comparisonOrigin=origin;
    }

    void prepare(CameraCharacteristics characteristics, Size jpeg, Runnable ready, Consumer<String> failure) {
        if (preparing || closing) return;
        preparing = true;
        failureListener = failure;
        maximumJpeg = jpeg;
        worker.execute(() -> {
            try {
                if (!directory.mkdirs()) throw new IOException("new recording directory unavailable");
                if (!original.createNewFile()) throw new IOException("new recording file unavailable");
                if (comparisonOrigin != null) {
                    try { comparisonOrigin.write(directory); }
                    catch (IOException error) { android.util.Log.w("GlassVideoTransfer","comparison origin unavailable; original retained"); }
                }
                if (characteristics != null) sensorTimestampSource = characteristics.get(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE);
                transition("preparing"); persist();
                port = factory.create();
                advertisedEncoder = port.prepare(original, characteristics, jpeg, options,
                        message -> abort(message, failure));
                surface = port.surface();
                if (surface == null) throw new IOException("recorder surface unavailable");
                transition("prepared"); persist();
                handler.post(() -> { if (!closing && !failed) ready.run(); });
            } catch (IOException | RuntimeException | OutOfMemoryError error) {
                failed = true; unsupported = error instanceof UnsupportedProfile;
                synchronized (this) { state = unsupported ? "unsupported" : "unknown"; reason = safeReason(error); }
                persistBestEffort();
                String message = unsupported ? "video evaluation unsupported: " + error.getMessage()
                        : "video evaluation prepare failed: " + error.getClass().getSimpleName();
                handler.post(() -> { if (!closing) failure.accept(message); });
            }
        });
    }
    void start(Runnable ready, Consumer<String> failure) {
        if (closing || failed || started || port == null) return;
        worker.execute(() -> {
            if (closing || failed || started) return;
            try {
                port.start(); started = true; recording = true;
                transition("recording"); event("recorder_started", new JSONObject()); persist();
                handler.post(() -> { if (!closing && !failed) ready.run(); });
            } catch (IOException | RuntimeException | OutOfMemoryError error) { abort("recorder_start_failed", failure); }
        });
    }
    void requestClose(String endReason) {
        if (finished) return;
        closing = true; recording = false;
        synchronized (this) { if (!failed && !finished) { state = "closing"; reason = endReason; } }
        schedulePersist();
    }
    void abort(String why, Consumer<String> failure) {
        synchronized (this) {
            if (finished || sealed || failed) return;
            failed = true; success = false; recording = false; state = "unknown"; reason = why;
        }
        schedulePersist();
        handler.post(() -> { if (!finished) failure.accept("video evaluation " + why); });
    }
    void finish(boolean ordinary, String endReason, Consumer<Boolean> complete) {
        if (finished) { handler.post(() -> complete.accept(success)); return; }
        synchronized (this) { if (!ordinary && !sealed) markFailure(endReason); }
        finishers.add(complete);
        if (finishQueued) return;
        finishQueued = true; requestClose(endReason);
        worker.execute(() -> {
            boolean ok = ordinary && !failed && started;
            try { if (port != null && started) port.stop(); }
            catch (RuntimeException | OutOfMemoryError error) { ok = false; markFailure("recorder_stop_failed"); }
            try { if (port != null) port.close(); }
            catch (RuntimeException | OutOfMemoryError error) { ok = false; markFailure("recorder_release_failed"); }
            surface = null;
            try {
                if (started && port != null) {
                    actual = port.inspect(original);
                    if (actual == null || !options.mime().equals(actual.mime) || actual.width != options.width
                            || actual.height != options.height || actual.rotation != 0
                            || actual.videoTracks != 1 || actual.audioTracks != 0)
                        throw new IOException("actual movie differs from explicit profile");
                }
                fileBytes = original.length();
                if (fileBytes <= 0 || fileBytes > MAX_BYTES) throw new IOException("raw movie byte budget");
                try (FileOutputStream sync = new FileOutputStream(original, true)) { sync.getFD().sync(); }
                sha256 = hash(original);
            } catch (IOException | RuntimeException | OutOfMemoryError error) { ok = false; markFailure("movie_inspection_failed"); }
            synchronized (this) {
                success = ok && !failed && !eventBudgetExceeded;
                state = unsupported ? "unsupported" : success ? "complete" : "unknown";
                if (reason.isEmpty()) reason = endReason;
                sealed = true;
            }
            try { persist(); }
            catch (IOException error) { success = false; markFailure("journal_persistence_failed"); persistBestEffort(); }
            synchronized (this) {
                finished = true;
                if (ownsWorker) ((ExecutorService)worker).shutdown();
            }
            handler.post(() -> {
                List<Consumer<Boolean>> waiting = new ArrayList<>(finishers); finishers.clear();
                for (Consumer<Boolean> waiter : waiting) waiter.accept(success);
            });
        });
    }
    synchronized void frame(long sensorTimestamp, long frameNumber) {
        if (closing || sensorTimestamp <= 0 || sensorTimestamp <= lastSensor) return;
        if (firstSensor == 0) { firstSensor = sensorTimestamp; firstFrame = frameNumber; }
        if (lastSensor > 0) largestPreviewGap = Math.max(largestPreviewGap, sensorTimestamp - lastSensor);
        lastSensor = sensorTimestamp; lastFrame = frameNumber;
    }
    synchronized void frame(long sensorTimestamp, long frameNumber, Rect crop, Integer stabilization, Integer optical) {
        frame(sensorTimestamp, frameNumber);
        if (closing || sensorTimestamp != lastSensor) return;
        latestCrop = crop == null ? null : new Rect(crop);
        videoStabilization = stabilization; opticalStabilization = optical;
    }
    void scene(long sequence, long sensorTimestamp, long elapsedMillis) {
        event("scene_observed", json("scene_sequence", sequence, "sensor_timestamp_ns", sensorTimestamp,
                "observation_elapsed_ms", elapsedMillis));
    }
    void stillRequested(long generation) { event("native_still_requested", json("still_generation", generation)); }
    void stillDelivered(long generation, long sensorTimestamp, int width, int height, String sha) {
        event("native_still_delivered", json("still_generation", generation, "sensor_timestamp_ns", sensorTimestamp,
                "width", width, "height", height, "jpeg_sha256", sha));
    }
    void gap(String why) { event("capture_gap_or_anomaly", json("reason", why)); }
    private void event(String type, JSONObject data) {
        synchronized (this) {
            if (finished || sealed) return;
            if (events.size() >= MAX_EVENTS) { eventBudgetExceeded = true; return; }
            try { data.put("event", type).put("elapsed_realtime_ns", SystemClock.elapsedRealtimeNanos()); }
            catch (JSONException error) { throw new IllegalStateException(error); }
            events.add(data);
        }
        // Only scene/shot/lifecycle events, never a task per preview frame.
        schedulePersist();
    }
    private void schedulePersist() {
        synchronized (this) {
            if (finished || journalQueued) return;
            journalQueued = true;
            worker.execute(() -> { synchronized (this) { journalQueued = false; } persistBestEffort(); });
        }
    }
    private synchronized void transition(String next) { if (!failed) state = closing ? "closing" : next; }
    private synchronized void markFailure(String why) {
        if (!failed || reason.isEmpty()) reason = why;
        failed = true; success = false; if (!unsupported) state = "unknown";
    }
    private static String safeReason(Throwable error) { return error instanceof UnsupportedProfile ? error.getMessage() : error.getClass().getSimpleName(); }
    private void persistBestEffort() {
        try { if (directory.isDirectory()) persist(); }
        catch (IOException error) {
            boolean notify = !failed;
            markFailure("journal_persistence_failed");
            if (notify && failureListener != null) handler.post(() -> failureListener.accept("video evaluation journal persistence failed"));
        }
    }
    private void persist() throws IOException {
        final byte[] bytes;
        synchronized (this) {
            try {
                JSONObject profile = json("codec", options.codec, "mime", options.mime(), "width", options.width,
                        "height", options.height, "fps", options.fps, "bitrate", options.bitrate);
                JSONObject data = json("schema", 1, "kind", "raw_video_evaluation", "state", state, "reason", reason,
                        "device_id", options.deviceId, "generation", options.generation, "clip_id", directory.getName(),
                        "rotation", options.rotation, "original", "original.mp4", "audio_enabled", false,
                        "selected_profile", profile, "profile_quality_calibrated", false,
                        "max_jpeg_width", maximumJpeg == null ? JSONObject.NULL : maximumJpeg.getWidth(),
                        "max_jpeg_height", maximumJpeg == null ? JSONObject.NULL : maximumJpeg.getHeight(),
                        "app_version", BuildConfig.VERSION_NAME, "app_version_code", BuildConfig.VERSION_CODE,
                        "producer_revision", "mediarecorder_hybrid_v1",
                        "advertised_compatible_encoder", advertisedEncoder == null ? JSONObject.NULL : advertisedEncoder,
                        "actual_encoder_name", "unknown_public_mediarecorder", "actual_file", actual == null ? JSONObject.NULL : actual.json(),
                        "bytes", fileBytes, "sha256", sha256 == null ? JSONObject.NULL : sha256,
                        "first_preview_sensor_ns", firstSensor, "last_preview_sensor_ns", lastSensor,
                        "first_preview_frame_number", firstFrame, "last_preview_frame_number", lastFrame,
                        "largest_preview_sensor_gap_ns", largestPreviewGap, "scene_clock", "camera_sensor_ns",
                        "sensor_timestamp_source", sensorTimestampSource == null ? JSONObject.NULL : sensorTimestampSource,
                        "latest_result_crop", latestCrop == null ? JSONObject.NULL : json("left", latestCrop.left,
                                "top", latestCrop.top, "right", latestCrop.right, "bottom", latestCrop.bottom),
                        "latest_result_video_stabilization", videoStabilization == null ? JSONObject.NULL : videoStabilization,
                        "latest_result_optical_stabilization", opticalStabilization == null ? JSONObject.NULL : opticalStabilization,
                        "video_to_jpeg_field_of_view", "unknown_requires_physical_calibration",
                        "scene_observation_source", "small_yuv_not_original_video_frame",
                        "sensor_to_video_pts", "unknown_requires_decoded_pts", "capture_gap_status", "unknown_requires_decoded_frame_coverage",
                        "exact_stream_support", "see_session_events", "all_pages_or_characters_verified", false,
                        "auto_upload_allowed", false, "complete_scope", "sealed_local_video_container_only",
                        "event_budget_exceeded", eventBudgetExceeded,
                        "evaluation_max_bytes", MAX_BYTES, "evaluation_max_duration_ms", MAX_DURATION_MILLIS,
                        "events", new JSONArray(events));
                bytes = data.toString().getBytes(StandardCharsets.UTF_8);
            } catch (JSONException error) { throw new IOException("journal encoding", error); }
        }
        File partial = new File(directory, "journal.json.partial");
        try (FileOutputStream out = new FileOutputStream(partial)) { out.write(bytes); out.getFD().sync(); }
        Files.move(partial.toPath(), journal.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
    }
    void sessionSupport(String support) { event("exact_session_support", json("support", support)); }
    private static JSONObject json(Object... pairs) {
        JSONObject value = new JSONObject();
        try { for (int i = 0; i < pairs.length; i += 2) value.put((String)pairs[i], pairs[i + 1]); }
        catch (JSONException error) { throw new IllegalStateException(error); }
        return value;
    }
    private static String hash(File file) throws IOException {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            try (FileInputStream input = new FileInputStream(file)) {
                byte[] buffer = new byte[64 * 1024]; int count;
                while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
            }
            StringBuilder hex = new StringBuilder();
            for (byte value : digest.digest()) hex.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
            return hex.toString();
        } catch (java.security.NoSuchAlgorithmException impossible) { throw new IOException(impossible); }
    }

    /** API32 public camera/encoder advertisements, not a sustained performance measurement. */
    static String requireSupported(CameraCharacteristics characteristics, Size jpeg, Options options) throws UnsupportedProfile {
        StreamConfigurationMap map = characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
        Size desired = new Size(options.width, options.height);
        Size[] video = map == null ? null : map.getOutputSizes(MediaRecorder.class);
        Size[] stills = map == null ? null : map.getOutputSizes(ImageFormat.JPEG);
        if (video == null || !Arrays.asList(video).contains(desired) || jpeg == null
                || stills == null || !Arrays.asList(stills).contains(jpeg))
            throw new UnsupportedProfile("requested_mediarecorder_size_or_max_jpeg_not_advertised");
        long minimum = map.getOutputMinFrameDuration(MediaRecorder.class, desired);
        if (minimum <= 0 || minimum > 1_000_000_000L / options.fps)
            throw new UnsupportedProfile("requested_camera_frame_rate_unknown_or_unsupported");
        Range<Integer>[] rates = characteristics.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES);
        if (rates == null || !Arrays.asList(rates).contains(new Range<>(options.fps, options.fps)))
            throw new UnsupportedProfile("requested_fixed_camera_fps_not_advertised");
        MediaFormat format = MediaFormat.createVideoFormat(options.mime(), options.width, options.height);
        format.setInteger(MediaFormat.KEY_FRAME_RATE, options.fps); format.setInteger(MediaFormat.KEY_BIT_RATE, options.bitrate);
        format.setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface);
        for (MediaCodecInfo codec : new MediaCodecList(MediaCodecList.REGULAR_CODECS).getCodecInfos()) {
            if (!codec.isEncoder() || !Arrays.asList(codec.getSupportedTypes()).contains(options.mime())) continue;
            MediaCodecInfo.CodecCapabilities capabilities = codec.getCapabilitiesForType(options.mime());
            MediaCodecInfo.VideoCapabilities v = capabilities.getVideoCapabilities();
            if (v != null && options.width % v.getWidthAlignment() == 0 && options.height % v.getHeightAlignment() == 0
                    && v.getBitrateRange().contains(options.bitrate) && v.areSizeAndRateSupported(options.width, options.height, options.fps)
                    && capabilities.isFormatSupported(format)
                    && Arrays.stream(capabilities.colorFormats).anyMatch(c -> c == MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface))
                return codec.getName();
        }
        throw new UnsupportedProfile("requested_" + options.codec + "_surface_encoder_profile_not_advertised");
    }
    private static final class NativePort implements Port {
        private MediaRecorder recorder;
        @Override public String prepare(File file, CameraCharacteristics characteristics, Size jpeg, Options options,
                Consumer<String> fatal) throws IOException {
            String encoder = requireSupported(characteristics, jpeg, options);
            recorder = new MediaRecorder();
            recorder.setOnErrorListener((r, what, extra) -> fatal.accept("recorder_error_" + what + "_" + extra));
            recorder.setOnInfoListener((r, what, extra) -> {
                if (what == MediaRecorder.MEDIA_RECORDER_INFO_MAX_DURATION_REACHED
                        || what == MediaRecorder.MEDIA_RECORDER_INFO_MAX_FILESIZE_REACHED) fatal.accept("evaluation_clip_budget_reached");
            });
            // No AudioSource/AudioEncoder: listening AudioRecord owns its independent microphone path.
            recorder.setVideoSource(MediaRecorder.VideoSource.SURFACE);
            recorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4);
            recorder.setVideoEncoder("hevc".equals(options.codec) ? MediaRecorder.VideoEncoder.HEVC : MediaRecorder.VideoEncoder.H264);
            recorder.setVideoSize(options.width, options.height); recorder.setVideoFrameRate(options.fps);
            recorder.setVideoEncodingBitRate(options.bitrate); recorder.setOrientationHint(0);
            recorder.setMaxDuration(MAX_DURATION_MILLIS); recorder.setMaxFileSize(MAX_BYTES);
            recorder.setOutputFile(file.getAbsolutePath()); recorder.prepare();
            return encoder;
        }
        @Override public Surface surface() { return recorder.getSurface(); }
        @Override public void start() { recorder.start(); }
        @Override public void stop() { recorder.stop(); }
        @Override public void close() { if (recorder != null) { recorder.release(); recorder = null; } }
        @Override public FileInfo inspect(File file) throws IOException {
            MediaExtractor extractor = new MediaExtractor();
            try {
                extractor.setDataSource(file.getAbsolutePath());
                MediaFormat video = null; int videoTracks = 0, audioTracks = 0;
                for (int i = 0; i < extractor.getTrackCount(); i++) {
                    MediaFormat format = extractor.getTrackFormat(i); String mime = format.getString(MediaFormat.KEY_MIME);
                    if (mime != null && mime.startsWith("video/")) { video = format; videoTracks++; }
                    else if (mime != null && mime.startsWith("audio/")) audioTracks++;
                    else throw new IOException("unexpected movie track");
                }
                if (video == null || videoTracks != 1 || audioTracks != 0) throw new IOException("movie track topology");
                FileInfo info = new FileInfo(video.getString(MediaFormat.KEY_MIME), video.getInteger(MediaFormat.KEY_WIDTH),
                        video.getInteger(MediaFormat.KEY_HEIGHT), video.containsKey(MediaFormat.KEY_ROTATION) ? video.getInteger(MediaFormat.KEY_ROTATION) : 0,
                        videoTracks, audioTracks);
                if (!video.containsKey(MediaFormat.KEY_DURATION) || video.getLong(MediaFormat.KEY_DURATION) <= 0)
                    throw new IOException("movie duration unavailable");
                info.durationUs = video.getLong(MediaFormat.KEY_DURATION);
                if (video.containsKey(MediaFormat.KEY_BIT_RATE)) info.bitrate = video.getInteger(MediaFormat.KEY_BIT_RATE);
                if (video.containsKey(MediaFormat.KEY_FRAME_RATE)) info.frameRate = video.getInteger(MediaFormat.KEY_FRAME_RATE);
                return info;
            } finally { extractor.release(); }
        }
    }
}
