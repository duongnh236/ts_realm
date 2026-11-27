"""Đăng nhập server TS Realm (game ``net.tsrealm.game``).

Khác ts_bot (mobiplay): TS Realm KHÔNG có bước HTTP lấy access_token. Game nối TCP thẳng tới
server rồi gửi tài khoản + mật khẩu ngay trong gói C:001-000. Bắt bằng PCAPdroid trên máy thật
26/11 (game 2.0.40.1, BundleVersion 1.3):

    c0 91 [len LE 2] 00 00 | 01          frame + opcode 001
    00 00                                (giống ts_bot: sub 000 + 1 byte 0)
    71 29                                版本編號 (2, LE) = 0x2971
    01 00                                伺服器ID (2, LE)
    00 00 00 00                          連線碼 (4)
    01                                   登入方式 = 1 (tài khoản/mật khẩu, ts_bot là 25 = VNSDK)
    00 00
    03 'nil' | L 'tài khoản' | L 'mật khẩu'   chuỗi độ dài 1 byte, UTF-8
    0a 00

Cả gói XOR 0xAD như ts_bot. Server trả S:001-002 (tài khoản + mã server phát) rồi vào game như cũ.
"""
from __future__ import annotations

import struct

REALM_SERVERS = {
    "ts_realm": {"label": "TS Realm", "ip": "136.85.11.211", "id": 1},
}
REALM_VERSION = 0x2971
LOGIN_KIND = 1
OP_LOGIN = 0x01
XOR_KEY = 0xAD


def is_realm_server(name) -> bool:
    return str(name or "") in REALM_SERVERS


def _byte_l(text: str) -> bytes:
    raw = str(text).encode("utf-8")
    if len(raw) > 255:
        raise ValueError("chuỗi quá dài cho gói đăng nhập")
    return bytes([len(raw)]) + raw


def build_realm_auth_packet(account: str, password: str, server_id: int = 1,
                            connect_code: int = 0, version: int = REALM_VERSION) -> bytes:
    """Gói C:001-000 đã XOR, sẵn sàng gửi."""
    payload = (b"\x00\x00"
               + struct.pack("<HHI", version & 0xFFFF, server_id & 0xFFFF, connect_code & 0xFFFFFFFF)
               + bytes([LOGIN_KIND]) + b"\x00\x00"
               + _byte_l("nil") + _byte_l(account) + _byte_l(password)
               + b"\x0a\x00")
    frame = b"\xc0\x91" + struct.pack("<H", 7 + len(payload)) + b"\x00\x00" + bytes([OP_LOGIN]) + payload
    return bytes(b ^ XOR_KEY for b in frame)


def realm_login(username: str, password: str) -> dict:
    """Thay ``train_bot.login.login``: không gọi HTTP, mang tài khoản/mật khẩu sang gói TCP."""
    return {"user_id": username, "access_token": password, "username": username}


def install(client_module) -> None:
    """Cho GameClient của train_bot gửi gói đăng nhập TS Realm (connect + relogin)."""
    if getattr(client_module, "_realm_auth_installed", False):
        return
    client_module.build_auth_packet = (
        lambda user_id, access_token, server_id=1: build_realm_auth_packet(user_id, access_token, server_id))
    cls = getattr(client_module, "GameClient", None)
    if cls is not None:
        patch_self_entity(cls)
        patch_bag_snapshot(cls)
        patch_use_slot(cls)
        patch_battle_start_marker(cls)
        patch_turn_order(cls)
        patch_world_boss_totals(cls)
        patch_pet_list(cls)
        patch_notices(cls)
    patch_potion_data(client_module)
    try:
        import importlib
        bt = importlib.import_module(client_module.__name__.rsplit(".", 1)[0] + ".battle_tracker")
        patch_battle_tracker(bt.BattleTracker)
    except (ImportError, AttributeError, ValueError):
        pass
    client_module._realm_auth_installed = True


POTION_KINDS = (17, 18)              # kd 17 = đồ ăn/rượu, 18 = thuốc
ATTR_HP, ATTR_SP = 25, 26            # a1k của items_gamedata.json


