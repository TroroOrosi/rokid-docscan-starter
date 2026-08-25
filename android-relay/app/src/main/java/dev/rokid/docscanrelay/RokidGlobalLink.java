package dev.rokid.docscanrelay;

import android.app.Activity;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.content.pm.PackageManager;
import android.os.IBinder;
import android.os.SystemClock;
import android.util.Log;

import com.rokid.sprite.aiapp.externalapp.IAiEventCallback;
import com.rokid.sprite.aiapp.externalapp.ICustomViewCallback;
import com.rokid.sprite.aiapp.externalapp.IDeviceStatusCallback;
import com.rokid.sprite.aiapp.externalapp.IImageStreamCallback;
import com.rokid.sprite.aiapp.externalapp.IMediaStreamService;

import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Minimal global-Hi-Rokid CXR-L client.
 *
 * <p>The official client-l 1.0.1 upper API targets the China package. This
 * class deliberately uses the AIDL interfaces bundled in that official AAR
 * and binds the equivalent exported service in
 * {@code com.rokid.sprite.global.aiapp}. No Rokid binary is copied into this
 * repository.</p>
 */
public final class RokidGlobalLink implements AutoCloseable {
    private volatile String serviceIdentity = "CXR-L 未接続";

    public interface Listener {
        void onLinkConnected(boolean connected);

        void onCaptureLinkStateChanged(boolean connected, CaptureLinkEvent event);

        void onAiPressDown();

        void onAiPressUp();

        void onAiExit();

        void onCustomViewClosedByUser();

        void onCustomViewAvailable(long generation, String purpose);

        void onCustomViewFailed(
                long generation,
                String purpose,
                String message,
                Throwable cause);

        void onPhoto(byte[] jpeg);

        void onPhotoError(String message, Throwable cause);

        void onError(String message, Throwable cause);
    }

    public enum PhotoStartResult {
        STARTED,
        REJECTED,
        UNKNOWN
    }

    private static final String TAG = "DocScanRokid";
    private static final String GLOBAL_PACKAGE = "com.rokid.sprite.global.aiapp";
    private static final String AUTH_ACTION =
            "com.rokid.sprite.aiapp.externalapp.AUTHORIZATION";
    private static final String AUTH_ACTIVITY =
            "com.rokid.sprite.aiapp.externalapp.auth.AuthorizationActivity";
    private static final String MEDIA_ACTION =
            "com.rokid.sprite.aiapp.externalapp.MEDIA_STREAM_SERVICE";
    private static final String EXTRA_AUTH_RESULT = "auth_result";
    private static final String EXTRA_AUTH_TOKEN = "auth_token";
    private static final String EXTRA_AUTH_PACKAGE = "auth_package";
    private static final int AUTH_SUCCESS = 2001;
    private static final long PROGRAMMATIC_CLOSE_TTL_MILLIS = 2000;
    public static final long NO_VIEW_GENERATION = -1;

    private final Context context;
    private final Listener listener;
    private final AtomicBoolean photoInFlight = new AtomicBoolean();
    private final CaptureLinkCoordinator captureLinks;
    private final LinkEpoch bindingEpochs = new LinkEpoch();
    private final LinkEpoch callbackEpochs = new LinkEpoch();
    private final CustomViewCloseTracker customViewCloses =
            new CustomViewCloseTracker(PROGRAMMATIC_CLOSE_TTL_MILLIS);
    private final CustomViewOpenTracker customViewOpens = new CustomViewOpenTracker();
    private final Map<Long, String> viewPurposes = new HashMap<>();
    private volatile IMediaStreamService service;
    private volatile boolean bound;
    private volatile boolean imageCallbackRegistered;
    private volatile boolean viewOpen;
    private volatile long viewGeneration;
    private volatile String viewPurpose = "none";
    private volatile BindingConnection connection;
    private volatile CallbackSet callbacks;

    public RokidGlobalLink(Context context, Listener listener) {
        this.context = context.getApplicationContext();
        this.listener = listener;
        captureLinks = new CaptureLinkCoordinator(
                () -> photoInFlight.set(false),
                listener::onCaptureLinkStateChanged);
    }

