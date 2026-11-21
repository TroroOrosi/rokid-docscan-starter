package dev.rokid.docscanrelay;

import static org.junit.Assert.*;
import java.io.File;
import java.nio.file.Files;
import java.util.Properties;
import java.util.UUID;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

public class NativeSelectionSessionTest {
    @Rule public TemporaryFolder folder = new TemporaryFolder();
    static CaptureReviewStore.Pending photo(LocalCaptureSession session, int value) {
        byte[] jpeg = {(byte)value, 2, 3};
        CaptureProvenance source = CaptureProvenance.nativeStill(jpeg, 4032, 3024, (long)value, (long)value, 1L,
                10_000_000L, 100, 0, 2).bind(session.id(), 0, 270);
        return new CaptureReviewStore.Pending(0, jpeg, "", 270, "", PageFraming.UNKNOWN, 123, source);
    }
    static CaptureSurface.NativeScene scene(CaptureReviewStore.Pending a) {
        return new CaptureSurface.NativeScene(UUID.randomUUID().toString(), 2, 4, a.provenance.captureId, a.provenance.jpegSha256);
    }
    @Test public void bothOriginalsAreDurableBeforeChoiceAndOnlyTheReviewedChoiceEntersUpload() throws Exception {
        LocalCaptureSession session = LocalCaptureSession.create(folder.getRoot(), "http://phone", false);
        var a = photo(session, 11); var b = photo(session, 22);
        assertTrue(session.beginQualitySelection(a, scene(a), 42));
        assertFalse(session.beginQualitySelection(a, scene(a), 42));
        session.retainQualityAlternative(a, b);
        assertArrayEquals(a.jpeg, session.qualityOriginal(0, false).jpeg);
        assertArrayEquals(b.jpeg, session.qualityOriginal(0, true).jpeg);
        var chosen = session.qualityDecision(a, NativeImageQuality.Decision.SELECT_B);
        assertNull(session.nextUnsent()); assertEquals(0, session.pageCount());
        session.commit(chosen);
        var upload = session.read(session.nextUnsent());
        assertArrayEquals(b.jpeg, upload.jpeg); assertEquals(b.provenance, upload.provenance);
        session.acknowledge(session.nextUnsent()); assertNull(session.nextUnsent());
        var restored = LocalCaptureSession.load(folder.getRoot(), session.id());
        assertArrayEquals(a.jpeg, restored.qualityOriginal(0, false).jpeg);
        assertArrayEquals(b.jpeg, restored.qualityOriginal(0, true).jpeg);
        assertFalse(restored.beginQualitySelection(a, scene(a), 42));
    }
    @Test public void restartAndFailedStateSaveDoNotIssueAnExtraOrDestroyOriginals() throws Exception {
        LocalCaptureSession session = LocalCaptureSession.create(folder.getRoot(), "http://phone", false);
        var a = photo(session, 11); var b = photo(session, 22);
        session.beginQualitySelection(a, scene(a), 42);
        var restored = LocalCaptureSession.load(folder.getRoot(), session.id());
        assertFalse(restored.beginQualitySelection(a, scene(a), 43));
        assertTrue(new File(session.directory(), "state.properties.tmp").mkdir());
        assertThrows(java.io.IOException.class, () -> session.retainQualityAlternative(a, b));
        try (var files = Files.list(session.directory().toPath())) {
            assertTrue(files.anyMatch(path -> path.getFileName().toString().startsWith("q-")));
        }
        assertArrayEquals(a.jpeg, restored.qualityOriginal(0, false).jpeg);
        assertNull(restored.nextUnsent());
    }
}
