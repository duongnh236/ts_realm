import datetime
import os
import sys
import tempfile
import types
import unittest

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tsrealm import status_logic as sl  # noqa: E402
from tsrealm.battle import Battle, status_id_from_name  # noqa: E402
from tsrealm.engine import Bot, StopFlow, in_window  # noqa: E402
from tsrealm.vision import Vision  # noqa: E402

W, H = 1280, 720
rng = np.random.default_rng(1)


def noise():
    return rng.integers(0, 60, (H, W, 3), dtype=np.uint8)


def patch(seed, size=32):
    r = np.random.default_rng(seed)
    return r.integers(0, 256, (size, size, 3), dtype=np.uint8)


def paste(img, p, cx, cy):
    s = p.shape[0]
    x, y = int(cx * W) - s // 2, int(cy * H) - s // 2
    img[y:y + s, x:x + s] = p


class FakeDev:
    def __init__(self, screens):
        self.screens = list(screens)
        self.taps = []

    def screenshot(self):
        return self.screens[0] if len(self.screens) == 1 else self.screens.pop(0)

    def tap(self, x, y):
        self.taps.append((x, y))

    def swipe(self, *a):
        pass


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tpl = os.path.join(self.tmp, "templates")
        for d in ("status", "battle", "skills", "ui"):
            os.makedirs(os.path.join(self.tpl, d))
        os.makedirs(os.path.join(self.tmp, "flows"))

    def save(self, name, img):
        cv2.imwrite(os.path.join(self.tpl, name + ".png"), img)


class StatusLogicTest(unittest.TestCase):
    cost = staticmethod(lambda s: {14022: 10, 11012: 15, 11025: 48, 14007: 5, 10009: 30}.get(s, 0))

    def test_cleanse_choices(self):
        self.assertEqual(sl.pick_cleanse({14022, 11012}, 99, self.cost, {(3, 2): ("chaos", 14021)}), (14022, (3, 2)))
        self.assertEqual(sl.pick_cleanse({14022, 11012}, 99, self.cost, {(3, 2): ("freeze", 11014)}), (11012, (3, 2)))
        self.assertIsNone(sl.pick_cleanse({11012}, 5, self.cost, {(3, 2): ("lock", 13007)}))
        two = {(2, 1): ("chaos", 14021), (3, 3): ("sleep", 14008)}
        self.assertEqual(sl.pick_cleanse({11025, 11012}, 99, self.cost, two, (3,))[0], 11025)

    def test_boss_cc_and_soft_cc(self):
        self.assertEqual(sl.ally_cc({(2, 3): {1: 23015}}, (2, 3)), {(2, 3): ("lock", 23015)})
        self.assertEqual(sl.ally_cc({(3, 2): {1: 13002}}, (2, 3)), {})

    def test_dispel(self):
        self.assertEqual(sl.pick_dispel({10009, 11012}, 99, self.cost, {(0, 2): {10010}}), (10009, (0, 2)))
        self.assertEqual(sl.pick_dispel({10009, 11012}, 99, self.cost, {(0, 2): {12025}}), (11012, (0, 2)))


class VisionTest(Base):
    def test_find_and_scale(self):
        p = patch(7)
        self.save("ui/btn", p)
        img = noise(); paste(img, p, 0.5, 0.5)
        v = Vision(self.tpl, 1280)
        hit = v.find(img, "ui/btn")
        self.assertAlmostEqual(hit.x, 640, delta=2); self.assertAlmostEqual(hit.y, 360, delta=2)
        self.assertIsNone(v.find(img, "ui/btn", region=[0, 0, 0.3, 0.3]))
        small = cv2.resize(img, (640, 360), interpolation=cv2.INTER_AREA)
        hit = v.find(small, "ui/btn", threshold=0.6)
        self.assertAlmostEqual(hit.x, 320, delta=3)

    def test_bar_ratio(self):
        img = np.zeros((H, W, 3), np.uint8)
        img[10:20, 0:320] = (40, 40, 220)
        self.assertAlmostEqual(Vision.bar_ratio(img, [0, 0, 0.5, 0.05], (40, 40, 220)), 0.5, delta=0.01)