def potion_heal(raw: dict):
    """(hp, sp) hồi của 1 món theo a1k/a1v trong items_gamedata.json, không phải thuốc thì None.

    Lượng hồi = a1v - 100 (Cam Thảo a1v 110 -> 10 HP, đúng cột hp sẵn có). Capture 27/11: Thuốc
    Hoàng Cân 0x6a12 (a1k 26, a1v 265) hồi +165 SP. File dữ liệu bỏ trống cột hp/sp của 22 món
    thuốc loại này (Thuốc Hoàng Cân, Viên Côn Lôn...) nên ts_bot coi là "hết thuốc"."""
    if not isinstance(raw, dict) or raw.get("kd") not in POTION_KINDS or raw.get("battle"):
        return None
    if int(raw.get("bs", 0) or 0):
        return None                      # nút Sử dụng bị khoá
    heal = int(raw.get("a1v", 0) or 0) - 100
    if heal <= 0:
        return None
    if raw.get("a1k") == ATTR_HP:
        return heal, 0
    if raw.get("a1k") == ATTR_SP:
        return 0, heal
    return None


def patch_potion_data(client_module) -> None:
    """Điền hp/sp còn thiếu cho thuốc trong từ điển gamedata của ts_bot (xem ``potion_heal``)."""
    orig = getattr(client_module, "_load_gamedata_items", None)
    if orig is None or getattr(orig, "_realm_potions", False):
        return
    loader = getattr(client_module, "_load_json_data_file", None)

    def _load_gamedata_items():
        items = orig()
        if getattr(client_module, "_realm_potions_filled", None) is items:
            return items
        raw = loader("items_gamedata.json") if loader else None
        for k, v in (raw or {}).items():
            try:
                iid = int(k, 16) if isinstance(k, str) and k.lower().startswith("0x") else int(k)
            except ValueError:
                continue
            cur = items.get(iid)
            if cur is None or cur.get("hp") or cur.get("sp"):
                continue
            heal = potion_heal(v)
            if heal:
                cur["hp"], cur["sp"] = heal
        client_module._realm_potions_filled = items
        return items

    _load_gamedata_items._realm_potions = True
    client_module._load_gamedata_items = _load_gamedata_items


def self_entity_from_login_reply(pkt: bytes):
    """Entity 8 byte của nhân vật trong S:001-002 (frame đã giải XOR), không có thì None.

    TS Realm không gửi gói 0x69 mà ts_bot dùng để biết entity của mình. Entity nằm ngay trong
    S:001-002: ``c0 91 LL LL 00 00 | 01 | 02 00 | 00 01 00 01 00 | entity(8) | ...`` (cùng entity
    với S:003-000 tự xuất hiện và S:079-007, đối chiếu từ capture 26/11)."""
    if len(pkt) >= 22 and pkt[6] == 0x01 and pkt[7:9] == b"\x02\x00":
        return bytes(pkt[14:22])
    return None


def patch_self_entity(cls) -> None:
    """Khi nhận S:001-002 mà chưa có entity -> đưa vào nhánh 0x69 sẵn có của ts_bot."""
    if getattr(cls, "_realm_entity_patched", False):
        return
    orig = cls._dispatch

    def _dispatch(self, opcode, pkt):
        orig(self, opcode, pkt)
        if opcode == 0x01 and getattr(self, "self_entity", None) is None:
            ent = self_entity_from_login_reply(pkt)
            if ent:
                orig(self, 0x69, b"\xc0\x91\x11\x00\x00\x00\x69\x01\x00" + ent)

    cls._dispatch = _dispatch
    cls._realm_entity_patched = True


BAG_RECORD = 58      # TS Realm: [ô u16][ThingData 56B]; ts_bot (server VN): [ô u8][ThingData 35B]


