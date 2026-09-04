package dev.rokid.docscanglass.doc;

/** One photographed page waiting for the server, with its recognized text. */
public final class PendingPage {

    private final int pageIndex;
    private final byte[] jpeg;
    private final String ocrText;
    private final int imageRotation;
    private int attempts;

    public PendingPage(int pageIndex, byte[] jpeg, String ocrText, int imageRotation) {
        this.pageIndex = pageIndex;
        this.jpeg = jpeg == null ? new byte[0] : jpeg;
        this.ocrText = ocrText == null ? "" : ocrText.trim();
        this.imageRotation = imageRotation;
    }

    public int pageIndex() {
        return pageIndex;
    }

    public byte[] jpeg() {
        return jpeg;
    }

    public String ocrText() {
        return ocrText;
    }

    public int imageRotation() {
        return imageRotation;
    }

    /** Failed upload attempts so far, for back-off. */
    public int attempts() {
        return attempts;
    }

    void recordAttempt() {
        attempts++;
    }
}
