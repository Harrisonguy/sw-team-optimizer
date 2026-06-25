"""Shared stat computation helpers used by both the rune and team optimizer UIs."""
from __future__ import annotations

import json as _json

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SET_SIZE: dict[str, int] = {
    "Violent": 4, "Swift": 4, "Rage": 4,
    "Despair": 4, "Vampire": 4, "Fatal": 4,
    "Will": 2, "Energy": 2, "Guard": 2, "Endure": 2, "Blade": 2,
    "Focus": 2, "Shield": 2, "Revenge": 2, "Nemesis": 2,
    "Destroy": 2, "Fight": 2, "Determination": 2,
    "Enhance": 2, "Accuracy": 2, "Tolerance": 2,
}

# (stat, bonus_type, value)   bonus_type: "pct" or "add"
# Only sets that actually grant a STAT bonus in-game appear here.
# Despair / Vampire / Violent / Nemesis / Will / Shield / Revenge / Destroy
# grant battle EFFECTS (stun chance, lifesteal, extra turn, ATB, immunity,
# shield, counter, HP destruction) — NO stat bonus.
SET_STAT_BONUS: dict[str, tuple[str, str, float]] = {
    "Energy":        ("hp",  "pct", 15.0),
    "Guard":         ("def", "pct", 15.0),
    "Swift":         ("spd", "pct", 25.0),   # % of BASE speed
    "Blade":         ("cr",  "add", 12.0),
    "Rage":          ("cd",  "add", 40.0),
    "Focus":         ("acc", "add", 20.0),
    "Endure":        ("res", "add", 20.0),
    "Fatal":         ("atk", "pct", 35.0),
    "Fight":         ("atk", "pct",  8.0),
    "Determination": ("def", "pct",  8.0),
    "Enhance":       ("hp",  "pct",  8.0),
    "Accuracy":      ("acc", "add", 10.0),
    "Tolerance":     ("res", "add", 10.0),
}

# prefix stat name -> stat_id (same encoding as main/substats)
# Accepts BOTH naming conventions: the DB importer's ('Flat HP', 'CR', 'CD',
# 'RES', 'ACC') and the UI's ('HP+', 'CR%', 'CD%', 'RES%', 'ACC%').
PNAME_TO_ID: dict[str, int] = {
    "HP+": 1, "HP%": 2, "ATK+": 3, "ATK%": 4, "DEF+": 5, "DEF%": 6,
    "SPD": 8, "CR%": 9, "CD%": 10, "RES%": 11, "ACC%": 12,
    "Flat HP": 1, "Flat ATK": 3, "Flat DEF": 5,
    "CR": 9, "CD": 10, "RES": 11, "ACC": 12,
}

# ---------------------------------------------------------------------------
# +15 main-stat projection
# ---------------------------------------------------------------------------
# Main stat value at +15 by stat_id -> {stars: value} (normal runes).
MAIN_STAT_MAX_15: dict[int, dict[int, int]] = {
    1:  {6: 2448, 5: 2088, 4: 1704, 3: 1380},   # Flat HP
    2:  {6: 63,   5: 51,   4: 43,   3: 38},     # HP%
    3:  {6: 160,  5: 135,  4: 111,  3: 92},     # Flat ATK
    4:  {6: 63,   5: 51,   4: 43,   3: 38},     # ATK%
    5:  {6: 160,  5: 135,  4: 111,  3: 92},     # Flat DEF
    6:  {6: 63,   5: 51,   4: 43,   3: 38},     # DEF%
    8:  {6: 42,   5: 39,   4: 30,   3: 27},     # SPD
    9:  {6: 58,   5: 47,   4: 41,   3: 37},     # CR
    10: {6: 80,   5: 65,   4: 57,   3: 43},     # CD
    11: {6: 64,   5: 51,   4: 44,   3: 38},     # RES
    12: {6: 64,   5: 51,   4: 44,   3: 38},     # ACC
}
# Ancient runes (SWEX raw_class 11-16) have higher main-stat maxima.
ANCIENT_MAIN_STAT_MAX_15: dict[int, dict[int, int]] = {
    1:  {6: 2755}, 2: {6: 69}, 3: {6: 180}, 4: {6: 69},
    5:  {6: 180},  6: {6: 69}, 8: {6: 48},  9: {6: 65},
    10: {6: 89},  11: {6: 72}, 12: {6: 72},
}


