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
    ERROR
}
