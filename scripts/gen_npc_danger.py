"""Sinh bảng NPC nguy hiểm cho realm/npc_danger.py từ dữ liệu game TS Realm.

Lấy file từ điện thoại (game net.tsrealm.game):
    adb pull /storage/emulated/0/Android/data/net.tsrealm.game/files/AssetBundles/Data/IOS_Npc_C.dat
    adb pull /storage/emulated/0/Android/data/net.tsrealm.game/files/AssetBundles/Data/IOS_Skill_C.dat
rồi: python3 scripts/gen_npc_danger.py IOS_Npc_C.dat IOS_Skill_C.dat > realm/npc_danger_table.py

IOS_Npc_C.dat: [n u32] + n bản ghi [độ dài tên u16 (byte)][tên UTF-16LE][u8][mã u16][78 byte]:
    3 skill thường u16 ở +48/+50/+52, đặc kỹ (specialSkill) u16 ở +54 (khớp npc_stats.json /
    npc_special_skills.json của TS Manager: 8353/8360 NPC giống hệt, 7 con BDY khác vì bản VN cũ).

Mức nguy hiểm (cao = đánh trước), xem realm/npc_danger.py.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen_weapon_skills import skill_table  # noqa: E402
from realm import npc_danger  # noqa: E402


def npc_table(path):
    b = open(path, "rb").read()
    n = int.from_bytes(b[:4], "little")
    p, out = 4, {}
    for _ in range(n):
        ln = int.from_bytes(b[p:p + 2], "little")
        name = b[p + 2:p + 2 + ln].decode("utf-16-le")
        p += 2 + ln + 1
        nid = int.from_bytes(b[p:p + 2], "little")
        body = b[p + 2:p + 80]
        p += 80
        skills = [int.from_bytes(body[o:o + 2], "little") for o in (48, 50, 52, 54)]
        out[nid] = (name.strip(), [s for s in skills if s])
    if p != len(b):
        raise SystemExit("IOS_Npc_C.dat: đọc lệch (%d/%d byte)" % (p, len(b)))
    return out


def main(npc_path, skill_path):
    skills = skill_table(skill_path)
    rows = []
    for nid, (name, sk) in sorted(npc_table(npc_path).items()):
        tier, hits = npc_danger.classify(sk, skills)
        if tier:
            rows.append((nid, tier, tuple(hits), name))
    print('"""SINH TỰ ĐỘNG bởi scripts/gen_npc_danger.py từ IOS_Npc_C.dat + IOS_Skill_C.dat (TS Realm)."""')
    print("# mã NPC -> (mức nguy hiểm, skill gây nguy hiểm). %d NPC." % len(rows))
    print("DANGER = {")
    for nid, tier, hits, name in rows:
        print("    %d: (%d, %r),  # %s" % (nid, tier, hits, name))
    print("}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
