"""Vòng đánh theo lượt đọc từ màn hình.

Mỗi lượt, với từng ô của mình (nhân vật, tướng) theo thứ tự:
  1. Ô mình đang bị khống chế cứng -> server khoá lệnh, bỏ qua (như client gốc).
  2. Đồng đội dính Hỗn Loạn / đóng băng / trói / choáng / ngủ / độc -> dùng skill giải.
  3. Boss có buff phòng thủ / tăng chỉ số -> dùng skill giải buff.
  4. Kiểu đánh boss: Sống dai luôn che khiên, Tự động che khi máu thấp, Full công không che.
  5. Còn lại: skill đánh chính lên boss.
Icon trạng thái là ảnh mẫu trong templates/status/, đặt tên theo id skill (``14021.png``)
hoặc theo loại (``chaos_1.png``, ``freeze_1.png``, ``lock_1.png``, ``sleep_1.png``,
``poison_1.png``, ``buff_1.png``).
"""
from __future__ import annotations

import logging
import time
from typing import Dict, Optional, Tuple

from . import status_logic as sl

log = logging.getLogger("tsrealm")

# id đại diện khi ảnh mẫu đặt tên theo loại thay vì theo id skill
KIND_SAMPLE_ID = {"chaos": 14021, "freeze": 11014, "lock": 13007, "sleep": 14008,
                  "poison": 14015, "soft": 13002, "buff": 12025, "shield": 10010, "mirror": 10015}
GUARD_SKILLS = (10010, 10041, 12024, 11002, 13003, 10015, 10026, 10038, 10039, 10040)
STYLES = ("auto", "full_attack", "survive")


def status_id_from_name(name: str) -> Optional[int]:
    stem = name.rsplit("/", 1)[-1].split("_", 1)[0]
    if stem.isdigit():
        return int(stem)
    return KIND_SAMPLE_ID.get(stem)


def parse_pos(key: str) -> Tuple[int, int]:
    a, b = key.split(",")
    return int(a), int(b)


