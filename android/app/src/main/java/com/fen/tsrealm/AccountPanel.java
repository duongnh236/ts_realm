package com.fen.tsrealm;

import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Context;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import android.graphics.Typeface;
import android.text.TextUtils;
import android.view.View;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/** Một tab = một tài khoản: khung đăng nhập, chọn hoạt động, nút Chạy/Dừng và bảng trạng thái trận. */
class AccountPanel extends ScrollView {
    interface Listener {
        void onStateChanged(AccountPanel p);
        /** Tuỳ chọn chạy (đội hình, boss...) của tab khác, để thành viên party dùng đội hình của chính nó. */
        JSONObject optsOf(String tab);
    }

    final String tab;
    private final SharedPreferences prefs;
    private final Listener listener;

    private EditText user, pass, wbGoal, npcLosses, pbLevel;
    private Spinner server;
    private LoadoutBox loWb, loNpc, loNk;
    private CheckBox remember, rememberPw, cWb, cWbTickets, cWbBuy, cNpc, cNk, cPbDon, cPbDoi;
    private Button btnLogin, btnRun, btnStop, btnParty;
    private TextView stateLine, charLine;
    private TextView wbLine, npcLine, fightLine, charRow, petRow, bossRow, recentView;
    private LinearLayout loginCard, actCard, cbCard;
    private Spinner cbItem;
    private CheckBox cbBreak;
    private EditText cbQty, cbSlots, cbRounds, cbKeepVal, cbKeepLv;
    private Button cbLoad, cbGo, cbStop;
    private TextView cbLine;

    String state = "offline";
    String charName = "";
    private final List<String> serverIds = new ArrayList<>();
    private static final Locale VI = new Locale("vi", "VN");

    AccountPanel(Context c, String tab, List<String> servers, Listener listener) {
        super(c);
        this.tab = tab;
        this.listener = listener;
        this.prefs = c.getSharedPreferences("tab_" + tab, Context.MODE_PRIVATE);
        serverIds.addAll(servers);
        setFillViewport(true);
        setBackgroundColor(Ui.BG);
        build(c);
        restore();
        refreshButtons();
    }

