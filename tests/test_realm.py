"""Kiểm tra ts_realm không cần server.

Chạy:  python -m unittest discover -s tests -v
Biến môi trường TS_BOT_PYTHON trỏ tới ts_bot/app/src/main/python để chạy thêm phần ghép với
train_bot.combat thật (bỏ qua nếu không có).
"""
import datetime
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from types import SimpleNamespace as NS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from realm import combat_rules as cr  # noqa: E402
from realm import features  # noqa: E402
from realm import status_logic as sl  # noqa: E402

CHAR, PET = 3, 2


class _Dec:
    def __init__(self, unit, atype, target, skill, b=0):
        self.unit, self.atype, self.target, self.skill, self.b = unit, atype, target, skill, b


def fake_combat(revive=None):
    """Module combat giả, đủ hàm mà combat_rules dùng."""
    calls = []
    m = types.ModuleType("fake_combat")
    m.config = NS(UNIT_CHAR=CHAR, UNIT_PET=PET)
    m.Decision = _Dec
    m._skill_cost = lambda s: 10
    m._row = lambda p: p // 10
    m._col = lambda p: p % 10
    m._offered_targets = lambda options, at: [o[1] for o in options if o[0] == at]

    def _resolve_target(pos, offered):
        c = pos % 10
        return c if c in offered else (c + 1 if c + 1 in offered else None)

    m._resolve_target = _resolve_target
    m._break_claims, m._break_lock = {}, threading.Lock()
    m._col_reachable = lambda c, off: c in off or (c + 1) in off
    m._lowest_hp_enemy = lambda state, offered: min(
        [(p, hp) for p, hp in state.enemy_hp.items() if hp > 0], key=lambda x: x[1])[0]
    m._enemy_target_pos = lambda state, offered, key: m._lowest_hp_enemy(state, offered)

    def _claim_target(state, cls, target, owner, claims, lock, group, turn_token=None):
        with lock:
            key = (group, cls, target)
            if claims.get(key, owner) != owner:
                return False
            claims[key] = owner
            return True

    m._claim_target = _claim_target
    m._register_current_unit = lambda *a: calls.append("register")
    m._try_revive = lambda *a: revive
    m.decide_char = lambda state, options, first_turn=False: calls.append("orig_char") or "ORIG_CHAR"
    m.decide_pet = lambda state, options, first_turn=False: calls.append("orig_pet") or "ORIG_PET"
    m._try_protect = lambda state, unit, skills, stat: "SHIELD"
    m.calls = calls
    return m


def fake_state(**kw):
    st = NS(label="acc1", party_idx=None, my_atype=1, support_combat=True, boss_mode=False,
            ally_rows=(2, 3), enemy_rows=(0, 1), char_row=3, status_by_kind={}, allies={},
            enemy_slots=[0, 1, 2], skills_char=[], pet_skills=[],
            char=NS(sp=200, hp=500, hp_max=1000), pet=NS(sp=200, hp=500, hp_max=1000))
    for k, v in kw.items():
        setattr(st, k, v)
    return st


def fresh_rules():
    cr._installed = False
    cr._claims.clear()
    cr.RULES.update({"cleanse": True, "dispel": True, "dispel_mode": "worthy", "avoid_barrier": True,
                     "dau_chuyen_first": True, "boss_style": "auto", "auto_guard_hp": 0.5})


class StatusLogicTest(unittest.TestCase):
    def test_ally_cc_priority(self):
        sbk = {(3, 1): {"a": 14014, "b": 14022} if 14014 in sl.CC_KIND else {"b": 14022}}
        # 14022 là skill giải; dùng skill gây CC thật lấy từ bảng
        chaos = next(s for s, (k, _) in sl.CC_KIND.items() if k == "chaos")
        poison = next((s for s, (k, _) in sl.CC_KIND.items() if k == "poison"), None)
        sbk = {(3, 1): {"x": chaos}, (2, 0): {"y": poison or chaos}, (0, 0): {"z": chaos}}
        out = sl.ally_cc(sbk, (2, 3))
        self.assertEqual(out[(3, 1)][0], "chaos")
        self.assertNotIn((0, 0), out)  # hàng địch không tính

    def test_pick_cleanse_prefers_char_row_and_specific_skill(self):
        freeze = next(s for s, (k, _) in sl.CC_KIND.items() if k == "freeze")
        victims = {(2, 0): ("freeze", freeze), (3, 2): ("freeze", freeze)}
        skill, pos = sl.pick_cleanse([11015, 11012], 200, lambda s: 10, victims, priority_rows=(3,))
        self.assertEqual(pos, (3, 2))
        self.assertEqual(skill, 11015)  # Tan Băng (chuyên dụng) trước Giải Trừ

    def test_pick_cleanse_no_sp(self):
        chaos = next(s for s, (k, _) in sl.CC_KIND.items() if k == "chaos")
        self.assertIsNone(sl.pick_cleanse([14022], 5, lambda s: 10, {(3, 0): ("chaos", chaos)}))

    def test_pick_dispel(self):
        buff = sorted(sl.BOSS_BUFFS)[0]
        buffed = sl.enemy_buffs({(0, 2): {"k": buff}, (3, 0): {"k": buff}}, (0, 1))
        self.assertEqual(list(buffed), [(0, 2)])
        self.assertEqual(sl.pick_dispel([11012], 200, lambda s: 10, buffed), (11012, (0, 2)))


class TsManagerRulesTest(unittest.TestCase):
    def test_ladder(self):
        self.assertLess(sl.ally_ladder_rank(True, 2), sl.ally_ladder_rank(True, 4))
        self.assertLess(sl.ally_ladder_rank(True, 4), sl.ally_ladder_rank(True, None))
        self.assertLess(sl.ally_ladder_rank(True, None), sl.ally_ladder_rank(False, 2))

    def test_worthy_only(self):
        sbk = {(0, 1): {"a": 13005}, (0, 2): {"b": 21026}}   # Ẩn Mình (không đáng), Nhân Giả Vô Địch
        self.assertEqual(set(sl.enemy_buffs(sbk, (0, 1), worthy_only=True)), {(0, 2)})
        self.assertEqual(set(sl.enemy_buffs(sbk, (0, 1))), {(0, 1), (0, 2)})

    def test_cleanse_order_by_element(self):
        fresh_rules()
        cb = fake_combat()
        cr.install(cb)
        chaos = next(s for s, (k, _) in sl.CC_KIND.items() if k == "chaos")
        st = fake_state(skills_char=[14022],
                        status_by_kind={(3, 1): {"c": chaos}, (3, 4): {"c": chaos}, (2, 0): {"c": chaos}},
                        allies={(3, 1): NS(hp=1, hp_max=9, element=4), (3, 4): NS(hp=1, hp_max=9, element=2),
                                (2, 0): NS(hp=1, hp_max=9, element=2)})
        d = cb.decide_char(st, [])
        self.assertEqual((d.b, d.target), (3, 4))   # NV hệ Thủy trước NV hệ Phong và Tướng

    def test_avoid_barrier(self):
        fresh_rules()
        cb = fake_combat()
        cr.install(cb)
        st = fake_state(enemy_hp={1: 100, 2: 500}, status_by_kind={(0, 1): {"b": 10010}})
        self.assertEqual(cb._lowest_hp_enemy(st, [0, 1, 2]), 2)
        st.support_combat = False
        self.assertEqual(cb._lowest_hp_enemy(st, [0, 1, 2]), 1)   # farm thường: như ts_bot


class CombatRulesTest(unittest.TestCase):
    def setUp(self):
        fresh_rules()

    def _chaos(self):
        return next(s for s, (k, _) in sl.CC_KIND.items() if k == "chaos")

    def test_cleanse_before_original(self):
        cb = fake_combat()
        cr.install(cb)
        st = fake_state(skills_char=[14022], status_by_kind={(3, 2): {"c": self._chaos()}})
        d = cb.decide_char(st, [(1, 0)])
        self.assertIsInstance(d, _Dec)
        self.assertEqual((d.skill, d.target, d.b, d.unit), (14022, 2, 3, CHAR))
        self.assertNotIn("orig_char", cb.calls)

    def test_revive_stays_first(self):
        cb = fake_combat(revive="REVIVE")
        cr.install(cb)
        st = fake_state(skills_char=[14022], status_by_kind={(3, 2): {"c": self._chaos()}})
        self.assertEqual(cb.decide_char(st, []), "REVIVE")

    def test_farm_mode_untouched(self):
        cb = fake_combat()
        cr.install(cb)
        st = fake_state(support_combat=False, skills_char=[14022],
                        status_by_kind={(3, 2): {"c": self._chaos()}})
        self.assertEqual(cb.decide_char(st, []), "ORIG_CHAR")

    def test_two_units_do_not_cleanse_same_ally(self):
        cb = fake_combat()
        cr.install(cb)
        sbk = {(3, 2): {"c": self._chaos()}}
        st = fake_state(skills_char=[14022], pet_skills=[14022], status_by_kind=sbk)
        self.assertIsInstance(cb.decide_char(st, []), _Dec)
        self.assertEqual(cb.decide_pet(st, []), "ORIG_PET")

    def test_dispel_boss_buff(self):
        cb = fake_combat()
        cr.install(cb)
        buff = sorted(sl.BOSS_BUFFS)[0]
        st = fake_state(skills_char=[11012], enemy_slots=[2], status_by_kind={(0, 2): {"b": buff}})
        d = cb.decide_char(st, [(1, 0), (1, 1), (1, 2)])
        self.assertEqual((d.skill, d.target, d.b), (11012, 2, 0))

    def test_dispel_off(self):
        cb = fake_combat()
        cr.install(cb, {"dispel": False})
        buff = sorted(sl.BOSS_BUFFS)[0]
        st = fake_state(skills_char=[11012], enemy_slots=[2], status_by_kind={(0, 2): {"b": buff}})
        self.assertEqual(cb.decide_char(st, [(1, 2)]), "ORIG_CHAR")

    def test_boss_style_guard(self):
        cb = fake_combat()
        cr.install(cb)
        hi, lo = NS(hp=900, hp_max=1000), NS(hp=300, hp_max=1000)
        boss = fake_state(boss_mode=True)
        self.assertIsNone(cb._try_protect(boss, CHAR, [], hi))   # auto, máu cao -> không khiên
        self.assertEqual(cb._try_protect(boss, CHAR, [], lo), "SHIELD")
        cr.RULES["boss_style"] = "full_attack"
        self.assertIsNone(cb._try_protect(boss, CHAR, [], lo))
        cr.RULES["boss_style"] = "survive"
        self.assertEqual(cb._try_protect(boss, CHAR, [], hi), "SHIELD")
        self.assertEqual(cb._try_protect(fake_state(), CHAR, [], hi), "SHIELD")  # ngoài boss: như cũ