    public static boolean isGlobalHiRokidInstalled(Context context) {
        try {
            context.getPackageManager().getPackageInfo(GLOBAL_PACKAGE, 0);
            return true;
        } catch (PackageManager.NameNotFoundException ignored) {
            return false;
        }
    }

    public static Intent authorizationIntent(Context context) {
        Intent byAction = new Intent(AUTH_ACTION).setPackage(GLOBAL_PACKAGE);
        if (byAction.resolveActivity(context.getPackageManager()) != null) {
            return byAction;
        }
        return new Intent().setComponent(new ComponentName(GLOBAL_PACKAGE, AUTH_ACTIVITY));
    }

    public static String authorizationToken(int resultCode, Intent data) {
        if (data == null) {
            return null;
        }
        String token = data.getStringExtra(EXTRA_AUTH_TOKEN);
        int authResult = data.getIntExtra(EXTRA_AUTH_RESULT, -1);
        if (token == null || token.trim().isEmpty()) {
            return null;
        }
        // Known Global builds return RESULT_OK + 2001. Some builds omit the
        // private result marker but still return a token; accept that only when
        // the Android activity result itself is successful.
        if (authResult == AUTH_SUCCESS || resultCode == Activity.RESULT_OK) {
            return token;
        }
        return null;
    }

    public synchronized boolean connect(String token) {
        if (token == null || token.isEmpty()) {
            listener.onError("Hi Rokidの認可トークンが空です", null);
            return false;
        }
        if (bound) {
            return true;
        }
        Intent intent = new Intent(MEDIA_ACTION)
                .setPackage(GLOBAL_PACKAGE)
                .putExtra(EXTRA_AUTH_TOKEN, token)
                .putExtra(EXTRA_AUTH_PACKAGE, context.getPackageName());
        long bindingEpoch = bindingEpochs.begin();
        BindingConnection candidate = new BindingConnection(bindingEpoch);
        connection = candidate;
        // Mark the candidate current before bindService: Android normally
        // delivers onServiceConnected asynchronously, but this also keeps a
        // synchronous test/future implementation from being rejected.
        bound = true;
        try {
            boolean didBind = context.bindService(
                    intent, candidate, Context.BIND_AUTO_CREATE);
            if (!didBind) {
                bound = false;
                connection = null;
                bindingEpochs.invalidate(bindingEpoch);
            }
        } catch (RuntimeException error) {
            bound = false;
            connection = null;
            bindingEpochs.invalidate(bindingEpoch);
            listener.onError("Hi Rokid MediaStreamServiceへの接続に失敗しました", error);
            return false;
        }
        if (!bound) {
            listener.onError(
                    "Hi Rokid MediaStreamServiceが見つかりません。Global版アプリと<queries>を確認してください",
                    null);
        }
        return bound;
    }

    public synchronized PhotoStartResult takePhoto(int width, int height, int quality) {
        IMediaStreamService current = service;
        if (current == null) {
            listener.onError("Rokidサービス未接続のため撮影できません", null);
            return PhotoStartResult.REJECTED;
        }
        if (!imageCallbackRegistered) {
            listener.onError("写真コールバック未登録のため撮影を安全停止しました", null);
            return PhotoStartResult.REJECTED;
        }
        if (!photoInFlight.compareAndSet(false, true)) {
            listener.onError("前回の撮影結果が未着のため重複撮影を拒否しました", null);
            return PhotoStartResult.REJECTED;
        }
        try {
            Log.i(TAG, "takePhoto request: " + width + "x" + height + " q" + quality);
            boolean started = current.takePhoto(width, height, quality);
            if (!started) {
                photoInFlight.set(false);
                return PhotoStartResult.REJECTED;
            }
            return PhotoStartResult.STARTED;
        } catch (Exception error) {
            // A Binder failure can happen after the remote process accepted
            // the request but before its boolean reply reached this process.
            // Keep the guard held until a terminal callback or real reconnect.
            listener.onError("Rokid Glassesの撮影要求に失敗しました", error);
            return PhotoStartResult.UNKNOWN;
        }
    }

