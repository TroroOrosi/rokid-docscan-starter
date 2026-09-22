package dev.rokid.docscanrelay;

import static org.junit.Assert.*;
import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

public class LocalCaptureSessionTest {
    @Rule public TemporaryFolder folder = new TemporaryFolder();

    @Test public void localCommitRestartReplacementAndAcknowledgementKeepEachRevision() throws Exception {
        LocalCaptureSession session = LocalCaptureSession.create(folder.getRoot(), "http://phone:8000", false);
        assertEquals(0, session.documentId());
        CaptureReviewStore.Pending first = photo(0, 1);
        session.commit(first);
        LocalCaptureSession restarted = LocalCaptureSession.load(folder.getRoot(), session.id());
        assertEquals(1, restarted.pageCount());
        assertTrue(restarted.contains(first));
        LocalCaptureSession.Page old = restarted.nextUnsent();
        assertArrayEquals(first.jpeg, restarted.read(old).jpeg);
        restarted.bindDocument(17);
        LocalCaptureSession bound = restarted;
        assertThrows(IOException.class, () -> bound.bindDocument(18));
        restarted.commit(photo(0, 2));
        restarted.acknowledge(old); // A late ACK cannot acknowledge the replacement.
        LocalCaptureSession.Page replacement = restarted.nextUnsent();
        assertNotNull(replacement);
        assertArrayEquals(first.jpeg, restarted.read(old).jpeg);
        assertEquals(2, restarted.read(replacement).jpeg[0]);
        restarted.acknowledge(replacement);
        restarted.setPhase(LocalCaptureSession.Phase.ANALYSIS);
        restarted.close();
        restarted = LocalCaptureSession.load(folder.getRoot(), session.id());
        assertEquals(17, restarted.documentId());
        assertNull(restarted.nextUnsent());
        assertEquals(LocalCaptureSession.Phase.CLOSED, restarted.phase());
        restarted.resume();
        assertEquals(LocalCaptureSession.Phase.ANALYSIS, restarted.phase());
    }

    @Test public void failedManifestWriteAndDamagedPageNeverEraseAcceptedPhotos() throws Exception {
        LocalCaptureSession session = LocalCaptureSession.create(folder.getRoot(), "http://phone:8000", true);
        session.commit(photo(0, 1));
        LocalCaptureSession.Page original = session.nextUnsent();
        File temporary = new File(session.directory(), "state.properties.tmp");
        assertTrue(temporary.mkdir()); // Simulate a write failure after the new image was saved.
        assertThrows(IOException.class, () -> session.commit(photo(0, 2)));
        LocalCaptureSession restarted = LocalCaptureSession.load(folder.getRoot(), session.id());
        assertArrayEquals(new byte[]{1, 2, 3}, restarted.read(original).jpeg);
        assertTrue(restarted.contains(photo(0, 1)));
        assertTrue(restarted.listening());
        File image = new File(session.directory(), original.fileName);
        byte[] damaged = Files.readAllBytes(image.toPath());
        damaged[damaged.length - 1] ^= 1;
        Files.write(image.toPath(), damaged);
        assertThrows(IOException.class, () -> restarted.read(original));
        assertArrayEquals(damaged, Files.readAllBytes(image.toPath()));
        assertThrows(IOException.class, () -> LocalCaptureSession.load(folder.getRoot(), "../outside"));
    }

    private static CaptureReviewStore.Pending photo(int index, int value) {
        return new CaptureReviewStore.Pending(index, new byte[]{(byte)value, 2, 3}, "実資料", 180, "",
                PageFraming.UNKNOWN, 1000 + value);
    }
}
