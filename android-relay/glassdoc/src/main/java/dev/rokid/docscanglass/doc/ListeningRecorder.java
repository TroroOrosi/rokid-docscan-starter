package dev.rokid.docscanglass.doc;

import android.Manifest;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import androidx.annotation.RequiresPermission;
import dev.rokid.docscanrelay.DocScanApi;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Arrays;
import java.util.Properties;
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
    private Properties saved = new Properties();

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
        try (FileOutputStream output = new FileOutputStream(new File(directory, "started-epoch-ms"))) {
            output.write(Long.toString(epoch).getBytes(StandardCharsets.UTF_8));
            output.getFD().sync();
        }
        save("phase", "recording");
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

    /** Explicit resume recovers stored samples; it never starts another microphone session. */
    synchronized boolean restore() throws IOException {
        if (!directory.exists()) return false;
        if (recording != null) throw new IOException("録音中は復元できません");
        try {
            epoch = Long.parseLong(new String(Files.readAllBytes(new File(directory, "started-epoch-ms").toPath()), StandardCharsets.UTF_8));
            if (epoch <= 0) throw new NumberFormatException();
        } catch (NumberFormatException error) { throw new IOException("録音開始時刻が不正です", error); }
        File manifest = new File(directory, "recording.properties");
        if (manifest.exists()) {
            if (manifest.length() > 128 * 1024) throw new IOException("録音記録が不正です");
            try (FileInputStream input = new FileInputStream(manifest)) { saved.load(input); }
        }
        String phase = saved.getProperty("phase", "interrupted");
        if (!Arrays.asList("recording", "interrupted", "stopped", "complete").contains(phase)) throw new IOException("録音状態が不正です");
        if (saved.containsKey("epoch") && !saved.getProperty("epoch").equals(Long.toString(epoch))) throw new IOException("録音時計が一致しません");
        boolean interrupted = phase.equals("recording") || phase.equals("interrupted");
        File[] files = directory.listFiles((dir, name) -> name.matches("[0-9]{4}\\.wav(\\.part)?"));
        if (files == null) throw new IOException("原音を確認できません");
        Arrays.sort(files, java.util.Comparator.comparing(File::getName));
        chunks = 0; samples = 0;
        int previousBytes = CHUNK * 2;
        for (File file : files) {
            int sequence = Integer.parseInt(file.getName().substring(0, 4));
            if (sequence >= 600) throw new IOException("録音チャンク番号が不正です");
            boolean partial = file.getName().endsWith(".part");
            if (partial && sequence < chunks) continue; // Original of an already recovered tail stays untouched.
            if (sequence != chunks || (chunks > 0 && previousBytes != (CHUNK + (chunks > 1 ? OVERLAP : 0)) * 2)) {
                throw new IOException("録音に欠番・短い中間区間があります");
            }
            byte[] raw = readBounded(file);
            int bytes = raw.length < 44 ? 0 : (raw.length - 44) / 2 * 2;
            int prefix = sequence == 0 ? 0 : OVERLAP * 2;
            if (partial) {
                if (!interrupted) throw new IOException("終了した録音に未確定区間があります");
                if (bytes <= prefix) continue; // Keep a header-only or overlap-only tail as evidence.
                byte[] header = wavHeader(bytes);
                // Only the length words can lag a PCM write. Do not reinterpret another audio format.
                for (int i = 0; i < 44; i++) {
                    if ((i < 4 || (i >= 8 && i < 40)) && raw[i] != header[i]) throw new IOException("未確定WAV形式が不正です");
                }
                File repaired = new File(directory, "recovered.tmp");
                try (FileOutputStream output = new FileOutputStream(repaired)) {
                    output.write(header); output.write(raw, 44, bytes); output.getFD().sync();
                }
                file = chunk(sequence);
                move(repaired, file);
                raw = readBounded(file);
            }
            if (bytes <= prefix || bytes > (CHUNK * 2 + prefix) || raw.length != bytes + 44
                    || !Arrays.equals(Arrays.copyOf(raw, 44), wavHeader(bytes))) throw new IOException("保存WAVが不正です");
            String hash = digest(raw);
            if (saved.containsKey("sha." + sequence) && !hash.equals(saved.getProperty("sha." + sequence))) throw new IOException("保存原音の破損を検出しました");
            saved.setProperty("sha." + sequence, hash);
            samples += (bytes - prefix) / 2;
            previousBytes = bytes;
            chunks++;
        }
        for (String name : saved.stringPropertyNames()) {
            if ((name.startsWith("sha.") || name.startsWith("ack."))
                    && !name.matches("(?:sha|ack)\\.(?:0|[1-9][0-9]{0,2})")) throw new IOException("録音参照が不正です");
            if (name.startsWith("sha.") && Integer.parseInt(name.substring(4)) >= chunks) throw new IOException("保存原音が欠落しています");
            if (name.startsWith("ack.") && !saved.getProperty(name).equals(saved.getProperty("sha." + name.substring(4)))) throw new IOException("録音ACKが一致しません");
        }
        if (!interrupted && (!Long.toString(samples).equals(saved.getProperty("samples"))
                || !Integer.toString(chunks).equals(saved.getProperty("chunks")))) throw new IOException("録音終了位置が一致しません");
        if (interrupted) recordingError = "録音が途中で中断されています。回収した原音は保存済みです";
        save("phase", interrupted ? "interrupted" : phase);
        return true;
    }

    boolean isInterrupted() { return recordingError != null; }

    private void record() {
        byte[] buffer = new byte[3200], tail = new byte[OVERLAP * 2];
        int tailLength = 0;
        try {
            while (running) {
                File file = chunk(chunks);
                File partial = new File(directory, file.getName() + ".part");
                int fresh = 0, prefix = chunks == 0 ? 0 : tailLength;
                try (RandomAccessFile output = new RandomAccessFile(partial, "rw")) {
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
                        // ponytail: sync each second of PCM; calibrate the interval with concurrent camera load.
                        if (fresh / (RATE * 2) != (fresh - count) / (RATE * 2)) output.getFD().sync();
                    }
                    output.getFD().sync();
                    int bytes = prefix + fresh;
                    tailLength = Math.min(tail.length, bytes);
                    output.seek(44L + bytes - tailLength);
                    output.readFully(tail, 0, tailLength);
                }
                if (fresh == 0) { if (!partial.delete()) throw new IOException("空録音を整理できません"); break; }
                move(partial, file);
                final int sequence = chunks++;
                save("sha." + sequence, digest(readBounded(file)));
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
        try {
            String hash = digest(readBounded(file));
            synchronized (this) {
                if (!hash.equals(saved.getProperty("sha." + sequence))) throw new IOException("保存原音の破損を検出しました");
                if (hash.equals(saved.getProperty("ack." + sequence))) return;
            }
            api.uploadAudioChunk(documentId, sequence, start, epoch + start / 16, file);
            save("ack." + sequence, hash);
        }
        catch (Exception error) { uploadError = error; }
    }

    /** Off UI thread. A later call retries stored originals, with stable sequence identities. */
    void finishAndUpload() throws Exception {
        running = false;
        if (recording != null) recording.join();
        if (recordingError == null && recording != null) save("phase", "stopped");
        Future<?> drained = uploads.submit(() -> { });
        drained.get();
        if (chunks == 0) throw new IOException("録音がありません");
        uploadError = null;
        for (int i = 0; i < chunks; i++) {
            upload(chunk(i), i, Math.max(0, (long)i * CHUNK - OVERLAP));
            if (uploadError != null) throw new IOException("文字起こしが未完了です。原音は保存済みです", uploadError);
        }
        if (recordingError != null) throw new IOException(recordingError);
        api.completeAudio(documentId, chunks, samples);
        save("phase", "complete");
    }

    private File chunk(int sequence) { return new File(directory, String.format(java.util.Locale.ROOT, "%04d.wav", sequence)); }

    private synchronized void save(String name, String value) throws IOException {
        Properties next = new Properties(); next.putAll(saved); next.setProperty(name, value);
        next.setProperty("epoch", Long.toString(epoch));
        if (name.equals("phase") && (value.equals("stopped") || value.equals("complete"))) {
            next.setProperty("chunks", Integer.toString(chunks)); next.setProperty("samples", Long.toString(samples));
        }
        File pending = new File(directory, "recording.properties.tmp");
        try (FileOutputStream output = new FileOutputStream(pending)) { next.store(output, "DocScan recording"); output.getFD().sync(); }
        move(pending, new File(directory, "recording.properties"));
        saved = next;
    }

    private static void move(File source, File target) throws IOException {
        Files.move(source.toPath(), target.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
    }

    private static byte[] readBounded(File file) throws IOException {
        if (file.length() > (CHUNK + OVERLAP) * 2L + 45) throw new IOException("保存原音が大きすぎます");
        return Files.readAllBytes(file.toPath());
    }

    private static String digest(byte[] bytes) {
        try {
            StringBuilder result = new StringBuilder(64);
            for (byte value : MessageDigest.getInstance("SHA-256").digest(bytes)) result.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
            return result.toString();
        } catch (NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
    }

    static byte[] wavHeader(int bytes) {
        return ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
                .put(new byte[]{'R','I','F','F'}).putInt(36 + bytes).put(new byte[]{'W','A','V','E','f','m','t',' '})
                .putInt(16).putShort((short)1).putShort((short)1).putInt(RATE).putInt(RATE*2)
                .putShort((short)2).putShort((short)16).put(new byte[]{'d','a','t','a'}).putInt(bytes).array();
    }

    @Override public void close() { running = false; uploads.shutdown(); }
}
