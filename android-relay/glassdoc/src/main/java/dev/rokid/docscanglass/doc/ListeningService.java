package dev.rokid.docscanglass.doc;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;

/** Keeps the microphone session eligible while the capture Activity's display sleeps. */
public final class ListeningService extends Service {
    static final String RECORDING = "recording";
    static final String FINISHING = "finishing";
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        boolean finishing = intent != null && intent.getBooleanExtra(FINISHING, false);
        NotificationManager notifications = getSystemService(NotificationManager.class);
        notifications.createNotificationChannel(new NotificationChannel(
                "listening", "リスニング録音", NotificationManager.IMPORTANCE_LOW));
        Notification notification = new Notification.Builder(this, "listening")
                .setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .setContentTitle(intent != null && intent.getBooleanExtra(RECORDING, false)
                        ? "リスニング録音中" : finishing
                        ? "保存した音声を送信中" : "マイク準備中")
                .setContentText("撮影完了後、ダブルタップで録音終了")
                .setOngoing(true).build();
        if (Build.VERSION.SDK_INT >= 30) startForeground(7402, notification, finishing
                ? ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC : ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE);
        else startForeground(7402, notification);
        return START_NOT_STICKY;
    }
    @Override public IBinder onBind(Intent intent) { return null; }
}
