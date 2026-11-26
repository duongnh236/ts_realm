"""Giai khong che cho dong doi va giai buff tren nguoi boss (logic thuan, khong gui packet).

Du lieu skill lay tu bang cua APK TS Manager (assets/tables/cc_skills.json + skill_area.json):
  - fight_way 3/15 = khong che / suy yeu, fight_way 4/9/19 = buff phong thu / tang chi so.
  - fight_way 5 = skill giai hieu ung cho phe ta, 16 = skill pha buff rieng (Giai Ket Gioi, Giai Kinh).

Luat (theo APK):
  * Hon Loan / Ly Gian: o do mat tu chu -> dong doi giai bang Giai Hon Loan (hoac Giai Tru...).
  * Khong che cung (dong bang / troi / choang / ngu): server khoa lenh cua o do -> dong doi giai.
  * Khong che mem (thoi bay / lam cham / giam AGI): khong ton luot giai.
  * Boss co buff phong thu / tang chi so -> o co skill pha buff giai truoc roi moi don dame.
Nguon status: ``state.status_by_kind`` {(row, col): {kind: skill_id}} tu S2C 0x35.
"""

# skill_id -> (loai, ten). loai: chaos | sleep | freeze | lock | soft | poison | debuff
CC_KIND = {
    10004: ('lock', 'Cây Tinh'),
    10025: ('soft', 'Thổ Băng'),
    10033: ('lock', 'Bộc Cầm'),
    11014: ('freeze', 'Băng Phong'),
    11027: ('freeze', 'Thiên Băng Vũ'),
    11028: ('freeze', 'Sương Quyền'),
    11039: ('freeze', 'Băng Siêu'),
    11046: ('chaos', 'Băng Kiếm'),
    12052: ('debuff', 'Hút Hồn'),
    13002: ('soft', 'Tuyền Phong'),
    13007: ('lock', 'Huyền Kích'),
    13011: ('debuff', 'Thu Nhỏ'),
    13015: ('soft', 'Thanh Long'),
    13029: ('lock', 'Sơn Cương'),
    13030: ('debuff', 'Hút Hồn'),
    13040: ('debuff', 'Siêu Nhỏ'),
    13044: ('lock', 'Nhục Bao'),
    13046: ('soft', 'Vô Tận Lam Phong'),
    13050: ('soft', 'Bữa Tiệc'),
    13052: ('soft', 'Thẻ Lốc Xoáy'),
    14008: ('sleep', 'Hôn Mê'),
    14015: ('poison', 'Bỏ Độc'),
    14020: ('chaos', 'Ly Gián'),
    14021: ('chaos', 'Hỗn Loạn'),
    14029: ('soft', 'Cát Phổ Đạn'),
    14065: ('chaos', 'C.Hỗn Loạn'),
    20014: ('chaos', 'Tứ Nhân Hỗn Loạn'),
    20016: ('lock', 'Long Đầu'),
    20020: ('lock', 'Tam Sát'),
    20022: ('debuff', 'Quy Thúc'),
    20023: ('poison', 'Tứ Độc Thủ'),
    20025: ('lock', 'Thụ Tinh'),
    20026: ('freeze', 'Băng Phong'),
    20027: ('soft', 'Hoàn Phong'),
    20047: ('poison', 'Thi Độc Cường'),
    20048: ('soft', 'Toàn Phong Siêu'),
    20049: ('lock', 'Thử Tinh Siêu'),
    20051: ('chaos', 'Cửu Vĩ Hồ Mị Hoặc'),
    20055: ('chaos', 'S.Hỗn Loạn'),
    20058: ('chaos', 'Bàn Thú Đóa Địa'),
    21008: ('poison', 'Độc Phong'),
    21028: ('debuff', 'Nhân Giả Vô Địch'),
    21033: ('lock', 'Sấm Vang'),
    21041: ('chaos', 'Vô Song'),
    21042: ('soft', 'Gia Cát Cuồng Long'),
    22016: ('freeze', 'Đồng Quang Chi Bán'),
    22017: ('freeze', 'Chân-Đồng Quang Chi Bán'),
    23007: ('chaos', 'Vu Độc Oa Oa'),
    23009: ('chaos', 'Mê Hoặc Độc Châm'),
    23011: ('debuff', 'Huyền Vũ'),
    23015: ('lock', 'Trảm Choáng'),
    23022: ('chaos', 'Chân-Mê Hoặc Độc Châm'),
}

