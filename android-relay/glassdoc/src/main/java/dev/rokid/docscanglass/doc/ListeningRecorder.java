package dev.rokid.docscanglass.doc;

import android.Manifest;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.AudioManager;
import android.media.AudioRecordingConfiguration;
import android.media.MediaRecorder;
import android.os.Build;
import android.os.SystemClock;
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
    static final class DocumentPending extends IOException {
        DocumentPending() { super("接続を待っています。録音は保存済みです"); }
    }
    private static final int RATE = 16000, CHUNK = RATE * 30, OVERLAP = RATE;
    private static final long INPUT_STALL_MILLIS = 2000;
    private final DocScanApi api;
    private volatile long documentId;
    private final File directory;
    private final Runnable onFailure;
    private final ExecutorService uploads = Executors.newSingleThreadExecutor();
    private AudioRecord microphone;
    private Thread recording;
    private volatile boolean running;
    private volatile boolean closed;
    private boolean recordingStopped;
    private java.util.function.Consumer<Boolean> recordingState;
    private AudioManager.AudioRecordingCallback audioCallback;
    private int inputDeviceId;
    private volatile String recordingError;
    private volatile Exception uploadError;
    private int chunks;
    private long samples;
    private long epoch;
    private Properties saved = new Properties();

    ListeningRecorder(File root, long documentId, DocScanApi api, Runnable onFailure) throws IOException {
        this.api = api;
        this.documentId = documentId;
        this.onFailure = onFailure;
        File previous = new File(root, "listening-" + documentId);
        if (previous.exists() && new File(root, "listening").exists()) throw new IOException("録音記録が重複しています。両方の原音を保持しています");
        directory = previous.exists() ? previous : new File(root, "listening");
    }

    void bindDocument(long id) throws IOException {
        synchronized (this) {
            if (closed || id <= 0 || (documentId > 0 && documentId != id)) throw new IOException("録音の送信先文書が一致しません");
            save("document", Long.toString(id));
            documentId = id;
        }
        uploads.submit(() -> {
            for (int i = 0; i < 600; i++) {
                synchronized (this) { if (!saved.containsKey("sha." + i)) break; }
                upload(chunk(i), i, Math.max(0, (long)i * CHUNK - OVERLAP));
            }
        });
    }

    @RequiresPermission(Manifest.permission.RECORD_AUDIO)
    void start(java.util.function.Consumer<Boolean> state) throws IOException {
        recordingState = java.util.Objects.requireNonNull(state);
        if (closed) throw new IOException("終了した録音です");
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
            if (Build.VERSION.SDK_INT >= 29) {
                int audioSession = microphone.getAudioSessionId();
                audioCallback = new AudioManager.AudioRecordingCallback() {
                    @Override public void onRecordingConfigChanged(java.util.List<AudioRecordingConfiguration> configurations) {
                        for (AudioRecordingConfiguration config : configurations) {
                            if (config.getClientAudioSessionId() == audioSession) inspectInput(config);
                        }
                    }
                };
                microphone.registerAudioRecordingCallback(Runnable::run, audioCallback);
            }
            microphone.startRecording();
            if (microphone.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING) throw new IOException("マイクが録音状態になりません");
        } catch (RuntimeException | IOException error) {
            releaseMicrophone();
            throw new IOException("マイクを開始できません", error);
        }
        running = true;
        recording = new Thread(this::record, "listening-pcm");
        recording.start();
    }

    private synchronized void inspectInput(AudioRecordingConfiguration config) {
        if (!running || config == null || Build.VERSION.SDK_INT < 29) return;
        int device = config.getAudioDevice() == null ? 0 : config.getAudioDevice().getId();
        if (config.isClientSilenced() || (inputDeviceId != 0 && device != 0 && inputDeviceId != device)) {
            recordingError = "OSの無音化またはマイク経路変更を検出しました。原音は保存済みです";
            running = false;
            onFailure.run();
        }
        if (device != 0) inputDeviceId = device;
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
        String bound = saved.getProperty("document", Long.toString(documentId));
        if (!bound.equals("0") && !bound.equals(Long.toString(documentId))) throw new IOException("録音の送信先文書が一致しません");
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
        short[] pcm = new short[buffer.length / 2];
        ByteBuffer encoded = ByteBuffer.wrap(buffer).order(ByteOrder.LITTLE_ENDIAN);
        boolean receivedSamples = false;
        long lastInput = SystemClock.elapsedRealtime();
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
                        int requested = Math.min(pcm.length, CHUNK - fresh / 2);
                        int read = microphone.read(pcm, 0, requested, AudioRecord.READ_NON_BLOCKING);
                        if (!running) break;
                        if (read < 0 || read > requested || microphone.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING) {
                            throw new IOException("マイク入力が中断されました");
                        }
                        if (read == 0) {
                            if (SystemClock.elapsedRealtime() - lastInput >= INPUT_STALL_MILLIS) throw new IOException("マイクからサンプルが届いていません");
                            Thread.sleep(10);
                            continue;
                        }
                        if (Build.VERSION.SDK_INT >= 29) inspectInput(microphone.getActiveRecordingConfiguration());
                        if (!running) break;
                        lastInput = SystemClock.elapsedRealtime();
                        encoded.clear();
                        for (int i = 0; i < read; i++) encoded.putShort(pcm[i]);
                        int count = read * 2;
                        output.seek(44L + prefix + fresh);
                        output.write(buffer, 0, count);
                        fresh += count;
                        samples += count / 2;
                        output.seek(0); output.write(wavHeader(prefix + fresh));
                        // ponytail: sync each second of PCM; calibrate the interval with concurrent camera load.
                        if (fresh / (RATE * 2) != (fresh - count) / (RATE * 2)) output.getFD().sync();
                        if (!receivedSamples) { receivedSamples = true; recordingState.accept(true); }
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
            if (BuildConfig.DEBUG) android.util.Log.w("DocScanListening", "Audio input stopped", error);
            recordingError = "録音が中断されました。原音を保全しています";
            if (!closed) onFailure.run();
        } finally {
            running = false;
            try {
                releaseMicrophone();
                if (!closed && recordingError == null) save("phase", "stopped");
            } catch (IOException error) {
                recordingError = "録音の終了位置を保存できません。原音は保持しています";
                if (!closed) onFailure.run();
            }
            finally {
                recordingState.accept(false);
                synchronized (this) { recordingStopped = true; if (closed) uploads.shutdown(); }
            }
        }
    }

    private void releaseMicrophone() {
        if (microphone == null) return;
        try {
            if (audioCallback != null && Build.VERSION.SDK_INT >= 29) microphone.unregisterAudioRecordingCallback(audioCallback);
            microphone.stop();
        } catch (IllegalStateException ignored) { }
        finally { microphone.release(); microphone = null; }
    }

    private void upload(File file, int sequence, long start) {
        if (closed || documentId == 0) return;
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
        if (closed) throw new IOException("録音は終了しています");
        running = false;
        if (recording != null) recording.join();
        Future<?> drained = uploads.submit(() -> { });
        drained.get();
        if (chunks == 0) throw new IOException("録音がありません");
        if (documentId == 0) throw new DocumentPending();
        uploadError = null;
        for (int i = 0; i < chunks; i++) {
            upload(chunk(i), i, Math.max(0, (long)i * CHUNK - OVERLAP));
            if (uploadError != null) throw new IOException("原音の転送が未完了です。録音は保存済みです", uploadError);
        }
        if (recordingError != null) throw new IOException(recordingError);
        if (closed) throw new IOException("録音は終了しています");
        api.completeAudio(documentId, chunks, samples);
        save("phase", "complete");
    }

    private File chunk(int sequence) { return new File(directory, String.format(java.util.Locale.ROOT, "%04d.wav", sequence)); }

    private synchronized void save(String name, String value) throws IOException {
        Properties next = new Properties(); next.putAll(saved); next.setProperty(name, value);
        next.setProperty("epoch", Long.toString(epoch));
        if (!next.containsKey("document") || (next.getProperty("document").equals("0") && documentId > 0)) {
            next.setProperty("document", Long.toString(documentId));
        }
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

    void requestStop() { running = false; }

    @Override public synchronized void close() {
        closed = true;
        running = false;
        if (recording == null || recordingStopped) uploads.shutdown();
    }
}