def parse_bag_snapshot(pkt: bytes):
    """S:023-005 (túi đồ lúc đăng nhập) của TS Realm -> {ô: [mã đồ, số lượng]}, sai định dạng thì None.

    ``body = 00 | n u16 | n x ([ô u16][mã u16][số lượng u32][...])``, mỗi bản ghi 58 byte (đối chiếu
    capture 26/11: n=172 -> 3 + 172*58 = độ dài body; ô 53 = 2 vé 46629, ô 172 = 6 vé 46614)."""
    if len(pkt) < 12 or pkt[6] != 0x17 or pkt[7:9] != b"\x05\x00":
        return None
    body = pkt[9:]
    n = int.from_bytes(body[1:3], "little")
    if len(body) != 3 + n * BAG_RECORD:
        return None
    slots = {}
    for k in range(n):
        r = body[3 + k * BAG_RECORD: 3 + (k + 1) * BAG_RECORD]
        idx = int.from_bytes(r[0:2], "little")
        tid = int.from_bytes(r[2:4], "little")
        cnt = int.from_bytes(r[4:8], "little")
        if idx > 0 and tid > 0 and 0 < cnt < 10_000_000:
            slots[idx] = [tid, cnt]
    return slots


def patch_bag_snapshot(cls) -> None:
    """Sau nhánh 0x17/05 của ts_bot (đọc theo bản ghi 36 byte -> sai), ghi đè túi bằng bản đọc đúng."""
    if getattr(cls, "_realm_bag_patched", False):
        return
    orig = cls._dispatch

    def _dispatch(self, opcode, pkt):
        rm = parse_bag_remove(pkt) if opcode == 0x17 else None
        saved = None
        if rm is not None:
            # ts_bot đọc S:023-009 với ô 1 byte -> trừ nhầm ô / nhầm số; giữ lại ô nó đụng để trả về
            k = pkt[9]
            rec = self.bag_slots.get(k)
            saved = (k, list(rec) if rec is not None else None)
        orig(self, opcode, pkt)
        if rm is not None:
            k, rec = saved
            if rec is None:
                self.bag_slots.pop(k, None)
            else:
                self.bag_slots[k] = rec
            slot, n = rm
            cur = self.bag_slots.get(slot)
            if cur is not None:
                left = int(cur[1]) - n
                if left > 0:
                    self.bag_slots[slot] = [cur[0], left]
                else:
                    self.bag_slots.pop(slot, None)
                    getattr(self, "bag_bonus", {}).pop(slot, None)
            counts = {}
            for t, c in self.bag_slots.values():
                counts[t] = counts.get(t, 0) + c
            self.bag_counts = counts
        if opcode == 0x17:
            upd = parse_bag_set_item(pkt)
            if upd is not None:
                slot, tid, cnt = upd
                bonus = getattr(self, "bag_bonus", None)
                if bonus is None:
                    bonus = self.bag_bonus = {}
                if tid > 0 and cnt > 0:
                    self.bag_slots[slot] = [tid, cnt]
                    v = item_bonus(pkt)
                    if v:
                        bonus[slot] = v
                    else:
                        bonus.pop(slot, None)
                else:
                    self.bag_slots.pop(slot, None)
                    bonus.pop(slot, None)
                counts = {}
                for t, c in self.bag_slots.values():
                    counts[t] = counts.get(t, 0) + c
                self.bag_counts = counts
            slots = parse_bag_snapshot(pkt)
            if slots is not None:
                self.bag_slots = slots
                self.bag_items = {}          # ThingData 56B khác 35B của ts_bot -> không đoán
                self.bag_bonus = {}
                counts = {}
                for tid, cnt in slots.values():
                    counts[tid] = counts.get(tid, 0) + cnt
                self.bag_counts = counts

    cls._dispatch = _dispatch
    cls._realm_bag_patched = True


def item_bonus(pkt: bytes) -> int:
    """"Giá trị" riêng của món trong S:023-008 (u16 ở pkt[42:44] = byte 26 sau ô/mã/số lượng).

    Capture 27/11: món Kiệt Tác Sáng Ma Thủ (21431) hợp ra có giá trị 28, 26 món thường đều 0.
    Chưa rõ tên chỉ số (có thể là điểm cộng thêm); dùng để chừa đồ tốt khi tự phân giải."""
    if len(pkt) < 44:
        return 0
    return int.from_bytes(pkt[42:44], "little")


