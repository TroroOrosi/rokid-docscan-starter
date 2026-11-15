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
            ended.done(offered.size(), file.length(), failure);
        }
    }

    private final List<GlassCamera.Captured> pages = new ArrayList<>();
    private final List<String> failures = new ArrayList<>();
    private final List<String> watchImages = new ArrayList<>(), clipImages = new ArrayList<>();
    private final List<Float> progress = new ArrayList<>();
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
            @Override public void showClipProgress(float share) { progress.add(share); }
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
    }

    private void watchFrame(boolean turned) {
        byte[] pixels = new byte[32 * 24]; Arrays.fill(pixels, (byte) 180);
        if (turned) Arrays.fill(pixels, 0, pixels.length / 3, (byte) 70);
        watchFrame(pixels);
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
            if (turning > 0) {
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
        assertEquals(1, encoder.opens); assertEquals(1, device.session.stops);
        idleSession(0);
        assertEquals("a bright scene needs no gain: never under 1.0", 100, asked(CaptureRequest.CONTROL_POST_RAW_SENSITIVITY_BOOST));
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
        assertEquals("frames whose exposure the gyroscope covered: the two clocks are one", 70,
                record(pages.get(0).provenance.captureId).getInt("gyro_frames"));
        for (int i = 0; i < 76; i++) {
            double smear = frames.getJSONObject(i).getDouble("smear_px");
            if (i >= 6 && i < 16) assertEquals(5.7, smear, 0.01); else assertTrue(smear <= 2);
            assertEquals((long) stamps.get(i), frames.getJSONObject(i).getLong("t_ns"));
        }
    }

    @Test public void ten_seconds_end_a_clip_that_never_fills() throws Exception {
        watching(); recording();
        clipFrames(20, 0); idle(0);
        assertEquals(0, encoder.ends);
        idle(10_000 - 20 * 33 - 1);
        assertEquals(0, encoder.ends);
        idle(1);
        assertEquals(1, encoder.ends);
        watchingAgain();
        assertEquals("what it has is the page", 1, pages.size());
        assertEquals(20, record(pages.get(0).provenance.captureId).getJSONArray("frames").length());
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
        assertEquals("no gyroscope reading came in this test", 0, record.getInt("gyro_frames"));

        // The desk check reads this line: frames in the clip, counted, refused by the encoder, the clip's size, the
        // wait for the first frame and for the watch preview's return, the gain applied.
        List<org.robolectric.shadows.ShadowLog.LogItem> lines = org.robolectric.shadows.ShadowLog.getLogsForTag("DocScanGlassDoc");
        String line = lines.get(lines.size() - 1).msg;
        assertTrue(line, line.matches("clip frames=66 counted=60 dropped=0 bytes=8 first_ms=\\d+ back_ms=\\d+ boost=500 exposure_ms=30 gyro=0"));
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

    @Test public void a_pause_while_recording_closes_the_clip_and_the_camera_in_order() {
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
        idleSession(1);
        assertTrue(device.closed);
        assertEquals("no session is built for a camera that is being closed", 2, device.configurations);
        assertTrue(pages.isEmpty()); assertTrue(failures.isEmpty());
        assertEquals("the controller is told that no photo is coming", 1, notReady);
        assertArrayEquals("nothing is left in the inbox", new String[0], inboxDirectory.list());
        assertEquals(0, sensors.getListeners().size());

        camera.preview(); idle(100);
        assertEquals("the camera opens again when it is asked to watch", 2, ManagerShadow.devices.size());
        assertEquals(1, device().configurations);
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

    @Test public void a_camera_error_while_recording_closes_the_clip_and_fails_the_capture() {
        watching(); recording();
        clipFrames(10, 0);
        DocScanTestCamera device = device();
        device.state.onError(device, CameraDevice.StateCallback.ERROR_CAMERA_DEVICE); idle(0);
        assertEquals(List.of("camera error 4"), failures);
        assertEquals(1, encoder.ends); assertTrue(device.closed);
        assertArrayEquals(new String[0], inboxDirectory.list());
        device.state.onError(device, CameraDevice.StateCallback.ERROR_CAMERA_DEVICE); idle(0);
        assertEquals("once", 1, failures.size());
        camera.preview(); idle(100);
        assertEquals(2, ManagerShadow.devices.size());
    }

    @Test public void frames_are_taken_and_returned_when_no_clip_is_recorded() {
        camera.preview(); idle(100);
        clipFrames(3, 0);
        assertEquals(3, clipImages.size()); assertEquals(0, encoder.offers);
        assertEquals(0, sensors.getListeners().size());
    }

    @Test public void the_progress_line_grows_with_the_counted_frames() {
        watching(); recording();
        clipFrames(66, 0);
        assertTrue("about five times a second over 2.2 s: " + progress, progress.size() >= 9 && progress.size() <= 12);
        for (int i = 1; i < progress.size(); i++) assertTrue(progress.get(i) >= progress.get(i - 1));
        assertEquals("nothing is counted while the brightness settles", 0f, progress.get(0), 0f);
        assertTrue(progress.get(progress.size() - 1) > 0.8f && progress.get(progress.size() - 1) <= 1f);
        idle(0);
        assertEquals("the line goes when the clip ends", 0f, progress.get(progress.size() - 1), 0f);
        assertTrue("the small window shows the frames being recorded", previews >= 9);
    }

    @Test public void the_far_mark_shows_only_while_waiting() {
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

    @Test public void a_far_share_of_zero_shows_no_mark() {
        ClipCamera.Options options = new ClipCamera.Options();
        options.farShare = 0;
        create(options);
        camera.preview(); idle(100);
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
