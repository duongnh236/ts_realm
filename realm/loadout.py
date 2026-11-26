"""Đội hình đánh boss: chọn pet ra trận, skill đánh chính và skill buff cho nhân vật / pet.

* Pet: ghi vào ``battle_config["pet_roles"]["boss"]``. ``do_world_boss`` của ts_bot có
  ``@_pet_role("boss")`` nên tự đổi sang pet này trước trận (gói C:019-001, server xác nhận
  S:019-001 - cùng khuôn ở TS Realm).
* Skill đánh: luật ``condition="boss"`` đặt ĐẦU danh sách luật của ts_bot (``battle_config["char"]``
  / ``["pets"][pet id]``). Skill chưa học / thiếu SP thì ts_bot tự bỏ qua luật đó và đánh tự động.
  Giải khống chế / giải buff boss / hồi sinh của ts_realm vẫn đứng trước.
* Buff: ``combat_rules.RULES["boss_buffs"]`` - xem ``combat_rules.try_buff``.
"""
from __future__ import annotations

ATTACK_CATS = (1, 2, 3)          # skill gây dame (skills_data.json: cat)
BUFF_CATS = (4, 9, 19)           # buff phòng thủ / tăng chỉ số

TAG = "realm_boss"               # đánh dấu luật do ts_realm thêm, để gỡ/ghi đè lần sau


def _info(sid):
    try:
        from train_bot import config
        return (config.SKILL_INFO or {}).get(int(sid)) or {}
    except Exception:
        return {}


def skill_entry(sid):
    i = _info(sid)
    return {"id": int(sid), "name": (i.get("name") or "skill %d" % int(sid)).strip(),
            "cat": int(i.get("cat") or 0), "cost": int(i.get("cost") or 0)}


def loadout(client):
    """Dữ liệu cho app: skill nhân vật đã học, pet mang theo kèm skill, pet đang ra trận."""
    st = getattr(client, "state", None)
    char = sorted(int(s) for s in (getattr(st, "skills_char", None) or ()))
    pets = []
    for pid, name in list(getattr(st, "carried_pets", None) or ()):
        try:
            sk = client.pet_usable_skills(pid)
        except Exception:
            sk = []
        pets.append({"id": int(pid), "name": name or "0x%04x" % int(pid),
                     "skills": [skill_entry(s) for s in sk]})
    return {"char_skills": [skill_entry(s) for s in char], "pets": pets,
            "active_pet": getattr(st, "active_pet_id", None)}


def _strip(rules):
    return [r for r in (rules or []) if not (isinstance(r, dict) and r.get("tag") == TAG)]


def apply(client, opts, rules_mod=None):
    """Áp lựa chọn đánh boss vào client trước khi chạy. ``opts`` = world_boss options từ app."""
    st = client.state
    cfg = dict(getattr(st, "battle_config", None) or {})
    pet_id = int(opts.get("pet_id") or 0)
    roles = dict(cfg.get("pet_roles") or {})
    if pet_id:
        roles["boss"] = pet_id
    else:
        roles.pop("boss", None)
    cfg["pet_roles"] = roles

    char_rules = _strip(cfg.get("char") if isinstance(cfg.get("char"), list) else [])
    cs = int(opts.get("char_skill") or 0)
    if cs:
        char_rules.insert(0, {"skill": cs, "target": "auto", "condition": "boss", "tag": TAG})
    cfg["char"] = char_rules

    ps = int(opts.get("pet_skill") or 0)
    pets_cfg = {k: _strip(v) for k, v in dict(cfg.get("pets") or {}).items() if isinstance(v, list)}
    owner = pet_id or getattr(st, "active_pet_id", None)
    if ps and owner:
        pets_cfg.setdefault(str(int(owner)), []).insert(
            0, {"skill": ps, "target": "auto", "condition": "boss", "tag": TAG})
    pets_cfg = {k: v for k, v in pets_cfg.items() if v}
    if pets_cfg:
        cfg["pets"] = pets_cfg
    else:
        cfg.pop("pets", None)
    st.battle_config = cfg

    if rules_mod is not None:
        buffs = {}
        for key in ("char", "pet"):
            sid = int(opts.get("%s_buff" % key) or 0)
            if sid:
                buffs[key] = {"skill": sid, "target": opts.get("%s_buff_target" % key) or "pet"}
        rules_mod.RULES["boss_buffs"] = buffs
    return cfg
