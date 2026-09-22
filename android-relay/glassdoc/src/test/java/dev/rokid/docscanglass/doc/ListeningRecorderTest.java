package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.io.File;
import java.io.RandomAccessFile;
import java.util.Arrays;
import java.util.concurrent.TimeUnit;
import dev.rokid.docscanrelay.DocScanApi;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
public class ListeningRecorderTest {
    @org.junit.Before public void recordingService() throws Exception {
        // Robolectric's AudioRecord monitor otherwise receives a null configuration list.
        Class<?> service = Class.forName("android.media.IAudioService");
        Object audio = java.lang.reflect.Proxy.newProxyInstance(service.getClassLoader(), new Class<?>[]{service},
                (proxy, method, args) -> method.getName().equals("getActiveRecordingConfigurations") ? java.util.List.of() : null);
        org.robolectric.util.ReflectionHelpers.setStaticField(
                Class.forName("android.media.AudioRecordingMonitorImpl"), "sService", audio);
    }

    @org.junit.After public void resetRecordingService() throws Exception {
        org.robolectric.shadows.ShadowAudioRecord.clearSource();
        org.robolectric.util.ReflectionHelpers.setStaticField(
                Class.forName("android.media.AudioRecordingMonitorImpl"), "sService", null);
    }

    @Test public void wavMatchesServerPcmContract() {
        byte[] header = ListeningRecorder.wavHeader(960000);
        ByteBuffer bytes = ByteBuffer.wrap(header).order(ByteOrder.LITTLE_ENDIAN);
        assertEquals("RIFF", new String(header, 0, 4, StandardCharsets.US_ASCII));
        assertEquals(960036, bytes.getInt(4));
        assertEquals(1, bytes.getShort(22));
        assertEquals(16000, bytes.getInt(24));
        assertEquals(16, bytes.getShort(34));
        assertEquals(960000, bytes.getInt(40));
    }

    @Test public void savedAudioUsesTheUploadServiceTypeInsteadOfTheMicrophone() {
        org.robolectric.android.controller.ServiceController<ListeningService> lifecycle = org.robolectric.Robolectric.buildService(ListeningService.class).create();
        ListeningService service = lifecycle.get();
        try {
            service.onStartCommand(new android.content.Intent(), 0, 1);
            assertEquals("マイク準備中", org.robolectric.Shadows.shadowOf(service).getLastForegroundNotification().extras.getCharSequence(android.app.Notification.EXTRA_TITLE));
            assertEquals(android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE, service.getForegroundServiceType());
            service.onStartCommand(new android.content.Intent().putExtra(ListeningService.RECORDING, true), 0, 2);
            assertEquals("リスニング録音中", org.robolectric.Shadows.shadowOf(service).getLastForegroundNotification().extras.getCharSequence(android.app.Notification.EXTRA_TITLE));
            service.onStartCommand(new android.content.Intent().putExtra(ListeningService.FINISHING, true), 0, 3);
            assertEquals("保存した音声を送信中", org.robolectric.Shadows.shadowOf(service).getLastForegroundNotification().extras.getCharSequence(android.app.Notification.EXTRA_TITLE));
            assertEquals(android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC, service.getForegroundServiceType());
        } finally { lifecycle.destroy(); }
    }

