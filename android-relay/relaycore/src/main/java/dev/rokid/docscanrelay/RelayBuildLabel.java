package dev.rokid.docscanrelay;

/**
 * The build identity shown on the phone screen.
 *
 * <p>A capture sweep is only interpretable if the operator can tell which build
 * took the photo, and consecutive relay builds differ in ways that change the
 * measurement: 0.3.8 opens the preset ladder on 4032x3024 q50 while 0.3.9 opens
 * it on 1920x1080 q95. Wireless debugging is not always up during a session, so
 * this cannot rely on {@code adb shell dumpsys package}.</p>
 */
public final class RelayBuildLabel {
    private RelayBuildLabel() {}

    public static String title(String versionName, int versionCode) {
        String name = versionName == null ? "" : versionName.trim();
        String suffix = name.isEmpty() ? "" : " " + name;
        return "Rokid DocScan Relay" + suffix + " (build " + versionCode + ")";
    }
}
