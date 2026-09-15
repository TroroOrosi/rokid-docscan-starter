package dev.rokid.docscanglass.doc;

import android.Manifest;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import androidx.annotation.RequiresPermission;
import dev.rokid.docscanrelay.DocScanApi;
import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

/** PCM originals are written before upload; one upload queue runs alongside recording/capture. */
final class ListeningRecorder implements AutoCloseable {
    private static final int RATE = 16000, CHUNK = RATE * 30, OVERLAP = RATE;
    private final DocScanApi api;
    private final long documentId;
    private final File directory;
    private final Runnable onFailure;
    private final ExecutorService uploads = Executors.newSingleThreadExecutor();
    private AudioRecord microphone;
    private Thread recording;
    private volatile boolean running;
    private volatile String recordingError;
    private volatile Exception uploadError;
    private int chunks;
    private long samples;
    private long epoch;

    ListeningRecorder(File root, long documentId, DocScanApi api, Runnable onFailure) {
        this.api = api;
        this.documentId = documentId;
        this.onFailure = onFailure;
        directory = new File(root, "listening-" + documentId);
    }

    @RequiresPermission(Manifest.permission.RECORD_AUDIO)
    void start() throws IOException {
        if (directory.exists()) throw new IOException("前回の録音を保全中です。新しい読取で録音してください");
        if (!directory.mkdirs()) throw new IOException("録音保存先を作れません");
        epoch = System.currentTimeMillis();
        Files.write(new File(directory, "started-epoch-ms").toPath(), Long.toString(epoch).getBytes(StandardCharsets.UTF_8));
        int minimum = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        if (minimum <= 0) throw new IOException("16 kHz録音に対応していません");
        microphone = new AudioRecord(MediaRecorder.AudioSource.MIC, RATE, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT, Math.max(minimum, RATE * 2));
        if (microphone.getState() != AudioRecord.STATE_INITIALIZED) {
            microphone.release(); microphone = null;
            throw new IOException("マイクを開始できません");
        }
        try {
            microphone.startRecording();
            if (microphone.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING) throw new IOException("マイクが録音状態になりません");
        } catch (RuntimeException | IOException error) {
            microphone.release(); microphone = null;
            throw new IOException("マイクを開始できません", error);
        }
        running = true;
        recording = new Thread(this::record, "listening-pcm");
        recording.start();
    }

    private void record() {
        byte[] buffer = new byte[3200], tail = new byte[OVERLAP * 2];
        int tailLength = 0;
        try {
            while (running) {
                File file = new File(directory, String.format(java.util.Locale.ROOT, "%04d.wav", chunks));
                int fresh = 0, prefix = chunks == 0 ? 0 : tailLength;
                try (RandomAccessFile output = new RandomAccessFile(file, "rw")) {
                    output.write(wavHeader(prefix));
                    if (prefix > 0) output.write(tail, 0, prefix);
                    while (running && fresh < CHUNK * 2) {
                        int count = microphone.read(buffer, 0, Math.min(buffer.length, CHUNK * 2 - fresh));
                        if (count < 0 || count % 2 != 0) throw new IOException("マイク入力が中断されました");
                        if (count == 0) continue;
                        output.seek(44L + prefix + fresh);
                        output.write(buffer, 0, count);
                        fresh += count;
                        samples += count / 2;
                        output.seek(0); output.write(wavHeader(prefix + fresh));
                    }
                    output.getFD().sync();
                    int bytes = prefix + fresh;
                    tailLength = Math.min(tail.length, bytes);
                    output.seek(44L + bytes - tailLength);
                    output.readFully(tail, 0, tailLength);
                }
                if (fresh == 0) { if (!file.delete()) throw new IOException("空録音を整理できません"); break; }
                final int sequence = chunks++;
                final long start = Math.max(0, (long)sequence * CHUNK - OVERLAP);
                uploads.submit(() -> upload(file, sequence, start));
                if (chunks >= 600) throw new IOException("録音保存上限に達しました。原音は保存済みです");
            }
        } catch (Exception error) {
            recordingError = "録音が中断されました。原音を保全しています";
            onFailure.run();
        } finally {
            running = false;
            if (microphone != null) {
                try { microphone.stop(); } catch (IllegalStateException ignored) { }
                finally { microphone.release(); microphone = null; }
            }
        }
    }

    private void upload(File file, int sequence, long start) {
        try { api.uploadAudioChunk(documentId, sequence, start, epoch + start / 16, file); }
        catch (Exception error) { uploadError = error; }
    }

    /** Off UI thread. A later call retries stored originals, with stable sequence identities. */
    void finishAndUpload() throws Exception {
        running = false;
        if (recording != null) recording.join();
        Future<?> drained = uploads.submit(() -> { });
        drained.get();
        if (recordingError != null) throw new IOException(recordingError);
        if (chunks == 0) throw new IOException("録音がありません");
        if (uploadError != null) {
            uploadError = null;
            for (int i = 0; i < chunks; i++) upload(new File(directory,
                    String.format(java.util.Locale.ROOT, "%04d.wav", i)), i, Math.max(0, (long)i * CHUNK - OVERLAP));
            if (uploadError != null) throw new IOException("文字起こしが未完了です。原音は保存済みです", uploadError);
        }
        api.completeAudio(documentId, chunks, samples);
        Files.write(new File(directory, "complete").toPath(), Long.toString(samples).getBytes(StandardCharsets.UTF_8));
    }

    static byte[] wavHeader(int bytes) {
        return ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
                .put(new byte[]{'R','I','F','F'}).putInt(36 + bytes).put(new byte[]{'W','A','V','E','f','m','t',' '})
                .putInt(16).putShort((short)1).putShort((short)1).putInt(RATE).putInt(RATE*2)
                .putShort((short)2).putShort((short)16).put(new byte[]{'d','a','t','a'}).putInt(bytes).array();
    }

    @Override public void close() { running = false; uploads.shutdown(); }
}
