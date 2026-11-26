package com.fen.tsrealm;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Typeface;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.DisplayMetrics;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Màn hình chính: thanh tab ở trên (mỗi tab một tài khoản), nội dung tab ở dưới. */
public class MainActivity extends Activity implements AccountPanel.Listener {
    private final Map<String, AccountPanel> panels = new LinkedHashMap<>();
    private final Map<String, TextView> chips = new LinkedHashMap<>();
    private final List<String> servers = new ArrayList<>();
    private final Handler ui = new Handler(Looper.getMainLooper());
    private SharedPreferences prefs;
    private LinearLayout tabStrip;
    private FrameLayout content;
    private TextView loading;
    private String current;
    private boolean ready;

    private final Runnable ticker = new Runnable() {
        @Override public void run() {
            for (AccountPanel p : panels.values()) p.poll();
            ui.postDelayed(this, 1000);
        }
    };

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        prefs = getSharedPreferences("main", MODE_PRIVATE);
        buildShell();
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1);
        }
        Py.call(r -> {
            JSONArray sv = r.optJSONArray("servers");
            if (sv != null) for (int i = 0; i < sv.length(); i++) servers.add(sv.optString(i));
            if (!r.optBoolean("ok")) {
                loading.setText("Không khởi động được bot:\n" + r.optString("error"));
                return;
            }
            ready = true;
            content.removeView(loading);
            restoreTabs();
            ui.post(ticker);
        }, "init", getFilesDir().getAbsolutePath());
    }

    private void buildShell() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Ui.BG);
        root.setBackground(Ui.round(this, Ui.BG, 14));
        root.setClipToOutline(true);

        // thanh tiêu đề cửa sổ: kéo để di chuyển, − thu xuống nền, □ phóng to / thu lại
        LinearLayout titleBar = Ui.row(this);
        titleBar.setBackgroundColor(0xFF0F1115);
        TextView drag = Ui.text(this, "TS Realm  •  Kéo để di chuyển", 13, Ui.DIM);
        drag.setPadding(Ui.dp(this, 12), Ui.dp(this, 10), 0, Ui.dp(this, 10));
        drag.setOnTouchListener(new View.OnTouchListener() {
            float x, y;
            int px, py;
            @Override public boolean onTouch(View v, MotionEvent e) {
                WindowManager.LayoutParams lp = getWindow().getAttributes();
                switch (e.getAction()) {
                    case MotionEvent.ACTION_DOWN:
                        x = e.getRawX(); y = e.getRawY(); px = lp.x; py = lp.y;
                        return true;
                    case MotionEvent.ACTION_MOVE:
                        lp.x = px + (int) (e.getRawX() - x);
                        lp.y = py + (int) (e.getRawY() - y);
                        getWindow().setAttributes(lp);
                        return true;
                    case MotionEvent.ACTION_UP:
                        prefs.edit().putInt("win_x", lp.x).putInt("win_y", lp.y).apply();
                        return true;
                }
                return false;
            }
        });
        titleBar.addView(drag, new LinearLayout.LayoutParams(0, -2, 1f));
        titleBar.addView(winButton("−", v -> moveTaskToBack(true)));
        titleBar.addView(winButton("□", v -> {
            prefs.edit().putBoolean("win_full", !prefs.getBoolean("win_full", false)).apply();
            applyAppWindow();
        }));
        root.addView(titleBar);

        LinearLayout bar = Ui.row(this);
        bar.setBackgroundColor(Ui.CARD);
        int p = Ui.dp(this, 6);
        bar.setPadding(p, p, p, p);
        HorizontalScrollView hs = new HorizontalScrollView(this);
        hs.setHorizontalScrollBarEnabled(false);
        tabStrip = new LinearLayout(this);
        tabStrip.setOrientation(LinearLayout.HORIZONTAL);
        hs.addView(tabStrip);
        bar.addView(hs, new LinearLayout.LayoutParams(0, -2, 1f));

        TextView add = Ui.text(this, "+", 22, 0xFFFFFFFF);
        add.setGravity(Gravity.CENTER);
        add.setBackground(Ui.round(this, Ui.ACCENT, 18));
        add.setOnClickListener(v -> { if (ready) selectTab(newTab()); });
        LinearLayout.LayoutParams alp = new LinearLayout.LayoutParams(Ui.dp(this, 36), Ui.dp(this, 36));
        alp.leftMargin = Ui.dp(this, 6);
        bar.addView(add, alp);

        TextView del = Ui.text(this, "✕", 18, 0xFFFFFFFF);
        del.setGravity(Gravity.CENTER);
        del.setBackground(Ui.round(this, Ui.LINE, 18));
        del.setOnClickListener(v -> { if (ready && current != null) askClose(current); });
        LinearLayout.LayoutParams dlp = new LinearLayout.LayoutParams(Ui.dp(this, 36), Ui.dp(this, 36));
        dlp.leftMargin = Ui.dp(this, 6);
        bar.addView(del, dlp);
        root.addView(bar);

        content = new FrameLayout(this);
        loading = Ui.text(this, "Đang khởi động bot…", 15, Ui.DIM);
        loading.setGravity(Gravity.CENTER);
        content.addView(loading, new FrameLayout.LayoutParams(-1, -1));
        root.addView(content, new LinearLayout.LayoutParams(-1, 0, 1f));
        setContentView(root);
    }

    private TextView winButton(String label, View.OnClickListener click) {
        TextView b = Ui.text(this, label, 18, Ui.TEXT);
        b.setGravity(Gravity.CENTER);
        b.setOnClickListener(click);
        b.setLayoutParams(new LinearLayout.LayoutParams(Ui.dp(this, 48), Ui.dp(this, 42)));
        return b;
    }

    /** Cửa sổ nổi 94% x 78% màn hình như ts_bot; □ để phóng to hết màn hình. */
    private void applyAppWindow() {
        DisplayMetrics m = getResources().getDisplayMetrics();
        boolean full = prefs.getBoolean("win_full", false);
        Window w = getWindow();
        w.setGravity(Gravity.CENTER);
        w.setLayout(full ? m.widthPixels : (int) (m.widthPixels * .94f),
                full ? m.heightPixels : (int) (m.heightPixels * .78f));
        WindowManager.LayoutParams lp = w.getAttributes();
        lp.x = full ? 0 : prefs.getInt("win_x", 0);
        lp.y = full ? 0 : prefs.getInt("win_y", 0);
        w.setAttributes(lp);
        w.clearFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND);
        w.addFlags(WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL);   // chạm ngoài cửa sổ thì tới app phía sau
        w.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        setFinishOnTouchOutside(false);
    }

    @Override
    protected void onResume() {
        super.onResume();
        applyAppWindow();
    }

    // ---------- tab ----------
    private void restoreTabs() {
        String saved = prefs.getString("tabs", "");
        for (String id : saved.split(",")) if (!id.isEmpty()) addTab(id);
        if (panels.isEmpty()) newTab();
        String last = prefs.getString("current", null);
        selectTab(last != null && panels.containsKey(last) ? last : panels.keySet().iterator().next());
    }

    private String newTab() {
        int n = prefs.getInt("next_id", 1);
        String id = String.valueOf(n);
        prefs.edit().putInt("next_id", n + 1).apply();
        addTab(id);
        saveTabs();
        return id;
    }

    private void addTab(String id) {
        AccountPanel panel = new AccountPanel(this, id, servers, this);
        panel.setVisibility(View.GONE);
        content.addView(panel, new FrameLayout.LayoutParams(-1, -1));
        panels.put(id, panel);

        TextView chip = Ui.text(this, "", 14, Ui.TEXT);
        chip.setGravity(Gravity.CENTER);
        chip.setSingleLine(true);
        int h = Ui.dp(this, 12), v = Ui.dp(this, 7);
        chip.setPadding(h, v, h, v);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-2, -2);
        lp.rightMargin = Ui.dp(this, 6);
        chip.setOnClickListener(x -> selectTab(id));
        chip.setOnLongClickListener(x -> { askClose(id); return true; });
        tabStrip.addView(chip, lp);
        chips.put(id, chip);
        paintChip(id);
    }

    private void selectTab(String id) {
        current = id;
        for (Map.Entry<String, AccountPanel> e : panels.entrySet())
            e.getValue().setVisibility(e.getKey().equals(id) ? View.VISIBLE : View.GONE);
        for (String k : chips.keySet()) paintChip(k);
        prefs.edit().putString("current", id).apply();
    }

    private void paintChip(String id) {
        AccountPanel p = panels.get(id);
        TextView chip = chips.get(id);
        if (p == null || chip == null) return;
        String t = p.title();
        if (t == null) t = "Tab " + id;
        chip.setText("● " + t);
        boolean sel = id.equals(current);
        chip.setBackground(Ui.round(this, sel ? Ui.LINE : Ui.BG, 16));
        chip.setTextColor(sel ? Ui.TEXT : Ui.DIM);
        android.text.SpannableString s = new android.text.SpannableString(chip.getText());
        s.setSpan(new android.text.style.ForegroundColorSpan(Ui.stateColor(p.state)), 0, 1, 0);
        chip.setText(s);
    }

    private void askClose(String id) {
        AccountPanel p = panels.get(id);
        if (p == null) return;
        String name = p.title() == null ? "Tab " + id : p.title();
        new AlertDialog.Builder(this)
                .setTitle("Đóng " + name + "?")
                .setMessage("Tài khoản trong tab sẽ đăng xuất và dừng mọi hoạt động.")
                .setPositiveButton("Đóng tab", (d, w) -> closeTab(id))
                .setNegativeButton("Thôi", null)
                .show();
    }

    private void closeTab(String id) {
        AccountPanel p = panels.remove(id);
        TextView chip = chips.remove(id);
        if (p != null) { content.removeView(p); p.forget(); }
        if (chip != null) tabStrip.removeView(chip);
        Py.call(r -> updateService(), "close_tab", id);
        if (panels.isEmpty()) newTab();
        saveTabs();
        if (id.equals(current)) selectTab(panels.keySet().iterator().next());
    }

    private void saveTabs() {
        prefs.edit().putString("tabs", android.text.TextUtils.join(",", panels.keySet())).apply();
    }

    @Override
    public void onStateChanged(AccountPanel p) {
        paintChip(p.tab);
        updateService();
    }

    private void updateService() {
        int online = 0, running = 0;
        for (AccountPanel p : panels.values()) {
            if ("online".equals(p.state) || "running".equals(p.state) || "logging_in".equals(p.state)) online++;
            if ("running".equals(p.state)) running++;
        }
        try { BotService.update(this, online, running); } catch (Exception ignored) {}
    }

    @Override
    public void onBackPressed() {
        moveTaskToBack(true);     // không thoát app, để các acc tiếp tục chạy
    }

    @Override
    protected void onDestroy() {
        ui.removeCallbacks(ticker);
        super.onDestroy();
    }
}
