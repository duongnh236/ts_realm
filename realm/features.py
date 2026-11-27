"""Chạy từng hoạt động trên một GameClient đã đăng nhập của ts_bot.

Giờ mở lấy theo APK TS Manager (giờ server UTC+7, sửa được trong settings.json):
  * Boss Thế Giới 10:00–23:00: 5 lượt free, rồi dùng vé trong túi tới khi đủ dame / hết vé.
  * 40 NPC: T2/T4/T6 20:00–23:00. Thua thì hồi đầy máu/mana rồi đánh tiếp tới hết giờ hoặc qua đủ
    40 tầng (``max_losses.npc40`` > 0 thì thua chừng ấy trận liên tiếp mới dừng). Xong thì ghi
    ``client._npc40_summary`` để app báo "đi đổi thưởng".
  * Nhị Kiều: Chủ nhật 08:00–23:00. Leo tháp 12922 -> 12959; thua thì hồi đầy rồi leo tiếp từ tầng
    đang đứng, tới khi bị đưa ra khỏi tháp / hết giờ (``max_losses.nhi_kieu`` > 0 thì giới hạn số lần thua).
  * Phó bản đơn: tới khi server báo xong lượt (tự mua vé theo ts_bot).
  * Phó bản đội: chỉ chủ phòng chạy; tạo phòng theo cấp 20/50/80/110.
"""
from __future__ import annotations

import datetime
import logging
import os
import threading
import time

log = logging.getLogger("bot")

DEFAULT_WINDOWS = {
    "world_boss": {"start": "10:00", "end": "23:00"},
    "npc40": {"days": [0, 2, 4], "start": "20:00", "end": "23:00"},
    "nhi_kieu": {"days": [6], "start": "08:00", "end": "23:00"},
}


def server_now(offset_hours: float = 7.0) -> datetime.datetime:
    return datetime.datetime.utcnow() + datetime.timedelta(hours=offset_hours)


def in_window(win, now=None) -> bool:
    if not win:
        return True
    now = now or server_now(win.get("utc_offset", 7))
    if "days" in win and now.weekday() not in win["days"]:
        return False
    hm = now.strftime("%H:%M")
    return win.get("start", "00:00") <= hm < win.get("end", "24:00")


