package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.io.DataInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.util.ArrayDeque;
import java.util.concurrent.Executor;

import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

public final class FieldRecordTest {
    @Rule public final TemporaryFolder folder = new TemporaryFolder();

    /** A whole-field watch frame, 640x480 in rows of 640: every pixel says where it is. */
    private static byte[] frame(int add) {
        byte[] luma = new byte[640 * 480];
        for (int y = 0; y < 480; y++) for (int x = 0; x < 640; x++) luma[y * 640 + x] = (byte) (x / 4 + y / 4 + add);
        return luma;
    }

    @Test public void aFrameIsWrittenAtTheRecordsSizeWithItsTimesAndTheClipsBegunSoFar() throws Exception {
        File file = folder.newFile("field.bin");
        FieldRecord record = new FieldRecord(file, Runnable::run, 1 << 20);

        assertTrue(record.offer(frame(0), 640, 480, 640, 1, 1_700_000_000_123L, 987_654_321L, 3, 10_000));
        record.close();

        assertEquals(FieldRecord.RECORD_BYTES, file.length());
        try (DataInputStream in = new DataInputStream(new FileInputStream(file))) {
            assertEquals(1_700_000_000_123L, in.readLong());
            assertEquals(987_654_321L, in.readLong());
            assertEquals(3, in.readInt());
            byte[] pixels = new byte[FieldRecord.WIDTH * FieldRecord.HEIGHT];
            in.readFully(pixels);
            // 640x480 to 320x240: every second pixel of every second row
            assertEquals((byte) 0, pixels[0]);
            assertEquals((byte) (2 * 100 / 4 + 2 * 50 / 4), pixels[50 * FieldRecord.WIDTH + 100]);
            assertEquals((byte) (638 / 4 + 478 / 4), pixels[239 * FieldRecord.WIDTH + 319]);
        }
    }

    @Test public void framesCloserThanAFifthOfASecondAreLeftOut() throws Exception {
        File file = folder.newFile("field.bin");
        FieldRecord record = new FieldRecord(file, Runnable::run, 1 << 20);

        assertTrue(record.offer(frame(0), 640, 480, 640, 1, 1, 1, 0, 10_000));
        assertFalse(record.offer(frame(1), 640, 480, 640, 1, 2, 2, 0, 10_100));
        assertTrue(record.offer(frame(2), 640, 480, 640, 1, 3, 3, 0, 10_200));
        record.close();

        assertEquals(2L * FieldRecord.RECORD_BYTES, file.length());
    }

    @Test public void aFrameOfferedWhileTheLastIsStillBeingWrittenIsDroppedAndTheCameraNeverWaits() throws Exception {
        File file = folder.newFile("field.bin");
        ArrayDeque<Runnable> held = new ArrayDeque<>();
        Executor slow = held::add;
        FieldRecord record = new FieldRecord(file, slow, 1 << 20);

        assertTrue(record.offer(frame(0), 640, 480, 640, 1, 1, 1, 0, 10_000));
        assertFalse("the storage has not taken the last frame yet", record.offer(frame(1), 640, 480, 640, 1, 2, 2, 0, 11_000));
        held.remove().run();
        assertTrue(record.offer(frame(2), 640, 480, 640, 1, 3, 3, 0, 12_000));
        held.remove().run();
        record.close();
        while (!held.isEmpty()) held.remove().run();

        assertEquals(2L * FieldRecord.RECORD_BYTES, file.length());
    }

    @Test public void theRecordStopsAtItsLimitAndIsAddedToByALaterStart() throws Exception {
        File file = folder.newFile("field.bin");
        FieldRecord first = new FieldRecord(file, Runnable::run, 2L * FieldRecord.RECORD_BYTES);
        assertTrue(first.offer(frame(0), 640, 480, 640, 1, 1, 1, 0, 10_000));
        assertTrue(first.offer(frame(1), 640, 480, 640, 1, 2, 2, 0, 11_000));
        assertFalse("the limit is reached", first.offer(frame(2), 640, 480, 640, 1, 3, 3, 0, 12_000));
        first.close();

        // The app was started again in the same worn pass: the frames already there stay, and count towards the limit.
        FieldRecord second = new FieldRecord(file, Runnable::run, 3L * FieldRecord.RECORD_BYTES);
        assertTrue(second.offer(frame(3), 640, 480, 640, 1, 4, 4, 1, 10_000));
        assertFalse(second.offer(frame(4), 640, 480, 640, 1, 5, 5, 1, 11_000));
        second.close();

        assertEquals(3L * FieldRecord.RECORD_BYTES, file.length());
    }
}
