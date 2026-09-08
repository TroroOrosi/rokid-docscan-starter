package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class RelayBuildLabelTest {
    @Test
    public void titleCarriesBothTheVersionAndTheBuildNumber() {
        // The version name alone is not enough: a rebuilt 0.3.9 and the 0.3.9
        // already on the phone are told apart by the build number.
        assertEquals(
                "Rokid DocScan Relay 0.3.9 (build 14)",
                RelayBuildLabel.title("0.3.9", 14));
    }

    @Test
    public void titleStaysUsableWhenTheVersionNameIsMissing() {
        String title = RelayBuildLabel.title("", 14);

        assertTrue(title, title.contains("Rokid DocScan Relay"));
        assertTrue(title, title.contains("14"));
    }
}