    // ---------- giao diện ----------
    private void build(Context c) {
        LinearLayout root = new LinearLayout(c);
        root.setOrientation(LinearLayout.VERTICAL);
        int p = Ui.dp(c, 12);
        root.setPadding(p, p, p, p);
        addView(root, new LayoutParams(-1, -2));

        // trạng thái
        LinearLayout head = Ui.card(c, null);
        stateLine = Ui.text(c, "● Chưa đăng nhập", 16, Ui.OFF);
        stateLine.setTypeface(Typeface.DEFAULT_BOLD);
        charLine = Ui.text(c, "", 13, Ui.DIM);
        head.addView(stateLine);
        head.addView(charLine);
        root.addView(head);

        // đăng nhập
        loginCard = Ui.card(c, "Tài khoản");
        user = Ui.field(c, "Tên đăng nhập", false);
        pass = Ui.field(c, "Mật khẩu", true);
        server = new Spinner(c);
        server.setBackground(Ui.round(c, Ui.FIELD, 8));
        server.setPadding(Ui.dp(c, 6), 0, 0, 0);
        ArrayAdapter<String> ad = new ArrayAdapter<String>(c, android.R.layout.simple_spinner_item, serverIds) {
            @Override public View getView(int pos, View v, android.view.ViewGroup parent) {
                TextView t = (TextView) super.getView(pos, v, parent);
                t.setTextColor(Ui.TEXT);
                t.setTextSize(15);
                return t;
            }
        };
        ad.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        server.setAdapter(ad);
        LinearLayout.LayoutParams sp = new LinearLayout.LayoutParams(-1, Ui.dp(c, 44));
        sp.bottomMargin = Ui.dp(c, 8);
        remember = Ui.check(c, "Nhớ tài khoản + server", true);
        rememberPw = Ui.check(c, "Nhớ cả mật khẩu trên máy này", false);
        loginCard.addView(Ui.text(c, "Server", 13, Ui.DIM));
        loginCard.addView(server, sp);
        loginCard.addView(user);
        loginCard.addView(pass);
        loginCard.addView(remember);
        loginCard.addView(rememberPw);
        LinearLayout lr = Ui.row(c);
        btnLogin = Ui.button(c, "Đăng nhập", Ui.ACCENT);
        btnLogin.setOnClickListener(v -> onLoginClick());
        lr.addView(btnLogin);
        loginCard.addView(lr);
        root.addView(loginCard);

        // hoạt động
        actCard = Ui.card(c, "Hoạt động");
        cWb = Ui.check(c, "Boss Thế Giới  (10:00–23:00)", true);
        LinearLayout wbOpts = indent(c);
        cWbTickets = Ui.check(c, "Hết 5 lượt free thì dùng vé trong túi", true);
        wbGoal = Ui.number(c, "Dừng khi dame hôm nay đạt", "5000000");
        cWbBuy = Ui.check(c, "Hết vé thì tự mua vé shop (mỗi trận 1 vé, đủ dame thì thôi)", false);
        wbOpts.addView(cWbTickets);
        wbOpts.addView(cWbBuy);
        wbOpts.addView(label(c, "Dừng khi dame hôm nay ≥"));
        wbOpts.addView(wbGoal);
        loWb = new LoadoutBox(c, wbOpts, "Đội hình đánh boss", "lo_", false);
        cNk = Ui.check(c, "Nhị Kiều (2k)  (Chủ nhật 08:00–23:00)", false);
        LinearLayout nkOpts = indent(c);
        loNk = new LoadoutBox(c, nkOpts, "Đội hình Nhị Kiều", "lo_nk_");
        cNpc = Ui.check(c, "40 NPC  (T2/T4/T6 20:00–23:00)", false);
        LinearLayout npcOpts = indent(c);
        npcLosses = Ui.number(c, "0 = thua thì hồi máu/mana rồi đánh tiếp", "0");
        npcOpts.addView(label(c, "Thua liên tiếp mấy trận thì dừng (0 = không dừng, hồi rồi đánh tiếp)"));
        npcOpts.addView(npcLosses);
        loNpc = new LoadoutBox(c, npcOpts, "Đội hình 40 NPC", "lo_npc40_");
        cPbDon = Ui.check(c, "Phó bản đơn", false);
        cPbDoi = Ui.check(c, "Phó bản đội", false);
        LinearLayout pbOpts = indent(c);
        pbLevel = Ui.number(c, "Cấp phòng (20/50/80/110)", "50");
        pbOpts.addView(label(c, "Cấp phòng phó bản đội (20/50/80/110)"));
        pbOpts.addView(pbLevel);

        actCard.addView(cWb);
        actCard.addView(wbOpts);
        actCard.addView(cNk);
        actCard.addView(nkOpts);
        actCard.addView(cNpc);
        actCard.addView(npcOpts);
        actCard.addView(cPbDon);
        actCard.addView(cPbDoi);
        actCard.addView(pbOpts);
        bindToggle(cWb, wbOpts);
        bindToggle(cNk, nkOpts);
        bindToggle(cNpc, npcOpts);
        bindToggle(cPbDoi, pbOpts);
        actCard.addView(Ui.text(c, "Chạy lần lượt theo thứ tự trên; cái nào ngoài giờ thì bỏ qua.", 12, Ui.DIM));

        LinearLayout ar = Ui.row(c);
        ar.setPadding(0, Ui.dp(c, 8), 0, 0);
        btnRun = Ui.button(c, "▶  Chạy", Ui.OK);
        btnStop = Ui.button(c, "■  Dừng", Ui.BAD);
        btnRun.setOnClickListener(v -> onRunClick());
        btnStop.setOnClickListener(v -> Py.call(r -> poll(), "stop", tab));
        ar.addView(btnRun);
        ar.addView(btnStop);
        actCard.addView(ar);
        btnParty = Ui.button(c, "👥  Chạy party (tab này làm đội trưởng)", Ui.ACCENT);
        btnParty.setOnClickListener(v -> onPartyClick());
        actCard.addView(btnParty);
        actCard.addView(Ui.text(c, "Party: chỉ 40 NPC / Nhị Kiều. Đội trưởng mở trận, các tab chọn làm "
                + "thành viên tự vào đội và đánh theo. Mọi tab phải đăng nhập, đứng rảnh.", 12, Ui.DIM));
        root.addView(actCard);

        // hợp vật phẩm
        cbCard = Ui.card(c, "Hợp vật phẩm");
        cbCard.addView(Ui.text(c, "Chọn món trong túi, số lượng mỗi ô (ví dụ 40 → hợp hàng loạt 40 40 40). Tốn Đồng mỗi lần.", 12, Ui.DIM));
        cbLoad = Ui.button(c, "Tải danh sách túi", Ui.FIELD);
        cbLoad.setOnClickListener(v -> loadBag());
        LinearLayout lr2 = Ui.row(c);
        lr2.addView(cbLoad);
        cbCard.addView(lr2);
        cbItem = spinner(c);
        setItems(cbItem, new long[]{0}, new String[]{"(bấm Tải danh sách túi)"}, 0);
        cbCard.addView(label(c, "Vật phẩm"));
        cbCard.addView(cbItem, spLp(c));
        cbQty = Ui.number(c, "Số lượng mỗi ô", "40");
        cbSlots = Ui.number(c, "Số ô (1–3)", "3");
        cbRounds = Ui.number(c, "0 = hợp tới khi hết", "0");
        cbCard.addView(label(c, "Số lượng mỗi ô"));
        cbCard.addView(cbQty);
        cbCard.addView(label(c, "Số ô nguyên liệu (1–3)"));
        cbCard.addView(cbSlots);
        cbCard.addView(label(c, "Số lần hợp (0 = tới khi hết nguyên liệu)"));
        cbCard.addView(cbRounds);
        cbBreak = Ui.check(c, "Hợp xong phân giải luôn đồ vừa hợp ra (không đụng đồ cũ trong túi)", true);
        cbCard.addView(cbBreak);
        cbKeepVal = Ui.number(c, "0 = tắt", "27");
        cbKeepLv = Ui.number(c, "0 = tắt", "0");
        cbCard.addView(label(c, "Giữ lại đồ có giá trị từ ... trở lên (Kiệt Tác = 28; 0 = tắt)"));
        cbCard.addView(cbKeepVal);
        cbCard.addView(label(c, "Giữ lại đồ từ cấp ... trở lên (0 = tắt)"));
        cbCard.addView(cbKeepLv);
        LinearLayout cr = Ui.row(c);
        cr.setPadding(0, Ui.dp(c, 8), 0, 0);
        cbGo = Ui.button(c, "⚗  Hợp", Ui.OK);
        cbStop = Ui.button(c, "■  Dừng", Ui.BAD);
        cbGo.setOnClickListener(v -> onCombineClick());
        cbStop.setOnClickListener(v -> Py.call(r -> poll(), "stop", tab));
        cr.addView(cbGo);
        cr.addView(cbStop);
        cbCard.addView(cr);
        cbLine = Ui.text(c, "", 13, Ui.TEXT);
        cbLine.setVisibility(GONE);
        cbCard.addView(cbLine);
        root.addView(cbCard);

        // trạng thái trận (nhật ký đầy đủ chỉ xuất ra file)
        LinearLayout fight = Ui.card(c, "Trận đấu");
        wbLine = Ui.text(c, "", 13, Ui.DIM);
        npcLine = Ui.text(c, "", 14, Ui.TEXT);
        npcLine.setVisibility(GONE);
        fightLine = Ui.text(c, "Chưa vào trận", 15, Ui.TEXT);
        fightLine.setTypeface(Typeface.DEFAULT_BOLD);
        charRow = Ui.text(c, "", 14, Ui.TEXT);
        petRow = Ui.text(c, "", 14, Ui.TEXT);
        bossRow = Ui.text(c, "", 14, Ui.TEXT);
        int gap = Ui.dp(c, 6);
        for (TextView t : new TextView[]{charRow, petRow, bossRow}) {
            t.setBackground(Ui.round(c, Ui.FIELD, 8));
            t.setPadding(gap + gap, gap, gap, gap);
        }
        recentView = Ui.text(c, "", 12, 0xFFC9CED6);
        recentView.setBackground(Ui.round(c, 0xFF101216, 8));
        recentView.setPadding(gap, gap, gap, gap);
        wbLine.setVisibility(GONE);
        for (TextView t : new TextView[]{charRow, petRow, bossRow, recentView}) t.setVisibility(GONE);
        fight.addView(wbLine);
        fight.addView(npcLine);
        fight.addView(fightLine);
        for (TextView t : new TextView[]{charRow, petRow, bossRow, recentView}) {
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
            lp.topMargin = gap;
            fight.addView(t, lp);
        }
        LinearLayout er = Ui.row(c);
        er.setPadding(0, Ui.dp(c, 8), 0, 0);
        Button exp = Ui.button(c, "Xuất nhật ký ra file", Ui.FIELD);
        exp.setOnClickListener(v -> exportLog());
        er.addView(exp);
        fight.addView(er);
        root.addView(fight);
    }