    public synchronized long showHud(List<String> lines) {
        IMediaStreamService current = service;
        if (current == null) {
            return NO_VIEW_GENERATION;
        }
        try {
            return replaceCustomView(current, HudLayout.fromLines(lines), "hud");
        } catch (Exception error) {
            listener.onError("HUD更新に失敗しました", error);
            return NO_VIEW_GENERATION;
        }
    }

    /**
     * Returns the service's current CustomView state for recovery decisions.
     * A false result is fail-closed: callers may attempt one normal reopen,
     * whose own request and acknowledgement are still generation-gated.
     */
    public synchronized boolean isCustomViewActuallyOpen() {
        IMediaStreamService current = service;
        if (current == null) {
            return false;
        }
        try {
            return current.isCustomViewOpened();
        } catch (Exception error) {
            Log.w(TAG, "could not query current CustomView state", error);
            return false;
        }
    }

    public synchronized long showCaptureAiming(
            int pageNumber,
            boolean retake,
            boolean stabilizing
    ) {
        IMediaStreamService current = service;
        if (current == null) {
            return NO_VIEW_GENERATION;
        }
        try {
            return replaceCustomView(
                    current,
                    HudLayout.fromCaptureAiming(pageNumber, retake, stabilizing),
                    stabilizing ? "capture-stabilizing" : "capture-aiming");
        } catch (Exception error) {
            listener.onError("撮影ガイドの表示に失敗しました", error);
            return NO_VIEW_GENERATION;
        }
    }

    public synchronized long showCaptureReview(
            byte[] jpeg,
            int rotationDegrees,
            List<String> lines
    ) {
        IMediaStreamService current = service;
        if (current == null) {
            return NO_VIEW_GENERATION;
        }
        try {
            if (current.isCustomViewOpened()) {
                closeCustomViewProgrammatically(current);
            }
            String icons = GlassesCapturePreview.iconJson(jpeg, rotationDegrees);
            if (!current.setIcons(icons)) {
                throw new IllegalStateException("setIcons returned false");
            }
            long generation = requestCustomView(
                    current,
                    HudLayout.fromCaptureReview(GlassesCapturePreview.ICON_NAME, lines),
                    "capture-review");
            Log.i(
                    TAG,
                    "capture review preview requested on glasses generation="
                            + generation);
            return generation;
        } catch (Exception error) {
            Log.w(TAG, "capture review image failed; falling back to text HUD", error);
            long fallbackGeneration = NO_VIEW_GENERATION;
            try {
                fallbackGeneration = replaceCustomView(
                        current,
                        HudLayout.fromLines(lines),
                        "capture-review-text");
            } catch (Exception fallbackError) {
                error.addSuppressed(fallbackError);
            }
            listener.onError(
                    "グラスに撮影プレビューを表示できないため文字案内へ切り替えました",
                    error);
            return fallbackGeneration;
        }
    }

    private long replaceCustomView(
            IMediaStreamService current,
            String layout,
            String purpose
    ) throws Exception {
        // client-l 1.0.1 / current Global Hi Rokid acknowledges update but
        // does not always redraw. Re-open is the verified fallback.
        if (current.isCustomViewOpened()) {
            closeCustomViewProgrammatically(current);
        }
        return requestCustomView(current, layout, purpose);
    }

    private long requestCustomView(
            IMediaStreamService current,
            String layout,
            String purpose
    ) throws Exception {
        if (customViewOpens.isFaulted()) {
            throw new IllegalStateException(
                    "CustomView callbacks are fenced; Hi Rokid再認可・再接続が必要です");
        }
        long generation = customViewOpens.requestOpen();
        viewGeneration = generation;
        viewPurpose = purpose;
        viewOpen = false;
        viewPurposes.put(generation, purpose);
        boolean accepted;
        try {
            accepted = current.openCustomView(layout);
        } catch (Exception error) {
            customViewOpens.rejectOpen(generation);
            viewPurposes.remove(generation);
            throw error;
        }
        if (!accepted) {
            customViewOpens.rejectOpen(generation);
            viewPurposes.remove(generation);
            throw new IllegalStateException("openCustomView returned false");
        }
        Log.i(
                TAG,
                "custom view requested generation=" + generation
                        + " purpose=" + purpose);
        return generation;
    }

