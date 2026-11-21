package dev.rokid.docscanrelay;

import static org.junit.Assert.*;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Set;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

public class ClipInboxTest {
    private static final String A = "11111111-2222-3333-4444-555555555555";
    private static final String B = "66666666-7777-8888-9999-000000000000";
    private static final byte[] RECORD = "{\"schema\":1}".getBytes(StandardCharsets.UTF_8);
    @Rule public TemporaryFolder folder = new TemporaryFolder();

    @Test public void aClipIsThereOnlyOnceItsRecordIsWritten() throws Exception {
        ClipInbox inbox = new ClipInbox(new File(folder.getRoot(), "clip-inbox"));
        File clip = inbox.reserve(A);
        assertFalse(inbox.has(A));
        Files.write(clip.toPath(), new byte[]{1, 2, 3});
        assertFalse("a clip without its record is still being written", inbox.has(A));
        inbox.offer(A, RECORD);
        assertTrue(inbox.has(A));
        assertFalse(inbox.has(B));
    }

    @Test public void aClipThatWasNeverWrittenCannotBeOffered() throws Exception {
        ClipInbox inbox = new ClipInbox(new File(folder.getRoot(), "clip-inbox"));
        inbox.reserve(A);
        assertThrows(IOException.class, () -> inbox.offer(A, RECORD));
        assertFalse(inbox.has(A));
    }

    @Test public void clipsOfPhotosThatWereReplacedAreDiscarded() throws Exception {
        ClipInbox inbox = new ClipInbox(new File(folder.getRoot(), "clip-inbox"));
        for (String id : new String[]{A, B}) {
            Files.write(inbox.reserve(id).toPath(), new byte[]{1});
            inbox.offer(id, RECORD);
        }
        File first = inbox.clip(A);
        inbox.discardExcept(Set.of(B));
        assertFalse(inbox.has(A));
        assertFalse(first.exists());
        assertTrue(inbox.has(B));
        inbox.discardExcept(Set.of());
        assertFalse(inbox.has(B));
    }

    @Test public void onlyACaptureIdNamesAClip() {
        ClipInbox inbox = new ClipInbox(new File(folder.getRoot(), "clip-inbox"));
        assertThrows(IOException.class, () -> inbox.reserve("../outside"));
        assertFalse(inbox.has("../outside"));
    }
}