class Battle:
    def __init__(self, bot, profile: dict):
        self.bot = bot
        self.p = profile
        self.vision = bot.vision
        self.ally_slots = {parse_pos(k): v for k, v in profile.get("ally_slots", {}).items()}
        self.enemy_slots = {parse_pos(k): v for k, v in profile.get("enemy_slots", {}).items()}
        self.ally_rows = tuple(profile.get("ally_rows", (2, 3)))
        self.enemy_rows = tuple(profile.get("enemy_rows", (0, 1)))
        self.style = profile.get("style", "auto") if profile.get("style", "auto") in STYLES else "auto"
        self.status_templates = self.vision.names("status/")

    # ---------- đọc màn hình ----------
    def _slot_region(self, point):
        w, h = self.p.get("status_box", (0.09, 0.12))
        x, y = point
        return [max(0.0, x - w / 2), max(0.0, y - h), min(1.0, x + w / 2), min(1.0, y + h * 0.2)]

    def read_status(self, screen) -> Dict[Tuple[int, int], Dict[int, int]]:
        """{(hàng, cột): {i: skill_id}} giống ``status_by_kind`` của bot giao thức."""
        out = {}
        slots = list(self.ally_slots.items()) + list(self.enemy_slots.items())
        th = self.p.get("status_threshold", 0.8)
        for pos, point in slots:
            region = self._slot_region(point)
            found = {}
            for i, name in enumerate(self.status_templates):
                sid = status_id_from_name(name)
                if sid and self.vision.find(screen, name, region, th):
                    found[i] = sid
            if found:
                out[pos] = found
        return out

    def hp_ratio(self, screen, unit: str) -> Optional[float]:
        bar = (self.p.get("units", {}).get(unit) or {}).get("hp_bar")
        if not bar:
            return None
        return self.vision.bar_ratio(screen, bar["region"], bar.get("bgr", (40, 40, 220)), bar.get("tol", 60))

    def sp_value(self, screen, unit: str) -> int:
        cfg = self.p.get("units", {}).get(unit) or {}
        bar = cfg.get("sp_bar")
        if not bar:
            return 10 ** 6  # không đọc được SP -> coi như đủ, game sẽ tự từ chối nếu thiếu
        return int(self.vision.bar_ratio(screen, bar["region"], bar.get("bgr", (220, 120, 40)),
                                         bar.get("tol", 60)) * cfg.get("sp_max", 1000))

    # ---------- quyết định ----------
    def decide(self, unit: str, screen, status) -> Tuple[str, Optional[int], Optional[Tuple[int, int]]]:
        cfg = self.p["units"][unit]
        me = (cfg.get("row", 3), cfg.get("col", 2))
        learned = set(int(s) for s in cfg.get("skills", []))
        sp = self.sp_value(screen, unit)
        cost = lambda s: int(self.p.get("skill_cost", {}).get(str(s), 0))
        if sl.is_hard_locked(status, me):
            return "skip", None, None
        victims = sl.ally_cc(status, self.ally_rows)
        pick = sl.pick_cleanse(learned, sp, cost, victims, priority_rows=(self.p.get("char_row", 3),))
        if pick:
            return "cleanse", pick[0], pick[1]
        buffed = sl.enemy_buffs(status, self.enemy_rows, set(self.enemy_slots))
        pick = sl.pick_dispel(learned, sp, cost, buffed)
        if pick:
            return "dispel", pick[0], pick[1]
        guard = self._guard(unit, screen, status, learned)
        if guard:
            return "guard", guard, me
        # "attack" = skill đánh do người dùng chọn theo thứ tự ưu tiên; rỗng = đánh thường
        for s in cfg.get("attack", []):
            if sp >= cost(int(s)):
                return "attack", int(s), self._boss_target()
        return "attack", None, self._boss_target()

    def _guard(self, unit, screen, status, learned) -> Optional[int]:
        if self.style == "full_attack":
            return None
        guards = [s for s in GUARD_SKILLS if s in learned]
        if not guards:
            return None
        me = tuple(self.p["units"][unit].get("guard_target", (self.p.get("char_row", 3), 2)))
        if any(s in sl.BOSS_BUFFS for s in (status.get(me) or {}).values()):
            return None  # đã có khiên
        if self.style == "survive":
            return guards[0]
        hp = self.hp_ratio(screen, "char")
        if hp is not None and hp <= self.p.get("auto_guard_hp", 0.45):
            return guards[0]
        return None

    def _boss_target(self):
        key = self.p.get("boss_slot")
        if key:
            return parse_pos(key)
        return next(iter(self.enemy_slots), None)

    # ---------- thao tác ----------
    def _point(self, pos):
        pt = self.ally_slots.get(pos) or self.enemy_slots.get(pos)
        return pt

    def act(self, unit, action, skill, target):
        bot = self.bot
        if action == "skip":
            log.info("  %s bị khống chế cứng -> bỏ lệnh lượt này", unit)
            return
        if skill is None:
            bot.tap_template(self.p.get("attack_button", "battle/btn_attack"))
        else:
            bot.tap_template(self.p.get("skill_button", "battle/btn_skill"))
            if not bot.tap_template("skills/%d" % skill, timeout=3):
                log.warning("  thiếu ảnh skill %s (templates/skills/%d.png) -> đánh thường", skill, skill)
                bot.tap_template(self.p.get("close_button", "battle/btn_close"), timeout=1)
                bot.tap_template(self.p.get("attack_button", "battle/btn_attack"))
        pt = self._point(target) if target else None
        if pt:
            bot.tap_ratio(*pt)
        log.info("  %s: %s %s -> ô %s", unit, action, sl.skill_label(skill) if skill else "đánh thường", target)

    # ---------- vòng lặp ----------
    def run(self) -> str:
        bot, p = self.bot, self.p
        max_turns = p.get("max_turns", 80)
        turn = 0
        deadline = time.time() + p.get("max_seconds", 1800)
        while turn < max_turns and time.time() < deadline:
            bot.check_stop()
            screen = bot.shot()
            end = self.vision.find_any(screen, p.get("end", []))
            if end:
                log.info("  hết trận: %s", end.name)
                return end.name
            if not self.vision.find_any(screen, p.get("turn", []), p.get("turn_region")):
                time.sleep(0.5)
                continue
            turn += 1
            status = self.read_status(screen)
            for unit in p.get("turn_order", ["char", "pet"]):
                if unit not in p.get("units", {}):
                    continue
                action, skill, target = self.decide(unit, screen, status)
                log.debug("lượt %d %s: %s", turn, unit, action)
                self.act(unit, action, skill, target)
                time.sleep(p.get("unit_delay", 0.6))
            time.sleep(p.get("turn_delay", 1.5))
        log.warning("  quá %d lượt / quá giờ, thoát vòng đánh", max_turns)
        return "timeout"