def parse_bag_remove(pkt: bytes):
    """S:023-009 (trừ đồ khỏi một ô) của TS Realm -> (ô, số lượng), khác định dạng thì None.

    ``09 00 | ô u16 | số lượng u32`` - capture 27/11: phân giải 8 món -> 8 gói ``0900 1d00 01000000`` ..."""
    if len(pkt) < 15 or pkt[6] != 0x17 or pkt[7:9] != b"\x09\x00":
        return None
    slot = int.from_bytes(pkt[9:11], "little")
    n = int.from_bytes(pkt[11:15], "little")
    if not 0 < slot < 1000 or not 0 < n < 10_000_000:
        return None
    return slot, n


def parse_bag_set_item(pkt: bytes):
    """S:023-008 (một ô túi đổi) của TS Realm -> (ô, mã, số lượng), khác định dạng thì None.

    ``08 00 | ô u16 | mã u16 | số lượng u32 | ...`` - capture 26/11 sau khi dùng vé shop ở ô 172:
    ``0800 ac00 16b6 05000000`` (còn 5 vé 46614). ts_bot đọc ô 1 byte nên lệch cả mã lẫn số lượng."""
    if len(pkt) < 17 or pkt[6] != 0x17 or pkt[7:9] != b"\x08\x00":
        return None
    slot = int.from_bytes(pkt[9:11], "little")
    tid = int.from_bytes(pkt[11:13], "little")
    cnt = int.from_bytes(pkt[13:17], "little")
    if not 0 < slot < 1000 or cnt >= 10_000_000:
        return None
    return slot, tid, cnt


def use_item_payload(slot: int, qty: int = 1, target: int = 0) -> bytes:
    """C:023-015 dùng vật phẩm của TS Realm: ``0f 00 | ô u16 | sl 1B | 00 00 00 | đích 1B | 00``.

    Capture 26/11: vé shop ô 172 -> ``0f00 ac00 01 000000 00 00``, vé tặng ô 53 -> ``0f00 3500 01 ...``,
    bình máu cho pet -> ``0f00 6400 05 000000 05 00``. ts_bot gửi ô 1 byte nên server bỏ qua."""
    qty = max(1, min(int(qty), 255))
    return (b"\x0f\x00" + int(slot).to_bytes(2, "little") + bytes([qty])
            + b"\x00\x00\x00" + bytes([int(target) & 0xFF]) + b"\x00")


def patch_use_slot(cls) -> None:
    if getattr(cls, "_realm_use_patched", False):
        return

    def use_slot(self, slot: int, target: int = 0, qty: int = 1) -> bool:
        rec = self.bag_slots.get(slot)
        if rec is not None and rec[1] <= 0:
            return False
        self.send(0x17, use_item_payload(slot, qty, target))
        return True

    cls.use_slot = use_slot
    cls._realm_use_patched = True


def is_realm_turn_marker(pkt: bytes) -> bool:
    """S:020-008 không kèm byte trạng thái (``08 00``, frame 9 byte).

    TS Realm gửi gói này NGAY SAU lượt đầu của mỗi trận boss (capture 26/11: 21.221 052-001 ->
    21.227 020-008 ``0800``), còn kết trận là ``080026``. ts_bot coi mọi 020-008 là kết trận/bỏ chạy
    -> hạ in_battle, huỷ lệnh đánh -> bot đứng im cả trận và báo "không vào được trận"."""
    return len(pkt) == 9 and pkt[6] == 0x14 and pkt[7:9] == b"\x08\x00"


def patch_battle_start_marker(cls) -> None:
    if getattr(cls, "_realm_marker_patched", False):
        return
    orig = cls._dispatch

    def _dispatch(self, opcode, pkt):
        if opcode == 0x14 and is_realm_turn_marker(pkt):
            st = getattr(self, "state", None)
            if st is not None and getattr(st, "in_battle", False):
                return                       # đang trong trận: không phải kết trận
        orig(self, opcode, pkt)

    cls._dispatch = _dispatch
    cls._realm_marker_patched = True



ROLE_EXTRA = 2       # mỗi bản ghi tham chiến của TS Realm dư 2 byte cuối so với server VN


