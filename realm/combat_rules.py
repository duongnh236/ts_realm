"""Luật đánh thêm cho ``train_bot.combat`` (gắn lúc chạy, không sửa file của ts_bot).

Theo Battle AI của TS Manager (APK + bản PC):
  * Sau Hồi Sinh: đồng đội dính Hỗn Loạn / đóng băng / trói / choáng / ngủ / độc -> giải.
    Thứ tự người được giải: NV hệ Thủy/Địa > NV hệ Phong/Hỏa > NV khác > Tướng.
  * Dịch có buff đáng giải (Nhân Giả Vô Địch, Kết Giới, Linh Kính, Băng Tường) -> giải buff.
    ``dispel_mode: "all"`` để giải cả 46 loại buff.
  * Địch có Đẩu Chuyển (13021) -> giải TRƯỚC MỌI VIỆC, kể cả hồi sinh (``dau_chuyen_first``).
  * Dịch đang có Kết Giới -> không đánh vào, đánh con khác trong lúc chờ giải.
  * Kiểu đánh boss: ``full_attack`` bỏ khiên/buff, ``survive`` khiên trước, ``auto`` chỉ khiên
    khi máu ô mình <= ``auto_guard_hp`` (mặc định 50%).
"""
from __future__ import annotations

import logging
import threading

from . import status_logic as sl

log = logging.getLogger("bot")

CLEANSE_NAMES = {
    14022: "Giải Hỗn Loạn", 20015: "Tứ Nhân Giải Loạn", 14007: "Giải Mê", 11015: "Tan Băng",
    14014: "Giải Độc", 20019: "Giải Thoát", 11025: "Trạng Giải", 11040: "C.Giải Trừ",
    11031: "Giải Thuật", 20050: "Giải Trừ Cường",
}

_lock = threading.Lock()
_claims = {}
_installed = False
RULES = {"cleanse": True, "dispel": True, "dispel_mode": "worthy", "avoid_barrier": True,
         "boss_style": "auto", "auto_guard_hp": 0.5,
         # AI đánh 40 NPC theo thứ tự vai trò của TS Manager (party_battle_roles_policy)
         "dau_chuyen_first": True,
         "npc40_ai": "ts_manager", "party_hp_emergency": 0.5, "guard_hp": 0.5,
         "guard_outnumbered_by": 2,
         # Buff theo chế độ: {"boss"|"npc40"|"nhi_kieu": {"char": {"skill": id, "target": "pet"|"char"},
         # "pet": {...}}} (app chọn, realm.loadout.apply ghi vào). Rỗng = không buff.
         # "boss_buffs" = tên cũ của mode_buffs["boss"].
         "mode_buffs": {}, "boss_buffs": {}, "buff_min_gap": 3}

_realm_rules = threading.local()   # .only = True: chỉ đọc luật skill do app chọn


def _is_realm_rule(rule):
    return isinstance(rule, dict) and str(rule.get("tag") or "").startswith("realm_")


_buff_cast = {}      # (nhóm, chế độ, hàng, cột, loại buff) -> (thế hệ trận, lượt) lần buff gần nhất
_SKILL_KIND = {}     # skill buff -> ô trạng thái (kind) server dùng, học từ S:053-001 trong trận


def _learn_kinds(status_by_kind):
    for by_kind in (status_by_kind or {}).values():
        for kind, sid in (by_kind or {}).items():
            try:
                _SKILL_KIND[int(sid)] = kind
            except (TypeError, ValueError):
                pass


def buff_group(skill):
    """Loại buff: cùng ô trạng thái (đã thấy trong trận) thì coi là cùng loại, buff sau đè buff trước."""
    kind = _SKILL_KIND.get(int(skill))
    return ("k", kind) if kind is not None else ("s", int(skill))


def _owner(combat, state, unit, tag):
    return state.label + (":char:" if unit == combat.config.UNIT_CHAR else ":pet:") + tag


def _group(state):
    g = getattr(state, "party_idx", None)
    return state.label if g is None else g


def _dead(stat):
    return getattr(stat, "hp_max", 0) > 0 and getattr(stat, "hp", 0) <= 0


def _alive_allies(state):
    allies = getattr(state, "allies", None) or {}
    alive = {pos for pos, u in allies.items() if getattr(u, "hp", 0) > 0 or not getattr(u, "hp_max", 0)}
    return alive or None


