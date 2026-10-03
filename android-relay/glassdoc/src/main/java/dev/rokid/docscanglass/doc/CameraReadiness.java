package dev.rokid.docscanglass.doc;

import static android.hardware.camera2.CameraMetadata.*;

/** Fresh native metering only; this is not an OCR or all-character readability test. */
final class CameraReadiness {
    static final long FRESH_MILLIS = 500;
    final int afMode;
    private final boolean aeSupported;
    private Integer afState;
    private Integer aeState;
    private long observedAt = -1;

    CameraReadiness(int[] afModes, Float minimumFocus, int[] aeModes) {
        afMode = minimumFocus != null && minimumFocus == 0f && contains(afModes, CONTROL_AF_MODE_OFF)
                ? CONTROL_AF_MODE_OFF : contains(afModes, CONTROL_AF_MODE_CONTINUOUS_PICTURE)
                ? CONTROL_AF_MODE_CONTINUOUS_PICTURE : contains(afModes, CONTROL_AF_MODE_AUTO)
                ? CONTROL_AF_MODE_AUTO : contains(afModes, CONTROL_AF_MODE_CONTINUOUS_VIDEO)
                ? CONTROL_AF_MODE_CONTINUOUS_VIDEO : contains(afModes, CONTROL_AF_MODE_MACRO)
                ? CONTROL_AF_MODE_MACRO : -1;
        aeSupported = contains(aeModes, CONTROL_AE_MODE_ON);
    }

    boolean supported() { return afMode >= 0 && aeSupported; }

    boolean needsTrigger() { return afMode == CONTROL_AF_MODE_AUTO || afMode == CONTROL_AF_MODE_MACRO; }

    void observe(Integer focus, Integer exposure, long now) {
        afState = focus;
        aeState = exposure;
        observedAt = now;
    }

    boolean ready(long now) {
        return supported() && observedAt >= 0 && now >= observedAt && now - observedAt <= FRESH_MILLIS
                && (afMode == CONTROL_AF_MODE_OFF || (afState != null
                && (afState == CONTROL_AF_STATE_FOCUSED_LOCKED
                || (!needsTrigger() && afState == CONTROL_AF_STATE_PASSIVE_FOCUSED))))
                && aeState != null && (aeState == CONTROL_AE_STATE_CONVERGED || aeState == CONTROL_AE_STATE_LOCKED);
    }

    private static boolean contains(int[] modes, int mode) {
        if (modes != null) for (int value : modes) if (value == mode) return true;
        return false;
    }
}