# skill_id -> ten. Buff tren nguoi DICH dang de giai (khien, kinh, an than, phan than, tang chi so...).
BOSS_BUFFS = {
    10010: 'Kết Giới',
    10015: 'Kính',
    10020: 'Địa Khí',
    10026: 'Linh Kính',
    10031: 'Chung Trảo',
    10038: 'Song Kính',
    10039: 'Duệ Kính',
    10040: 'Thuẫn Kính',
    10041: 'S.Kết Giới',
    11002: 'Băng Tường',
    11020: 'Thủy Khí',
    11024: 'Đình Thủy',
    11032: 'Vô Tưởng',
    12020: 'Hỏa Khí',
    12024: 'Hỏa Hộ Thân',
    12025: 'Cuồng Nộ',
    12045: 'Nhiệt Hống',
    12053: 'P.HoàngĐản',
    13003: 'Lẫn Tránh',
    13005: 'Ẩn Mình',
    13008: 'Phân Thân',
    13012: 'Phóng To',
    13014: 'Nguyên Khí',
    13019: 'Phong Khí',
    13020: 'Phong Chi',
    13021: 'Đẩu Chuyển',
    13025: 'Vô Hình',
    13032: 'Thân Thuật',
    13042: 'S.Ẩn Thân',
    13049: 'Tuyệt ',
    13051: 'Ba Long Phong Chương ',
    14012: 'Đồng Tâm',
    14013: 'Cổ Vũ',
    14040: 'Bá Ý',
    14044: 'Thiên Thần Thuẫn',
    14046: 'Ngưng Khí Hộ Thân',
    14053: 'Thánh Linh Thuật',
    20024: 'Thập Khí',
    21026: 'Nhân Giả Vô Dịch',
    21037: 'Hải Đồn',
    22006: 'Quang Chi Kính',
    22024: 'Kính Linh',
    22031: 'Lĩnh Vực Ma Vương ',
    22044: 'Băng Tinh Thủ Hộ ',
    22046: 'Hào Quang Thần Tượng',
    23008: 'Yêu Thuật Kích Hóa',
}

# --- Theo Battle AI cua TS Manager ban PC (battle_ai_scenario_generated) ---
# Buff dich DANG giai (ENEMY_DISPEL_WORTHY_BUFF_SKILL_IDS). Buff khac: khong ton luot giai.
DISPEL_WORTHY_BUFFS = frozenset((21026, 10010, 10026, 11002, 13021))   # Nhan Gia Vo Dich, Ket Gioi, Linh Kinh, Bang Tuong, Dau Chuyen
# Buff dich phai giai TRUOC MOI VIEC (yeu cau user 25/11): Dau Chuyen 13021 (he Phong, fight_way 4).
TOP_PRIORITY_DISPEL = frozenset((13021,))
# Dich dang co Ket Gioi: khong dap dame vao, cho giai truoc (DAMAGE_AVOID_ENEMY_BUFF_SKILL_IDS).
DAMAGE_AVOID_BUFFS = frozenset((10010,))
# Thu tu uu tien giai cho dong doi (CLEANSE_ALLY_LADDER): NV he Thuy/Dia > NV he Phong/Hoa > NV khac > Tuong.
# Ma he: 1 Dia, 2 Thuy, 3 Hoa, 4 Phong.
CLEANSE_ALLY_LADDER = ((1, 2), (3, 4))


def ally_ladder_rank(is_player, element=None):
    """0 = giai truoc nhat. ``is_player`` False = tuong/pet."""
    if not is_player:
        return len(CLEANSE_ALLY_LADDER) + 1
    for i, els in enumerate(CLEANSE_ALLY_LADDER):
        if element in els:
            return i
    return len(CLEANSE_ALLY_LADDER)


# Loai khong che dang ton mot luot de giai, theo thu tu uu tien.
CLEANSE_PRIORITY = ("chaos", "freeze", "lock", "sleep", "poison")

# Skill giai cho phe ta: skill_id -> (cac loai giai duoc, so muc tieu: 1 = don, 3 = vung, 6 = ca doi)
CLEANSE_SKILLS = {
    14022: ({"chaos"}, 1),                                           # Giai Hon Loan
    20015: ({"chaos"}, 3),                                           # Tu Nhan Giai Loan
    14007: ({"sleep"}, 1),                                           # Giai Me
    11015: ({"freeze"}, 1),                                          # Tan Bang
    14014: ({"poison"}, 1),                                          # Giai Doc
    11012: ({"chaos", "freeze", "lock", "sleep", "poison", "debuff"}, 1),  # Giai Tru
    20019: ({"chaos", "freeze", "lock", "sleep", "poison", "debuff"}, 1),  # Giai Thoat
    11025: ({"chaos", "freeze", "lock", "sleep", "poison", "debuff"}, 3),  # Trang Giai
    11040: ({"chaos", "freeze", "lock", "sleep", "poison", "debuff"}, 3),  # C.Giai Tru
    11031: ({"chaos", "freeze", "lock", "sleep", "poison", "debuff"}, 6),  # Giai Thuat
}

# Skill pha buff tren nguoi dich: skill_id -> tap buff pha duoc (None = moi buff)
DISPEL_SKILLS = {
    11012: None,                        # Giai Tru
    20050: None,                        # Giai Tru Cuong
    11040: None,                        # C.Giai Tru (vung)
    10009: frozenset((10010, 10041)),   # Giai Ket Gioi
    10014: frozenset((10015, 10026, 10038, 10039, 10040)),  # Giai Kinh
}


