package dev.rokid.docscanglass.doc;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.provider.Settings;
import android.util.Log;
import dev.rokid.docscanrelay.DocScanApi;
import dev.rokid.docscanrelay.ClientIdentity;
import java.io.File;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Proximity-only residency. The trusted phone watcher opens the UI; this service never does. */
public final class WearService extends Service {
    static final String COLD_BOOT = "cold_boot";
    private static final String CHANNEL = "docscan-wear";
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService network = Executors.newSingleThreadExecutor();
    private PowerState state;
    private WearWatch watch;
    private long coldGeneration = -1;
    private volatile boolean destroyed;
    private ConnectionSettings settings;

    @Override public void onCreate() {
        super.onCreate();
        state = PowerState.forContext(this);
        settings = new ConnectionSettings(new File(getNoBackupFilesDir(), "connection.bin"));
        NotificationManager notifications = getSystemService(NotificationManager.class);
        notifications.createNotificationChannel(new NotificationChannel(CHANNEL, "装着待機", NotificationManager.IMPORTANCE_LOW));
        Notification notification = new Notification.Builder(this, CHANNEL).setSmallIcon(android.R.drawable.ic_menu_view)
                .setContentTitle("DocScan 装着待機").setContentText("装着すると最初の画面を開きます")
                .setOngoing(true).build();
        startForeground(7404, notification, Build.VERSION.SDK_INT >= 34 ? ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE : 0);
        watch = new WearWatch(this, this::wornAgain);
        if (!watch.start()) {
            Log.w("DocScanWear", "wakeup proximity unavailable; wear entry unsupported");
            stopSelf();
        }
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && intent.getBooleanExtra(COLD_BOOT, false)) coldGeneration = intent.getLongExtra("cold_generation", -1);
        return START_NOT_STICKY; // a process restart while still worn must not reopen a completed run
    }

    private void wornAgain(boolean initial) {
        try {
            PowerState.Snapshot entry = state.wear(initial, coldGeneration);
            coldGeneration = -1;
            if (entry != null) transmit(entry);
        } catch (Exception error) { Log.w("DocScanWear", "wear entry not saved: " + error.getClass().getSimpleName()); }
    }

    private void transmit(PowerState.Snapshot entry) {
        if (destroyed) return;
        network.execute(() -> {
            if (destroyed || state.load().generation != entry.generation) return;
            PowerManager power = getSystemService(PowerManager.class);
            PowerManager.WakeLock lock = power == null ? null : power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "docscan:wear-notify");
            try {
                if (lock != null) lock.acquire(5_000);
                ConnectionSettings.Saved connection = settings.load();
                if (connection == null) throw new java.io.IOException("connection unavailable");
                String device = Settings.Secure.getString(getContentResolver(), Settings.Secure.ANDROID_ID);
                if (device == null || device.isEmpty()) device = PowerState.preferencesForContext(this).getString("device_id", "");
                if (device == null || device.isEmpty()) throw new java.io.IOException("device identity unavailable");
                DocScanApi api = new DocScanApi(connection.server, connection.key,
                        new ClientIdentity("rokid-glasses-camera2", "glassdoc/" + BuildConfig.VERSION_NAME, "camera2/no-cxr"), this);
                api.glassesState(device, null, entry.generation, entry.sequence, "chooser", "wake", "chooser");
            } catch (Exception error) {
                Log.w("DocScanWear", "wear notification paused: " + error.getClass().getSimpleName());
                main.postDelayed(() -> { if (!destroyed && state.load().generation == entry.generation) transmit(entry); }, 5_000);
            } finally { if (lock != null && lock.isHeld()) lock.release(); }
        });
    }

    @Override public void onDestroy() {
        destroyed = true;
        main.removeCallbacksAndMessages(null);
        if (watch != null) watch.stop();
        network.shutdown();
        super.onDestroy();
    }
    @Override public IBinder onBind(Intent intent) { return null; }
}