def try_top_dispel(combat, state, unit, skills, stat, options):
    """Đẩu Chuyển trên người địch -> giải trước mọi việc (kể cả hồi sinh)."""
    if not RULES.get("dau_chuyen_first", True):
        return None
    return try_dispel(combat, state, unit, skills, stat, options, only=sl.TOP_PRIORITY_DISPEL)


def try_cleanse(combat, state, unit, skills, stat, options):
    if not RULES.get("cleanse") or _dead(stat):
        return None
    sbk = getattr(state, "status_by_kind", None) or {}
    victims = sl.ally_cc(sbk, getattr(state, "ally_rows", (2, 3)), _alive_allies(state))
    if not victims:
        return None
    char_row = getattr(state, "char_row", 3)
    allies = getattr(state, "allies", None) or {}

    def rank_of(pos):
        u = allies.get(pos)
        return sl.ally_ladder_rank(pos[0] == char_row, getattr(u, "element", None))

    pick = sl.pick_cleanse(skills, stat.sp, combat._skill_cost, victims, rank_of=rank_of)
    if pick is None:
        return None
    skill, (row, col) = pick
    if not combat._claim_target(state, "cleanse", (row, col), _owner(combat, state, unit, "cleanse"),
                                _claims, _lock, _group(state)):
        return None
    kind, sid = victims[(row, col)]
    log.info("[%s] giải khống chế: ô %d/%d dính %s (%s) -> %s", state.label, row, col,
             sl.skill_label(sid), kind, CLEANSE_NAMES.get(skill, skill))
    return combat.Decision(unit, state.my_atype, col, skill, b=row)


def _fight_key(state):
    tr = getattr(state, "tracker", None)
    return int(getattr(tr, "generation", 0) or 0), int(getattr(tr, "turn", 0) or 0)


MODE_NAMES = {"boss": "buff boss", "npc40": "buff 40 NPC", "nhi_kieu": "buff Nhị Kiều"}


def buff_mode(state):
    """Chế độ đang đánh để chọn bộ buff: 40 NPC / Nhị Kiều (realm_mode) hoặc boss (boss_mode)."""
    rm = getattr(state, "realm_mode", None)
    if rm in ("npc40", "nhi_kieu"):
        return rm
    if getattr(state, "boss_mode", False):
        return "boss"
    return None


def _buff_cfg(mode, key):
    mb = (RULES.get("mode_buffs") or {}).get(mode)
    if mb is None and mode == "boss":
        mb = RULES.get("boss_buffs")
    return (mb or {}).get(key)


def try_buff(combat, state, unit, skills, stat, options):
    """Buff dame (hoặc buff người dùng chọn) trong trận boss / 40 NPC / Nhị Kiều.

    Dùng khi: đang ở chế độ có cấu hình buff, đã học skill, đủ SP, mục tiêu còn sống và CHƯA mang buff đó (đọc từ
    danh sách trạng thái S:053-001 / ``status_by_kind``). Server không báo trạng thái thì vẫn không
    buff lại trước ``buff_min_gap`` lượt kể từ lần buff trước trong cùng trận."""
    mode = buff_mode(state)
    if mode is None or _dead(stat):
        return None
    key = "char" if unit == combat.config.UNIT_CHAR else "pet"
    cfg = _buff_cfg(mode, key)
    if not cfg:
        return None
    try:
        skill = int(cfg.get("skill") or 0)
    except (TypeError, ValueError):
        return None
    if not skill or skill not in set(skills or ()) or stat.sp < combat._skill_cost(skill):
        return None
    col = state.my_atype
    row = getattr(state, "char_row", 3) if cfg.get("target") == "char" else 2
    tgt = getattr(state, "pet", None) if row == 2 else getattr(state, "char", None)
    if tgt is not None and getattr(tgt, "hp_max", 0) > 0 and getattr(tgt, "hp", 1) <= 0:
        return None
    sbk = getattr(state, "status_by_kind", None) or {}
    _learn_kinds(sbk)
    on = sbk.get((row, col)) or {}
    grp = buff_group(skill)
    # Mục tiêu đang mang đúng buff này, hoặc buff cùng loại (cùng ô trạng thái server) -> không buff trùng
    if skill in set(on.values()) or (grp[0] == "k" and grp[1] in on):
        return None
    gen, turn = _fight_key(state)
    # Ghi theo MỤC TIÊU + loại buff (không theo người buff): nhân vật vừa buff pet thì pet không buff
    # trùng lên chính nó cùng lượt / trong ``buff_min_gap`` lượt, kể cả khi server chưa báo trạng thái.
    ck = (_group(state), mode, row, col, grp)
    gap = max(1, int(RULES.get("buff_min_gap", 3) or 0))
    with _lock:
        last = _buff_cast.get(ck)
        if last is not None and last[0] == gen and 0 <= turn - last[1] < gap:
            return None
        _buff_cast[ck] = (gen, turn)
    log.info("[%s] %s: %s dùng %s lên %s", state.label, MODE_NAMES[mode], "nhân vật" if key == "char" else "pet",
             ((getattr(combat.config, "SKILL_INFO", {}) or {}).get(skill) or {}).get("name", skill),
             "nhân vật" if row != 2 else "pet")
    return combat.Decision(unit, state.my_atype, col, skill, b=row)


