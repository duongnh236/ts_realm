"""Party giữa các tab (account) đang đăng nhập trong app: đội trưởng mời, thành viên tự nhận.

Gói tin party của TS Realm trùng ts_bot (đối chiếu bảng gói mobile của TS Manager PC 1.0.183):
  C:013-007 [07 00][entity 8B]        mời
  S:013-009 [09 00][entity người mời] lời mời tới mình  -> ts_bot tự trả C:013-008 [08 00 01][entity]
  S:013-005 / 013-006                 có người vào đội / danh sách đội (client.party_members, party_leader)
  C:013-004 [04 00][entity đội trưởng] rời đội
ts_bot đã có sẵn: ``client.invite_entity``, nhánh nhận lời mời (``auto_accept_party`` +
``party_invite_ready``, chỉ nhận người cùng ``party_idx`` hoặc tên trong PARTY_LEADERS), ``leave_party``.

Module này chỉ gắn các client của app vào cùng một ``party_idx`` rồi điều phối mời / chờ vào đội.
Server chỉ cho mời người đang đứng cùng map (và nhìn thấy nhau).
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("bot")

PIDX = 9001          # party_idx riêng của app (không đụng party cấu hình của ts_bot)


def _cm():
    from train_bot import client as cm
    return cm


def _cfg():
    from train_bot import config
    return config


def in_party_with(leader, member) -> bool:
    """``member`` đã nằm trong đội của ``leader`` (theo danh sách đội server gửi về leader)."""
    me = bytes(getattr(member, "self_entity", b"") or b"")
    lead = bytes(getattr(leader, "self_entity", b"") or b"")
    if not me or not lead:
        return False
    roster = [bytes(e) for e in (getattr(leader, "party_members", None) or [])]
    if me in roster:
        return True
    ml = getattr(member, "party_leader", None)
    return bool(ml) and bytes(ml) == lead


def attach(clients, leader, pidx=PIDX):
    """Gắn mọi client vào ``pidx``: đăng ký entity, chỉ nhận lời mời của đội trưởng."""
    cm, cfg = _cm(), _cfg()
    for c in clients:
        c.party_idx = pidx
        ent = getattr(c, "self_entity", None)
        if ent:
            cm._register_party_entity(pidx, ent)
            cm._register_party_client(pidx, ent, c)
    name = getattr(leader, "char_name", None)
    by_idx = getattr(cfg, "PARTY_LEADERS_BY_IDX", None)
    if name and isinstance(by_idx, dict):
        by_idx[pidx] = [name]           # lời mời từ người lạ (khác tên đội trưởng) bị từ chối
    for c in clients:
        if c is leader:
            continue
        c.auto_accept_party = True
        if hasattr(c, "set_party_invite_ready"):
            c.set_party_invite_ready(True)
        else:
            c.party_invite_ready = True


def form(leader, members, timeout=40.0, gap=4.0, stop=None, say=None):
    """Đội trưởng mời từng thành viên tới khi vào đội hết hoặc hết ``timeout`` giây.
    Trả (đã vào, chưa vào) theo nhãn account."""
    say = say or (lambda m: log.info(m))
    members = [m for m in members if m is not leader]
    attach([leader] + members, leader)
    deadline = time.time() + timeout
    last = {}
    while True:
        missing = [m for m in members if getattr(m, "running", False) and not in_party_with(leader, m)]
        if not missing or time.time() >= deadline or (stop is not None and stop.is_set()):
            break
        for m in missing:
            if time.time() - last.get(id(m), 0) < gap:
                continue
            last[id(m)] = time.time()
            if leader.current_map is not None and getattr(m, "current_map", None) != leader.current_map:
                say("Party: %s đang ở map %s, đội trưởng ở map %s -> chưa mời được"
                    % (_label(m), getattr(m, "current_map", None), leader.current_map))
                continue
            say("Party: %s mời %s" % (_label(leader), _label(m)))
            leader.invite_entity(m.self_entity)
        time.sleep(1.0)
    joined = [_label(m) for m in members if in_party_with(leader, m)]
    left = [_label(m) for m in members if not in_party_with(leader, m)]
    return joined, left


def disband(leader, members):
    """Thành viên rời đội của đội trưởng (C:013-004 kèm entity đội trưởng), rồi tắt nhận lời mời."""
    for m in members:
        if m is leader or not getattr(m, "running", False):
            continue
        try:
            if in_party_with(leader, m):
                m.leave_party(leader_entity=getattr(leader, "self_entity", None))
        except Exception as exc:
            log.warning("[%s] rời party lỗi: %s", _label(m), exc)
        m.party_invite_ready = False


def _label(c):
    return getattr(c, "char_name", None) or getattr(c, "_label", None) or "?"


def _label_entity(c, entity):
    """Tên đội trưởng theo entity (tra các client cùng party_idx), không biết thì mã rút gọn."""
    if not entity:
        return None
    entity = bytes(entity)
    if bytes(getattr(c, "self_entity", b"") or b"") == entity:
        return _label(c)
    try:
        for p in c.party_peers() or ():
            if bytes(getattr(p, "self_entity", b"") or b"") == entity:
                return _label(p)
    except Exception:
        pass
    return entity.hex()[:8]


def summary(c):
    """Đội hiện tại của client theo danh sách server gửi (S:013-005/006): None nếu không ở đội."""
    members = [bytes(e) for e in (getattr(c, "party_members", None) or [])]
    lead = getattr(c, "party_leader", None)
    if not members and not lead:
        return None
    if lead and bytes(lead) not in members:
        members.insert(0, bytes(lead))
    me = bytes(getattr(c, "self_entity", b"") or b"")
    return {"size": len(members), "leader": _label_entity(c, lead),
            "is_leader": bool(lead) and bytes(lead) == me,
            "names": [_label_entity(c, e) for e in members]}