class WindowTest(unittest.TestCase):
    def test_windows(self):
        w = features.DEFAULT_WINDOWS
        mon_13 = datetime.datetime(2026, 11, 23, 13, 0)   # thứ Hai
        tue_13 = datetime.datetime(2026, 11, 24, 13, 0)
        sun_9 = datetime.datetime(2026, 11, 29, 9, 0)
        self.assertFalse(features.in_window(w["npc40"], mon_13))   # 40 NPC mở 20:00
        self.assertTrue(features.in_window(w["npc40"], datetime.datetime(2026, 11, 23, 20, 30)))
        self.assertFalse(features.in_window(w["npc40"], tue_13))
        self.assertTrue(features.in_window(w["nhi_kieu"], sun_9))
        self.assertFalse(features.in_window(w["nhi_kieu"], mon_13))
        self.assertTrue(features.in_window(w["world_boss"], tue_13))
        self.assertFalse(features.in_window(w["world_boss"], datetime.datetime(2026, 11, 24, 23, 30)))


class FakeClient:
    def __init__(self, npc40_results=(), crawl_results=()):
        self.running = True
        self.state = NS(support_combat=False, quest_mode=False)
        self.log = []
        self._npc40 = list(npc40_results)
        self._crawl = list(crawl_results)

    # Boss TG giả: mỗi trận server gửi 073-004 với dame cộng dồn
    world_boss_count, world_boss_max, _label, _username = 0, 5, "acc1", "acc1"
    bag_slots = {}
    fight_damage = 600_000

    def _world_boss_event_open(self):
        return True

    def query_world_boss_attempts(self):
        return (self.world_boss_count, self.world_boss_max)

    def _set_world_boss_progress(self, cur, mx=5, source=""):
        self.world_boss_count, self.world_boss_max = cur, mx

    def _dispatch(self, opcode, pkt):
        pass

    def do_world_boss(self, heal_after=False):
        self.log.append(("boss", self.state.support_combat))
        if self.fight_damage is not None:
            for part in (self.fight_damage // 2, self.fight_damage):
                self._dispatch(0x49, boss_pkt(part))
        self.world_boss_count += 1
        return True

    def use_slot_wait(self, slot, target=0, qty=1):
        tid, cnt = self.bag_slots[slot]
        self.bag_slots[slot] = (tid, cnt - 1)
        self.log.append(("ticket", tid))
        return True, cnt - 1

    def do_daily_dungeon(self, cho_phep=None):
        self.log.append(("pb_don", self.state.support_combat))
        return True

    def do_team_dungeon(self, level):
        self.log.append(("pb_doi", level))
        return True

    def go_to_event(self, ev):
        self.log.append(("go", ev["key"]))
        return True

    def heal_npc40_between_battles(self):
        self.log.append(("heal",))

    def start_npc40_loop(self, point, on_loss, before_repeat=None, ignore_window=False):
        lost = self._npc40.pop(0) if self._npc40 else False
        self.log.append(("npc40", point))

        def run():
            if lost:
                on_loss()
        self._npc40_thread = threading.Thread(target=run)
        self._npc40_thread.start()
        return True

    def stop_npc40_loop(self):
        pass

    def start_floor_crawl(self, ev, on_done=None, heal_party=None, lost_check=None, du_party=None):
        lost = self._crawl.pop(0) if self._crawl else False
        self.log.append(("crawl",))

        def run():
            on_done(lost, "thua" if lost else "len_dinh")
        self._floor_crawl_thread = threading.Thread(target=run)
        self._floor_crawl_thread.start()
        return True

    def stop_floor_crawl(self):
        pass


def boss_pkt(dmg):
    body = b"\x00" + int(dmg).to_bytes(4, "little") + b"\x03"
    return b"\x00" * 6 + bytes([0x49, 0x04]) + body


class WorldBossTest(unittest.TestCase):
    def setUp(self):
        from realm import world_boss as wb
        self.wb = wb
        features.time.sleep = lambda s: None
        wb.time.sleep = lambda s: None
        self.dlog = wb.DamageLog(os.path.join(tempfile.mkdtemp(), "d.json"))

    def test_parse(self):
        self.assertEqual(self.wb.fight_damage_from_packet(0x49, boss_pkt(60415)), 60415)
        self.assertIsNone(self.wb.fight_damage_from_packet(0x14, boss_pkt(1)))

    def test_free_then_tickets_until_goal(self):
        c = FakeClient()
        c.bag_slots = {3: (46614, 3), 9: (46629, 2), 1: (1234, 5)}
        ok, why = self.wb.run(c, "acc1", "2026-11-25", self.dlog, {"damage_goal": 5_000_000})
        self.assertTrue(ok)
        tickets = [x[1] for x in c.log if x[0] == "ticket"]
        self.assertEqual(tickets, [46629, 46629, 46614, 46614])   # vé tặng trước, vé shop sau
        self.assertEqual(sum(1 for x in c.log if x[0] == "boss"), 9)
        self.assertIn("đủ dame", why)
        self.assertEqual(self.dlog.today("acc1", "2026-11-25"), 5_400_000)

    def test_stop_when_out_of_tickets(self):
        c = FakeClient()
        c.bag_slots = {9: (46629, 1)}
        ok, why = self.wb.run(c, "acc1", "2026-11-25", self.dlog, {})
        self.assertEqual(sum(1 for x in c.log if x[0] == "boss"), 6)
        self.assertIn("hết vé", why)

    def test_goal_reached_by_earlier_runs_today(self):
        self.dlog.add("acc1", "2026-11-25", 4_900_000)
        c = FakeClient()
        c.bag_slots = {9: (46629, 5)}
        self.wb.run(c, "acc1", "2026-11-25", self.dlog, {})
        self.assertEqual([x for x in c.log if x[0] == "ticket"], [])  # 5 free + đã đủ -> không vé

    def test_unknown_count_tries_fights_without_tickets(self):
        c = FakeClient()
        c.query_world_boss_attempts = lambda: None
        c.world_boss_count = None
        c.bag_slots = {9: (46629, 5)}
        fights = []

        def do_boss(heal_after=False):
            fights.append(1)
            return len(fights) <= 2          # server cho 2 trận rồi từ chối (hết lượt)
        c.do_world_boss = do_boss
        ok, why = self.wb.run(c, "acc1", "2026-11-25", self.dlog, {})
        self.assertTrue(ok)
        self.assertEqual(len(fights), 3)
        self.assertIn("không vào được trận", why)
        self.assertEqual([x for x in c.log if x[0] == "ticket"], [])

    def test_unknown_damage_no_ticket(self):
        c = FakeClient()
        c.fight_damage = None
        c.bag_slots = {9: (46629, 5)}
        ok, why = self.wb.run(c, "acc1", "2026-11-25", self.dlog, {})
        self.assertIn("không dùng vé mù", why)


EVENTS = {"npc_40": {"key": "npc_40", "party_battle": {"point": [910, 290]}},
          "nhi_kieu": {"key": "nhi_kieu", "party_battle": {"kind": "floor_crawl"}}}
CONFIG = NS(EVENTS=EVENTS, event_hom_nay=lambda k: EVENTS.get(k))
ALWAYS = {"world_boss": None, "npc40": None, "nhi_kieu": None}


class FakeNpc40Mod:
    CHECK_CHO_PROMPT = 3

    @staticmethod
    def _end_npc_dialog(client, sleep_fn):
        client.log.append("close")

    @staticmethod
    def _open_event_battle(client, prev, stop, sleep_fn, poll, adv):
        if not client.results:
            stop.set()
            return False
        r = client.results.pop(0)
        client.log.append(r)
        client._dead = r == "stuck_dead"
        client._npc40_last_defeated = r == "lose"
        if r in ("win", "lose"):
            client._npc40_prompt_seq += 1
        return True

    @staticmethod
    def _wait_counter(client, name, prev, stop, sleep_fn, poll, checks):
        return getattr(client, name) > prev

    @staticmethod
    def _da_thua_that(client):
        return client._dead


class FakeNpcClient:
    def __init__(self, results):
        self.results = list(results)
        self.running = True
        self.log = []
        self._label = "acc1"
        self._npc40_prompt_seq = 0
        self._battle_start_seq = 0
        self._npc40_last_defeated = False
        self._dead = False

    def navigate_to(self, x, y, flee=False):
        return True

    def _wait_combat_clear(self, idle=1.0, cap=20.0):
        pass

    def rearm_ready(self):
        pass


class Npc40LoopTest(unittest.TestCase):
    def run_loop(self, results, window=lambda: True, max_consec=3):
        from realm import npc40_loop
        c = FakeNpcClient(results)
        heals = []
        why = npc40_loop.run_loop(c, (910, 290), threading.Event(), lambda: None,
                                  before_repeat=lambda: heals.append(1), window_open=window,
                                  max_consec_losses=max_consec, sleep_fn=lambda s: None,
                                  npc40=FakeNpc40Mod)
        return why, c, heals

    def test_three_consecutive_losses(self):
        why, c, heals = self.run_loop(["win", "lose", "lose", "win", "lose", "lose", "lose", "win"])
        self.assertIn("thua 3 trận liên tiếp", why)
        self.assertEqual(c.results, ["win"])          # dừng ngay sau thua liên tiếp thứ 3
        self.assertEqual(len(heals), 6)               # hồi đầy sau mỗi trận chưa dừng

    def test_two_losses_not_enough(self):
        why, c, _ = self.run_loop(["lose", "lose", "win", "lose", "lose"])
        self.assertNotIn("liên tiếp", why)

    def test_stuck_retry_three_times(self):
        why, c, _ = self.run_loop(["win", "stuck_alive", "stuck_alive", "stuck_alive", "stuck_alive", "win"])
        self.assertIn("không vào lại được trận", why)

    def test_stuck_dead_counts_as_loss(self):
        why, c, _ = self.run_loop(["lose", "stuck_dead", "lose", "win"])
        self.assertIn("thua 3 trận liên tiếp", why)

    def test_window_closed(self):
        calls = {"n": 0}

        def win():
            calls["n"] += 1
            return calls["n"] < 2
        why, c, _ = self.run_loop(["win", "win", "win"], window=win)
        self.assertIn("hết giờ", why)

    def test_unlimited_losses_by_default(self):
        from realm import npc40_loop
        c = FakeNpcClient(["lose"] * 6 + ["win"])
        heals = []
        why = npc40_loop.run_loop(c, (910, 290), threading.Event(), lambda: None,
                                  before_repeat=lambda: heals.append(1), sleep_fn=lambda s: None,
                                  npc40=FakeNpc40Mod)
        self.assertNotIn("liên tiếp", why)
        self.assertEqual(c.results, [])                # đánh hết, không dừng vì thua
        self.assertEqual(len(heals), 7)                # hồi đầy sau mỗi trận, kể cả trận thua

    def test_floor_from_bag_and_stop_at_40(self):
        from realm import npc40_loop, npc40_progress as pg
        c = FakeNpcClient(["win", "win", "win"])
        c.bag_slots = {5: [30020, 1]}
        floors = []

        def floor():
            f = pg.floors_cleared(c)
            floors.append(f)
            c.bag_slots = {5: [30063, 1]}              # trận sau lên tầng 40
            return f
        why = npc40_loop.run_loop(c, (910, 290), threading.Event(), lambda: None,
                                  sleep_fn=lambda s: None, npc40=FakeNpc40Mod, floor_fn=floor)
        self.assertEqual(floors, [7, 40])
        self.assertIn("40 tầng", why)
        self.assertEqual(c._npc40_floor, 40)


class Npc40ProgressTest(unittest.TestCase):
    def test_floors_cleared(self):
        from realm import npc40_progress as pg
        self.assertEqual(len(pg.VICTORY_ORDER), 40)
        self.assertEqual(pg.floors_cleared(NS(bag_slots={})), 0)
        self.assertEqual(pg.floors_cleared(NS(bag_slots={1: [30014, 1], 2: [30043, 1]})), 30)
        self.assertEqual(pg.floors_cleared(NS(bag_slots={1: [30054, 1], 2: [46614, 3]})), 31)
        self.assertEqual(pg.floors_cleared(NS(bag_slots={1: [30063, 0]})), 0)
        self.assertEqual(pg.floors_cleared(NS()), 0)


class TsmDecideTest(unittest.TestCase):
    def setUp(self):
        fresh_rules()
        self.cb = fake_combat()
        cb = self.cb
        cb.config.SKILL_HEAL_ALL, cb.config.HEAL_SP_COST = 11010, 42
        cb.config.CHAR_FIRE_MIN_SP = cb.config.PET_FIRE_MIN_SP = 65
        cb._CUSTOM_AUTO = object()
        cb._custom_decision = lambda *a: cb._CUSTOM_AUTO
        cb._hang_char_ta = lambda st: 3
        cb._heal_decide = None
        cb._claim_support_action = lambda *a: True
        cb._try_cc = lambda st, u, sk, stat, op, ph: ("CC", ph) if "cc" in sk else None
        cb._try_break_enemy_protect = lambda *a: None
        cb._try_sp_restore = lambda *a: None
        cb._combat_attack = lambda *a: "ATTACK"
        cr.install(cb)

    def st(self, **kw):
        kw.setdefault("realm_mode", "npc40")
        kw.setdefault("quest_mode", True)
        st = fake_state(**kw)
        st.lowest_hp_ally = lambda: None
        return st

    def test_emergency_heal_before_cleanse(self):
        chaos = next(s for s, (k, _) in sl.CC_KIND.items() if k == "chaos")
        st = self.st(skills_char=[11010, 14022], status_by_kind={(3, 2): {"c": chaos}},
                     allies={(3, 2): NS(hp=100, hp_max=1000), (3, 1): NS(hp=200, hp_max=1000)})
        self.assertEqual(self.cb.decide_char(st, []).skill, 11010)

    def test_cleanse_then_cc_then_attack(self):
        chaos = next(s for s, (k, _) in sl.CC_KIND.items() if k == "chaos")
        ok_allies = {(3, 2): NS(hp=900, hp_max=1000)}
        st = self.st(skills_char=[14022, "cc"], status_by_kind={(3, 2): {"c": chaos}}, allies=ok_allies,
                     char=NS(sp=200, hp=900, hp_max=1000), enemy_hp={0: 10})
        self.assertEqual(self.cb.decide_char(st, []).skill, 14022)
        st2 = self.st(skills_char=["cc"], allies=ok_allies, char=NS(sp=200, hp=900, hp_max=1000),
                      enemy_hp={0: 10})
        self.assertEqual(self.cb.decide_char(st2, []), ("CC", "high"))
        st3 = self.st(skills_char=[], allies=ok_allies, char=NS(sp=200, hp=900, hp_max=1000), enemy_hp={0: 10})
        self.assertEqual(self.cb.decide_char(st3, []), "SHIELD")   # khiên của ts_bot trước khi đánh

    def test_guard_first_when_outnumbered(self):
        st = self.st(skills_char=["cc"], allies={(3, 2): NS(hp=900, hp_max=1000)},
                     char=NS(sp=200, hp=900, hp_max=1000), enemy_hp={0: 5, 1: 5, 2: 5})
        self.assertEqual(self.cb.decide_char(st, []), "SHIELD")

    def test_dau_chuyen_first_even_before_revive(self):
        cb = self.cb
        cb._try_revive = lambda *a: "REVIVE"
        st = self.st(skills_char=[11012], enemy_slots=[2], status_by_kind={(0, 2): {"b": 13021}},
                     allies={(3, 2): NS(hp=900, hp_max=1000)})
        d = cb.decide_char(st, [(1, 0), (1, 1), (1, 2)])
        self.assertEqual((d.skill, d.target, d.b), (11012, 2, 0))
        st2 = self.st(skills_char=[11012], enemy_slots=[2], status_by_kind={(0, 2): {"b": 10010}},
                      allies={(3, 2): NS(hp=900, hp_max=1000)})
        self.assertEqual(cb.decide_char(st2, [(1, 2)]), "REVIVE")   # buff khác: hồi sinh vẫn trước

    def test_dau_chuyen_first_in_other_events(self):
        cb = self.cb
        cb._try_revive = lambda *a: "REVIVE"
        st = self.st(realm_mode=None, skills_char=[11012], enemy_slots=[1],
                     status_by_kind={(0, 1): {"b": 13021}})
        self.assertEqual(cb.decide_char(st, [(1, 1)]).skill, 11012)

    def test_other_modes_untouched(self):
        st = self.st(realm_mode=None, skills_char=[], allies={(3, 2): NS(hp=900, hp_max=1000)})
        self.assertEqual(self.cb.decide_char(st, []), "ORIG_CHAR")

    def test_nhi_kieu_uses_tsm_ai(self):
        st = self.st(realm_mode="nhi_kieu", skills_char=["cc"], allies={(3, 2): NS(hp=900, hp_max=1000)},
                     char=NS(sp=200, hp=900, hp_max=1000), enemy_hp={0: 10})
        self.assertEqual(self.cb.decide_char(st, []), ("CC", "high"))


class RunnerTest(unittest.TestCase):
    def setUp(self):
        features.time.sleep = lambda s: None  # chạy nhanh

    def runner(self, client, **settings):
        settings.setdefault("windows", ALWAYS)
        return features.Runner(client, CONFIG, settings, threading.Event())

    def test_boss_and_dungeons_turn_support_on(self):
        c = FakeClient()
        c.world_boss_count = 5
        self.runner(c, team_dungeon_level=80, _runtime_dir=tempfile.mkdtemp()).run(
            ["world_boss", "pb_don", "pb_doi", "la"])
        self.assertEqual(c.log, [("pb_don", True), ("pb_doi", 80)])   # hết lượt free, không vé
        self.assertFalse(c.state.support_combat)

    def test_boss_turns_auto_combat_on_then_restores(self):
        c = FakeClient()
        c.auto_combat = False
        seen = []
        orig = c.do_world_boss

        def boss(heal_after=False):
            seen.append(c.auto_combat)
            return orig(heal_after)
        c.do_world_boss = boss
        c.world_boss_count = 4
        self.runner(c, _runtime_dir=tempfile.mkdtemp()).world_boss()
        self.assertEqual(seen, [True])                 # có ra lệnh đánh trong trận
        self.assertFalse(c.auto_combat)                # xong trả lại như cũ

    def test_boss_outside_window(self):
        c = FakeClient()
        r = self.runner(c, windows={"world_boss": {"days": []}})
        self.assertFalse(r.world_boss())
        self.assertEqual(c.log, [])

    def test_npc40_uses_realm_loop_and_tsm_mode(self):
        from realm import npc40_loop
        seen = {}

        def fake_loop(client, point, stop, on_loss, before_repeat, window_open, max_consec):
            seen.update(point=point, max=max_consec, mode=client.state.realm_mode,
                        quest=client.state.quest_mode, win=window_open())
            return "thua 3 trận liên tiếp"
        orig = npc40_loop.run_loop
        npc40_loop.run_loop = fake_loop
        try:
            c = FakeClient()
            self.assertTrue(self.runner(c, max_losses={"npc40": 3}).npc40())
        finally:
            npc40_loop.run_loop = orig
        self.assertEqual(seen, {"point": (910, 290), "max": 3, "mode": "npc40", "quest": True, "win": True})
        self.assertIsNone(c.state.realm_mode)
        self.assertFalse(c.state.quest_mode)

    def test_nhi_kieu_finishes(self):
        c = FakeClient(crawl_results=[True, False])
        self.assertTrue(self.runner(c, max_losses={"nhi_kieu": 3}).nhi_kieu())
        self.assertEqual([x[0] for x in c.log], ["go", "crawl", "heal", "crawl"])

    def test_nhi_kieu_keeps_climbing_after_losses(self):
        c = FakeClient(crawl_results=[True, True, True, True, False])
        self.assertTrue(self.runner(c).nhi_kieu())
        self.assertEqual([x[0] for x in c.log].count("crawl"), 5)

    def test_nhi_kieu_stops_when_out_of_tower(self):
        c = FakeClient(crawl_results=[True, True])
        c.current_map = 12003
        r = self.runner(c)
        orig = r._event
        r._event = lambda k: dict(orig(k), dest_map=12922, party_battle={"kind": "floor_crawl", "top_map": 12959})
        self.assertTrue(r.nhi_kieu())
        self.assertEqual([x[0] for x in c.log], ["go", "crawl"])

    def test_npc40_summary_for_app(self):
        from realm import npc40_loop
        orig = npc40_loop.run_loop
        npc40_loop.run_loop = lambda *a: "hết giờ sự kiện"
        try:
            c = FakeClient()
            c.bag_slots = {3: [30030, 1]}
            self.assertTrue(self.runner(c).npc40())
        finally:
            npc40_loop.run_loop = orig
        self.assertEqual((c._npc40_summary["floor"], c._npc40_summary["why"]), (17, "hết giờ sự kiện"))



class FakeBagClient:
    def __init__(self, slots, take=105, refuse_after=None):
        self.bag_slots = {k: list(v) for k, v in slots.items()}
        self.sent = []
        self.running = True
        self._label = "acc1"
        self.state = NS(in_battle=False)
        self.take, self.refuse_after = take, refuse_after

    def send(self, op, body):
        self.sent.append((op, body))
        if self.refuse_after is not None and len(self.sent) > self.refuse_after:
            return
        need = self.take
        for slot in sorted(self.bag_slots):
            tid, cnt = self.bag_slots[slot]
            if tid == 40045 and need:
                k = min(cnt, need)
                self.bag_slots[slot][1] -= k
                need -= k


class CombineTest(unittest.TestCase):
    def setUp(self):
        from realm import combine
        self.cb = combine

    def run_it(self, c, rounds=0, qty=40, slots=3):
        return self.cb.run(c, 40045, qty, rounds, threading.Event(), slots, sleep_fn=lambda s: None,
                           wait=0.01, gap=0)

    def test_payload_matches_capture(self):
        self.assertEqual(self.cb.payload([(66, 40)] * 3).hex(),
                         "0e00" + "420028000000" * 3 + "01")
        self.assertEqual(self.cb.payload([(5, 2)]).hex(), "0e00" + "050002000000" + "000000000000" * 2 + "01")

    def test_plan_spreads_over_stacks(self):
        c = FakeBagClient({66: [40045, 9108]})
        self.assertEqual(self.cb.plan(c, 40045, 40), [(66, 40)] * 3)
        c = FakeBagClient({3: [40045, 50], 9: [40045, 45], 4: [1, 99]})
        self.assertEqual(self.cb.plan(c, 40045, 40), None)
        self.assertEqual(self.cb.plan(c, 40045, 25), [(3, 25), (3, 25), (9, 25)])

    def test_rounds_limit(self):
        c = FakeBagClient({66: [40045, 9108]})
        r = self.run_it(c, rounds=2)
        self.assertEqual((r["done"], r["used"]), (2, 210))
        self.assertEqual(len(c.sent), 2)
        self.assertEqual(c.sent[0], (0x17, self.cb.payload([(66, 40)] * 3)))

    def test_until_out_of_material(self):
        c = FakeBagClient({66: [40045, 400]}, take=120)
        r = self.run_it(c)
        self.assertEqual(r["done"], 3)
        self.assertIn("hết nguyên liệu", r["why"])

    def test_stops_when_server_refuses(self):
        c = FakeBagClient({66: [40045, 9108]}, refuse_after=1)
        r = self.run_it(c)
        self.assertEqual(r["done"], 1)
        self.assertIn("không trừ", r["why"])

    def test_decompose_body_matches_capture(self):
        b = self.cb.decompose_body(3, [(0x39, 1), (0x4e, 1)])
        self.assertEqual(b.hex(), "030002" + "390001000000" + "4e0001000000")
        self.assertEqual(self.cb.decompose_body(4, [(5, 1)])[:3], b"\x04\x00\x01")

    def test_new_gear_only_new_slots(self):
        items = {20430: {"fc": 690}, 40045: {}, 777: {"fc": 0}, 19030: {"fc": 690}}
        before = {66: [40045, 9108], 7: [19030, 1]}
        after = {66: [40045, 9003], 7: [19030, 1], 10: [20430, 1], 11: [777, 1], 12: [40045, 13]}
        self.assertEqual(self.cb.new_gear(before, after, 40045, items), [(10, 1)])

    def test_combine_then_decompose(self):
        cb = self.cb
        c = FakeBagClient({66: [40045, 9108]})
        orig_send = c.send

        def send(op, body):
            orig_send(op, body)
            if op == 0x17:
                c.bag_slots[100 + len(c.sent)] = [20430, 1]      # đồ hợp ra
                c.bag_slots[200 + len(c.sent)] = [20430, 1]
            elif op == 0x59 and body[0] == 3:
                for i in range(body[2]):
                    c.bag_slots.pop(int.from_bytes(body[3 + 6 * i:5 + 6 * i], "little"), None)
        c.send = send
        orig_items = cb._items
        cb._items = lambda: {20430: {"fc": 690}}
        try:
            r = cb.run(c, 40045, 40, 2, threading.Event(), 3, sleep_fn=lambda s: None, wait=0.01, gap=0,
                       settle=0)
        finally:
            cb._items = orig_items
        self.assertEqual((r["done"], r["broken"]), (2, 4))
        self.assertEqual([op for op, _ in c.sent], [0x17, 0x59, 0x59, 0x17, 0x59, 0x59])
        self.assertEqual([t for t, _ in c.bag_slots.values()], [40045])

    def test_bag_remove_patch(self):
        from realm import realm_login as rl

        class Base:
            def __init__(self):
                self.bag_slots = {0x1d: [20430, 1], 0x142: [40045, 50], 0x42: [1, 5]}

            def _dispatch(self, opcode, pkt):          # giống ts_bot: đọc ô 1 byte, số sai
                rec = self.bag_slots.get(pkt[9])
                if rec:
                    rec[1] = max(0, rec[1] - 256)
        rl.patch_bag_snapshot(Base)
        b = Base()
        pkt = lambda slot, n: b"\xc0\x91\x0f\x00\x00\x00\x17\x09\x00" + slot.to_bytes(2, "little") + n.to_bytes(4, "little")
        b._dispatch(0x17, pkt(0x1d, 1))
        b._dispatch(0x17, pkt(0x142, 8))
        self.assertEqual(b.bag_slots, {0x142: [40045, 42], 0x42: [1, 5]})
        self.assertEqual(b.bag_counts, {40045: 42, 1: 5})

    def test_keep_good_items(self):
        items = {20430: {"fc": 690, "lv": 25}, 21431: {"fc": 690, "lv": 26}}
        before = {66: [40045, 9108]}
        after = {66: [40045, 9003], 10: [20430, 1], 98: [21431, 1], 99: [20430, 1]}
        kept = []
        out = self.cb.new_gear(before, after, 40045, items, {98: 28, 99: 5}, 27, 0, kept)
        self.assertEqual(out, [(10, 1), (99, 1)])
        self.assertEqual(kept, [(98, 21431, "giá trị 28")])
        out = self.cb.new_gear(before, after, 40045, items, {}, 0, 26)
        self.assertEqual(out, [(10, 1), (99, 1)])

    def test_item_bonus_from_capture(self):
        from realm import realm_login as rl
        body = bytes.fromhex("08006200b75301000000" + "00" * 25 + "1c" + "00" * 25)
        pkt = b"\xc0\x91" + (7 + len(body)).to_bytes(2, "little") + b"\x00\x00\x17" + body
        self.assertEqual(rl.parse_bag_set_item(pkt)[:2], (0x62, 21431))
        self.assertEqual(rl.item_bonus(pkt), 28)

    def test_bag_list_groups_by_item(self):
        c = FakeBagClient({1: [40045, 10], 2: [40045, 5], 3: [777, 1]})
        lst = self.cb.bag_list(c)
        self.assertEqual([(x["tid"], x["qty"], x["stacks"]) for x in lst], [(40045, 15, 2), (777, 1, 1)])

class LoginGuardTest(unittest.TestCase):
    def setUp(self):
        from realm.login_guard import LoginGuard, BadCredentials
        self.G, self.Bad = LoginGuard, BadCredentials
        self.dir = tempfile.mkdtemp()
        self.calls = []

    def _login(self, ok_pw):
        def fn(u, p):
            self.calls.append(p)
            if p != ok_pw:
                e = RuntimeError("Login that bai")
                e.error_code = -53
                raise e
            return {"user_id": 7, "access_token": "t"}
        return fn

    def test_block_wrong_password_until_changed(self):
        g = self.G(self.dir)
        with self.assertRaises(self.Bad):
            g.login(self._login("dung"), "Acc", "sai")
        with self.assertRaises(self.Bad):
            g.login(self._login("dung"), "acc", "sai")       # không gửi lên server nữa
        self.assertEqual(self.calls, ["sai"])
        self.assertEqual(g.login(self._login("dung"), "acc", "dung")["user_id"], 7)
        self.assertFalse(g.is_blocked("acc", "sai"))          # đăng nhập được thì xóa chặn
        self.assertNotIn("sai", open(g.block_path).read() if os.path.exists(g.block_path) else "")

    def test_other_errors_not_blocked(self):
        g = self.G(self.dir)

        def net(u, p):
            raise RuntimeError("mạng lỗi")
        with self.assertRaises(RuntimeError):
            g.login(net, "acc", "x")
        self.assertFalse(g.is_blocked("acc", "x"))

    def test_profile_without_password(self):
        g = self.G(self.dir)
        g.remember("Acc", "trieu_van", 7, "NhanVat", "acc1")
        rec = g.profiles()["acc"]
        self.assertEqual((rec["server"], rec["user_id"], rec["character"]), ("trieu_van", 7, "NhanVat"))
        self.assertNotIn("password", rec)


TS_BOT_PY = os.environ.get("TS_BOT_PYTHON", os.path.expanduser("~/Documents/ts_bot/app/src/main/python"))


class BossTsmTest(unittest.TestCase):
    """Boss TG: AI TS Manager, bỏ skill chọn trong app, đánh skill atk tốn SP cao nhất, xử lý Kim Chung Tráo."""

    COST = {10000: 0, 101: 30, 102: 120, 103: 300, 104: 200, 105: 500}

    def setUp(self):
        fresh_rules()
        cr.RULES.update({"tsm_modes": ["npc40", "nhi_kieu", "boss"], "reflect_policy": "hold",
                         "npc40_ai": "ts_manager", "mode_buffs": {}, "boss_buffs": {}})
        self.cb = cb = fake_combat()
        cb.config.SKILL_HEAL_ALL, cb.config.HEAL_SP_COST = 11010, 42
        cb.config.CHAR_FIRE_MIN_SP = cb.config.PET_FIRE_MIN_SP = 65
        cb.config.SKILL_NORMAL, cb.config.SKILL_DEFEND = 10000, 17001
        cb.CC_SKILLS = frozenset((104,))            # 104 = khống chế: không dùng để đánh
        cb._skill_cost = lambda s: self.COST.get(s, 10)
        cb._is_attack = lambda s: s in (10000, 101, 102, 103, 104, 105)
        cb._CUSTOM_AUTO = object()
        cb._custom_decision = lambda *a: _Dec(CHAR, 1, 1, 999)   # skill chọn trong app / luật riêng
        cb._hang_char_ta = lambda st: 3
        cb._claim_support_action = lambda *a: True
        cb._heal_decide = None
        cb._try_cc = lambda *a: None
        cb._try_break_enemy_protect = lambda *a: None
        cb._try_sp_restore = lambda *a: None
        cb._try_protect = lambda *a: None
        cb._combat_attack = lambda *a: "ORIG_ATTACK"
        cr.install(cb)

    def st(self, **kw):
        kw.setdefault("realm_mode", "boss")
        kw.setdefault("boss_mode", True)
        kw.setdefault("allies", {(3, 2): NS(hp=900, hp_max=1000)})
        kw.setdefault("enemy_hp", {2: 5000})
        kw.setdefault("enemy_slots", [2])
        st = fake_state(**kw)
        st.lowest_hp_ally = lambda: None
        return st

    def test_highest_sp_attack_skill_ignores_app_skill(self):
        st = self.st(skills_char=[10000, 101, 102, 103, 104, 105], char=NS(sp=350, hp=900, hp_max=1000))
        d = self.cb.decide_char(st, [(1, 2)])
        self.assertEqual((d.skill, d.target, d.b), (103, 2, 0))   # 105 thiếu SP, 104 là khống chế

    def test_no_sp_normal_attack(self):
        st = self.st(skills_char=[101, 102], char=NS(sp=5, hp=900, hp_max=1000))
        self.assertEqual(self.cb.decide_char(st, [(1, 2)]).skill, 10000)

    def test_pet_also(self):
        st = self.st(pet_skills=[101, 102], pet=NS(sp=200, hp=900, hp_max=1000))
        self.assertEqual(self.cb.decide_pet(st, [(1, 2)]).skill, 102)

    def test_dispel_kim_chung_trao(self):
        st = self.st(skills_char=[11012, 103], status_by_kind={(0, 2): {"b": 10031}})
        d = self.cb.decide_char(st, [(1, 2)])
        self.assertEqual((d.skill, d.target), (11012, 2))

    def test_avoid_reflect_target(self):
        st = self.st(skills_char=[103], char=NS(sp=350, hp=900, hp_max=1000), status_by_kind={(0, 2): {"b": 10031}},
                     enemy_hp={2: 100, 3: 9000}, enemy_slots=[2, 3])
        d = self.cb.decide_char(st, [(1, 2), (1, 3)])
        self.assertEqual((d.skill, d.target), (103, 3))

    def test_hold_when_all_reflect(self):
        st = self.st(skills_char=[103], char=NS(sp=350, hp=900, hp_max=1000), status_by_kind={(0, 2): {"b": 10031}})
        d = self.cb.decide_char(st, [(1, 2)])
        self.assertEqual((d.skill, d.b), (17001, 3))
        cr.RULES["reflect_policy"] = "attack"
        st2 = self.st(skills_char=[103], char=NS(sp=350, hp=900, hp_max=1000), status_by_kind={(0, 2): {"b": 10031}})
        self.assertEqual(self.cb.decide_char(st2, [(1, 2)]).skill, 103)

    def test_cleanse_boc_cam_before_attack(self):
        st = self.st(skills_char=[11012, 103], status_by_kind={(3, 2): {"c": 10033}})
        d = self.cb.decide_char(st, [(1, 2)])
        self.assertEqual((d.skill, d.b, d.target), (11012, 3, 2))

    def test_no_heal_or_sp_skill_in_boss(self):
        cb = self.cb
        cb._try_sp_restore = lambda *a: "SP_RESTORE"
        st = self.st(skills_char=[11010, 103], char=NS(sp=350, hp=900, hp_max=1000),
                     allies={(3, 2): NS(hp=50, hp_max=1000), (3, 1): NS(hp=60, hp_max=1000)})
        self.assertEqual(cb.decide_char(st, [(1, 2)]).skill, 103)
        cr.RULES["boss_skip"] = []          # tắt bỏ qua -> hồi máu như 40 NPC
        st2 = self.st(skills_char=[11010, 103], char=NS(sp=350, hp=900, hp_max=1000),
                      allies={(3, 2): NS(hp=50, hp_max=1000), (3, 1): NS(hp=60, hp_max=1000)})
        self.assertEqual(cb.decide_char(st2, [(1, 2)]).skill, 11010)
        cr.RULES["boss_skip"] = ["heal", "sp_restore"]

    def test_sp_saver_between_fights(self):
        from realm import world_boss as wb
        calls = []
        c = NS(_label="a", bag_slots={1: (1, 1)}, active_pet_slot=1, in_combat=lambda: False,
               state=NS(in_battle=False, solo_multipet=False,
                        char=NS(hp=500, hp_max=1000, sp=400, sp_max=1000),
                        pet=NS(hp=500, hp_max=1000, sp=100, sp_max=1000)),
               heal_full=lambda force=False: calls.append("orig"))
        c._heal_unit = lambda t, u, lab, key, kind, thr_override=None, force=False: calls.append(key)
        saver = wb.SpSaver(c, 0.3)
        c.heal_full(force=True)
        self.assertEqual(calls, ["hp_char", "hp_pet", "sp_pet"])   # SP nhân vật 40% -> không uống
        saver.remove()
        c.heal_full()
        self.assertEqual(calls[-1], "orig")

    def test_boss_buff_mode(self):
        st = self.st()
        self.assertEqual(cr.buff_mode(st), "boss")

    def test_loadout_drops_boss_skill(self):
        from realm import loadout
        client = NS(state=NS(battle_config={}, active_pet_id=7))
        cfg = loadout.apply(client, {"char_skill": 103, "pet_skill": 102, "pet_id": 7}, mode="boss")
        self.assertEqual(cfg["char"], [])
        self.assertNotIn("pets", cfg)


@unittest.skipUnless(os.path.isdir(os.path.join(TS_BOT_PY, "train_bot")), "không có ts_bot")
class RealCombatTest(unittest.TestCase):
    """Gắn luật vào train_bot.combat thật của ts_bot (chỉ trong bộ nhớ)."""

    @classmethod
    def setUpClass(cls):
        from realm import bootstrap
        tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmp, "data"))
        bootstrap.prepare({"ts_bot_python": TS_BOT_PY, "ts_bot_data": os.path.join(tmp, "data"),
                           "runtime_dir": os.path.join(tmp, "rt")})
        from train_bot import combat
        cls.combat = combat

    def test_install_and_cleanse(self):
        fresh_rules()
        cb = self.combat
        orig = cb.decide_char
        cr.install(cb)
        self.assertIsNot(cb.decide_char, orig)
        chaos = next(s for s, (k, _) in sl.CC_KIND.items() if k == "chaos")
        st = fake_state(skills_char=[14022], status_by_kind={(3, 4): {"c": chaos}})
        d = cr.try_cleanse(cb, st, cb.config.UNIT_CHAR, st.skills_char, st.char, [])
        self.assertIsInstance(d, cb.Decision)
        self.assertEqual((d.skill, d.target, d.b), (14022, 4, 3))


