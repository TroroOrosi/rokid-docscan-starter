package dev.rokid.docscanrelay;

import static org.junit.Assert.*;
import java.io.*;
import java.nio.file.Files;
import java.nio.file.StandardOpenOption;
import org.junit.Test;

public class CaptureStreamingMatchTest {
    private static CaptureReviewStore.Pending pending(byte[] jpeg, String text) {
        return new CaptureReviewStore.Pending(2, jpeg, text, 270, "", PageFraming.UNKNOWN, 123);
    }
    @Test public void comparesAllBytesAndMetadataAndDoesNotConsumeTheRecord() throws Exception {
        File file = new File(Files.createTempDirectory("capture-compare").toFile(), "pending.bin");
        CaptureReviewPersistence store = new CaptureReviewPersistence(file);
        byte[] jpeg = new byte[20003];
        jpeg[0] = 1; jpeg[8192] = 2; jpeg[20002] = 3;
        CaptureReviewStore.Pending original = pending(jpeg, "原文");
        store.save(original);
        byte[] before = Files.readAllBytes(file.toPath());
        assertTrue(store.matches(original));
        for (int index : new int[]{0, 8192, 20002}) {
            byte[] changed = jpeg.clone(); changed[index]++;
            assertFalse(store.matches(pending(changed, "原文")));
        }
        assertFalse(store.matches(pending(new byte[2], "原文")));
        assertFalse(store.matches(pending(new byte[25000], "原文")));
        assertFalse(store.matches(pending(jpeg, "別の原文")));
        assertFalse(store.matches(new CaptureReviewStore.Pending(3, jpeg, "原文", 270, "", null, 123)));
        assertFalse(store.matches(new CaptureReviewStore.Pending(2, jpeg, "原文", 90, "", null, 123)));
        assertFalse(store.matches(new CaptureReviewStore.Pending(2, jpeg, "原文", 270, "failed", null, 123)));
        assertFalse(store.matches(new CaptureReviewStore.Pending(2, jpeg, "原文", 270, "", null, 124)));
        assertArrayEquals(before, Files.readAllBytes(file.toPath()));
        assertArrayEquals(jpeg, store.readPending().jpeg);
    }
    @Test public void validatesCorruptTailEvenWhenJpegAlreadyDiffers() throws Exception {
        File file = new File(Files.createTempDirectory("capture-tail").toFile(), "pending.bin");
        CaptureReviewPersistence store = new CaptureReviewPersistence(file);
        store.save(pending(new byte[]{1, 2, 3}, "原文"));
        byte[] intact = Files.readAllBytes(file.toPath());
        for (boolean truncated : new boolean[]{false, true}) {
            Files.write(file.toPath(), intact);
            if (truncated) try (RandomAccessFile data = new RandomAccessFile(file, "rw")) {
                data.setLength(intact.length - 1);
            } else Files.write(file.toPath(), new byte[]{9}, StandardOpenOption.APPEND);
            byte[] corrupted = Files.readAllBytes(file.toPath());
            try { store.matches(pending(new byte[]{9}, "other")); fail("corruption must be explicit"); }
            catch (IOException expected) { }
            assertArrayEquals(corrupted, Files.readAllBytes(file.toPath()));
        }
    }
    @Test public void acceptsVersionOneWithoutInventingFramingOrTime() throws Exception {
        File file = new File(Files.createTempDirectory("capture-v1").toFile(), "pending.bin");
        try (DataOutputStream data = new DataOutputStream(new FileOutputStream(file))) {
            data.writeInt(0x44534350); data.writeInt(1); data.writeInt(0); data.writeInt(90);
            data.writeInt(0); data.writeInt(0); data.writeInt(3); data.write(new byte[]{1, 2, 3});
        }
        CaptureReviewPersistence store = new CaptureReviewPersistence(file);
        assertTrue(store.matches(new CaptureReviewStore.Pending(0, new byte[]{1,2,3}, "", 90, "")));
        assertEquals(0, store.readPending().capturedAtMillis);
    }
}
