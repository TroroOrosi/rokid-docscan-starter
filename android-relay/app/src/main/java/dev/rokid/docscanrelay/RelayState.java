package dev.rokid.docscanrelay;

public enum RelayState {
    DISCONNECTED,
    READY,
    CAPTURING,
    OCR,
    UPLOADING,
    READING,
    FINALIZING,
    REVIEW,
    ERROR;

    public boolean isCaptureInProgress() {
        return this == CAPTURING || this == OCR || this == UPLOADING;
    }
}
