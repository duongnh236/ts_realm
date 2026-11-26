"""Tìm ảnh mẫu trên ảnh chụp màn hình bằng OpenCV matchTemplate."""
from __future__ import annotations

import os
from typing import Dict, Optional, Sequence, Tuple

import cv2
import numpy as np

Region = Optional[Sequence[float]]  # [trái, trên, phải, dưới] theo tỉ lệ 0..1


class Hit:
    def __init__(self, name: str, x: float, y: float, score: float):
        self.name, self.x, self.y, self.score = name, x, y, score

    def __repr__(self):
        return "Hit(%s, %.0f, %.0f, %.2f)" % (self.name, self.x, self.y, self.score)


class Vision:
    """Ảnh mẫu cắt từ màn hình rộng ``ref_width`` px; màn hình khác cỡ thì tự co giãn."""

    def __init__(self, template_dir: str, ref_width: int = 1280, threshold: float = 0.85):
        self.dir = template_dir
        self.ref_width = ref_width
        self.threshold = threshold
        self._raw: Dict[str, Optional[np.ndarray]] = {}
        self._scaled: Dict[Tuple[str, int], Optional[np.ndarray]] = {}

    def path(self, name: str) -> str:
        return os.path.join(self.dir, name + ".png")

    def has(self, name: str) -> bool:
        return os.path.exists(self.path(name))

    def names(self, prefix: str) -> list:
        """Mọi ảnh mẫu trong thư mục con / tiền tố, ví dụ ``status/``."""
        sub, _, start = prefix.rpartition("/")
        folder = os.path.join(self.dir, sub)
        if not os.path.isdir(folder):
            return []
        out = []
        for f in sorted(os.listdir(folder)):
            if f.endswith(".png") and f.startswith(start):
                out.append((sub + "/" if sub else "") + f[:-4])
        return out

    def _template(self, name: str, screen_w: int) -> Optional[np.ndarray]:
        key = (name, screen_w)
        if key not in self._scaled:
            if name not in self._raw:
                img = cv2.imread(self.path(name), cv2.IMREAD_COLOR)
                self._raw[name] = img
            img = self._raw[name]
            if img is not None and screen_w != self.ref_width:
                f = screen_w / float(self.ref_width)
                img = cv2.resize(img, (max(1, int(img.shape[1] * f)), max(1, int(img.shape[0] * f))),
                                 interpolation=cv2.INTER_AREA)
            self._scaled[key] = img
        return self._scaled[key]

    @staticmethod
    def crop_box(screen: np.ndarray, region: Region) -> Tuple[int, int, int, int]:
        h, w = screen.shape[:2]
        if not region:
            return 0, 0, w, h
        l, t, r, b = region
        return int(l * w), int(t * h), max(int(l * w) + 1, int(r * w)), max(int(t * h) + 1, int(b * h))

    def find(self, screen: np.ndarray, name: str, region: Region = None,
             threshold: Optional[float] = None) -> Optional[Hit]:
        tpl = self._template(name, screen.shape[1])
        if tpl is None:
            return None
        x0, y0, x1, y1 = self.crop_box(screen, region)
        roi = screen[y0:y1, x0:x1]
        if roi.shape[0] < tpl.shape[0] or roi.shape[1] < tpl.shape[1]:
            return None
        res = cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        if score < (self.threshold if threshold is None else threshold):
            return None
        return Hit(name, x0 + loc[0] + tpl.shape[1] / 2.0, y0 + loc[1] + tpl.shape[0] / 2.0, float(score))

    def find_any(self, screen, names, region: Region = None, threshold=None) -> Optional[Hit]:
        for n in names:
            h = self.find(screen, n, region, threshold)
            if h:
                return h
        return None

    @staticmethod
    def bar_ratio(screen: np.ndarray, region: Region, bgr: Sequence[int], tol: int = 60) -> float:
        """Tỉ lệ thanh máu/SP: phần cột có màu gần ``bgr`` trong vùng, tính từ trái sang."""
        x0, y0, x1, y1 = Vision.crop_box(screen, region)
        roi = screen[y0:y1, x0:x1].astype(int)
        mask = (np.abs(roi - np.array(bgr)).sum(axis=2) < tol)
        cols = mask.any(axis=0)
        if not cols.any():
            return 0.0
        return float(np.nonzero(cols)[0].max() + 1) / float(len(cols))