if __name__ == "__main__":
    unittest.main()


class AndroidApiTest(unittest.TestCase):
    """Cầu nối app Android: mỗi tab một phiên, đăng nhập nền, chạy hoạt động, log tách theo tab."""

    def setUp(self):
        import json
        import logging
        from unittest import mock
        from realm import android_api as api
        import realm.main  # noqa: F401  nạp trước patch.dict(sys.modules), kẻo bị gỡ khi stop
        import realm.features  # noqa: F401
        self.json, self.api = json, api
        api._SESSIONS.clear()
        fake_tb = types.ModuleType("train_bot")
        fake_tb.config = NS(SERVERS={"trieu_van": {}, "tu_long": {}})
        self.ran = []
        test = self

        class FakeCli:
            def __init__(self, name):
                self.running, self.char_name, self._label = True, name, name
                self.current_map, self.world_boss_count, self.world_boss_max = 1001, 2, 5

            def close(self):
                self.running = False

        def connect(tb, cfg, settings, acc):
            if acc["password"] == "treo":          # server không cho vào map -> chờ tới khi huỷ
                acc["cancel"].wait(3)
                raise SystemExit("đã huỷ đăng nhập")
            if acc["password"] == "sai":
                raise SystemExit("sai mật khẩu")
            return FakeCli("NV_" + acc["username"])

        class FakeRunner:
            def __init__(self, client, cfg, settings, stop_event):
                self.c, self.s = client, settings

            def run(self, names):
                logging.getLogger("bot").info("[%s] chạy %s", self.c._label, names[0])
                test.ran.append((self.c.char_name, names[0], self.s["world_boss"]["damage_goal"]))

        self.patches = [mock.patch.dict(sys.modules, {"train_bot": fake_tb, "train_bot.config": fake_tb.config}),
                        mock.patch("realm.main.connect", connect),
                        mock.patch("realm.features.Runner", FakeRunner)]
        for p in self.patches:
            p.start()
        api._INIT["done"] = True            # bỏ phần gắn train_bot.combat thật
        h = api._RingHandler()
        h.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger("bot").addHandler(h)
        logging.getLogger("bot").setLevel(logging.INFO)
        self.handler = h

    def tearDown(self):
        import logging
        logging.getLogger("bot").removeHandler(self.handler)
        for p in self.patches:
            p.stop()
        self.api._SESSIONS.clear()

    def wait(self, tab, states, cap=3.0):
        end = time.time() + cap
        while time.time() < end:
            st = self.json.loads(self.api.status(tab))
            if st["state"] in states:
                return st
            time.sleep(0.02)
        self.fail("tab %s không tới %s" % (tab, states))

    def test_cancel_login(self):
        api, j = self.api, self.json
        self.assertTrue(j.loads(api.login("3", "acc3", "treo", "ts_realm"))["ok"])
        self.wait("3", ("logging_in",))
        self.assertTrue(j.loads(api.logout("3"))["ok"])
        st = self.wait("3", ("offline",))
        time.sleep(0.1)                                     # thread đăng nhập kết thúc
        st = j.loads(api.status("3"))
        self.assertEqual(st["state"], "offline")            # không bị đè thành "error"
        self.assertTrue(any("huỷ đăng nhập" in x for x in j.loads(api.logs("3", 0))["lines"]))

    def test_two_tabs(self):
        api, j = self.api, self.json
        self.assertEqual(api.servers(), ["ts_realm", "trieu_van", "tu_long"])
        self.assertTrue(j.loads(api.login("1", "acc1", "pw", "trieu_van"))["ok"])
        self.assertTrue(j.loads(api.login("2", "acc2", "sai", "trieu_van"))["ok"])
        st1 = self.wait("1", ("online",))
        self.assertEqual(st1["char"], "NV_acc1")
        self.assertEqual(st1["boss"], [2, 5])
        st2 = self.wait("2", ("error",))
        self.assertIn("sai", st2["error"])
        self.assertFalse(j.loads(api.run("2", '["world_boss"]'))["ok"])     # chưa đăng nhập
        r = j.loads(api.run("1", '["world_boss","npc40"]', '{"world_boss":{"damage_goal":7000000}}'))
        self.assertTrue(r["ok"])
        self.wait("1", ("online",))
        time.sleep(0.05)
        self.assertEqual(self.ran, [("NV_acc1", "world_boss", 7000000), ("NV_acc1", "npc40", 7000000)])
        lg1 = j.loads(api.logs("1", 0))
        self.assertTrue(any("chạy npc40" in x for x in lg1["lines"]))
        lg2 = j.loads(api.logs("2", 0))
        self.assertFalse(any("chạy" in x for x in lg2["lines"]))           # log không lẫn tab
        self.assertEqual(j.loads(api.logs("1", lg1["next"]))["lines"], [])
        self.assertEqual(api.busy_count(), 1)
        api.close_tab("1")
        self.assertEqual(api.busy_count(), 0)


