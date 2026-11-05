package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import static org.robolectric.Shadows.shadowOf;
import static android.hardware.camera2.CameraMetadata.*;
import android.content.Intent;
import android.app.Activity;
import org.robolectric.Robolectric;
import org.robolectric.shadows.ShadowActivity;
import android.graphics.ImageFormat;
import android.hardware.camera2.*;
import org.robolectric.annotation.Implementation;
import org.robolectric.annotation.Implements;
import android.media.DocScanTestImage;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import java.nio.ByteBuffer;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.shadow.api.Shadow;
import org.robolectric.shadows.ShadowCaptureResult;
import org.robolectric.shadows.ShadowTotalCaptureResult;
import org.robolectric.util.ReflectionHelpers;

/** Actual GlassCamera/session/barrier code, fake HAL and encoder; not physical acceptance. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE, shadows = {GlassCameraVideoTest.ManagerShadow.class,
        GlassCameraWarmSessionTest.CharacteristicsShadow.class, GlassCameraWarmSessionTest.MapShadow.class,
        GlassCameraZslTest.Reader.class, GlassCameraWarmSessionTest.BuilderShadow.class,
        GlassCameraWarmSessionTest.RequestShadow.class, GlassCameraVideoTest.ActivityShadow.class})
public class GlassCameraVideoTest {
    private GlassCamera camera;
    private final CaptureVideoRecordingTest.Worker worker = new CaptureVideoRecordingTest.Worker();
    private final CaptureVideoRecordingTest.Port port = new CaptureVideoRecordingTest.Port();
    private final List<String> failures = new ArrayList<>();
    private final List<GlassCamera.Captured> originals = new ArrayList<>();
    @Before public void setup() {
        GlassCameraWarmSessionTest.ManagerShadow.devices.clear();
        GlassCameraWarmSessionTest.ManagerShadow.refuseSession = false;
        ManagerShadow.exactSupported = true; ManagerShadow.queryUnavailable = false;
        ActivityShadow.recreated = 0;
        GlassCameraWarmSessionTest.CharacteristicsShadow.fixedFocus = true;
        GlassCameraWarmSessionTest.CharacteristicsShadow.afMode = CONTROL_AF_MODE_OFF;
        GlassCameraWarmSessionTest.ReaderShadow.readers.clear();
        camera = new GlassCamera(RuntimeEnvironment.getApplication(), new Handler(Looper.getMainLooper()),
                new GlassCamera.Callback() {
                    public void onCaptured(byte[] bytes, int w, int h, long elapsed) { fail("rich callback expected"); }
                    public void onCaptured(GlassCamera.Captured captured) { originals.add(captured); }
                    public void onCaptureFailed(String reason) { failures.add(reason); }
                }, GlassCamera.Mode.VIDEO_EVALUATION, worker, null,
                CaptureVideoRecording.Options.defaults("device-test", 4, 270), () -> port);
    }
    private void idle(long ms) { shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(ms)); }
    private DocScanTestCamera device() { return GlassCameraWarmSessionTest.ManagerShadow.devices.get(0); }
    private GlassCameraZslTest.Reader reader(int format) {
        return (GlassCameraZslTest.Reader)GlassCameraWarmSessionTest.ReaderShadow.readers.stream().filter(r -> r.format == format).findFirst().orElseThrow();
    }
    private void begin() { camera.preview(); idle(0); worker.drain(); worker.drain(); idle(0); }
    private void frame() {
        long timestamp = SystemClock.elapsedRealtimeNanos();
        TotalCaptureResult result = ShadowTotalCaptureResult.newTotalCaptureResult();
        ShadowCaptureResult values = Shadow.extract(result);
        values.set(CaptureResult.SENSOR_TIMESTAMP, timestamp); values.set(CaptureResult.SENSOR_EXPOSURE_TIME, 10_000_000L);
        values.set(CaptureResult.CONTROL_AF_STATE, CONTROL_AF_STATE_INACTIVE); values.set(CaptureResult.CONTROL_AE_STATE, CONTROL_AE_STATE_CONVERGED);
        device().session.previewCallback.onCaptureCompleted(device().session, device().session.repeating, result);
        DocScanTestImage image = new DocScanTestImage(new ArrayList<>());
        image.format = ImageFormat.YUV_420_888; image.width = 32; image.height = 24;
        image.timestamp = timestamp; image.rowStride = 32; image.pixelStride = 1;
        byte[] luma = new byte[32*24]; Arrays.fill(luma, (byte)180); image.buffer = ByteBuffer.wrap(luma);
        GlassCameraZslTest.Reader reader = reader(ImageFormat.YUV_420_888); reader.image = image; reader.listener.onImageAvailable(reader.reader);
    }
    private void issue() {
        begin(); for (int i=0;i<6;i++) { idle(100); frame(); }
        camera.captureOnce(); idle(1); frame(); idle(50);
    }
    private void jpeg() {
        GlassCameraZslTest.Reader reader = reader(ImageFormat.JPEG); reader.image = new DocScanTestImage(new ArrayList<>());
        reader.listener.onImageAvailable(reader.reader); idle(0);
    }
    private void closeWorkers() throws Exception {
        long until = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(5);
        while (ReflectionHelpers.getField(camera, "videoClose") != null && !port.closed && System.nanoTime() < until) {
            idle(0); worker.drain(); Thread.sleep(2);
        }
        idle(0);
    }
    private void awaitCameraResourcesClosed() throws Exception {
        Object ending = ReflectionHelpers.getField(camera, "videoClose");
        long until = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(5);
        while (!(Boolean)ReflectionHelpers.getField(ending, "resourcesClosed") && System.nanoTime() < until) {
            idle(0); Thread.sleep(2);
        }
        idle(0);
        assertTrue("camera close did not finish", (Boolean)ReflectionHelpers.getField(ending, "resourcesClosed"));
    }
    @Test public void explicitVideoKeepsMaxNativeJpegAndWarmObservationWithOneRecorder() {
        issue();
        assertEquals(3, device().outputs.size()); assertNotNull(device().queriedConfiguration);
        assertEquals(4032, reader(ImageFormat.JPEG).width); assertEquals(3024, reader(ImageFormat.JPEG).height);
        var repeating = (GlassCameraWarmSessionTest.RequestShadow)Shadow.extract(device().session.repeating);
        assertEquals(CameraDevice.TEMPLATE_RECORD, repeating.template); assertTrue(repeating.targets.contains(port.surface));
        assertEquals(1, port.starts); assertEquals(1, device().session.captures);
        var request = (GlassCameraWarmSessionTest.RequestShadow)Shadow.extract(device().session.captured);
        assertTrue(request.targets.contains(port.surface)); assertTrue(request.targets.contains(reader(ImageFormat.JPEG).surface));
        jpeg();
        assertEquals(1, originals.size()); assertEquals("native_still", originals.get(0).provenance.sourceKind);
        assertFalse(device().closed); assertFalse(port.stopped); assertTrue(failures.isEmpty());
    }
    @Test public void observationStopWaitsForOriginalCameraCloseAndContainerFinalize() throws Exception {
        issue(); final int[] stopped = {0};
        camera.stopFuturePages(() -> stopped[0]++); idle(0); assertEquals(0, stopped[0]); assertFalse(port.stopped);
        jpeg(); assertEquals(1, originals.size()); assertEquals(0, stopped[0]);
        closeWorkers(); assertEquals(1, stopped[0]); assertTrue(port.stopped); assertTrue(port.closed);
        assertTrue(device().closed); assertTrue(failures.isEmpty());
    }
    @Test public void failedStopNeverAcknowledgesIdleOrStartsANewCapture() throws Exception {
        issue(); jpeg(); port.stopFails = true; final int[] stopped = {0};
        camera.stopFuturePages(() -> stopped[0]++); idle(0); closeWorkers();
        assertEquals(0, stopped[0]); assertTrue((Boolean)ReflectionHelpers.getField(camera, "unknown"));
        camera.captureOnce(); idle(500); assertEquals(1, device().session.captures); assertFalse(failures.isEmpty());
    }
    @Test public void zslAndVideoFlagsAreRejectedAndNativeIsStillTheDefault() {
        assertEquals(GlassCamera.Mode.NATIVE_STILL, DocScanGlassActivity.evaluationMode(new Intent()));
        assertEquals(GlassCamera.Mode.VIDEO_EVALUATION, DocScanGlassActivity.evaluationMode(new Intent().putExtra("video_evaluation", true)));
        try { DocScanGlassActivity.evaluationMode(new Intent().putExtra("video_evaluation", true).putExtra("zsl_evaluation", true)); fail("must reject"); }
        catch (IllegalArgumentException expected) { assertTrue(expected.getMessage().contains("同時")); }
        var hevc = DocScanGlassActivity.videoOptions(new Intent().putExtra("video_evaluation", true).putExtra("video_codec", "hevc")
                .putExtra("video_width", 3200).putExtra("video_height", 2400), "device", 7);
        assertEquals("video/hevc", hevc.mime()); assertEquals(3200, hevc.width); assertEquals(7, hevc.generation);
    }
    @Test public void exactSessionRefusalRetainsOriginalWithoutNativeFallback() throws Exception {
        ManagerShadow.exactSupported = false; begin(); closeWorkers();
        assertEquals(1, failures.size()); assertTrue(failures.get(0).contains("exact session unsupported"));
        assertEquals(0, device().configurations); assertFalse(port.started); assertTrue(port.source.exists());
        assertTrue((Boolean)ReflectionHelpers.getField(camera, "unknown"));
    }
    @Test public void unsupportedSessionQueryMeansUnknownForThisEvaluation() throws Exception {
        ManagerShadow.queryUnavailable = true; begin(); closeWorkers();
        assertEquals(1, failures.size()); assertTrue(failures.get(0).contains("support unknown"));
        assertEquals(0, device().configurations); assertFalse(port.started); assertTrue(port.source.exists());
    }
    @Test public void generationEndDoesNotEndTheHandlerBeforeRecorderFinalization() throws Exception {
        issue(); jpeg(); final int[] ended = {0};
        camera.close(() -> ended[0]++); idle(0); assertEquals(0, ended[0]);
        closeWorkers(); assertEquals(1, ended[0]); assertTrue(port.stopped); assertTrue(port.closed);
    }
    @Test public void generationEndWithAnUnresolvedNativeOriginalCannotReportAnOrdinaryCompleteClip() throws Exception {
        issue(); CaptureVideoRecording recording=ReflectionHelpers.getField(camera,"video");
        camera.close(); idle(0); closeWorkers();
        assertFalse("an in-flight native original still has an unresolved gap",recording.finalizedSuccessfully());
        assertTrue(recording.originalFile().exists()); assertEquals(0,originals.size());
    }
    @Test public void missingCameraCloseAcknowledgementCannotSealOrAcknowledgeIdle() throws Exception {
        issue(); jpeg(); device().suppressCloseCallback = true;
        final int[] stopped = {0}, ended = {0};
        camera.stopFuturePages(() -> stopped[0]++); camera.close(() -> ended[0]++); idle(0);
        // Resource close returned, but onClosed never came. A timeout keeps the partial original.
        for (int i=0;i<10;i++) { idle(0); worker.drain(); Thread.sleep(2); }
        assertFalse(port.stopped); assertEquals(0, stopped[0]); assertEquals(0, ended[0]);
        idle(15_000); worker.drain();
        assertEquals(0, stopped[0]); assertEquals(1, ended[0]); assertTrue(port.source.exists());
        assertFalse(((CaptureVideoRecording)ReflectionHelpers.getField(ReflectionHelpers.getField(camera, "videoClose"), "recording")).finalizedSuccessfully());
    }
    @Test public void singleTaskEvaluationRelaunchWaitsForTheOldRecorderBeforeRecreation() throws Exception {
        issue(); jpeg();
        DocScanGlassActivity activity=Robolectric.buildActivity(DocScanGlassActivity.class).get();
        ReflectionHelpers.setField(activity,"camera",camera);
        try {
            activity.onNewIntent(new Intent().putExtra("video_evaluation",true).putExtra("video_codec","hevc"));
            idle(0); assertEquals(0,ActivityShadow.recreated);
            closeWorkers(); assertTrue(port.closed); assertEquals(1,ActivityShadow.recreated);
        } finally {
            ((java.util.concurrent.ExecutorService)ReflectionHelpers.getField(activity,"stateExecutor")).shutdownNow();
            ((java.util.concurrent.ExecutorService)ReflectionHelpers.getField(activity,"answerPersistExecutor")).shutdownNow();
        }
    }
    @Test public void closeDeadlineHoldsRepeatedAndLateLifecycleCallbacksUntilRecorderFinishes() throws Exception {
        issue(); jpeg(); CaptureVideoRecording recording = ReflectionHelpers.getField(camera, "video");
        int[] ended = {0}, stopped = {0};
        try {
            camera.stopFuturePages(() -> stopped[0]++); camera.close(() -> ended[0]++); idle(0);
            awaitCameraResourcesClosed();
            idle(15_000);
            assertFalse(port.stopped); assertFalse(port.closed);
            assertEquals("deadline cannot stand in for recorder finalization", 0, ended[0]);
            assertTrue((Boolean)ReflectionHelpers.getField(camera, "unknown"));
            camera.close(() -> ended[0]++); camera.videoGeneration(5); camera.preview(); camera.captureOnce(); idle(0);
            device().state.onClosed(device()); idle(0);
            assertEquals(0, ended[0]); assertEquals(0, stopped[0]);
            assertEquals(1, GlassCameraWarmSessionTest.ManagerShadow.devices.size());
            assertEquals(1, device().session.captures); assertFalse(recording.finalizedSuccessfully());
            worker.drain();
            assertTrue(port.stopped); assertTrue(port.closed); assertEquals(1, port.stops);
            assertEquals(2, ended[0]); assertEquals(0, stopped[0]);
            assertNotNull(ReflectionHelpers.getField(camera, "videoClose"));
            assertFalse(recording.finalizedSuccessfully()); assertTrue(recording.originalFile().isFile());
            var journal = new org.json.JSONObject(new String(java.nio.file.Files.readAllBytes(recording.journalFile().toPath()),
                    java.nio.charset.StandardCharsets.UTF_8));
            assertEquals("unknown", journal.getString("state"));
            camera.close(() -> ended[0]++); idle(0); assertEquals(3, ended[0]);
            worker.drain(); idle(15_000); assertEquals(3, ended[0]); assertEquals(0, stopped[0]);
        } finally { worker.drain(); }
    }
    @Test public void singleTaskDeadlineCannotRecreateBeforeOldRecorderFinishesOrRepeatRecreation() throws Exception {
        issue(); jpeg();
        DocScanGlassActivity activity = Robolectric.buildActivity(DocScanGlassActivity.class).get();
        ReflectionHelpers.setField(activity, "camera", camera);
        try {
            Intent evaluation = new Intent().putExtra("video_evaluation", true).putExtra("video_codec", "hevc");
            activity.onNewIntent(evaluation); idle(0); awaitCameraResourcesClosed();
            idle(15_000);
            assertFalse(port.stopped); assertFalse(port.closed);
            assertEquals("deadline cannot release singleTask recreation", 0, ActivityShadow.recreated);
            activity.onNewIntent(evaluation); idle(0); device().state.onClosed(device()); idle(0);
            assertEquals(0, ActivityShadow.recreated);
            worker.drain();
            assertTrue(port.stopped); assertTrue(port.closed); assertEquals(1, port.stops);
            assertEquals(1, ActivityShadow.recreated); assertTrue((Boolean)ReflectionHelpers.getField(camera, "unknown"));
            activity.onNewIntent(evaluation); idle(0); worker.drain(); assertEquals(1, ActivityShadow.recreated);
        } finally {
            worker.drain();
            ((java.util.concurrent.ExecutorService)ReflectionHelpers.getField(activity,"stateExecutor")).shutdownNow();
            ((java.util.concurrent.ExecutorService)ReflectionHelpers.getField(activity,"answerPersistExecutor")).shutdownNow();
        }
    }
    @Test public void wronglyTypedEvaluationFlagsAndProfileValuesCannotSilentlySelectDefaults() {
        try { DocScanGlassActivity.evaluationMode(new Intent().putExtra("video_evaluation","true")); fail("reject wrong type"); }
        catch(IllegalArgumentException expected){ }
        try { DocScanGlassActivity.videoOptions(new Intent().putExtra("video_evaluation",true).putExtra("video_fps","60"),"test",1); fail("reject wrong type"); }
        catch(IllegalArgumentException expected){ }
    }
    @Implements(Activity.class) public static class ActivityShadow extends ShadowActivity {
        static int recreated;
        @Implementation protected void recreate() { recreated++; }
    }
    @Implements(CameraManager.class) public static class ManagerShadow extends GlassCameraWarmSessionTest.ManagerShadow {
        static boolean exactSupported, queryUnavailable;
        @Implementation protected void openCamera(String id, CameraDevice.StateCallback callback, Handler h) {
            super.openCamera(id, callback, h);
            DocScanTestCamera opened = devices.get(devices.size()-1);
            opened.supportsExactSession = exactSupported; opened.sessionQueryUnsupported = queryUnavailable;
        }
    }
}