def patch_battle_tracker(tracker_cls) -> None:
    """Bảng tham chiến S:011-250 / S:011-005 của TS Realm khác server VN ở 2 chỗ:

    * tên là UTF-8 (VN: UTF-16LE) - "Cơ Trí Đất Sét" 19 byte -> ts_bot giải mã hỏng;
    * mỗi bản ghi dư 2 byte cuối: quái không tên = 42 + 2 byte, người chơi = 42 + tên + ngoại hình
      + 2 (capture 26/11: create 110 byte = 42 + 1+19 + 48, spawn quái 44 byte).

    ts_bot đọc hỏng -> tracker không bật -> ``in_battle`` bị kéo về False mỗi lượt -> bot vào
    trận mà không ra lệnh đánh (log 26/11 14:23)."""
    if getattr(tracker_cls, "_realm_roles_patched", False):
        return
    import importlib
    import struct
    mod = importlib.import_module(tracker_cls.__module__)
    fmt, size = mod.ROLE_HEADER_FORMAT, mod.ROLE_HEADER_SIZE
    players, named = mod.PLAYER_ROLE_KINDS, mod.NAMED_NPC_ROLE_KINDS
    Unit = mod.BattleUnit

    def _parse_name(data, offset):
        if offset >= len(data):
            return None
        end = offset + 1 + data[offset]
        if end > len(data):
            return None
        raw = data[offset + 1:end]
        try:
            return raw.decode("utf-8"), end
        except UnicodeDecodeError:
            try:
                return raw.decode("utf-16le"), end
            except UnicodeDecodeError:
                return None

    def _parse_roles(cls, data, tag="", mot_phan=False):
        units = []
        offset = 0
        while offset < len(data):
            chunk = data[offset:offset + size]
            if len(chunk) != size:
                return cls._hong(tag, "thieu byte header", offset, data, units, mot_phan)
            v = struct.unpack_from(fmt, chunk)
            war_type, role_kind, role_id, template_id, master_id = v[:5]
            row, col, hp_max, sp_max, hp, sp, level, upgrade, element = v[5:]
            if row > 3 or col > 5:
                return cls._hong(tag, "row=%d col=%d ngoai bang (role_kind=%d)" % (row, col, role_kind),
                                 offset, data, units, mot_phan)
            cursor = offset + size
            name = ""
            if role_kind in players:
                parsed = cls._parse_player_appearance(data, cursor)
                if parsed is None:
                    return cls._hong(tag, "doc ngoai hinh nguoi choi hong (role_kind=%d)" % role_kind,
                                     offset, data, units, mot_phan)
                name, cursor = parsed
            elif role_kind in named:
                parsed = _parse_name(data, cursor)
                if parsed is None:
                    return cls._hong(tag, "doc ten NPC hong (role_kind=%d)" % role_kind,
                                     offset, data, units, mot_phan)
                name, cursor = parsed
            cursor += ROLE_EXTRA
            if cursor > len(data):
                return cls._hong(tag, "thieu 2 byte cuoi ban ghi", offset, data, units, mot_phan)
            units.append(Unit(row=row, col=col, role_id=role_id, template_id=template_id,
                              master_id=master_id, war_type=war_type, role_kind=role_kind,
                              hp=hp, hp_max=hp_max, sp=sp, sp_max=sp_max, level=level,
                              upgrade_level=upgrade, element=element, name=name, alive=hp > 0))
            offset = cursor
        return units

    tracker_cls._parse_name = staticmethod(_parse_name)
    tracker_cls._parse_roles = classmethod(_parse_roles)
    tracker_cls._realm_roles_patched = True