def projected_main_value(rune: dict) -> float:
    """Main stat value this rune will have at +15.

    Deterministic: main stats grow on every upgrade level, so the +15 value
    is fixed by stat type, star level, and ancient status. Substats are NOT
    projected (their future rolls are random). Returns the current value if
    the rune is already +15 or the stat is unknown.
    """
    cur = float(rune.get("main_stat_value") or 0)
    try:
        lvl = int(rune.get("upgrade_curr") or 0)
    except (TypeError, ValueError):
        lvl = 0
    if lvl >= 15:
        return cur
    sid = rune.get("main_stat_id")
    if sid is None:
        sid = PNAME_TO_ID.get((rune.get("main_stat_name") or "").strip())
    try:
        stars = int(rune.get("stars") or 6)
    except (TypeError, ValueError):
        stars = 6
    ancient = False
    try:
        ancient = int(rune.get("raw_class") or 0) >= 11
    except (TypeError, ValueError):
        pass
    val = None
    if ancient:
        val = (ANCIENT_MAIN_STAT_MAX_15.get(sid) or {}).get(stars)
    if val is None:
        val = (MAIN_STAT_MAX_15.get(sid) or {}).get(stars)
    return float(val) if val is not None else cur


# Empty bonus sentinel — all known bonus keys zeroed
EMPTY_BUILDING_BONUSES: dict[str, float] = {
    "hp_pct": 0.0, "atk_pct": 0.0, "def_pct": 0.0, "spd_pct": 0.0,
    "cd_add": 0.0,  "cr_add": 0.0,  "res_add": 0.0, "acc_add": 0.0,
}


def merge_bonuses(*bonus_dicts) -> dict:
    """Merge multiple bonus dicts (buildings, leader, etc.) by summing each key."""
    out: dict[str, float] = {}
    for bd in bonus_dicts:
        if not bd:
            continue
        for k, v in bd.items():
            out[k] = out.get(k, 0.0) + float(v or 0)
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt_k(n: int | float) -> str:
    """Format large integer as '23.5k' or plain number."""
    n = int(n)
    if n >= 10_000:
        return str(round(n / 1000, 1)) + "k"
    return str(n)


