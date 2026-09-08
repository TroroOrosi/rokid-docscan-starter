package dev.rokid.docscanglass.input;

import java.util.Set;

/** Activity key names retained as known candidates during hardware calibration. */
public final class GlassKeyEvents {

    private static final Set<String> KNOWN_NAMES = Set.of(
            "KEYCODE_BACK",
            "KEYCODE_BUTTON_A",
            "KEYCODE_DPAD_CENTER",
            "KEYCODE_DPAD_DOWN",
            "KEYCODE_DPAD_LEFT",
            "KEYCODE_DPAD_RIGHT",
            "KEYCODE_DPAD_UP",
            "KEYCODE_ENTER",
            "KEYCODE_NUMPAD_ENTER",
            "KEYCODE_NOTIFICATION");

    private GlassKeyEvents() {
    }

    public static boolean isKnown(String keyName) {
        return keyName != null && KNOWN_NAMES.contains(keyName);
    }
}
