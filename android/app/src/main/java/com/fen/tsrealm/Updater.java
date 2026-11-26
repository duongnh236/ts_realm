package com.fen.tsrealm;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.PendingIntent;
import android.content.Intent;
import android.content.pm.PackageInstaller;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * Nút "Cập nhật": đọc GitHub Release mới nhất của repo, có bản mới hơn thì tải file .apk đính kèm
 * và mở trình cài đặt của Android (PackageInstaller, người dùng bấm "Cập nhật" để xác nhận).
 *
 * Quy ước release: tag = số phiên bản (vd "v1.2.0"), đính kèm đúng một file .apk.
 * APK phải ký cùng khoá với bản đang cài (build trên cùng máy Mac), nếu không Android từ chối cài.
 */
final class Updater {
    static final String REPO = "duongnh236/ts_realm";
    static final String ACTION_STATUS = "com.fen.tsrealm.UPDATE_STATUS";

    private final Activity act;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private boolean busy;

    Updater(Activity act) { this.act = act; }

    static String currentVersion(Activity a) {
        try {
            return a.getPackageManager().getPackageInfo(a.getPackageName(), 0).versionName;
        } catch (PackageManager.NameNotFoundException e) {
            return "0";
        }
    }

    /** So "1.2.10" với "1.2.9" theo từng số. Bỏ chữ "v" ở đầu. */
    static int compare(String a, String b) {
        String[] x = strip(a).split("[.\\-+]"), y = strip(b).split("[.\\-+]");
        for (int i = 0; i < Math.max(x.length, y.length); i++) {
            int p = i < x.length ? num(x[i]) : 0, q = i < y.length ? num(y[i]) : 0;
            if (p != q) return Integer.compare(p, q);
        }
        return 0;
    }

    private static String strip(String s) {
        s = s == null ? "" : s.trim();
        return s.startsWith("v") || s.startsWith("V") ? s.substring(1) : s;
    }

    private static int num(String s) {
        int n = 0;
        for (char ch : s.toCharArray()) {
            if (ch < '0' || ch > '9') break;
            n = n * 10 + (ch - '0');
        }
        return n;
    }

    void check(boolean botBusy) {
        if (busy) return;
        busy = true;
        toast("Đang kiểm tra bản mới…");
        new Thread(() -> {
            try {
                JSONObject rel = new JSONObject(get("https://api.github.com/repos/" + REPO + "/releases/latest"));
                String tag = rel.optString("tag_name", "");
                String apkUrl = null;
                long size = 0;
                JSONArray assets = rel.optJSONArray("assets");
                if (assets != null) for (int i = 0; i < assets.length(); i++) {
                    JSONObject a = assets.optJSONObject(i);
                    if (a != null && a.optString("name").toLowerCase().endsWith(".apk")) {
                        apkUrl = a.optString("browser_download_url");
                        size = a.optLong("size");
                        break;
                    }
                }
                String cur = currentVersion(act);
                String notes = rel.optString("body", "");
                final String fUrl = apkUrl, fTag = tag;
                final long fSize = size;
                ui.post(() -> {
                    busy = false;
                    if (fUrl == null) { toast("Release " + fTag + " chưa có file .apk"); return; }
                    if (compare(fTag, cur) <= 0) { toast("Đang dùng bản mới nhất (" + cur + ")"); return; }
                    String msg = "Bản đang dùng: " + cur + "\nBản mới: " + fTag
                            + String.format(" (%.1f MB)", fSize / 1048576.0);
                    if (!notes.isEmpty()) msg += "\n\n" + (notes.length() > 600 ? notes.substring(0, 600) + "…" : notes);
                    if (botBusy) msg += "\n\nBot đang chạy / đăng nhập: cài bản mới sẽ ngắt bot.";
                    new AlertDialog.Builder(act)
                            .setTitle("Có bản cập nhật")
                            .setMessage(msg)
                            .setPositiveButton("Tải và cài", (d, w) -> download(fUrl, fTag, fSize))
                            .setNegativeButton("Để sau", null)
                            .show();
                });
            } catch (Exception e) {
                ui.post(() -> { busy = false; toast("Không kiểm tra được bản mới: " + e.getMessage()); });
            }
        }, "update-check").start();
    }

