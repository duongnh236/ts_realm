"""Dame tương đối của skill (Boss TG, 40 NPC, Nhị Kiều), theo công thức trên wiki TS Realm.

Wiki ghi cho từng skill: hệ số sức mạnh (vd Long Trời Lỡ Đất x0,78, Liên kích x1,5975), skill đánh
nhiều mục tiêu thì mỗi con chỉ chịu 1/2 hoặc 1/3 dame đòn đơn, và % dame cộng thêm (vd Cường Chấn Điện
+70% ở cấp max). Điểm = hệ số x phần dame mỗi mục tiêu x (1 + % cộng thêm). Không tính chỉ số
Trí / Công của người đánh (coi gốc dame phép và vật lý như nhau). Bảng sinh bởi
scripts/gen_skill_power.py từ data/wiki/skill.json.
"""
from __future__ import annotations

try:
    from .skill_power_table import POWER
except ImportError:  # pragma: no cover
    POWER = {}


def single_target_score(skill) -> float:
    """Điểm dame lên 1 mục tiêu; skill không có trong wiki = 1.0 (như skill đơn thường), skill wiki không
    ghi công thức dame = 0 (chỉ dùng khi không còn skill nào khác, bằng nhau thì xét SP)."""
    p = POWER.get(int(skill))
    if p is None:
        return 1.0
    power, share, bonus = p[:3]
    return power * share * (1.0 + bonus)


def targets(skill) -> int:
    p = POWER.get(int(skill))
    return int(p[3]) if p and len(p) > 3 else 1


def total_score(skill, enemies: int) -> float:
    """Tổng dame ước tính khi phe địch còn ``enemies`` con: dame 1 mục tiêu x số con trúng
    (min(số mục tiêu của skill, số con còn sống), không xét hình dạng vùng đánh)."""
    return single_target_score(skill) * max(1, min(targets(skill), int(enemies or 1)))