    @Test public void interruptedTailAndUnknownAckSurviveRestartWithoutClaimingComplete() throws Exception {
        File root = Files.createTempDirectory("listening-recovery").toFile();
        File folder = new File(root, "listening-17");
        assertTrue(folder.mkdir());
        Files.write(new File(folder, "started-epoch-ms").toPath(), "1700000000000".getBytes(StandardCharsets.UTF_8));
        byte[] first = new byte[960000];
        for (int i = 0; i < first.length; i++) first[i] = (byte) (i % 113);
        writeWav(new File(folder, "0000.wav"), first, first.length);
        byte[] tail = new byte[35201]; // One trailing byte never forms a PCM sample.
        System.arraycopy(first, first.length - 32000, tail, 0, 32000);
        Arrays.fill(tail, 32000, tail.length, (byte) 7);
        writeWav(new File(folder, "0001.wav.part"), tail, 32000); // Header before the final write.
        byte[] originalPart = Files.readAllBytes(new File(folder, "0001.wav.part").toPath());
        try (MockWebServer server = new MockWebServer()) {
            server.enqueue(new MockResponse().setBody("{}"));
            server.enqueue(new MockResponse().setResponseCode(503).setBody("{}"));
            DocScanApi api = new DocScanApi(server.url("/").toString(), "",
                    new dev.rokid.docscanrelay.ClientIdentity("test", "test", "test"));
            try (ListeningRecorder recorder = new ListeningRecorder(root, 17, api, () -> { })) {
                assertTrue(recorder.restore());
                assertThrows(java.io.IOException.class, recorder::finishAndUpload);
            }
            assertEquals("/v1/documents/17/audio-chunks", server.takeRequest().getPath());
            String unknown = server.takeRequest().getBody().readUtf8();
            assertTrue(unknown.contains("1700000029000"));
            server.enqueue(new MockResponse().setBody("{}"));
            try (ListeningRecorder recorder = new ListeningRecorder(root, 17, api, () -> { })) {
                assertTrue(recorder.restore());
                assertThrows(java.io.IOException.class, recorder::finishAndUpload);
            }
            String retried = server.takeRequest().getBody().readUtf8();
            assertTrue(retried.contains("1700000029000"));
            assertEquals("1", retried.split("name=\"sequence\"", 2)[1].split("\r\n\r\n", 2)[1].split("\r\n")[0]);
            assertNull(server.takeRequest(100, TimeUnit.MILLISECONDS)); // No acknowledged chunk or complete request.
            byte[] recovered = Files.readAllBytes(new File(folder, "0001.wav").toPath());
            assertEquals(35200, ByteBuffer.wrap(recovered).order(ByteOrder.LITTLE_ENDIAN).getInt(40));
            assertArrayEquals(Arrays.copyOf(tail, 35200), Arrays.copyOfRange(recovered, 44, recovered.length));
            assertArrayEquals(originalPart, Files.readAllBytes(new File(folder, "0001.wav.part").toPath()));
            // Already acknowledged originals are still checked, never silently trusted.
            try (RandomAccessFile corrupt = new RandomAccessFile(new File(folder, "0000.wav"), "rw")) {
                corrupt.seek(80); corrupt.write(127);
            }
            try (ListeningRecorder recorder = new ListeningRecorder(root, 17, api, () -> { })) {
                assertThrows(java.io.IOException.class, recorder::restore);
            }
        }
    }

    @Test public void stoppedRecordingRetriesCompletionAfterRestartWithoutReuploadingAcknowledgedAudio() throws Exception {
        File root = Files.createTempDirectory("listening-stopped").toFile();
        File folder = new File(root, "listening-18");
        assertTrue(folder.mkdir());
        Files.write(new File(folder, "started-epoch-ms").toPath(), "1700000000000".getBytes(StandardCharsets.UTF_8));
        writeWav(new File(folder, "0000.wav"), new byte[3200], 3200);
        java.util.Properties manifest = new java.util.Properties();
        manifest.setProperty("phase", "stopped");
        manifest.setProperty("epoch", "1700000000000");
        manifest.setProperty("chunks", "1");
        manifest.setProperty("samples", "1600");
        byte[] original = Files.readAllBytes(new File(folder, "0000.wav").toPath());
        StringBuilder hash = new StringBuilder();
        for (byte value : java.security.MessageDigest.getInstance("SHA-256").digest(original)) hash.append(String.format("%02x", value & 255));
        manifest.setProperty("sha.0", hash.toString());
        try (java.io.FileOutputStream output = new java.io.FileOutputStream(new File(folder, "recording.properties"))) {
            manifest.store(output, "stopped before network ACK");
        }
        try (MockWebServer server = new MockWebServer()) {
            server.enqueue(new MockResponse().setBody("{}"));
            server.enqueue(new MockResponse().setResponseCode(503).setBody("{}"));
            DocScanApi api = new DocScanApi(server.url("/").toString(), "",
                    new dev.rokid.docscanrelay.ClientIdentity("test", "test", "test"));
            try (ListeningRecorder recorder = new ListeningRecorder(root, 18, api, () -> { })) {
                assertTrue(recorder.restore());
                assertFalse(recorder.isInterrupted());
                assertThrows(java.io.IOException.class, recorder::finishAndUpload);
            }
            assertEquals("/v1/documents/18/audio-chunks", server.takeRequest().getPath());
            assertEquals("/v1/documents/18/audio-complete", server.takeRequest().getPath());
            server.enqueue(new MockResponse().setBody("{}"));
            try (ListeningRecorder recorder = new ListeningRecorder(root, 18, api, () -> { })) {
                assertTrue(recorder.restore());
                recorder.finishAndUpload();
            }
            okhttp3.mockwebserver.RecordedRequest completed = server.takeRequest();
            assertEquals("/v1/documents/18/audio-complete", completed.getPath());
            assertTrue(completed.getBody().readUtf8().contains("\"total_samples\":1600"));
            assertNull(server.takeRequest(100, TimeUnit.MILLISECONDS));
            assertArrayEquals(original, Files.readAllBytes(new File(folder, "0000.wav").toPath()));
        }
    }