    public synchronized void closeHud() {
        IMediaStreamService current = service;
        if (current == null) {
            return;
        }
        try {
            if (current.isCustomViewOpened()) {
                closeCustomViewProgrammatically(current);
            }
        } catch (Exception error) {
            Log.w(TAG, "closeCustomView failed", error);
        } finally {
            viewOpen = false;
            customViewOpens.onCurrentClosed();
        }
    }

    private final class CallbackSet {
        private final IDeviceStatusCallback deviceStatus;
        private final IImageStreamCallback imageStream;
        private final IAiEventCallback aiEvents;
        private final ICustomViewCallback customView;

        CallbackSet(long epoch) {
            deviceStatus = new IDeviceStatusCallback.Stub() {
                @Override
                public void onDeviceConnectChanged(boolean connected) {
                    dispatchCallback(
                            epoch,
                            "device-status",
                            () -> glassesStatusChanged(connected));
                }
            };
            imageStream = new IImageStreamCallback.Stub() {
                @Override
                public void onImageReceived(byte[] data) {
                    // Logged before the in-flight check so a duplicate or late
                    // frame is still measurable: the payload size is what tells
                    // a capture sweep whether the Binder budget was the limit.
                    int received = data == null ? 0 : data.length;
                    Log.i(
                            TAG,
                            "Photo callback: " + received + " bytes ("
                                    + Math.round(received * 100.0
                                            / CaptureDiagnostics.ASYNC_BINDER_BUDGET_BYTES)
                                    + "% of the async Binder budget)");
                    dispatchCallback(epoch, "image", () -> {
                        if (!photoInFlight.compareAndSet(true, false)) {
                            return;
                        }
                        if (data == null || data.length == 0) {
                            listener.onPhotoError(
                                    "グラスから空の写真が返されました", null);
                            return;
                        }
                        listener.onPhoto(Arrays.copyOf(data, data.length));
                    });
                }

                @Override
                public void onImageError(int code, String message) {
                    dispatchCallback(epoch, "image-error", () -> {
                        if (!photoInFlight.compareAndSet(true, false)) {
                            return;
                        }
                        listener.onPhotoError(
                                "グラス撮影エラー " + code + ": " + message, null);
                    });
                }
            };
            aiEvents = new IAiEventCallback.Stub() {
                @Override
                public void onAiKeyDown() {
                    dispatchCallback(epoch, "AI-key-down", () -> {
                        Log.i(
                                TAG,
                                "AI-key-down epoch=" + epoch
                                        + " elapsed=" + SystemClock.elapsedRealtime()
                                        + " viewGeneration=" + viewGeneration
                                        + " purpose=" + viewPurpose);
                        IMediaStreamService current = service;
                        if (current == null) {
                            listener.onError(
                                    "AI長押しを安全に終了できないため操作を中止しました",
                                    null);
                            return;
                        }
                        final boolean exitAccepted;
                        try {
                            exitAccepted = current.sendExit(false);
                            Log.i(
                                    TAG,
                                    "sendExit(false) before LONG dispatch returned "
                                            + exitAccepted);
                        } catch (Exception error) {
                            Log.w(TAG, "sendExit(false) failed", error);
                            listener.onError(
                                    "AI長押しの終了確認に失敗したため操作を中止しました",
                                    error);
                            return;
                        }
                        if (!exitAccepted) {
                            listener.onError(
                                    "AI長押しの終了が拒否されたため操作を中止しました",
                                    null);
                            return;
                        }
                        // Match client-l 1.0.1's ExternalAppClient ordering:
                        // leave AI assist before the app mutates/reopens its HUD.
                        listener.onAiPressDown();
                    });
                }

                @Override
                public void onAiKeyUp() {
                    dispatchCallback(epoch, "AI-key-up", () -> {
                        Log.i(
                                TAG,
                                "AI-key-up epoch=" + epoch
                                        + " elapsed=" + SystemClock.elapsedRealtime()
                                        + " viewGeneration=" + viewGeneration
                                        + " purpose=" + viewPurpose);
                        listener.onAiPressUp();
                    });
                }

                @Override
                public void onAiExit() {
                    dispatchCallback(epoch, "AI-exit", () -> {
                        Log.i(
                                TAG,
                                "AI-exit epoch=" + epoch
                                        + " elapsed=" + SystemClock.elapsedRealtime()
                                        + " viewGeneration=" + viewGeneration
                                        + " purpose=" + viewPurpose);
                        listener.onAiExit();
                    });
                }

                @Override
                public void onGlassAppResumeChange(String from, String to) {
                    // No glasses-side custom APK is installed in CUSTOMVIEW mode.
                }
            };
            customView = new ICustomViewCallback.Stub() {
                @Override
                public void onCustomViewOpened() {
                    dispatchCallback(
                            epoch,
                            "custom-view-open",
                            () -> handleCustomViewOpened(epoch));
                }

                @Override
                public void onCustomViewUpdated() {
                    dispatchCallback(
                            epoch,
                            "custom-view-update",
                            () -> handleCustomViewUpdated(epoch));
                }

                @Override
                public void onCustomViewClosed() {
                    dispatchCallback(
                            epoch,
                            "custom-view-close",
                            () -> handleCustomViewClosed(epoch));
                }

                @Override
                public void onCustomViewIconsSent() {
                    dispatchCallback(
                            epoch,
                            "custom-view-icons",
                            () -> Log.i(TAG, "custom view icons sent to glasses"));
                }

                @Override
                public void onCustomViewError(int code, String message) {
                    dispatchCallback(
                            epoch,
                            "custom-view-error",
                            () -> handleCustomViewError(code, message));
                }
            };
        }
    }

