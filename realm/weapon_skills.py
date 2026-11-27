"""Skill của vũ khí chuyên dụng (VKCD / Thần Khí) cho pet.

Pet cầm đúng Thần Khí của mình (ô trang bị 3, kind 87, ví dụ Triệu Vân + Long Đảm Thương) thì có
thêm skill (ví dụ "Chấn Điện EX"). Server TS Realm không gửi danh sách skill của pet, còn dữ liệu
game của ts_bot (pets.json / skills_data.json) chỉ có 3 skill thường + đặc kỹ, không có skill của
vũ khí. Vì vậy bot (``pet_usable_skills``) không thấy skill VKCD: Boss TG chọn skill tốn SP nhất
trong 3 skill thường (Loạn Kích), app cũng không cho chọn.

Module này:
  * đọc vũ khí từng pet đang cầm từ gói danh sách pet S:015-008 (bản TS Realm, ThingData 56 byte);
  * thêm skill của vũ khí (bảng ``WEAPON_SKILLS``) vào ``pet_usable_skills`` -> có trong
    ``state.pet_skills`` (Boss TG tự chọn), ``multi_pet_skills`` và ``loadout`` (app chọn đánh/buff);
  * nạp tên / SP / loại skill (bảng ``SKILLS``) vào ``config.SKILL_INFO`` để combat tính được SP và
    biết skill đánh hay buff.

Bảng lấy từ capture thật (trận dùng tay skill VKCD: C:050-001 / S:050-001 ghi mã skill). Thiếu
vũ khí nào thì thêm 1 dòng vào hai bảng dưới, không cần sửa chỗ khác.
"""
from __future__ import annotations

import logging

log = logging.getLogger("bot")

FIT_WEAPON = 3                 # ô trang bị vũ khí (fitType 3)
THING_REALM = 56               # ThingData của TS Realm trong S:015-008

# mã vũ khí -> skill vũ khí đó cho pet cầm nó
WEAPON_SKILLS: dict = {
}

# mã skill -> dữ liệu như skills_data.json (cat: 1/2/3 = đánh, 4/9/19 = buff; splash: số ô)
SKILLS: dict = {
}


def pet_weapons(pkt: bytes) -> dict:
    """{mã pet: mã vũ khí} từ S:015-008 nguyên bản TS Realm (frame đủ header). Sai khuôn -> {}."""
    if len(pkt) < 10 or pkt[6] != 0x0F or pkt[7:9] != b"\x08\x00":
        return {}
    b = pkt[7:]
    out, pos = {}, 3
    for _ in range(b[2]):
        if pos + 35 > len(b):
            return {}
        head = 35 + b[pos + 31]
        size = head + 6 * THING_REALM + 9
        if pos + size > len(b):
            return {}
        pid = int.from_bytes(b[pos + 1:pos + 3], "little")
        w = pos + head + (FIT_WEAPON - 1) * THING_REALM
        out[pid] = int.from_bytes(b[w:w + 2], "little")
        pos += size
    return out


def weapon_skills(weapon_id) -> list:
    return list(WEAPON_SKILLS.get(int(weapon_id or 0)) or ())


def _weapon_of(client, pid):
    w = (getattr(client, "_realm_pet_weapon", None) or {}).get(pid)
    if w:
        return w
    # dự phòng: bảng trang bị pet của ts_bot theo thứ tự pet mang theo (1..4)
    for i, rec in enumerate(list(getattr(getattr(client, "state", None), "carried_pets", None) or ())[:4], 1):
        try:
            if int(rec[0]) == pid:
                return ((getattr(client, "pet_equip_by_fit", None) or {}).get(i) or {}).get(FIT_WEAPON)
        except (TypeError, ValueError, IndexError):
            continue
    return None


def fill_skill_info(config) -> None:
    info = getattr(config, "SKILL_INFO", None)
    if info is None:
        info = {}
        config.SKILL_INFO = info
    for sid, v in SKILLS.items():
        info.setdefault(int(sid), dict(v))


def patch_client(cls) -> None:
    if getattr(cls, "_realm_weapon_patched", False):
        return
    orig_usable = cls.pet_usable_skills
    orig_dispatch = cls._dispatch

    def pet_usable_skills(self, pet_id):
        out = list(orig_usable(self, pet_id) or [])
        try:
            pid = int(pet_id)
            for s in weapon_skills(_weapon_of(self, pid)):
                if s not in out:
                    out.append(s)
        except Exception:
            pass
        return out

    def _dispatch(self, opcode, pkt):
        # chạy TRƯỚC bản vá danh sách pet (bản đó cắt ThingData còn 35 byte rồi gọi ts_bot, ts_bot
        # gọi pet_usable_skills ngay) nên phải biết vũ khí trước
        if opcode == 0x0F and len(pkt) > 9 and pkt[7:9] == b"\x08\x00":
            try:
                ws = pet_weapons(pkt)
                if ws:
                    if not isinstance(getattr(self, "_realm_pet_weapon", None), dict):
                        self._realm_pet_weapon = {}
                    self._realm_pet_weapon.update(ws)
            except Exception:
                pass
        return orig_dispatch(self, opcode, pkt)

    cls.pet_usable_skills = pet_usable_skills
    cls._dispatch = _dispatch
    cls._realm_weapon_patched = True


def install(client_module) -> None:
    cfg = getattr(client_module, "config", None)
    if cfg is not None:
        fill_skill_info(cfg)
    cls = getattr(client_module, "GameClient", None)
    if cls is not None:
        patch_client(cls)
