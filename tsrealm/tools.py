"""Công cụ làm ảnh mẫu.

  python -m tsrealm.tools snap ten_anh            # chụp màn hình giả lập -> shots/ten_anh.png
  python -m tsrealm.tools crop shots/a.png battle/btn_skill 0.80 0.85 0.88 0.95
                                                   # cắt vùng [trái trên phải dưới] (tỉ lệ) -> templates/
  python -m tsrealm.tools test battle/btn_skill    # thử tìm ảnh mẫu trên màn hình hiện tại
"""
from __future__ import annotations

import json
import os
import sys

import cv2

from .adb import Adb
from .vision import Vision

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cfg():
    p = os.path.join(ROOT, "config.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if not a:
        print(__doc__)
        return
    cfg = _cfg()
    dev = Adb(cfg.get("adb_serial", ""), cfg.get("adb_path", "adb"))
    if a[0] == "snap":
        os.makedirs(os.path.join(ROOT, "shots"), exist_ok=True)
        out = os.path.join(ROOT, "shots", (a[1] if len(a) > 1 else "shot") + ".png")
        img = dev.screenshot()
        cv2.imwrite(out, img)
        print("đã lưu", out, img.shape[1], "x", img.shape[0])
    elif a[0] == "crop":
        src, name = a[1], a[2]
        l, t, r, b = map(float, a[3:7])
        img = cv2.imread(src)
        x0, y0, x1, y1 = Vision.crop_box(img, [l, t, r, b])
        ref = cfg.get("ref_width", 1280)
        piece = img[y0:y1, x0:x1]
        if img.shape[1] != ref:  # đưa ảnh mẫu về chuẩn ref_width
            f = ref / float(img.shape[1])
            piece = cv2.resize(piece, (max(1, int(piece.shape[1] * f)), max(1, int(piece.shape[0] * f))))
        out = os.path.join(ROOT, "templates", name + ".png")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        cv2.imwrite(out, piece)
        print("đã lưu", out)
    elif a[0] == "test":
        v = Vision(os.path.join(ROOT, "templates"), cfg.get("ref_width", 1280), cfg.get("threshold", 0.85))
        img = dev.screenshot()
        for n in a[1:]:
            print(n, v.find(img, n, threshold=0.0))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
