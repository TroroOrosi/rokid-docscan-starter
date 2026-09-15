package dev.rokid.docscanglass.doc;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Matrix;
import android.os.Handler;

import java.util.List;
import java.util.concurrent.atomic.AtomicLong;

import dev.rokid.docscanrelay.CaptureSurface;

/**
 * The glasses-side {@link CaptureSurface}: camera2 for the still, this
 * process's own canvas for everything the relay pushes as a CUSTOMVIEW.
 *
 * <p>Nothing below this class differs between the phone and the glasses. The
 * controller, the recognizer, the upload and the review store are the relay's,
 * unchanged.</p>
 */
final class GlassesCaptureSurface implements CaptureSurface {
    /**
     * Longest edge of the review thumbnail. The display is 480x640, so a
     * larger decode would be scaled straight back down, and the still is
     * already held in full as JPEG bytes by the review store.
     */
    private static final int PREVIEW_MAX_EDGE = 640;

    interface Listener {
        /**
         * A view is on screen. The controller will not arm a capture until it
         * hears this for the generation it requested.
         */
        void onViewShown(long generation, String purpose);

        default void onReviewHidden(long generation) { }
    }

    private final Context context;
    private final GlassCamera camera;
    private final HudView hud;
    private final Handler main;
    private final Listener listener;
    private final AtomicLong generations = new AtomicLong();

    private Bitmap preview;
    private volatile long visibleReview = NO_VIEW_GENERATION;
    private volatile boolean closed;

    @Override
    public boolean supportsLocalCaptureReview() { return true; }

    @Override
    public boolean isCaptureReviewVisible(long generation) {
        return generation == visibleReview && visibleReview != NO_VIEW_GENERATION;
    }

    GlassesCaptureSurface(
            Context context,
            GlassCamera camera,
            HudView hud,
            Handler main,
            Listener listener) {
        this.context = context;
        this.camera = camera;
        this.hud = hud;
        this.main = main;
        this.listener = listener;
    }

    /**
     * {@inheritDoc}
     *
     * <p>The arguments are ignored. camera2 here takes the sensor's full
     * 4032x3024 -- measured at 785-1380 ms against the phone relay's 5.2 s --
     * and the device chooses the JPEG quality, so {@code PhotoCaptureSettings}
     * has no effect on this path. The result is delivered to the camera
     * callback the activity installed, not returned here.</p>
     */
    @Override
    public PhotoStartResult takePhoto(int width, int height, int quality) {
        if (context.checkSelfPermission(Manifest.permission.CAMERA)
                != PackageManager.PERMISSION_GRANTED) {
            // REJECTED rather than UNKNOWN: nothing reached the camera, so the
            // controller can release the capture lease at once instead of
            // holding it for a callback that will never arrive.
            return PhotoStartResult.REJECTED;
        }
        camera.captureOnce();
        return PhotoStartResult.STARTED;
    }

    @Override
    public long showHud(List<String> lines) {
        return show("hud", () -> hud.showLines(GlassesHudText.adapt(lines)));
    }

    @Override
    public long showCaptureAiming(int pageNumber, boolean retake, boolean stabilizing) {
        List<String> lines = aimingLines(pageNumber, retake, stabilizing);
        return show(
                stabilizing ? "capture-stabilizing" : "capture-aiming",
                () -> hud.showAiming(lines));
    }

    @Override
    public long showCaptureReview(byte[] jpeg, int rotationDegrees, List<String> lines) {
        Bitmap still = decodePreview(jpeg, rotationDegrees);
        if (still == null) return NO_VIEW_GENERATION;
        return show("capture-review", () -> {
            Bitmap previous = preview;
            preview = still;
            hud.showReview(still, GlassesHudText.adapt(lines));
            recycle(previous);
        });
    }

    /**
     * {@inheritDoc}
     *
     * <p>Nothing to retire. The display is this process's own window, so a
     * view request cannot be stranded in another process's callback stream --
     * which is the only situation the fence exists for.</p>
     */
    @Override
    public void fenceCustomViewEpoch(long generation, String reason) {
    }

    /** Releases the review thumbnail. The activity calls this on destruction. */
    void close() {
        closed = true;
        visibleReview = NO_VIEW_GENERATION;
        generations.incrementAndGet();
        hud.onVisibleFrame(null, null);
        Bitmap held = preview;
        preview = null;
        recycle(held);
    }

    private long show(String purpose, Runnable draw) {
        long generation = generations.incrementAndGet();
        visibleReview = NO_VIEW_GENERATION;
        main.post(() -> {
            if (closed || generation != generations.get()) return;
            draw.run();
            hud.onVisibleFrame(() -> {
                if (closed || generation != generations.get()) return;
                if ("capture-review".equals(purpose)) visibleReview = generation;
                listener.onViewShown(generation, purpose);
            }, () -> {
                visibleReview = NO_VIEW_GENERATION;
                if ("capture-review".equals(purpose)) listener.onReviewHidden(generation);
            });
        });
        return generation;
    }

    /**
     * The aiming text. Deliberately not the relay's: on the phone the shutter
     * is a button and the operator looks at a preview, while here the shutter
     * is a tap on the temple and this is the only thing the operator sees.
     */
    private static List<String> aimingLines(
            int pageNumber, boolean retake, boolean stabilizing) {
        String title = "P" + pageNumber + (retake ? " 撮り直し" : " 撮影");
        if (stabilizing) {
            return List.of(title, "そのまま静止");
        }
        return List.of(title, "枠に用紙を合わせる", "タップで撮影");
    }

    /**
     * Decodes a thumbnail at the display's own size and applies the rotation
     * the controller was configured with.
     */
    private static Bitmap decodePreview(byte[] jpeg, int rotationDegrees) {
        if (jpeg == null || jpeg.length == 0) {
            return null;
        }
        BitmapFactory.Options bounds = new BitmapFactory.Options();
        bounds.inJustDecodeBounds = true;
        BitmapFactory.decodeByteArray(jpeg, 0, jpeg.length, bounds);

        int sample = 1;
        int longest = Math.max(bounds.outWidth, bounds.outHeight);
        while (longest / (sample * 2) >= PREVIEW_MAX_EDGE) {
            sample *= 2;
        }
        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inSampleSize = sample;
        options.inPreferredConfig = Bitmap.Config.RGB_565;

        Bitmap decoded;
        try {
            decoded = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.length, options);
        } catch (OutOfMemoryError error) {
            return null;
        }
        if (decoded == null || rotationDegrees % 360 == 0) {
            return decoded;
        }
        Matrix matrix = new Matrix();
        matrix.postRotate(rotationDegrees);
        Bitmap rotated = Bitmap.createBitmap(
                decoded, 0, 0, decoded.getWidth(), decoded.getHeight(), matrix, true);
        if (rotated != decoded) {
            decoded.recycle();
        }
        return rotated;
    }

    private static void recycle(Bitmap bitmap) {
        if (bitmap != null && !bitmap.isRecycled()) {
            bitmap.recycle();
        }
    }
}