    private void download(String url, String tag, long size) {
        if (Build.VERSION.SDK_INT >= 26 && !act.getPackageManager().canRequestPackageInstalls()) {
            toast("Cho phép TS Realm cài ứng dụng, rồi bấm Cập nhật lại");
            act.startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:" + act.getPackageName())));
            return;
        }
        TextView tv = Ui.text(act, "Đang tải 0%", 15, Ui.TEXT);
        int p = Ui.dp(act, 20);
        tv.setPadding(p, p, p, p);
        AlertDialog dlg = new AlertDialog.Builder(act).setTitle("Tải " + tag).setView(tv).setCancelable(false).show();
        new Thread(() -> {
            File dir = new File(act.getExternalFilesDir(null), "update");
            File f = new File(dir, "tsrealm-" + tag + ".apk");
            try {
                dir.mkdirs();
                HttpURLConnection c = open(url);
                long total = c.getContentLengthLong() > 0 ? c.getContentLengthLong() : size;
                try (InputStream in = c.getInputStream(); OutputStream out = new FileOutputStream(f)) {
                    byte[] buf = new byte[65536];
                    long got = 0;
                    int k, last = -1;
                    while ((k = in.read(buf)) > 0) {
                        out.write(buf, 0, k);
                        got += k;
                        int pct = total > 0 ? (int) (got * 100 / total) : -1;
                        if (pct != last) {
                            last = pct;
                            final long g = got;
                            ui.post(() -> tv.setText(pct >= 0 ? "Đang tải " + pct + "%" : "Đang tải " + g / 1024 + " KB"));
                        }
                    }
                }
                ui.post(() -> tv.setText("Đang mở trình cài đặt…"));
                install(f);
                ui.post(dlg::dismiss);
            } catch (Exception e) {
                ui.post(() -> { dlg.dismiss(); toast("Tải bản mới lỗi: " + e.getMessage()); });
            }
        }, "update-download").start();
    }

    /** Cài qua PackageInstaller (không cần FileProvider). Android hỏi xác nhận qua ACTION_STATUS. */
    private void install(File apk) throws Exception {
        PackageInstaller pi = act.getPackageManager().getPackageInstaller();
        PackageInstaller.SessionParams sp = new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
        sp.setAppPackageName(act.getPackageName());
        int id = pi.createSession(sp);
        try (PackageInstaller.Session s = pi.openSession(id)) {
            try (InputStream in = new FileInputStream(apk); OutputStream out = s.openWrite("tsrealm.apk", 0, apk.length())) {
                byte[] buf = new byte[65536];
                int k;
                while ((k = in.read(buf)) > 0) out.write(buf, 0, k);
                s.fsync(out);
            }
            Intent cb = new Intent(act, MainActivity.class).setAction(ACTION_STATUS);
            int flags = PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 31 ? PendingIntent.FLAG_MUTABLE : 0);
            PendingIntent pend = PendingIntent.getActivity(act, id, cb, flags);
            s.commit(pend.getIntentSender());
        }
    }

    /** MainActivity.onNewIntent chuyển kết quả cài về đây. */
    void onStatus(Intent i) {
        int st = i.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
        if (st == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            Intent confirm = Build.VERSION.SDK_INT >= 33
                    ? i.getParcelableExtra(Intent.EXTRA_INTENT, Intent.class)
                    : i.getParcelableExtra(Intent.EXTRA_INTENT);
            if (confirm != null) act.startActivity(confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        } else if (st != PackageInstaller.STATUS_SUCCESS) {
            String m = i.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE);
            if (st == PackageInstaller.STATUS_FAILURE_CONFLICT || st == PackageInstaller.STATUS_FAILURE_INCOMPATIBLE)
                m = "APK ký khác khoá với bản đang cài (" + m + ")";
            toast("Cài bản mới không được: " + m);
        }
    }

    private static HttpURLConnection open(String url) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setRequestProperty("User-Agent", "tsrealm-updater");
        c.setRequestProperty("Accept", "application/vnd.github+json");
        c.setConnectTimeout(15000);
        c.setReadTimeout(30000);
        c.setInstanceFollowRedirects(true);
        int code = c.getResponseCode();
        if (code == 404) throw new Exception("repo chưa có release nào");
        if (code >= 400) throw new Exception("HTTP " + code);
        return c;
    }

    private static String get(String url) throws Exception {
        HttpURLConnection c = open(url);
        try (InputStream in = c.getInputStream()) {
            ByteArrayOutputStream b = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int k;
            while ((k = in.read(buf)) > 0) b.write(buf, 0, k);
            return b.toString("UTF-8");
        }
    }

    private void toast(String s) { Toast.makeText(act, s, Toast.LENGTH_LONG).show(); }
}