def compute_final_stats(
    monster_info: dict,
    build,
    artifact_flat: dict | None = None,
    building_bonuses: dict | None = None,
) -> dict:
    """Compute approximate in-game final stats for a monster with a given build.

    Accounts for: base stats, rune main stats, rune substats (inc. grind/enchant),
    prefix (innate) stats, active set bonuses, artifact flat bonuses, and island
    building stat bonuses.

    building_bonuses is a dict returned by queries.get_building_bonuses() with keys:
        hp_pct, atk_pct, def_pct, spd_pct  (% of base)
        cd_add, cr_add                       (flat percentage-point additions)

    Returns a dict with keys:
        hp, atk, def_, spd, cr, cd, res, acc
    """
    bb = building_bonuses or {}

    base_hp  = int(monster_info.get("max_lvl_hp",      0) or 0)
    base_atk = int(monster_info.get("max_lvl_attack",  0) or 0)
    base_def = int(monster_info.get("max_lvl_defense", 0) or 0)
    base_spd = int(monster_info.get("base_speed",      0) or 0)
    base_cr  = float(monster_info.get("crit_rate",     0) or 0)
    base_cd  = float(monster_info.get("crit_damage",   0) or 0)
    base_res = float(monster_info.get("resistance",    0) or 0)
    base_acc = float(monster_info.get("accuracy",      0) or 0)

    empty = {
        "hp": base_hp, "atk": base_atk, "def_": base_def,
        "spd": base_spd, "cr": base_cr, "cd": base_cd,
        "res": base_res, "acc": base_acc,
    }
    if not build:
        # Still apply building bonuses even without runes
        bld_hp  = int(base_hp  * float(bb.get("hp_pct",  0)) / 100)
        bld_atk = int(base_atk * float(bb.get("atk_pct", 0)) / 100)
        bld_def = int(base_def * float(bb.get("def_pct", 0)) / 100)
        bld_spd = int(base_spd * float(bb.get("spd_pct", 0)) / 100)
        return {
            "hp":   base_hp  + bld_hp,
            "atk":  base_atk + bld_atk,
            "def_": base_def + bld_def,
            "spd":  base_spd + bld_spd,
            "cr":   min(100, round(base_cr  + float(bb.get("cr_add",  0)), 1)),
            "cd":   round(base_cd  + float(bb.get("cd_add",  0)), 1),
            "res":  round(base_res + float(bb.get("res_add", 0)), 1),
            "acc":  round(base_acc + float(bb.get("acc_add", 0)), 1),
        }

    flat_hp = flat_atk = flat_def = 0
    pct_hp  = pct_atk  = pct_def  = 0.0
    add_spd = 0
    add_cr  = add_cd = add_res = add_acc = 0.0

    def _apply(stat_id: int, val):
        nonlocal flat_hp, flat_atk, flat_def
        nonlocal pct_hp,  pct_atk,  pct_def
        nonlocal add_spd, add_cr, add_cd, add_res, add_acc
        if stat_id == 1:   flat_hp  += int(val or 0)
        elif stat_id == 2:  pct_hp   += float(val or 0)
        elif stat_id == 3:  flat_atk += int(val or 0)
        elif stat_id == 4:  pct_atk  += float(val or 0)
        elif stat_id == 5:  flat_def += int(val or 0)
        elif stat_id == 6:  pct_def  += float(val or 0)
        elif stat_id == 8:  add_spd  += int(val or 0)
        elif stat_id == 9:  add_cr   += float(val or 0)
        elif stat_id == 10: add_cd   += float(val or 0)
        elif stat_id == 11: add_res  += float(val or 0)
        elif stat_id == 12: add_acc  += float(val or 0)

    for sr in build.slots:
        r = sr.rune
        if not r:
            continue
        # Main stat
        _apply(r.get("main_stat_id") or 0, r.get("main_stat_value") or 0)
        # Prefix / innate stat (stored by name, not ID)
        pname = (r.get("prefix_stat_name") or "").strip()
        pval  = r.get("prefix_stat_value") or 0
        if pname and pval:
            _apply(PNAME_TO_ID.get(pname, 0), pval)
        # Substats: sec_eff = [[stat_id, base, enchanted, grind], ...]
        raw = r.get("sec_eff")
        if raw:
            try:
                subs = _json.loads(raw) if isinstance(raw, str) else raw
                for sub in (subs or []):
                    if not sub or len(sub) < 2:
                        continue
                    sid = sub[0]
                    val = (sub[1] or 0) + (sub[3] if len(sub) >= 4 else 0)
                    _apply(sid, val)
            except Exception:
                pass

    # Artifact flat bonuses (HP / ATK / DEF only)
    if artifact_flat:
        flat_hp  += int(artifact_flat.get("hp",  0) or 0)
        flat_atk += int(artifact_flat.get("atk", 0) or 0)
        flat_def += int(artifact_flat.get("def", 0) or 0)

    # Active set bonuses — only count sets that have enough pieces
    set_pct_hp = set_pct_atk = set_pct_def = set_pct_spd = 0.0
    set_add_cr = set_add_cd = set_add_res = set_add_acc = 0.0
    for sname, cnt in (build.set_summary or {}).items():
        req = SET_SIZE.get(sname, 2)
        if cnt < req:
            continue
        bonus = SET_STAT_BONUS.get(sname)
        if not bonus:
            continue
        completed_sets = cnt // req
        stat, btype, raw_bonus = bonus
        bval = raw_bonus * completed_sets
        if btype == "pct":
            if stat == "hp":   set_pct_hp  += bval
            elif stat == "atk": set_pct_atk += bval
            elif stat == "def": set_pct_def += bval
            elif stat == "spd": set_pct_spd += bval
        else:
            if stat == "cr":   set_add_cr  += bval
            elif stat == "cd":  set_add_cd  += bval
            elif stat == "res": set_add_res += bval
            elif stat == "acc": set_add_acc += bval

    # Building % bonuses (additive with rune % and set %, all applied to base)
    bld_hp_pct  = float(bb.get("hp_pct",  0))
    bld_atk_pct = float(bb.get("atk_pct", 0))
    bld_def_pct = float(bb.get("def_pct", 0))
    bld_spd_pct = float(bb.get("spd_pct", 0))
    bld_cd_add  = float(bb.get("cd_add",  0))
    bld_cr_add  = float(bb.get("cr_add",  0))
    bld_res_add = float(bb.get("res_add", 0))
    bld_acc_add = float(bb.get("acc_add", 0))

    total_hp  = int(base_hp  * (1 + (pct_hp  + set_pct_hp  + bld_hp_pct)  / 100) + flat_hp)
    total_atk = int(base_atk * (1 + (pct_atk + set_pct_atk + bld_atk_pct) / 100) + flat_atk)
    total_def = int(base_def * (1 + (pct_def + set_pct_def + bld_def_pct) / 100) + flat_def)
    # SPD % bonuses (Swift set, SPD leader skill, Sky Tribe Totem) apply to
    # BASE speed only — never to rune speed. Swift rounds up in-game.
    import math as _math
    set_spd_bonus = _math.ceil(base_spd * set_pct_spd / 100) if set_pct_spd else 0
    bld_spd_bonus = int(base_spd * bld_spd_pct / 100) if bld_spd_pct else 0
    total_spd = int(base_spd + add_spd + set_spd_bonus + bld_spd_bonus)
    total_cr  = min(100, round(base_cr  + add_cr  + set_add_cr  + bld_cr_add,  1))
    total_cd  = round(base_cd  + add_cd  + set_add_cd  + bld_cd_add,  1)
    # RES and ACC are capped at 100% in-game
    total_res = min(100, round(base_res + add_res + set_add_res + bld_res_add, 1))
    total_acc = min(100, round(base_acc + add_acc + set_add_acc + bld_acc_add, 1))

    return {
        "hp": total_hp, "atk": total_atk, "def_": total_def,
        "spd": total_spd, "cr": total_cr, "cd": total_cd,
        "res": total_res, "acc": total_acc,
    }


