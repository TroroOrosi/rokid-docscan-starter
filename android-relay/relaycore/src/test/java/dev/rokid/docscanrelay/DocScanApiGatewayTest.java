package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.fail;

import java.net.UnknownHostException;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

/** "gateway" goes to the Wi-Fi gateway lookup, never to DNS. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
public class DocScanApiGatewayTest {
    @Test public void gatewayHostWithoutAWifiNetworkNamesTheHotspot() throws Exception {
        DocScanApi api = new DocScanApi("http://" + DocScanApi.GATEWAY_HOST + ":8000", "k",
                new ClientIdentity("test", "test", "test"), RuntimeEnvironment.getApplication());
        try {
            api.health();
            fail("no Wi-Fi network, so there is no gateway to reach");
        } catch (UnknownHostException expected) {
            assertEquals("スマホのテザリングに接続されていません", expected.getMessage());
        }
    }
}
