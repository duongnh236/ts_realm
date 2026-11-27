"""Sinh bảng skill vũ khí chuyên dụng cho realm/weapon_skills.py từ dữ liệu game TS Realm.

Lấy file từ điện thoại (game net.tsrealm.game):
    adb pull /storage/emulated/0/Android/data/net.tsrealm.game/files/AssetBundles/Data/IOS_ExclusiveWeapon_C.dat
    adb pull /storage/emulated/0/Android/data/net.tsrealm.game/files/AssetBundles/Data/IOS_Skill_C.dat
rồi: python3 scripts/gen_weapon_skills.py IOS_ExclusiveWeapon_C.dat IOS_Skill_C.dat
In ra hai bảng WEAPON_SKILLS / SKILLS để dán vào realm/weapon_skills.py.

IOS_ExclusiveWeapon_C.dat: [n u32] + n bản ghi 29 byte [vũ khí u16][cấp vũ khí u8][skill u16][cấp skill u8][chỉ số...].
IOS_Skill_C.dat: mỗi skill [độ dài tên u16][tên UTF-16LE][u8][mã u16] rồi SP u16 @0, hệ @2, loại (cat) @9, số ô @10.
"""
import sys


def exclusive_weapons(path):
    b = open(path, "rb").read()
    n = int.from_bytes(b[:4], "little")
    out = {}
    for i in range(n):
        r = b[4 + i * 29:4 + (i + 1) * 29]
        w, lv, s = int.from_bytes(r[0:2], "little"), r[2], int.from_bytes(r[3:5], "little")
        if s:
            steps = out.setdefault(w, [])
            if not steps or steps[-1][1] != s:
                steps.append((lv, s))
    return out


def skill_table(path):
    b = open(path, "rb").read()
    out = {}
    for st in range(2, len(b) - 32):
        ln = int.from_bytes(b[st - 2:st], "little")
        if not 2 <= ln <= 60 or ln % 2:
            continue
        try:
            name = b[st:st + ln].decode("utf-16-le")
        except UnicodeDecodeError:
            continue
        if not name.strip() or not all(c.isprintable() for c in name):
            continue
        sid = int.from_bytes(b[st + ln + 1:st + ln + 3], "little")
        p = st + ln + 3
        if 10000 <= sid <= 60000 and sid not in out:
            out[sid] = {"name": name.strip(" ,"), "cost": int.from_bytes(b[p:p + 2], "little"),
                        "cat": b[p + 9], "splash": b[p + 10], "element": b[p + 2]}
    return out


def main(excl_path, skill_path):
    ws, sk = exclusive_weapons(excl_path), skill_table(skill_path)
    used = set()
    print("WEAPON_SKILLS = {")
    for w in sorted(ws):
        steps = tuple(st for st in ws[w] if sk.get(st[1], {}).get("cat"))   # cat 0 = bị động, không dùng được
        if steps:
            used.update(s for _, s in steps)
            print("    %d: %r," % (w, steps))
    print("}\n\nSKILLS = {")
    for s in sorted(used):
        print("    %d: %r," % (s, sk[s]))
    print("}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