    private void closeCustomViewProgrammatically(IMediaStreamService current)
            throws Exception {
        customViewCloses.expectProgrammaticClose(
                SystemClock.elapsedRealtime(),
                viewGeneration);
        final boolean accepted;
        try {
            accepted = current.closeCustomView();
        } catch (Exception error) {
            customViewCloses.cancelLatestExpectation();
            customViewOpens.fault();
            throw error;
        }
        if (!accepted) {
            customViewCloses.cancelLatestExpectation();
            customViewOpens.fault();
            throw new IllegalStateException("closeCustomView returned false");
        }
        viewOpen = false;
        customViewOpens.onCurrentClosed();
    }

    private synchronized void handleCustomViewOpened(long epoch) {
        if (customViewOpens.isFaulted()) {
            Log.i(TAG, "ignored CustomView open from a fenced callback epoch=" + epoch);
            return;
        }
        long openedGeneration = customViewOpens.onOpened();
        if (openedGeneration == CustomViewOpenTracker.NONE) {
            Log.i(TAG, "unexpected CustomView open callback epoch=" + epoch);
            return;
        }
        String purpose = viewPurposes.remove(openedGeneration);
        if (purpose == null) {
            purpose = "unknown";
        }
        if (!customViewOpens.isCurrentAcknowledged(openedGeneration)) {
            Log.i(
                    TAG,
                    "stale custom view open acknowledged epoch=" + epoch
                            + " generation=" + openedGeneration
                            + " purpose=" + purpose
                            + " currentGeneration=" + viewGeneration);
            return;
        }
        IMediaStreamService current = service;
        boolean remoteOpen;
        try {
            remoteOpen = current != null && current.isCustomViewOpened();
        } catch (Exception error) {
            customViewOpens.onError();
            notifyCurrentViewFailed(
                    openedGeneration,
                    purpose,
                    "CustomView open acknowledgement could not be verified",
                    error);
            return;
        }
        if (!remoteOpen) {
            customViewOpens.onError();
            notifyCurrentViewFailed(
                    openedGeneration,
                    purpose,
                    "CustomView closed before its open acknowledgement",
                    null);
            return;
        }
        viewOpen = true;
        viewPurpose = purpose;
        Log.i(
                TAG,
                "custom view opened on glasses epoch=" + epoch
                        + " generation=" + openedGeneration
                        + " purpose=" + purpose);
        listener.onCustomViewAvailable(openedGeneration, purpose);
    }

