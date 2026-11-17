package dev.rokid.docscanglass.doc;

import static android.hardware.camera2.CameraMetadata.*;
import static org.junit.Assert.*;
import static org.robolectric.Shadows.shadowOf;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.ImageFormat;
import android.graphics.Rect;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorManager;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CaptureRequest;
import android.hardware.camera2.CaptureResult;
import android.hardware.camera2.DocScanTestCamera;
import android.hardware.camera2.TotalCaptureResult;
import android.media.DocScanTestImage;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Range;
import android.util.Size;
import dev.rokid.docscanglass.doc.GlassCameraWarmSessionTest.ManagerShadow;
import dev.rokid.docscanglass.doc.GlassCameraWarmSessionTest.MapShadow;
import dev.rokid.docscanglass.doc.GlassCameraWarmSessionTest.ReaderShadow;
import dev.rokid.docscanglass.doc.GlassCameraWarmSessionTest.RequestShadow;
import dev.rokid.docscanrelay.CaptureProvenance;
import dev.rokid.docscanrelay.CaptureSurface;
import dev.rokid.docscanrelay.ClipInbox;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.GraphicsMode;
import org.robolectric.shadow.api.Shadow;
import org.robolectric.shadows.ShadowCaptureResult;
import org.robolectric.shadows.ShadowSensor;
import org.robolectric.shadows.ShadowSensorManager;
import org.robolectric.shadows.ShadowTotalCaptureResult;