class BattleTest(Base):
    def profile(self, **kw):
        p = {"ally_slots": {"3,2": [0.78, 0.72], "2,2": [0.70, 0.62]},
             "enemy_slots": {"0,2": [0.22, 0.30]}, "boss_slot": "0,2",
             "units": {"char": {"row": 3, "col": 2, "skills": [14022, 11012, 10010], "attack": [12006]}},
             "skill_cost": {}, "style": "auto"}
        p.update(kw)
        return p

    def bot(self, screen):
        return types.SimpleNamespace(vision=Vision(self.tpl, 1280, 0.85), shot=lambda: screen)

    def test_name_to_id(self):
        self.assertEqual(status_id_from_name("status/14021"), 14021)
        self.assertEqual(status_id_from_name("status/chaos_2"), 14021)
        self.assertIsNone(status_id_from_name("status/abc"))

    def test_cleanse_ally_with_chaos_icon(self):
        icon = patch(11, 20)
        self.save("status/chaos_1", icon)
        img = noise(); paste(img, icon, 0.70, 0.58)  # trên đầu tướng (2,2)
        b = Battle(self.bot(img), self.profile())
        st = b.read_status(img)
        self.assertEqual(st, {(2, 2): {0: 14021}})
        self.assertEqual(b.decide("char", img, st), ("cleanse", 14022, (2, 2)))

    def test_dispel_boss_buff_icon(self):
        icon = patch(12, 20)
        self.save("status/12025", icon)  # Cuồng Nộ trên boss
        img = noise(); paste(img, icon, 0.22, 0.26)
        b = Battle(self.bot(img), self.profile())
        st = b.read_status(img)
        self.assertEqual(b.decide("char", img, st), ("dispel", 11012, (0, 2)))

    def test_self_locked_skips(self):
        icon = patch(13, 20)
        self.save("status/freeze_1", icon)
        img = noise(); paste(img, icon, 0.78, 0.68)
        b = Battle(self.bot(img), self.profile())
        self.assertEqual(b.decide("char", img, b.read_status(img))[0], "skip")

    def test_styles(self):
        img = noise()
        st = {}
        self.assertEqual(Battle(self.bot(img), self.profile(style="survive")).decide("char", img, st)[:2], ("guard", 10010))
        self.assertEqual(Battle(self.bot(img), self.profile(style="full_attack")).decide("char", img, st), ("attack", 12006, (0, 2)))
        self.assertEqual(Battle(self.bot(img), self.profile(style="auto")).decide("char", img, st)[0], "attack")


class EngineTest(Base):
    def test_window(self):
        mon = datetime.datetime(2026, 11, 23, 13, 0)  # thứ 2
        self.assertTrue(in_window({"days": [0, 2, 4], "start": "12:00", "end": "22:00"}, mon))
        self.assertFalse(in_window({"days": [6], "start": "08:00", "end": "23:00"}, mon))
        self.assertFalse(in_window({"start": "14:00", "end": "23:00"}, mon))

    def test_wait_tap_and_stop(self):
        p = patch(21); self.save("ui/btn", p)
        q = patch(22); self.save("ui/het", q)
        img = noise(); paste(img, p, 0.25, 0.25); paste(img, q, 0.75, 0.75)
        dev = FakeDev([img])
        bot = Bot(self.tmp, {"ref_width": 1280, "lv": 50}, dev)
        bot.steps([{"do": "wait_for", "t": "ui/btn", "tap": True, "after": 0}])
        self.assertAlmostEqual(dev.taps[0][0], 320, delta=2)
        with self.assertRaises(StopFlow):
            bot.steps([{"do": "stop_if", "t": "ui/het"}])
        with self.assertRaises(StopFlow):
            bot.steps([{"do": "wait_for", "t": "ui/khong_co", "timeout": 100}])
        self.assertEqual(bot._names({"t": "pb/lv_{lv}"}), ["pb/lv_50"])

    def test_flows_are_valid_json_and_known_commands(self):
        import json
        root = os.path.join(os.path.dirname(__file__), "..")
        known = {"log", "sleep", "tap", "swipe", "wait_for", "tap_if", "if", "stop_if",
                 "stop_if_outside", "repeat", "run", "battle"}

        def walk(x):
            if isinstance(x, dict):
                if "do" in x:
                    self.assertIn(x["do"], known)
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        for f in os.listdir(os.path.join(root, "flows")):
            walk(json.load(open(os.path.join(root, "flows", f), encoding="utf-8")))
        cfg = json.load(open(os.path.join(root, "config.json"), encoding="utf-8"))
        for prof in cfg["battle_profiles"]:
            self.assertIn(prof, {"world_boss", "nhi_kieu", "npc40", "pb"})


if __name__ == "__main__":
    unittest.main()
