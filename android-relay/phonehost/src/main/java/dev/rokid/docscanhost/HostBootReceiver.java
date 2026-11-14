package dev.rokid.docscanhost;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.util.Log;

public final class HostBootReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        if (!Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())
                || !HostPreferences.get(context).read().enabled) return;
        try {
            context.startForegroundService(new Intent(context, HostMonitorService.class));
        } catch (IllegalStateException | SecurityException error) {
            Log.w("DocScanHost", "Boot monitor start refused");
        }
    }
}