/**
 * Runs the real watch -> clip -> watch cycle against a fake HAL and a fake encoder, never a camera or a codec. A
 * session reports itself idle only when the test says so: on the glasses a session changed before that left the
 * camera unable to drain after 16 to 28 pages (M-29).
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE, shadows = {GlassCameraWarmSessionTest.ManagerShadow.class,
        GlassCameraWarmSessionTest.CharacteristicsShadow.class, GlassCameraWarmSessionTest.MapShadow.class,
        GlassCameraWarmSessionTest.ReaderShadow.class, GlassCameraWarmSessionTest.BuilderShadow.class,
        GlassCameraWarmSessionTest.RequestShadow.class})
public class ClipCameraTest {
    private static final int W = 2016, H = 1512, ROW = 2048; // the glasses' camera pads its rows to 2048

    /** Takes what a codec would and keeps its counts; the clip it "writes" is eight bytes. */
    private static final class FakeEncoder implements ClipEncoder {
        final List<Long> offered = new ArrayList<>();
        File file;
        int width, height, bitrate, frameRate, opens, offers, ends;
        /** Frames the encoder took and its file does not hold. */
        int lost;
        boolean refuse, holdEnd;
        String failure;
        IOException openFailure;
        Ended pending;

        @Override public void open(File clip, int width, int height, int bitrate, int frameRate) throws IOException {
            if (openFailure != null) throw openFailure;
            opens++; file = clip; this.width = width; this.height = height; this.bitrate = bitrate; this.frameRate = frameRate;
            offered.clear();
            Files.write(clip.toPath(), new byte[]{0, 0, 0, 24, 'f', 't', 'y', 'p'});
        }

        @Override public boolean offer(ByteBuffer luma, int rowStride, long timestampNanos) {
            offers++;
            if (refuse) return false;
            assertEquals(ROW, rowStride);
            offered.add(timestampNanos);
            return true;
        }

        @Override public void end(Ended ended) {
            ends++; pending = ended;
            if (!holdEnd) finish();
        }

        void finish() {
            Ended ended = pending; pending = null;
            ended.done(offered.size() - lost, file.length(), failure);
        }
    }

    private final List<GlassCamera.Captured> pages = new ArrayList<>();
    private final List<String> failures = new ArrayList<>();
    private final List<String> watchImages = new ArrayList<>(), clipImages = new ArrayList<>();
    /** What the display's bar is told: "counted/wanted", with " end" for the report that ends a recording; and when. */
    private final List<String> progress = new ArrayList<>();
    private final List<Long> progressAt = new ArrayList<>();
    private final List<Boolean> far = new ArrayList<>();
    private final List<Long> stamps = new ArrayList<>();
    private final byte[] luma = new byte[ROW * (H - 1) + W];
    private int notReady, previews;
    private FakeEncoder encoder;
    private File inboxDirectory;
    private ClipInbox inbox;
    private ClipCamera camera;
    private ShadowSensorManager sensors;

    @Before public void setup() {
        ManagerShadow.devices.clear(); ReaderShadow.readers.clear();
        ManagerShadow.refuseSession = false; ManagerShadow.refuseOutputs = 0;
        MapShadow.previewSize = new Size(320, 240); MapShadow.fullSizeYuv = false;
        Context app = RuntimeEnvironment.getApplication();
        sensors = shadowOf((SensorManager) app.getSystemService(Context.SENSOR_SERVICE));
        sensors.addSensor(ShadowSensor.newInstance(Sensor.TYPE_GYROSCOPE));
        inboxDirectory = new File(app.getFilesDir(), "clip-inbox");
        inbox = new ClipInbox(inboxDirectory);
        create(new ClipCamera.Options());
    }

    @After public void close() {
        camera.close(); idle(2000);
    }

    private void create(ClipCamera.Options options) {
        encoder = new FakeEncoder();
        camera = new ClipCamera(RuntimeEnvironment.getApplication(), new Handler(Looper.getMainLooper()),
                new GlassCamera.Callback() {
                    @Override public void onCaptured(GlassCamera.Captured captured) { pages.add(captured); }
                    @Override public void onCaptured(byte[] jpeg, int width, int height, long elapsedMillis) {
                        throw new AssertionError("a page comes with where it was taken from");
                    }
                    @Override public void onCaptureFailed(String reason) { failures.add(reason); }
                    @Override public void onCaptureNotReady() { notReady++; }
                    @Override public void onPreview(Bitmap frame) { previews++; frame.recycle(); }
                }, inbox, encoder, options);
        camera.pageEncoder = (nv21, width, height, quality) -> new byte[]{(byte) 0xff, (byte) 0xd8, nv21[0]};
        camera.marks(new ClipCamera.Marks() {
            @Override public void showClipProgress(int counted, int wanted, boolean recording) {
                progress.add(counted + "/" + wanted + (recording ? "" : " end"));
                progressAt.add(SystemClock.elapsedRealtime());
            }
            @Override public void showFar(boolean value) { far.add(value); }
        });
    }

    private void idle(long millis) { shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(millis)); }
    private DocScanTestCamera device() { return ManagerShadow.devices.get(ManagerShadow.devices.size() - 1); }
    private ReaderShadow reader(int width) {
        return ReaderShadow.readers.stream().filter(r -> r.width == width && !r.closed).findFirst().orElseThrow();
    }
    private RequestShadow repeating() { return Shadow.extract(device().session.repeating); }
    private Object asked(CaptureRequest.Key<?> key) { return repeating().values.get(key.getName()); }

    private TotalCaptureResult result(long stamp, long exposureNanos, int iso, Integer boost, int ae) {
        TotalCaptureResult result = ShadowTotalCaptureResult.newTotalCaptureResult();
        ShadowCaptureResult values = Shadow.extract(result);
        values.set(CaptureResult.SENSOR_TIMESTAMP, stamp);
        values.set(CaptureResult.SENSOR_EXPOSURE_TIME, exposureNanos);
        values.set(CaptureResult.SENSOR_SENSITIVITY, iso);
        if (boost != null) values.set(CaptureResult.CONTROL_POST_RAW_SENSITIVITY_BOOST, boost);
        values.set(CaptureResult.CONTROL_AE_STATE, ae);
        return result;
    }

    /** What the watch preview's auto exposure reports: the light the clip has to match. */
    private void light(long exposureNanos, int iso, Integer boost, int ae) {
        var session = device().session;
        session.previewCallback.onCaptureCompleted(session, session.repeating,
                result(SystemClock.elapsedRealtimeNanos(), exposureNanos, iso, boost, ae));
    }

    private void watchFrame(byte[] pixels) {
        DocScanTestImage image = new DocScanTestImage(watchImages);
        image.format = ImageFormat.YUV_420_888; image.width = 32; image.height = 24;
        image.rowStride = 32; image.pixelStride = 1;
        image.timestamp = SystemClock.elapsedRealtimeNanos(); image.buffer = ByteBuffer.wrap(pixels);
        ReaderShadow watch = reader(320);
        watch.image = image; watch.listener.onImageAvailable(watch.reader);
        idle(0); // the camera's thread works on the copy
    }

    private void watchFrame(boolean turned) {
        byte[] pixels = new byte[32 * 24]; Arrays.fill(pixels, (byte) 180);
        if (turned) Arrays.fill(pixels, 0, pixels.length / 3, (byte) 70);
        watchFrame(pixels);
    }

    /** A 320x240 watch frame of print whose lines lie {@code period} px apart: 6.3 px of the recorded frame to one of it. */
    private void watchPrint(double period) {
        byte[] pixels = new byte[320 * 240];
        for (int y = 0; y < 240; y++) for (int x = 0; x < 320; x++) {
            pixels[y * 320 + x] = (byte) Math.round(190 - 90 * Math.max(0, Math.cos(2 * Math.PI * x / period)));
        }
        DocScanTestImage image = new DocScanTestImage(watchImages);
        image.format = ImageFormat.YUV_420_888; image.width = 320; image.height = 240;
        image.rowStride = 320; image.pixelStride = 1;
        image.timestamp = SystemClock.elapsedRealtimeNanos(); image.buffer = ByteBuffer.wrap(pixels);
        ReaderShadow watch = reader(320);
        watch.image = image; watch.listener.onImageAvailable(watch.reader);
        idle(0);
    }

    /** A frame whose first {@code share} of pixels is paper and the rest desk. */
    private void watchShare(float share) {
        byte[] pixels = new byte[32 * 24]; Arrays.fill(pixels, (byte) 40);
        Arrays.fill(pixels, 0, (int) (pixels.length * share), (byte) 220);
        idle(70); watchFrame(pixels);
    }

    /** The camera open and watching, its light measured (50 ms at ISO 800 and a gain of 4.23), one page seen still. */
    private AtomicInteger watching() {
        AtomicInteger ready = new AtomicInteger();
        camera.awaitNextPage(ready::incrementAndGet); idle(100);
        light(50_000_000L, 800, 423, CONTROL_AE_STATE_CONVERGED);
        watchFrame(false); idle(400); watchFrame(false);
        assertEquals("a page seen still is offered once", 1, ready.get());
        return ready;
    }

    /** The session asked for at position {@code configuration} has nothing in flight any more. */
    private void idleSession(int configuration) {
        DocScanTestCamera device = device();
        device.callbacks.get(configuration).onReady(device.session); idle(0);
    }

    /** From the request for a page to the clip session's repeating request. */
    private void recording() {
        camera.captureOnce(); idle(0);
        idleSession(0);
        assertEquals(2, device().configurations);
    }

    /** Frames of the clip stream, 33 ms apart, each with its result; a gyroscope reading inside each exposure. */
    private void clipFrames(int count, float turning) {
        ReaderShadow clip = reader(W);
        var session = device().session;
        for (int i = 0; i < count; i++) {
            idle(33);
            long stamp = SystemClock.elapsedRealtimeNanos();
            if (turning >= 0) { // a gyroscope reports a head that does not turn too; under 0: no reading reaches the app
                SensorEvent event = ShadowSensorManager.createSensorEvent(3);
                event.timestamp = stamp + 1_000_000; event.values[0] = turning;
                sensors.sendSensorEventToListeners(event);
            }
            session.previewCallback.onCaptureCompleted(session, session.repeating,
                    result(stamp, 30_000_000L, 800, 500, CONTROL_AE_STATE_INACTIVE));
            DocScanTestImage image = new DocScanTestImage(clipImages);
            image.format = ImageFormat.YUV_420_888; image.width = W; image.height = H;
            image.rowStride = ROW; image.pixelStride = 1;
            luma[0] = (byte) stamps.size(); // which frame this is
            stamps.add(stamp);
            image.timestamp = stamp; image.buffer = ByteBuffer.wrap(luma);
            clip.image = image; clip.listener.onImageAvailable(clip.reader);
        }
    }

    /** The clip session has drained, the watch session is built, and its first frame has come. */
    private void watchingAgain() {
        idleSession(1);
        assertEquals(3, device().configurations);
        watchFrame(false);
    }

    private JSONObject record(String captureId) throws Exception {
        return new JSONObject(new String(Files.readAllBytes(new File(inboxDirectory, captureId + ".json").toPath()),
                StandardCharsets.UTF_8));
    }

    @Test public void the_watch_preview_is_zoomed_to_the_centre() {
        camera.preview(); idle(100);
        ReaderShadow watch = reader(320);
        assertEquals(240, watch.height);
        assertEquals("the small preview alone", List.of(List.of(watch.surface)), device().configured);
        assertEquals(CameraDevice.TEMPLATE_PREVIEW, repeating().template);
        assertEquals(List.of(watch.surface), repeating().targets);
        assertEquals("the middle half of the sensor each way", new Rect(1008, 756, 3024, 2268),
                asked(CaptureRequest.SCALER_CROP_REGION));
        assertEquals(new Range<>(15, 15), asked(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE));
        idle(70); watchFrame(false);
        assertEquals("the live image goes to the small window", 1, previews);
        assertEquals(List.of("image.close"), watchImages);
    }

    @Test public void a_watch_frame_is_returned_at_once_whatever_the_cameras_thread_is_doing() {
        // On the glasses, 2026-11-16, clip 26 of a run: the camera's thread was held up for over a second as a clip
        // began (it opens the clip's file and the codec), the watch preview's buffers were not returned meanwhile, the
        // camera could not get one ("Can't dequeue next output buffer") and never drained ("Error waiting to drain").
        camera.preview(); idle(100);
        ReaderShadow watch = reader(320);
        assertNotSame("taken on a thread that neither opens files nor changes sessions", Looper.getMainLooper(), watch.handler.getLooper());
        for (int i = 0; i < 2; i++) {
            DocScanTestImage image = new DocScanTestImage(watchImages);
            image.format = ImageFormat.YUV_420_888; image.width = 32; image.height = 24;
            image.rowStride = 32; image.pixelStride = 1;
            image.timestamp = SystemClock.elapsedRealtimeNanos(); image.buffer = ByteBuffer.wrap(new byte[32 * 24]);
            watch.image = image; watch.listener.onImageAvailable(watch.reader);
        }
        assertEquals("both returned before the camera's thread has looked at either", List.of("image.close", "image.close"), watchImages);
        assertEquals(0, previews);
        idle(0);
        assertEquals("it works on one copy; the frame that came meanwhile was only returned", 1, previews);
    }

    @Test public void a_session_the_camera_cannot_make_closes_the_camera_and_the_same_page_is_looked_for_again() {
        // The same night: the session for that clip could not be made, and the capture ended ("restart the app").
        // Nothing had been recorded and the camera is closed here, so nothing is in doubt.
        watching();
        device().refuseSession = true;
        camera.captureOnce(); idle(0);
        idleSession(0); idle(100);
        assertTrue(failures.isEmpty());
        assertEquals("the wearer is asked to hold still again", 1, notReady);
        assertArrayEquals("the clip that was opened is deleted", new String[0], inboxDirectory.list());
        assertEquals("the camera is opened again", 2, ManagerShadow.devices.size());
        AtomicInteger ready = new AtomicInteger();
        camera.awaitNextPage(ready::incrementAndGet); idle(100);
        light(50_000_000L, 800, 423, CONTROL_AE_STATE_CONVERGED);
        watchFrame(false); idle(400); watchFrame(false);
        assertEquals("the page that was in view is offered again without being turned", 1, ready.get());
    }

    @Test public void a_late_error_of_the_camera_that_was_let_go_does_not_stop_the_one_being_opened() {
        // The camera is opened again by itself after a failure, so an error the old one reports late now arrives
        // while the new one is being opened. Taken for the new one's, it left the camera closing for ever.
        watching();
        DocScanTestCamera old = device();
        old.refuseSession = true;
        old.suppressCloseCallback = true;
        camera.captureOnce(); idle(0);
        idleSession(0); idle(0);
        assertTrue(old.closed);
        old.state.onClosed(old); // the next camera is asked for
        old.state.onError(old, CameraDevice.StateCallback.ERROR_CAMERA_DEVICE); // and only then the old one's error comes
        idle(100);
        assertEquals(2, ManagerShadow.devices.size());
        assertNotSame(old, device());
        assertEquals("the new camera watches", 1, device().configurations);
        assertTrue(failures.isEmpty());
    }

    @Test public void a_clip_session_is_built_only_after_the_watch_session_is_idle() {
        watching();
        DocScanTestCamera device = device();
        camera.captureOnce(); idle(0);
        assertEquals("the watch session is asked to stop", 1, device.session.stops);
        assertEquals(1, encoder.opens);
        assertEquals(W, encoder.width); assertEquals(H, encoder.height);
        assertEquals("at 50 Mbit/s a page read 5.7% wrong, at 95 3.1% (M-29)", 95_000_000, encoder.bitrate);
        assertEquals(30, encoder.frameRate);
        idle(1000);
        assertEquals("nothing is built while the old session may have frames in flight", 1, device.configurations);
        idleSession(0);
        assertEquals(2, device.configurations);
        ReaderShadow clip = reader(W);
        assertEquals(H, clip.height); assertEquals(ImageFormat.YUV_420_888, clip.format); assertEquals(4, clip.maxImages);
        assertEquals("one output", List.of(clip.surface), device.configured.get(1));
        assertEquals(List.of(clip.surface), repeating().targets);
        assertNotSame("its frames never come on the camera's thread", Looper.getMainLooper(), clip.handler.getLooper());
    }

    @Test public void each_session_is_created_with_its_own_request_as_session_parameters() {
        // The frame-rate range is a session key of this camera. A session created without it was configured a second
        // time by its first request, after a wait for the device to idle that ran out once in eleven clips (M-30).
        watching();
        DocScanTestCamera device = device();
        assertEquals(1, device.sessionParameters.size());
        assertSame(device.session.repeating, device.sessionParameters.get(0));
        recording();
        assertEquals(2, device.sessionParameters.size());
        assertSame("the clip's own request, with its frame rate", device.session.repeating, device.sessionParameters.get(1));
    }

    @Test public void a_session_that_never_reports_idle_is_left_after_a_second_and_a_half() {
        watching();
        camera.captureOnce(); idle(1499);
        assertEquals(1, device().configurations);
        idle(1);
        assertEquals(2, device().configurations);
    }

    @Test public void the_clip_request_is_manual_with_the_gain_capped() {
        watching(); recording();
        assertEquals(CameraDevice.TEMPLATE_PREVIEW, repeating().template);
        assertEquals(CONTROL_AE_MODE_OFF, asked(CaptureRequest.CONTROL_AE_MODE));
        assertEquals(true, asked(CaptureRequest.CONTROL_AWB_LOCK));
        assertEquals(new Range<>(30, 30), asked(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE));
        assertEquals(33_333_333L, asked(CaptureRequest.SENSOR_FRAME_DURATION));
        assertEquals(30_000_000L, asked(CaptureRequest.SENSOR_EXPOSURE_TIME));
        assertEquals(800, asked(CaptureRequest.SENSOR_SENSITIVITY));
        assertEquals("50 ms at a gain of 4.23 would need 7.05 at 30 ms: capped at 5.0", 500,
                asked(CaptureRequest.CONTROL_POST_RAW_SENSITIVITY_BOOST));
        assertEquals(NOISE_REDUCTION_MODE_OFF, asked(CaptureRequest.NOISE_REDUCTION_MODE));
        assertEquals(EDGE_MODE_OFF, asked(CaptureRequest.EDGE_MODE));
        assertEquals(new Rect(1008, 756, 3024, 2268), asked(CaptureRequest.SCALER_CROP_REGION));
        assertNull("a tone curve makes this camera fail with error 4", asked(CaptureRequest.TONEMAP_MODE));
        assertNull(asked(CaptureRequest.TONEMAP_CURVE));
    }

    @Test public void the_gain_follows_the_preview_between_its_limits() {
        AtomicInteger ready = new AtomicInteger();
        camera.awaitNextPage(ready::incrementAndGet); idle(100);
        light(15_000_000L, 800, 500, CONTROL_AE_STATE_CONVERGED);
        watchFrame(false); idle(400); watchFrame(false);
        recording();
        assertEquals("half the exposure at 5.0 is 2.5 at 30 ms", 250, asked(CaptureRequest.CONTROL_POST_RAW_SENSITIVITY_BOOST));
    }

    @Test public void a_scene_too_dark_for_thirty_ms_at_the_gain_limit_is_recorded_at_sixty() throws Exception {
        // M-29: where 30 ms needed a gain of 7.05 and got 5.0 a page read 3.1% wrong; with half that light, 6.6%.
        // Twice the exposure brings the paper back to the brightness that was read.
        AtomicInteger ready = new AtomicInteger();
        camera.awaitNextPage(ready::incrementAndGet); idle(100);
        light(60_000_000L, 800, 600, CONTROL_AE_STATE_CONVERGED); // 12.0 at 30 ms, 6.0 at 60 ms
        watchFrame(false); idle(400); watchFrame(false);
        recording();
        assertEquals(60_000_000L, asked(CaptureRequest.SENSOR_EXPOSURE_TIME));
        assertEquals(new Range<>(15, 15), asked(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE));
        assertEquals(66_666_666L, asked(CaptureRequest.SENSOR_FRAME_DURATION));
        assertEquals("never over 5.0", 500, asked(CaptureRequest.CONTROL_POST_RAW_SENSITIVITY_BOOST));
        assertEquals("the same bits a frame at half the frames", 47_500_000, encoder.bitrate);
        assertEquals(15, encoder.frameRate);
        clipFrames(74, 0); idle(0);
        assertEquals("the first fifteen frames are not counted: this exposure settles more slowly", 0, encoder.ends);
        clipFrames(1, 0); idle(0);
        assertEquals(1, encoder.ends);
        watchingAgain();
        JSONObject record = record(pages.get(0).provenance.captureId);
        assertEquals(60_000_000L, record.getLong("exposure_ns"));
        assertEquals(15, record.getInt("settle"));
        assertEquals(15, record.getInt("frame_rate"));
    }

    @Test public void the_light_a_page_was_read_at_is_still_recorded_at_thirty() {
        watching(); recording(); // 50 ms at a gain of 4.23: 7.05 at 30 ms, the light of the page that passed
        assertEquals(30_000_000L, asked(CaptureRequest.SENSOR_EXPOSURE_TIME));
    }

    @Test public void the_gain_above_which_the_long_exposure_is_taken_can_be_set() {
        // One measurement set it (a page read at 7.05); it has to be movable once worn pages are read.
        ClipCamera.Options options = new ClipCamera.Options();
        options.longAboveBoost = 300;
        create(options);
        watching(); recording(); // 7.05 at 30 ms
        assertEquals(60_000_000L, asked(CaptureRequest.SENSOR_EXPOSURE_TIME));
        assertEquals("3.5 at 60 ms", 353, asked(CaptureRequest.CONTROL_POST_RAW_SENSITIVITY_BOOST));
    }

    @Test public void without_a_long_exposure_a_dark_scene_is_recorded_at_thirty() {
        ClipCamera.Options options = new ClipCamera.Options();
        options.longExposureNanos = 0;
        create(options);
        AtomicInteger ready = new AtomicInteger();
        camera.awaitNextPage(ready::incrementAndGet); idle(100);
        light(60_000_000L, 800, 600, CONTROL_AE_STATE_CONVERGED);
        watchFrame(false); idle(400); watchFrame(false);
        recording();
        assertEquals(30_000_000L, asked(CaptureRequest.SENSOR_EXPOSURE_TIME));
        assertEquals(95_000_000, encoder.bitrate);
    }

    @Test public void a_request_before_the_light_is_measured_waits_for_the_watch_preview() {
        camera.captureOnce(); idle(100);
        DocScanTestCamera device = device();
        assertEquals("the camera opens and watches first", 1, device.configurations);
        assertEquals(0, encoder.opens); assertEquals(0, device.session.stops);
        light(10_000_000L, 100, null, CONTROL_AE_STATE_SEARCHING);
        assertEquals("an exposure that is still searching is not the light to match", 0, encoder.opens);
        light(10_000_000L, 100, null, CONTROL_AE_STATE_CONVERGED);
        assertEquals(1, encoder.opens); assertEquals(1, device.session.stops);
        idleSession(0);
        assertEquals("a bright scene needs no gain: never under 1.0", 100, asked(CaptureRequest.CONTROL_POST_RAW_SENSITIVITY_BOOST));
    }

    @Test public void a_preview_that_does_not_settle_is_recorded_with_its_last_reading() {
        // The preview starts its exposure over whenever it restarts (after every clip, a pause, a reopening). A clip
        // asked for just then took its exposure and gain from a reading still on its way. It waits a moment for the
        // exposure to settle, and no longer than that: a page recorded a little off is better than none.
        camera.captureOnce(); idle(100);
        light(40_000_000L, 800, 300, CONTROL_AE_STATE_SEARCHING);
        idle(4000);
        assertEquals(0, encoder.opens);
        idle(1100);
        assertEquals(1, encoder.opens); assertEquals(0, notReady);
        idleSession(0);
        assertEquals("40 ms at 3.0 is 4.0 at 30 ms", 400, asked(CaptureRequest.CONTROL_POST_RAW_SENSITIVITY_BOOST));
    }

    @Test public void a_request_just_after_the_preview_restarted_waits_for_its_exposure_at_most_a_second_and_a_half() {
        watching(); recording();
        clipFrames(66, 0); idle(0);
        watchingAgain();
        assertEquals(1, pages.size());
        light(20_000_000L, 800, 200, CONTROL_AE_STATE_SEARCHING); // the restarted preview, still on its way
        camera.captureOnce(); idle(0);
        assertEquals("not with a reading that is still moving", 1, encoder.opens);
        idle(1500);
        assertEquals("but not for long", 2, encoder.opens);
    }

    @Test public void a_request_the_light_was_never_measured_for_is_given_up_before_anything_is_recorded() {
        camera.captureOnce(); idle(5100);
        assertEquals(1, notReady); assertEquals(0, encoder.opens);
        assertTrue(failures.isEmpty());
        assertFalse("the camera keeps watching", device().closed);
        assertEquals(1, device().configurations);
    }

    @Test public void sixty_counted_frames_end_the_clip() {
        watching(); recording();
        assertEquals("the gyroscope is listened to while a clip is recorded", 1, sensors.getListeners().size());
        clipFrames(65, 0); idle(0);
        assertEquals("the first six frames are not counted", 0, encoder.ends);
        clipFrames(1, 0); idle(0);
        assertEquals(66, encoder.offers); assertEquals(1, encoder.ends);
        assertEquals("and only then", 0, sensors.getListeners().size());
        clipFrames(3, 0);
        assertEquals("a frame after the end is not in the clip", 66, encoder.offers);
        assertEquals("but every frame is taken and returned", 69, clipImages.size());
    }

    @Test public void a_short_target_still_records_a_second() {
        ClipCamera.Options options = new ClipCamera.Options();
        options.targetFrames = 10;
        create(options);
        watching(); recording();
        clipFrames(31, 0); idle(0);
        assertEquals("sixteen frames fill it after half a second; the clip goes on", 0, encoder.ends);
        clipFrames(1, 0); idle(0);
        assertEquals(1, encoder.ends); assertEquals(32, encoder.offers);
    }

    @Test public void smeared_frames_are_not_counted() throws Exception {
        watching(); recording();
        clipFrames(6, 0);
        clipFrames(10, 0.1f); // 0.1 rad/s over 30 ms is 5.7 px at 1900 px of focal length
        clipFrames(59, 0.01f); idle(0);
        assertEquals("ten of the frames after the first six did not count", 0, encoder.ends);
        clipFrames(1, 0.01f); idle(0);
        assertEquals(1, encoder.ends); assertEquals(76, encoder.offers);
        watchingAgain();
        JSONArray frames = record(pages.get(0).provenance.captureId).getJSONArray("frames");
        assertEquals(76, frames.length());
        assertEquals("frames whose exposure the gyroscope covered: the two clocks are one", 76,
                record(pages.get(0).provenance.captureId).getInt("gyro_frames"));
        for (int i = 0; i < 76; i++) {
            double smear = frames.getJSONObject(i).getDouble("smear_px");
            if (i >= 6 && i < 16) assertEquals(5.7, smear, 0.01); else assertTrue(smear <= 2);
            assertEquals((long) stamps.get(i), frames.getJSONObject(i).getLong("t_ns"));
        }
        // What the head did is kept whole, not only its fastest reading a frame: worn for the first time (M-31) the
        // clips came back with a smear a frame and nothing to work out the head's turn from.
        JSONObject gyro = record(pages.get(0).provenance.captureId).getJSONObject("gyro");
        assertEquals(76, gyro.getJSONArray("t_ns").length());
        assertEquals(76, gyro.getJSONArray("x").length());
        assertEquals(76, gyro.getJSONArray("y").length());
        assertEquals(76, gyro.getJSONArray("z").length());
        assertEquals(stamps.get(7) + 1_000_000, gyro.getJSONArray("t_ns").getLong(7));
        assertEquals(0.1, gyro.getJSONArray("x").getDouble(7), 0.00001);
        assertEquals(0.0, gyro.getJSONArray("y").getDouble(7), 0.0);
    }

    @Test public void a_frame_the_gyroscope_said_nothing_about_is_not_taken_for_still() throws Exception {
        // Worn for the first time (M-31): eight of a clip's 296 frames had no reading of the gyroscope during their
        // exposure. They were written as 0 px of smear, counted, and offered to the phone as its stillest frames.
        watching(); recording();
        clipFrames(6, 0);
        clipFrames(8, -1);
        clipFrames(59, 0); idle(0);
        assertEquals("the eight did not count", 0, encoder.ends);
        clipFrames(1, 0); idle(0);
        assertEquals(1, encoder.ends); assertEquals(74, encoder.offers);
        watchingAgain();
        JSONObject record = record(pages.get(0).provenance.captureId);
        assertEquals(66, record.getInt("gyro_frames"));
        for (int i = 0; i < 74; i++) {
            double smear = record.getJSONArray("frames").getJSONObject(i).getDouble("smear_px");
            if (i >= 6 && i < 14) assertEquals("over any limit the phone applies", 999.0, smear, 0.0); else assertEquals(0.0, smear, 0.0);
        }
    }

    @Test public void ten_seconds_end_a_clip_that_never_fills() throws Exception {
        watching(); recording();
        clipFrames(46, 0); idle(0); // forty count after the first six
        assertEquals(0, encoder.ends);
        idle(10_000 - 46 * 33 - 1);
        assertEquals(0, encoder.ends);
        idle(1);
        assertEquals(1, encoder.ends);
        watchingAgain();
        assertEquals("with two thirds of its frames, what it has is the page", 1, pages.size());
        assertEquals(46, record(pages.get(0).provenance.captureId).getJSONArray("frames").length());
        assertEquals(0, notReady);
    }

    /** The second and later clips of a test: the watch session after clip {@code number - 1} is the one that is left. */
    private void recordingAgain(int number) {
        light(50_000_000L, 800, 423, CONTROL_AE_STATE_CONVERGED);
        camera.captureOnce(); idle(0);
        idleSession(2 * number);
        assertEquals(2 * number + 2, device().configurations);
    }

    private void watchingAgainAfter(int number) {
        idleSession(2 * number + 1);
        assertEquals(2 * number + 3, device().configurations);
        watchFrame(false);
    }

    /**
     * The operator's morning of 2026-11-17 (M-44 (15)): eight of 35 clips ran to their ten seconds with 4 to 38
     * still frames, each was saved as its page all the same, and three booklets came back without an answer five
     * minutes later. The glasses knew the count when the clip ended. A clip that runs out its time with fewer than
     * two thirds of its frames is not a page: the page is looked for and recorded again.
     */
    @Test public void a_clip_that_runs_out_its_time_short_of_still_frames_is_not_a_page() {
        watching(); recording();
        clipFrames(20, 0); idle(10_000 - 20 * 33); // fourteen count
        assertEquals(1, encoder.ends);
        watchingAgain();
        assertTrue("fourteen still frames are not a page", pages.isEmpty());
        assertTrue(failures.isEmpty());
        assertEquals("the wearer is asked to hold still and the page is looked for again", 1, notReady);
        assertArrayEquals("its file is gone", new String[0], inboxDirectory.list());
    }

    /** A wearer who cannot hold still is not kept at one page for good: the third short clip in a row is the page. */
    @Test public void the_third_short_clip_in_a_row_is_taken_as_it_is() throws Exception {
        watching(); recording();
        clipFrames(20, 0); idle(10_000 - 20 * 33); watchingAgain();
        recordingAgain(1);
        clipFrames(20, 0); idle(10_000 - 20 * 33); watchingAgainAfter(1);
        assertTrue(pages.isEmpty());
        assertEquals(2, notReady);
        recordingAgain(2);
        clipFrames(20, 0); idle(10_000 - 20 * 33); watchingAgainAfter(2);
        assertEquals(1, pages.size());
        assertEquals(20, record(pages.get(0).provenance.captureId).getJSONArray("frames").length());
        assertEquals(2, notReady);
        // A page was handed over: the count of short clips starts over with the next page.
        recordingAgain(3);
        clipFrames(20, 0); idle(10_000 - 20 * 33); watchingAgainAfter(3);
        assertEquals(1, pages.size());
        assertEquals(3, notReady);
    }

    /** What the wearer cuts short with a tap or a double tap is the page, however few frames it has (2026-11-16). */
    @Test public void a_clip_the_wearer_cut_short_is_the_page_whatever_it_has() throws Exception {
        watching(); recording();
        clipFrames(20, 0); idle(0);
        camera.pausePreview(); idle(0);
        assertEquals(1, encoder.ends);
        idleSession(1);
        assertEquals("fourteen still frames, and the wearer's own choice", 1, pages.size());
        assertEquals(0, notReady);
    }

    @Test public void a_clip_without_one_still_frame_is_not_a_page_and_the_page_is_looked_for_again() {
        watching(); recording();
        clipFrames(20, 0.1f);
        idle(10_000);
        assertEquals(1, encoder.ends);
        watchingAgain();
        assertTrue(pages.isEmpty()); assertTrue(failures.isEmpty());
        assertEquals("nothing was taken: the wearer is asked to hold still", 1, notReady);
        assertArrayEquals(new String[0], inboxDirectory.list());
        AtomicInteger ready = new AtomicInteger();
        camera.awaitNextPage(ready::incrementAndGet); idle(100);
        watchFrame(false); idle(400); watchFrame(false);
        assertEquals("the same page is offered again", 1, ready.get());
    }

    @GraphicsMode(GraphicsMode.Mode.NATIVE)
    @Test public void the_page_arrives_as_a_frame_with_its_clip_in_the_inbox() throws Exception {
        int[] asked = new int[3];
        byte[][] kept = new byte[1][];
        camera.pageEncoder = (nv21, width, height, quality) -> {
            asked[0] = width; asked[1] = height; asked[2] = quality; kept[0] = nv21.clone();
            Bitmap grey = Bitmap.createBitmap(width, height, Bitmap.Config.RGB_565);
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            grey.compress(Bitmap.CompressFormat.JPEG, quality, out); grey.recycle();
            return out.toByteArray();
        };
        luma[W] = 99;   // padding after the first row: not part of the picture
        luma[ROW] = 77; // the second row's first pixel
        luma[luma.length - 1] = 55;
        watching(); recording();
        clipFrames(66, 0); idle(0);
        assertTrue("the page waits until the camera watches again", pages.isEmpty());
        watchingAgain();

        assertEquals(1, pages.size()); assertTrue(failures.isEmpty());
        GlassCamera.Captured page = pages.get(0);
        assertEquals(W, page.width); assertEquals(H, page.height); assertTrue(page.associationResolved);
        BitmapFactory.Options bounds = new BitmapFactory.Options();
        bounds.inJustDecodeBounds = true;
        BitmapFactory.decodeByteArray(page.jpeg, 0, page.jpeg.length, bounds);
        assertEquals(W, bounds.outWidth); assertEquals(H, bounds.outHeight);
        assertArrayEquals(new int[]{W, H, 90}, asked);
        assertEquals(W * H * 3 / 2, kept[0].length);
        assertEquals("the thirtieth counted frame, the middle of sixty", 35, kept[0][0]);
        assertEquals("rows are packed without the camera's padding", 77, kept[0][W]);
        assertEquals(55, kept[0][W * H - 1]);
        for (int i = W * H; i < kept[0].length; i++) assertEquals("grey", (byte) 128, kept[0][i]);

        CaptureProvenance provenance = page.provenance;
        assertEquals("clip_frame", provenance.sourceKind);
        assertEquals(stamps.get(35), provenance.imageTimestampNanos);
        assertEquals("that frame's own result", stamps.get(35), provenance.resultTimestampNanos);
        assertEquals(Long.valueOf(30_000_000L), provenance.exposureNanos);
        assertEquals(Integer.valueOf(800), provenance.sensitivityIso);
        assertTrue(inbox.has(provenance.captureId));
        String[] left = inboxDirectory.list();
        Arrays.sort(left);
        assertArrayEquals("the clip under the page's own number, and its record",
                new String[]{provenance.captureId + ".json", provenance.captureId + ".mp4"}, left);
        assertEquals(8, new File(inboxDirectory, provenance.captureId + ".mp4").length());

        JSONObject record = record(provenance.captureId);
        assertEquals(1, record.getInt("schema"));
        assertEquals(provenance.captureId, record.getString("capture_id"));
        assertEquals(W, record.getInt("width")); assertEquals(H, record.getInt("height"));
        assertEquals(270, record.getInt("rotation_degrees"));
        assertEquals(30_000_000L, record.getLong("exposure_ns"));
        assertEquals(800, record.getInt("sensitivity_iso"));
        assertEquals(500, record.getInt("boost"));
        JSONObject preview = record.getJSONObject("preview");
        assertEquals(50_000_000L, preview.getLong("exposure_ns"));
        assertEquals(800, preview.getInt("sensitivity_iso"));
        assertEquals(423, preview.getInt("boost"));
        assertEquals("one entry for each frame of the clip", 66, record.getJSONArray("frames").length());
        assertEquals(0, record.getInt("dropped"));
        assertEquals(6, record.getInt("settle"));
        assertEquals(30, record.getInt("frame_rate"));
        assertEquals("every frame had a reading of the gyroscope", 66, record.getInt("gyro_frames"));
        assertEquals("and for each the readings ended before its exposure did: how often that is, is counted", 66, record.getInt("gyro_partial"));

        // The desk check reads this line: frames in the clip, counted, refused by the encoder, the clip's size, the
        // wait for the first frame and for the watch preview's return, the gain applied.
        List<org.robolectric.shadows.ShadowLog.LogItem> lines = org.robolectric.shadows.ShadowLog.getLogsForTag("DocScanGlassDoc");
        String line = lines.get(lines.size() - 1).msg;
        // And, after those: whether the clip became its page, and how many short clips in a row were not kept.
        assertTrue(line, line.matches("clip frames=66 counted=60 dropped=0 bytes=8 first_ms=\\d+ back_ms=\\d+ boost=500 exposure_ms=30 gyro=66 kept=true short=0"));
    }

    @Test public void a_second_request_during_a_clip_starts_nothing() {
        watching(); recording();
        clipFrames(10, 0);
        camera.captureOnce(); idle(0);
        assertEquals(1, encoder.opens); assertEquals(2, device().configurations);
        clipFrames(56, 0); idle(0);
        assertEquals(1, encoder.ends);
        watchingAgain();
        assertEquals(1, pages.size());
    }

    @Test public void a_frame_the_encoder_refuses_is_not_in_the_clip() throws Exception {
        watching(); recording();
        clipFrames(10, 0);
        encoder.refuse = true; clipFrames(2, 0); encoder.refuse = false;
        clipFrames(55, 0); idle(0);
        assertEquals(0, encoder.ends);
        clipFrames(1, 0); idle(0);
        assertEquals(1, encoder.ends);
        watchingAgain();
        JSONObject record = record(pages.get(0).provenance.captureId);
        assertEquals(66, record.getJSONArray("frames").length());
        assertEquals(2, record.getInt("dropped"));
        assertEquals("the record's entries are the clip's frames", (long) stamps.get(12),
                record.getJSONArray("frames").getJSONObject(10).getLong("t_ns"));
    }

    @Test public void after_the_clip_the_camera_watches_again_once_idle() {
        AtomicInteger ready = watching();
        recording();
        DocScanTestCamera device = device();
        clipFrames(66, 0); idle(0);
        assertEquals("the clip session is asked to stop", 2, device.session.stops);
        assertEquals("the watch session is not built before the clip session is idle", 2, device.configurations);
        idleSession(0);
        assertEquals("the idle of a session already left does not count", 2, device.configurations);
        idleSession(1);
        assertEquals(3, device.configurations);
        assertEquals(List.of(reader(320).surface), device.configured.get(2));
        assertEquals(new Range<>(15, 15), asked(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE));
        assertTrue(pages.isEmpty());
        watchFrame(false);
        assertEquals(1, pages.size());

        camera.awaitNextPage(ready::incrementAndGet); idle(0);
        // The restarted preview starts its exposure over: until it has settled, its frames are not page evidence.
        idle(100); watchFrame(true); idle(500); watchFrame(true);
        assertEquals(1, ready.get());
        light(50_000_000L, 800, 423, CONTROL_AE_STATE_CONVERGED);
        idle(100); watchFrame(false); idle(500); watchFrame(false);
        assertEquals("an unmoving page is not recorded again", 1, ready.get());
        idle(100); watchFrame(true); idle(500); watchFrame(true);
        assertEquals("a turned page is offered", 2, ready.get());
    }

    @Test public void a_pause_while_recording_ends_the_clip_at_once_and_what_it_has_is_the_page() {
        // A tap (pause) or a double tap (end) while a page is being recorded. The clip used to be thrown away: the
        // page the wearer was looking at was then not in the booklet, and an end was left hanging until asked again.
        // The camera stops just as fast; what has been recorded is kept, as a still in flight is.
        watching(); recording();
        clipFrames(10, 0);
        DocScanTestCamera device = device();
        camera.pausePreview(); idle(0);
        assertEquals("the clip is closed", 1, encoder.ends);
        assertEquals("the clip session is asked to stop", 2, device.session.stops);
        assertFalse("the camera is not closed before that session is idle", device.closed);
        clipFrames(2, 0);
        assertEquals("frames still in flight are taken and returned, not recorded", 10, encoder.offers);
        assertEquals(12, clipImages.size());
        idleSession(1); idle(0);
        assertTrue(device.closed);
        assertEquals("no session is built for a camera that is being closed", 2, device.configurations);
        assertEquals("the four frames that counted are a page", 1, pages.size());
        assertEquals(0, notReady); assertTrue(failures.isEmpty());
        assertTrue(inbox.has(pages.get(0).provenance.captureId));
        assertEquals(0, sensors.getListeners().size());

        camera.preview(); idle(100);
        assertEquals("the camera opens again when it is asked to watch", 2, ManagerShadow.devices.size());
        assertEquals(1, device().configurations);
    }

    @Test public void a_pause_before_any_frame_has_counted_drops_the_clip() {
        watching(); recording();
        clipFrames(3, 0);
        camera.pausePreview(); idle(0);
        idleSession(1); idle(0);
        assertTrue(pages.isEmpty()); assertTrue(failures.isEmpty());
        assertEquals("the controller is told that nothing was taken", 1, notReady);
        assertArrayEquals("nothing is left in the inbox", new String[0], inboxDirectory.list());
        assertTrue(device().closed);
    }

    @Test public void a_page_whose_clip_a_pause_dropped_is_looked_for_again_on_return() {
        // A tap pauses at once from 2026-11-16, so a clip can be dropped before a frame of it has counted. The page
        // was marked as taken when its clip began: left so, it would be passed over on return until a page was turned.
        watching(); recording();
        clipFrames(3, 0);
        camera.pausePreview(); idle(0);
        idleSession(1); idle(0);
        assertEquals(1, notReady);
        AtomicInteger ready = new AtomicInteger();
        camera.awaitNextPage(ready::incrementAndGet); idle(100);
        light(50_000_000L, 800, 423, CONTROL_AE_STATE_CONVERGED);
        watchFrame(false); idle(400); watchFrame(false);
        assertEquals("the page that was in view is offered again without being turned", 1, ready.get());
    }

    @Test public void a_pause_after_the_recording_ended_still_hands_the_page_over() {
        watching(); recording();
        clipFrames(66, 0); idle(0);
        camera.pausePreview(); idle(0);
        assertTrue(pages.isEmpty());
        idleSession(1);
        assertTrue(device().closed);
        assertEquals(1, pages.size()); assertEquals(0, notReady);
        assertTrue(inbox.has(pages.get(0).provenance.captureId));
    }

    @Test public void closing_while_recording_waits_for_the_session_and_then_for_the_camera() {
        watching(); recording();
        clipFrames(10, 0);
        DocScanTestCamera device = device();
        ReaderShadow clip = reader(W);
        AtomicInteger done = new AtomicInteger();
        camera.close(done::incrementAndGet); idle(0);
        assertEquals(1, encoder.ends);
        assertFalse(device.closed); assertEquals(0, done.get());
        idleSession(1);
        assertTrue(device.closed); assertTrue(clip.closed);
        assertEquals("the camera's thread may be let go only now", 1, done.get());
        assertTrue(pages.isEmpty()); assertTrue(failures.isEmpty()); assertEquals(0, notReady);
        assertArrayEquals(new String[0], inboxDirectory.list());
        camera.preview(); camera.captureOnce(); idle(100);
        assertEquals("a closed camera does not open again", 1, ManagerShadow.devices.size());
    }

    @Test public void an_encoder_failure_is_a_failed_capture_and_the_camera_goes_on() {
        watching(); recording();
        encoder.failure = "clip java.lang.IllegalStateException";
        clipFrames(66, 0); idle(0);
        assertEquals(List.of("clip java.lang.IllegalStateException"), failures);
        assertTrue(pages.isEmpty());
        assertArrayEquals(new String[0], inboxDirectory.list());
        idleSession(1);
        assertTrue("the camera is closed in order after the failure", device().closed);
        camera.preview(); idle(100);
        assertEquals(2, ManagerShadow.devices.size());
        assertEquals("and watches again", List.of(reader(320).surface), device().configured.get(0));
    }

    /**
     * 2026-11-18, forty desk clips on the route that sends: one file held 64 of the 66 frames the encoder had taken (the
     * second and third were missing, though the encoder's own count said every frame was done). The frames behind them
     * could not be decoded up to the next key frame, and those that could no longer paired with what the glasses had
     * logged for each frame. The clip went out as a whole page and came back as the one frame it arrived as.
     */
    @Test public void a_clip_whose_file_holds_fewer_frames_than_the_encoder_took_is_a_failed_capture() {
        watching(); recording();
        encoder.lost = 2;
        clipFrames(66, 0); idle(0);
        assertEquals(List.of("clip lost 2 of 66 frames"), failures);
        assertTrue("it is not a page", pages.isEmpty());
        assertArrayEquals("and nothing of it is left to send", new String[0], inboxDirectory.list());
        idleSession(1);
        camera.preview(); idle(100);
        assertEquals("the camera goes on, as after any failed capture", 2, ManagerShadow.devices.size());
    }

    @Test public void an_encoder_that_cannot_be_opened_is_a_failed_capture_before_any_session_change() {
        watching();
        encoder.openFailure = new IOException("no codec");
        camera.captureOnce(); idle(0);
        assertEquals(List.of("encoder java.io.IOException: no codec"), failures);
        assertEquals(1, device().configurations);
        idleSession(0);
        assertTrue(device().closed);
        assertArrayEquals(new String[0], inboxDirectory.list());
    }

    @Test public void a_camera_error_while_recording_drops_the_clip_and_the_same_page_is_looked_for_again() {
        watching(); recording();
        clipFrames(10, 0);
        DocScanTestCamera device = device();
        device.state.onError(device, CameraDevice.StateCallback.ERROR_CAMERA_DEVICE); idle(0);
        assertTrue("nothing was taken and nothing is in doubt: the camera is closed and the clip deleted", failures.isEmpty());
        assertEquals(1, notReady);
        assertEquals(1, encoder.ends); assertTrue(device.closed);
        assertArrayEquals(new String[0], inboxDirectory.list());
        device.state.onError(device, CameraDevice.StateCallback.ERROR_CAMERA_DEVICE); idle(0);
        assertEquals("once", 1, notReady);
        idle(100);
        assertEquals("the camera opens again", 2, ManagerShadow.devices.size());
        assertEquals("and watches", List.of(reader(320).surface), device().configured.get(0));
    }

    @Test public void a_camera_error_after_the_clip_was_recorded_still_hands_the_page_over() {
        // On the glasses, 2026-11-16: the clip was whole and its file closed when the camera failed on its way back
        // to watching. The page was thrown away and the session ended.
        watching(); recording();
        clipFrames(66, 0); idle(0);
        assertEquals(1, encoder.ends);
        DocScanTestCamera device = device();
        device.state.onError(device, CameraDevice.StateCallback.ERROR_CAMERA_DEVICE); idle(100);
        assertEquals(1, pages.size()); assertTrue(failures.isEmpty()); assertEquals(0, notReady);
        assertTrue(inbox.has(pages.get(0).provenance.captureId));
        assertEquals("the camera opens again for the next page", 2, ManagerShadow.devices.size());
    }

    @Test public void the_page_of_a_clip_still_being_closed_when_the_camera_fails_comes_once_its_file_is_closed() {
        watching(); recording();
        encoder.holdEnd = true;
        clipFrames(66, 0); idle(0);
        DocScanTestCamera device = device();
        device.state.onError(device, CameraDevice.StateCallback.ERROR_CAMERA_DEVICE); idle(100);
        assertTrue(pages.isEmpty());
        encoder.finish(); idle(0);
        assertEquals(1, pages.size()); assertTrue(failures.isEmpty());
    }

    @Test public void three_camera_errors_with_no_page_between_them_fail_the_capture() {
        camera.preview(); idle(100);
        for (int i = 0; i < 2; i++) {
            DocScanTestCamera device = device();
            device.state.onError(device, CameraDevice.StateCallback.ERROR_CAMERA_DEVICE); idle(100);
            assertTrue(failures.isEmpty());
        }
        assertEquals(3, ManagerShadow.devices.size());
        DocScanTestCamera device = device();
        device.state.onError(device, CameraDevice.StateCallback.ERROR_CAMERA_DEVICE); idle(100);
        assertEquals(List.of("camera error 4"), failures);
        assertEquals("it is not opened a fourth time by itself", 3, ManagerShadow.devices.size());
    }

    @Test public void frames_are_taken_and_returned_when_no_clip_is_recorded() {
        camera.preview(); idle(100);
        clipFrames(3, 0);
        assertEquals(3, clipImages.size()); assertEquals(0, encoder.offers);
        assertEquals(0, sensors.getListeners().size());
    }

    /** The counts reported while recording, without the report that ends it. */
    private List<Integer> counts() {
        List<Integer> counts = new ArrayList<>();
        for (String each : progress) if (!each.endsWith(" end")) counts.add(Integer.parseInt(each.substring(0, each.indexOf('/'))));
        return counts;
    }

    // Worn on 2026-11-16 (M-33): on three pages the head turned at 0.12-0.145 rad/s, 5 to 8 frames of 290 were still
    // and no page came; nothing on the display said that a clip was being recorded or that it was waiting for a
    // still head. The display's bar is fed by these reports.
    @Test public void a_clip_of_still_frames_reports_its_count_from_nothing_to_all_it_wants() {
        watching();
        assertTrue("nothing is reported while the camera only watches", progress.isEmpty());
        recording();
        assertEquals("the recording has begun and nothing has counted yet", List.of("0/60"), progress);
        clipFrames(66, 0);
        List<Integer> counts = counts();
        assertEquals("the end is not among them yet", progress.size(), counts.size());
        assertTrue("as the count grows, at most about ten times a second over 2.2 s: " + progress,
                counts.size() >= 12 && counts.size() <= 23);
        for (int i = 1; i < counts.size(); i++) {
            assertTrue("only a count that has grown is reported: " + progress, counts.get(i) > counts.get(i - 1));
            if (i > 1) assertTrue("a tenth of a second apart: " + progressAt, progressAt.get(i) - progressAt.get(i - 1) >= 100);
        }
        assertEquals("the first frame that counts is shown at once", Integer.valueOf(1), counts.get(1));
        idle(0);
        assertEquals("once more when the recording ends, with the final count", "60/60 end", progress.get(progress.size() - 1));
        assertEquals(counts.size() + 1, progress.size());
        int reports = progress.size();
        watchingAgain();
        assertEquals(1, pages.size());
        camera.awaitNextPage(() -> { }); idle(100); watchFrame(false); idle(400); watchFrame(false);
        assertEquals("and nothing while the camera watches again", reports, progress.size());
        assertTrue("the small window shows the frames being recorded", previews >= 9);
    }

    @Test public void a_clip_whose_frames_are_all_smeared_stays_at_nothing_until_its_ten_seconds_are_up() {
        watching(); recording();
        clipFrames(100, 0.1f); // 0.1 rad/s over 30 ms is 5.7 px
        assertEquals("the count does not grow, so nothing is reported: the bar stands still", List.of("0/60"), progress);
        idle(10_000);
        assertEquals(List.of("0/60", "0/60 end"), progress);
        watchingAgain();
        assertEquals("not a page: the wearer is asked to hold still", 1, notReady);
        assertEquals(2, progress.size());
    }

    @Test public void the_count_reported_grows_only_on_still_frames_and_never_past_what_the_clip_wants() {
        ClipCamera.Options options = new ClipCamera.Options();
        options.targetFrames = 10;
        create(options);
        watching(); recording();
        clipFrames(6, 0);
        assertEquals("frames that are still settling do not count", List.of("0/10"), progress);
        clipFrames(5, 0);
        assertEquals("the first at once, the next a tenth of a second later", List.of("0/10", "1/10", "5/10"), progress);
        clipFrames(10, 0.1f);
        assertEquals("the head moves: nothing", List.of("0/10", "1/10", "5/10"), progress);
        clipFrames(11, 0); // the clip has its ten after five of these and goes on to the end of its first second
        assertEquals("never more than it wants, and what it wants is reported once",
                List.of("0/10", "1/10", "5/10", "6/10", "10/10"), progress);
        idle(0);
        assertEquals(1, encoder.ends);
        assertEquals(List.of("0/10", "1/10", "5/10", "6/10", "10/10", "10/10 end"), progress);
    }

    @Test public void a_clip_given_up_ends_its_report_once_and_one_that_never_began_reports_nothing() {
        watching();
        camera.captureOnce(); idle(0); // its session is not built yet
        camera.pausePreview(); idle(0);
        assertTrue("it was never recording: " + progress, progress.isEmpty());
        idleSession(0); idle(0);

        camera.awaitNextPage(() -> { }); idle(100);
        light(50_000_000L, 800, 423, CONTROL_AE_STATE_CONVERGED);
        camera.captureOnce(); idle(0);
        idleSession(0);
        clipFrames(10, 0);
        camera.pausePreview(); idle(0); // a tap: what the clip has is the page
        assertEquals(List.of("0/60", "1/60", "4/60 end"), progress);
        idleSession(1); idle(0);
        assertEquals("the page is handed over without another report", 3, progress.size());
        assertEquals(1, pages.size());
    }

    @Test public void the_far_mark_shows_only_while_waiting() {
        ClipCamera.Options options = new ClipCamera.Options();
        options.farShare = 0.5f;
        create(options);
        camera.preview(); idle(100);
        light(50_000_000L, 800, 423, CONTROL_AE_STATE_CONVERGED);
        watchShare(0.2f);
        assertEquals("less than half the window is paper", List.of(true), far);
        watchShare(0.8f);
        assertEquals(List.of(true, false), far);
        watchShare(0.2f); watchShare(0.25f);
        assertEquals("told once", List.of(true, false, true), far);
        camera.captureOnce(); idle(0);
        assertEquals("not while a clip is recorded", List.of(true, false, true, false), far);
        idleSession(0);
        clipFrames(8, 0);
        assertEquals(4, far.size());
    }

    /**
     * The distance between lines of print is measured for the record (watch_status lines=) and shows nothing: the
     * mark it drove until 2026-11-17 said "too near" by a rule the operator's trial of that day did not bear out
     * (pages with larger print read best; what failed lay toward the frame's edge, M-44).
     */
    @Test public void the_distance_between_lines_of_print_is_measured_for_the_record_twice_a_second_at_most() {
        camera.preview(); idle(100);
        light(50_000_000L, 800, 423, CONTROL_AE_STATE_CONVERGED);
        idle(600); watchPrint(7.6); // 47.9 px of the frame
        assertEquals(47.9f, (float) org.robolectric.util.ReflectionHelpers.getField(camera, "lines"), 1.5f);
        idle(70); watchPrint(6.2);
        assertEquals("the transform is not run on every frame", 47.9f,
                (float) org.robolectric.util.ReflectionHelpers.getField(camera, "lines"), 1.5f);
        idle(500); watchPrint(6.2); // 39 px
        assertEquals(39f, (float) org.robolectric.util.ReflectionHelpers.getField(camera, "lines"), 1.5f);
        idle(600); watchFrame(false); // a picture in which no print is found
        assertEquals(0f, (float) org.robolectric.util.ReflectionHelpers.getField(camera, "lines"), 0f);
    }

    @Test public void the_far_mark_is_off_until_a_share_is_set() {
        // Its rule does not measure distance: worn on 2026-11-16 the mark stood for 38 of 67 s of watching while the
        // characters were as large as the page that passed needed (M-31, register 2-24).
        camera.preview(); idle(100);
        light(50_000_000L, 800, 423, CONTROL_AE_STATE_CONVERGED);
        watchShare(0.1f);
        assertTrue(far.isEmpty());
    }

    @Test public void the_clip_route_keeps_no_future_pages_and_takes_no_second_still() {
        assertFalse(camera.supportsFuturePages());
        AtomicInteger idle = new AtomicInteger(), skipped = new AtomicInteger();
        camera.stopFuturePages(idle::incrementAndGet);
        assertEquals(1, idle.get());
        camera.requestNativeAlternative(null, new CaptureSurface.NativeAlternative() {
            @Override public boolean onStarting() { throw new AssertionError(); }
            @Override public void onOriginal(byte[] jpeg, CaptureProvenance source, boolean sameScene) { throw new AssertionError(); }
            @Override public void onSkipped() { skipped.incrementAndGet(); }
        });
        assertEquals(1, skipped.get());
        assertNull(camera.nativeSelectionScene(null));
        assertFalse(camera.isNativeSelectionSceneCurrent(null));
        GlassesCaptureSurface surface = new GlassesCaptureSurface(RuntimeEnvironment.getApplication(), camera,
                new HudView(RuntimeEnvironment.getApplication()), new Handler(Looper.getMainLooper()), (generation, purpose) -> { });
        assertFalse(surface.supportsFuturePages());
    }
}
