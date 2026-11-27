"""Đội hình theo chế độ: chọn pet ra trận, skill đánh chính và skill buff cho nhân vật / pet.

Ba chế độ, mỗi chế độ cấu hình riêng (app có 3 khung chọn):
  * ``boss``     - Boss Thế Giới.
  * ``npc40``    - 40 NPC.
  * ``nhi_kieu`` - Nhị Kiều (2k).

* Pet: ghi vào ``battle_config["pet_roles"][vai]``. Boss: ``do_world_boss`` của ts_bot có
  ``@_pet_role("boss")`` nên tự đổi pet trước trận. 40 NPC / Nhị Kiều: ``features`` gọi
  ``ensure_pet_role(vai)`` trước khi vào đánh và trả pet về vai mặc định khi xong.
* Skill đánh: luật đặt ĐẦU danh sách luật của ts_bot (``battle_config["char"]`` /
  ``["pets"][pet id]``). Boss dùng ``condition="boss"`` (giữ lại giữa các lần chạy). 40 NPC /
  Nhị Kiều dùng ``condition="quest"`` (cả hai chạy với quest_mode) và được gỡ khi xong hoạt động
  (``clear``) để không lan sang phó bản. Skill chưa học / thiếu SP thì ts_bot tự bỏ qua luật đó.
  Giải Đẩu Chuyển / hồi sinh / giải khống chế / giải buff địch của ts_realm vẫn đứng trước.
* Buff: ``combat_rules.RULES["mode_buffs"][chế độ]`` - xem ``combat_rules.try_buff``.
"""
from __future__ import annotations

ATTACK_CATS = (1, 2, 3)          # skill gây dame (skills_data.json: cat)
BUFF_CATS = (4, 9, 19)           # buff phòng thủ / tăng chỉ số

MODES = ("boss", "npc40", "nhi_kieu")
TAG = "realm_boss"               # đánh dấu luật do ts_realm thêm, để gỡ/ghi đè lần sau
TAGS = {"boss": TAG, "npc40": "realm_npc40", "nhi_kieu": "realm_nhi_kieu"}
CONDITION = {"boss": "boss", "npc40": "quest", "nhi_kieu": "quest"}


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


def _strip(rules, tag):
    return [r for r in (rules or []) if not (isinstance(r, dict) and r.get("tag") == tag)]


def _mode(mode):
    if mode not in MODES:
        raise ValueError("chế độ lạ: %r" % (mode,))
    return mode


def has_choice(opts) -> bool:
    return any(int((opts or {}).get(k) or 0) for k in ("pet_id", "char_skill", "pet_skill", "char_buff", "pet_buff"))


def apply(client, opts, rules_mod=None, mode="boss"):
    """Áp lựa chọn của ``mode`` vào client trước khi chạy. ``opts`` = lựa chọn từ app."""
    mode = _mode(mode)
    tag, cond = TAGS[mode], CONDITION[mode]
    opts = opts or {}
    st = client.state
    cfg = dict(getattr(st, "battle_config", None) or {})
    pet_id = int(opts.get("pet_id") or 0)
    roles = dict(cfg.get("pet_roles") or {})
    if pet_id:
        roles[mode] = pet_id
    else:
        roles.pop(mode, None)
    cfg["pet_roles"] = roles

    char_rules = _strip(cfg.get("char") if isinstance(cfg.get("char"), list) else [], tag)
    # Boss TG không còn chọn skill đánh: combat_rules.boss_attack tự đánh skill tốn SP cao nhất.
    if mode == "boss":
        opts = {k: v for k, v in opts.items() if k not in ("char_skill", "pet_skill")}
    cs = int(opts.get("char_skill") or 0)
    if cs:
        char_rules.insert(0, {"skill": cs, "target": "auto", "condition": cond, "tag": tag})
    cfg["char"] = char_rules

    ps = int(opts.get("pet_skill") or 0)
    pets_cfg = {k: _strip(v, tag) for k, v in dict(cfg.get("pets") or {}).items() if isinstance(v, list)}
    owner = pet_id or getattr(st, "active_pet_id", None)
    if ps and owner:
        pets_cfg.setdefault(str(int(owner)), []).insert(
            0, {"skill": ps, "target": "auto", "condition": cond, "tag": tag})
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
        mb = dict(rules_mod.RULES.get("mode_buffs") or {})
        mb[mode] = buffs
        rules_mod.RULES["mode_buffs"] = mb
        if mode == "boss":
            rules_mod.RULES["boss_buffs"] = buffs   # tên cũ, giữ cho settings.json cũ
    return cfg


def clear(client, mode, rules_mod=None):
    """Gỡ hết luật / pet / buff của ``mode`` (gọi khi hoạt động xong)."""
    return apply(client, {}, rules_mod=rules_mod, mode=mode)