class RealmLoginPacketTest(unittest.TestCase):
    """Cấu trúc gói C:001-000 của TS Realm, bắt từ game thật 26/11 (giá trị giả)."""

    def test_packet_layout(self):
        from realm.realm_login import build_realm_auth_packet
        x = bytes(b ^ 0xAD for b in build_realm_auth_packet("acc", "pw12", 1))
        self.assertEqual(x[:2], b"\xc0\x91")
        self.assertEqual(int.from_bytes(x[2:4], "little"), len(x))
        self.assertEqual(x[6], 0x01)
        self.assertEqual(x[7:20].hex(), "0000712901000000000001" + "0000")
        self.assertEqual(x[20:], b"\x03nil\x03acc\x04pw12\x0a\x00")

    def test_install_patches_client(self):
        import types
        from realm import realm_login
        mod = types.ModuleType("fake_client")
        realm_login.install(mod)
        self.assertEqual(mod.build_auth_packet("a", "b", 1), realm_login.build_realm_auth_packet("a", "b", 1))
        self.assertTrue(realm_login.is_realm_server("ts_realm"))
        self.assertFalse(realm_login.is_realm_server("trieu_van"))


class RealmSelfEntityTest(unittest.TestCase):
    def test_login_reply_feeds_0x69(self):
        from realm import realm_login
        calls = []

        class FakeClient:
            self_entity = None

            def _dispatch(self, opcode, pkt):
                calls.append(opcode)
                if opcode == 0x69:
                    self.self_entity = pkt[9:17]

        realm_login.patch_self_entity(FakeClient)
        # S:001-002 lấy từ capture (phần sau entity cắt bớt)
        pkt = bytes.fromhex("c091360000000102000001000100c5d1df4c838d03000ca7691e")
        c = FakeClient()
        c._dispatch(0x01, pkt)
        self.assertEqual(calls, [0x01, 0x69])
        self.assertEqual(c.self_entity, bytes.fromhex("c5d1df4c838d0300"))
        c._dispatch(0x01, pkt)            # đã có entity -> không gọi lại
        self.assertEqual(calls, [0x01, 0x69, 0x01])