    // ---------- đội hình theo chế độ (Boss TG / 40 NPC / Nhị Kiều) ----------
    /** Một khung chọn pet ra trận, skill đánh, skill buff. Mỗi chế độ một khung, lưu riêng theo ``prefix``. */
    private class LoadoutBox {
        final String prefix;
        final Spinner pet, charSkill, petSkill, charBuff, charBuffTgt, petBuff, petBuffTgt;
        final TextView hint;
        String sig = "";
        JSONObject data;

        final boolean withSkills;

        LoadoutBox(Context c, LinearLayout box, String title, String prefix) {
            this(c, box, title, prefix, true);
        }

        /** ``withSkills`` false (Boss TG): không có ô chọn skill đánh, bot tự đánh skill tốn SP cao nhất. */
        LoadoutBox(Context c, LinearLayout box, String title, String prefix, boolean withSkills) {
            this.prefix = prefix;
            this.withSkills = withSkills;
            TextView h = Ui.text(c, title, 14, Ui.TEXT);
            h.setTypeface(Typeface.DEFAULT_BOLD);
            h.setPadding(0, Ui.dp(c, 10), 0, Ui.dp(c, 2));
            box.addView(h);
            hint = Ui.text(c, "Đăng nhập để chọn pet và skill", 12, Ui.DIM);
            box.addView(hint);
            pet = spinner(c);
            charSkill = spinner(c);
            petSkill = spinner(c);
            charBuff = spinner(c);
            charBuffTgt = spinner(c);
            petBuff = spinner(c);
            petBuffTgt = spinner(c);
            box.addView(label(c, "Pet ra trận"));
            box.addView(pet, spLp(c));
            if (withSkills) {
                box.addView(label(c, "Skill đánh của nhân vật"));
                box.addView(charSkill, spLp(c));
                box.addView(label(c, "Skill đánh của pet"));
                box.addView(petSkill, spLp(c));
            }
            box.addView(label(c, "Buff của nhân vật"));
            box.addView(pair(c, charBuff, charBuffTgt));
            box.addView(label(c, "Buff của pet"));
            box.addView(pair(c, petBuff, petBuffTgt));
            box.addView(Ui.text(c, withSkills
                    ? "Skill chưa học / thiếu SP thì bot tự đánh như cũ. Hồi sinh, giải khống chế, giải buff địch vẫn được ưu tiên trước; hết buff thì buff lại."
                    : "Đánh bằng skill gây dame tốn SP cao nhất còn đủ SP. Ưu tiên: giải Đẩu Chuyển, hồi sinh, giải khống chế, giải buff boss (cả Kim Chung Tráo), buff; không dùng skill hồi máu trong trận, ai SP dưới 30% thì dùng skill hồi SP, không có skill thì nhân vật cho uống thuốc SP trong túi; boss có Kim Chung Tráo mà chưa giải được thì phòng thủ chờ. Trước mỗi trận hồi đầy HP/SP, hết thuốc thì dừng (không đốt vé); trận treo 90 giây thì ngắt.", 12, Ui.DIM));
            String[] tg = {"lên Pet", "lên Nhân vật"};
            setItems(charBuffTgt, new long[]{1, 2}, tg, prefs.getLong(prefix + "char_buff_tgt", 1));
            setItems(petBuffTgt, new long[]{1, 2}, tg, prefs.getLong(prefix + "pet_buff_tgt", 1));
            pet.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener() {
                @Override public void onItemSelected(android.widget.AdapterView<?> p, View v, int pos, long id) { fillPetSkills(); }
                @Override public void onNothingSelected(android.widget.AdapterView<?> p) {}
            });
            enable(false);
        }

        void enable(boolean on) {
            for (Spinner sp : new Spinner[]{pet, charSkill, petSkill, charBuff, charBuffTgt, petBuff, petBuffTgt}) {
                sp.setEnabled(on);
                sp.setAlpha(on ? 1f : 0.5f);
            }
            hint.setVisibility(on ? GONE : VISIBLE);
        }

        private long keep(Spinner sp, String key) {
            return sp.getTag() == null ? prefs.getLong(prefix + key, 0) : selectedId(sp);
        }