    private synchronized void handleCustomViewUpdated(long epoch) {
        if (customViewOpens.isFaulted()) {
            Log.i(TAG, "ignored CustomView update from a fenced callback epoch=" + epoch);
            return;
        }
        if (!customViewOpens.isCurrentAcknowledged()) {
            Log.i(
                    TAG,
                    "CustomView update ignored before current open acknowledgement epoch="
                            + epoch);
            return;
        }
        viewOpen = true;
        Log.i(
                TAG,
                "custom view updated on glasses epoch=" + epoch
                        + " generation=" + viewGeneration
                        + " purpose=" + viewPurpose);
        listener.onCustomViewAvailable(viewGeneration, viewPurpose);
    }

    private synchronized void handleCustomViewClosed(long epoch) {
        if (customViewOpens.isFaulted()) {
            Log.i(TAG, "ignored CustomView close from a fenced callback epoch=" + epoch);
            return;
        }
        long now = SystemClock.elapsedRealtime();
        boolean localViewWasOpen =
                viewOpen && customViewOpens.isCurrentAcknowledged();
        boolean remoteStillOpen = false;
        IMediaStreamService current = service;
        if (current != null) {
            try {
                remoteStillOpen = current.isCustomViewOpened();
            } catch (Exception error) {
                Log.w(TAG, "could not query CustomView after close callback", error);
                viewOpen = false;
                customViewOpens.onCurrentClosed();
                customViewCloses.reset();
                notifyCurrentViewFailed(
                        viewGeneration,
                        viewPurpose,
                        "グラス画面の終了状態を確認できなかったため操作を受け付けません",
                        error);
                return;
            }
        }
        boolean userInitiated = customViewCloses.onClosed(
                now,
                viewGeneration,
                remoteStillOpen,
                localViewWasOpen);
        viewOpen = remoteStillOpen;
        if (!remoteStillOpen) {
            customViewOpens.onCurrentClosed();
        }
        Log.i(
                TAG,
                "custom view closed on glasses epoch=" + epoch
                        + " elapsed=" + now
                        + " generation=" + viewGeneration
                        + " purpose=" + viewPurpose
                        + " userInitiated=" + userInitiated
                        + " remoteStillOpen=" + remoteStillOpen);
        if (userInitiated && !remoteStillOpen) {
            listener.onCustomViewClosedByUser();
        }
    }

    private synchronized void handleCustomViewError(int code, String message) {
        if (customViewOpens.isFaulted()) {
            Log.i(TAG, "ignored CustomView error from a fenced callback epoch");
            return;
        }
        long failedGeneration = customViewOpens.onError();
        if (failedGeneration == CustomViewOpenTracker.NONE) {
            Log.w(TAG, "CustomView error without a tracked view: " + code + ": " + message);
            return;
        }
        String failedPurpose = viewPurposes.remove(failedGeneration);
        if (failedPurpose == null) {
            failedPurpose = failedGeneration == viewGeneration
                    ? viewPurpose
                    : "unknown";
        }
        if (failedGeneration != viewGeneration) {
            Log.w(
                    TAG,
                    "stale CustomView error generation=" + failedGeneration
                            + " purpose=" + failedPurpose
                            + " currentGeneration=" + viewGeneration
                            + ": " + code + ": " + message);
            return;
        }
        notifyCurrentViewFailed(
                failedGeneration,
                failedPurpose,
                "HUDエラー " + code + ": " + message,
                null);
    }

    private void notifyCurrentViewFailed(
            long generation,
            String purpose,
            String message,
            Throwable cause
    ) {
        viewOpen = false;
        viewPurpose = "error";
        customViewCloses.reset();
        customViewOpens.fault();
        viewPurposes.clear();
        listener.onCustomViewFailed(generation, purpose, message, cause);
        listener.onError(message, cause);
    }

