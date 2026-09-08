package dev.rokid.docscanglass.input;

import java.util.List;

/** Official key and touchpad broadcasts documented for Rokid custom apps. */
public final class OfficialKeyBroadcasts {

    private static final List<String> ACTIONS = List.of(
            "com.android.action.ACTION_SPRITE_BUTTON_CLICK",
            "com.android.action.ACTION_SPRITE_BUTTON_DOWN",
            "com.android.action.ACTION_SPRITE_BUTTON_UP",
            "com.android.action.ACTION_SPRITE_BUTTON_DOUBLE_CLICK",
            "com.android.action.ACTION_SPRITE_BUTTON_LONG_PRESS",
            "com.android.action.ACTION_AI_START",
            "com.android.action.ACTION_TWO_FINGER_SINGLE_TAP",
            "com.android.action.ACTION_TWO_FINGER_DOUBLE_TAP",
            "com.android.action.ACTION_TWO_FINGER_SWIPE_FORWARD",
            "com.android.action.ACTION_TWO_FINGER_SWIPE_BACK",
            "com.android.action.ACTION_SETTINGS_KEY");

    private OfficialKeyBroadcasts() {
    }

    public static List<String> actions() {
        return ACTIONS;
    }

    public static boolean isOfficial(String action) {
        return ACTIONS.contains(action);
    }
}