def compute_stats_from_equipped(
    monster_info: dict,
    rune_dict: dict,   # {slot_no: rune_row_dict} from get_monster_rune_build
    artifact_flat: dict | None = None,
    building_bonuses: dict | None = None,
) -> dict:
    """Same as compute_final_stats but accepts the raw {slot_no: rune_dict} format
    returned by queries.get_monster_rune_build, without needing a BuildResult object.
    """
    from collections import Counter

    if not rune_dict:
        return compute_final_stats(monster_info, None, artifact_flat, building_bonuses)

    set_counts: dict[str, int] = {}
    for r in rune_dict.values():
        sname = (r.get("set_name") or "").strip()
        if sname:
            set_counts[sname] = set_counts.get(sname, 0) + 1

    class _MockSlot:
        __slots__ = ("slot_no", "rune")
        def __init__(self, slot_no, rune):
            self.slot_no = slot_no
            self.rune    = rune

    class _MockBuild:
        __slots__ = ("slots", "set_summary")
        def __init__(self, slots, set_summary):
            self.slots       = slots
            self.set_summary = set_summary

    slots = [_MockSlot(slot_no=k, rune=v) for k, v in rune_dict.items()]
    mock  = _MockBuild(slots=slots, set_summary=set_counts)
    return compute_final_stats(monster_info, mock, artifact_flat, building_bonuses)


# ---------------------------------------------------------------------------
# Damage / survivability metrics
# ---------------------------------------------------------------------------

def effective_offense(
    stats:        dict,
    cd_bonus:     float = 0.0,
    element_bonus: float = 0.0,
    addl_atk_pct: float = 0.0,
    addl_hp_pct:  float = 0.0,
    addl_def_pct: float = 0.0,
    addl_spd_pct: float = 0.0,
) -> int:
    """Effective Offense (EO) — expected damage coefficient.

    Formula:  EO = ATK × [1 + (CR/100) × (CD/100 - 1)]

    Derivation:
      Non-crit hit  = ATK × multiplier × 1.0
      Critical hit  = ATK × multiplier × (CD/100)
      Expected      = ATK × multiplier × [(1-CR/100) + CR/100 × CD/100]
                    = ATK × multiplier × [1 + CR/100 × (CD/100 - 1)]

    Since the skill multiplier is constant for a given monster, EO is the
    damage-maximising quantity to optimise. CD shown in-game includes the base
    +50%, so CD=150% means 1.5× crit damage (minimum possible value).

    Marginal values (higher = more important to stack first):
      1% ATK%  ≈  base_atk/100 × (1 + CR × (CD/100-1))
      1% CR    ≈  ATK/100 × (CD/100 - 1)    [only if CR < 100%]
      1% CD    ≈  ATK/100 × CR

    Crossover point: CR% and CD% have equal marginal value when
      CD - 100 = CR  (e.g. at CD=200%, CR=100%)
    → Always push CR to 100% before stacking CD beyond 200%.
    """
    atk  = float(stats.get("atk",  0) or 0)
    hp   = float(stats.get("hp",   0) or 0)
    def_ = float(stats.get("def_", 0) or 0)
    spd  = float(stats.get("spd",  0) or 0)
    cr   = min(100.0, float(stats.get("cr",  0) or 0)) / 100.0
    cd   = (float(stats.get("cd", 150) or 150) + float(cd_bonus or 0)) / 100.0
    # Shared crit scaling factor (same for main hit and all additional hits)
    crit_factor = 1.0 + cr * (cd - 1.0)
    # Effective damage base: ATK + artifact additional hits (all crit at same CR/CD)
    # Effect 219: Add'l DMG by % ATK  | 218: by % HP  | 220: by % DEF  | 221: by % SPD
    dmg_base = (atk  * (1.0 + float(addl_atk_pct or 0) / 100.0)
              + hp   * float(addl_hp_pct  or 0) / 100.0
              + def_ * float(addl_def_pct or 0) / 100.0
              + spd  * float(addl_spd_pct or 0) / 100.0)
    eo = dmg_base * crit_factor
    # Element damage bonus (effects 300-304): final multiplier vs dungeon boss element
    if element_bonus:
        eo *= (1.0 + float(element_bonus) / 100.0)
    return int(eo)


