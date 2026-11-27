"""NPC nguy hiểm: con nào có skill nguy hiểm thì đánh trước (40 NPC, Nhị Kiều, Boss TG).

Bảng ``DANGER`` (npc_danger_table.py) sinh từ dữ liệu game TS Realm (IOS_Npc_C.dat: 3 skill thường +
đặc kỹ của từng NPC; IOS_Skill_C.dat: số ô / loại skill) bằng scripts/gen_npc_danger.py.

Mức nguy hiểm (cao hơn = đánh trước):
  3  phản dame (Đẩu Chuyển, Kim Chung Tráo / Chung Phản, Kính, Linh Kính, Vạn Hoa Kính, Kính Linh...)
     hoặc khống chế CỨNG diện rộng (hỗn loạn / ngủ / đóng băng / trói, skill trúng >= 5 ô:
     Tứ Nhân Hỗn Loạn, Cửu Vĩ Hồ Mị Hoặc, Vô Song...).
  2  khống chế mềm / độc diện rộng (Bữa Tiệc, Gia Cát Cuồng Long, Tứ Độc Thủ) hoặc có Kết Giới.
  1  skill đánh trúng cả phe ta (số ô 8: Long Trời Lỡ Đất, Vạn Mã Phi Đằng, Băng Thương...).
Số ô (splash) của skill: 1 đơn, 2 dọc, 3 ngang, 5 chữ thập, 6/7 rộng, 8 toàn bộ.

Vị trí -> mã NPC lấy từ ``state.tracker.units`` (roster S:011-005, có template_id), không có thì
``state.enemy_pos_tids`` (gói 0x0b của ts_bot).
"""
from __future__ import annotations

from . import status_logic as sl

try:
    from .npc_danger_table import DANGER
except ImportError:  # pragma: no cover - bảng chưa sinh
    DANGER = {}

# Buff phản dame / phản phép mà NPC tự đặt (lên mình hoặc đồng đội).
REFLECT_SKILLS = frozenset((13021, 10031, 10044, 10015, 10026, 10038, 22006, 22023, 22024, 14085))
BARRIER_SKILLS = frozenset((10010, 10041))   # Kết Giới, S.Kết Giới
HARD_CC = frozenset(("chaos", "sleep", "freeze", "lock"))
SOFT_CC = frozenset(("soft", "poison"))
WIDE_AREA = 5       # số ô >= 5 (chữ thập trở lên)
ALL_AREA = 8


def classify(npc_skills, skill_info):
    """(mức, [skill gây nguy hiểm]) cho danh sách skill của 1 NPC. ``skill_info`` = {mã: {"splash", "cat"}}."""
    tier, hits = 0, []
    for s in npc_skills or ():
        info = skill_info.get(s) or {}
        area, cat = info.get("splash", 0), info.get("cat", 0)
        kind = (sl.CC_KIND.get(s) or (None,))[0]
        t = 0
        if s in REFLECT_SKILLS or (kind in HARD_CC and area >= WIDE_AREA):
            t = 3
        elif (kind in SOFT_CC and area >= WIDE_AREA) or s in BARRIER_SKILLS:
            t = 2
        elif cat in (1, 2) and area == ALL_AREA:
            t = 1
        if t:
            hits.append(s)
            tier = max(tier, t)
    return tier, hits


def tier_of(tid) -> int:
    v = DANGER.get(int(tid or 0))
    return v[0] if v else 0


def enemy_tids(state, pos):
    """Mã NPC của ô ``pos`` (hàng*10+cột) phe địch."""
    tracker = getattr(state, "tracker", None)
    units = getattr(tracker, "units", None) or {}
    u = units.get((pos // 10, pos % 10))
    tid = int(getattr(u, "template_id", 0) or 0) if u is not None else 0
    if tid:
        return {tid}
    return set((getattr(state, "enemy_pos_tids", None) or {}).get(pos, ()) or ())


def danger_of(state, pos) -> int:
    return max((tier_of(t) for t in enemy_tids(state, pos)), default=0)


def pick(state, candidates, min_tier=1):
    """Ô nguy hiểm nhất trong ``candidates`` [(pos, hp)], cùng mức thì con ít máu nhất. None nếu không có."""
    ranked = [(danger_of(state, p), hp, p) for p, hp in candidates]
    ranked = [r for r in ranked if r[0] >= min_tier]
    if not ranked:
        return None
    return min(ranked, key=lambda r: (-r[0], r[1], r[2]))[2]
