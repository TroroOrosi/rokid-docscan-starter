package dev.rokid.docscanrelay;

/**
 * Applies one typed CXR-L link event to both capture-guard owners.
 *
 * <p>The link-level reset runs first, then the same event is forwarded to the
 * workflow controller. This keeps a glasses status callback from being
 * reinterpreted as a service-binding reset at either layer.</p>
 */
final class CaptureLinkCoordinator {
    @FunctionalInterface
    interface Listener {
        void onCaptureLinkStateChanged(boolean ready, CaptureLinkEvent event);
    }

    private final Runnable resetLinkCapture;
    private final Listener listener;

    CaptureLinkCoordinator(Runnable resetLinkCapture, Listener listener) {
        this.resetLinkCapture = resetLinkCapture;
        this.listener = listener;
    }

    void glassesStatusChanged(boolean connected) {
        dispatch(connected, CaptureLinkEvent.GLASSES_STATUS_CHANGED);
    }

    void serviceBindingReset(boolean connected) {
        dispatch(connected, CaptureLinkEvent.SERVICE_BINDING_RESET);
    }

    private void dispatch(boolean connected, CaptureLinkEvent event) {
        event.resetCaptureIfSafe(resetLinkCapture);
        listener.onCaptureLinkStateChanged(connected, event);
    }
}
