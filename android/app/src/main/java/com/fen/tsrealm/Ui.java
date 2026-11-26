package com.fen.tsrealm;

import android.content.Context;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Màu và vài widget dựng sẵn (không dùng file layout XML). */
final class Ui {
    static final int BG = 0xFF15171C, CARD = 0xFF1F2229, LINE = 0xFF2C3038, FIELD = 0xFF262A32;
    static final int TEXT = 0xFFE6E8EC, DIM = 0xFF9AA0AA, ACCENT = 0xFF4C8DFF;
    static final int OK = 0xFF3CC47C, WARN = 0xFFF2B33D, BAD = 0xFFEF5B5B, OFF = 0xFF6B717C;

    private Ui() {}

    static int dp(Context c, float v) {
        return Math.round(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v,
                c.getResources().getDisplayMetrics()));
    }

    static GradientDrawable round(Context c, int color, float radius) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(color);
        g.setCornerRadius(dp(c, radius));
        return g;
    }

    static LinearLayout card(Context c, String title) {
        LinearLayout l = new LinearLayout(c);
        l.setOrientation(LinearLayout.VERTICAL);
        l.setBackground(round(c, CARD, 12));
        int p = dp(c, 14);
        l.setPadding(p, p, p, p);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.bottomMargin = dp(c, 12);
        l.setLayoutParams(lp);
        if (title != null) {
            TextView t = text(c, title, 15, TEXT);
            t.setTypeface(Typeface.DEFAULT_BOLD);
            t.setPadding(0, 0, 0, dp(c, 8));
            l.addView(t);
        }
        return l;
    }

    static TextView text(Context c, String s, float sp, int color) {
        TextView t = new TextView(c);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(color);
        return t;
    }

    static EditText field(Context c, String hint, boolean password) {
        EditText e = new EditText(c);
        e.setHint(hint);
        e.setHintTextColor(DIM);
        e.setTextColor(TEXT);
        e.setTextSize(15);
        e.setSingleLine(true);
        e.setBackground(round(c, FIELD, 8));
        int p = dp(c, 10);
        e.setPadding(p, p, p, p);
        e.setInputType(password
                ? InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD
                : InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.bottomMargin = dp(c, 8);
        e.setLayoutParams(lp);
        return e;
    }

    static EditText number(Context c, String hint, String value) {
        EditText e = field(c, hint, false);
        e.setInputType(InputType.TYPE_CLASS_NUMBER);
        e.setText(value);
        return e;
    }

    static Button button(Context c, String label, int color) {
        Button b = new Button(c);
        b.setText(label);
        b.setAllCaps(false);
        b.setTextColor(Color.WHITE);
        b.setTextSize(15);
        b.setBackground(round(c, color, 10));
        b.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, dp(c, 46), 1f);
        lp.setMargins(dp(c, 4), dp(c, 4), dp(c, 4), dp(c, 4));
        b.setLayoutParams(lp);
        return b;
    }

    static CheckBox check(Context c, String label, boolean on) {
        CheckBox b = new CheckBox(c);
        b.setText(label);
        b.setTextColor(TEXT);
        b.setTextSize(15);
        b.setChecked(on);
        b.setButtonTintList(ColorStateList.valueOf(ACCENT));
        return b;
    }

    static LinearLayout row(Context c) {
        LinearLayout l = new LinearLayout(c);
        l.setOrientation(LinearLayout.HORIZONTAL);
        l.setGravity(Gravity.CENTER_VERTICAL);
        l.setLayoutParams(new LinearLayout.LayoutParams(-1, -2));
        return l;
    }

    static int stateColor(String state) {
        switch (state == null ? "" : state) {
            case "running": return OK;
            case "online": return ACCENT;
            case "logging_in": return WARN;
            case "error": return BAD;
            default: return OFF;
        }
    }

    static String stateText(String state) {
        switch (state == null ? "" : state) {
            case "running": return "Đang chạy";
            case "online": return "Đã vào game";
            case "logging_in": return "Đang đăng nhập…";
            case "error": return "Lỗi";
            default: return "Chưa đăng nhập";
        }
    }
}
