package dev.rokid.docscanrelay;

import java.util.ArrayList;
import java.util.List;

/** Adapts server HUD copy to the single tap this firmware delivers. */
final class RelayMessages {
    private RelayMessages() {
    }

    static List<String> forAiKeyScanAck(List<String> serverLines) {
        List<String> adapted = new ArrayList<>(serverLines.size());
        for (String line : serverLines) {
            adapted.add((line == null ? "" : line).replace("ダブルタップ", "スマホ")
                    .replace("長押し", "スマホ"));
        }
        return adapted;
    }
}
