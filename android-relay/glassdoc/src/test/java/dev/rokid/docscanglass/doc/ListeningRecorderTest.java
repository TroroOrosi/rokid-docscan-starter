package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import org.junit.Test;

public class ListeningRecorderTest {
    @Test public void wavMatchesServerPcmContract() {
        byte[] header = ListeningRecorder.wavHeader(960000);
        ByteBuffer bytes = ByteBuffer.wrap(header).order(ByteOrder.LITTLE_ENDIAN);
        assertEquals("RIFF", new String(header, 0, 4, StandardCharsets.US_ASCII));
        assertEquals(960036, bytes.getInt(4));
        assertEquals(1, bytes.getShort(22));
        assertEquals(16000, bytes.getInt(24));
        assertEquals(16, bytes.getShort(34));
        assertEquals(960000, bytes.getInt(40));
    }
}
