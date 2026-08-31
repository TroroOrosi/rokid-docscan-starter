package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.util.List;
import org.junit.Test;

public class RelayWorkflowTest {
    @Test
    public void zeroProblemRetryWalksOnlyExistingPages() {
        RetryCursor cursor = new RetryCursor();
        cursor.begin(3);

        assertTrue(cursor.isActive());
        assertEquals(0, cursor.nextOr(3));
        assertEquals(-1, cursor.previousOr(3));

        cursor.onUploaded(0);
        assertEquals(1, cursor.nextOr(3));
        assertEquals(0, cursor.previousOr(3));

        cursor.onUploaded(1);
        assertEquals(2, cursor.nextOr(3));
        cursor.onUploaded(2);

        assertFalse(cursor.isActive());
        assertEquals(3, cursor.nextOr(3));
    }

    @Test
    public void previousRetryDoesNotAdvanceCurrentTarget() {
        RetryCursor cursor = new RetryCursor();
        cursor.begin(3);
        cursor.onUploaded(0);

        cursor.onUploaded(cursor.previousOr(3));

        assertEquals(1, cursor.nextOr(3));
    }

    @Test
    public void scanAckUsesAiKeyLongPressVocabulary() {
        List<String> source = List.of(
                "P01 読取済み",
                "1ページ読取済",
                "次ページ / 完了はスマホ");

        List<String> adapted = RelayMessages.forAiKeyScanAck(source);

        assertEquals("次ページ / 完了はスマホ", adapted.get(2));
        assertEquals("次ページ / 完了はスマホ", source.get(2));
    }

    @Test
    public void capturePipelineStatesAreBusy() {
        assertTrue(RelayState.CAPTURING.isCaptureInProgress());
        assertTrue(RelayState.OCR.isCaptureInProgress());
        assertTrue(RelayState.UPLOADING.isCaptureInProgress());
        assertFalse(RelayState.READING.isCaptureInProgress());
        assertFalse(RelayState.ERROR.isCaptureInProgress());
    }
}
