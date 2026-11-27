"""Ra lệnh cho các võ tướng PHỤ của mình khi đi party (40 NPC / Nhị Kiều).

Đi party mỗi người có nhân vật + võ tướng đi theo + 1-2 võ tướng phụ (realm/pet_order.py). ts_bot chỉ
ra lệnh cho nhân vật và võ tướng đi theo (ô (2, my_atype)), nên server phải chờ hết giờ lượt (~90 giây)
mới cho các võ tướng phụ tự đánh -> mỗi lượt 90 giây, 40 NPC chậm và hay báo "trận bị kẹt" (log
27/11 19:00, ACK của (2,0) (2,4) (3,0) (3,4) tới sau đúng 90 giây).

Game thật: đội trưởng gửi C:050-001 cho cả 4 ô của mình (3,2) (2,0) (2,2) (2,4) mỗi lượt
(capture 27/11 18:21). Võ tướng của ai thì roster S:011-005 ghi ``master_id`` = entity người đó.

Chỉ ra lệnh cho ô có ``master_id`` đúng là mình: gửi lệnh cho ô không phải của mình là server báo
"sửa gói chiến đấu" và khoá acc (ts_bot, sự cố 25/08).
"""
from __future__ import annotations

import logging

log = logging.getLogger("bot")

PET_KINDS = (4,)        # role_kind của võ tướng trong roster


def own_extra_units(client):
    """[(hàng, cột, unit)] võ tướng phụ CỦA MÌNH còn sống trong trận (trừ nhân vật và pet đi theo)."""
    tracker = getattr(client, "battle_tracker", None)
    me = bytes(getattr(client, "self_entity", b"") or b"")
    st = getattr(client, "state", None)
    if tracker is None or not getattr(tracker, "active", False) or not me or st is None:
        return []
    at = getattr(st, "my_atype", None)
    char_row = getattr(st, "char_row", 3)
    pet_row = next((r for r in getattr(st, "ally_rows", (2, 3)) if r != char_row), 2)
    out = []
    for (row, col), u in list((getattr(tracker, "units", None) or {}).items()):
        if row not in getattr(st, "ally_rows", (2, 3)):
            continue
        if (row, col) in ((char_row, at), (pet_row, at)):
            continue
        if getattr(u, "role_kind", None) not in PET_KINDS:
            continue
        if bytes(getattr(u, "master_id", b"") or b"") != me:
            continue
        if not getattr(u, "alive", True) or getattr(u, "hp", 1) <= 0:
            continue
        out.append((row, col, u))
    return sorted(out, key=lambda x: (x[0], x[1]))


def pet_id_of(unit) -> int:
    rid = bytes(getattr(unit, "role_id", b"") or b"")
    return int.from_bytes(rid[:2], "little") if len(rid) >= 2 else 0


def _skills(client, pid):
    try:
        return list(client.pet_usable_skills(pid) or [])
    except Exception:
        return []


def decide(client, combat, row, col, unit, skill_pref=None):
    """Lệnh đánh cho 1 võ tướng phụ: skill người dùng đặt cho con này (nếu đủ SP), không thì skill
    dame cao nhất theo wiki; mục tiêu là con nguy hiểm / ít máu (cùng luật với nhân vật)."""
    from . import combat_rules
    st = client.state
    enemy = sorted(p for p, hp in (getattr(st, "enemy_hp", None) or {}).items() if hp > 0)
    if not enemy:
        return None
    cols = sorted({p % 10 for p in enemy})
    pid = pet_id_of(unit)
    skills = _skills(client, pid)
    sp = int(getattr(unit, "sp", 0) or 0)
    sk = None
    if skill_pref and skill_pref in skills and combat._skill_cost(skill_pref) <= sp:
        sk = skill_pref
    if sk is None:
        n = sum(1 for p in enemy)
        alive_danger = combat_rules._danger_alive(st)
        sk = combat_rules.best_attack_skill(combat, skills, sp, 1 if alive_danger else n)
    pos = combat._lowest_hp_enemy(st, cols)
    if pos is None:
        pos = enemy[0]
    return combat.Decision(row, col, pos % 10, sk, b=pos // 10)


def patch_client(cls) -> None:
    if getattr(cls, "_realm_party_pets_patched", False):
        return
    orig = cls._make_decisions

    def _make_decisions(self, expected_key=None, available_snapshot=None):
        r = orig(self, expected_key, available_snapshot)
        try:
            _send_extras(self, expected_key)
        except Exception as exc:
            log.warning("[%s] lệnh võ tướng phụ lỗi: %s", getattr(self, "_label", ""), exc)
        return r

    cls._make_decisions = _make_decisions
    cls._realm_party_pets_patched = True


def _send_extras(client, expected_key):
    if not getattr(client, "auto_combat", False) or not getattr(client.state, "support_combat", False):
        return
    if not client._is_current_combat_turn(expected_key):
        return
    key = client._combat_turn_key()
    if getattr(client, "_realm_extra_key", None) == key:
        return
    extras = own_extra_units(client)
    if not extras:
        return
    client._realm_extra_key = key
    from train_bot import combat
    prefs = getattr(client, "_realm_pet_skill_pref", None) or {}
    for row, col, u in extras:
        d = decide(client, combat, row, col, u, prefs.get(pet_id_of(u)))
        if d is None:
            continue
        # _send_combat lấy hàng nguồn theo d.unit (3 = hàng nhân vật, 2 = hàng pet)
        if combat._hang_cua(client.state, d.unit) != row:
            log.warning("[%s] bỏ lệnh võ tướng phụ ô (%d,%d): không khớp hàng", client._label, row, col)
            continue
        client._send_combat(d, expected_key=expected_key)
        log.info("[%s] VÕ TƯỚNG PHỤ %s ô (%d,%d) -> %s", client._label, "0x%04x" % pet_id_of(u), row, col, d)


def install(client_module) -> None:
    cls = getattr(client_module, "GameClient", None)
    if cls is not None and hasattr(cls, "_make_decisions"):
        patch_client(cls)
