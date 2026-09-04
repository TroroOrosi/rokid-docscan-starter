package dev.rokid.docscanglass.doc;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Context;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.os.Bundle;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowManager;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import dev.rokid.docscanglass.input.BackExitPolicy;
import dev.rokid.docscanglass.input.GlassKeyEvents;
import dev.rokid.docscanglass.input.GlassesInputAction;
import dev.rokid.docscanglass.input.GlassesInputNormalizer;
import dev.rokid.docscanglass.input.InputSignal;
import dev.rokid.docscanrelay.PageFraming;

/**
 * The operator surface, on the glasses.
 *
 * <p>One gesture drives the loop, because a gesture is all the firmware
 * delivers: a single tap photographs the page in front of the operator, and the
 * page is recognized and uploaded without the phone being in the path at all.
 *
 * <p>Everything here rests on measurements taken 2026-09-04 on
 * {@code RG-glasses} build {@code 1.25.012-20260901-150201}:
 *
 * <ul>
 *   <li>a still takes 785-1380 ms at 4032x3024, so a second tap arriving
 *       mid-capture is refused by {@link ScanSession} rather than opening the
 *       camera twice;</li>
 *   <li>the glasses reach the server on their own Wi-Fi, and hold no route at
 *       all without it, so pages buffer in {@link UploadQueue} and drain when
 *       connectivity returns;</li>
 *   <li>{@code KEYCODE_BACK} is consumable, so the one-finger double tap is a
 *       deliberate two-stage exit instead of ending the session on a mis-tap;</li>
 *   <li>folding the temple arms makes {@code assistserver} force-stop this
 *       process, which is why the pending pages are the source of truth rather
 *       than anything held only in the view.</li>
 * </ul>
 *
 * <p>The server base URL arrives as an Intent extra so a different address
 * costs one adb command rather than a rebuild:
 *
 * <pre>
 * adb -s SERIAL shell am start \
 *   -n dev.rokid.docscanglass.doc/.DocScanGlassActivity \
 *   --es server "http://HOST:8000"
 * </pre>
 */
public final class DocScanGlassActivity extends Activity {

    private static final String TAG = "DocScanGlassDoc";
    private static final String EXTRA_SERVER = "server";
    /** Calibration for the aiming guide; see {@link FramingGuide}. */
    private static final String EXTRA_GUIDE = "guide";
    private static final int CAMERA_PERMISSION_REQUEST = 7401;

    private final ScanSession session = new ScanSession();
    private final UploadQueue queue = new UploadQueue();
    private final GlassesInputNormalizer normalizer = new GlassesInputNormalizer();
    private final BackExitPolicy backExit = new BackExitPolicy();
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService network = Executors.newSingleThreadExecutor();

    private HandlerThread cameraThread;
    private GlassCamera camera;
    private PageOcr ocr;
    private GlassDocApi api;
    private HudView view;
    private String overrideLine;
    private double guideFraction = FramingGuide.UNCALIBRATED_FRACTION;
    private PageFraming lastFraming = PageFraming.UNKNOWN;
    private ReviewFrame reviewFrame;
    private byte[] reviewJpeg;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // The measured default screen-off is 20 s, shorter than one capture
        // plus one upload.
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        view = new HudView(this);
        setContentView(view);

        cameraThread = new HandlerThread("glass-camera");
        cameraThread.start();
        camera = new GlassCamera(this, new Handler(cameraThread.getLooper()), cameraCallback());
        ocr = new PageOcr();

