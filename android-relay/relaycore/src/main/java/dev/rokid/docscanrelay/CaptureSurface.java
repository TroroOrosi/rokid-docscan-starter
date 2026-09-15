package dev.rokid.docscanrelay;

import java.util.List;

/**
 * Everything {@link DocScanController} needs from the device that holds the
 * camera and shows the HUD.
 *
 * <p>The controller and the whole pipeline below it -- OCR, upload, review,
 * solve -- are device-independent. Only these five calls are not, so this is
 * the single seam between the phone relay and a glasses-side app.</p>
 *
 * <p>{@link RokidGlobalLink} implements it over CXR-L, where the HUD is a
 * CUSTOMVIEW owned by Hi Rokid and the photo comes back through a Binder
 * callback. A glasses-side implementation draws the same {@link HudLayout}
 * output on its own canvas and takes the still with camera2, so it has no
 * view generations to fence.</p>
 */
public interface CaptureSurface {
    /** Returned by every view call that could not reach the glasses. */
    long NO_VIEW_GENERATION = -1;

    /**
     * Whether a capture request was accepted. {@code UNKNOWN} is not a
     * failure: the IPC broke after the request may already have been
     * delivered, so the caller must not assume the camera stayed idle.
     */
    enum PhotoStartResult {
        STARTED,
        REJECTED,
        UNKNOWN
    }

    PhotoStartResult takePhoto(int width, int height, int quality);

    long showHud(List<String> lines);

    long showCaptureAiming(int pageNumber, boolean retake, boolean stabilizing);

    long showCaptureReview(byte[] jpeg, int rotationDegrees, List<String> lines);

    /** Only an app-owned surface with verified gestures may register automatically. */
    default boolean supportsLocalCaptureReview() { return false; }

    /** True only while this exact still remains visible, not merely requested. */
    default boolean isCaptureReviewVisible(long generation) { return false; }

    /**
     * Retires an ambiguous view callback stream after an acknowledgement
     * timeout. An implementation that owns its own display has nothing to
     * retire and may do nothing.
     */
    void fenceCustomViewEpoch(long generation, String reason);
}
