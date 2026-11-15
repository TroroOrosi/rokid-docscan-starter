package dev.rokid.docscanglass.doc;

import dev.rokid.docscanrelay.CaptureProvenance;
import dev.rokid.docscanrelay.CaptureSurface;

/**
 * What the capture surface and the activity ask of a camera that turns the page in view into one JPEG:
 * {@link GlassCamera} with a still, {@link ClipCamera} with a frame of the clip it records.
 */
interface PageCamera {
    /** Runs {@code ready} once, when a page that was not taken yet has been seen still. */
    void awaitNextPage(Runnable ready);

    /** One page; the result arrives at the camera's callback. */
    void captureOnce();

    void preview();

    void pausePreview();

    void resetPages();

    /** Whether pages turned to during a review are photographed and kept; false makes the surface answer the same. */
    default boolean supportsFuturePages() { return true; }

    void observeFuturePages(int capacity, CaptureSurface.FuturePageListener listener);

    void stopFuturePages(Runnable idle);

    CaptureSurface.NativeScene nativeSelectionScene(CaptureProvenance source);

    boolean isNativeSelectionSceneCurrent(CaptureSurface.NativeScene scene);

    void requestNativeAlternative(CaptureSurface.NativeScene scene, CaptureSurface.NativeAlternative result);

    void close();

    /** {@code completed} runs on the camera's thread once nothing of the camera is in use any more. */
    void close(Runnable completed);
}