        if (getIntent() != null) {
            guideFraction = getIntent().getFloatExtra(
                    EXTRA_GUIDE, (float) FramingGuide.UNCALIBRATED_FRACTION);
        }
        String server = getIntent() == null ? null : getIntent().getStringExtra(EXTRA_SERVER);
        try {
            api = new GlassDocApi(server);
        } catch (IllegalArgumentException | NullPointerException error) {
            overrideLine = "NO --es server";
            Log.w(TAG, "no usable server URL supplied");
        }
        Log.i(TAG, "glasses document scanner started, guide fraction "
                + guideFraction + " (expects a filling page to cover "
                + FramingGuide.expectedPageAreaFraction(guideFraction)
                + " of the still)");
        redraw();
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        // KEYCODE_BACK is absent on purpose: it has to reach the framework so
        // onBackPressed runs, which is where the two-stage exit is decided.
        if (normalize("DOWN", keyCode)) {
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    public boolean onKeyUp(int keyCode, KeyEvent event) {
        if (normalize("UP", keyCode)) {
            return true;
        }
        return super.onKeyUp(keyCode, event);
    }

    /**
     * The one-finger double tap. Measured on hardware as
     * {@code KEYCODE_NOTIFICATION} twice then {@code KEYCODE_BACK}; left
     * unconsumed it ended the session on a single mis-tap.
     *
     * <p>Lint asks for the AndroidX OnBackPressedDispatcher. Its claim that
     * onBackPressed is no longer called holds only where
     * android.window.OnBackInvokedDispatcher exists, which is API 33; the
     * measured build reports API 32. Revisit when the glasses report 33.
     */
    @Override
    @SuppressLint("GestureBackNavigation")
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (backExit.onBack(SystemClock.elapsedRealtime()) == BackExitPolicy.Decision.EXIT) {
            Log.i(TAG, "exit confirmed");
            finish();
            return;
        }
        overrideLine = "AGAIN TO EXIT";
        redraw();
    }

