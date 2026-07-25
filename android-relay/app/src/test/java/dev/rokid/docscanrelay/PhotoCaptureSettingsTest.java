package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public class PhotoCaptureSettingsTest {
    @Test
    public void usesTheClientLDefaultsThatStayWithinTheBinderCallbackLimit() {
        assertEquals(1920, DocScanController.PHOTO_WIDTH);
        assertEquals(1080, DocScanController.PHOTO_HEIGHT);
        assertEquals(80, DocScanController.PHOTO_QUALITY);
    }
}
