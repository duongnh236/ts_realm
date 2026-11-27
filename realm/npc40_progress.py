"""Tầng 40 NPC đọc từ "Thắng Lệnh" trong túi (giống ``npc40_floors_cleared`` của TS Manager).

Qua tầng N thì server phát vật phẩm "Thắng Lệnh N" (mã đọc từ items_gamedata của ts_bot):
tầng 1–30 = 30014–30043, tầng 31–40 = 30054–30063. Tầng đã qua = Thắng Lệnh số lớn nhất
đang có. Đổi thưởng xong thì lệnh mất khỏi túi nên số tầng về 0.
"""
from __future__ import annotations

TOTAL_FLOORS = 40
VICTORY_ORDER = tuple(range(30014, 30044)) + tuple(range(30054, 30064))
_INDEX = {tid: i for i, tid in enumerate(VICTORY_ORDER)}


def floors_cleared(client) -> int:
    best = 0
    for rec in list((getattr(client, "bag_slots", None) or {}).values()):
        try:
            tid, cnt = int(rec[0]), int(rec[1])
        except (TypeError, ValueError, IndexError):
            continue
        if cnt > 0 and tid in _INDEX:
            best = max(best, _INDEX[tid] + 1)
    return best
