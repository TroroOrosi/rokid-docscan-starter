package dev.rokid.docscanrelay;

import java.util.ArrayList;
import java.util.List;

/** Adapts server HUD copy to the AI-key timing controls used by this relay. */
final class RelayMessages {
    private RelayMessages() {
    }

    static List<String> forAiKeyScanAck(List<String> serverLines) {
        List<String> adapted = new ArrayList<>(serverLines.size());
        for (String line : serverLines) {
            adapted.add((line == null ? "" : line).replace("ダブルタップ", "長押し"));
        }
        return adapted;
    }
}