    /**
     * Retires an ambiguous callback stream after an acknowledgement timeout.
     * No later view request is accepted until a real service rebind installs
     * fresh callback stubs.
     */
    public synchronized void fenceCustomViewEpoch(
            long generation,
            String reason
    ) {
        if (generation != viewGeneration || customViewOpens.isFaulted()) {
            return;
        }
        viewOpen = false;
        viewPurpose = "fenced";
        customViewCloses.reset();
        customViewOpens.fault();
        viewPurposes.clear();
        listener.onError(
                reason + "。Hi Rokid認可・再接続が必要です",
                null);
    }

    private final class BindingConnection implements ServiceConnection {
        private final long epoch;

        BindingConnection(long epoch) {
            this.epoch = epoch;
        }

        @Override
        public void onServiceConnected(ComponentName name, IBinder binder) {
            handleServiceConnected(this, binder);
        }

        @Override
        public void onServiceDisconnected(ComponentName name) {
            handleServiceDisconnected(this);
        }
    }

    private void handleServiceConnected(BindingConnection source, IBinder binder) {
        long callbackEpoch;
        synchronized (this) {
            if (!bound
                    || connection != source
                    || !bindingEpochs.isCurrent(source.epoch)
                    || service != null) {
                return;
            }
            callbackEpoch = callbackEpochs.begin();
        }

        IMediaStreamService connected = IMediaStreamService.Stub.asInterface(binder);
        CallbackSet candidate = new CallbackSet(callbackEpoch);
        logServiceIdentity(connected);
        try {
            boolean callbacksReady =
                    connected.registerDeviceStatusCallback(candidate.deviceStatus)
                            && connected.registerImageCallback(candidate.imageStream)
                            && connected.registerCustomViewCallback(candidate.customView)
                            && connected.registAiEventCallback(candidate.aiEvents);
            if (!callbacksReady) {
                throw new IllegalStateException(
                        "one or more required CXR-L callbacks were rejected");
            }
            boolean glassesConnected = connected.isDeviceConnected();
            boolean installed;
            synchronized (this) {
                installed =
                        bound
                                && connection == source
                                && bindingEpochs.isCurrent(source.epoch)
                                && callbackEpochs.activate(callbackEpoch);
                if (installed) {
                    service = connected;
                    callbacks = candidate;
                    imageCallbackRegistered = true;
                    viewOpen = false;
                    viewPurpose = "none";
                    customViewCloses.reset();
                    customViewOpens.reset();
                    viewPurposes.clear();
                    listener.onLinkConnected(true);
                    serviceBindingReset(glassesConnected);
                }
            }
            if (!installed) {
                callbackEpochs.invalidate(callbackEpoch);
                unregisterCallbacks(connected, candidate);
            }
        } catch (Exception error) {
            unregisterCallbacks(connected, candidate);
            failCallbackRegistration(source, callbackEpoch, error);
        }
    }

    /**
     * Records which CXR-L build answered the bind.
     *
     * <p>Capture behaviour is firmware-dependent, so a sweep result is only
     * reproducible if the service build that produced it is known. Failures are
     * swallowed: this is measurement, and it must never keep a working link
     * from being established.</p>
     */
    private void logServiceIdentity(IMediaStreamService connected) {
        String version = null;
        int versionCode = 0;
        try {
            version = connected.getServiceVersion();
            versionCode = connected.getServiceVersionCode();
        } catch (Exception error) {
            Log.w(TAG, "CXR-L service version unavailable", error);
        }
        serviceIdentity = CaptureDiagnostics.serviceIdentity(version, versionCode);
        Log.i(TAG, serviceIdentity);
    }

    /**
     * The CXR-L build that answered the most recent bind.
     *
     * <p>Exposed rather than only logged because a real-device session is run
     * without adb attached, and the service build has to be recorded alongside
     * the capture results for them to mean anything later.</p>
     */
    public String serviceIdentity() {
        return serviceIdentity;
    }

