"""Sinh bảng dame tương đối của skill cho realm/skill_power.py từ wiki TS Realm.

Nguồn: https://wiki.tsrealm.net/data/skill.json (bản sao ở data/wiki/skill.json), trường fx.l là các dòng
mô tả, ví dụ "Hệ số sức mạnh skill: x0,78 ...", "Đánh nhiều mục tiêu: mỗi mục tiêu chịu 1/3 sát thương
đòn đơn.", "Sát thương cộng thêm Lv1..Lv5: 35 / 40 / 45 / 55 / 70% ...".
Chạy: python3 scripts/gen_skill_power.py data/wiki/skill.json > realm/skill_power_table.py
"""
import json
import re
import sys


def _num(s):
    return float(s.replace(",", "."))


def parse(row):
    """(hệ số sức mạnh, phần dame mỗi mục tiêu, % cộng thêm ở cấp cao nhất) hoặc None nếu skill không gây dame."""
    lines = (row.get("fx") or {}).get("l") or []
    if not any(t.startswith("Sát thương tính theo") for t in lines):
        return None
    power, share, bonus = 1.0, 1.0, 0.0
    for t in lines:
        m = re.match(r"Hệ số sức mạnh skill: x([0-9]+(?:,[0-9]+)?)", t)
        if m:
            power = _num(m.group(1))
        m = re.match(r"Đánh nhiều mục tiêu: mỗi mục tiêu chịu ([0-9]+)/([0-9]+)", t)
        if m:
            share = int(m.group(1)) / int(m.group(2))
        if t.startswith("Sát thương cộng thêm"):
            body = t.split("(")[0]
            nums = [_num(x) for x in re.findall(r"([0-9]+(?:,[0-9]+)?)%", body)]
            nums += [_num(x) for x in re.findall(r"([0-9]+(?:,[0-9]+)?)\s*/", body.split(":")[-1])]
            if nums:
                bonus = max(nums) / 100.0
    return round(power, 4), round(share, 4), round(bonus, 4)


def main(path):
    rows = json.load(open(path, encoding="utf-8"))
    out = [(r["id"], parse(r), r["name"]) for r in rows]
    # skill wiki không ghi công thức dame (buff, khống chế, gọi thú dame cố định...) -> 0
    out = [(i, p or (0.0, 0.0, 0.0), n) for i, p, n in out]
    print('"""SINH TỰ ĐỘNG bởi scripts/gen_skill_power.py từ wiki TS Realm (data/wiki/skill.json)."""')
    print("# mã skill -> (hệ số sức mạnh, phần dame mỗi mục tiêu, %% cộng thêm cấp max), 0 = không có công thức dame. %d skill." % len(out))
    print("POWER = {")
    for i, p, n in out:
        print("    %d: %r,  # %s" % (i, p, n.strip()))
    print("}")


if __name__ == "__main__":
    main(sys.argv[1])