def effective_hp(stats: dict) -> int:
    """Effective HP (EHP) — survivability accounting for DEF damage reduction.

    Uses the actual SW damage-reduction formula:
      damage taken multiplier = 1000 / (1140 + 3.75 × DEF)
      EHP = HP / multiplier  = HP × (1140 + 3.75 × DEF) / 1000
    """
    hp   = float(stats.get("hp",   0) or 0)
    def_ = float(stats.get("def_", 0) or 0)
    return int(hp * (1140.0 + 3.75 * def_) / 1000.0)


def eo_rune_score(
    rune: dict,
    ref_atk: float = 3000.0,
    ref_cr:  float = 85.0,
    ref_cd:  float = 200.0,
    projected: bool = False,
) -> float:
    """Per-rune estimate of Effective Offense contribution.

    Used by the optimizer when scoring_mode == 'effective_offense' to rank
    candidate runes for each slot instead of desirability.

    Each stat's EO marginal value at the reference build:
      flat ATK:  delta_atk × (1 + (ref_cr/100) × (ref_cd/100 - 1))
      ATK%:      ref_atk × pct/100 × (1 + (ref_cr/100) × (ref_cd/100 - 1))
      CR%:       ref_atk × add/100 × (ref_cd/100 - 1)  [capped at 100%-ref_cr]
      CD%:       ref_atk × (ref_cr/100) × add/100

    ref_atk / ref_cr / ref_cd are the monster's approximate final stats
    WITHOUT this rune's contribution (base + other runes).  Using typical
    defaults produces a reasonable sort order even without knowing the exact
    build.
    """
    import json as _json

    cr_factor = min(ref_cr, 100.0) / 100.0
    cd_factor = ref_cd / 100.0
    base_eo_mult = 1.0 + cr_factor * (cd_factor - 1.0)   # ≈1.85 at ref

    flat_atk = 0.0
    pct_atk  = 0.0
    add_cr   = 0.0
    add_cd   = 0.0

    # Main stat (match by stat id when available — names vary by source)
    _mid = rune.get("main_stat_id") or PNAME_TO_ID.get(rune.get("main_stat_name") or "")
    mval = projected_main_value(rune) if projected \
           else float(rune.get("main_stat_value") or 0)
    if _mid == 3:    flat_atk += mval
    elif _mid == 4:  pct_atk  += mval
    elif _mid == 9:  add_cr   += mval
    elif _mid == 10: add_cd   += mval

    # Prefix (innate)
    _pid = PNAME_TO_ID.get((rune.get("prefix_stat_name") or "").strip())
    pval = float(rune.get("prefix_stat_value") or 0)
    if _pid == 3:    flat_atk += pval
    elif _pid == 4:  pct_atk  += pval
    elif _pid == 9:  add_cr   += pval
    elif _pid == 10: add_cd   += pval

    # Substats: sec_eff [[stat_id, base, enchanted, grind], ...]
    _STAT_ID_NAME = {3: "ATK+", 4: "ATK%", 9: "CR%", 10: "CD%"}
    raw = rune.get("sec_eff")
    if raw:
        try:
            subs = _json.loads(raw) if isinstance(raw, str) else raw
            for sub in (subs or []):
                if not sub or len(sub) < 2:
                    continue
                sid = sub[0]
                val = float(sub[1] or 0) + float(sub[3] if len(sub) >= 4 else 0)
                sname = _STAT_ID_NAME.get(sid)
                if sname == "ATK+":   flat_atk += val
                elif sname == "ATK%": pct_atk  += val
                elif sname == "CR%":  add_cr   += val
                elif sname == "CD%":  add_cd   += val
        except Exception:
            pass

    # EO delta from each stat type
    delta_flat = flat_atk * base_eo_mult
    delta_pct  = (ref_atk * pct_atk / 100.0) * base_eo_mult
    # CR only valuable below 100% — weight it less if already near cap
    cr_headroom = max(0.0, 100.0 - ref_cr) / 100.0
    delta_cr   = ref_atk * (add_cr / 100.0) * (cd_factor - 1.0) * cr_headroom
    delta_cd   = ref_atk * cr_factor * (add_cd / 100.0)

    return delta_flat + delta_pct + delta_cr + delta_cd
