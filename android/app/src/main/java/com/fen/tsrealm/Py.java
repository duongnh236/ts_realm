package com.fen.tsrealm;

import android.os.Handler;
import android.os.Looper;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;

import org.json.JSONObject;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Gọi realm.android_api trên một luồng nền duy nhất, trả kết quả JSON về luồng giao diện. */
final class Py {
    interface Done { void on(JSONObject r); }

    private static final ExecutorService EXEC = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "py-bridge");
        t.setDaemon(true);
        return t;
    });
    private static final Handler UI = new Handler(Looper.getMainLooper());
    private static PyObject api;

    private Py() {}

    private static PyObject api() {
        if (api == null) api = Python.getInstance().getModule("realm.android_api");
        return api;
    }

    /** Gọi đồng bộ (chỉ dùng trên luồng nền). */
    static JSONObject callNow(String fn, Object... args) {
        try {
            PyObject r = api().callAttr(fn, args);
            String s = r == null ? "{}" : r.toString();
            if (s.startsWith("[")) return new JSONObject().put("list", new org.json.JSONArray(s));
            return new JSONObject(s);
        } catch (Throwable e) {
            JSONObject o = new JSONObject();
            try { o.put("ok", false).put("error", String.valueOf(e.getMessage())); } catch (Exception ignored) {}
            return o;
        }
    }

    /** Gọi nền, ``done`` chạy trên luồng giao diện (có thể null). */
    static void call(Done done, String fn, Object... args) {
        EXEC.execute(() -> {
            JSONObject r = callNow(fn, args);
            if (done != null) UI.post(() -> done.on(r));
        });
    }
}