        private JSONArray petSkills(long pid) {
            if (data == null) return null;
            if (pid == 0) pid = data.optLong("active_pet", 0);
            JSONArray pets = data.optJSONArray("pets");
            if (pets != null) for (int i = 0; i < pets.length(); i++) {
                JSONObject p = pets.optJSONObject(i);
                if (p != null && p.optLong("id") == pid) return p.optJSONArray("skills");
            }
            return null;
        }

        void fillPetSkills() {
            if (data == null) return;
            long keepSkill = keep(petSkill, "pet_skill");
            long keepBuff = keep(petBuff, "pet_buff");
            JSONArray sk = petSkills(selectedId(pet));
            fillSkills(petSkill, sk, true, "Tự động", keepSkill);
            fillSkills(petBuff, sk, false, "Không buff", keepBuff);
        }

        void apply(JSONObject lo) {
            if (lo == null) return;
            String s = lo.toString();
            if (s.equals(sig)) return;
            sig = s;
            data = lo;
            JSONArray pets = lo.optJSONArray("pets");
            List<Long> ids = new ArrayList<>();
            List<String> labels = new ArrayList<>();
            ids.add(0L);
            labels.add("Giữ pet đang dùng");
            if (pets != null) for (int i = 0; i < pets.length(); i++) {
                JSONObject p = pets.optJSONObject(i);
                if (p == null) continue;
                ids.add(p.optLong("id"));
                String nm = p.optString("name");
                if (p.optLong("id") == lo.optLong("active_pet", -1)) nm += "  (đang dùng)";
                labels.add(nm);
            }
            long[] a = new long[ids.size()];
            for (int i = 0; i < a.length; i++) a[i] = ids.get(i);
            long keepPet = keep(pet, "pet");
            setItems(pet, a, labels.toArray(new String[0]), keepPet);
            JSONArray cs = lo.optJSONArray("char_skills");
            long keepCS = keep(charSkill, "char_skill");
            long keepCB = keep(charBuff, "char_buff");
            fillSkills(charSkill, cs, true, "Tự động", keepCS);
            fillSkills(charBuff, cs, false, "Không buff", keepCB);
            fillPetSkills();
            enable(cs != null && cs.length() > 0);
        }

        void save(SharedPreferences.Editor e) {
            if (pet.getTag() != null) {
                e.putLong(prefix + "pet", selectedId(pet)).putLong(prefix + "char_skill", selectedId(charSkill))
                        .putLong(prefix + "pet_skill", selectedId(petSkill)).putLong(prefix + "char_buff", selectedId(charBuff))
                        .putLong(prefix + "pet_buff", selectedId(petBuff));
            }
            e.putLong(prefix + "char_buff_tgt", selectedId(charBuffTgt)).putLong(prefix + "pet_buff_tgt", selectedId(petBuffTgt));
        }

