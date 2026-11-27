"""Hồi đầy máu/mana giữa các trận 40 NPC / Nhị Kiều cho CẢ võ tướng phụ và thành viên party.

ts_bot ``heal_npc40_between_battles`` chỉ hồi nhân vật + võ tướng đi theo. Log 27/11 (acc 100653,
tầng 38): đi solo có 8 võ tướng phụ, thua 1 trận là chúng về 1 HP và không ai hồi -> trận sau vào
lượt 1 đã "máu party < 50%", lượt 2 chết gần hết. Thành viên party (``_follow``) bật quest_mode nên
ts_bot cũng không tự hồi sau trận.

Máu võ tướng phụ lấy từ roster trận vừa xong (``battle_tracker.units``: ô có ``master_id`` là mình,
role_kind 4). Hồi bằng thuốc trong túi lên ô võ tướng (``target`` = số ô trong danh sách võ tướng,
giống pet đi theo dùng ``active_pet_slot``).
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger("bot")

PET_KINDS = (4,)


class _Stat:
    def __init__(self, hp, hp_max, sp, sp_max):
        self.hp, self.hp_max, self.sp, self.sp_max = hp, hp_max, sp, sp_max


def _pid(unit) -> int:
    rid = bytes(getattr(unit, "role_id", b"") or b"")
    return int.from_bytes(rid[:2], "little") if len(rid) >= 2 else 0


def _markers(client):
    """{mã võ tướng: số ô} từ danh sách võ tướng S:015-008 (``_pet_skill_rows`` của ts_bot)."""
    out = {}
    for row in list(getattr(client, "_pet_skill_rows", None) or ()):
        try:
            marker, pid = int(row[0]), int(row[1])
        except (TypeError, ValueError, IndexError):
            continue
        if pid and marker > 0:
            out[pid] = marker
    return out


def own_generals(client):
    """[(số ô, mã, BattleUnit)] võ tướng phụ của mình trong trận vừa đánh (cả con đã chết)."""
    tracker = getattr(client, "battle_tracker", None)
    me = bytes(getattr(client, "self_entity", b"") or b"")
    st = getattr(client, "state", None)
    if tracker is None or not me or st is None:
        return []
    active = int(getattr(st, "active_pet_id", 0) or 0)
    markers = _markers(client)
    out = []
    for (row, col), u in list((getattr(tracker, "units", None) or {}).items()):
        if row not in getattr(st, "ally_rows", (2, 3)):
            continue
        if getattr(u, "role_kind", None) not in PET_KINDS:
            continue
        if bytes(getattr(u, "master_id", b"") or b"") != me:
            continue
        pid = _pid(u)
        if not pid or pid == active:
            continue          # võ tướng đi theo: heal_full của ts_bot đã lo
        marker = markers.get(pid)
        if marker is None:
            continue
        out.append((marker, pid, u))
    return sorted(out)


def heal_generals(client):
    """Hồi đầy HP/SP các võ tướng phụ của mình. Mỗi trận chỉ hồi 1 lần (tránh phí thuốc khi
    được gọi 2 lần giữa cùng 2 trận)."""
    st = getattr(client, "state", None)
    if st is None or getattr(st, "in_battle", False) or not getattr(client, "bag_slots", None):
        return 0
    tracker = getattr(client, "battle_tracker", None)
    gen = int(getattr(tracker, "generation", 0) or 0)
    if gen and getattr(client, "_realm_generals_healed_gen", None) == gen:
        return 0
    heal = getattr(client, "_heal_unit", None)
    if heal is None:
        return 0
    n = 0
    for marker, pid, u in own_generals(client):
        hp_max, sp_max = int(getattr(u, "hp_max", 0) or 0), int(getattr(u, "sp_max", 0) or 0)
        # Chết trong trận thì hết trận server hồi về 1 HP
        stat = _Stat(max(1, int(getattr(u, "hp", 0) or 0)), hp_max,
                     max(0, int(getattr(u, "sp", 0) or 0)), sp_max)
        if (not hp_max or stat.hp >= hp_max) and (not sp_max or stat.sp >= sp_max):
            continue
        log.info("[%s] Hồi võ tướng phụ 0x%04x (ô %d): HP %d/%d SP %d/%d", client._label, pid, marker,
                 stat.hp, hp_max, stat.sp, sp_max)
        label = "vo tuong 0x%04x" % pid
        try:
            if hp_max:
                heal(marker, stat, label, "hp_pet", "hp", thr_override=1.0, force=True)
            if sp_max:
                heal(marker, stat, label, "sp_pet", "sp", thr_override=1.0, force=True)
            n += 1
        except Exception as exc:
            log.warning("[%s] Hồi võ tướng phụ 0x%04x lỗi: %s", client._label, pid, exc)
    if gen:
        client._realm_generals_healed_gen = gen
    return n


def heal_one(client):
    """Nhân vật + võ tướng đi theo (ts_bot) rồi tới võ tướng phụ."""
    try:
        client.heal_npc40_between_battles()
    except Exception as exc:
        log.warning("[%s] hồi máu lỗi: %s", getattr(client, "_label", "?"), exc)
    try:
        heal_generals(client)
    except Exception as exc:
        log.warning("[%s] hồi võ tướng phụ lỗi: %s", getattr(client, "_label", "?"), exc)


def heal_party(leader, members=(), timeout=20.0):
    """Đội trưởng hồi cho mình và cho mọi thành viên (mỗi tab một luồng, chạy song song) trước khi
    mở trận kế tiếp."""
    others = [m for m in (members or ()) if m is not leader and getattr(m, "running", False)]
    threads = [threading.Thread(target=heal_one, args=(m,), daemon=True, name="realm-heal") for m in others]
    for t in threads:
        t.start()
    heal_one(leader)
    for t in threads:
        t.join(timeout)
