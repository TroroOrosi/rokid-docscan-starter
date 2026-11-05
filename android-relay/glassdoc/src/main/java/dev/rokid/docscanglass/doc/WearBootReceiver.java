package dev.rokid.docscanglass.doc;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.util.Log;

/** Ordinary boot restores proximity monitoring. Vendor force-stop still needs phone bootstrap. */
public final class WearBootReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        if (intent == null || !Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) return;
        try {
            context.startForegroundService(new Intent(context, WearService.class).putExtra(WearService.COLD_BOOT, true)
                    .putExtra("cold_generation", PowerState.forContext(context).load().generation));
        } catch (RuntimeException error) { Log.w("DocScanWear", "boot monitoring unavailable: " + error.getClass().getSimpleName()); }
    }
}
