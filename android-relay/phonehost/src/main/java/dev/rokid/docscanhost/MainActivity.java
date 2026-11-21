package dev.rokid.docscanhost;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

public final class MainActivity extends Activity {
    private static final int PERMISSIONS = 1;
    private HostPreferences store;
    private TextView status;
    private Button enable;
    private Button disable;

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        store = HostPreferences.get(this);
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        int margin = (int) (24 * getResources().getDisplayMetrics().density);
        content.setPadding(margin, margin * 2, margin, margin);
        TextView title = new TextView(this);
        title.setText("DocScan 実行環境");
        title.setTextSize(24);
        content.addView(title);
        TextView description = new TextView(this);
        description.setText("グラス用サーバーを15秒ごとに確認し、接続できないときにTermuxの起動を要求します。監視の設定はスマホの再起動後も引き継ぎます。");
        description.setPadding(0, margin, 0, margin);
        content.addView(description);
        status = new TextView(this);
        status.setTextSize(18);
        content.addView(status);
        enable = new Button(this);
        enable.setText("監視を開始");
        enable.setOnClickListener(view -> requestEnable());
        content.addView(enable);
        disable = new Button(this);
        disable.setText("監視を停止");
        disable.setOnClickListener(view -> disable());
        content.addView(disable);
        TextView setup = new TextView(this);
        setup.setText("初回はTermuxの外部コマンド許可と実行環境の導入が必要です。現在の接続状態は通知で確認できます。");
        setup.setPadding(0, margin, 0, 0);
        content.addView(setup);
        ScrollView scroll = new ScrollView(this);
        scroll.addView(content);
        setContentView(scroll);
    }

    @Override protected void onResume() {
        super.onResume();
        refresh();
        if (store.read().enabled) {
            try {
                startForegroundService(new Intent(this, HostMonitorService.class));
            } catch (IllegalStateException | SecurityException error) {
                status.setText("監視を再開できませんでした。権限とスマホの設定を確認してください。");
            }
        }
    }

    private void requestEnable() {
        HostMonitor.Status availability = new TermuxLauncher(this).availability();
        if (availability == HostMonitor.Status.TERMUX_MISSING) {
            status.setText(availability.text);
            return;
        }
        boolean commandGranted = checkSelfPermission(TermuxLauncher.PERMISSION) == PackageManager.PERMISSION_GRANTED;
        boolean notificationGranted = Build.VERSION.SDK_INT < 33
                || checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED;
        if (!commandGranted || !notificationGranted) {
            String[] permissions = Build.VERSION.SDK_INT >= 33
                    ? new String[]{TermuxLauncher.PERMISSION, Manifest.permission.POST_NOTIFICATIONS}
                    : new String[]{TermuxLauncher.PERMISSION};
            requestPermissions(permissions, PERMISSIONS);
            return;
        }
        enable();
    }

    @Override public void onRequestPermissionsResult(int request, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(request, permissions, results);
        if (request != PERMISSIONS) return;
        if (checkSelfPermission(TermuxLauncher.PERMISSION) == PackageManager.PERMISSION_GRANTED) enable();
        else status.setText(HostMonitor.Status.PERMISSION_REQUIRED.text);
    }

    private void enable() {
        if (!store.setEnabled(true)) {
            stopService(new Intent(this, HostMonitorService.class));
            refresh();
            status.setText(HostMonitor.Status.STORAGE_FAILED.text);
            return;
        }
        try {
            startForegroundService(new Intent(this, HostMonitorService.class));
            refresh();
        } catch (IllegalStateException | SecurityException error) {
            store.setEnabled(false);
            stopService(new Intent(this, HostMonitorService.class));
            refresh();
            status.setText("監視を開始できませんでした。権限とスマホの設定を確認してください。");
        }
    }

    private void disable() {
        boolean saved = store.setEnabled(false);
        stopService(new Intent(this, HostMonitorService.class));
        refresh();
        if (!saved) status.setText(HostMonitor.Status.STORAGE_FAILED.text);
    }

    private void refresh() {
        boolean enabled = store.read().enabled;
        status.setText(enabled ? "監視の設定は有効です" : "監視は停止しています");
        enable.setEnabled(!enabled);
        disable.setEnabled(enabled);
    }
}
