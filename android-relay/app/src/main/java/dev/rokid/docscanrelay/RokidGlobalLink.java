package dev.rokid.docscanrelay;

import android.app.Activity;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.content.pm.PackageManager;
import android.os.IBinder;
import android.util.Log;

import com.rokid.sprite.aiapp.externalapp.IAiEventCallback;
import com.rokid.sprite.aiapp.externalapp.ICustomViewCallback;
import com.rokid.sprite.aiapp.externalapp.IDeviceStatusCallback;
import com.rokid.sprite.aiapp.externalapp.IImageStreamCallback;
import com.rokid.sprite.aiapp.externalapp.IMediaStreamService;

import java.util.Arrays;
import java.util.List;
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
    public interface Listener {
        void onLinkConnected(boolean connected);

        void onCaptureLinkStateChanged(boolean connected, CaptureLinkEvent event);

        void onAiPressDown();

        void onAiPressUp();

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

    private final Context context;
    private final Listener listener;
    private final AtomicBoolean photoInFlight = new AtomicBoolean();
    private final CaptureLinkCoordinator captureLinks;
    private final LinkEpoch bindingEpochs = new LinkEpoch();
    private final LinkEpoch callbackEpochs = new LinkEpoch();
    private volatile IMediaStreamService service;
    private volatile boolean bound;
    private volatile boolean imageCallbackRegistered;
    private volatile boolean viewOpen;
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

    public synchronized void showHud(List<String> lines) {
        IMediaStreamService current = service;
        if (current == null) {
            return;
        }
        String layout = HudLayout.fromLines(lines);
        try {
            // client-l 1.0.1 / current Global Hi Rokid acknowledges update but
            // does not always redraw. Re-open on a black background is the
            // verified fallback. No white frame is emitted by this app.
            if (viewOpen || current.isCustomViewOpened()) {
                current.closeCustomView();
            }
            viewOpen = current.openCustomView(layout);
        } catch (Exception error) {
            listener.onError("HUD更新に失敗しました", error);
        }
    }

    public synchronized void closeHud() {
        IMediaStreamService current = service;
        if (current == null) {
            return;
        }
        try {
            current.closeCustomView();
        } catch (Exception error) {
            Log.w(TAG, "closeCustomView failed", error);
        } finally {
            viewOpen = false;
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
                    dispatchCallback(epoch, "AI-key-down", listener::onAiPressDown);
                }

                @Override
                public void onAiKeyUp() {
                    dispatchCallback(epoch, "AI-key-up", listener::onAiPressUp);
                }

                @Override
                public void onAiExit() {
                    dispatchCallback(epoch, "AI-exit", listener::onAiPressUp);
                }

                @Override
                public void onGlassAppResumeChange(String from, String to) {
                    // No glasses-side custom APK is installed in CUSTOMVIEW mode.
                }
            };
            customView = new ICustomViewCallback.Stub() {
                @Override
                public void onCustomViewOpened() {
                    dispatchCallback(epoch, "custom-view-open", () -> viewOpen = true);
                }

                @Override
                public void onCustomViewUpdated() {
                    dispatchCallback(epoch, "custom-view-update", () -> viewOpen = true);
                }

                @Override
                public void onCustomViewClosed() {
                    dispatchCallback(epoch, "custom-view-close", () -> viewOpen = false);
                }

                @Override
                public void onCustomViewIconsSent() {
                }

                @Override
                public void onCustomViewError(int code, String message) {
                    dispatchCallback(
                            epoch,
                            "custom-view-error",
                            () -> listener.onError(
                                    "HUDエラー " + code + ": " + message,
                                    null));
                }
            };
        }
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