    @Override
    public void onRequestPermissionsResult(
            int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != CAMERA_PERMISSION_REQUEST) {
            return;
        }
        if (hasCamera()) {
            shoot();
        } else {
            session.onFailed("camera refused");
            redraw();
        }
    }

    @Override
    protected void onDestroy() {
        discardReview();
        camera.close();
        ocr.close();
        cameraThread.quitSafely();
        network.shutdownNow();
        backExit.reset();
        super.onDestroy();
    }

    private boolean normalize(String phase, int keyCode) {
        String name = KeyEvent.keyCodeToString(keyCode);
        Optional<GlassesInputAction> action = normalizer.accept(InputSignal.key(
                SystemClock.elapsedRealtime(), phase, name, GlassKeyEvents.isKnown(name)));
        action.ifPresent(this::onAction);
        // Consume every gesture key the firmware delivers except BACK, so the
        // system does not act on it behind the session.
        return !"KEYCODE_BACK".equals(name) && GlassKeyEvents.isKnown(name);
    }

    private void onAction(GlassesInputAction action) {
        if (action != GlassesInputAction.BACK) {
            backExit.reset();
            overrideLine = null;
        }
        Log.i(TAG, "action " + action);
        switch (action) {
            case SHORT_TAP:
                onTap();
                break;
            case SWIPE_FORWARD:
                if (session.state() == ScanSession.State.REVIEW) {
                    retake();
                } else {
                    drainQueue();
                }
                break;
            case SWIPE_BACK:
                if (session.state() == ScanSession.State.REVIEW) {
                    retake();
                } else {
                    finalizeDocument();
                }
                break;
            default:
                break;
        }
        redraw();
    }

    /** The whole operating loop: start the document, then photograph pages. */
    private void onTap() {
        if (api == null) {
            return;
        }
        if (session.state() == ScanSession.State.NO_DOCUMENT) {
            openDocument();
            return;
        }
        if (session.state() == ScanSession.State.REVIEW) {
            confirmReviewedPage();
            return;
        }
        if (!session.beginCapture()) {
            // A tap arriving inside the 785-1380 ms capture window. Ignoring it
            // is the point; reporting it would be noise.
            return;
        }
        if (!hasCamera()) {
            requestPermissions(new String[]{Manifest.permission.CAMERA}, CAMERA_PERMISSION_REQUEST);
            return;
        }
        shoot();
    }

    /** Throws the reviewed still away and photographs the page again. */
    private void retake() {
        lastFraming = PageFraming.UNKNOWN;
        discardReview();
        if (session.beginCapture() && hasCamera()) {
            shoot();
        }
    }

    @SuppressLint("MissingPermission")
    private void shoot() {
        camera.captureOnce();
    }

    private void openDocument() {
        // Measured 2026-09-04: two taps produced documents 3 and 4 because the
        // guard sat on the response. It sits on the request now.
        if (!session.beginOpenDocument()) {
            return;
        }
        redraw();
        network.execute(() -> {
            try {
                long id = api.createDocument("Rokid Glasses scan");
                main.post(() -> {
                    session.openDocument(id);
                    Log.i(TAG, "document " + id + " open");
                    redraw();
                });
            } catch (Exception error) {
                main.post(() -> {
                    session.onFailed(reasonOf(error));
                    redraw();
                });
            }
        });
    }

    private GlassCamera.Callback cameraCallback() {
        return new GlassCamera.Callback() {
            @Override
            public void onCaptured(byte[] jpeg, int width, int height, long elapsedMillis) {
                ReviewFrame frame = ReviewFrame.of(jpeg);
                main.post(() -> {
                    session.onImageCaptured();
                    showReview(jpeg, frame);
                });
            }

            @Override
            public void onCaptureFailed(String reason) {
                main.post(() -> {
                    session.onFailed(reason);
                    redraw();
                });
            }
        };
    }

    /** Holds the still on screen until the operator accepts or retakes it. */
    private void showReview(byte[] jpeg, ReviewFrame frame) {
        if (reviewFrame != null) {
            reviewFrame.recycle();
        }
        reviewJpeg = jpeg;
        reviewFrame = frame;
        Log.i(TAG, "review " + frame.verdict());
        redraw();
    }

    private void confirmReviewedPage() {
        byte[] jpeg = reviewJpeg;
        if (jpeg == null || !session.confirmPage()) {
            return;
        }
        redraw();
        ocr.recognize(jpeg, ocrCallback(jpeg));
    }

    /**
     * Keeps the still on screen through a failure. Only a new capture or a
     * successful upload replaces it, so "FAILED" always comes with the frame
     * it is talking about.
     */
    private void discardReview() {
        if (reviewFrame != null) {
            reviewFrame.recycle();
            reviewFrame = null;
        }
        reviewJpeg = null;
    }

    private PageOcr.Callback ocrCallback(byte[] jpeg) {
        return new PageOcr.Callback() {
            @Override
            public void onRecognized(String text, PageFraming framing) {
                main.post(() -> {
                    // The relay's framing check, from the recognized line
                    // boxes: it names the side that is cut rather than saying
                    // the border looks dark.
                    lastFraming = framing;
                    if (framing.isFailing()) {
                        session.onFailed(framing.describe());
                        redraw();
                        return;
                    }
                    enqueueAndSend(jpeg, text);
                });
            }

            @Override
            public void onRecognitionFailed(String reason) {
                // The page is still worth keeping: a configured image-capable
                // analyzer can transcribe it server-side.
                Log.w(TAG, "recognition failed, sending image only: " + reason);
                main.post(() -> {
                    lastFraming = PageFraming.UNKNOWN;
                    enqueueAndSend(jpeg, "");
                });
            }
        };
    }

    private void enqueueAndSend(byte[] jpeg, String text) {
        session.onTextRecognized();
        PendingPage page = new PendingPage(
                session.nextPageIndex(), jpeg, text, ReviewFrame.MEASURED_ROTATION_DEGREES);
        if (!queue.enqueue(page)) {
            session.onFailed("buffer full");
            redraw();
            return;
        }
        discardReview();
        redraw();
        drainQueue();
    }

    /** Sends buffered pages oldest first, stopping at the first failure. */
    private void drainQueue() {
        if (api == null || session.documentId() < 0) {
            return;
        }
        network.execute(() -> {
            while (true) {
                Optional<PendingPage> head = queue.head();
                if (!head.isPresent()) {
                    return;
                }
                try {
                    api.uploadPage(session.documentId(), head.get());
                    queue.markUploaded();
                    main.post(() -> {
                        session.onPageAccepted();
                        redraw();
                    });
                } catch (Exception error) {
                    queue.markFailed();
                    String reason = reasonOf(error);
                    main.post(() -> {
                        session.onFailed(reason);
                        redraw();
                    });
                    return;
                }
            }
        });
    }

    private void finalizeDocument() {
        if (api == null || session.documentId() < 0 || queue.size() > 0) {
            return;
        }
        long documentId = session.documentId();
        network.execute(() -> {
            try {
                api.finalizeDocument(documentId);
                main.post(() -> {
                    session.reset();
                    overrideLine = "DONE";
                    redraw();
                });
            } catch (Exception error) {
                main.post(() -> {
                    session.onFailed(reasonOf(error));
                    redraw();
                });
            }
        });
    }

    /** States in which the operator is lining up the next page. */
    private boolean isAiming() {
        ScanSession.State state = session.state();
        return state == ScanSession.State.READY
                || state == ScanSession.State.ACKED
                || state == ScanSession.State.CAPTURING;
    }

    private boolean hasCamera() {
        return checkSelfPermission(Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_GRANTED;
    }

    private static String reasonOf(Exception error) {
        String message = error.getMessage();
        return message == null || message.isEmpty()
                ? error.getClass().getSimpleName() : message;
    }

    private void redraw() {
        if (view != null) {
            view.invalidate();
        }
    }

    /** Green on black: the only combination this display has. */
    private final class HudView extends View {

        private static final int GREEN = Color.rgb(0x40, 0xFF, 0x5E);

        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint guidePaint = new Paint(Paint.ANTI_ALIAS_FLAG);

        HudView(Context context) {
            super(context);
            paint.setColor(GREEN);
            paint.setTypeface(Typeface.MONOSPACE);
            guidePaint.setColor(GREEN);
            guidePaint.setStyle(Paint.Style.STROKE);
        }

        @Override
        protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            canvas.drawColor(Color.BLACK);

            // In review the operator is looking at the page, not at words, so
            // the still gets the upper two thirds and the text is pushed under
            // it. This is the substitute for a viewfinder: a live preview would
            // hold the camera streaming, and the privacy indicator is lit for
            // exactly as long as the camera streams.
            // The still is drawn whenever one exists, not only during review.
            // On 2026-09-04 an operator hit four capture timeouts in a row and
            // the HUD showed "FAILED" with nothing to look at, which says
            // nothing about what to change. If there is an image, show it.
            float textTop = 0;
            ReviewFrame frame = reviewFrame;
            if (frame != null && frame.preview() != null && !frame.preview().isRecycled()) {
                textTop = drawPreview(canvas, frame);
            } else if (isAiming() || session.state() == ScanSession.State.FAILED) {
                drawGuide(canvas);
            }

            List<String> lines = new ArrayList<>(HudLines.render(
                    session.state(), session.nextPageIndex(), queue.size(), session.lastError()));
            if (session.state() == ScanSession.State.REVIEW && frame != null) {
                // During review the exposure verdict replaces the page counter,
                // because that is the decision being made. Framing cannot be
                // judged yet -- it comes from the recognized line boxes, and
                // recognition runs only after the operator confirms.
                lines.set(0, frame.verdict().hudLabel());
            } else if (session.state() == ScanSession.State.FAILED
                    && lastFraming.isFailing()) {
                lines.set(0, lastFraming.describe());
            }
            if (overrideLine != null && !lines.isEmpty()) {
                lines.set(lines.size() - 1, overrideLine);
            }
            if (lines.isEmpty()) {
                return;
            }
            float available = getHeight() - textTop;
            float lineHeight = available / (float) (lines.size() + 1);
            paint.setTextSize(lineHeight * 0.55f);
            float y = textTop + lineHeight;
            for (String line : lines) {
                canvas.drawText(line, lineHeight * 0.2f, y, paint);
                y += lineHeight;
            }
        }

        /**
         * The aiming rectangle. Corner brackets rather than a closed box: on a
         * monochrome see-through display a full outline competes with the page
         * itself, and the corners are what the operator aligns to.
         */
        private void drawGuide(Canvas canvas) {
            FramingGuide.Rect guide =
                    FramingGuide.of(getWidth(), getHeight(), guideFraction);
            if (guide.width() <= 0) {
                return;
            }
            float arm = Math.min(guide.width(), guide.height()) * 0.18f;
            guidePaint.setStrokeWidth(Math.max(2f, guide.width() * 0.008f));
            float[] corners = {
                guide.left(), guide.top(), 1, 1,
                guide.right(), guide.top(), -1, 1,
                guide.left(), guide.bottom(), 1, -1,
                guide.right(), guide.bottom(), -1, -1,
            };
            for (int i = 0; i < corners.length; i += 4) {
                float x = corners[i];
                float y = corners[i + 1];
                float dx = corners[i + 2];
                float dy = corners[i + 3];
                canvas.drawLine(x, y, x + arm * dx, y, guidePaint);
                canvas.drawLine(x, y, x, y + arm * dy, guidePaint);
            }
        }

        /** Draws the still letterboxed into the top band and returns its bottom. */
        private float drawPreview(Canvas canvas, ReviewFrame frame) {
            Bitmap preview = frame.preview();
            float band = getHeight() * 0.62f;
            float scale = Math.min(getWidth() / (float) preview.getWidth(),
                    band / preview.getHeight());
            float width = preview.getWidth() * scale;
            float height = preview.getHeight() * scale;
            RectF target = new RectF(
                    (getWidth() - width) / 2f, 0, (getWidth() + width) / 2f, height);
            canvas.drawBitmap(preview, null, target, null);
            return height;
        }
    }
}
