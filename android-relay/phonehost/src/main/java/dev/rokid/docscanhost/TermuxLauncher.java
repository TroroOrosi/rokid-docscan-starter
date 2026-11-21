package dev.rokid.docscanhost;

import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;

final class TermuxLauncher implements HostMonitor.Launcher {
    static final String PERMISSION = "com.termux.permission.RUN_COMMAND";
    private final Context context;

    TermuxLauncher(Context context) { this.context = context.getApplicationContext(); }

    static Intent command() {
        return new Intent("com.termux.RUN_COMMAND")
                .setComponent(new ComponentName("com.termux", "com.termux.app.RunCommandService"))
                .putExtra("com.termux.RUN_COMMAND_PATH", "/data/data/com.termux/files/usr/bin/bash")
                .putExtra("com.termux.RUN_COMMAND_ARGUMENTS", new String[]{
                        "/data/data/com.termux/files/home/.termux/boot/20-rokid-services"})
                .putExtra("com.termux.RUN_COMMAND_BACKGROUND", true);
    }

    @Override public HostMonitor.Status availability() {
        try {
            ServiceInfo service = context.getPackageManager().getServiceInfo(command().getComponent(), 0);
            if (!service.enabled || !service.applicationInfo.enabled || !service.exported) {
                return HostMonitor.Status.TERMUX_MISSING;
            }
        } catch (PackageManager.NameNotFoundException error) {
            return HostMonitor.Status.TERMUX_MISSING;
        }
        if (context.checkSelfPermission(PERMISSION) != PackageManager.PERMISSION_GRANTED) {
            return HostMonitor.Status.PERMISSION_REQUIRED;
        }
        return HostMonitor.Status.READY;
    }

    @Override public void launch() {
        if (context.startService(command()) == null) {
            throw new IllegalStateException("Termux command service unavailable");
        }
    }
}
