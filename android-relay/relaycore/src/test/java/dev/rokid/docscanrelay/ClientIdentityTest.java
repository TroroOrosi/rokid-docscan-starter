package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThrows;

import org.junit.Test;

public class ClientIdentityTest {
    @Test
    public void reportsExactlyWhatTheOwningAppSupplied() {
        // The pipeline is shared, so the app that owns the capture surface is
        // the only thing that knows which device and SDK produced the page.
        ClientIdentity identity = new ClientIdentity(
                "rokid-glasses-camera2", "glassdoc/0.6.0", "camera2/no-cxr");

        assertEquals("rokid-glasses-camera2", identity.captureDevice);
        assertEquals("glassdoc/0.6.0", identity.clientVersion);
        assertEquals("camera2/no-cxr", identity.sdkHint);
    }

    @Test
    public void trimsSurroundingWhitespaceSoTheServerNeverStoresIt() {
        ClientIdentity identity = new ClientIdentity(
                "  device  ", "  client/1  ", "  sdk  ");

        assertEquals("device", identity.captureDevice);
        assertEquals("client/1", identity.clientVersion);
        assertEquals("sdk", identity.sdkHint);
    }

    @Test
    public void refusesABlankFieldRatherThanRecordingAnEmptyProvenance() {
        // A blank capture_device would be stored as a real provenance for
        // every page of the document, so it has to fail before creation.
        assertThrows(
                IllegalArgumentException.class,
                () -> new ClientIdentity("", "client/1", "sdk"));
        assertThrows(
                IllegalArgumentException.class,
                () -> new ClientIdentity("device", null, "sdk"));
        assertThrows(
                IllegalArgumentException.class,
                () -> new ClientIdentity("device", "client/1", "   "));
    }
}