def try_dispel(combat, state, unit, skills, stat, options, only=None):
    """``only`` = tập buff giới hạn (vd. chỉ Đẩu Chuyển); None = theo ``dispel_mode``."""
    if not RULES.get("dispel") or _dead(stat) or not getattr(state, "enemy_slots", None):
        return None
    offered = combat._offered_targets(options, state.my_atype)
    if not offered:
        return None
    alive = {(combat._row(p), combat._col(p)) for p in state.enemy_slots or []}
    buffed = sl.enemy_buffs(getattr(state, "status_by_kind", None) or {},
                            getattr(state, "enemy_rows", (0, 1)), alive,
                            worthy_only=RULES.get("dispel_mode", "worthy") != "all")
    if only is not None:
        buffed = {pos: b & only for pos, b in buffed.items() if b & only}
    pick = sl.pick_dispel(skills, stat.sp, combat._skill_cost, buffed)
    if pick is None:
        return None
    skill, (b1, b2) = pick
    col = combat._resolve_target(b1 * 10 + b2, offered)
    if col is None:
        return None
    if not combat._claim_target(state, "break_protect", (b1, b2), _owner(combat, state, unit, "dispel"),
                                combat._break_claims, combat._break_lock, _group(state)):
        return None
    log.info("[%s] giải buff boss ô %d/%d (%s) -> skill %s", state.label, b1, b2,
             ", ".join(sl.skill_label(s) for s in sorted(buffed[(b1, b2)])), skill)
    return combat.Decision(unit, state.my_atype, col, skill, b=b1)


def guard_allowed(state, stat) -> bool:
    """Kiểu đánh boss quyết định có được đặt khiên/buff phòng thủ không."""
    if not getattr(state, "boss_mode", False):
        return True
    style = RULES.get("boss_style", "auto")
    if style == "full_attack":
        return False
    if style == "survive":
        return True
    hp, mx = getattr(stat, "hp", 0), getattr(stat, "hp_max", 0)
    return not mx or hp <= mx * float(RULES.get("auto_guard_hp", 0.5))


def avoid_barrier(combat, state, offered, pos):
    """Dich dang co Ket Gioi -> doi sang con khac (it mau nhat) de khong phi dame, cho giai Ket Gioi."""
    if pos is None or not RULES.get("avoid_barrier", True) or not getattr(state, "support_combat", False):
        return pos
    avoid = sl.avoid_damage_targets(getattr(state, "status_by_kind", None) or {},
                                    getattr(state, "enemy_rows", (0, 1)))
    if (combat._row(pos), combat._col(pos)) not in avoid:
        return pos
    off = set(offered or ())
    alt = [(p, hp) for p, hp in (getattr(state, "enemy_hp", None) or {}).items()
           if hp > 0 and (combat._row(p), combat._col(p)) not in avoid
           and combat._col_reachable(combat._col(p), off)]
    if not alt:
        return pos  # con nao cung co Ket Gioi -> danh nhu cu
    new = min(alt, key=lambda x: x[1])[0]
    log.info("[%s] ô %d có Kết Giới -> đánh ô %d trước, chờ giải", state.label, pos, new)
    return new