        /** Ghi lựa chọn vào ``o`` (chưa đăng nhập thì lấy lựa chọn đã lưu lần trước). */
        JSONObject put(JSONObject o) throws org.json.JSONException {
            return o.put("pet_id", keep(pet, "pet"))
                    .put("char_skill", withSkills ? keep(charSkill, "char_skill") : 0)
                    .put("pet_skill", withSkills ? keep(petSkill, "pet_skill") : 0)
                    .put("char_buff", keep(charBuff, "char_buff"))
                    .put("char_buff_target", selectedId(charBuffTgt) == 2 ? "char" : "pet")
                    .put("pet_buff", keep(petBuff, "pet_buff"))
                    .put("pet_buff_target", selectedId(petBuffTgt) == 2 ? "char" : "pet");
        }
    }

    private LinearLayout pair(Context c, Spinner a, Spinner b) {
        LinearLayout r = new LinearLayout(c);
        r.setOrientation(LinearLayout.HORIZONTAL);
        LinearLayout.LayoutParams la = new LinearLayout.LayoutParams(0, Ui.dp(c, 44), 2f);
        LinearLayout.LayoutParams lb = new LinearLayout.LayoutParams(0, Ui.dp(c, 44), 1.2f);
        lb.leftMargin = Ui.dp(c, 6);
        r.addView(a, la);
        r.addView(b, lb);
        LinearLayout.LayoutParams lr = new LinearLayout.LayoutParams(-1, -2);
        lr.bottomMargin = Ui.dp(c, 8);
        r.setLayoutParams(lr);
        return r;
    }

    private static LinearLayout.LayoutParams spLp(Context c) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, Ui.dp(c, 44));
        lp.bottomMargin = Ui.dp(c, 8);
        return lp;
    }

    private Spinner spinner(Context c) {
        Spinner sp = new Spinner(c);
        sp.setBackground(Ui.round(c, Ui.FIELD, 8));
        sp.setPadding(Ui.dp(c, 6), 0, 0, 0);
        return sp;
    }

    /** Mỗi spinner giữ danh sách id song song với nhãn (tag). */
    private void setItems(Spinner sp, long[] ids, String[] labels, long selected) {
        ArrayAdapter<String> ad = new ArrayAdapter<String>(getContext(), android.R.layout.simple_spinner_item, labels) {
            @Override public View getView(int pos, View v, android.view.ViewGroup parent) {
                TextView t = (TextView) super.getView(pos, v, parent);
                t.setTextColor(Ui.TEXT);
                t.setTextSize(14);
                t.setSingleLine(true);
                return t;
            }
        };
        ad.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        sp.setTag(ids);
        sp.setAdapter(ad);
        int idx = 0;
        for (int i = 0; i < ids.length; i++) if (ids[i] == selected) idx = i;
        sp.setSelection(idx);
    }

    private static long selectedId(Spinner sp) {
        Object t = sp.getTag();
        if (!(t instanceof long[])) return 0;
        long[] ids = (long[]) t;
        int i = sp.getSelectedItemPosition();
        return i >= 0 && i < ids.length ? ids[i] : 0;
    }

    private static boolean isAttack(int cat) { return cat == 1 || cat == 2 || cat == 3; }
    private static boolean isBuff(int cat) { return cat == 4 || cat == 9 || cat == 19; }

    private void fillSkills(Spinner sp, JSONArray skills, boolean attack, String none, long selected) {
        List<Long> ids = new ArrayList<>();
        List<String> labels = new ArrayList<>();
        ids.add(0L);
        labels.add(none);
        if (skills != null) for (int i = 0; i < skills.length(); i++) {
            JSONObject k = skills.optJSONObject(i);
            if (k == null) continue;
            int cat = k.optInt("cat");
            if (attack ? !isAttack(cat) : !isBuff(cat)) continue;
            ids.add(k.optLong("id"));
            labels.add(k.optString("name") + "  (" + k.optInt("cost") + " SP)");
        }
        long[] a = new long[ids.size()];
        for (int i = 0; i < a.length; i++) a[i] = ids.get(i);
        setItems(sp, a, labels.toArray(new String[0]), selected);
    }

    private static LinearLayout indent(Context c) {
        LinearLayout l = new LinearLayout(c);
        l.setOrientation(LinearLayout.VERTICAL);
        l.setPadding(Ui.dp(c, 32), 0, 0, Ui.dp(c, 4));
        return l;
    }

    private static TextView label(Context c, String s) {
        TextView t = Ui.text(c, s, 13, Ui.DIM);
        t.setPadding(0, Ui.dp(c, 2), 0, Ui.dp(c, 4));
        return t;
    }

    private static void bindToggle(CheckBox cb, View opts) {
        opts.setVisibility(cb.isChecked() ? VISIBLE : GONE);
        cb.setOnCheckedChangeListener((b, on) -> opts.setVisibility(on ? VISIBLE : GONE));
    }

    // ---------- lưu / nạp lựa chọn ----------
    private void restore() {
        user.setText(prefs.getString("user", ""));
        pass.setText(prefs.getString("pw", ""));
        rememberPw.setChecked(prefs.contains("pw"));
        String sv = prefs.getString("server", null);
        int i = sv == null ? -1 : serverIds.indexOf(sv);
        if (i < 0) i = Math.max(0, serverIds.indexOf("ts_realm"));
        if (!serverIds.isEmpty()) server.setSelection(i);
        cWb.setChecked(prefs.getBoolean("wb", true));
        cWbTickets.setChecked(prefs.getBoolean("wb_tickets", true));
        cWbBuy.setChecked(prefs.getBoolean("wb_buy", false));
        wbGoal.setText(prefs.getString("wb_goal", "5000000"));
        cNk.setChecked(prefs.getBoolean("nk", false));
        cNpc.setChecked(prefs.getBoolean("npc", false));
        npcLosses.setText(prefs.getString("npc_losses0", "0"));
        cPbDon.setChecked(prefs.getBoolean("pb_don", false));
        cPbDoi.setChecked(prefs.getBoolean("pb_doi", false));
        pbLevel.setText(prefs.getString("pb_level", "50"));
        cbQty.setText(prefs.getString("cb_qty", "40"));
        cbSlots.setText(prefs.getString("cb_slots", "3"));
        cbRounds.setText(prefs.getString("cb_rounds", "0"));
        cbBreak.setChecked(prefs.getBoolean("cb_break", true));
        cbKeepVal.setText(prefs.getString("cb_keep_val", "27"));
        cbKeepLv.setText(prefs.getString("cb_keep_lv", "0"));
    }

    private void saveChoices() {
        SharedPreferences.Editor e = prefs.edit()
                .putBoolean("wb", cWb.isChecked()).putBoolean("wb_tickets", cWbTickets.isChecked())
                .putBoolean("wb_buy", cWbBuy.isChecked())
                .putString("wb_goal", wbGoal.getText().toString())
                .putBoolean("nk", cNk.isChecked()).putBoolean("npc", cNpc.isChecked())
                .putString("npc_losses0", npcLosses.getText().toString())
                .putBoolean("pb_don", cPbDon.isChecked()).putBoolean("pb_doi", cPbDoi.isChecked())
                .putString("pb_level", pbLevel.getText().toString());
        loWb.save(e);
        loNpc.save(e);
        loNk.save(e);
        e.apply();
    }

    String savedUser() { return prefs.getString("user", ""); }

    void forget() { prefs.edit().clear().apply(); }

    // ---------- hành động ----------
    private void onLoginClick() {
        if (!"offline".equals(state) && !"error".equals(state)) {
            Py.call(r -> poll(), "logout", tab);
            return;
        }
        String u = user.getText().toString().trim();
        String pw = pass.getText().toString();
        if (TextUtils.isEmpty(u) || TextUtils.isEmpty(pw) || serverIds.isEmpty()) {
            toast("Nhập tên đăng nhập và mật khẩu");
            return;
        }
        String sv = serverIds.get(server.getSelectedItemPosition());
        SharedPreferences.Editor e = prefs.edit();
        if (remember.isChecked()) e.putString("user", u).putString("server", sv);
        else e.remove("user").remove("server");
        if (rememberPw.isChecked()) e.putString("pw", pw); else e.remove("pw");
        e.apply();
        if (!rememberPw.isChecked()) pass.setText("");
        state = "logging_in";
        refreshButtons();
        Py.call(r -> { if (!r.optBoolean("ok")) toast(r.optString("error")); poll(); },
                "login", tab, u, pw, sv);
    }

    private void onRunClick() {
        JSONArray feats = buildFeats(false);
        if (feats.length() == 0) {
            toast("Chọn ít nhất một hoạt động");
            return;
        }
        saveChoices();
        Py.call(r -> { if (!r.optBoolean("ok")) toast(r.optString("error")); poll(); },
                "run", tab, feats.toString(), buildOpts().toString());
    }

    private JSONArray buildFeats(boolean partyOnly) {
        JSONArray feats = new JSONArray();
        if (cWb.isChecked() && !partyOnly) feats.put("world_boss");
        if (cNk.isChecked()) feats.put("nhi_kieu");
        if (cNpc.isChecked()) feats.put("npc40");
        if (cPbDon.isChecked() && !partyOnly) feats.put("pb_don");
        if (cPbDoi.isChecked() && !partyOnly) feats.put("pb_doi");
        return feats;
    }

    /** Tuỳ chọn chạy của tab này (đội hình 40 NPC / Nhị Kiều, boss, phó bản). */
    JSONObject buildOpts() {
        JSONObject opts = new JSONObject();
        try {
            opts.put("world_boss", loWb.put(new JSONObject())
                    .put("use_tickets", cWbTickets.isChecked() || cWbBuy.isChecked())
                    .put("auto_buy", cWbBuy.isChecked())
                    .put("damage_goal", num(wbGoal, 5000000)));
            opts.put("loadouts", new JSONObject()
                    .put("npc40", loNpc.put(new JSONObject()))
                    .put("nhi_kieu", loNk.put(new JSONObject())));
            opts.put("max_losses", new JSONObject().put("npc40", Math.max(0, num(npcLosses, 0))).put("nhi_kieu", 0));
            opts.put("team_dungeon_level", num(pbLevel, 50));
        } catch (Exception ignored) {}
        return opts;
    }

    private void onPartyClick() {
        JSONArray feats = buildFeats(true);
        if (feats.length() == 0) {
            toast("Tick 40 NPC hoặc Nhị Kiều trước");
            return;
        }
        if (!"online".equals(state)) {
            toast("Tab này chưa đăng nhập hoặc đang chạy");
            return;
        }
        saveChoices();
        Py.call(r -> {
            JSONArray all = r.optJSONArray("tabs");
            List<String> ids = new ArrayList<>();
            List<String> names = new ArrayList<>();
            for (int i = 0; all != null && i < all.length(); i++) {
                JSONObject t = all.optJSONObject(i);
                if (t == null || tab.equals(t.optString("tab")) || t.optBoolean("busy")) continue;
                ids.add(t.optString("tab"));
                String nm = t.isNull("char") ? t.optString("user") : t.optString("char");
                names.add(nm + "  (map " + t.optString("map") + ")");
            }
            if (ids.isEmpty()) {
                toast("Không có tab nào khác đang đăng nhập và rảnh");
                return;
            }
            boolean[] pick = new boolean[ids.size()];
            java.util.Arrays.fill(pick, true);
            new android.app.AlertDialog.Builder(getContext())
                    .setTitle("Chọn thành viên party")
                    .setMultiChoiceItems(names.toArray(new String[0]), pick, (d, w, on) -> pick[w] = on)
                    .setPositiveButton("Chạy", (d, w) -> startParty(feats, ids, pick))
                    .setNegativeButton("Huỷ", null)
                    .show();
        }, "party_status");
    }

    private void startParty(JSONArray feats, List<String> ids, boolean[] pick) {
        JSONArray mem = new JSONArray();
        JSONObject opts = buildOpts();
        JSONObject per = new JSONObject();
        try {
            for (int i = 0; i < ids.size(); i++) {
                if (!pick[i]) continue;
                mem.put(ids.get(i));
                JSONObject o = listener.optsOf(ids.get(i));
                if (o != null) per.put(ids.get(i), o);
            }
            opts.put("_tabs", per);
        } catch (Exception ignored) {}
        if (mem.length() == 0) {
            toast("Chưa chọn thành viên");
            return;
        }
        Py.call(r -> { if (!r.optBoolean("ok")) toast(r.optString("error")); poll(); },
                "run_party", tab, mem.toString(), feats.toString(), opts.toString());
    }

    private static long num(EditText e, long def) {
        try { return Long.parseLong(e.getText().toString().trim()); } catch (Exception x) { return def; }
    }

    private void toast(String s) {
        if (!TextUtils.isEmpty(s)) Toast.makeText(getContext(), s, Toast.LENGTH_SHORT).show();
    }

    // ---------- cập nhật từ Python (MainActivity gọi mỗi giây) ----------
    private boolean polling;

    void poll() {
        if (polling) return;                       // lượt trước chưa về thì bỏ qua
        polling = true;
        Py.call(r -> { polling = false; applyStatus(r); }, "status", tab);
    }

    private void applyStatus(JSONObject s) {
        String st = s.optString("state", "offline");
        String ch = s.isNull("char") ? "" : s.optString("char", "");
        boolean changed = !st.equals(state) || !ch.equals(charName);
        state = st;
        charName = ch;
        String line = "● " + Ui.stateText(st);
        String task = s.optString("task", "");
        if (!task.isEmpty()) line += " — " + taskName(task);
        if ("error".equals(st) && !s.optString("error").isEmpty()) line += ": " + s.optString("error");
        stateLine.setText(line);
        stateLine.setTextColor(Ui.stateColor(st));
        StringBuilder sb = new StringBuilder();
        if (!ch.isEmpty()) sb.append("Nhân vật: ").append(ch);
        if (!s.isNull("map") && s.has("map")) sb.append("   ·   Map ").append(s.opt("map"));
        JSONArray boss = s.optJSONArray("boss");
        if (boss != null && !boss.isNull(0)) sb.append("   ·   Boss TG ").append(boss.opt(0)).append("/").append(boss.opt(1));
        charLine.setText(sb.toString());
        applyBattle(s.optJSONObject("wb"), s.optJSONObject("battle"));
        applyNpc40(s.optJSONObject("npc40"), "npc40".equals(task));
        applyCombine(s.optJSONObject("combine"));
        JSONObject lo = s.optJSONObject("loadout");
        for (LoadoutBox b : new LoadoutBox[]{loWb, loNpc, loNk}) b.apply(lo);
        if (changed) {
            refreshButtons();
            if (listener != null) listener.onStateChanged(this);
        }
    }

    // ---------- hợp vật phẩm ----------
    private void loadBag() {
        Py.call(r -> {
            if (!r.optBoolean("ok")) { toast(r.optString("error")); return; }
            JSONArray items = r.optJSONArray("items");
            int n = items == null ? 0 : items.length();
            if (n == 0) { toast("Túi chưa có món nào hợp được"); return; }
            long[] ids = new long[n];
            String[] labels = new String[n];
            for (int i = 0; i < n; i++) {
                JSONObject o = items.optJSONObject(i);
                ids[i] = o.optLong("tid");
                labels[i] = o.optString("name") + (o.optInt("lv") > 0 ? "  (lv" + o.optInt("lv") + ")" : "")
                        + "  ×" + n(o.optLong("qty"));
            }
            setItems(cbItem, ids, labels, prefs.getLong("cb_tid", 0));
        }, "bag_list", tab);
    }

    private void onCombineClick() {
        long tid = selectedId(cbItem);
        if (tid == 0) { toast("Bấm Tải danh sách túi rồi chọn vật phẩm"); return; }
        prefs.edit().putLong("cb_tid", tid).putString("cb_qty", cbQty.getText().toString())
                .putString("cb_slots", cbSlots.getText().toString())
                .putString("cb_rounds", cbRounds.getText().toString())
                .putBoolean("cb_break", cbBreak.isChecked())
                .putString("cb_keep_val", cbKeepVal.getText().toString())
                .putString("cb_keep_lv", cbKeepLv.getText().toString()).apply();
        JSONObject o = new JSONObject();
        try {
            o.put("tid", tid).put("qty", num(cbQty, 40)).put("slots", num(cbSlots, 3)).put("rounds", num(cbRounds, 0))
                    .put("decompose", cbBreak.isChecked())
                    .put("keep_bonus", num(cbKeepVal, 27)).put("keep_level", num(cbKeepLv, 0));
        } catch (Exception ignored) {}
        Py.call(r -> { if (!r.optBoolean("ok")) toast(r.optString("error")); poll(); }, "combine", tab, o.toString());
    }

    private void applyCombine(JSONObject o) {
        if (o == null) { cbLine.setVisibility(GONE); return; }
        boolean run = o.optBoolean("running");
        String name = o.optString("name", "");
        int done = o.optInt("done"), rounds = o.optInt("rounds");
        StringBuilder sb = new StringBuilder(run ? "⚗ Đang hợp " : "Hợp xong ");
        sb.append(name).append(": ").append(done).append(rounds > 0 ? "/" + rounds : "").append(" lần");
        if (o.has("left")) sb.append("  ·  còn ").append(n(o.optLong("left")));
        if (o.has("used")) sb.append("  ·  đã dùng ").append(n(o.optLong("used")));
        if (o.optInt("broken") > 0) sb.append("  ·  đã phân giải ").append(o.optInt("broken")).append(" món");
        if (o.optInt("kept") > 0) sb.append("  ·  ⭐ giữ lại ").append(o.optInt("kept")).append(" món");
        if (!run && o.has("why")) sb.append("\n").append(o.optString("why"));
        cbLine.setText(sb.toString());
        cbLine.setTextColor(run ? Ui.OK : Ui.TEXT);
        cbLine.setVisibility(VISIBLE);
    }

    private double npcDoneAt;

    /** Tầng 40 NPC (từ Thắng Lệnh trong túi) khi đang chạy; chạy xong thì báo đi đổi thưởng. */
    private void applyNpc40(JSONObject o, boolean running) {
        JSONObject done = o == null ? null : o.optJSONObject("done");
        int floor = o == null ? 0 : o.optInt("floor", 0);
        if (running) {
            npcLine.setText("40 NPC: đã qua " + floor + "/40 tầng");
            npcLine.setTextColor(Ui.TEXT);
            npcLine.setVisibility(VISIBLE);
        } else if (done != null) {
            int f = done.optInt("floor", floor);
            npcLine.setText("✅ 40 NPC đã xong (" + done.optString("why", "") + ") — qua " + f
                    + "/40 tầng.\nNhớ đi đổi Thắng Lệnh lấy thưởng nha!");
            npcLine.setTextColor(Ui.OK);
            npcLine.setVisibility(VISIBLE);
            double at = done.optDouble("at", 0);
            if (at > 0 && at != npcDoneAt) {
                if (npcDoneAt != 0 || System.currentTimeMillis() / 1000.0 - at < 120)
                    toast("40 NPC xong: qua " + f + "/40 tầng — đi đổi thưởng nha");
                npcDoneAt = at;
            }
        } else {
            npcLine.setVisibility(GONE);
        }
    }

    private static String n(long v) { return String.format(VI, "%,d", v); }

    private void applyBattle(JSONObject wb, JSONObject b) {
        wbLine.setVisibility(wb == null ? GONE : VISIBLE);
        int rows = b == null ? GONE : VISIBLE;
        for (TextView t : new TextView[]{charRow, petRow, bossRow, recentView}) t.setVisibility(rows);
        if (wb != null) {
            String today = wb.isNull("today") ? "?" : n(wb.optLong("today"));
            wbLine.setText("Dame boss hôm nay: " + today + " / " + n(wb.optLong("goal", 5000000))
                    + "   ·   Vé trong túi: " + wb.optInt("tickets"));
        }
        if (b == null) {
            fightLine.setText("Chưa vào trận");
            charRow.setText(""); petRow.setText(""); bossRow.setText(""); recentView.setText("");
            return;
        }
        boolean on = b.optBoolean("active");
        StringBuilder h = new StringBuilder(on ? "⚔ Đang trong trận" : "Không trong trận");
        if (b.optInt("turn") > 0) h.append("  ·  Lượt ").append(b.optInt("turn"));
        if (!b.isNull("turns_left") && b.has("turns_left")) h.append(" (còn ").append(b.optInt("turns_left")).append(")");
        if (!b.isNull("fight_damage") && b.has("fight_damage")) h.append("  ·  Dame trận ").append(n(b.optLong("fight_damage")));
        fightLine.setText(h.toString());
        fightLine.setTextColor(on ? Ui.OK : Ui.TEXT);
        charRow.setText(side("Nhân vật", b.optJSONObject("char")));
        petRow.setText(side("Pet", b.optJSONObject("pet")));
        bossRow.setText(side("Boss", b.optJSONObject("boss")));
        JSONArray rec = b.optJSONArray("recent");
        StringBuilder r = new StringBuilder();
        if (rec != null) for (int i = rec.length() - 1; i >= 0; i--) {      // mới nhất ở trên
            r.append(rec.optString(i));
            if (i > 0) r.append('\n');
        }
        recentView.setText(r.length() == 0 ? "Chưa có lượt đánh nào" : r.toString());
    }

    private static String side(String role, JSONObject o) {
        if (o == null) return role;
        StringBuilder sb = new StringBuilder(role);
        String name = o.optString("name", "");
        if (!name.isEmpty() && !name.equals(role)) sb.append(": ").append(name);
        if (!o.isNull("hp") && o.has("hp"))
            sb.append("   ❤ ").append(n(o.optLong("hp"))).append("/").append(n(o.optLong("hp_max")));
        String sk = o.optString("skill", "");
        if (!sk.isEmpty()) {
            sb.append("\n   ↳ ").append(sk);
            String tg = o.optString("target", "");
            if (!tg.isEmpty()) sb.append(" → ").append(tg);
            long d = o.optLong("dmg", 0);
            if (d > 0) sb.append("  (-").append(n(d)).append(")");
        }
        return sb.toString();
    }

    // ---------- xuất nhật ký ----------
    private void exportLog() {
        Py.call(r -> {
            if (!r.optBoolean("ok")) { toast("Không xuất được: " + r.optString("error")); return; }
            String src = r.optString("path"), name = r.optString("name");
            new Thread(() -> {
                String msg = saveToDownloads(src, name);
                post(() -> toast(msg));
            }, "export-log").start();
        }, "export_log", tab);
    }

    private String saveToDownloads(String src, String name) {
        try (InputStream in = new FileInputStream(src)) {
            if (Build.VERSION.SDK_INT >= 29) {
                ContentResolver cr = getContext().getContentResolver();
                ContentValues v = new ContentValues();
                v.put(MediaStore.MediaColumns.DISPLAY_NAME, name);
                v.put(MediaStore.MediaColumns.MIME_TYPE, "text/plain");
                v.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/TSRealm");
                Uri uri = cr.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
                if (uri == null) return "Không tạo được file trong Download";
                try (OutputStream out = cr.openOutputStream(uri)) { copy(in, out); }
                return "Đã lưu Download/TSRealm/" + name;
            }
            File dir = getContext().getExternalFilesDir(null);
            File f = new File(dir, name);
            try (OutputStream out = new FileOutputStream(f)) { copy(in, out); }
            return "Đã lưu " + f.getAbsolutePath();
        } catch (Exception e) {
            return "Lỗi lưu nhật ký: " + e.getMessage();
        }
    }

    private static void copy(InputStream in, OutputStream out) throws java.io.IOException {
        byte[] buf = new byte[16384];
        int k;
        while ((k = in.read(buf)) > 0) out.write(buf, 0, k);
    }

    private static String taskName(String t) {
        switch (t) {
            case "world_boss": return "Boss Thế Giới";
            case "npc40": return "40 NPC";
            case "nhi_kieu": return "Nhị Kiều";
            case "pb_don": return "Phó bản đơn";
            case "pb_doi": return "Phó bản đội";
            case "combine": return "Hợp vật phẩm";
            default: return t;
        }
    }

    private void refreshButtons() {
        boolean in = "online".equals(state) || "running".equals(state);
        boolean busy = "logging_in".equals(state);
        btnLogin.setText(in ? "Đăng xuất" : busy ? "Huỷ đăng nhập" : "Đăng nhập");
        btnLogin.setBackground(Ui.round(getContext(), in ? Ui.FIELD : Ui.ACCENT, 10));
        btnLogin.setEnabled(true);
        for (View v : new View[]{user, pass, server, remember, rememberPw}) v.setEnabled(!in && !busy);
        btnRun.setEnabled("online".equals(state));
        btnRun.setAlpha("online".equals(state) ? 1f : 0.4f);
        btnParty.setEnabled("online".equals(state));
        btnParty.setAlpha("online".equals(state) ? 1f : 0.4f);
        btnStop.setEnabled("running".equals(state));
        btnStop.setAlpha("running".equals(state) ? 1f : 0.4f);
        actCard.setAlpha(in ? 1f : 0.6f);
        boolean online = "online".equals(state), running = "running".equals(state);
        cbLoad.setEnabled(in);
        cbGo.setEnabled(online);
        cbGo.setAlpha(online ? 1f : 0.4f);
        cbStop.setEnabled(running);
        cbStop.setAlpha(running ? 1f : 0.4f);
        cbCard.setAlpha(in ? 1f : 0.6f);
    }

    String title() {
        if (!charName.isEmpty()) return charName;
        String u = user.getText().toString().trim();
        return u.isEmpty() ? null : u;
    }
}
