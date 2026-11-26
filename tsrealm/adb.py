"""Điều khiển giả lập / điện thoại qua adb: chụp màn hình, bấm, vuốt."""
from __future__ import annotations

import subprocess
import time

import cv2
import numpy as np


class Adb:
    def __init__(self, serial: str = "", adb_path: str = "adb"):
        self.serial = serial
        self.adb_path = adb_path

    def _cmd(self, *args: str) -> list:
        base = [self.adb_path]
        if self.serial:
            base += ["-s", self.serial]
        return base + list(args)

    def screenshot(self, retries: int = 3) -> np.ndarray:
        last = None
        for _ in range(retries):
            try:
                raw = subprocess.run(self._cmd("exec-out", "screencap", "-p"),
                                     capture_output=True, timeout=15, check=True).stdout
                img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    return img
            except Exception as exc:  # adb chập chờn -> thử lại
                last = exc
            time.sleep(0.5)
        raise RuntimeError("Không chụp được màn hình qua adb: %s" % last)

    def tap(self, x: float, y: float) -> None:
        subprocess.run(self._cmd("shell", "input", "tap", str(int(x)), str(int(y))), timeout=10)

    def swipe(self, x1: float, y1: float, x2: float, y2: float, ms: int = 400) -> None:
        subprocess.run(self._cmd("shell", "input", "swipe", str(int(x1)), str(int(y1)),
                                 str(int(x2)), str(int(y2)), str(int(ms))), timeout=10)