class RealmBagTest(unittest.TestCase):
    def test_parse_58_byte_records(self):
        from realm.realm_login import parse_bag_snapshot

        def rec(idx, tid, cnt):
            return idx.to_bytes(2, "little") + tid.to_bytes(2, "little") + cnt.to_bytes(4, "little") + bytes(50)
        body = b"\x00" + (3).to_bytes(2, "little") + rec(1, 14509, 1) + rec(53, 46629, 2) + rec(172, 46614, 6)
        frame = b"\xc0\x91" + (9 + len(body)).to_bytes(2, "little") + b"\x00\x00\x17\x05\x00" + body
        self.assertEqual(parse_bag_snapshot(frame), {1: [14509, 1], 53: [46629, 2], 172: [46614, 6]})
        self.assertIsNone(parse_bag_snapshot(frame[:-1]))       # sai độ dài -> không đoán


class RealmUseItemTest(unittest.TestCase):
    def test_use_payload_matches_capture(self):
        from realm.realm_login import use_item_payload
        self.assertEqual(use_item_payload(172).hex(), "0f00ac00010000000000")
        self.assertEqual(use_item_payload(53).hex(), "0f003500010000000000")
        self.assertEqual(use_item_payload(100, qty=5, target=5).hex(), "0f006400050000000500")

    def test_set_item_updates_bag(self):
        from realm import realm_login
        sent = []

        class Cli:
            def __init__(self):
                self.bag_slots = {172: [46614, 6], 53: [46629, 2]}
                self.bag_counts = {}

            def _dispatch(self, opcode, pkt):
                pass

            def send(self, op, pl):
                sent.append((op, pl))
        realm_login.patch_bag_snapshot(Cli)
        realm_login.patch_use_slot(Cli)
        c = Cli()
        self.assertTrue(c.use_slot(172))
        self.assertEqual(sent, [(0x17, bytes.fromhex("0f00ac00010000000000"))])
        frame = bytes.fromhex("c091440000001708" + "00ac0016b605000000") + bytes(51)
        c._dispatch(0x17, frame)
        self.assertEqual(c.bag_slots[172], [46614, 5])
        self.assertEqual(c.bag_counts[46614], 5)


