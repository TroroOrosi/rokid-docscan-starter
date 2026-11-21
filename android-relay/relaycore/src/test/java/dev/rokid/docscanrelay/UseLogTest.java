package dev.rokid.docscanrelay;

import static org.junit.Assert.*;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;
import org.robolectric.shadows.ShadowLog;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
public class UseLogTest {
    @Rule public TemporaryFolder folder = new TemporaryFolder();

    private List<String> lines(String name) throws IOException {
        return Files.readAllLines(new File(folder.getRoot(), name).toPath(), StandardCharsets.UTF_8);
    }

    @Test public void aLineCarriesBothClocksItsTagAndItsMessage() throws Exception {
        UseLog log = new UseLog(UseLog.ROTATE_BYTES, UseLog.MAX_WAITING);
        log.use(folder.getRoot());
        long before = System.currentTimeMillis();
        log.line("Tag", "start version=1 free_mb=2");
        log.line("Tag", "two\nlines");
        log.await();
        List<String> written = lines(UseLog.FILE);
        assertEquals(2, written.size());
        String[] parts = written.get(0).split(" ", 4);
        assertTrue(Long.parseLong(parts[0]) >= before && Long.parseLong(parts[0]) <= System.currentTimeMillis());
        assertTrue(Long.parseLong(parts[1]) >= 0);
        assertEquals("Tag", parts[2]);
        assertEquals("start version=1 free_mb=2", parts[3]);
        assertTrue("one line an entry", written.get(1).endsWith(" Tag two lines"));
    }

    @Test public void aFileOverItsSizeBecomesTheOlderOneAndReplacesTheOneBefore() throws Exception {
        UseLog log = new UseLog(100, UseLog.MAX_WAITING);
        log.use(folder.getRoot());
        Files.write(new File(folder.getRoot(), UseLog.OLDER).toPath(), "from before\n".getBytes(StandardCharsets.UTF_8));
        for (int i = 0; i < 3; i++) log.line("Tag", "line=" + i + " " + "x".repeat(40)); // two of them pass 100 bytes
        log.await();
        List<String> older = lines(UseLog.OLDER), current = lines(UseLog.FILE);
        assertTrue("the first lines moved on: " + older, older.get(0).contains("line=0"));
        assertFalse(older.toString().contains("from before"));
        assertTrue("and a new file was begun: " + current, current.get(current.size() - 1).contains("line=2"));
        assertEquals("no line is lost at the change", 3, older.size() + current.size());
    }

    @Test public void aNewStartAppendsToWhatIsThere() throws Exception {
        UseLog first = new UseLog(UseLog.ROTATE_BYTES, UseLog.MAX_WAITING);
        first.use(folder.getRoot()); first.line("Tag", "one"); first.await();
        UseLog second = new UseLog(UseLog.ROTATE_BYTES, UseLog.MAX_WAITING);
        second.use(folder.getRoot()); second.line("Tag", "two"); second.await();
        assertEquals(2, lines(UseLog.FILE).size());
    }

    @Test public void linesBeyondWhatMayWaitAreDroppedCountedAndNeverHoldTheCaller() throws Exception {
        UseLog log = new UseLog(UseLog.ROTATE_BYTES, 3);
        log.use(folder.getRoot());
        log.await();
        CountDownLatch held = new CountDownLatch(1), holding = new CountDownLatch(1);
        log.run(() -> {
            holding.countDown();
            try { held.await(5, TimeUnit.SECONDS); } catch (InterruptedException ignored) { }
        });
        assertTrue(holding.await(5, TimeUnit.SECONDS)); // the writer is busy: what follows can only wait
        long began = System.nanoTime();
        for (int i = 0; i < 10; i++) log.line("Tag", "line=" + i);
        assertTrue("the caller only hands the line over", System.nanoTime() - began < TimeUnit.SECONDS.toNanos(2));
        held.countDown();
        log.await();
        log.line("Tag", "after");
        log.await();
        List<String> written = lines(UseLog.FILE);
        assertEquals("three waited, seven were dropped and said so, then the next: " + written, 5, written.size());
        assertTrue(written.get(2).endsWith(" Tag line=2"));
        assertTrue(written.get(3).endsWith(" UseLog dropped=7"));
        assertTrue(written.get(4).endsWith(" Tag after"));
    }

    @Test public void withoutAPlaceToWriteTheLogcatLineIsAllThereIsAndNothingIsThrown() throws Exception {
        UseLog log = new UseLog(UseLog.ROTATE_BYTES, UseLog.MAX_WAITING);
        log.line("Tag", "before any directory");
        File blocked = folder.newFile("not-a-directory");
        log.use(blocked);
        log.line("Tag", "nowhere to go");
        log.await();
        assertEquals(0, blocked.length());
        UseLog.i("UseLogTest", "kept in logcat");
        UseLog.w("UseLogTest", "a warning");
        assertEquals(List.of("kept in logcat", "a warning"),
                ShadowLog.getLogsForTag("UseLogTest").stream().map(item -> item.msg).collect(java.util.stream.Collectors.toList()));
    }

    @Test public void aDiagnosticIsKeptUpToWhereTextTheAppDidNotWriteCouldBegin() {
        // Every message of an exception is appended to a diagnostic behind ": "; it may name a server or quote its reply.
        assertEquals("Photo committed locally; network upload queued", UseLog.head("Photo committed locally; network upload queued"));
        assertEquals("Retake did not start; previous review photo retained",
                UseLog.head("Retake did not start; previous review photo retained: HTTP 500: body"));
        assertEquals("", UseLog.head(null));
    }

    @Test public void aFailedCallIsNamedByItsStatusOrItsClassNeverByItsMessage() {
        assertEquals("http_503", UseLog.failure(new DocScanApi.ApiException(503, "body of the reply")));
        assertEquals("io_SocketTimeoutException", UseLog.failure(new java.net.SocketTimeoutException("failed to connect to /10.0.0.1")));
        assertEquals("io_JSONException", UseLog.failure(new org.json.JSONException("Value x")));
    }
}
