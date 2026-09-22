package dev.rokid.docscanrelay;

public enum RelayState {
    DISCONNECTED,
    READY,
    AIMING,
    STABILIZING,
    CAPTURING,
    OCR,
    CAPTURE_REVIEW,
    UPLOADING,
    READING,
    LISTENING,
    FINALIZING,
    REVIEW,
    ERROR;

    public boolean isCaptureInProgress() {
        return this == STABILIZING
                || this == CAPTURING
                || this == OCR
                || this == UPLOADING;
    }
}