def _party_hp_ratio(state):
    units = [u for u in (getattr(state, "allies", None) or {}).values() if getattr(u, "hp_max", 0) > 0]
    if not units:
        return 1.0
    return sum(max(0, u.hp) for u in units) / float(sum(u.hp_max for u in units))


def _alive_count(hp_by_pos):
    return sum(1 for hp in (hp_by_pos or {}).values() if hp > 0)


def _party_heal(combat, state, unit, skills, stat, tag):
    cfg = combat.config
    if (_party_hp_ratio(state) >= float(RULES.get("party_hp_emergency", 0.5))
            or cfg.SKILL_HEAL_ALL not in (skills or ()) or stat.sp < cfg.HEAL_SP_COST):
        return None
    at = state.my_atype
    low = state.lowest_hp_ally()
    ht = low.slot if (low is not None and getattr(low, "slot", None) is not None) else at
    hc = combat._hang_char_ta(state)
    if combat._claim_support_action(state, "heal_hp", (hc, ht), state.label + ":" + tag, stat.sp,
                                    combat._heal_decide):
        log.info("[%s] TSM: máu party < %d%% -> hồi máu toàn party", state.label,
                 int(float(RULES.get("party_hp_emergency", 0.5)) * 100))
        return combat.Decision(unit, at, ht, cfg.SKILL_HEAL_ALL, b=hc)
    return None


def _guard_first(state, stat):
    """guard_before_freeze của TS Manager: máu mình thấp HOẶC phe địch đông hơn -> khiên trước."""
    hp, mx = getattr(stat, "hp", 0), getattr(stat, "hp_max", 0)
    low = bool(mx) and hp <= mx * float(RULES.get("guard_hp", 0.5))
    allies = sum(1 for u in (getattr(state, "allies", None) or {}).values() if getattr(u, "hp", 0) > 0)
    enemies = _alive_count(getattr(state, "enemy_hp", None))
    outnumbered = bool(allies) and enemies - allies >= int(RULES.get("guard_outnumbered_by", 2))
    return low or outnumbered


def tsm_decide(combat, state, unit, skills, stat, options, tag, spam, fire_min):
    """Đẩu Chuyển trên địch (ưu tiên nhất, theo yêu cầu) -> thứ tự của TS Manager: hồi sinh -> hồi máu party khi nguy -> giải khống chế đồng đội ->
    (khiên trước nếu đang yếu / bị áp đảo) -> khống chế địch -> giải buff địch -> phá khiên -> buff người dùng chọn -> khiên ->
    hồi SP party -> đánh (tránh con có Kết Giới, ưu tiên con ít máu)."""
    if getattr(stat, "hp_max", 0) > 0 and getattr(stat, "hp", 0) <= 0:
        return combat._combat_attack(state, unit, skills, stat, options, spam, fire_min)
    steps = (
        lambda: try_top_dispel(combat, state, unit, skills, stat, options),
        lambda: combat._try_revive(state, unit, skills, stat, options),
        lambda: _party_heal(combat, state, unit, skills, stat, tag),
        lambda: try_cleanse(combat, state, unit, skills, stat, options),
        lambda: combat._try_protect(state, unit, skills, stat) if _guard_first(state, stat) else None,
        lambda: combat._try_cc(state, unit, skills, stat, options, "high"),
        lambda: combat._try_cc(state, unit, skills, stat, options, "low"),
        lambda: try_dispel(combat, state, unit, skills, stat, options),
        lambda: combat._try_break_enemy_protect(state, unit, skills, stat, options),
        lambda: try_buff(combat, state, unit, skills, stat, options),
        lambda: combat._try_protect(state, unit, skills, stat),
        lambda: combat._try_sp_restore(state, unit, skills, stat),
    )
    for step in steps:
        d = step()
        if d is not None:
            return d
    return combat._combat_attack(state, unit, skills, stat, options, spam, fire_min)


def _use_tsm(state):
    return (getattr(state, "support_combat", False) and getattr(state, "realm_mode", None) == "npc40"
            and RULES.get("npc40_ai", "ts_manager") == "ts_manager")