class RealmBattleMarkerTest(unittest.TestCase):
    def test_bare_020_008_ignored_in_battle(self):
        from realm import realm_login
        seen = []

        class Cli:
            def __init__(self):
                self.state = NS(in_battle=True)

            def _dispatch(self, opcode, pkt):
                seen.append(pkt.hex())
                if opcode == 0x14 and pkt[7:9] == b"\x08\x00":
                    self.state.in_battle = False
        realm_login.patch_battle_start_marker(Cli)
        c = Cli()
        c._dispatch(0x14, bytes.fromhex("c091090000001408 00".replace(" ", "")))
        self.assertTrue(c.state.in_battle)              # "0800" giữa trận -> bỏ qua
        c._dispatch(0x14, bytes.fromhex("c0910a000000140800" + "26"))
        self.assertFalse(c.state.in_battle)             # "080026" = kết trận thật


class RealmTurnOrderTest(unittest.TestCase):
    def test_offers_delivered_after_turn_start(self):
        from realm import realm_login
        seen = []

        class Cli:
            def _dispatch(self, opcode, pkt):
                seen.append((opcode, pkt[7]))
        realm_login.patch_turn_order(Cli)
        c = Cli()

        def fr(op, sub):
            return b"\xc0\x91\x0b\x00\x00\x00" + bytes([op, sub, 0, 0])
        for op, sub in ((0x35, 1), (0x35, 1), (0x49, 4), (0x34, 1), (0x33, 1), (0x35, 5)):
            c._dispatch(op, fr(op, sub))
        self.assertEqual(seen, [(0x49, 4), (0x34, 1), (0x35, 1), (0x35, 1), (0x33, 1), (0x35, 5)])
        c._dispatch(0x35, fr(0x35, 1))          # danh sách trạng thái lúc kết trận, không có 052
        c._dispatch(0x0b, fr(0x0b, 0))
        self.assertEqual(seen[-2:], [(0x35, 1), (0x0b, 0)])


