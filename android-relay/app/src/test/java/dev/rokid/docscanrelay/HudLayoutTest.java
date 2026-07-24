package dev.rokid.docscanrelay;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.util.List;
import org.junit.Test;

public class HudLayoutTest {
    @Test
    public void limitsDisplayToThreeLinesAndEscapesJson() {
        String json = HudLayout.fromLines(List.of("問\"1", "A\\B", "3", "ignored"));
        assertTrue(json.contains("問\\\"1\\nA\\\\B\\n3"));
        assertFalse(json.contains("ignored"));
        assertTrue(json.contains("\"backgroundColor\":\"#000000\""));
    }
}