def install(combat, rules: dict = None):
    """Bọc decide_char / decide_pet / _try_protect của ``train_bot.combat``."""
    global _installed
    if rules:
        RULES.update(rules)
    if _installed:
        return
    _installed = True
    orig_char, orig_pet, orig_protect = combat.decide_char, combat.decide_pet, combat._try_protect
    orig_low, orig_pos = combat._lowest_hp_enemy, combat._enemy_target_pos
    orig_rules, orig_attack = getattr(combat, "_battle_rules", None), getattr(combat, "_combat_attack", None)

    # Luật skill đánh do app chọn (tag "realm_...") KHÔNG được chen trước hồi sinh / giải / hồi máu /
    # khiên: lúc ts_bot đọc luật thì ẩn chúng đi, tới bước TẤN CÔNG mới dùng (thay cho đánh tự động).
    def _battle_rules(state, unit_key):
        rules = orig_rules(state, unit_key) or []
        only = getattr(_realm_rules, "only", False)
        return [r for r in rules if _is_realm_rule(r) == only]

    def _combat_attack(state, unit, skills, stat, options, spam_attr, fire_min):
        if not _dead(stat):
            key = "char" if unit == combat.config.UNIT_CHAR else "pet"
            _realm_rules.only = True
            try:
                d = combat._custom_decision(state, unit, key, skills, stat, options)
            finally:
                _realm_rules.only = False
            if d is not None and d is not getattr(combat, "_CUSTOM_AUTO", object()):
                return d
        return orig_attack(state, unit, skills, stat, options, spam_attr, fire_min)

    def _support(state, unit, skills, stat, options):
        if not getattr(state, "support_combat", False):
            return None
        top = try_top_dispel(combat, state, unit, skills, stat, options)
        if top is not None:
            return top
        rv = combat._try_revive(state, unit, skills, stat, options)
        if rv is not None:
            return rv  # Hồi Sinh vẫn đứng đầu như ts_bot
        return (try_cleanse(combat, state, unit, skills, stat, options)
                or try_dispel(combat, state, unit, skills, stat, options)
                or try_buff(combat, state, unit, skills, stat, options))

    def _custom(state, unit, key, skills, stat, options):
        c = combat._custom_decision(state, unit, key, skills, stat, options)
        return None if c is getattr(combat, "_CUSTOM_AUTO", object()) else c

    def decide_char(state, options, first_turn=False):
        cfg = combat.config
        combat._register_current_unit(state, cfg.UNIT_CHAR, state.skills_char)
        if _use_tsm(state):
            c = _custom(state, cfg.UNIT_CHAR, "char", state.skills_char, state.char, options)
            return c if c is not None else tsm_decide(
                combat, state, cfg.UNIT_CHAR, state.skills_char, state.char, options,
                "char", "char_spam", cfg.CHAR_FIRE_MIN_SP)
        d = _support(state, cfg.UNIT_CHAR, state.skills_char, state.char, options)
        return d if d is not None else orig_char(state, options, first_turn)

    def decide_pet(state, options, first_turn=False):
        cfg = combat.config
        if _use_tsm(state):
            combat._register_current_unit(state, cfg.UNIT_PET, state.pet_skills)
            c = _custom(state, cfg.UNIT_PET, "pet", state.pet_skills, state.pet, options)
            return c if c is not None else tsm_decide(
                combat, state, cfg.UNIT_PET, state.pet_skills, state.pet, options,
                "pet", "pet_spam", cfg.PET_FIRE_MIN_SP)
        d = _support(state, cfg.UNIT_PET, state.pet_skills, state.pet, options)
        return d if d is not None else orig_pet(state, options, first_turn)

    def _try_protect(state, unit, skills, stat):
        if not guard_allowed(state, stat):
            return None
        return orig_protect(state, unit, skills, stat)

    def _lowest_hp_enemy(state, offered):
        return avoid_barrier(combat, state, offered, orig_low(state, offered))

    def _enemy_target_pos(state, offered, target_key):
        return avoid_barrier(combat, state, offered, orig_pos(state, offered, target_key))

    combat.decide_char, combat.decide_pet, combat._try_protect = decide_char, decide_pet, _try_protect
    combat._lowest_hp_enemy, combat._enemy_target_pos = _lowest_hp_enemy, _enemy_target_pos
    if orig_rules is not None and orig_attack is not None:
        combat._battle_rules, combat._combat_attack = _battle_rules, _combat_attack