def patch_turn_order(cls) -> None:
    """Đổi lại thứ tự gói đầu lượt cho giống server VN mà ts_bot viết theo.

    TS Realm gửi ``053-001`` (lệnh được phép) TRƯỚC ``052-001`` (bắt đầu lượt):
    ``053-001 x3, 073-004, 052-001, 051-001`` (capture 26/11 + log trận 14:42). ts_bot nhận 053-001
    ở lượt cũ -> tính lệnh, rồi 052-001 tăng lượt -> tính lại; lần sau pet tưởng hết quái và bỏ
    lệnh, server phải chờ hết giờ lượt (~90s). Giữ 053-001 lại tới khi có 052-001 rồi mới chuyển."""
    if getattr(cls, "_realm_order_patched", False):
        return
    orig = cls._dispatch

    def _flush(self):
        pending = self.__dict__.pop("_realm_pending_35", None)
        for p in pending or ():
            orig(self, 0x35, p)

    def _dispatch(self, opcode, pkt):
        if opcode == 0x35 and len(pkt) >= 9 and pkt[7:9] == b"\x01\x00":
            self.__dict__.setdefault("_realm_pending_35", []).append(pkt)
            return
        pending = self.__dict__.get("_realm_pending_35")
        if pending and opcode == 0x49:
            return orig(self, opcode, pkt)       # 073-004 nằm giữa, không liên quan thứ tự
        if pending and opcode == 0x34:
            orig(self, opcode, pkt)
            _flush(self)
            return
        if pending:
            _flush(self)
        return orig(self, opcode, pkt)

    cls._dispatch = _dispatch
    cls._realm_order_patched = True


def patch_world_boss_totals(cls) -> None:
    """Ghi lại S:073-003 (thống kê boss trong ngày): mục 3 = tổng dame hôm nay, mục 4 = số trận."""
    if getattr(cls, "_realm_wbtotal_patched", False):
        return
    orig = cls._dispatch

    def _dispatch(self, opcode, pkt):
        if opcode == 0x49 and len(pkt) >= 14 and pkt[7] == 0x03:
            kind = pkt[9]
            val = int.from_bytes(pkt[10:14], "little")
            if kind == 3:
                import datetime
                day = (datetime.datetime.utcnow() + datetime.timedelta(hours=7)).strftime("%Y-%m-%d")
                # lúc đăng nhập server gửi 0 trước rồi mới gửi số thật -> trong cùng ngày không cho
                # số tụt về 0; sang ngày mới thì nhận lại từ đầu
                if val or getattr(self, "realm_wb_total_day", None) != day:
                    self.realm_wb_total = val
                    self.realm_wb_total_day = day
            elif kind == 4:
                self.realm_wb_fights = val
        return orig(self, opcode, pkt)

    cls._dispatch = _dispatch
    cls._realm_wbtotal_patched = True


THING_REALM, THING_VN = 56, 35


def pet_list_to_vn(pkt: bytes):
    """S:015-008 (danh sách pet mang theo) của TS Realm -> cùng gói theo khuôn server VN.

    Mỗi bản ghi = 35 byte đầu + tên (độ dài ở byte 31) + 6 trang bị x ThingData + 9 byte cuối.
    TS Realm: ThingData 56 byte (VN 35) -> bản ghi 380 byte thay vì 254; ts_bot đọc lệch nên chỉ
    thấy 2/5 pet (capture 26/11: 5 pet 0x3715, 0x2ee2, 0x2eef, 0x32d0, 0xb166). Cắt mỗi ThingData về
    35 byte đầu (ts_bot chỉ đọc mã đồ 2 byte đầu). Không đúng khuôn TS Realm thì trả None."""
    if len(pkt) < 10 or pkt[6] != 0x0F or pkt[7:9] != b"\x08\x00":
        return None
    b = pkt[7:]
    n = b[2]
    pos, out = 3, [b[:3]]
    for _ in range(n):
        if pos + 35 > len(b):
            return None
        head = 35 + b[pos + 31]
        size = head + 6 * THING_REALM + 9
        if pos + size > len(b):
            return None
        rec = b[pos:pos + size]
        eq = rec[head:head + 6 * THING_REALM]
        out.append(rec[:head] + b"".join(eq[k * THING_REALM:k * THING_REALM + THING_VN] for k in range(6))
                   + rec[head + 6 * THING_REALM:])
        pos += size
    if pos != len(b):
        return None
    body = b"".join(out)
    return b"\xc0\x91" + (7 + len(body)).to_bytes(2, "little") + pkt[4:7] + body