    @Test public void localAudioWaitsForADurableDocumentBindingAndRejectsAnotherId() throws Exception {
        File root = Files.createTempDirectory("listening-before-http").toFile();
        File folder = new File(root, "listening");
        assertTrue(folder.mkdir());
        Files.write(new File(folder, "started-epoch-ms").toPath(), "1700000000000".getBytes(StandardCharsets.UTF_8));
        writeWav(new File(folder, "0000.wav"), new byte[3200], 3200);
        try (MockWebServer server = new MockWebServer()) {
            DocScanApi api = new DocScanApi(server.url("/").toString(), "",
                    new dev.rokid.docscanrelay.ClientIdentity("test", "test", "test"));
            try (ListeningRecorder recorder = new ListeningRecorder(root, 0, api, () -> { })) {
                assertTrue(recorder.restore());
                assertEquals("DocumentPending", assertThrows(java.io.IOException.class, recorder::finishAndUpload).getClass().getSimpleName());
                assertEquals(0, server.getRequestCount());
                server.enqueue(new MockResponse().setBody("{}"));
                recorder.bindDocument(17);
                assertThrows(java.io.IOException.class, recorder::finishAndUpload); // Still interrupted.
                assertEquals("/v1/documents/17/audio-chunks", server.takeRequest().getPath());
            }
            try (ListeningRecorder recorder = new ListeningRecorder(root, 18, api, () -> { })) {
                assertThrows(java.io.IOException.class, recorder::restore);
            }
            try (ListeningRecorder recorder = new ListeningRecorder(root, 17, api, () -> { })) {
                assertTrue(recorder.restore());
                assertThrows(java.io.IOException.class, recorder::finishAndUpload);
            }
            assertNull(server.takeRequest(100, TimeUnit.MILLISECONDS));
            assertTrue(new File(folder, "0000.wav").isFile());
        }
    }

    @Test public void recordingStateWaitsForSamplesAndNaturalSilenceIsStillValidAudio() throws Exception {
        File root = Files.createTempDirectory("listening-samples").toFile();
        java.util.concurrent.atomic.AtomicBoolean supply = new java.util.concurrent.atomic.AtomicBoolean();
        java.util.concurrent.atomic.AtomicBoolean blockingRead = new java.util.concurrent.atomic.AtomicBoolean();
        java.util.concurrent.atomic.AtomicBoolean failed = new java.util.concurrent.atomic.AtomicBoolean();
        java.util.concurrent.CountDownLatch read = new java.util.concurrent.CountDownLatch(1);
        java.util.concurrent.CountDownLatch started = new java.util.concurrent.CountDownLatch(1);
        java.util.concurrent.CountDownLatch stopped = new java.util.concurrent.CountDownLatch(1);
        java.util.List<Boolean> states = new java.util.concurrent.CopyOnWriteArrayList<>();
        org.robolectric.shadows.ShadowAudioRecord.setSource(new org.robolectric.shadows.ShadowAudioRecord.AudioRecordSource() {
            private int next(boolean blocking) {
                blockingRead.set(blocking); read.countDown();
                return supply.compareAndSet(true, false) ? 160 : 0;
            }
            public int readInShortArray(short[] target, int offset, int size, boolean blocking) { return next(blocking); }
            public int readInByteArray(byte[] target, int offset, int size, boolean blocking) { return next(blocking) * 2; }
        });
        ListeningRecorder recorder = new ListeningRecorder(root, 0, null, () -> failed.set(true));
        try {
            recorder.start(active -> { states.add(active); if (active) started.countDown(); else stopped.countDown(); });
            assertTrue(read.await(1, TimeUnit.SECONDS));
            assertTrue(states.isEmpty());
            supply.set(true); // All zero PCM represents natural silence, not a stalled read.
            assertTrue(started.await(3, TimeUnit.SECONDS));
            assertFalse(blockingRead.get());
            recorder.requestStop();
            assertTrue(stopped.await(1, TimeUnit.SECONDS));
            assertEquals(java.util.List.of(true, false), states);
            assertFalse(failed.get());
            java.util.Properties saved = new java.util.Properties();
            try (java.io.FileInputStream input = new java.io.FileInputStream(new File(root, "listening/recording.properties"))) { saved.load(input); }
            assertEquals("stopped", saved.getProperty("phase"));
            byte[] wav = Files.readAllBytes(new File(root, "listening/0000.wav").toPath());
            assertEquals(320, ByteBuffer.wrap(wav).order(ByteOrder.LITTLE_ENDIAN).getInt(40));
        } finally { recorder.close(); }
    }

