"""NPC nguy hiểm: con nào có skill nguy hiểm thì đánh trước (40 NPC, Nhị Kiều, Boss TG).

Bảng ``DANGER`` (npc_danger_table.py) sinh từ dữ liệu game TS Realm (IOS_Npc_C.dat: 3 skill thường +
đặc kỹ của từng NPC; IOS_Skill_C.dat: số ô / loại skill) bằng scripts/gen_npc_danger.py.

Mức nguy hiểm (cao hơn = đánh trước), phân theo mô tả skill của wiki TS Realm:
  3  phản sát thương (Đẩu Chuyển, Kính, Vạn Hoa Kính, Chung Trạo, Hỏa Hộ Thân...) hoặc khống chế
     trúng 6-10 mục tiêu (Gọi đại long, Bá Vương Trảm, Gia Cát Cuồng Long Chú...).
  2  phản khống chế (Linh Kính, Thái Quang Kính...), khống chế 4-5 mục tiêu (Tứ Nhân Hỗn Loạn,
     Cửu Vĩ Hồ...) hoặc Kết Giới.
  1  skill đánh toàn đội địch (Long Trời Lỡ Đất, Vạn Mã Phi Đằng, Băng Thương...).
Số ô (splash) của skill: 1 = 1 mục tiêu, 2 = 2 cùng hàng, 3 = 3 một hàng, 4 = 3 nhảy cách,
5 = 5 chữ thập, 6 = 6 mục tiêu, 7 = 5 cùng hàng, 8 = toàn đội địch (khớp wiki).

Vị trí -> mã NPC lấy từ ``state.tracker.units`` (roster S:011-005, có template_id), không có thì
``state.enemy_pos_tids`` (gói 0x0b của ts_bot).
"""
from __future__ import annotations

try:
    from .npc_danger_table import DANGER
except ImportError:  # pragma: no cover - bảng chưa sinh
    DANGER = {}

# Phân loại theo mô tả skill trên wiki TS Realm (https://wiki.tsrealm.net/#/skill, data/wiki/skill.json).
# Phản sát thương: đánh vào là ăn dame dội lại.
REFLECT_DAMAGE = frozenset((
    13021,  # Đẩu Chuyển: chịu 30-50%, dội 50-70% lên cả phe đánh
    10015,  # Kính: phản 100%, vỡ sau 4 lần
    10038,  # Vạn Hoa Kính: Kính cho 2 người cùng cột
    10039,  # Duệ Thổ Kính
    10031,  # Chung Trạo (Kim Chung Tráo): miễn dame + phản 10%
    10044,  # Chung Phản
    12024,  # Hỏa Hộ Thân: phản 30%
    13051,  # Ba Phong Long Chướng
    14059,  # Đằng giáp thuật
    23038,  # Hùng Đồ Phách Nghiệp
))
# Phản khống chế: khống chế / debuff của ta bị dội ngược về người tung.
REFLECT_CC = frozenset((10026, 10040, 22023, 22024, 22031))   # Linh Kính, Thuẫn Thổ Linh Kính, Linh Quang Kính, Thái Quang Kính, Ma Vương Lĩnh Vực
# Khống chế (mất lượt / hỗn loạn) trúng 6-10 mục tiêu.
WIDE_CC = frozenset((
    13017,  # Gọi trung long: trói 6
    13018,  # Gọi đại long: khống chế toàn thể 50%
    13046,  # Vô Tận Lam Phong: 6 người
    14062,  # Thực Hồn Nguyền Chú: nguyền toàn thể
    21041,  # Bá Vương Trảm (Vô Song): hỗn loạn toàn thể
    21042,  # Gia Cát Cuồng Long Chú: khống chế toàn thể
    22022,  # Quyền Khuynh Vạn: tê liệt 6
    22041,  # Yêm Nãi Trương Dực Đức: choáng 50% toàn thể
    22043,  # Ức Mẫu Cuồng Lôi: khống chế 20% toàn thể
    22052,  # Hầu Mao Phân Thân: choáng 50% toàn thể
    41002,  # Khuynh Thế Mị Hồ: hỗn loạn toàn thể
    46001,  # Hét Sập Trường Bản: tê liệt 50% toàn thể
    46002,  # Cuồng Long Phá Nguyệt: khống chế 50% toàn thể
))
# Khống chế trúng 4-5 mục tiêu (chữ thập).
MID_CC = frozenset((13016, 20014, 20051, 13050, 22028, 22004))   # Tiểu trung long, Tứ Nhân Hỗn Loạn, Cửu Vĩ Hồ, Khai Phái Đối La, Băng Tuyết Lôi, Liệt diệm chi quang
BARRIER_SKILLS = frozenset((10010, 10041))   # Kết Giới, S.Kết Giới
ALL_AREA = 8        # splash 8 = toàn đội địch (10 mục tiêu)


def classify(npc_skills, skill_info):
    """(mức, [skill gây nguy hiểm]) cho danh sách skill của 1 NPC. ``skill_info`` = {mã: {"splash", "cat"}}."""
    tier, hits = 0, []
    for s in npc_skills or ():
        info = skill_info.get(s) or {}
        t = 0
        if s in REFLECT_DAMAGE or s in WIDE_CC:
            t = 3
        elif s in REFLECT_CC or s in MID_CC or s in BARRIER_SKILLS:
            t = 2
        elif info.get("cat", 0) in (1, 2) and info.get("splash", 0) == ALL_AREA:
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