def cc_kind(skill_id):
    v = CC_KIND.get(int(skill_id or 0))
    return v[0] if v else None


def skill_label(skill_id):
    v = CC_KIND.get(int(skill_id or 0))
    if v:
        return v[1]
    return BOSS_BUFFS.get(int(skill_id or 0), "#%s" % skill_id)


def _statuses(status_by_kind, pos):
    return [int(s) for s in (status_by_kind.get(pos) or {}).values() if s]


def ally_cc(status_by_kind, ally_rows, alive=None):
    """{(row, col): (loai uu tien nhat, skill_id)} cho moi o phe ta dang dinh khong che dang giai."""
    out = {}
    for pos in status_by_kind or {}:
        if pos[0] not in ally_rows or pos[1] > 5:
            continue
        if alive is not None and pos not in alive:
            continue
        best = None
        for sid in _statuses(status_by_kind, pos):
            k = cc_kind(sid)
            if k in CLEANSE_PRIORITY:
                rank = CLEANSE_PRIORITY.index(k)
                if best is None or rank < best[0]:
                    best = (rank, k, sid)
        if best:
            out[pos] = (best[1], best[2])
    return out


def is_hard_locked(status_by_kind, pos):
    """O nay dang bi khoa lenh (khong che cung / hon loan) -> lenh cua o nay luot nay vo dung."""
    return any(cc_kind(s) in ("chaos", "freeze", "lock", "sleep") for s in _statuses(status_by_kind, pos))


def pick_cleanse(learned, sp, cost_of, victims, priority_rows=(), rank_of=None):
    """Chon (skill, (row, col)) de giai. ``victims`` = ket qua ``ally_cc``.

    Uu tien: o thuoc hang ``priority_rows`` (hang nhan vat) -> loai CC nang hon. Co tu 2 o dinh CC tro len
    thi uu tien skill vung neu giai duoc ca 2.
    """
    if not victims:
        return None
    learned = set(learned or ())
    usable = [(s, kinds, area) for s, (kinds, area) in CLEANSE_SKILLS.items()
              if s in learned and sp >= cost_of(s)]
    if not usable:
        return None
    if rank_of is None:
        def rank_of(pos):
            return 0 if pos[0] in priority_rows else 1
    order = sorted(victims.items(), key=lambda kv: (
        rank_of(kv[0]), CLEANSE_PRIORITY.index(kv[1][0]), kv[0]))
    if len(victims) >= 2:
        for s, kinds, area in sorted(usable, key=lambda x: -x[2]):
            if area > 1 and sum(1 for k, _ in victims.values() if k in kinds) >= 2:
                return s, order[0][0]
    for pos, (kind, _sid) in order:
        # skill chuyen dung (re, chi giai dung loai) truoc skill giai tong hop
        for s, kinds, area in sorted(usable, key=lambda x: (len(x[1]), x[2])):
            if kind in kinds:
                return s, pos
    return None


def enemy_buffs(status_by_kind, enemy_rows, alive=None, worthy_only=False):
    """{(row, col): set(buff_skill_id)} cho moi dich con song dang co buff dang giai.

    ``worthy_only`` = chi tinh 4 buff ma TS Manager cho la dang giai (DISPEL_WORTHY_BUFFS)."""
    pool = DISPEL_WORTHY_BUFFS if worthy_only else BOSS_BUFFS
    out = {}
    for pos in status_by_kind or {}:
        if pos[0] not in enemy_rows or pos[1] > 5:
            continue
        if alive is not None and pos not in alive:
            continue
        b = {s for s in _statuses(status_by_kind, pos) if s in pool}
        if b:
            out[pos] = b
    return out


def pick_dispel(learned, sp, cost_of, buffed):
    """Chon (skill, (row, col)) de giai buff dich. Skill pha rieng (re) truoc, Giai Tru sau."""
    if not buffed:
        return None
    learned = set(learned or ())
    usable = [(s, covers) for s, covers in DISPEL_SKILLS.items() if s in learned and sp >= cost_of(s)]
    if not usable:
        return None
    usable.sort(key=lambda x: (x[1] is None, cost_of(x[0])))
    # dich nhieu buff nhat truoc
    for pos, buffs in sorted(buffed.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        for s, covers in usable:
            if covers is None or buffs & covers:
                return s, pos
    return None


def avoid_damage_targets(status_by_kind, enemy_rows):
    """O dich dang co Ket Gioi -> khong danh vao (cho giai). Tra set((row, col))."""
    return {pos for pos in status_by_kind or {}
            if pos[0] in enemy_rows and any(x in DAMAGE_AVOID_BUFFS for x in _statuses(status_by_kind, pos))}