def patch_pet_list(cls) -> None:
    if getattr(cls, "_realm_petlist_patched", False):
        return
    orig = cls._dispatch

    def _dispatch(self, opcode, pkt):
        if opcode == 0x0F and len(pkt) > 9 and pkt[7:9] == b"\x08\x00":
            conv = pet_list_to_vn(pkt)
            if conv is not None:
                return orig(self, opcode, conv)
        return orig(self, opcode, pkt)

    cls._dispatch = _dispatch
    cls._realm_petlist_patched = True


NOTICE_KEEP = 60          # giữ bao nhiêu dòng thông báo gần nhất
NOTICE_CHUNK = 250        # server cắt thông báo dài thành nhiều gói, mỗi gói tối đa 250 byte chữ


def parse_notice(pkt: bytes):
    """S:002 thông báo hệ thống dạng chữ -> (kênh, chữ, số byte chữ), không phải thì None.

    ``0a 00 | kênh u8 | 00 | n u8 | n byte UTF-8 (kết thúc 00)``. Kênh 1/2/3 (khung chat / giữa màn
    hình / hệ thống). Byte thứ 4 = 01 là dạng có cấu trúc (nhận đồ...) -> bỏ qua. Capture 27/11:
    "Hợp thành hàng loạt 20/20 lần: ... - phí 1780 Đồng - hoàn nguyên liệu 1 lần",
    "Không hợp thành được lần này. Chưa mất gì."."""
    if len(pkt) < 13 or pkt[6] != 0x02 or pkt[7:9] != b"\x0a\x00" or pkt[10] != 0:
        return None
    n = pkt[11]
    raw = pkt[12:12 + n]
    text = raw.split(b"\x00", 1)[0].decode("utf-8", "replace")
    return pkt[9], text, n


def patch_notices(cls) -> None:
    """Ghi thông báo hệ thống của server vào ``realm_notices`` = [(seq, giờ, chữ)] để tính năng
    (hợp vật phẩm...) đọc được server nói gì; ghép lại các mẩu bị cắt 250 byte.
    Cũng ghi ô túi lớn nhất từng thấy (``realm_bag_max_slot``) và Đồng đã tiêu từ S:026 id=2."""
    if getattr(cls, "_realm_notices_patched", False):
        return
    orig = cls._dispatch

    def _dispatch(self, opcode, pkt):
        orig(self, opcode, pkt)
        try:
            if opcode == 0x02:
                got = parse_notice(pkt)
                if got is not None:
                    _add_notice(self, *got)
            elif opcode == 0x1a and len(pkt) >= 13:
                sid = int.from_bytes(pkt[7:9], "little")
                val = int.from_bytes(pkt[9:13], "little")
                if sid == 4:                         # số Đồng hiện có -> đếm lại từ đầu
                    self.realm_money_spent = 0
                elif sid == 2:                       # Đồng vừa bị trừ (phí hợp 1780 = đúng S:026)
                    self.realm_money_spent = int(getattr(self, "realm_money_spent", 0) or 0) + val
            elif opcode == 0x17:
                slots = getattr(self, "bag_slots", None) or {}
                if slots:
                    top = max(int(k) for k in slots)
                    if top > int(getattr(self, "realm_bag_max_slot", 0) or 0):
                        self.realm_bag_max_slot = top
        except Exception:
            pass

    cls._dispatch = _dispatch
    cls._realm_notices_patched = True


def _add_notice(client, channel, text, nbytes, now=None):
    import time as _t
    now = _t.time() if now is None else now
    lst = getattr(client, "realm_notices", None)
    if lst is None:
        lst = client.realm_notices = []
    last = getattr(client, "_realm_notice_open", None)
    if last is not None and last[0] == channel and now - last[1] < 1.5 and lst and lst[-1][0] == last[2]:
        seq, t0, old = lst[-1]
        lst[-1] = (seq, t0, old + text)              # mẩu nối tiếp của thông báo bị cắt
        seq_now = seq
    else:
        seq_now = int(getattr(client, "realm_notice_seq", 0) or 0) + 1
        client.realm_notice_seq = seq_now
        lst.append((seq_now, now, text))
        del lst[:-NOTICE_KEEP]
    client._realm_notice_open = (channel, now, seq_now) if nbytes >= NOTICE_CHUNK else None