    private void failCallbackRegistration(
            BindingConnection source,
            long callbackEpoch,
            Exception error
    ) {
        boolean failedCurrentBinding = false;
        synchronized (this) {
            if (connection == source
                    && bindingEpochs.isCurrent(source.epoch)
                    && callbackEpochs.isCurrent(callbackEpoch)) {
                callbackEpochs.invalidate(callbackEpoch);
                bindingEpochs.invalidate(source.epoch);
                service = null;
                callbacks = null;
                connection = null;
                bound = false;
                imageCallbackRegistered = false;
                serviceBindingReset(false);
                viewOpen = false;
                viewPurpose = "none";
                customViewCloses.reset();
                customViewOpens.reset();
                viewPurposes.clear();
                failedCurrentBinding = true;
                listener.onLinkConnected(false);
                listener.onError("Rokidコールバック登録に失敗しました", error);
            }
        }
        if (!failedCurrentBinding) {
            return;
        }
        try {
            context.unbindService(source);
        } catch (RuntimeException cleanupError) {
            Log.w(TAG, "unbind after callback registration failure failed", cleanupError);
        }
    }

    private void handleServiceDisconnected(BindingConnection source) {
        synchronized (this) {
            if (connection != source || !bindingEpochs.isCurrent(source.epoch)) {
                return;
            }
            callbackEpochs.invalidateCurrent();
            service = null;
            callbacks = null;
            imageCallbackRegistered = false;
            serviceBindingReset(false);
            viewOpen = false;
            viewPurpose = "none";
            customViewCloses.reset();
            customViewOpens.reset();
            viewPurposes.clear();
            listener.onLinkConnected(false);
        }
    }

    private void dispatchCallback(long epoch, String name, Runnable action) {
        if (!callbackEpochs.runIfActive(epoch, action)) {
            Log.i(TAG, "ignored stale " + name + " callback epoch=" + epoch);
        }
    }

    private void glassesStatusChanged(boolean connected) {
        Log.i(
                TAG,
                "capture link ready=" + connected
                        + " event=" + CaptureLinkEvent.GLASSES_STATUS_CHANGED);
        captureLinks.glassesStatusChanged(connected);
    }

    private void serviceBindingReset(boolean connected) {
        Log.i(
                TAG,
                "capture link ready=" + connected
                        + " event=" + CaptureLinkEvent.SERVICE_BINDING_RESET);
        captureLinks.serviceBindingReset(connected);
    }

    private void unregisterCallbacks(
            IMediaStreamService current,
            CallbackSet registered
    ) {
        try {
            current.unregisterDeviceStatusCallback(registered.deviceStatus);
        } catch (Exception error) {
            Log.w(TAG, "device-status callback cleanup failed", error);
        }
        try {
            current.unregisterImageCallback(registered.imageStream);
        } catch (Exception error) {
            Log.w(TAG, "image callback cleanup failed", error);
        }
        try {
            current.unregisterCustomViewCallback(registered.customView);
        } catch (Exception error) {
            Log.w(TAG, "custom-view callback cleanup failed", error);
        }
        try {
            current.unregistAiEventCallback(registered.aiEvents);
        } catch (Exception error) {
            Log.w(TAG, "AI-event callback cleanup failed", error);
        }
    }

    @Override
    public void close() {
        IMediaStreamService current;
        CallbackSet registered;
        BindingConnection activeConnection;
        boolean wasBound;
        synchronized (this) {
            current = service;
            registered = callbacks;
            activeConnection = connection;
            wasBound = bound;
            bindingEpochs.invalidateCurrent();
            callbackEpochs.invalidateCurrent();
            service = null;
            callbacks = null;
            connection = null;
            bound = false;
            imageCallbackRegistered = false;
            serviceBindingReset(false);
            viewOpen = false;
            viewPurpose = "none";
            customViewCloses.reset();
            customViewOpens.reset();
            viewPurposes.clear();
        }
        if (current != null && registered != null) {
            unregisterCallbacks(current, registered);
        }
        if (wasBound && activeConnection != null) {
            try {
                context.unbindService(activeConnection);
            } catch (RuntimeException error) {
                Log.w(TAG, "unbindService failed", error);
            }
        }
    }
}