    @Test public void missingSamplesAndOsSilencingStopRecordingWithoutCompletingIt() throws Exception {
        for (boolean silenced : new boolean[]{false, true}) {
            File root = Files.createTempDirectory("listening-input-loss").toFile();
            java.util.concurrent.atomic.AtomicBoolean first = new java.util.concurrent.atomic.AtomicBoolean(true);
            java.util.concurrent.CountDownLatch started = new java.util.concurrent.CountDownLatch(1);
            java.util.concurrent.CountDownLatch failed = new java.util.concurrent.CountDownLatch(1);
            java.util.concurrent.CountDownLatch stopped = new java.util.concurrent.CountDownLatch(1);
            org.robolectric.shadows.ShadowAudioRecord.setSource(new org.robolectric.shadows.ShadowAudioRecord.AudioRecordSource() {
                public int readInShortArray(short[] target, int offset, int size, boolean blocking) {
                    return first.getAndSet(false) ? Math.min(160, size) : 0;
                }
            });
            try (ListeningRecorder recorder = new ListeningRecorder(root, 0, null, failed::countDown)) {
                recorder.start(active -> { if (active) started.countDown(); else stopped.countDown(); });
                assertTrue(started.await(2, TimeUnit.SECONDS));
                if (silenced) {
                    android.media.AudioRecord microphone = org.robolectric.util.ReflectionHelpers.getField(recorder, "microphone");
                    android.media.AudioManager manager = org.robolectric.RuntimeEnvironment.getApplication().getSystemService(android.media.AudioManager.class);
                    android.media.AudioRecordingConfiguration config = org.robolectric.Shadows.shadowOf(manager)
                            .createActiveRecordingConfiguration(microphone.getAudioSessionId(), android.media.MediaRecorder.AudioSource.MIC, "test");
                    org.robolectric.util.ReflectionHelpers.setField(config, "mClientSilenced", true);
                    android.media.AudioManager.AudioRecordingCallback callback = org.robolectric.util.ReflectionHelpers.getField(recorder, "audioCallback");
                    callback.onRecordingConfigChanged(java.util.List.of(config));
                } else org.robolectric.shadows.ShadowSystemClock.advanceBy(java.time.Duration.ofSeconds(3));
                assertTrue(failed.await(2, TimeUnit.SECONDS));
                assertTrue(stopped.await(2, TimeUnit.SECONDS));
                assertTrue(recorder.isInterrupted());
                assertThrows(java.io.IOException.class, recorder::finishAndUpload);
            }
            try (ListeningRecorder recovered = new ListeningRecorder(root, 0, null, () -> { })) {
                assertTrue(recovered.restore());
                assertTrue(recovered.isInterrupted());
                byte[] wav = Files.readAllBytes(new File(root, "listening/0000.wav").toPath());
                assertEquals(320, ByteBuffer.wrap(wav).order(ByteOrder.LITTLE_ENDIAN).getInt(40));
            }
        }
    }

    private static void writeWav(File file, byte[] pcm, int headerBytes) throws Exception {
        try (RandomAccessFile output = new RandomAccessFile(file, "rw")) {
            output.write(ListeningRecorder.wavHeader(headerBytes));
            output.write(pcm);
        }
    }
}
