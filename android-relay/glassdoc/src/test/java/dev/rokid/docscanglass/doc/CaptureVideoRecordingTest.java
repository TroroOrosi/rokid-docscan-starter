package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import static org.robolectric.Shadows.shadowOf;

import android.hardware.camera2.CameraCharacteristics;
import android.os.Handler;
import android.os.Looper;
import android.util.Size;
import android.view.Surface;
import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Executor;
import java.util.function.Consumer;
import org.json.JSONObject;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;
import org.robolectric.shadow.api.Shadow;

/** Recorder/container boundaries are fakes; no physical recording is claimed. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
public class CaptureVideoRecordingTest {
    static class Worker implements Executor {
        final ArrayDeque<Runnable> tasks = new ArrayDeque<>();
        public void execute(Runnable task) { tasks.add(task); }
        void drain() { while (!tasks.isEmpty()) tasks.remove().run(); shadowOf(Looper.getMainLooper()).idle(); }
    }
    static class Port implements CaptureVideoRecording.Port {
        File source;
        boolean started, stopped, closed, stopFails, closeFails, prepareFails;
        int starts, stops;
        Consumer<String> fatal;
        final Surface surface = Shadow.newInstanceOf(Surface.class);
        public String prepare(File file, CameraCharacteristics c, Size jpeg,
                CaptureVideoRecording.Options options, Consumer<String> fatal) throws IOException {
            this.source = file; this.fatal = fatal;
            Files.write(file.toPath(), new byte[]{0,1,2,3,4,5});
            if (prepareFails) throw new CaptureVideoRecording.UnsupportedProfile("explicit_profile_unsupported");
            return "fake-advertised-encoder";
        }
        public Surface surface() { return surface; }
        public void start() { started = true; starts++; }
        public void stop() { stops++; if (stopFails) throw new IllegalStateException("fake stop"); stopped = true; }
        public void close() { closed = true; if (closeFails) throw new IllegalStateException("fake release"); }
        public CaptureVideoRecording.FileInfo inspect(File file) {
            return new CaptureVideoRecording.FileInfo("video/avc", 4032, 3024, 0, 1, 0);
        }
    }
    private Worker worker;
    private Port port;
    private CaptureVideoRecording video;
    private File root;
    private final List<String> failures = new ArrayList<>();
    @Before public void setup() throws Exception {
        root = Files.createTempDirectory("video-record-test").toFile();
        worker = new Worker(); port = new Port();
        video = new CaptureVideoRecording(root, new Handler(Looper.getMainLooper()),
                CaptureVideoRecording.Options.defaults("device-test", 7, 270), worker, () -> port);
    }
    private void prepare() { video.prepare(null, new Size(4032,3024), () -> {}, failures::add); worker.drain(); }
    private void start() { prepare(); video.start(() -> {}, failures::add); worker.drain(); }
    private JSONObject journal() throws Exception { return new JSONObject(new String(Files.readAllBytes(video.journalFile().toPath()), java.nio.charset.StandardCharsets.UTF_8)); }
    @Test public void rawMovieAndUnknownClockJournalAreSealedOnlyAfterStopReleaseAndInspection() throws Exception {
        start();
        video.scene(1, 100, 10); video.frame(100, 1); video.frame(140, 2);
        video.stillRequested(1); video.stillDelivered(1, 140, 4032, 3024, "abc");
        List<Boolean> barrier = new ArrayList<>();
        video.requestClose("capture_end"); video.finish(true, "capture_end", barrier::add);
        assertFalse(port.stopped); assertTrue(barrier.isEmpty());
        worker.drain();
        assertEquals(List.of(true), barrier); assertTrue(port.stopped); assertTrue(port.closed);
        assertEquals("complete", journal().getString("state"));
        assertFalse(journal().getBoolean("all_pages_or_characters_verified"));
        assertEquals("unknown_requires_decoded_pts", journal().getString("sensor_to_video_pts"));
        assertEquals("video/avc", journal().getJSONObject("actual_file").getString("mime"));
        assertEquals(6, journal().getLong("bytes"));
        assertEquals("17e88db187afd62c16e5debf3e6527cd006bc012bc90b51a810cd80c2d511f43", journal().getString("sha256"));
        assertArrayEquals(new byte[]{0,1,2,3,4,5}, Files.readAllBytes(video.originalFile().toPath()));
        assertEquals(1, port.starts); assertEquals(1, port.stops);
    }
    @Test public void stopFailureRetainsOriginalAndCannotAcknowledgeACompleteBarrier() throws Exception {
        start(); port.stopFails = true; List<Boolean> barrier = new ArrayList<>();
        video.requestClose("capture_end"); video.finish(true, "capture_end", barrier::add); worker.drain();
        assertEquals(List.of(false), barrier); assertTrue(port.closed);
        assertEquals("unknown", journal().getString("state")); assertTrue(video.originalFile().exists());
        assertFalse(video.finalizedSuccessfully());
    }
    @Test public void closeDuringPrepareNeverStartsOrPublishesALateSurface() throws Exception {
        final int[] prepared = {0};
        video.prepare(null, new Size(4032,3024), () -> prepared[0]++, failures::add);
        video.requestClose("generation_end"); List<Boolean> barrier = new ArrayList<>();
        video.finish(false, "generation_end", barrier::add); worker.drain();
        assertEquals(0, prepared[0]); assertFalse(port.started); assertTrue(port.closed);
        assertEquals(List.of(false), barrier); assertEquals("unknown", journal().getString("state"));
    }
    @Test public void duplicateFinishIsOneStopAndAllCallersWaitForTheSameResult() throws Exception {
        start(); List<Boolean> first = new ArrayList<>(), second = new ArrayList<>();
        video.finish(true, "capture_end", first::add); video.finish(true, "capture_end", second::add);
        worker.drain(); assertEquals(1, port.stops); assertEquals(List.of(true), first); assertEquals(first, second);
    }
    @Test public void unsupportedProfileHasItsOwnJournalAndNeverFallsBack() throws Exception {
        port.prepareFails = true; prepare();
        assertEquals(List.of("video evaluation unsupported: explicit_profile_unsupported"), failures);
        List<Boolean> barrier = new ArrayList<>(); video.finish(false, "unsupported", barrier::add); worker.drain();
        assertEquals("unsupported", journal().getString("state")); assertFalse(port.started);
        assertTrue(video.originalFile().exists()); assertEquals(List.of(false), barrier);
    }
    @Test public void anomalousEndCanKeepAValidContainerButCannotBecomeComplete() throws Exception {
        start(); video.gap("preview_failed"); List<Boolean> barrier = new ArrayList<>();
        video.finish(false, "preview_failed", barrier::add); worker.drain();
        assertTrue(port.stopped); assertEquals(List.of(false), barrier);
        assertEquals("unknown", journal().getString("state")); assertTrue(video.originalFile().isFile());
    }
    @Test public void releaseFailureCannotSealTheRawMovie() throws Exception {
        port.closeFails = true; start(); List<Boolean> barrier = new ArrayList<>();
        video.finish(true, "end", barrier::add); worker.drain();
        assertEquals(List.of(false), barrier); assertEquals("unknown",journal().getString("state")); assertTrue(video.originalFile().exists());
    }
    @Test public void actualDimensionsAndCodecAreComparedToTheExplicitRequest() throws Exception {
        port = new Port() { @Override public CaptureVideoRecording.FileInfo inspect(File file) {
            return new CaptureVideoRecording.FileInfo("video/hevc", 3840, 2160, 0, 1, 0);
        }};
        video = new CaptureVideoRecording(root,new Handler(Looper.getMainLooper()),CaptureVideoRecording.Options.defaults("test",1,270),worker,()->port);
        start(); List<Boolean> barrier = new ArrayList<>(); video.finish(true,"end",barrier::add); worker.drain();
        assertEquals(List.of(false),barrier); assertEquals("unknown",journal().getString("state")); assertTrue(video.originalFile().exists());
    }
    @Test public void recorderErrorCannotBeForgottenByAnOrdinaryEnd() throws Exception {
        start(); port.fatal.accept("recorder_error_test"); worker.drain();
        List<Boolean> barrier=new ArrayList<>(); video.finish(true,"end",barrier::add); worker.drain();
        assertEquals(List.of(false),barrier); assertFalse(failures.isEmpty()); assertEquals("unknown",journal().getString("state"));
    }
    @Test public void receiptFailureKeepsOriginalAndDoesNotAcknowledgeCompletion() throws Exception {
        start(); assertTrue(new File(video.journalFile().getParentFile(),"journal.json.partial").mkdir());
        List<Boolean> barrier=new ArrayList<>(); video.finish(true,"end",barrier::add); worker.drain();
        assertEquals(List.of(false),barrier); assertNotEquals("complete",journal().getString("state")); assertTrue(video.originalFile().exists());
    }
    @Test public void eventBudgetIsAHoldAndNotAClaimThatTheRemainingScenesWereCaptured() throws Exception {
        start(); for(int i=0;i<600;i++)video.scene(i,i+1,i);
        List<Boolean> barrier=new ArrayList<>(); video.finish(true,"end",barrier::add); worker.drain();
        assertEquals(List.of(false),barrier); assertTrue(journal().getBoolean("event_budget_exceeded"));
        assertEquals("unknown",journal().getString("state")); assertTrue(video.originalFile().exists());
    }
    @Test public void unexpectedAudioOrRotationIsNeverAcceptedAsTheRequestedSilentRawMovie() throws Exception {
        for(int invalid=0;invalid<2;invalid++) {
            final int value=invalid;
            port=new Port(){ @Override public CaptureVideoRecording.FileInfo inspect(File file) {
                return new CaptureVideoRecording.FileInfo("video/avc",4032,3024,value==0?90:0,1,value==1?1:0);
            }};
            video=new CaptureVideoRecording(root,new Handler(Looper.getMainLooper()),CaptureVideoRecording.Options.defaults("test",1,270),worker,()->port);
            start(); List<Boolean> barrier=new ArrayList<>(); video.finish(true,"end",barrier::add); worker.drain();
            assertEquals(List.of(false),barrier); assertEquals("unknown",journal().getString("state"));
        }
    }
    @Test public void blockedNativeStopLeavesTheHandlerResponsiveAndLateSuccessCannotOverrideAnAbort() throws Exception {
        var executor=java.util.concurrent.Executors.newSingleThreadExecutor();
        var entered=new java.util.concurrent.CountDownLatch(1); var gate=new java.util.concurrent.CountDownLatch(1);
        port=new Port() { @Override public void stop() {
            entered.countDown(); try { if(!gate.await(5,java.util.concurrent.TimeUnit.SECONDS))throw new IllegalStateException("test deadline"); }
            catch(InterruptedException e){ throw new IllegalStateException(e); } super.stop();
        }};
        video=new CaptureVideoRecording(root,new Handler(Looper.getMainLooper()),CaptureVideoRecording.Options.defaults("test",1,270),executor,()->port);
        try {
            final boolean[] ready={false}; video.prepare(null,new Size(4032,3024),()->ready[0]=true,failures::add); waitFor(()->ready[0]);
            ready[0]=false; video.start(()->ready[0]=true,failures::add); waitFor(()->ready[0]);
            List<Boolean> barrier=new ArrayList<>(); video.finish(true,"end",barrier::add);
            assertTrue(entered.await(5,java.util.concurrent.TimeUnit.SECONDS)); assertTrue(barrier.isEmpty());
            final boolean[] responsive={false}; new Handler(Looper.getMainLooper()).post(()->responsive[0]=true);
            shadowOf(Looper.getMainLooper()).idle(); assertTrue(responsive[0]);
            video.abort("watchdog_test",failures::add); gate.countDown(); waitFor(()->!barrier.isEmpty());
            assertEquals(List.of(false),barrier); assertEquals("unknown",journal().getString("state")); assertTrue(video.originalFile().exists());
        } finally { gate.countDown(); executor.shutdownNow(); }
    }
    private static void waitFor(java.util.function.BooleanSupplier condition)throws Exception {
        long deadline=System.nanoTime()+java.util.concurrent.TimeUnit.SECONDS.toNanos(5);
        while(!condition.getAsBoolean()&&System.nanoTime()<deadline){ shadowOf(Looper.getMainLooper()).idle(); Thread.sleep(2); }
        assertTrue("asynchronous boundary did not complete",condition.getAsBoolean());
    }
}
