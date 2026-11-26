"""Chạy kịch bản JSON trong flows/<tên>.json trên giả lập."""
from __future__ import annotations

import datetime
import json
import logging
import os
import threading
import time
from typing import List, Optional

from .battle import Battle
from .vision import Vision

log = logging.getLogger("tsrealm")


class StopFlow(Exception):
    pass


def in_window(win: Optional[dict], now: Optional[datetime.datetime] = None) -> bool:
    """win = {"days": [0..6] (0 = thứ 2), "start": "HH:MM", "end": "HH:MM", "utc_offset": 7}."""
    if not win:
        return True
    off = win.get("utc_offset", 7)
    now = now or (datetime.datetime.utcnow() + datetime.timedelta(hours=off))
    if "days" in win and now.weekday() not in win["days"]:
        return False
    hm = now.strftime("%H:%M")
    return win.get("start", "00:00") <= hm < win.get("end", "24:00")


class Bot:
    def __init__(self, root: str, config: dict, device):
        self.root = root
        self.cfg = config
        self.dev = device
        self.vision = Vision(os.path.join(root, "templates"), config.get("ref_width", 1280),
                             config.get("threshold", 0.85))
        self.stop_event = threading.Event()
        self._screen = None

    # ---- tiện ích ----
    def check_stop(self):
        if self.stop_event.is_set():
            raise StopFlow("đã bấm dừng")

    def shot(self):
        self._screen = self.dev.screenshot()
        return self._screen

    def tap_ratio(self, x: float, y: float, after: float = 0.6):
        h, w = (self._screen if self._screen is not None else self.shot()).shape[:2]
        self.dev.tap(x * w, y * h)
        time.sleep(after)

    def wait_for(self, names: List[str], region=None, timeout: float = 15, threshold=None):
        end = time.time() + timeout
        missing = [n for n in names if not self.vision.has(n)]
        for n in missing:
            log.warning("⚠ thiếu ảnh mẫu: templates/%s.png", n)
        names = [n for n in names if n not in missing]
        if not names:
            return None
        while True:
            self.check_stop()
            hit = self.vision.find_any(self.shot(), names, region, threshold)
            if hit or time.time() > end:
                return hit
            time.sleep(0.4)

    def tap_template(self, name: str, timeout: float = 8, region=None, after: float = 0.7) -> bool:
        hit = self.wait_for([name], region, timeout)
        if not hit:
            return False
        self.dev.tap(hit.x, hit.y)
        time.sleep(after)
        return True

    # ---- kịch bản ----
    def load(self, name: str) -> dict:
        with open(os.path.join(self.root, "flows", name + ".json"), encoding="utf-8") as f:
            return json.load(f)

    def profile(self, name: str) -> dict:
        base = dict(self.cfg.get("battle", {}))
        base.update(self.cfg.get("battle_profiles", {}).get(name, {}))
        return base

    def run_feature(self, name: str):
        flow = self.load(name)
        log.info("▶ %s", flow.get("title", name))
        win = self.cfg.get("schedules", {}).get(name)
        if not in_window(win):
            log.info("■ %s: ngoài giờ mở (%s)", name, win)
            return
        try:
            self.steps(flow["steps"], name)
        except StopFlow as exc:
            log.info("■ %s: %s", name, exc)

    def _names(self, o) -> List[str]:
        t = o.get("t", [])
        names = [t] if isinstance(t, str) else list(t)
        # cho phép "pb/lv_{team_dungeon_level}" lấy giá trị từ config.json
        return [n.format(**{k: v for k, v in self.cfg.items() if not isinstance(v, (dict, list))})
                for n in names]

    def steps(self, arr, feature: str = ""):
        for o in arr:
            self.step(o, feature)

    def step(self, o: dict, feature: str):
        self.check_stop()
        do = o["do"]
        th = o.get("threshold")
        if do == "log":
            log.info(o["text"])
        elif do == "sleep":
            time.sleep(o.get("ms", 500) / 1000.0)
        elif do == "tap":
            self.shot(); self.tap_ratio(o["x"], o["y"], o.get("after", 600) / 1000.0)
        elif do == "swipe":
            h, w = self.shot().shape[:2]
            self.dev.swipe(o["x1"] * w, o["y1"] * h, o["x2"] * w, o["y2"] * h, o.get("ms", 400))
            time.sleep(o.get("after", 600) / 1000.0)
        elif do == "wait_for":
            hit = self.wait_for(self._names(o), o.get("region"), o.get("timeout", 15000) / 1000.0, th)
            if hit is None:
                if o.get("optional"):
                    return
                raise StopFlow("không thấy %s — %s" % (self._names(o), o.get("hint", "dừng")))
            if o.get("tap"):
                self.dev.tap(hit.x, hit.y)
                time.sleep(o.get("after", 700) / 1000.0)
        elif do == "tap_if":
            hit = self.vision.find_any(self.shot(), [n for n in self._names(o) if self.vision.has(n)],
                                       o.get("region"), th)
            if hit:
                self.dev.tap(hit.x, hit.y)
                time.sleep(o.get("after", 700) / 1000.0)
        elif do in ("if", "stop_if"):
            hit = self.vision.find_any(self.shot(), [n for n in self._names(o) if self.vision.has(n)],
                                       o.get("region"), th)
            if do == "stop_if":
                if hit:
                    raise StopFlow(o.get("text", "điều kiện dừng: %s" % hit.name))
            else:
                self.steps(o.get("then" if hit else "else", []), feature)
        elif do == "stop_if_outside":
            if not in_window(self.cfg.get("schedules", {}).get(o.get("schedule", feature))):
                raise StopFlow("hết giờ sự kiện")
        elif do == "repeat":
            until = o.get("until")
            losses = 0
            max_losses = self.cfg.get("max_losses", {}).get(feature, o.get("max_losses", 0))
            for k in range(o.get("times", 1000)):
                if until and self.vision.find_any(self.shot(), [until], o.get("until_region")):
                    break
                if o.get("log_round"):
                    log.info("  lượt %d", k + 1)
                self._last_result = None
                self.steps(o["steps"], feature)
                if self._last_result and "lose" in self._last_result:
                    losses += 1
                    log.info("  thua %d trận", losses)
                    if max_losses and losses >= max_losses:
                        raise StopFlow("thua đủ %d trận — dừng như APK (hôm nay không vào lại)" % losses)
        elif do == "run":
            self.steps(self.load(o["flow"])["steps"], feature)
        elif do == "battle":
            self._last_result = Battle(self, self.profile(o.get("profile", feature))).run()
            if o.get("after"):
                self.steps(o["after"], feature)
        else:
            log.warning("⚠ lệnh lạ: %s", do)

    _last_result = None
