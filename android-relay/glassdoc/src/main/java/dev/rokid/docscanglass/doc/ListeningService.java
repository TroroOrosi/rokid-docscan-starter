package dev.rokid.docscanglass.doc;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.IBinder;

/** Keeps the microphone session eligible while the capture Activity's display sleeps. */
public final class ListeningService extends Service {
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        NotificationManager notifications = getSystemService(NotificationManager.class);
        notifications.createNotificationChannel(new NotificationChannel(
                "listening", "リスニング録音", NotificationManager.IMPORTANCE_LOW));
        startForeground(7402, new Notification.Builder(this, "listening")
                .setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .setContentTitle("リスニング録音中")
                .setContentText("撮影完了後、ダブルタップで録音終了")
                .setOngoing(true).build());
        return START_NOT_STICKY;
    }
    @Override public IBinder onBind(Intent intent) { return null; }
}