class BattleViewTest(unittest.TestCase):
    def test_actions_become_readable_lines(self):
        from realm.battle_view import BattleView

        class Tr:
            def __init__(self):
                self.active, self.turn = False, 0
                self.units = {(3, 2): NS(hp=500, hp_max=1000, name="NV", template_id=0),
                              (2, 2): NS(hp=900, hp_max=1000, name="", template_id=0),
                              (0, 2): NS(hp=990000, hp_max=1000000, name="", template_id=0)}

            def apply(self, opcode, pkt):
                return self.next

        class Cli:
            def __init__(self):
                self.battle_tracker = Tr()
                self.state = NS(my_atype=2)
                self.char_name, self.pet_name = "NV", "Lữ Bố"

            def _dispatch(self, opcode, pkt):
                pass
        c = Cli()
        v = BattleView(c, skill_names={13013: "Loạn Kích", 12037: "Long Bá", 14021: "Hỗn Loạn"}, npc_names={})
        ev = lambda kind, **kw: NS(kind=kind, **kw)
        c.battle_tracker.next = [ev("start")]
        c.battle_tracker.active = True
        c.battle_tracker.apply(0x0b, b"")
        c.battle_tracker.turn = 1
        c.battle_tracker.next = [
            ev("action", source=(3, 2), position=(0, 2), skill_id=13013, payload=(1, 1, 0, ((25, -5000, 995000),))),
            ev("action", source=(2, 2), position=(0, 2), skill_id=12037, payload=(1, 1, 0, ((25, -13000, 982000),))),
            ev("action", source=(0, 2), position=(2, 2), skill_id=14021, payload=(1, 0, 2, ()))]
        c.battle_tracker.apply(0x32, b"")
        c._dispatch(0x49, bytes.fromhex("c0910e00000049040045e3000014"))
        snap = v.snapshot()
        self.assertTrue(snap["active"])
        self.assertEqual(snap["char"]["skill"], "Loạn Kích")
        self.assertEqual(snap["pet"]["dmg"], 13000)
        self.assertEqual(snap["boss"]["skill"], "Hỗn Loạn")
        self.assertEqual(snap["boss"]["target"], "Pet")
        self.assertEqual(snap["fight_damage"], 0xe345)
        self.assertEqual(snap["turns_left"], 0x14)
        self.assertEqual(snap["recent"][0], "Lượt 1 · Nhân vật: Loạn Kích → Boss  (-5.000)")


class WorldBossAutoBuyTest(unittest.TestCase):
    def setUp(self):
        from realm import world_boss as wb
        self.wb = wb
        wb.time.sleep = lambda s: None
        self.dlog = wb.DamageLog(os.path.join(tempfile.mkdtemp(), "d.json"))

    def test_shop_payload_matches_capture(self):
        self.assertEqual(self.wb.shop_ticket_payload().hex(), "010001010904" + "16b6" + "0900" + "010000")

    def test_buys_one_ticket_per_fight_until_goal(self):
        c = FakeClient()
        c.world_boss_count = 5
        c.bag_slots = {}
        c.fight_damage = 2_000_000
        buys = []

        def send(op, pl):
            buys.append((op, pl.hex()))
            c.bag_slots[172] = [46614, c.bag_slots.get(172, [0, 0])[1] + 1]
        c.send = send
        ok, why = self.wb.run(c, "acc1", "2026-11-25", self.dlog, {"auto_buy": True, "damage_goal": 5_000_000})
        self.assertEqual(len(buys), 3)                     # 2tr x3 = 6tr >= 5tr
        self.assertTrue(all(op == 0x42 for op, _ in buys))
        self.assertIn("đủ dame", why)

    def test_server_total_counts_manual_fights(self):
        c = FakeClient()
        c.world_boss_count = 5
        c.realm_wb_total, c.realm_wb_total_day = 4_950_000, "2026-11-25"
        c.bag_slots = {9: (46629, 3)}
        orig = c.do_world_boss

        def boss(heal_after=False):                       # server cộng dame trận vào S:073-003
            r = orig(heal_after)
            c.realm_wb_total += c.fight_damage
            return r
        c.do_world_boss = boss
        ok, why = self.wb.run(c, "acc1", "2026-11-25", self.dlog, {"damage_goal": 5_000_000})
        self.assertEqual(sum(1 for x in c.log if x[0] == "ticket"), 1)   # 1 trận là vượt 5tr
        self.assertIn("đủ dame", why)

    def test_buy_failure_stops(self):
        c = FakeClient()
        c.world_boss_count = 5
        c.bag_slots = {}
        c.send = lambda op, pl: None                      # server không giao vé
        self.wb.time.time = __import__("time").time
        ok, why = self.wb.run(c, "acc1", "2026-11-25", self.dlog, {"auto_buy": True})
        self.assertIn("mua vé không được", why)


class LoadoutTest(unittest.TestCase):
    def test_apply_sets_pet_role_skill_rules_and_buffs(self):
        from realm import loadout
        rules = NS(RULES={})
        c = NS(state=NS(battle_config={"char": [{"skill": 1, "condition": "always"}]}, active_pet_id=0xb166))
        loadout.apply(c, {"pet_id": 0x2ee2, "char_skill": 13013, "pet_skill": 13010,
                          "pet_buff": 12045, "pet_buff_target": "pet"}, rules_mod=rules)
        cfg = c.state.battle_config
        self.assertEqual(cfg["pet_roles"], {"boss": 0x2ee2})
        # Boss TG bỏ chọn skill đánh (tự đánh skill SP cao nhất) -> không thêm luật skill
        self.assertEqual([r["skill"] for r in cfg["char"]], [1])     # luật cũ giữ nguyên
        self.assertNotIn("pets", cfg)
        self.assertEqual(rules.RULES["boss_buffs"], {"pet": {"skill": 12045, "target": "pet"}})
        loadout.apply(c, {}, rules_mod=rules)                         # bỏ chọn -> gỡ sạch
        cfg = c.state.battle_config
        self.assertNotIn("boss", cfg["pet_roles"])
        self.assertEqual([r["skill"] for r in cfg["char"]], [1])
        self.assertNotIn("pets", cfg)
        self.assertEqual(rules.RULES["boss_buffs"], {})


class BuffRuleTest(unittest.TestCase):
    def test_buff_once_then_wait_gap(self):
        from realm import combat_rules as cr_mod
        cfg = NS(UNIT_CHAR=3, UNIT_PET=2, SKILL_INFO={12045: {"name": "Nhiệt Hống"}})
        comb = NS(config=cfg, _skill_cost=lambda s: 60, Decision=lambda u, a, c, s, b=0: (u, s, b, c))
        tr = NS(generation=1, turn=1)
        st = NS(label="t", boss_mode=True, my_atype=2, char_row=3, tracker=tr, status_by_kind={},
                pet=NS(hp=100, hp_max=100), char=NS(hp=100, hp_max=100))
        stat = NS(sp=500, hp=100, hp_max=100)
        old = dict(cr_mod.RULES)
        try:
            cr_mod.RULES["boss_buffs"] = {"pet": {"skill": 12045, "target": "pet"}}
            cr_mod._buff_cast.clear()
            self.assertEqual(cr_mod.try_buff(comb, st, 2, [12045], stat, []), (2, 12045, 2, 2))
            tr.turn = 2
            self.assertIsNone(cr_mod.try_buff(comb, st, 2, [12045], stat, []))      # mới buff
            tr.turn = 4
            st.status_by_kind = {(2, 2): {4: 12045}}
            self.assertIsNone(cr_mod.try_buff(comb, st, 2, [12045], stat, []))      # còn buff
            st.status_by_kind = {}
            self.assertEqual(cr_mod.try_buff(comb, st, 2, [12045], stat, [])[1], 12045)
            st.boss_mode = False
            tr.turn = 9
            self.assertIsNone(cr_mod.try_buff(comb, st, 2, [12045], stat, []))      # ngoài boss
        finally:
            cr_mod.RULES.clear(); cr_mod.RULES.update(old)


