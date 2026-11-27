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


class NpcDangerTest(unittest.TestCase):
    """NPC có skill nguy hiểm (realm/npc_danger.py) bị đánh trước trong 40 NPC / Nhị Kiều / Boss."""

    def setUp(self):
        fresh_rules()
        cr.RULES.update({"danger_first": True, "danger_min_tier": 1, "npc40_ai": "ts_manager",
                         "tsm_modes": ["npc40", "nhi_kieu", "boss"]})

    def tearDown(self):
        cr.RULES.update({"danger_first": True, "danger_min_tier": 1})

    def _state(self, tids, hp, **kw):
        units = {(p // 10, p % 10): NS(template_id=t) for p, t in tids.items()}
        return fake_state(realm_mode="nhi_kieu", enemy_hp=hp, tracker=NS(units=units), **kw)

    def test_table(self):
        from realm import npc_danger as nd
        self.assertGreater(len(nd.DANGER), 500)
        self.assertEqual(nd.tier_of(45276), 3)   # Cuồng Đại Kiều: Đẩu Chuyển
        self.assertEqual(nd.tier_of(45275), 2)   # Cuồng Tiểu Kiều: Linh Kính (phản khống chế)
        self.assertEqual(nd.tier_of(10002), 0)   # Trương Bảo: skill thường
        info = {20014: {"splash": 5, "cat": 15}, 10012: {"splash": 8, "cat": 2}, 14021: {"splash": 1}}
        self.assertEqual(nd.classify([14021], info)[0], 0)          # Hỗn Loạn đơn: không tính
        self.assertEqual(nd.classify([20014], info), (2, [20014]))  # Tứ Nhân Hỗn Loạn (4 mục tiêu)
        self.assertEqual(nd.classify([21041], info), (3, [21041]))  # Bá Vương Trảm: hỗn loạn toàn thể
        self.assertEqual(nd.classify([10012], info), (1, [10012]))  # Long Trời Lỡ Đất

    def test_dangerous_first_then_low_hp(self):
        cb = fake_combat()
        cr.install(cb)
        st = self._state({0: 10002, 1: 10001, 2: 45276}, {0: 100, 1: 200, 2: 900})
        self.assertEqual(cb._lowest_hp_enemy(st, [0, 1, 2]), 2)    # Đẩu Chuyển (mức 3) trước
        cr.RULES["danger_min_tier"] = 3
        st = self._state({0: 10002, 1: 10001}, {0: 100, 1: 50})
        self.assertEqual(cb._lowest_hp_enemy(st, [0, 1, 2]), 1)    # không con mức 3: ít máu nhất

    def test_skip_barrier_and_off_modes(self):
        cb = fake_combat()
        cr.install(cb)
        st = self._state({0: 10002, 1: 45275, 2: 45276}, {0: 100, 1: 900, 2: 800},
                         status_by_kind={(0, 2): {"b": 10010}})
        self.assertEqual(cb._lowest_hp_enemy(st, [0, 1, 2]), 1)    # con Kết Giới chờ giải, đánh mức 2
        st = self._state({0: 10002, 2: 45276}, {0: 100, 2: 800})
        st.realm_mode = None                                       # farm thường: như cũ
        self.assertEqual(cb._lowest_hp_enemy(st, [0, 1, 2]), 0)
        st.realm_mode = "boss"
        self.assertEqual(cb._lowest_hp_enemy(st, [0, 1, 2]), 2)
        cr.RULES["danger_first"] = False
        self.assertEqual(cb._lowest_hp_enemy(st, [0, 1, 2]), 0)


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
        self.assertTrue(features.in_window(w["npc40"], mon_13))    # 40 NPC mở 12:00
        self.assertFalse(features.in_window(w["npc40"], datetime.datetime(2026, 11, 23, 11, 59)))
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
        if r == "end_no_prompt":                      # TS Realm: hết trận, không có hộp thoại
            client.exp_stats_battles = getattr(client, "exp_stats_battles", 0) + 1
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

    def test_battle_end_without_prompt_reopens_at_once(self):
        why, c, heals = self.run_loop(["end_no_prompt", "end_no_prompt", "win"])
        self.assertNotIn("không vào lại", why)
        self.assertEqual(c.log.count("end_no_prompt"), 2)
        self.assertEqual(len(heals), 3)                # mỗi trận xong là hồi rồi mở tiếp, không coi là kẹt

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
        cb._is_attack = lambda s: s in (13010, 13013)
        cb.config.SKILL_NORMAL = 10000
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

    def test_char_damage_first(self):
        """40 NPC: nhân vật còn skill dame đủ SP thì đánh trước khống chế; hết SP thì khống chế."""
        ok = {(3, 2): NS(hp=900, hp_max=1000)}
        st = self.st(skills_char=["cc", 13010], allies=ok, char=NS(sp=200, hp=900, hp_max=1000), enemy_hp={0: 10})
        self.assertEqual(self.cb.decide_char(st, []), "ATTACK")
        st.char = NS(sp=5, hp=900, hp_max=1000)                       # không đủ SP (giả lập 10 SP / skill)
        self.assertEqual(self.cb.decide_char(st, []), ("CC", "high"))

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
        r = self.cb.run(c, 40045, 40, 0, threading.Event(), 3, sleep_fn=lambda s: None, wait=0.01, gap=0,
                        max_refused=3)
        self.assertEqual(r["done"], 1)
        self.assertEqual(len(c.sent), 1 + 3)                          # thử lại rồi mới dừng
        self.assertIn("từ chối", r["why"])
        self.assertIn("ô trống", r["why"])

    def _notify(self, c, script):
        """Mỗi lần gửi gói hợp, server 'nói' câu tiếp theo trong ``script`` (None = im)."""
        orig = c.send
        msgs = list(script)

        def send(op, body):
            text = msgs.pop(0) if msgs else None
            if text and "Không hợp" in text:
                c.sent.append((op, body))                       # server bỏ qua cả lô, không trừ
            else:
                orig(op, body)
            if text:
                c.realm_notice_seq = getattr(c, "realm_notice_seq", 0) + 1
                c.realm_notices = getattr(c, "realm_notices", []) + [(c.realm_notice_seq, 0, text)]
        c.send = send

    def test_refused_once_then_retries(self):
        c = FakeBagClient({66: [40045, 9108]})
        self._notify(c, ["Hợp thành hàng loạt 20/20 lần: Tơ Lụa Tứ Xuyên x9 - phí 1780 Đồng",
                         "Không hợp thành được lần này. Chưa mất gì.",
                         "Hợp thành hàng loạt 19/20 lần: Tơ Lụa Tứ Xuyên x9 - phí 1691 Đồng - hoàn nguyên liệu 1 lần"])
        r = self.run_it(c, rounds=2)
        self.assertEqual(r["done"], 2)
        self.assertEqual(len(c.sent), 3)
        self.assertEqual(r["fee"], 1780 + 1691)

    def test_refused_with_free_slots_is_not_bag_full(self):
        c = FakeBagClient({66: [40045, 9108], 1: [1, 1]})
        c.realm_bag_cap = 210
        self._notify(c, ["Không hợp thành được lần này. Chưa mất gì."] * 5)
        r = self.cb.run(c, 40045, 40, 0, threading.Event(), 3, sleep_fn=lambda s: None, wait=0.01, gap=0,
                        max_refused=5)
        self.assertEqual(r["done"], 0)
        self.assertNotIn("đầy", r["why"])
        self.assertIn("208/210", r["why"])

    def test_refused_keeps_going_by_default(self):
        c = FakeBagClient({66: [40045, 9108]})
        self._notify(c, ["Không hợp thành được lần này. Chưa mất gì."] * 10
                     + ["Hợp thành hàng loạt 20/20 lần: x - phí 1780 Đồng"])
        r = self.run_it(c, rounds=1)
        self.assertEqual((r["done"], len(c.sent)), (1, 11))

    def test_real_bag_full(self):
        c = FakeBagClient({k: [1, 1] for k in range(1, 210)})
        c.bag_slots[210] = [40045, 9108]
        self._notify(c, ["Không hợp thành được lần này. Chưa mất gì."])
        r = self.run_it(c)
        self.assertEqual(len(c.sent), 1)
        self.assertIn("túi đầy (210/210", r["why"])

    def test_not_enough_money(self):
        c = FakeBagClient({66: [40045, 9108]})
        self._notify(c, ["Không đủ Đồng để hợp thành (cần 1780)."])
        r = self.run_it(c)
        self.assertEqual(len(c.sent), 1)
        self.assertIn("không đủ Đồng", r["why"])

    def test_money_estimate_explains_refusal(self):
        c = FakeBagClient({66: [40045, 9108]})
        c.money, c.realm_money_spent = 2000, 0
        orig = c.send

        def send(op, body):
            c.realm_money_spent += 1780
            orig(op, body)
        c.send = send
        self._notify(c, ["Hợp thành hàng loạt 20/20 lần: x - phí 1780 Đồng",
                         "Không hợp thành được lần này. Chưa mất gì."])
        r = self.run_it(c)
        self.assertEqual(r["done"], 1)
        self.assertIn("hết Đồng", r["why"])

    def test_full_refund_batch_counts_as_done(self):
        c = FakeBagClient({66: [40045, 9108]}, refuse_after=0)          # không trừ gì (hoàn hết)
        self._notify(c, ["Hợp thành hàng loạt 3/3 lần: thất bại 3 lần - phí 267 Đồng - hoàn nguyên liệu 3 lần"])
        r = self.run_it(c, rounds=1)
        self.assertEqual(r["done"], 1)

    def test_notice_patch_joins_chunks(self):
        from realm import realm_login as rl

        def frame(ch, text):
            raw = text.encode()
            body = b"\x0a\x00" + bytes([ch, 0, len(raw)]) + raw
            return b"\xc0\x91" + (len(body) + 7).to_bytes(2, "little") + b"\x00\x00\x02" + body

        class Base:
            bag_slots = {}

            def _dispatch(self, opcode, pkt):
                pass
        rl.patch_notices(Base)
        b = Base()
        first = "Hợp thành hàng loạt 20/20 lần: " + "a" * 400
        first = first.encode()[:250].decode("utf-8", "ignore")
        first = first + "b" * (250 - len(first.encode()))
        b._dispatch(0x02, frame(3, first))
        b._dispatch(0x02, frame(3, " - phí 1780 Đồng\x00"))
        b._dispatch(0x02, frame(2, "Không hợp thành được lần này. Chưa mất gì.\x00"))
        self.assertEqual(len(b.realm_notices), 2)
        self.assertTrue(b.realm_notices[0][2].endswith("phí 1780 Đồng"))
        kind, info = self.cb.classify([b.realm_notices[0][2]])
        self.assertEqual((kind, info["fee"]), ("batch", 1780))
        self.assertEqual(self.cb.classify([b.realm_notices[1][2]])[0], "refused")
        b._dispatch(0x1a, b"\xc0\x91\x0d\x00\x00\x00\x1a" + b"\x02\x00" + (1780).to_bytes(4, "little"))
        self.assertEqual(b.realm_money_spent, 1780)

    def test_bag_capacity_from_highest_slot(self):
        c = FakeBagClient({5: [1, 1], 210: [2, 1]})
        self.assertEqual((self.cb.bag_capacity(c), self.cb.bag_free(c)), (210, 208))
        c.realm_bag_max_slot = 215
        self.assertEqual(self.cb.bag_capacity(c), 215)

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

    def _gear_client(self, swallow):
        """Mỗi lần hợp ra 2 món; ``swallow(n)`` True = server nuốt lượt phân giải thứ n."""
        c = FakeBagClient({66: [40045, 9108]})
        orig_send = c.send
        c.decomp = 0

        def send(op, body):
            orig_send(op, body)
            if op == 0x17:
                c.bag_slots[100 + len(c.sent)] = [20430, 1]
                c.bag_slots[200 + len(c.sent)] = [20430, 1]
            elif op == 0x59 and body[0] == 3:
                c.decomp += 1
                if swallow(c.decomp):
                    return
                for i in range(body[2]):
                    c.bag_slots.pop(int.from_bytes(body[3 + 6 * i:5 + 6 * i], "little"), None)
        c.send = send
        return c

    def _run_gear(self, c, rounds):
        orig_items = self.cb._items
        self.cb._items = lambda: {20430: {"fc": 690}}
        try:
            return self.cb.run(c, 40045, 40, rounds, threading.Event(), 3, sleep_fn=lambda s: None,
                               wait=0.01, gap=0, settle=0)
        finally:
            self.cb._items = orig_items

    def test_decompose_resends_swallowed_batch(self):
        c = self._gear_client(lambda n: n == 1)
        r = self._run_gear(c, 1)
        self.assertEqual((r["done"], r["broken"]), (1, 2))
        self.assertEqual([t for t, _ in c.bag_slots.values()], [40045])

    def test_decompose_failure_does_not_stop_combine(self):
        c = self._gear_client(lambda n: n <= 3)          # lần hợp 1: cả 3 lượt bị nuốt
        r = self._run_gear(c, 3)
        self.assertEqual(r["done"], 3)
        self.assertNotIn("phân giải", r["why"])
        self.assertEqual(r["broken"], 6)                  # 2 món hụt được phân giải ở lần sau
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
                         "boss_skip": ["heal"], "boss_sp_below": 0.3,
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
        cb._try_sp_restore = lambda *a: "SP_RESTORE"    # bản ts_bot không dùng trong boss
        st = self.st(skills_char=[11010, 103], char=NS(sp=350, hp=900, hp_max=1000),
                     allies={(3, 2): NS(hp=50, hp_max=1000), (3, 1): NS(hp=60, hp_max=1000)})
        self.assertEqual(cb.decide_char(st, [(1, 2)]).skill, 103)
        cr.RULES["boss_skip"] = []          # tắt bỏ qua -> hồi máu như 40 NPC
        st2 = self.st(skills_char=[11010, 103], char=NS(sp=350, hp=900, hp_max=1000),
                      allies={(3, 2): NS(hp=50, hp_max=1000), (3, 1): NS(hp=60, hp_max=1000)})
        self.assertEqual(cb.decide_char(st2, [(1, 2)]).skill, 11010)
        cr.RULES["boss_skip"] = ["heal"]

    def test_boss_sp_restore_below_30(self):
        cb = self.cb
        cb.pick_sp_restore_skill = lambda sk: 11030 if 11030 in sk else None
        self.COST[11030] = 40
        allies = {(3, 2): NS(hp=900, hp_max=1000, sp=100, sp_max=1000)}
        st = self.st(skills_char=[11030, 103], char=NS(sp=350, sp_max=1000, hp=900, hp_max=1000), allies=allies)
        d = cb.decide_char(st, [(1, 2)])
        self.assertEqual((d.skill, d.target, d.b), (11030, 2, 3))
        allies = {(3, 2): NS(hp=900, hp_max=1000, sp=400, sp_max=1000)}
        st2 = self.st(skills_char=[11030, 103], char=NS(sp=350, sp_max=1000, hp=900, hp_max=1000), allies=allies)
        self.assertEqual(cb.decide_char(st2, [(1, 2)]).skill, 103)      # SP 40% -> đánh

    def test_boss_sp_item_when_no_skill(self):
        cb = self.cb
        cb.pick_sp_restore_skill = lambda sk: None
        cb._hang_cua = lambda st, u: 3 if u == CHAR else 2
        cr._item_used.clear()
        pending = {}
        st = self.st(skills_char=[103], char=NS(sp=350, sp_max=1000, hp=900, hp_max=1000),
                     my_atype=2, allies={(3, 2): NS(hp=900, hp_max=1000, sp=350, sp_max=1000),
                                         (2, 2): NS(hp=900, hp_max=1000, sp=50, sp_max=1000)},
                     realm_item_pending=pending, realm_sp_item=lambda: (7, 0x6a12, 265),
                     tracker=NS(generation=1, turn=1))
        d = cb.decide_char(st, [(1, 2)])
        self.assertEqual((d.skill, d.b, d.target), (0x6a12, 2, 2))   # nhân vật cho pet uống thuốc SP
        self.assertEqual(pending, {(3, 2): 0x6a12})
        st.last_atk_gen_char = None
        d2 = cb.decide_char(st, [(1, 2)])                            # cùng lượt -> không cho uống lại
        self.assertEqual(d2.skill, 103)
        st3 = self.st(pet_skills=[102], pet=NS(sp=50, sp_max=1000, hp=900, hp_max=1000),
                      realm_item_pending={}, realm_sp_item=lambda: (7, 0x6a12, 265))
        self.assertEqual(cb.decide_pet(st3, [(1, 2)]).skill, 10000)   # pet không dùng thuốc, hết SP -> đánh thường

    def test_item_payload_rewrite(self):
        from realm import world_boss as wb
        pending = {(3, 2): 0x6a12}
        pl = bytes.fromhex("01000302020212 6a5680".replace(" ", ""))
        self.assertEqual(wb.item_payload(pl, pending).hex(), "02000302020212 6a5680".replace(" ", ""))
        self.assertEqual(pending, {})
        atk = bytes.fromhex("0100030200021d2b0178")
        self.assertEqual(wb.item_payload(atk, {(3, 2): 0x6a12}), atk)   # đánh thường giữ nguyên

    def test_not_ready_after_heal(self):
        from realm import world_boss as wb
        healed = []
        c = NS(_label="a", in_combat=lambda: False, heal_full=lambda: healed.append(1),
               state=NS(char=NS(hp=1000, hp_max=1000, sp=0, sp_max=682),
                        pet=NS(hp=2, hp_max=5984, sp=100, sp_max=100)))
        why = wb.not_ready(c, 0.95)
        self.assertEqual(healed, [1])
        self.assertIn("SP nhân vật 0/682", why)
        self.assertIn("HP pet 2/5984", why)
        c.state.char.sp, c.state.pet.hp = 682, 5984
        self.assertIsNone(wb.not_ready(c, 0.95))

    def test_stall_watch_closes(self):
        from realm import world_boss as wb
        closed = []
        c = NS(_label="a", running=True, state=NS(in_battle=True), close=lambda: closed.append(1))
        tap = NS(last=time.time() - 100)
        w = wb.StallWatch(c, tap, stall_s=5)
        for _ in range(40):
            if w.stalled:
                break
            time.sleep(0.1)
        w.remove()
        self.assertTrue(w.stalled)
        self.assertEqual(closed, [1])

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
        self.ran, self.parties = [], []
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
            def __init__(self, client, cfg, settings, stop_event, party=None):
                self.c, self.s, self.party = client, settings, party

            def run(self, names):
                logging.getLogger("bot").info("[%s] chạy %s", self.c._label, names[0])
                if self.party is not None:
                    role = self.party["role"]
                    if role == "member":
                        self.party["done"].wait(2)
                    test.parties.append((self.c.char_name, names[0], role,
                                         self.s.get("max_losses", {}).get("npc40")))
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

    def test_run_party(self):
        api, j = self.api, self.json
        for t in ("1", "2"):
            api.login(t, "acc" + t, "pw", "trieu_van")
            self.wait(t, ("online",))
        self.assertFalse(j.loads(api.run_party("1", '["2"]', '["world_boss"]'))["ok"])   # chỉ 40 NPC / Nhị Kiều
        api._SETTINGS["windows"] = {"npc40": {"days": [], "start": "00:00", "end": "00:01"}}
        r = j.loads(api.run_party("1", '["2"]', '["npc40"]'))
        self.assertFalse(r["ok"])
        self.assertIn("Ngoài giờ", r["error"])
        self.assertIn("Ngoài giờ", j.loads(api.status("1"))["note"])           # hiện trên app
        api._SETTINGS["windows"] = {"npc40": None}
        self.assertTrue(j.loads(api.party_status())["tabs"][0]["char"].startswith("NV_"))
        opts = {"max_losses": {"npc40": 3}, "_tabs": {"2": {"max_losses": {"npc40": 7}}}}
        r = j.loads(api.run_party("1", '["2"]', '["npc40","world_boss"]', j.dumps(opts)))
        self.assertTrue(r["ok"], r)
        self.wait("2", ("online",))
        self.wait("1", ("online",))
        time.sleep(0.05)
        self.assertEqual(sorted(self.parties), [("NV_acc1", "npc40", "leader", 3), ("NV_acc2", "npc40", "member", 7)])
        api._SETTINGS.pop("windows", None)

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

    def test_potion_data_filled(self):
        """Thuốc Hoàng Cân / Viên Côn Lôn thiếu cột sp/hp -> bot báo 'HET thuoc' dù túi có 5890 lọ."""
        import types
        from realm import realm_login
        raw = {
            "0x6a12": {"name": "Thuốc Hoàng Cân", "kd": 18, "a1k": 26, "a1v": 265},
            "0x6a14": {"name": "Viên Côn Lôn", "kd": 18, "a1k": 25, "a1v": 265},
            "0x6979": {"name": "Cam Thảo", "hp": 10, "sp": 0, "kd": 18, "a1k": 25, "a1v": 110},
            "0x6645": {"name": "Rượu Linh Chi", "kd": 17, "bs": 254, "a1k": 26, "a1v": 241},
            "0x6648": {"name": "Rượu Cung Quy", "kd": 17, "a1k": 26, "a1v": 100},
            "0x5b0f": {"name": "Nước Mắt A Thập", "kd": 14, "a1v": 100},
        }
        mod = types.ModuleType("fake_client")
        cache = {int(k, 16): {"name": v["name"], "hp": v.get("hp", 0), "sp": v.get("sp", 0)}
                 for k, v in raw.items()}
        mod._load_gamedata_items = lambda: cache
        mod._load_json_data_file = lambda name: raw
        realm_login.patch_potion_data(mod)
        realm_login.patch_potion_data(mod)          # gọi lại không bọc 2 lần
        items = mod._load_gamedata_items()
        self.assertEqual((items[0x6a12]["hp"], items[0x6a12]["sp"]), (0, 165))
        self.assertEqual((items[0x6a14]["hp"], items[0x6a14]["sp"]), (165, 0))
        self.assertEqual(items[0x6979]["hp"], 10)
        for tid in (0x6645, 0x6648, 0x5b0f):
            self.assertEqual((items[tid]["hp"], items[tid]["sp"]), (0, 0))


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


def _realm_pet_list(pets):
    """S:015-008 khuôn TS Realm: [(mã pet, tên, {ô: mã đồ})] -> frame đủ header."""
    body = bytearray(b"\x08\x00\x09" + bytes([len(pets)]))
    for i, (pid, name, eq) in enumerate(pets, 1):
        nm = name.encode("utf-8")
        head = bytearray(35 + len(nm))
        head[0] = i
        head[1:3] = pid.to_bytes(2, "little")
        head[31] = len(nm)
        head[32:32 + len(nm)] = nm
        head[32 + len(nm):35 + len(nm)] = b"\x0a\x0a\x0a"
        things = bytearray(6 * 56)
        for fit, tid in eq.items():
            tid, lv = tid if isinstance(tid, tuple) else (tid, 1)
            things[(fit - 1) * 56:(fit - 1) * 56 + 2] = tid.to_bytes(2, "little")
            things[(fit - 1) * 56 + 18] = lv
        body += head + things + bytes(9)
    body = bytes(body[:2]) + bytes(body[3:])   # bỏ byte đệm: [sub 2B][n 1B]
    return b"\xc0\x91" + (7 + len(body)).to_bytes(2, "little") + b"\x00\x00\x0f" + body


class WeaponSkillTest(unittest.TestCase):
    EX = 60001                                  # mã giả cho test

    def setUp(self):
        from realm import weapon_skills as ws
        self.ws = ws
        self._saved = (dict(ws.WEAPON_SKILLS), dict(ws.SKILLS))
        ws.WEAPON_SKILLS[64515] = ((1, self.EX),)
        ws.SKILLS[self.EX] = {"name": "Chấn Điện EX", "cost": 90, "cat": 1, "splash": 4}

    def tearDown(self):
        self.ws.WEAPON_SKILLS.clear()
        self.ws.WEAPON_SKILLS.update(self._saved[0])
        self.ws.SKILLS.clear()
        self.ws.SKILLS.update(self._saved[1])

    def _client_cls(self):
        seen = []

        class Cli:
            def __init__(self):
                self.state = NS(carried_pets=[])
                self.pet_equip_by_fit = {}

            def pet_usable_skills(self, pid):
                return {0xb0a5: [13009, 13013, 13024], 0xb085: [12013, 12014, 12021]}.get(pid, [])

            def _dispatch(self, opcode, pkt):
                # như ts_bot: đọc danh sách pet xong là gọi pet_usable_skills ngay
                seen.append(self.pet_usable_skills(0xb0a5))
        self.ws.patch_client(Cli)
        return Cli, seen

    def test_parse_weapons_from_realm_pet_list(self):
        pkt = _realm_pet_list([(0xb0a5, "", {1: 20120, 3: 64515}), (0xb085, "Tào", {3: 11111})])
        self.assertEqual(self.ws.pet_weapons(pkt), {0xb0a5: (64515, 1), 0xb085: (11111, 1)})
        from realm import realm_login
        self.assertIsNotNone(realm_login.pet_list_to_vn(pkt))   # cùng khuôn bản vá danh sách pet
        self.assertEqual(self.ws.pet_weapons(pkt[:-5]), {})

    def test_weapon_skill_added_before_ts_bot_reads_pet_list(self):
        Cli, seen = self._client_cls()
        c = Cli()
        self.assertEqual(c.pet_usable_skills(0xb0a5), [13009, 13013, 13024])    # chưa biết vũ khí
        c._dispatch(0x0F, _realm_pet_list([(0xb0a5, "", {3: 64515}), (0xb085, "", {3: 11111})]))
        self.assertEqual(seen[-1], [13009, 13013, 13024, self.EX])
        self.assertEqual(c.pet_usable_skills(0xb085), [12013, 12014, 12021])    # vũ khí chưa có trong bảng
        c._dispatch(0x0F, _realm_pet_list([(0xb0a5, "", {3: (64515, 0)})]))
        self.assertEqual(seen[-1], [13009, 13013, 13024])                      # vũ khí cấp 0: chưa có skill

    def test_real_table(self):
        self._saved[0][64515]                                                  # bảng thật có Long Đảm Thương
        self.assertEqual(self.ws.WEAPON_SKILLS.get(64502), ((7, 22032),))
        self.ws.WEAPON_SKILLS.clear()
        self.ws.WEAPON_SKILLS.update(self._saved[0])
        self.ws.SKILLS.clear()
        self.ws.SKILLS.update(self._saved[1])
        self.assertEqual(self.ws.weapon_skills(64515, 1), [13043])              # Cường Chấn Điện (Chấn Điện EX)
        self.assertEqual(self.ws.weapon_skills(64502, 6), [])
        self.assertEqual(self.ws.weapon_skills(64502, 7), [22032])
        self.assertEqual(self.ws.SKILLS[13043]["cost"], 72)
        for steps in self.ws.WEAPON_SKILLS.values():
            for _, sid in steps:
                self.assertIn(sid, self.ws.SKILLS)

    def test_fallback_to_ts_bot_equipment_table(self):
        Cli, _ = self._client_cls()
        c = Cli()
        c.state.carried_pets = [(0xb085, "Tào"), (0xb0a5, "Triệu Vân")]
        c.pet_equip_by_fit = {2: {3: 64515}}
        self.assertEqual(c.pet_usable_skills(0xb0a5)[-1], self.EX)

    def test_skill_info_and_boss_picks_weapon_skill(self):
        cfg = NS(SKILL_INFO={13013: {"name": "Loạn Kích", "cost": 49, "cat": 1}}, SKILL_NORMAL=10000)
        self.ws.fill_skill_info(cfg)
        self.assertEqual(cfg.SKILL_INFO[self.EX]["name"], "Chấn Điện EX")
        info = cfg.SKILL_INFO
        comb = NS(config=cfg, CC_SKILLS=frozenset(), _skill_cost=lambda s: info[s]["cost"],
                  _is_attack=lambda s: info[s]["cat"] in (1, 2))
        skills = [13013, self.EX]
        from unittest import mock
        from realm import skill_power
        with mock.patch.dict(skill_power.POWER, {self.EX: skill_power.POWER[13043]}):   # mã giả = Cường Chấn Điện
            self.assertEqual(cr.best_attack_skill(comb, skills, 200), self.EX)
            self.assertEqual(cr.best_attack_skill(comb, skills, 60), 13013)          # thiếu SP cho EX

    def test_boss_skill_by_single_target_damage(self):
        """Wiki: Long Trời Lỡ Đất x0,78 nhưng đánh toàn đội chỉ ăn 1/3; Liên kích x1,5975 > Loạn kích x1,11."""
        info = {10012: 50, 10001: 9, 13010: 40, 13013: 49}
        comb = NS(config=NS(SKILL_NORMAL=10000), CC_SKILLS=frozenset(), _skill_cost=lambda s: info[s],
                  _is_attack=lambda s: True)
        self.assertEqual(cr.best_attack_skill(comb, [10001, 10012], 200), 10001)
        self.assertEqual(cr.best_attack_skill(comb, [13013, 13010], 200), 13010)
        self.assertEqual(cr.best_attack_skill(comb, [13013, 13010], 45), 13010)
        self.assertEqual(cr.best_attack_skill(comb, [13013, 13010], 30), 10000)

    def test_weapon_only_for_its_owner(self):
        self.ws._CONFIG[0] = NS(PET_NAMES={45221: "Triệu Vân rb2", 12027: "Triệu Vân rb0", 45414: "Lữ Bố rb2",
                                           13038: "Tôn Thượng Hương rb0"}, SKILL_INFO={})
        try:
            self.assertTrue(self.ws.owns_weapon(45221, 64515))            # Long Đảm Thương: Triệu Vân
            self.assertFalse(self.ws.owns_weapon(45414, 64534))           # Lữ Bố cầm Thần Khí Tôn Thượng Hương
            self.assertTrue(self.ws.owns_weapon(99999, 64515))            # không biết tên -> không chặn
        finally:
            self.ws._CONFIG[0] = None

    def test_soul_skills_from_s120_008(self):
        def soul(pet, skills, item=59562):
            r = bytearray(53)
            r[0:2] = (0x10).to_bytes(2, "little")
            r[2:6] = bytes.fromhex("d0921800")
            r[6:8] = b"\x05\x00"
            r[8:10] = item.to_bytes(2, "little")
            r[11:13] = pet.to_bytes(2, "little")
            for k, (sid, lv) in enumerate(skills):
                r[40 + 3 * k:42 + 3 * k] = sid.to_bytes(2, "little")
                r[42 + 3 * k] = lv
            return bytes(r)
        body = b"\x08\x00\x03\x00" + soul(0xb0a5, [(13025, 1), (13023, 1)]) + soul(0, [(11028, 2)]) \
            + soul(0xb085, [(99999 & 0xffff, 1)]) + b"\x00"
        pkt = b"\xc0\x91" + (7 + len(body)).to_bytes(2, "little") + b"\x00\x00\x78" + body
        self.assertEqual(self.ws.pet_souls(pkt), {0xb0a5: [13025, 13023], 0xb085: [99999 & 0xffff]})
        Cli, _ = self._client_cls()
        c = Cli()
        c.state.active_pet_id = 0xb0a5
        self.ws._CONFIG[0] = NS(SKILL_INFO={13025: {"cat": 4}, 13023: {"cat": 2}})
        try:
            c._dispatch(0x78, pkt)
            self.assertEqual(c.state.pet_skills, [13009, 13013, 13024, 13025, 13023])
            self.assertEqual(c.pet_usable_skills(0xb085), [12013, 12014, 12021])   # skill lạ: bỏ qua
        finally:
            self.ws._CONFIG[0] = None

    def test_battle_view_logs_unknown_own_skill_once(self):
        from realm.battle_view import BattleView
        c = NS(battle_tracker=None, state=NS(my_atype=2), _dispatch=lambda o, p: None)
        v = BattleView(c, skill_names={13013: "Loạn Kích"}, npc_names={})
        ev = NS(kind="action", source=(2, 2), position=(0, 2), skill_id=self.EX, payload=())
        with self.assertLogs("bot", "WARNING") as lg:
            v.on_events([ev, ev])
        self.assertEqual(len(lg.output), 1)
        self.assertIn("skill lạ %d" % self.EX, lg.output[0])


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
        cr.RULES["damage_modes"] = []
        self.assertEqual(self.cb.decide_char(self.st([]), []), "ATTACK")         # tắt: bước đánh của ts_bot
        cr.RULES["damage_modes"] = ["npc40", "nhi_kieu"]
        user_rule = {"skill": 999, "condition": "always"}                       # luật riêng của người dùng
        self.assertEqual(self.cb.decide_char(self.st([user_rule, realm_rule]), []), ("RULE", 999))


class DamageAttackTest(unittest.TestCase):
    """40 NPC / Nhị Kiều: bước đánh tự động chọn skill theo dame wiki (auto_attack)."""
    COST = {10000: 0, 10001: 9, 10012: 50, 13010: 40, 13013: 49}

    def setUp(self):
        fresh_rules()
        cr.RULES.update({"damage_modes": ["npc40", "nhi_kieu"], "npc40_ai": "ts_manager",
                         "tsm_modes": ["npc40", "nhi_kieu", "boss"], "danger_first": True, "danger_min_tier": 1})
        cb = self.cb = fake_combat()
        cb.config.SKILL_NORMAL, cb.config.SKILL_DEFEND = 10000, 17001
        cb.config.CHAR_FIRE_MIN_SP = cb.config.PET_FIRE_MIN_SP = 0
        cb.config.SKILL_HEAL_ALL, cb.config.HEAL_SP_COST = 11010, 42
        cb.CC_SKILLS = frozenset()
        cb._skill_cost = lambda s: self.COST.get(s, 10)
        cb._is_attack = lambda s: s in self.COST
        cb._train_target = lambda es, off: 1                # giữa cụm
        for n in ("_try_cc", "_try_break_enemy_protect", "_try_sp_restore"):
            setattr(cb, n, lambda *a: None)
        cb._try_protect = lambda *a: None
        cb._custom_decision = lambda *a: None
        cb._battle_rules = lambda *a: []
        cb._combat_attack = lambda *a: "ORIG"
        cr.install(cb)

    def st(self, skills, hp, tids=None, mode="npc40"):
        units = {(p // 10, p % 10): NS(template_id=t) for p, t in (tids or {}).items()}
        st = fake_state(realm_mode=mode, skills_char=skills, char=NS(sp=300, hp=900, hp_max=1000),
                        enemy_hp=hp, enemy_slots=sorted(p for p, v in hp.items() if v > 0),
                        tracker=NS(units=units), allies={(3, 2): NS(hp=900, hp_max=1000)})
        st.lowest_hp_ally = lambda: None
        return st

    def test_many_enemies_aoe_center(self):
        d = self.cb.decide_char(self.st([10001, 10012], {0: 500, 1: 400, 2: 300, 3: 200}), [(1, 0), (1, 1), (1, 2), (1, 3)])
        self.assertEqual((d.skill, d.target), (10012, 1))        # 4 con: Long Trời (0,78/3 x 4) > Mưa Đá

    def test_danger_alive_focus_single(self):
        d = self.cb.decide_char(self.st([10001, 10012], {0: 500, 1: 400, 2: 300, 3: 200}, {0: 45276}),
                                [(1, 0), (1, 1), (1, 2), (1, 3)])
        self.assertEqual((d.skill, d.target), (10001, 0))        # Đại Kiều Đẩu Chuyển: dồn dame đơn

    def test_single_enemy_strongest(self):
        d = self.cb.decide_char(self.st([13013, 13010], {2: 900}, mode="nhi_kieu"), [(1, 2)])
        self.assertEqual(d.skill, 13010)                         # Liên kích x1,6 > Loạn kích x1,11


def json_copy(d):
    import json
    return json.loads(json.dumps(d))


class PartyTest(unittest.TestCase):
    """realm/party.py: đội trưởng mời các tab, thành viên tự nhận (giả lập server)."""

    def setUp(self):
        from realm import party
        self.party = party
        self.reg = {}
        fake_cm = NS(_register_party_entity=lambda i, e: self.reg.setdefault(i, set()).add(e),
                     _register_party_client=lambda i, e, c: None)
        self.cfg = NS(PARTY_LEADERS_BY_IDX={})
        self._old = party._cm, party._cfg
        party._cm, party._cfg = (lambda: fake_cm), (lambda: self.cfg)

    def tearDown(self):
        self.party._cm, self.party._cfg = self._old

    def _client(self, name, ent, mp=12001):
        c = NS(char_name=name, self_entity=ent, running=True, current_map=mp, party_members=[],
               party_leader=None, auto_accept_party=False, party_invite_ready=False, invites=[])
        return c

    def test_form_invites_same_map_only(self):
        lead = self._client("A", b"A" * 8)
        b, far = self._client("B", b"B" * 8), self._client("C", b"C" * 8, mp=99)

        def invite(ent):                       # server: người được mời đã sẵn sàng thì vào đội ngay
            m = {b"B" * 8: b, b"C" * 8: far}[bytes(ent)]
            lead.invites.append(m.char_name)
            if m.party_invite_ready:
                lead.party_members.append(bytes(ent))
                m.party_leader = lead.self_entity
        lead.invite_entity = invite
        joined, left = self.party.form(lead, [b, far], timeout=1.5, gap=0.1)
        self.assertEqual((joined, left), (["B"], ["C"]))
        self.assertEqual(lead.invites, ["B"])              # khác map: không mời
        self.assertEqual(self.cfg.PARTY_LEADERS_BY_IDX[self.party.PIDX], ["A"])
        self.assertTrue(b.party_invite_ready and b.party_idx == self.party.PIDX)

    def test_summary(self):
        a = self._client("A", b"A" * 8)
        a.party_peers = lambda: []
        self.assertIsNone(self.party.summary(a))
        a.party_leader, a.party_members = b"A" * 8, [b"A" * 8, b"B" * 8]
        sm = self.party.summary(a)
        self.assertEqual((sm["size"], sm["is_leader"], sm["names"][0]), (2, True, "A"))

    def test_member_follow_until_leader_done(self):
        from realm import features
        lead = self._client("A", b"A" * 8)
        m = self._client("B", b"B" * 8)
        m.party_leader = lead.self_entity
        m.state = NS(support_combat=False, quest_mode=False, realm_mode=None)
        done = threading.Event()
        r = features.Runner(m, NS(), {}, threading.Event(), party={"role": "member", "leader": lead, "done": done})
        r._loadout_on = lambda mode: False
        r._loadout_off = lambda mode, sw: None
        seen = {}

        def finish():
            time.sleep(0.3)
            seen["mode"], seen["support"] = m.state.realm_mode, m.state.support_combat
            done.set()
        threading.Thread(target=finish).start()
        self.assertTrue(r._follow("npc40", quest=True))
        self.assertEqual(seen, {"mode": "npc40", "support": True})
        self.assertIsNone(m.state.realm_mode)
        self.assertFalse(m.state.support_combat)


class PetOrderTest(unittest.TestCase):
    """realm/pet_order.py: đưa võ tướng chọn lên đầu danh sách bằng C:033-014 (đổi chỗ 2 ô)."""

    def test_plan(self):
        from realm import pet_order as po
        slots = [(1, 0x3715), (2, 0x2ee2), (3, 0x2eef), (4, 0x32d0), (5, 0xb166)]
        self.assertEqual(po.plan(slots, [0x2eef]), [(1, 3)])                 # như capture 27/11 18:21
        self.assertEqual(po.plan(slots, [0x3715, 0x2ee2]), [])               # đã đúng thứ tự
        self.assertEqual(po.plan(slots, [0x32d0, 0x3715, 0x9999]), [(1, 4), (2, 4)])

    def test_arrange_sends_swaps(self):
        from realm import pet_order as po
        sent = []
        c = NS(_label="a", state=NS(in_battle=False),
               _realm_pet_slots=[(1, 0x3715), (2, 0x2ee2), (3, 0x2eef)])

        def send(op, payload):
            sent.append((op, payload.hex()))
            c._realm_swap_result = (0, payload[2], payload[3], 0)   # server: mã 0 = được
            c._realm_swap_event.set()
        c.send = send
        self.assertTrue(po.arrange(c, [0x2eef, 0x3715]))
        self.assertEqual(sent, [(0x21, "0e000103"), (0x21, "0e000203")])
        self.assertEqual(c._realm_pet_slots, [(1, 0x2eef), (2, 0x3715), (3, 0x2ee2)])
        c.state.in_battle = True
        self.assertFalse(po.arrange(c, [0x2ee2]))                            # trong trận: không đổi


class PartyPetsTest(unittest.TestCase):
    """realm/party_pets.py: chỉ ra lệnh cho võ tướng phụ có master_id là mình."""

    def _client(self):
        me, other = b"M" * 8, b"O" * 8
        U = lambda pid, owner, kind=4, hp=100, sp=500: NS(role_id=pid.to_bytes(2, "little") + b"\0" * 6,
                                                         master_id=owner, role_kind=kind, hp=hp, alive=hp > 0, sp=sp)
        units = {(3, 2): U(0, me, kind=1), (2, 2): U(0xb170, me), (2, 0): U(0x2eef, me), (2, 4): U(0x2ee2, me, hp=0),
                 (3, 0): U(0x1111, other), (3, 1): U(0, other, kind=1), (0, 2): U(0x9999, b"\0" * 8, kind=3)}
        st = NS(my_atype=2, char_row=3, ally_rows=(2, 3), enemy_rows=(0, 1), enemy_hp={2: 900, 3: 100},
                support_combat=True, status_by_kind={})
        sent = []
        c = NS(self_entity=me, state=st, battle_tracker=NS(active=True, units=units, generation=1, turn=1),
               auto_combat=True, _label="a", pet_usable_skills=lambda pid: [13010, 13013],
               _is_current_combat_turn=lambda k: True, _combat_turn_key=lambda: (1, 1),
               _send_combat=lambda d, expected_key=None: sent.append(d))
        return c, sent

    def test_only_own_alive_extras(self):
        from realm import party_pets as pp
        c, _ = self._client()
        self.assertEqual([(r, cl) for r, cl, _u in pp.own_extra_units(c)], [(2, 0)])

    def test_send_extras(self):
        from realm import party_pets as pp
        c, sent = self._client()
        cost = {13010: 40, 13013: 49}
        comb = NS(Decision=_Dec, _skill_cost=lambda s: cost.get(s, 0), _is_attack=lambda s: True,
                  CC_SKILLS=frozenset(), config=NS(SKILL_NORMAL=10000), _hang_cua=lambda st, u: u,
                  _lowest_hp_enemy=lambda st, off: 3)
        import sys as _s
        with mock_module("train_bot", NS(combat=comb)), mock_module("train_bot.combat", comb):
            pp._send_extras(c, (1, 1))
            pp._send_extras(c, (1, 1))                       # cùng lượt: không gửi lại
        self.assertEqual([(d.unit, d.atype, d.b, d.target, d.skill) for d in sent], [(2, 0, 0, 3, 13013)])   # 2 con: Loạn kích (3 mục tiêu) tổng dame cao hơn


class PartyPetRoleTest(unittest.TestCase):
    """Vai trò võ tướng phụ: giải -> khống chế -> đánh (theo skill nó có)."""

    def setUp(self):
        from realm import party_pets
        self.pp = party_pets
        cr._claims.clear()
        self.comb = fake_combat()
        self.comb._skill_cost = lambda s: 20
        self.comb._is_attack = lambda s: s in (13010, 13013)
        self.comb.CC_SKILLS = frozenset((14021,))
        self.comb.config.SKILL_NORMAL = 10000

    def client(self, skills, sbk=None, hp=None):
        st = fake_state(status_by_kind=sbk or {}, enemy_hp=hp or {2: 900, 3: 100}, label="a", party_idx=None)
        return NS(state=st, pet_usable_skills=lambda pid: skills)

    def unit(self):
        return NS(role_id=b"\x01\x02" + b"\0" * 6, sp=500)

    def test_cleanse_first(self):
        chaos = 14021
        c = self.client([14022, 14021, 13010], sbk={(3, 1): {"c": chaos}})
        d = self.pp.decide(c, self.comb, 2, 0, self.unit())
        self.assertEqual((d.skill, d.b, d.target), (14022, 3, 1))

    def test_cc_then_damage(self):
        c = self.client([14021, 13010])
        d = self.pp.decide(c, self.comb, 2, 0, self.unit())
        self.assertEqual((d.skill, d.b, d.target), (14021, 0, 2))            # khống chế con nhiều máu
        d2 = self.pp.decide(c, self.comb, 2, 4, self.unit())                 # con kia đã giữ chỗ
        self.assertEqual(d2.skill, 14021)
        self.assertEqual((d2.b, d2.target), (0, 3))
        c1 = self.client([14021, 13010], hp={2: 900})
        self.assertEqual(self.pp.decide(c1, self.comb, 2, 0, self.unit()).skill, 13010)   # còn 1 con: đánh

    def test_skill_pref_overrides_roles(self):
        c = self.client([14021, 13010, 13013])
        self.assertEqual(self.pp.decide(c, self.comb, 2, 0, self.unit(), skill_pref=13013).skill, 13013)


def mock_module(name, obj):
    from unittest import mock
    return mock.patch.dict(sys.modules, {name: obj})


class PetSkillPrefTest(unittest.TestCase):
    def test_default_pet_skill_used_when_mode_has_none(self):
        from unittest import mock
        seen = {}
        c = NS(state=NS(active_pet_id=0xb170))
        r = features.Runner(c, NS(), {"loadouts": {"npc40": {"pet_skill": 0}}, "pet_skills": {0xb170: 13010}},
                            threading.Event())
        with mock.patch("realm.loadout.apply", lambda cl, opts, rules_mod=None, mode=None: seen.update(opts)):
            r._loadout_on("npc40")
        self.assertEqual(seen.get("pet_skill"), 13010)
        seen.clear()
        r.s["loadouts"]["npc40"]["pet_skill"] = 13013                  # chế độ đã chọn: giữ
        with mock.patch("realm.loadout.apply", lambda cl, opts, rules_mod=None, mode=None: seen.update(opts)):
            r._loadout_on("npc40")
        self.assertEqual(seen.get("pet_skill"), 13013)


class Npc40Floor38FixTest(unittest.TestCase):
    """Log 27/11 acc 100653 kẹt tầng 38 (team + solo)."""

    def setUp(self):
        TsmDecideTest.setUp(self)

    st = TsmDecideTest.st

    def test_dau_chuyen_not_dispelled_again_next_turn(self):
        cb = self.cb
        opts = [(1, 0), (1, 1), (1, 2)]
        mk = lambda turn: self.st(skills_char=[11012], enemy_slots=[2], status_by_kind={(0, 2): {"b": 13021}},
                                  allies={(3, 2): NS(hp=900, hp_max=1000)}, char=NS(sp=200, hp=900, hp_max=1000),
                                  enemy_hp={2: 50}, tracker=NS(generation=7, turn=turn, units={}))
        self.assertEqual(cb.decide_char(mk(4), opts).skill, 11012)      # lượt 4: giải
        self.assertEqual(cb.decide_char(mk(5), opts), "SHIELD")          # lượt 5 boss buff lại: thôi giải
        self.assertEqual(cb.decide_char(mk(6), opts), "SHIELD")          # (khiên/đánh của ts_bot)
        self.assertEqual(cb.decide_char(mk(7), opts).skill, 11012)      # quá 2 lượt: thử giải lại

    def test_heal_before_dau_chuyen_when_party_low(self):
        st = self.st(skills_char=[11012, 11010], enemy_slots=[2], status_by_kind={(0, 2): {"b": 13021}},
                     allies={(3, 2): NS(hp=2460, hp_max=8601), (2, 2): NS(hp=1244, hp_max=5984)})
        self.assertEqual(self.cb.decide_char(st, [(1, 2)]).skill, 11010)

    def test_party_ratio_ignores_dead(self):
        st = fake_state(allies={(3, 2): NS(hp=900, hp_max=1000), (2, 0): NS(hp=0, hp_max=5000)})
        self.assertGreater(cr._party_hp_ratio(st), 0.5)

    def test_dau_chuyen_target_avoided(self):
        self.assertIn((1, 0), sl.avoid_damage_targets({(1, 0): {"b": 13021}}, (0, 1)))


class PartyHealTest(unittest.TestCase):
    def _client(self, units, gen=3):
        healed = []
        me = b"ME" * 4
        c = NS(_label="acc1", self_entity=me, bag_slots={1: [0x6a14, 50]},
               _pet_skill_rows=[(1, 0xb0a5, 1, 0, []), (2, 0xb170, 1, 0, []), (3, 0xb169, 1, 0, [])],
               state=NS(in_battle=False, active_pet_id=0xb170, ally_rows=(2, 3)),
               battle_tracker=NS(generation=gen, units=units))
        c._heal_unit = lambda target, stat, label, key, kind, **kw: healed.append((target, kind, stat.hp))
        c.heal_npc40_between_battles = lambda: healed.append("main")
        return c, healed

    @staticmethod
    def _u(pid, hp, hp_max, master=b"ME" * 4, kind=4):
        return NS(role_kind=kind, master_id=master, role_id=pid.to_bytes(2, "little") + b"\0" * 6,
                  hp=hp, hp_max=hp_max, sp=100, sp_max=100)

    def test_heals_own_generals_once_per_battle(self):
        from realm import party_heal
        units = {(2, 0): self._u(0xb0a5, 0, 5000),                       # chết -> 1 HP
                 (2, 2): self._u(0xb170, 0, 5984),                       # pet đi theo: ts_bot lo
                 (2, 4): self._u(0xb169, 5000, 5000),                    # đầy rồi
                 (2, 1): self._u(0xb0a5, 0, 5000, master=b"XX" * 4)}     # của người khác
        c, healed = self._client(units)
        party_heal.heal_one(c)
        self.assertEqual(healed, ["main", (1, "hp", 1), (1, "sp", 1)])
        party_heal.heal_one(c)                                            # cùng trận: không hồi lại
        self.assertEqual(healed, ["main", (1, "hp", 1), (1, "sp", 1), "main"])

    def test_leader_heals_members(self):
        from realm import party_heal
        lead, h1 = self._client({})
        mem, h2 = self._client({(2, 0): self._u(0xb0a5, 10, 5000)})
        mem.running = True
        party_heal.heal_party(lead, [mem])
        self.assertEqual(h1, ["main"])
        self.assertEqual(h2, ["main", (1, "hp", 10), (1, "sp", 10)])


class Npc40WinByFloorTest(unittest.TestCase):
    def test_new_floor_is_win_even_if_marked_defeated(self):
        from realm import npc40_loop
        c = FakeNpcClient(["lose", "lose", "lose", "win"])
        floors = iter([36, 37, 37, 37, 37, 37])
        why = npc40_loop.run_loop(c, (910, 290), threading.Event(), lambda: None,
                                  max_consec_losses=3, sleep_fn=lambda s: None, npc40=FakeNpc40Mod,
                                  floor_fn=lambda: next(floors))
        self.assertNotIn("liên tiếp", why)       # trận 1 lên tầng 37 = thắng -> chỉ thua 2 liền
