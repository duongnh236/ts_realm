"""Boss Thế Giới: đánh hết 5 lượt free, rồi dùng vé trong hành trang tới khi đủ dame hoặc hết vé.

Theo TS Manager bản PC (world_boss damage goal):
  * Vé, theo thứ tự: 46629 "Vé Khiêu Chiến Boss" (vé được tặng) rồi 46614 "Khiêu Chiến Boss"
    (vé mua ở cửa hàng). Chỉ dùng vé ĐANG CÓ trong túi, không tự mua thêm.
  * Dame một trận = số lớn nhất của gói ``S 073-004`` trong trận (u32 little-endian ngay sau
    byte cờ; server gửi số cộng dồn của trận). Dame trong ngày = cộng mọi trận Boss TG bot đánh
    trong ngày (giờ server), lưu ở ``runtime/world_boss_damage.json``.
  * Lượt free luôn đánh. Trước MỖI lần dùng vé: dame hôm nay >= ``damage_goal`` thì dừng.
  * Có trận không đọc được dame thì không dùng vé nữa (không tiêu vé mù).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time

log = logging.getLogger("bot")

TICKET_IDS = (46629, 46614)          # Vé Khiêu Chiến Boss, Khiêu Chiến Boss (cửa hàng)
OP_WORLD_BOSS = 0x49                 # 073
SUB_FIGHT_DAMAGE = 0x04              # 073-004
DEFAULT_GOAL = 5_000_000

# Mua vé ở shop (capture TS Realm 26/11): C:066-001 ``0100 01 01 09 04 16b6 0900 01 0000``
#   = shop 1, tab 1, trang 9, ô 4, mã 46614, giá 9, số lượng 1 (cùng khuôn `_shop42_payload` của ts_bot).
#   Server trả S:023-008 (ô túi chứa vé tăng 1) + S:066-003 ``0300 16b6 01``.
SHOP_TICKET = {"shop": 1, "tab": 1, "page": 9, "slot": 4, "item": 46614, "price": 9}


def shop_ticket_payload(t=None) -> bytes:
    t = dict(SHOP_TICKET, **(t or {}))
    return (b"\x01\x00" + bytes([t["shop"] & 0xFF, t["tab"] & 0xFF, t["page"] & 0xFF, t["slot"] & 0xFF])
            + int(t["item"]).to_bytes(2, "little") + int(t["price"]).to_bytes(2, "little")
            + b"\x01\x00\x00")


def ticket_count(bag_slots, tid):
    return sum(int(c) for t, c in (bag_slots or {}).values() if int(t) == int(tid))


def buy_ticket(client, wait=4.0, shop=None):
    """Mua 1 vé shop, chờ túi tăng. Trả True nếu thấy vé về túi."""
    tid = int(dict(SHOP_TICKET, **(shop or {}))["item"])
    before = ticket_count(client.bag_slots, tid)
    client.send(0x42, shop_ticket_payload(shop))
    t0 = time.time()
    while time.time() - t0 < wait:
        if not client.running:
            return False
        if ticket_count(client.bag_slots, tid) > before:
            return True
        time.sleep(0.2)
    return False


def today_damage(client, damage_log, account, day):
    """Dame hôm nay = số lớn hơn giữa sổ của bot và tổng server gửi (S:073-003 mục 3).

    Mục 3 của S:073-003 là tổng dame boss trong ngày của nhân vật, kể cả trận đánh tay: 1.274.555
    lúc 11:31 -> 2.446.731 sau 2 trận đánh tay -> 2.594.071 sau trận bot đánh 147.340 (log 26/11)."""
    local = damage_log.today(account, day)
    server = getattr(client, "realm_wb_total", None)
    if getattr(client, "realm_wb_total_day", day) != day:
        server = None                      # số của hôm trước
    return max(int(local or 0), int(server or 0))


def fight_damage_from_packet(opcode, pkt):
    """Trả dame (int) nếu gói là S 073-004, ngược lại None. ``pkt`` = cả gói như ts_bot nhận."""
    if opcode != OP_WORLD_BOSS or len(pkt) < 13 or pkt[7] != SUB_FIGHT_DAMAGE:
        return None
    return int.from_bytes(pkt[9:13], "little")


class DamageLog:
    """Dame Boss TG cộng dồn theo ngày server, mỗi tài khoản một dòng."""

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def today(self, account, day):
        rec = self._load().get(account) or {}
        return int(rec.get("damage", 0)) if rec.get("day") == day else 0

    def add(self, account, day, dmg):
        with self._lock:
            d = self._load()
            rec = d.get(account) or {}
            if rec.get("day") != day:
                rec = {"day": day, "damage": 0, "fights": 0}
            rec["damage"] = int(rec.get("damage", 0)) + int(dmg)
            rec["fights"] = int(rec.get("fights", 0)) + 1
            d[account] = rec
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
            return rec["damage"]


class DamageTap:
    """Gắn vào ``client._dispatch`` để đọc dame trận Boss TG (chỉ đọc, không đổi gói)."""

    def __init__(self, client):
        self.c = client
        self.fight_max = None
        self.last = time.time()
        orig = client._dispatch

        def _dispatch(opcode, pkt):
            self.last = time.time()
            try:
                dmg = fight_damage_from_packet(opcode, pkt)
                if dmg is not None and (self.fight_max is None or dmg > self.fight_max):
                    self.fight_max = dmg
            except Exception:
                pass
            return orig(opcode, pkt)

        client._dispatch = _dispatch
        self._orig = orig

    def reset(self):
        self.fight_max = None
        self.last = time.time()

    def remove(self):
        self.c._dispatch = self._orig


def not_ready(client, ratio=0.95):
    """Hồi FULL HP/SP (thuốc) rồi kiểm tra. Trả lý do (chuỗi) nếu nhân vật / pet chưa đủ ``ratio``
    HP và SP (thường là hết thuốc), None nếu sẵn sàng vào trận."""
    try:
        if not client.in_combat():
            client.heal_full()
    except Exception as exc:
        log.warning("[%s] Boss TG: hồi máu/SP lỗi: %s", getattr(client, "_label", "?"), exc)
    st = client.state
    low = []
    for name, u in (("nhân vật", getattr(st, "char", None)), ("pet", getattr(st, "pet", None))):
        if u is None:
            continue
        for kind, cur, mx in (("HP", u.hp, u.hp_max), ("SP", u.sp, u.sp_max)):
            if mx and mx > 0 and cur < mx * float(ratio):
                low.append("%s %s %d/%d" % (kind, name, cur, mx))
    return ", ".join(low) or None


class StallWatch:
    """Trận Boss TG mà ``stall_s`` giây không nhận gói nào từ server -> coi là treo, ngắt kết nối
    (log 26/11: gửi lượt 1 xong im 11 phút tới khi server cắt, mất vé cuối)."""

    def __init__(self, client, tap, stall_s=90):
        self.c, self.tap, self.stall_s = client, tap, float(stall_s)
        self.stalled = False
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, name="wb-stall", daemon=True)
        self._t.start()

    def _loop(self):
        while not self._stop.wait(2.0):
            if not self.c.running or not getattr(self.c.state, "in_battle", False):
                continue
            idle = time.time() - self.tap.last
            if idle >= self.stall_s:
                self.stalled = True
                log.warning("[%s] Boss TG: trận %ds không có gói nào từ server -> coi là treo, ngắt kết nối",
                            self.c._label, int(idle))
                try:
                    self.c.close()
                except Exception:
                    pass
                return

    def remove(self):
        self._stop.set()


OP_COMBAT = 0x32


def item_payload(payload, pending):
    """Lệnh đánh ts_bot dựng ``01 00 hàng cột b đích skill(2) đuôi(2)``. Nếu nguồn (hàng, cột) đang chờ
    dùng thuốc và skill == mã thuốc -> đổi thành lệnh DÙNG ĐỒ TRONG TRẬN ``02 00 ... mã đồ(2) đuôi``
    (capture 27/11 11:31 + 11:34: ``02 00 03 02 02 02 126a xx yy`` = nhân vật ô 3/2 cho pet ô 2/2
    uống Thuốc Hoàng Cân 0x6a12, server trả ``S:050-001 ... 394a ... 1a a500`` = +165 SP).
    Capture 11:44: nhân vật tự uống ``02 00 03 02 03 02 126a ..`` -> server +165 SP ô 3/2 (đã kiểm)."""
    if len(payload) < 8 or payload[:2] != b"\x01\x00":
        return payload
    src = (payload[2], payload[3])
    tid = pending.get(src)
    if tid is None or int.from_bytes(payload[6:8], "little") != int(tid):
        return payload
    pending.pop(src, None)
    return b"\x02\x00" + payload[2:]


class ItemInBattle:
    """Cho combat_rules dùng thuốc SP trong trận Boss TG: tìm thuốc SP trong túi + sửa gói gửi đi."""

    def __init__(self, client):
        self.c = client
        st = client.state
        self.pending = {}
        st.realm_item_pending = self.pending
        finder = getattr(client, "_slot_for_known", None)
        st.realm_sp_item = (lambda: finder("sp", set())) if finder else None
        self._orig = client.send

        def send(opcode, payload, *a, **kw):
            if opcode == OP_COMBAT and self.pending:
                try:
                    payload = item_payload(payload, self.pending)
                except Exception:
                    pass
            return self._orig(opcode, payload, *a, **kw)

        client.send = send

    def remove(self):
        self.c.send = self._orig
        st = self.c.state
        st.realm_item_pending = None
        st.realm_sp_item = None


def find_ticket(bag_slots, ticket_ids=TICKET_IDS):
    """(slot, template_id, số lượng) của vé dùng trước tiên, hoặc None."""
    for tid in ticket_ids:
        for slot, (t, cnt) in sorted((bag_slots or {}).items()):
            if int(t) == int(tid) and int(cnt) > 0:
                return slot, int(t), int(cnt)
    return None


def run(client, account, day, damage_log, opts, cho_phep=None, max_loops=300):
    """Trả (đã_đánh_trận_nào, lý_do_dừng)."""
    goal = int(opts.get("damage_goal", DEFAULT_GOAL) or DEFAULT_GOAL)
    use_tickets = bool(opts.get("use_tickets", True))
    auto_buy = bool(opts.get("auto_buy", False))
    max_buy = int(opts.get("max_buy", 60) or 0)
    bought = 0
    ticket_ids = tuple(opts.get("ticket_ids") or TICKET_IDS)
    if not client._world_boss_event_open():
        log.info("[%s] Boss TG: dừng — ngoài giờ", client._label)
        return False, "ngoài giờ"
    unknown = client.query_world_boss_attempts() is None
    if unknown:
        # Đăng nhập lại nhanh (nhân vật còn trong game) thì server TS Realm có khi không gửi lại
        # bảng nhiệm vụ S:024 -> không biết đã đánh mấy lượt. Cứ thử vào trận: hết lượt thì server
        # không cho vào và bot dừng. Không dùng vé khi chưa rõ số lượt.
        log.info("[%s] Boss TG: chưa đọc được số lượt từ server -> thử vào trận", client._label)
    unknown_fights = 0
    tap = DamageTap(client)
    ready_ratio = float(opts.get("ready_ratio", 0.95) or 0)
    watch = StallWatch(client, tap, opts.get("stall_seconds", 90))
    items = ItemInBattle(client) if hasattr(client, "send") else None
    did_any = False
    blind = False
    why = "đủ vòng lặp tối đa"
    try:
        for _ in range(max_loops):
            if not client.running:
                why = "mất kết nối"
                break
            reason = cho_phep() if cho_phep else None
            if reason:
                why = reason
                break
            cur = client.world_boss_count
            mx = client.world_boss_max or 5
            if cur is None:
                if not unknown:
                    why = "mất số lượt giữa chừng"
                    break
                if unknown_fights >= mx:
                    why = "đã thử %d trận, vẫn chưa đọc được số lượt" % unknown_fights
                    break
                low = not_ready(client, ready_ratio) if ready_ratio else None
                if low:
                    why = "chưa hồi đầy (%s) — có thể hết thuốc" % low
                    break
                log.info("[%s] Boss TG: trận thứ %d (chưa rõ số lượt)", client._label, unknown_fights + 1)
                tap.reset()
                ok = client.do_world_boss(heal_after=True)
                if watch.stalled:
                    why = "trận bị treo, đã ngắt kết nối"
                    break
                if not ok:
                    why = "không vào được trận (có thể đã hết lượt hôm nay)"
                    break
                did_any = True
                unknown_fights += 1
                if tap.fight_max is not None:
                    total = damage_log.add(account, day, tap.fight_max)
                    log.info("[%s] Boss TG: trận này %s dame, hôm nay %s/%s", client._label,
                             format(tap.fight_max, ","), format(total, ","), format(goal, ","))
                continue
            if cur >= mx:
                # hết lượt free -> xét vé
                total = today_damage(client, damage_log, account, day)
                if not use_tickets:
                    why = "xong %d lượt free (tắt dùng vé)" % mx
                    break
                if total >= goal:
                    why = "đủ dame hôm nay %s/%s" % (format(total, ","), format(goal, ","))
                    break
                if blind:
                    why = "có trận không đọc được dame -> không dùng vé mù"
                    break
                t = find_ticket(client.bag_slots, ticket_ids)
                if t is None and auto_buy:
                    if bought >= max_buy:
                        why = "đã mua %d vé trong lần chạy này (giới hạn)" % bought
                        break
                    if not buy_ticket(client, shop=opts.get("shop_ticket")):
                        why = "mua vé không được (có thể hết tiền hoặc shop đổi giá)"
                        break
                    bought += 1
                    log.info("[%s] Boss TG: mua 1 vé shop (lần %d, dame hôm nay %s/%s)", client._label,
                             bought, format(total, ","), format(goal, ","))
                    t = find_ticket(client.bag_slots, ticket_ids)
                if t is None:
                    bag = sorted({int(tid) for tid, cnt in (client.bag_slots or {}).values() if int(cnt) > 0})
                    log.info("[%s] Boss TG: không thấy vé %s trong túi (%d loại đồ: %s)", client._label,
                             list(ticket_ids), len(bag), bag[:60])
                    why = "hết vé (dame hôm nay %s/%s)" % (format(total, ","), format(goal, ","))
                    break
                low = not_ready(client, ready_ratio) if ready_ratio else None
                if low:
                    why = "chưa hồi đầy (%s) — có thể hết thuốc, không dùng vé" % low
                    break
                slot, tid, cnt = t
                ok, left = client.use_slot_wait(slot, target=0)
                if not ok:
                    why = "dùng vé %d ở ô %d không được" % (tid, slot)
                    break
                client._set_world_boss_progress(max(0, mx - 1), mx, "vé %d" % tid)
                log.info("[%s] Boss TG: dùng vé %d (ô %d, còn %d) -> đánh thêm 1 trận",
                         client._label, tid, slot, left)
                time.sleep(1.0)
                continue
            low = not_ready(client, ready_ratio) if ready_ratio else None
            if low:
                why = "chưa hồi đầy (%s) — có thể hết thuốc" % low
                break
            log.info("[%s] Boss TG: lượt %d/%d", client._label, cur, mx)
            tap.reset()
            ok = client.do_world_boss(heal_after=True)
            if watch.stalled:
                why = "trận bị treo, đã ngắt kết nối"
                break
            if not ok:
                why = "không vào được trận"
                break
            did_any = True
            if client.world_boss_count is None or client.world_boss_count <= cur:
                client._set_world_boss_progress(min(mx, cur + 1), mx, "sau trận")
            if tap.fight_max is None:
                blind = True
                log.warning("[%s] Boss TG: không đọc được dame trận này", client._label)
            else:
                damage_log.add(account, day, tap.fight_max)
                total = today_damage(client, damage_log, account, day)
                log.info("[%s] Boss TG: trận này %s dame, hôm nay %s/%s", client._label,
                         format(tap.fight_max, ","), format(total, ","), format(goal, ","))
    finally:
        watch.remove()
        if items is not None:
            items.remove()
        tap.remove()
    log.info("[%s] Boss TG: dừng — %s", client._label, why)
    return did_any, why
