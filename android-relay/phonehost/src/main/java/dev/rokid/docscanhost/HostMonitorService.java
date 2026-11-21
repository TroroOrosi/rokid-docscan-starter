package dev.rokid.docscanhost;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;
import android.provider.Settings;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

public class HostMonitorService extends Service {
    private static final String CHANNEL = "host-runtime";
    private static final int NOTIFICATION = 1;
    private final Handler main = new Handler(Looper.getMainLooper());
    private HostPreferences store;
    private HostMonitor monitor;
    private ScheduledExecutorService worker;
    private ScheduledFuture<?> polling;
    private boolean destroyed;

    @Override public void onCreate() {
        super.onCreate();
        store = HostPreferences.get(this);
        monitor = createMonitor();
        worker = Executors.newSingleThreadScheduledExecutor();
        getSystemService(NotificationManager.class).createNotificationChannel(new NotificationChannel(
                CHANNEL, "グラス実行環境の監視", NotificationManager.IMPORTANCE_LOW));
    }

    HostMonitor createMonitor() {
        return new HostMonitor(HostPreferences.get(this), new HostMonitor.Clock() {
            @Override public long elapsedRealtime() { return SystemClock.elapsedRealtime(); }
            @Override public int bootCount() {
                return Settings.Global.getInt(getContentResolver(), Settings.Global.BOOT_COUNT, -1);
            }
        }, new LoopbackHealth(), new TermuxLauncher(this));
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (!store.read().enabled) {
            monitor.stop();
            stopForeground(STOP_FOREGROUND_REMOVE);
            stopSelf();
            return START_NOT_STICKY;
        }
        startForeground(NOTIFICATION, notification(HostMonitor.Status.STARTING),
                ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE);
        monitor.start();
        if (polling == null) {
            polling = worker.scheduleWithFixedDelay(this::check, 0,
                    HostMonitor.POLL_MILLIS, TimeUnit.MILLISECONDS);
        }
        return START_STICKY;
    }

    private void check() {
        HostMonitor.Result result = monitor.check();
        main.post(() -> {
            HostMonitor.Snapshot saved = store.read();
            if (destroyed || !saved.enabled || saved.revision != result.revision
                    || result.status == HostMonitor.Status.STOPPED) return;
            getSystemService(NotificationManager.class).notify(NOTIFICATION, notification(result.status));
        });
    }

    private Notification notification(HostMonitor.Status status) {
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, CHANNEL)
                .setSmallIcon(android.R.drawable.stat_notify_sync)
                .setContentTitle("DocScan 実行環境")
                .setContentText(status.text)
                .setContentIntent(open)
                .setOnlyAlertOnce(true)
                .setOngoing(true)
                .build();
    }

    @Override public void onDestroy() {
        destroyed = true;
        monitor.stop();
        if (polling != null) polling.cancel(true);
        worker.shutdownNow();
        main.removeCallbacksAndMessages(null);
        stopForeground(STOP_FOREGROUND_REMOVE);
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
