"""Skill thêm của pet: vũ khí chuyên dụng (VKCD / Thần Khí) và Linh Hồn đang mang.

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

Bảng sinh từ dữ liệu game TS Realm (IOS_ExclusiveWeapon_C.dat: vũ khí + cấp -> skill), chạy lại
scripts/gen_weapon_skills.py khi game cập nhật. Cấp vũ khí = ThingData +18 (enhanceLv); cấp 0 chưa
có skill.

Linh Hồn: server gửi S:120-008 (danh sách Linh Hồn của nhân vật) lúc đăng nhập, mỗi Linh Hồn ghi đang
gắn cho pet nào và 1..4 skill (vd Triệu Vân mang Linh hồn Trương Giác: Vô Hình + Phong Thần). Các skill
đó là skill thường đã có trong skills_data.json nên chỉ cần thêm vào danh sách skill của pet.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("bot")

FIT_WEAPON = 3                 # ô trang bị vũ khí (fitType 3)
THING_REALM = 56               # ThingData của TS Realm trong S:015-008

# Sinh bởi scripts/gen_weapon_skills.py từ IOS_ExclusiveWeapon_C.dat + IOS_Skill_C.dat của game TS
# Realm (27/11). Vũ khí -> ((cấp vũ khí tối thiểu, skill), ...): skill là cái của bậc cao nhất mà cấp
# vũ khí đạt tới (vài vũ khí đổi skill ở cấp 6/7). Đã bỏ skill bị động (cat 0).
# Ví dụ Long Đảm Thương 64515 (Triệu Vân) cấp >= 1 -> 13043 Cường Chấn Điện (game hiện "Chấn Điện EX").
WEAPON_SKILLS: dict = {
    64502: ((7, 22032),),
    64503: ((1, 11041),),
    64504: ((1, 14064),),
    64506: ((1, 11040),),
    64507: ((1, 12046),),
    64508: ((1, 12048),),
    64511: ((1, 14065),),
    64512: ((1, 14063),),
    64513: ((1, 12050),),
    64514: ((1, 14063),),
    64515: ((1, 13043),),
    64518: ((1, 12049),),
    64519: ((1, 11039),),
    64520: ((1, 13041),),
    64521: ((0, 11039),),
    64523: ((1, 10039),),
    64525: ((1, 10040),),
    64527: ((1, 12049),),
    64529: ((1, 13042),),
    64531: ((1, 10041),),
    64532: ((1, 10040),),
    64534: ((1, 12047),),
    64535: ((6, 11046),),
    64536: ((6, 11045),),
    64539: ((1, 11039),),
    64540: ((1, 13041),),
    64541: ((1, 12052),),
    64543: ((1, 12047),),
    64544: ((1, 14063),),
    64549: ((1, 12047),),
    64553: ((1, 13043),),
    64554: ((1, 13041),),
    64561: ((1, 11041),),
    64562: ((1, 10039),),
    64564: ((1, 11040),),
    64571: ((1, 12048),),
    64572: ((1, 14063),),
    64573: ((1, 23024),),
    64574: ((1, 11042),),
    64576: ((1, 10042),),
    64577: ((1, 23027),),
    64578: ((1, 11044),),
    64580: ((1, 12050),),
    64581: ((1, 13046),),
    64588: ((1, 10045),),
    64590: ((1, 13051),),
    64592: ((1, 22032),),
    64595: ((1, 11049),),
    64597: ((0, 12058),),
    64601: ((1, 23035),),
    64602: ((1, 23036),),
    64603: ((1, 23037),),
    64604: ((1, 41001),),
    64605: ((1, 41002),),
    64606: ((1, 41003),),
    64607: ((1, 41004),),
    64608: ((1, 45001),),
    64609: ((1, 51001),),
    64610: ((1, 45002),),
    64611: ((1, 45003),),
    64612: ((1, 45004),),
    64614: ((1, 46005),),
}

# vũ khí -> võ tướng chủ (mã bản gốc rb0, cột +86 của Item_C). Pet khác cầm thì không có skill
# ("chỉ có Triệu Vân mới phát huy được toàn bộ sức mạnh"). So theo tên trong pets.json, bỏ " rbN".
WEAPON_OWNER: dict = {
    64501: 10001,
    64502: 10002,
    64503: 13014,
    64504: 12022,
    64505: 11010,
    64506: 13009,
    64507: 14101,
    64508: 11047,
    64509: 12033,
    64510: 11063,
    64511: 12094,
    64512: 12017,
    64513: 14009,
    64514: 12020,
    64515: 12027,
    64516: 13002,
    64517: 11248,
    64518: 11144,
    64519: 14490,
    64520: 14583,
    64521: 13019,
    64522: 14503,
    64523: 14054,
    64524: 11031,
    64525: 11091,
    64526: 13021,
    64527: 11053,
    64528: 12041,
    64529: 12012,
    64530: 12001,
    64531: 27039,
    64532: 13037,
    64533: 13036,
    64534: 13038,
    64535: 14200,
    64536: 11074,
    64537: 14597,
    64538: 14520,
    64539: 14096,
    64540: 12043,
    64541: 14409,
    64542: 15277,
    64543: 11020,
    64544: 11034,
    64545: 11045,
    64547: 11024,
    64548: 11050,
    64549: 11021,
    64550: 11026,
    64553: 12066,
    64554: 12042,
    64555: 12059,
    64556: 12015,
    64557: 13005,
    64558: 13008,
    64559: 13003,
    64560: 13016,
    64561: 13012,
    64562: 10001,
    64563: 10232,
    64564: 10002,
    64565: 10003,
    64566: 14066,
    64567: 14489,
    64568: 14487,
    64570: 14024,
    64571: 14488,
    64572: 14366,
    64573: 15493,
    64574: 41550,
    64575: 15478,
    64576: 15479,
    64577: 45437,
    64578: 15495,
    64579: 15494,
    64580: 15496,
    64581: 11249,
    64582: 12179,
    64583: 14747,
    64587: 14748,
    64588: 22113,
    64589: 12219,
    64590: 22114,
    64591: 11252,
    64592: 45511,
    64593: 22117,
    64594: 14749,
    64595: 45510,
    64596: 22119,
    64597: 22118,
    64598: 45513,
    64599: 45516,
    64600: 11251,
    64601: 13170,
    64602: 11253,
    64603: 45514,
    64604: 27217,
    64605: 27214,
    64606: 27218,
    64607: 27219,
    64608: 45520,
    64609: 12220,
    64610: 45523,
    64611: 14750,
    64612: 45525,
    64613: 11254,
    64614: 45526,
}

# mã skill -> dữ liệu như skills_data.json, lấy từ Skill_C của TS Realm (cat 1/2/3 = đánh, 4/9/19 = buff)
SKILLS: dict = {
    10039: {'name': 'Duệ Thổ Kính', 'cost': 40, 'cat': 4, 'splash': 1, 'element': 1},
    10040: {'name': 'Thuẫn Thổ Linh Kính', 'cost': 50, 'cat': 4, 'splash': 1, 'element': 1},
    10041: {'name': 'Thâm Uyên Kết Giới', 'cost': 33, 'cat': 4, 'splash': 1, 'element': 1},
    10042: {'name': 'Hữu Khách Lai', 'cost': 72, 'cat': 21, 'splash': 2, 'element': 1},
    10045: {'name': 'Nhân Ba Vô Địch', 'cost': 262, 'cat': 2, 'splash': 6, 'element': 1},
    11039: {'name': 'Cường Băng Phong', 'cost': 40, 'cat': 3, 'splash': 1, 'element': 2},
    11040: {'name': 'Cường Trạng Giải', 'cost': 48, 'cat': 5, 'splash': 3, 'element': 2},
    11041: {'name': 'Trảm Kỵ', 'cost': 60, 'cat': 1, 'splash': 1, 'element': 2},
    11042: {'name': 'Thiên Băng Tích', 'cost': 120, 'cat': 7, 'splash': 3, 'element': 2},
    11044: {'name': 'Tam Diện Mai Phục', 'cost': 72, 'cat': 1, 'splash': 4, 'element': 2},
    11045: {'name': 'Trì Độn Băng Kiếm', 'cost': 28, 'cat': 1, 'splash': 1, 'element': 2},
    11046: {'name': 'Hỗn Loạn Băng Kiếm', 'cost': 28, 'cat': 1, 'splash': 1, 'element': 2},
    11049: {'name': 'Lĩnh Mệnh', 'cost': 250, 'cat': 8, 'splash': 6, 'element': 2},
    12046: {'name': 'Cuồng Lôi Liệt Kích', 'cost': 54, 'cat': 2, 'splash': 7, 'element': 3},
    12047: {'name': 'Cự Long Tàn Nhật', 'cost': 66, 'cat': 1, 'splash': 1, 'element': 3},
    12048: {'name': 'Sí Diệc Dung Hỏa', 'cost': 48, 'cat': 2, 'splash': 5, 'element': 3},
    12049: {'name': 'Siêu Hỏa Tiễn', 'cost': 23, 'cat': 1, 'splash': 3, 'element': 3},
    12050: {'name': 'Viêm Dương Loạn Vũ', 'cost': 105, 'cat': 1, 'splash': 4, 'element': 3},
    12052: {'name': 'Hấp Hồn Địa Ngục', 'cost': 101, 'cat': 15, 'splash': 7, 'element': 3},
    12058: {'name': 'Long Tức - Thuấn Sát', 'cost': 210, 'cat': 2, 'splash': 4, 'element': 3},
    13041: {'name': 'Cường Lực Huyền Kích', 'cost': 31, 'cat': 1, 'splash': 2, 'element': 4},
    13042: {'name': 'Siêu Ẩn Mình', 'cost': 22, 'cat': 4, 'splash': 1, 'element': 4},
    13043: {'name': 'Cường Chấn Điện', 'cost': 72, 'cat': 1, 'splash': 4, 'element': 4},
    13046: {'name': 'Vô Tận Lam Phong', 'cost': 128, 'cat': 3, 'splash': 6, 'element': 4},
    13051: {'name': 'Ba Phong Long Chướng', 'cost': 285, 'cat': 4, 'splash': 2, 'element': 1},
    14063: {'name': 'Nộ Hét', 'cost': 20, 'cat': 2, 'splash': 2, 'element': 5},
    14064: {'name': 'Kích Tâm Thuấn Thi', 'cost': 24, 'cat': 1, 'splash': 1, 'element': 5},
    14065: {'name': 'Cường Lực Hỗn Loạn', 'cost': 25, 'cat': 15, 'splash': 2, 'element': 5},
    22032: {'name': 'Thuấn Vịnh Thi Tâm', 'cost': 163, 'cat': 2, 'splash': 1, 'element': 2},
    23024: {'name': 'Hắc Lôi Trảm', 'cost': 72, 'cat': 1, 'splash': 4, 'element': 8},
    23027: {'name': 'Hắc Quang Nhất Thiểm', 'cost': 118, 'cat': 2, 'splash': 6, 'element': 8},
    23035: {'name': 'Mộc Thánh Hộ Hữu', 'cost': 280, 'cat': 7, 'splash': 7, 'element': 2},
    23036: {'name': 'Kiếm Chí Phá Thiên', 'cost': 165, 'cat': 1, 'splash': 3, 'element': 4},
    23037: {'name': 'Tích Lý Ba Lạp', 'cost': 210, 'cat': 2, 'splash': 1, 'element': 3},
    41001: {'name': 'Kiếm Trảm Cửu Thiên', 'cost': 320, 'cat': 2, 'splash': 8, 'element': 7},
    41002: {'name': 'Khuynh Thế Mị Hồ', 'cost': 320, 'cat': 2, 'splash': 8, 'element': 8},
    41003: {'name': 'Sí Diệm Phá Thiên', 'cost': 162, 'cat': 1, 'splash': 1, 'element': 3},
    41004: {'name': 'Tiên Quyết·Phá Ma Trảm', 'cost': 128, 'cat': 2, 'splash': 1, 'element': 1},
    45001: {'name': 'Xích Xà Đoạt Hồn', 'cost': 84, 'cat': 1, 'splash': 1, 'element': 3},
    45002: {'name': 'Cuồng Long Phong Thực', 'cost': 166, 'cat': 15, 'splash': 7, 'element': 4},
    45003: {'name': 'Khuynh Quốc Khuynh Thành', 'cost': 163, 'cat': 2, 'splash': 1, 'element': 2},
    45004: {'name': 'Lạc Thần Mệnh Lệnh', 'cost': 250, 'cat': 8, 'splash': 6, 'element': 2},
    46005: {'name': 'Thiết Cầu Xung Trận', 'cost': 230, 'cat': 2, 'splash': 7, 'element': 1},
    51001: {'name': 'Tam Lược Phạt Mưu', 'cost': 72, 'cat': 1, 'splash': 4, 'element': 1},
}


_CONFIG = [None]               # train_bot.config (install đặt vào)
SOUL_REC = 53                  # S:120-008: [n u16] + n bản ghi 53 byte
SOUL_PET, SOUL_SKILLS = 11, 40 # +11 pet đang mang (0 = chưa gắn), +40 4 x [skill u16][cấp u8]


def pet_souls(pkt: bytes) -> dict:
    """{mã pet: [skill...]} từ S:120-008 (frame đủ header). Bản ghi 53 byte (capture 27/11, 2 acc):
    +0 mã riêng u16 | +2 chủ u32 | +8 mã Linh Hồn u16 | +10 phẩm | +11 pet u16 | +16 chỉ số | +40 skill."""
    if len(pkt) < 11 or pkt[6] != 0x78 or pkt[7:9] != b"\x08\x00":
        return None
    b = pkt[7:]
    n = int.from_bytes(b[2:4], "little")
    if 4 + n * SOUL_REC > len(b):
        return None
    out = {}
    for i in range(n):
        r = b[4 + i * SOUL_REC:4 + (i + 1) * SOUL_REC]
        pid = int.from_bytes(r[SOUL_PET:SOUL_PET + 2], "little")
        if not pid:
            continue
        for k in range(4):
            o = SOUL_SKILLS + 3 * k
            sid = int.from_bytes(r[o:o + 2], "little")
            if sid and sid not in out.setdefault(pid, []):
                out[pid].append(sid)
    return out


def soul_skills(client, pid) -> list:
    """Skill Linh Hồn của pet, chỉ skill bot có dữ liệu và dùng chủ động được (cat khác 0)."""
    info = getattr(_CONFIG[0], "SKILL_INFO", None) or {}
    out = []
    for sid in (getattr(client, "_realm_pet_soul", None) or {}).get(pid) or ():
        if (info.get(sid) or {}).get("cat"):
            out.append(sid)
    return out


ENHANCE_LV = 18                # ThingData +18 enhanceLv (Logic_Item.lua) = cấp vũ khí chuyên dụng


def pet_weapons(pkt: bytes) -> dict:
    """{mã pet: (mã vũ khí, cấp)} từ S:015-008 nguyên bản TS Realm (frame đủ header). Sai khuôn -> {}."""
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
        out[pid] = (int.from_bytes(b[w:w + 2], "little"), b[w + ENHANCE_LV])
        pos += size
    return out


def weapon_skills(weapon_id, level=None) -> list:
    """Skill vũ khí ``weapon_id`` cho ở cấp ``level`` (None = không rõ cấp -> coi như cấp 1)."""
    lv = 1 if level is None else int(level)
    pick = None
    for need, sid in WEAPON_SKILLS.get(int(weapon_id or 0)) or ():
        if lv >= need:
            pick = sid
    return [pick] if pick else []


def _base_name(pid):
    name = (getattr(_CONFIG[0], "PET_NAMES", None) or {}).get(int(pid or 0)) or ""
    return re.sub(r"\s+rb\d+$", "", name.strip())


def owns_weapon(pid, weapon_id) -> bool:
    """Pet ``pid`` có phải chủ của Thần Khí ``weapon_id`` không. Thiếu dữ liệu tên -> coi là có."""
    owner = WEAPON_OWNER.get(int(weapon_id or 0))
    if not owner:
        return True
    a, b = _base_name(pid), _base_name(owner)
    return not a or not b or a == b


def _weapon_of(client, pid):
    """(mã vũ khí, cấp) pet ``pid`` đang cầm, không có -> (None, None)."""
    got = (getattr(client, "_realm_pet_weapon", None) or {}).get(pid)
    if got and got[0]:
        return got
    # dự phòng: bảng trang bị pet của ts_bot theo thứ tự pet mang theo (1..4), không có cấp
    for i, rec in enumerate(list(getattr(getattr(client, "state", None), "carried_pets", None) or ())[:4], 1):
        try:
            if int(rec[0]) == pid:
                return ((getattr(client, "pet_equip_by_fit", None) or {}).get(i) or {}).get(FIT_WEAPON), None
        except (TypeError, ValueError, IndexError):
            continue
    return None, None


def fill_skill_info(config) -> None:
    """Dữ liệu skill VKCD lấy theo TS Realm (vài skill SP khác bản VN của ts_bot, vd Thiên Băng Tích 120)."""
    info = getattr(config, "SKILL_INFO", None)
    if info is None:
        info = {}
        config.SKILL_INFO = info
    for sid, v in SKILLS.items():
        cur = info.setdefault(int(sid), {})
        cur.update(v)


def patch_client(cls) -> None:
    if getattr(cls, "_realm_weapon_patched", False):
        return
    orig_usable = cls.pet_usable_skills
    orig_dispatch = cls._dispatch

    def pet_usable_skills(self, pet_id):
        out = list(orig_usable(self, pet_id) or [])
        try:
            pid = int(pet_id)
            w, lv = _weapon_of(self, pid)
            wsk = weapon_skills(w, lv) if owns_weapon(pid, w) else []
            for s in wsk + soul_skills(self, pid):
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
        elif opcode == 0x78 and len(pkt) > 9 and pkt[7:9] == b"\x08\x00":
            try:
                souls = pet_souls(pkt)
                if souls is not None:
                    self._realm_pet_soul = souls
                    st = getattr(self, "state", None)
                    pid = getattr(st, "active_pet_id", None)
                    if st is not None and pid:
                        st.pet_skills = self.pet_usable_skills(pid)
                    if souls:
                        log.info("[%s] Linh Hồn: %s", getattr(self, "_label", ""),
                                 {"0x%04x" % p: v for p, v in souls.items()})
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
        _CONFIG[0] = cfg
    cls = getattr(client_module, "GameClient", None)
    if cls is not None:
        patch_client(cls)