class Runner:
    def __init__(self, client, config_mod, settings: dict, stop_event: threading.Event):
        self.c = client
        self.config = config_mod
        self.s = settings
        self.stop = stop_event

    # ---- tiện ích ----
    def window(self, name):
        return (self.s.get("windows") or {}).get(name, DEFAULT_WINDOWS.get(name))

    def _cho_phep(self):
        """Trả lý do dừng (chuỗi) hoặc None — kiểu ``cho_phep`` của ts_bot."""
        if self.stop.is_set():
            return "đã bấm dừng"
        if not self.c.running:
            return "mất kết nối"
        return None

    def _support(self, on: bool):
        self.c.state.support_combat = bool(on)
        # ts_bot chỉ ra lệnh đánh khi `auto_combat` bật (nút AUTO BATTLE của nó). Thiếu dòng này
        # bot vào trận boss rồi đứng im tới hết giờ lượt (log 26/11 14:23). Bật trong lúc chạy
        # hoạt động, xong thì trả lại như cũ.
        if on:
            if not hasattr(self, "_auto_combat_before"):
                self._auto_combat_before = bool(getattr(self.c, "auto_combat", False))
            self.c.auto_combat = True
        elif hasattr(self, "_auto_combat_before"):
            self.c.auto_combat = self._auto_combat_before
            del self._auto_combat_before

    def _loadout_on(self, mode):
        """Áp pet / skill đánh / buff người dùng chọn cho ``mode`` (npc40 / nhi_kieu).
        Trả True nếu đã đổi pet (để lúc xong đổi lại)."""
        opts = dict((self.s.get("loadouts") or {}).get(mode) or {})
        from . import combat_rules, loadout
        try:
            loadout.apply(self.c, opts, rules_mod=combat_rules, mode=mode)
        except Exception as exc:
            log.warning("%s: không áp được đội hình (%s) -> đánh tự động", mode, exc)
            return False
        if not int(opts.get("pet_id") or 0) or not hasattr(self.c, "ensure_pet_role"):
            return False
        try:
            self.c.ensure_pet_role(mode)
            return True
        except Exception as exc:
            log.warning("%s: đổi pet lỗi (%s)", mode, exc)
            return False

    def _loadout_off(self, mode, pet_switched):
        from . import combat_rules, loadout
        try:
            loadout.clear(self.c, mode, rules_mod=combat_rules)
        except Exception as exc:
            log.warning("%s: gỡ đội hình lỗi (%s)", mode, exc)
        if pet_switched:
            try:
                self.c.ensure_pet_role(getattr(self.c, "default_pet_role", "train"))
            except Exception as exc:
                log.warning("%s: trả pet lỗi (%s)", mode, exc)

    def _wait_thread(self, thread, win_name=None, done: threading.Event = None):
        while thread is not None and thread.is_alive():
            if self.stop.is_set() or not self.c.running:
                return "dừng"
            if done is not None and done.is_set():
                return "xong"
            if win_name and not in_window(self.window(win_name)):
                return "hết giờ sự kiện"
            time.sleep(2)
        return "xong"

    # ---- hoạt động ----
    def world_boss(self):
        win = self.window("world_boss")
        if not in_window(win):
            log.info("Boss TG: ngoài giờ %s–%s -> bỏ qua", (win or {}).get("start"), (win or {}).get("end"))
            return False
        from . import world_boss as wb
        opts = dict(self.s.get("world_boss") or {})
        runtime = self.s.get("_runtime_dir") or "runtime"
        dlog = wb.DamageLog(os.path.join(runtime, "world_boss_damage.json"))
        day = server_now(7).strftime("%Y-%m-%d")
        account = getattr(self.c, "_username", None) or "acc"
        # ts_bot tự chặn boss ngoài 12h–23h (GameClient._world_boss_event_open, giờ server VN cũ).
        # TS Realm mở boss từ 10h -> cho client dùng khung giờ của ts_realm thay vì giờ cứng đó.
        self.c._world_boss_event_open = lambda: in_window(self.window("world_boss"))
        # Đội hình boss người dùng chọn trong app: pet ra trận, skill đánh, buff
        try:
            from . import combat_rules, loadout
            loadout.apply(self.c, opts, rules_mod=combat_rules)
        except Exception as exc:
            log.warning("[%s] Boss TG: không áp được đội hình (%s) -> đánh tự động", account, exc)
        self._support(True)
        self.c.state.realm_mode = "boss"      # AI TS Manager + skill dame 1 mục tiêu cao nhất (combat_rules)
        try:
            ok, _why = wb.run(self.c, account, day, dlog, opts, cho_phep=self._cho_phep)
            return ok
        finally:
            self.c.state.realm_mode = None
            self._support(False)

    def pb_don(self):
        self._support(True)
        try:
            return self.c.do_daily_dungeon(cho_phep=self._cho_phep)
        finally:
            self._support(False)

    def pb_doi(self):
        level = int(self.s.get("team_dungeon_level", 50))
        self._support(True)
        try:
            return self.c.do_team_dungeon(level)
        finally:
            self._support(False)

    def _event(self, key):
        ev = getattr(self.config, "event_hom_nay", lambda k: self.config.EVENTS.get(k))(key)
        if not ev:
            raise RuntimeError("events.json của ts_bot không có event '%s'" % key)
        return ev

    def npc40(self):
        win = self.window("npc40")
        if not in_window(win):
            log.info("40 NPC: ngoài giờ (T2/T4/T6 %s–%s) -> bỏ qua", (win or {}).get("start"), (win or {}).get("end"))
            return False
        ev = self._event("npc_40")
        if not self.c.go_to_event(ev):
            log.warning("40 NPC: không vào được sân")
            return False
        from . import npc40_loop, npc40_progress
        max_consec = int((self.s.get("max_losses") or {}).get("npc40", 0) or 0)
        self.c._npc40_summary = None
        why = None
        point = tuple(ev["party_battle"]["point"])
        self._support(True)
        self.c.state.quest_mode = True
        self.c.state.realm_mode = "npc40"     # bật AI đánh theo TS Manager (combat_rules)
        pet_switched = self._loadout_on("npc40")
        try:
            t, res = npc40_loop.start(self.c, point, on_loss=lambda: None,
                                      before_repeat=self.c.heal_npc40_between_battles,
                                      window_open=lambda: in_window(self.window("npc40")),
                                      max_consec_losses=max_consec)
            why = self._wait_thread(t)
            why = res.get("why") or why
            log.info("40 NPC: dừng — %s", why)
        finally:
            self.c.stop_npc40_loop()
            tang = npc40_progress.floors_cleared(self.c) or int(getattr(self.c, "_npc40_floor", 0) or 0)
            self.c._npc40_summary = {"floor": tang, "total": npc40_progress.TOTAL_FLOORS,
                                     "why": why or "dừng", "at": time.time()}
            log.info("40 NPC: XONG — đã qua %d/40 tầng, nhớ đi đổi Thắng Lệnh lấy thưởng", tang)
            self.c.state.quest_mode = False
            self.c.state.realm_mode = None
            self._loadout_off("npc40", pet_switched)
            self._support(False)
        return True

    def nhi_kieu(self):
        if not in_window(self.window("nhi_kieu")):
            log.info("Nhị Kiều: ngoài giờ (Chủ nhật 08:00–23:00) -> bỏ qua")
            return False
        ev = self._event("nhi_kieu")
        if not self.c.go_to_event(ev):
            log.warning("Nhị Kiều: không vào được tháp")
            return False
        max_losses = int((self.s.get("max_losses") or {}).get("nhi_kieu", 0) or 0)
        losses = {"n": 0, "last": False}
        done = threading.Event()

        def on_done(lost=False, ly_do="ket"):
            losses["last"] = bool(lost)
            if lost:
                losses["n"] += 1
            log.info("Nhị Kiều: dừng leo (%s, thua %d)", ly_do, losses["n"])
            done.set()

        self._support(True)
        self.c.state.realm_mode = "nhi_kieu"  # chọn bộ buff / skill Nhị Kiều (combat_rules)
        pet_switched = self._loadout_on("nhi_kieu")
        try:
            while not self.stop.is_set():
                done.clear()
                losses["last"] = False
                self.c._floor_crawl_started = False
                if not self.c.start_floor_crawl(ev, on_done=on_done, heal_party=self.c.heal_npc40_between_battles):
                    return False
                why = self._wait_thread(getattr(self.c, "_floor_crawl_thread", None), "nhi_kieu")
                self.c.stop_floor_crawl()
                if why != "xong" or not losses["last"]:
                    break  # leo xong tháp / hết giờ / dừng
                if not in_window(self.window("nhi_kieu")):
                    break
                if max_losses and losses["n"] >= max_losses:
                    log.info("Nhị Kiều: thua đủ %d trận -> bỏ lượt hôm nay (như APK)", max_losses)
                    break
                if not self._in_tower(ev):
                    log.info("Nhị Kiều: thua và đã bị đưa ra khỏi tháp (map %s) -> hết lượt",
                             getattr(self.c, "current_map", None))
                    break
                log.info("Nhị Kiều: thua lần %d -> hồi đầy máu/mana rồi leo tiếp từ tầng đang đứng", losses["n"])
                self.c.heal_npc40_between_battles()
                time.sleep(3)
        finally:
            self.c.stop_floor_crawl()
            self.c.state.realm_mode = None
            self._loadout_off("nhi_kieu", pet_switched)
            self._support(False)
        return True

    def _in_tower(self, ev):
        """Còn đứng trong tháp Nhị Kiều không (dest_map..top_map). Thiếu dữ liệu thì coi như còn."""
        dest = int(ev.get("dest_map") or 0)
        top = int(((ev.get("party_battle") or {}).get("top_map")) or 0)
        try:
            m = int(getattr(self.c, "current_map", 0) or 0)
        except (TypeError, ValueError):
            return True
        if not (dest and top and m):
            return True
        return dest <= m <= top

    ALL = ("world_boss", "nhi_kieu", "npc40", "pb_don", "pb_doi")

    def run(self, names):
        for n in names:
            if self.stop.is_set():
                break
            if n not in self.ALL:
                log.warning("bỏ qua hoạt động lạ: %s", n)
                continue
            log.info("▶ %s", n)
            try:
                ok = getattr(self, n)()
                log.info("■ %s: %s", n, "xong" if ok else "không chạy / chưa xong")
            except Exception as exc:
                log.exception("■ %s lỗi: %s", n, exc)
