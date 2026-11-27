"""Bảng trạng thái trận cho app: ai đánh skill gì, máu, lượt, dame — thay cho việc đọc nhật ký.

Chỉ đọc, không gửi gói. Gắn vào ``client.battle_tracker.apply`` (sự kiện "action" của ts_bot đã giải
S:050-001 thành nguồn -> đích + skill + máu thay đổi) và ``client._dispatch`` để lấy S:073-004
(dame cộng dồn của trận boss + số lượt còn lại).
"""
from __future__ import annotations

import collections
import logging
import threading

log = logging.getLogger("bot")

HP_ATTR = 25                  # thuộc tính máu trong S:050-001 / S:051-001
ROLE_NAMES = {"char": "Nhân vật", "pet": "Pet", "boss": "Boss", "ally": "Đồng đội"}


def _skill_names():
    try:
        from train_bot import config
        return {int(k): (v or {}).get("name") for k, v in (config.SKILL_INFO or {}).items()}
    except Exception:
        return {}


def _npc_names():
    try:
        from train_bot import config
        return dict(getattr(config, "NPC_NAMES", {}) or {})
    except Exception:
        return {}


class BattleView:
    MAX_RECENT = 8

    def __init__(self, client, skill_names=None, npc_names=None):
        self.c = client
        self._skills = skill_names if skill_names is not None else _skill_names()
        self._npcs = npc_names if npc_names is not None else _npc_names()
        self._lock = threading.Lock()
        self.reset()
        self._hook()

    # ---------- gắn vào client ----------
    def _hook(self):
        tracker = getattr(self.c, "battle_tracker", None)
        if tracker is not None and not getattr(tracker, "_realm_view", None):
            orig_apply = tracker.apply

            def apply(opcode, pkt):
                events = orig_apply(opcode, pkt)
                try:
                    self.on_events(events)
                except Exception:
                    pass
                return events
            tracker.apply = apply
            tracker._realm_view = self
        orig_dispatch = self.c._dispatch

        def _dispatch(opcode, pkt):
            try:
                if opcode == 0x49 and len(pkt) >= 14 and pkt[7] == 0x04:
                    self.on_boss_damage(int.from_bytes(pkt[9:13], "little"), pkt[-1])
            except Exception:
                pass
            return orig_dispatch(opcode, pkt)
        self.c._dispatch = _dispatch

    # ---------- dữ liệu ----------
    def reset(self):
        with getattr(self, "_lock", threading.Lock()):
            self.active = False
            self.turn = 0
            self.turns_left = None
            self.fight_damage = None
            self.last = {}                      # vai -> {"skill", "target", "dmg", "turn"}
            self.recent = collections.deque(maxlen=self.MAX_RECENT)
            self._turn_acts = {}                # (lượt, vị trí nguồn) -> dòng đang gộp

    def _my_col(self):
        st = getattr(self.c, "state", None)
        return int(getattr(st, "my_atype", 2) or 2)

    def role_of(self, pos):
        row, col = pos
        if row in (0, 1):
            return "boss"
        if col == self._my_col():
            return "char" if row == 3 else "pet"
        return "ally"

    def skill_name(self, sid):
        name = self._skills.get(int(sid))
        return name.strip() if name else "skill %d" % int(sid)

    def _unit(self, pos):
        units = getattr(getattr(self.c, "battle_tracker", None), "units", None) or {}
        return units.get(pos)

    def on_boss_damage(self, dmg, left):
        with self._lock:
            self.fight_damage = int(dmg)
            self.turns_left = int(left)

    def on_events(self, events):
        tracker = getattr(self.c, "battle_tracker", None)
        for e in events or ():
            kind = getattr(e, "kind", None)
            if kind == "start":
                self.reset()
                with self._lock:
                    self.active = True
            elif kind == "end":
                with self._lock:
                    self.active = False
                    if self.fight_damage:
                        self.recent.append("Kết trận — dame trận: %s" % format(self.fight_damage, ",").replace(",", "."))
            elif kind == "action":
                self._on_action(e, int(getattr(tracker, "turn", 0) or 0))
        with self._lock:
            if tracker is not None:
                self.active = bool(getattr(tracker, "active", self.active))
                self.turn = int(getattr(tracker, "turn", self.turn) or 0)

    def _on_action(self, e, turn):
        src, dst, sid = tuple(e.source), tuple(e.position), int(e.skill_id)
        payload = getattr(e, "payload", ()) or ()
        changes = payload[3] if len(payload) > 3 else ()
        dmg = 0
        for ch in changes or ():
            try:
                k, delta = ch[0], ch[1]
            except (TypeError, IndexError):
                continue
            if k == HP_ATTR and delta < 0:
                dmg += -int(delta)
        who, tgt = self.role_of(src), self.role_of(dst)
        if who in ("char", "pet") and sid not in self._skills:
            seen = self.__dict__.setdefault("_unknown_seen", set())
            if sid not in seen:
                seen.add(sid)
                # thường là skill vũ khí chuyên dụng / skill mới của TS Realm: thêm vào realm/weapon_skills.py
                log.warning("Trận đấu: %s dùng skill lạ %d (0x%04x) chưa có trong dữ liệu",
                            ROLE_NAMES.get(who, who), sid, sid)
        with self._lock:
            key = (turn, src)
            rec = self._turn_acts.get(key)
            if rec is None or rec["skill"] != sid:
                rec = {"skill": sid, "targets": [], "dmg": 0, "turn": turn, "who": who}
                self._turn_acts[key] = rec
                self.recent.append(rec)
            rec["targets"].append(tgt)
            rec["dmg"] += dmg
            self.last[who] = {"skill": self.skill_name(sid), "target": ROLE_NAMES.get(tgt, tgt),
                              "dmg": rec["dmg"], "turn": turn}
            if len(self._turn_acts) > 64:
                for k in sorted(self._turn_acts)[:32]:
                    self._turn_acts.pop(k, None)

    # ---------- xuất cho app ----------
    def _line(self, rec):
        if isinstance(rec, str):
            return rec
        tg = []
        for t in rec["targets"]:
            name = ROLE_NAMES.get(t, t)
            if name not in tg:
                tg.append(name)
        s = "Lượt %d · %s: %s → %s" % (rec["turn"], ROLE_NAMES.get(rec["who"], rec["who"]),
                                        self.skill_name(rec["skill"]), ", ".join(tg))
        if rec["dmg"]:
            s += "  (-%s)" % format(rec["dmg"], ",").replace(",", ".")
        return s

    def _side(self, role, pos, name):
        u = self._unit(pos) if pos else None
        out = {"name": name, "hp": None, "hp_max": None}
        if u is not None:
            out["hp"], out["hp_max"] = int(u.hp), int(u.hp_max)
            if not name and getattr(u, "name", ""):
                out["name"] = u.name
        out.update(self.last.get(role) or {})
        return out

    def _boss_pos(self):
        units = getattr(getattr(self.c, "battle_tracker", None), "units", None) or {}
        enemies = [p for p, u in units.items() if p[0] in (0, 1)]
        alive = [p for p in enemies if getattr(units[p], "hp", 0) > 0]
        pick = sorted(alive or enemies)
        return pick[0] if pick else None

    def snapshot(self):
        with self._lock:
            col = self._my_col()
            bp = self._boss_pos()
            bu = self._unit(bp) if bp else None
            bname = (getattr(bu, "name", "") or self._npcs.get(int(getattr(bu, "template_id", 0) or 0))
                     or "Boss") if bu is not None else "Boss"
            return {
                "active": bool(self.active),
                "turn": self.turn,
                "turns_left": self.turns_left,
                "fight_damage": self.fight_damage,
                "char": self._side("char", (3, col), getattr(self.c, "char_name", None) or ""),
                "pet": self._side("pet", (2, col), getattr(self.c, "pet_name", None) or ""),
                "boss": self._side("boss", bp, bname),
                "recent": [self._line(r) for r in self.recent],
            }
