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

        void onGlassesConnected(boolean connected);

        void onAiPressDown();

        void onAiPressUp();

        void onPhoto(byte[] jpeg);

        void onPhotoError(String message, Throwable cause);

        void onError(String message, Throwable cause);
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
    private IMediaStreamService service;
    private boolean bound;
    private volatile boolean viewOpen;

    public RokidGlobalLink(Context context, Listener listener) {
        this.context = context.getApplicationContext();
        this.listener = listener;
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
        try {
            bound = context.bindService(intent, connection, Context.BIND_AUTO_CREATE);
        } catch (RuntimeException error) {
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

    public synchronized boolean takePhoto(int width, int height, int quality) {
        IMediaStreamService current = service;
        if (current == null) {
            listener.onError("Rokidサービス未接続のため撮影できません", null);
            return false;
        }
        try {
            return current.takePhoto(width, height, quality);
        } catch (Exception error) {
            listener.onError("Rokid Glassesの撮影要求に失敗しました", error);
            return false;
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

    private final IDeviceStatusCallback deviceStatus = new IDeviceStatusCallback.Stub() {
        @Override
        public void onDeviceConnectChanged(boolean connected) {
            listener.onGlassesConnected(connected);
        }
    };

    private final IImageStreamCallback imageStream = new IImageStreamCallback.Stub() {
        @Override
        public void onImageReceived(byte[] data) {
            if (data == null || data.length == 0) {
                listener.onPhotoError("グラスから空の写真が返されました", null);
                return;
            }
            listener.onPhoto(Arrays.copyOf(data, data.length));
        }

        @Override
        public void onImageError(int code, String message) {
            listener.onPhotoError("グラス撮影エラー " + code + ": " + message, null);
        }
    };

    private final IAiEventCallback aiEvents = new IAiEventCallback.Stub() {
        @Override
        public void onAiKeyDown() {
            listener.onAiPressDown();
        }

        @Override
        public void onAiKeyUp() {
            listener.onAiPressUp();
        }

        @Override
        public void onAiExit() {
            listener.onAiPressUp();
        }

        @Override
        public void onGlassAppResumeChange(String from, String to) {
            // No glasses-side custom APK is installed in CUSTOMVIEW mode.
        }
    };

    private final ICustomViewCallback customView = new ICustomViewCallback.Stub() {
        @Override
        public void onCustomViewOpened() {
            viewOpen = true;
        }

        @Override
        public void onCustomViewUpdated() {
            viewOpen = true;
        }

        @Override
        public void onCustomViewClosed() {
            viewOpen = false;
        }

        @Override
        public void onCustomViewIconsSent() {
        }

        @Override
        public void onCustomViewError(int code, String message) {
            listener.onError("HUDエラー " + code + ": " + message, null);
        }
    };

    private final ServiceConnection connection = new ServiceConnection() {
        @Override
        public void onServiceConnected(ComponentName name, IBinder binder) {
            IMediaStreamService connected = IMediaStreamService.Stub.asInterface(binder);
            service = connected;
            try {
                connected.registerDeviceStatusCallback(deviceStatus);
                connected.registerImageCallback(imageStream);
                connected.registerCustomViewCallback(customView);
                connected.registAiEventCallback(aiEvents);
                listener.onLinkConnected(true);
                listener.onGlassesConnected(connected.isDeviceConnected());
            } catch (Exception error) {
                listener.onError("Rokidコールバック登録に失敗しました", error);
            }
        }

        @Override
        public void onServiceDisconnected(ComponentName name) {
            service = null;
            viewOpen = false;
            listener.onLinkConnected(false);
            listener.onGlassesConnected(false);
        }
    };

    @Override
    public synchronized void close() {
        IMediaStreamService current = service;
        if (current != null) {
            try {
                current.unregisterDeviceStatusCallback(deviceStatus);
                current.unregisterImageCallback(imageStream);
                current.unregisterCustomViewCallback(customView);
                current.unregistAiEventCallback(aiEvents);
            } catch (Exception error) {
                Log.w(TAG, "callback cleanup failed", error);
            }
        }
        if (bound) {
            try {
                context.unbindService(connection);
            } catch (RuntimeException error) {
                Log.w(TAG, "unbindService failed", error);
            }
        }
        service = null;
        bound = false;
        viewOpen = false;
    }
}
