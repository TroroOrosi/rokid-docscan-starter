package dev.rokid.docscanrelay;

/**
 * Distinguishes a glasses status notification from a genuine callback-epoch reset.
 *
 * <p>A device status change does not prove that a queued image callback from the
 * current CXR-L binding is gone. Only resetting the service binding invalidates
 * that callback epoch and makes it safe to release an unresolved capture.</p>
 */
public enum CaptureLinkEvent {
    GLASSES_STATUS_CHANGED(false),
    SERVICE_BINDING_RESET(true);

    private final boolean resetsCapture;

    CaptureLinkEvent(boolean resetsCapture) {
        this.resetsCapture = resetsCapture;
    }

    boolean resetsCapture() {
        return resetsCapture;
    }

    void resetCaptureIfSafe(Runnable resetAction) {
        if (resetsCapture) {
            resetAction.run();
        }
    }
}
