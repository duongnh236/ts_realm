"""Võ tướng xuất chiến khi đi party (40 NPC / Nhị Kiều): xếp lại thứ tự võ tướng mang theo.

Đánh một mình thì cả 9 võ tướng mang theo đều ra trận. Đi party thì mỗi người chỉ được vài con: võ
tướng đi theo (C:019-001) cộng các con đứng ĐẦU danh sách. Capture 27/11 18:21, party 3 người: đội
trưởng ra trận với ô 1, ô 2 + Lữ Bố (pet đi theo, ô 5); thành viên được 2 con. Ô nào ra trận nằm
ở trường thứ 3 (u16) của bản ghi võ tướng trong roster trận S:011-005.

Đổi chỗ 2 võ tướng trong danh sách (giống kéo thả trong game):
  C:033-014 [0e 00][ô a][ô b]          -> S:033-014 [0e 00][mã][ô a][ô b], mã 0 = được (6 = lỗi,
                                          vd a == b), rồi server gửi lại danh sách S:015-008.
S:015-008 [08 00][?][n] + n bản ghi, byte đầu mỗi bản ghi = số ô (1..n), tiếp theo mã võ tướng u16.

Module này đọc thứ tự từ S:015-008, gửi đổi chỗ để các võ tướng người dùng chọn lên đầu danh sách
trước khi vào trận. Chỉ đổi ngoài trận.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("bot")

OP_ROLE = 0x21          # họ 033
SUB_SWAP = 0x0E
OP_PET = 0x0F


def pet_slots(pkt: bytes) -> list:
    """[(ô, mã võ tướng)] từ S:015-008 nguyên bản TS Realm (frame đủ header). Sai khuôn -> []."""
    from .weapon_skills import THING_REALM
    if len(pkt) < 10 or pkt[6] != OP_PET or pkt[7:9] != b"\x08\x00":
        return []
    b = pkt[7:]
    out, pos = [], 3
    for _ in range(b[2]):
        if pos + 35 > len(b):
            return []
        size = 35 + b[pos + 31] + 6 * THING_REALM + 9
        if pos + size > len(b):
            return []
        out.append((b[pos], int.from_bytes(b[pos + 1:pos + 3], "little")))
        pos += size
    return out


def patch_client(cls) -> None:
    if getattr(cls, "_realm_pet_order_patched", False):
        return
    orig = cls._dispatch

    def _dispatch(self, opcode, pkt):
        try:
            if opcode == OP_PET and len(pkt) > 9 and pkt[7:9] == b"\x08\x00":
                slots = pet_slots(pkt)
                if slots:
                    self._realm_pet_slots = slots
            elif opcode == OP_ROLE and len(pkt) >= 12 and pkt[7] == SUB_SWAP:
                self._realm_swap_result = (pkt[9], pkt[10], pkt[11], time.time())
                ev = getattr(self, "_realm_swap_event", None)
                if ev is not None:
                    ev.set()
        except Exception:
            pass
        return orig(self, opcode, pkt)

    cls._dispatch = _dispatch
    cls._realm_pet_order_patched = True


def install(client_module) -> None:
    cls = getattr(client_module, "GameClient", None)
    if cls is not None:
        patch_client(cls)


def plan(slots, wanted):
    """Các lần đổi chỗ (ô a, ô b) để ``wanted`` (mã võ tướng, theo thứ tự) đứng ở ô 1, 2, ...
    Võ tướng không mang theo thì bỏ qua."""
    order = {s: p for s, p in slots}
    where = {p: s for s, p in slots}
    swaps, target = [], 1
    for pid in wanted:
        if pid not in where:
            continue
        cur = where[pid]
        if cur != target:
            other = order.get(target)
            swaps.append((target, cur))
            order[target], order[cur] = pid, other
            where[pid] = target
            if other is not None:
                where[other] = cur
        target += 1
    return swaps


def arrange(client, wanted, wait=4.0) -> bool:
    """Đưa các võ tướng ``wanted`` lên đầu danh sách. True nếu đã đúng thứ tự."""
    wanted = [int(p) for p in (wanted or ()) if int(p or 0)]
    if not wanted:
        return True
    if getattr(getattr(client, "state", None), "in_battle", False):
        log.info("[%s] Xếp võ tướng: đang trong trận -> để sau", getattr(client, "_label", ""))
        return False
    slots = list(getattr(client, "_realm_pet_slots", None) or ())
    if not slots:
        log.warning("[%s] Xếp võ tướng: chưa có danh sách võ tướng (S:015-008)", getattr(client, "_label", ""))
        return False
    ok = True
    for a, b in plan(slots, wanted):
        ev = threading.Event()
        client._realm_swap_event = ev
        client._realm_swap_result = None
        client.send(OP_ROLE, bytes((SUB_SWAP, 0, a, b)))
        if not ev.wait(wait):
            log.warning("[%s] Xếp võ tướng: đổi ô %d <-> %d không thấy server trả lời",
                        getattr(client, "_label", ""), a, b)
            ok = False
            break
        code = (client._realm_swap_result or (None,))[0]
        if code != 0:
            log.warning("[%s] Xếp võ tướng: đổi ô %d <-> %d bị từ chối (mã %s)",
                        getattr(client, "_label", ""), a, b, code)
            ok = False
            break
        # server gửi lại S:015-008 ngay sau; tự đổi trong bộ nhớ phòng khi gói đó tới chậm
        cur = dict(getattr(client, "_realm_pet_slots", None) or ())
        cur[a], cur[b] = cur.get(b), cur.get(a)
        client._realm_pet_slots = sorted((s, p) for s, p in cur.items() if p is not None)
        time.sleep(0.3)
    try:
        from train_bot import config
        names = getattr(config, "PET_NAMES", None) or {}
    except Exception:
        names = {}
    if ok:
        log.info("[%s] Xếp võ tướng xuất chiến party: %s", getattr(client, "_label", ""),
                 ", ".join(names.get(p, "0x%04x" % p) for p in wanted))
    return ok
