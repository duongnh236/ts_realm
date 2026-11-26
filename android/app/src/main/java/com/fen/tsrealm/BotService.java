package com.fen.tsrealm;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;

/** Dịch vụ chạy nền: giữ app sống + giữ CPU khi tắt màn hình, để các acc không rớt mạng. */
public class BotService extends Service {
    static final String CH = "tsrealm_run";
    static final int NID = 7;
    static final String EXTRA_TEXT = "text";
    private PowerManager.WakeLock wake;

    static void update(Context ctx, int online, int running) {
        Intent i = new Intent(ctx, BotService.class);
        if (online <= 0) {
            ctx.stopService(i);
            return;
        }
        String text = online + " tài khoản đang vào game" + (running > 0 ? ", " + running + " đang chạy" : "");
        i.putExtra(EXTRA_TEXT, text);
        ctx.startForegroundService(i);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String text = intent != null ? intent.getStringExtra(EXTRA_TEXT) : null;
        Notification n = build(text == null ? "Đang chạy" : text);
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        } else {
            startForeground(NID, n);
        }
        if (wake == null) {
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            wake = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "tsrealm:bot");
            wake.setReferenceCounted(false);
            wake.acquire();
        }
        return START_STICKY;
    }

    private Notification build(String text) {
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm.getNotificationChannel(CH) == null) {
            nm.createNotificationChannel(new NotificationChannel(CH, "TS Realm chạy nền",
                    NotificationManager.IMPORTANCE_LOW));
        }
        PendingIntent open = PendingIntent.getActivity(this, 0,
                new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        return new Notification.Builder(this, CH)
                .setSmallIcon(R.drawable.ic_launcher)
                .setContentTitle("TS Realm")
                .setContentText(text)
                .setOngoing(true)
                .setContentIntent(open)
                .build();
    }

    @Override
    public void onDestroy() {
        if (wake != null && wake.isHeld()) wake.release();
        wake = null;
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }
}