class ModeLoadoutTest(unittest.TestCase):
    """Đội hình riêng cho 40 NPC / Nhị Kiều: pet, skill đánh, buff."""

    def setUp(self):
        self.old = json_copy(cr.RULES)
        cr.RULES["mode_buffs"], cr.RULES["boss_buffs"] = {}, {}
        cr._buff_cast.clear()

    def tearDown(self):
        cr.RULES.clear()
        cr.RULES.update(self.old)

    def test_apply_per_mode_and_clear(self):
        from realm import loadout
        c = NS(state=NS(battle_config={"char": [{"skill": 1, "condition": "always"}]}, active_pet_id=0xb166))
        loadout.apply(c, {"pet_id": 0x2ee2, "char_skill": 13013, "pet_buff": 12045}, rules_mod=cr)
        loadout.apply(c, {"pet_id": 0x1111, "char_skill": 14001, "pet_skill": 14002,
                          "char_buff": 12050, "char_buff_target": "char"}, rules_mod=cr, mode="npc40")
        cfg = c.state.battle_config
        self.assertEqual(cfg["pet_roles"], {"boss": 0x2ee2, "npc40": 0x1111})
        self.assertEqual([(r["skill"], r["condition"]) for r in cfg["char"]],
                         [(14001, "quest"), (1, "always")])       # boss không còn luật skill
        self.assertEqual(cfg["pets"][str(0x1111)][0]["tag"], "realm_npc40")
        self.assertEqual(cr.RULES["mode_buffs"]["npc40"], {"char": {"skill": 12050, "target": "char"}})
        self.assertEqual(cr.RULES["mode_buffs"]["boss"], {"pet": {"skill": 12045, "target": "pet"}})
        loadout.clear(c, "npc40", rules_mod=cr)
        cfg = c.state.battle_config
        self.assertEqual(cfg["pet_roles"], {"boss": 0x2ee2})             # Boss TG giữ nguyên
        self.assertEqual([r["skill"] for r in cfg["char"]], [1])
        self.assertNotIn("pets", cfg)
        self.assertEqual(cr.RULES["mode_buffs"]["npc40"], {})
        with self.assertRaises(ValueError):
            loadout.apply(c, {}, mode="pb_don")

    def test_buff_uses_mode_config(self):
        cfg = NS(UNIT_CHAR=3, UNIT_PET=2, SKILL_INFO={})
        comb = NS(config=cfg, _skill_cost=lambda s: 60, Decision=lambda u, a, c, s, b=0: (u, s, b, c))
        tr = NS(generation=1, turn=1)
        st = NS(label="m", boss_mode=False, realm_mode="npc40", my_atype=2, char_row=3, tracker=tr,
                status_by_kind={}, pet=NS(hp=100, hp_max=100), char=NS(hp=100, hp_max=100))
        stat = NS(sp=500, hp=100, hp_max=100)
        cr.RULES["mode_buffs"] = {"boss": {"pet": {"skill": 111, "target": "pet"}},
                                  "npc40": {"pet": {"skill": 222, "target": "pet"}},
                                  "nhi_kieu": {"char": {"skill": 333, "target": "char"}}}
        self.assertEqual(cr.try_buff(comb, st, 2, [111, 222], stat, []), (2, 222, 2, 2))
        st.realm_mode = "nhi_kieu"
        self.assertIsNone(cr.try_buff(comb, st, 2, [111, 222], stat, []))    # pet Nhị Kiều không chọn buff
        self.assertEqual(cr.try_buff(comb, st, 3, [333], stat, []), (3, 333, 3, 2))
        st.realm_mode, st.boss_mode = None, True
        self.assertEqual(cr.try_buff(comb, st, 2, [111], stat, [])[1], 111)
        st.boss_mode = False
        self.assertIsNone(cr.try_buff(comb, st, 2, [111], stat, []))         # train: không buff

    def test_runner_applies_and_restores(self):
        seen = {}

        class Cli(FakeClient):
            def ensure_pet_role(self, role):
                self.log.append(("pet", role, (self.state.battle_config.get("pet_roles") or {}).get(role)))
                return True

        from realm import npc40_loop

        def fake_loop(client, point, stop, on_loss, before_repeat, window_open, max_consec):
            seen["npc40"] = (dict(cr.RULES["mode_buffs"].get("npc40") or {}),
                             [r["skill"] for r in client.state.battle_config["char"]])
            return "xong"
        orig = npc40_loop.run_loop
        npc40_loop.run_loop = fake_loop
        try:
            c = Cli()
            c.state.battle_config = {}
            c.default_pet_role = "train"
            lo = {"npc40": {"pet_id": 7, "char_skill": 14001, "pet_buff": 12045},
                  "nhi_kieu": {"char_buff": 12050, "char_buff_target": "char"}}
            r = features.Runner(c, CONFIG, {"windows": ALWAYS, "loadouts": lo}, threading.Event())
            self.assertTrue(r.npc40())
            self.assertEqual(seen["npc40"], ({"pet": {"skill": 12045, "target": "pet"}}, [14001]))
            self.assertIn(("pet", "npc40", 7), c.log)
            self.assertEqual(c.log[-1], ("pet", "train", None))                 # trả pet
            self.assertEqual(c.state.battle_config["char"], [])                # gỡ luật 40 NPC
            self.assertEqual(cr.RULES["mode_buffs"]["npc40"], {})
            c.log.clear()
            orig_crawl = c.start_floor_crawl

            def crawl(ev, **kw):
                seen["nk"] = (c.state.realm_mode, dict(cr.RULES["mode_buffs"].get("nhi_kieu") or {}))
                return orig_crawl(ev, **kw)
            c.start_floor_crawl = crawl
            self.assertTrue(r.nhi_kieu())
            self.assertEqual(seen["nk"], ("nhi_kieu", {"char": {"skill": 12050, "target": "char"}}))
            self.assertNotIn("pet", [x[0] for x in c.log])                     # không chọn pet -> không đổi
            self.assertIsNone(c.state.realm_mode)
            self.assertEqual(cr.RULES["mode_buffs"]["nhi_kieu"], {})
        finally:
            npc40_loop.run_loop = orig


class BuffDedupTest(unittest.TestCase):
    """Không buff trùng: nhân vật + pet cùng buff một mục tiêu, hoặc mục tiêu đang có buff cùng loại."""

    def setUp(self):
        self.old = json_copy(cr.RULES)
        cr._buff_cast.clear()
        cr._SKILL_KIND.clear()
        cfg = NS(UNIT_CHAR=3, UNIT_PET=2, SKILL_INFO={})
        self.comb = NS(config=cfg, _skill_cost=lambda s: 60, Decision=lambda u, a, c, s, b=0: (u, s, b, c))
        self.tr = NS(generation=1, turn=1)
        self.st = NS(label="d", party_idx=None, boss_mode=True, realm_mode=None, my_atype=2, char_row=3,
                     tracker=self.tr, status_by_kind={}, pet=NS(hp=100, hp_max=100), char=NS(hp=100, hp_max=100))
        self.stat = NS(sp=500, hp=100, hp_max=100)

    def tearDown(self):
        cr.RULES.clear()
        cr.RULES.update(self.old)
        cr._SKILL_KIND.clear()

    def test_char_and_pet_same_buff_same_target(self):
        cr.RULES["mode_buffs"] = {"boss": {"char": {"skill": 12045, "target": "pet"},
                                           "pet": {"skill": 12045, "target": "pet"}}}
        self.assertEqual(cr.try_buff(self.comb, self.st, 3, [12045], self.stat, [])[1], 12045)
        self.assertIsNone(cr.try_buff(self.comb, self.st, 2, [12045], self.stat, []))   # pet không buff lại
        self.tr.turn = 2
        self.assertIsNone(cr.try_buff(self.comb, self.st, 2, [12045], self.stat, []))   # vẫn trong gap

    def test_same_kind_already_on_target(self):
        cr.RULES["mode_buffs"] = {"boss": {"pet": {"skill": 12046, "target": "pet"}}}
        self.st.status_by_kind = {(3, 1): {7: 12045}}            # đã thấy 12045 chiếm ô trạng thái 7
        self.assertEqual(cr.try_buff(self.comb, self.st, 2, [12046], self.stat, [])[1], 12046)
        self.tr.generation = 2
        self.st.status_by_kind = {(3, 1): {7: 12045}, (2, 2): {7: 12046}}
        cr.RULES["mode_buffs"] = {"boss": {"char": {"skill": 12045, "target": "pet"}}}
        self.assertIsNone(cr.try_buff(self.comb, self.st, 3, [12045], self.stat, []))   # cùng loại đang có


class RealmRuleOrderTest(unittest.TestCase):
    """Skill đánh do app chọn không chen trước hồi sinh / giải; tới bước đánh mới dùng."""

    def setUp(self):
        fresh_rules()
        cb = self.cb = fake_combat()
        cb.config.SKILL_HEAL_ALL, cb.config.HEAL_SP_COST = 11010, 42
        cb.config.CHAR_FIRE_MIN_SP = cb.config.PET_FIRE_MIN_SP = 65
        cb._CUSTOM_AUTO = object()
        cb._battle_rules = lambda st, key: list((st.battle_config or {}).get(key) or [])

        def custom(st, unit, key, skills, stat, options):
            rules = cb._battle_rules(st, key)
            return ("RULE", rules[0]["skill"]) if rules else None
        cb._custom_decision = custom
        cb._hang_char_ta = lambda st: 3
        cb._heal_decide = None
        cb._claim_support_action = lambda *a: True
        cb._try_cc = lambda *a: None
        cb._try_break_enemy_protect = lambda *a: None
        cb._try_sp_restore = lambda *a: None
        cb._try_protect = lambda *a: None
        cb._combat_attack = lambda *a: "ATTACK"
        cr.install(cb)

    def st(self, rules, **kw):
        st = fake_state(realm_mode="npc40", quest_mode=True, battle_config={"char": rules},
                        allies={(3, 2): NS(hp=900, hp_max=1000)}, char=NS(sp=200, hp=900, hp_max=1000),
                        enemy_hp={0: 10}, **kw)
        st.lowest_hp_ally = lambda: None
        return st

    def test_realm_rule_after_support(self):
        realm_rule = {"skill": 14001, "condition": "quest", "tag": "realm_npc40"}
        self.cb._try_revive = lambda *a: "REVIVE"
        self.assertEqual(self.cb.decide_char(self.st([realm_rule]), []), "REVIVE")
        self.cb._try_revive = lambda *a: None
        self.assertEqual(self.cb.decide_char(self.st([realm_rule]), []), ("RULE", 14001))
        self.assertEqual(self.cb.decide_char(self.st([]), []), "ATTACK")
        user_rule = {"skill": 999, "condition": "always"}                       # luật riêng của người dùng
        self.assertEqual(self.cb.decide_char(self.st([user_rule, realm_rule]), []), ("RULE", 999))


def json_copy(d):
    import json
    return json.loads(json.dumps(d))
