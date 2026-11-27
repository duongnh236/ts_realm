"""Hợp vật phẩm cho TS Realm: chọn món trong túi + số lượng mỗi ô, hợp lặp lại.

Gói C:023-014 bắt từ máy thật (PCAPdroid 27/11 10:25, hợp Lụa Tứ Xuyên 40 40 40):
    ``0e00 | 4200 28000000 | 4200 28000000 | 4200 28000000 | 01``
= 3 ô nguyên liệu, mỗi ô ``ô túi u16 + số lượng u32`` (ô túi thật, KHÔNG cộng 0x100 như ts_bot),
cuối là ``01``. Cùng một ô túi được dùng cho cả 3 ô nếu đủ số lượng.

Số lượng mỗi ô = số lần "hợp thành hàng loạt" (server báo "Hợp thành hàng loạt 40/40 lần",
tốn Đồng, thất bại thì hoàn nguyên liệu) -> số bị trừ không đúng 3×40 (capture: 105 rồi 109),
nên bot đọc lại túi sau mỗi lần hợp. Đồ hợp ra (26–31 món trang bị) rơi vào ô trống.

Phân giải ngay sau mỗi lần hợp (capture cùng file, 10:26:39): client gửi C:089-004 (xem trước)
rồi C:089-003 cùng thân ``0x00 | n u8 | n × (ô u16 + số lượng u32)``, tối đa 8 ô một lượt;
server trả S:023-009 trừ từng ô rồi S:089-003 danh sách vật liệu. Bot chỉ phân giải đúng các ô
MỚI xuất hiện sau lần hợp (đồ vừa hợp ra, có ``fc`` > 0 = phân giải được), không đụng đồ cũ.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("bot")

MAX_SLOTS = 3
RESTRICT_NOT_COMBINE_MATERIAL = 4      # bit "không dùng làm nguyên liệu hợp" trong items_gamedata
WAIT_RESULT = 6.0                      # chờ server trừ nguyên liệu sau mỗi lần hợp
GAP = 1.2                              # nghỉ giữa hai lần hợp
DECOMPOSE_BATCH = 8                    # client gốc phân giải tối đa 8 ô một lượt
SETTLE = 0.8                           # chờ server bỏ hết đồ hợp ra vào túi


def payload(entries) -> bytes:
    """``entries`` = [(ô túi, số lượng)] tối đa 3; ô thiếu ghi 0."""
    entries = list(entries)[:MAX_SLOTS]
    if not entries:
        raise ValueError("cần ít nhất 1 ô nguyên liệu")
    body = b"\x0e\x00"
    for i in range(MAX_SLOTS):
        slot, qty = entries[i] if i < len(entries) else (0, 0)
        body += int(slot).to_bytes(2, "little") + int(qty).to_bytes(4, "little")
    return body + b"\x01"


def decompose_body(sub, entries) -> bytes:
    """C:089-00x phân giải: ``sub 00 | n | n × (ô u16 + số lượng u32)`` (sub 4 = xem trước, 3 = làm)."""
    entries = list(entries)
    body = bytes([sub, 0, len(entries)])
    for slot, qty in entries:
        body += int(slot).to_bytes(2, "little") + int(qty).to_bytes(4, "little")
    return body


def keep_reason(slot, tid, items, bonus, keep_bonus=0, keep_level=0):
    """Lý do GIỮ món này (không phân giải), None = phân giải được."""
    v = int((bonus or {}).get(slot, 0) or 0)
    if keep_bonus and v >= keep_bonus:
        return "giá trị %d" % v
    lv = int((items.get(int(tid)) or {}).get("lv", 0) or 0)
    if keep_level and lv >= keep_level:
        return "cấp %d" % lv
    return None


def new_gear(before, after, material, items, bonus=None, keep_bonus=0, keep_level=0, kept=None):
    """Ô mới có đồ (hoặc đổi món) sau lần hợp, trừ nguyên liệu; chỉ món phân giải được (fc > 0).
    Món đạt ngưỡng giữ (giá trị / cấp) thì bỏ ra ``kept`` thay vì phân giải."""
    out = []
    for slot, rec in sorted(after.items()):
        tid, cnt = int(rec[0]), int(rec[1])
        if cnt <= 0 or tid == int(material):
            continue
        old = before.get(slot)
        if old is not None and int(old[0]) == tid:
            continue
        if int((items.get(tid) or {}).get("fc", 0) or 0) <= 0:
            continue
        why = keep_reason(slot, tid, items, bonus, keep_bonus, keep_level)
        if why:
            if kept is not None:
                kept.append((slot, tid, why))
            continue
        out.append((slot, cnt))
    return out


def decompose(client, entries, stop_event, sleep_fn=time.sleep, now=time.time, wait=WAIT_RESULT):
    """Phân giải ``entries`` theo lượt 8 ô như client gốc. Trả số ô đã phân giải xong."""
    done = 0
    entries = list(entries)
    for i in range(0, len(entries), DECOMPOSE_BATCH):
        if stop_event.is_set():
            break
        batch = entries[i:i + DECOMPOSE_BATCH]
        client.send(0x59, decompose_body(4, batch))
        sleep_fn(0.5)
        client.send(0x59, decompose_body(3, batch))
        slots = {s for s, _ in batch}
        deadline = now() + wait

        def left():
            bag = getattr(client, "bag_slots", None) or {}
            return [s for s in slots if s in bag and int(bag[s][1]) > 0]
        while left() and now() < deadline and not stop_event.is_set():
            sleep_fn(0.2)
        rest = left()
        done += len(slots) - len(rest)
        if rest:
            break
        sleep_fn(0.4)
    return done


def _items():
    try:
        from train_bot.client import _load_gamedata_items
        return _load_gamedata_items() or {}
    except Exception:
        return {}


def total(client, tid) -> int:
    return sum(int(c) for t, c in list((getattr(client, "bag_slots", None) or {}).values()) if int(t) == int(tid))


def plan(client, tid, qty, n_slots=MAX_SLOTS):
    """Xếp ``n_slots`` ô, mỗi ô ``qty`` cái lấy từ các ô túi đang chứa ``tid``. Không đủ -> None."""
    rem = {int(s): int(c) for s, (t, c) in list((getattr(client, "bag_slots", None) or {}).items())
           if int(t) == int(tid) and int(c) > 0}
    out = []
    for slot in sorted(rem):
        while rem[slot] >= qty and len(out) < n_slots:
            out.append((slot, qty))
            rem[slot] -= qty
    return out if len(out) == n_slots else None


def bag_list(client):
    """Món trong túi dùng được để hợp: [{tid, name, qty, stacks}], gộp theo mã."""
    items = _items()
    agg = {}
    for slot, (tid, cnt) in list((getattr(client, "bag_slots", None) or {}).items()):
        tid, cnt = int(tid), int(cnt)
        if cnt <= 0:
            continue
        info = items.get(tid) or {}
        if int(info.get("restrict", 0) or 0) & RESTRICT_NOT_COMBINE_MATERIAL:
            continue
        a = agg.setdefault(tid, {"tid": tid, "name": info.get("name") or ("Mã %d" % tid), "qty": 0, "stacks": 0,
                                 "lv": int(info.get("lv", 0) or 0)})
        a["qty"] += cnt
        a["stacks"] += 1
    return sorted(agg.values(), key=lambda a: (-a["qty"], a["name"]))


def check(client, tid, qty, n_slots):
    if int(qty) <= 0:
        return "số lượng mỗi ô phải > 0"
    if not 1 <= int(n_slots) <= MAX_SLOTS:
        return "số ô phải từ 1 tới 3"
    info = _items().get(int(tid)) or {}
    if int(info.get("restrict", 0) or 0) & RESTRICT_NOT_COMBINE_MATERIAL:
        return "%s không dùng để hợp được" % (info.get("name") or tid)
    if getattr(getattr(client, "state", None), "in_battle", False):
        return "đang trong trận"
    return None


def run(client, tid, qty, rounds, stop_event, n_slots=MAX_SLOTS, progress=None,
        sleep_fn=time.sleep, now=time.time, wait=WAIT_RESULT, gap=GAP, auto_decompose=True,
        settle=SETTLE, keep_bonus=27, keep_level=0):
    """Hợp tới khi đủ ``rounds`` lần (0 = tới khi hết nguyên liệu), bấm dừng, hoặc server không trừ đồ."""
    lbl = getattr(client, "_label", "?")
    tid, qty, rounds, n_slots = int(tid), int(qty), int(rounds), int(n_slots)
    name = (_items().get(tid) or {}).get("name") or ("mã %d" % tid)
    err = check(client, tid, qty, n_slots)
    if err:
        log.warning("[%s] Hợp vật phẩm: %s", lbl, err)
        return {"done": 0, "used": 0, "why": err}
    start = total(client, tid)
    done, why, broken, kept_n = 0, "xong", 0, 0
    items = _items()
    log.info("[%s] Hợp vật phẩm: %s, %d ô × %d cái, %s (đang có %d)", lbl, name, n_slots, qty,
             "%d lần" % rounds if rounds > 0 else "tới khi hết", start)
    while True:
        if stop_event.is_set() or not getattr(client, "running", True):
            why = "đã bấm dừng"
            break
        if rounds > 0 and done >= rounds:
            why = "đủ %d lần" % rounds
            break
        if getattr(getattr(client, "state", None), "in_battle", False):
            sleep_fn(1.0)
            continue
        entries = plan(client, tid, qty, n_slots)
        if entries is None:
            why = "hết nguyên liệu (còn %d, cần %d)" % (total(client, tid), qty * n_slots)
            break
        before = total(client, tid)
        snap = {k: list(v) for k, v in list((getattr(client, "bag_slots", None) or {}).items())}
        client.send(0x17, payload(entries))
        deadline = now() + wait
        while total(client, tid) >= before and now() < deadline and not stop_event.is_set():
            sleep_fn(0.2)
        after = total(client, tid)
        if after >= before:
            why = "server không trừ nguyên liệu (túi đầy hoặc bị từ chối)"
            break
        done += 1
        log.info("[%s] Hợp lần %d: dùng %d %s, còn %d", lbl, done, before - after, name, after)
        if auto_decompose:
            sleep_fn(settle)
            kept = []
            gear = new_gear(snap, dict(getattr(client, "bag_slots", None) or {}), tid, items,
                            getattr(client, "bag_bonus", None), keep_bonus, keep_level, kept)
            for slot, ktid, kwhy in kept:
                kept_n += 1
                log.info("[%s] ⭐ Giữ lại %s ở ô %d (%s), không phân giải", lbl,
                         (items.get(ktid) or {}).get("name") or ktid, slot, kwhy)
            if gear:
                ok = decompose(client, gear, stop_event, sleep_fn, now, wait)
                broken += ok
                log.info("[%s] Phân giải %d/%d món vừa hợp ra", lbl, ok, len(gear))
                if ok < len(gear) and not stop_event.is_set():
                    why = "phân giải không xong (%d/%d món) — dừng để fen kiểm tra" % (ok, len(gear))
                    break
        if progress is not None:
            try:
                progress({"tid": tid, "name": name, "done": done, "rounds": rounds, "left": after,
                          "used": start - after, "broken": broken, "kept": kept_n})
            except Exception:
                pass
        sleep_fn(gap)
    used = start - total(client, tid)
    log.info("[%s] Hợp vật phẩm dừng: %s — hợp %d lần, dùng %d %s", lbl, why, done, used, name)
    return {"done": done, "used": used, "why": why, "name": name, "broken": broken, "kept": kept_n}
