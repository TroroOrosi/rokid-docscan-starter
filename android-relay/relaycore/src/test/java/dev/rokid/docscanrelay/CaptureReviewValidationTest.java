package dev.rokid.docscanrelay;

import static org.junit.Assert.*;
import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import org.junit.Test;

/** Invalid candidates must never replace the only recoverable original. */
public class CaptureReviewValidationTest {
    @Test public void rejectsInvalidMetadataBeforeTouchingThePreviousOriginal() throws Exception {
        File file = new File(Files.createTempDirectory("capture-validation").toFile(), "pending.bin");
        CaptureReviewPersistence store = new CaptureReviewPersistence(file);
        CaptureReviewStore.Pending original = new CaptureReviewStore.Pending(0,
                new byte[]{1, 2, 3}, "原文", 270, "", PageFraming.UNKNOWN, 123);
        store.save(original);
        byte[] before = Files.readAllBytes(file.toPath());
        CaptureReviewStore.Pending[] invalid = {
                new CaptureReviewStore.Pending(-1, new byte[]{9}, "", 270, ""),
                new CaptureReviewStore.Pending(0, new byte[]{9}, "", 45, ""),
                new CaptureReviewStore.Pending(0, new byte[0], "", 270, ""),
                new CaptureReviewStore.Pending(0, new byte[]{9}, "", 270, "", null, -1),
                new CaptureReviewStore.Pending(0, new byte[8 * 1024 * 1024 + 1], "", 270, "")
        };
        for (CaptureReviewStore.Pending candidate : invalid) {
            try {
                store.save(candidate);
                fail("invalid candidate was accepted");
            } catch (IOException expected) { }
            assertArrayEquals("last good original must remain byte-identical", before,
                    Files.readAllBytes(file.toPath()));
        }
    }
}
