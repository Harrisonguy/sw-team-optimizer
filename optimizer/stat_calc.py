"""
Stat calculation utilities for the SW Team Rune Optimizer.
"""
from __future__ import annotations

from src.core.account.account_model import Rune, Monster

# ── Stat ID constants ────────────────────────────────────────────────────────
HP_FLAT  = 1
HP_PCT   = 2
ATK_FLAT = 3
ATK_PCT  = 4
DEF_FLAT = 5
DEF_PCT  = 6
SPD      = 8
CR       = 9
CD       = 10
RES      = 11
ACC      = 12

ALL_STAT_IDS = [HP_FLAT, HP_PCT, ATK_FLAT, ATK_PCT, DEF_FLAT, DEF_PCT,
                SPD, CR, CD, RES, ACC]

# stat_id -> index into ALL_STAT_IDS (for fast list-based stat totals)
STAT_ID_TO_IDX: dict[int, int] = {sid: i for i, sid in enumerate(ALL_STAT_IDS)}

# Human-readable stat key -> stat IDs that contribute to it
STAT_KEY_TO_IDS: dict[str, list[int]] = {
    "hp":  [HP_FLAT, HP_PCT],
    "atk": [ATK_FLAT, ATK_PCT],
    "def": [DEF_FLAT, DEF_PCT],
    "spd": [SPD],
    "cr":  [CR],
    "cd":  [CD],
    "res": [RES],
    "acc": [ACC],
}

# ── Set metadata ─────────────────────────────────────────────────────────────
FOUR_PIECE_SET_IDS: set[int] = {3, 5, 8, 10, 11, 13}
# set_id -> (stat_id, bonus_value)  None value = special-case Swift (+25% base spd)
SET_BONUSES = {
    1:  (HP_PCT,   15),
    2:  (DEF_PCT,  15),
    3:  (SPD,      None),
    4:  (CR,       12),
    5:  (CD,       40),
    6:  (ACC,      20),
    7:  (RES,      20),
    8:  (ATK_PCT,  35),
    10: None,
    11: None,
    13: None,
    14: None,
    15: None,
    16: None,
    17: None,
    18: None,
    19: (ATK_PCT,   8),
    20: (DEF_PCT,   8),
    21: (HP_PCT,    8),
    22: (ACC,      10),
    23: (RES,      10),
    24: None,
    25: None,
}


def extract_rune_stats(rune: Rune) -> dict[int, float]:
    """Extract all stats from a rune: main + innate/prefix + substats + grinds."""
    stats: dict[int, float] = {sid: 0.0 for sid in ALL_STAT_IDS}

    if rune.pri_eff and len(rune.pri_eff) >= 2:
        sid, val = rune.pri_eff[0], rune.pri_eff[1]
        if sid in stats:
            stats[sid] += val

    if rune.prefix_eff and len(rune.prefix_eff) >= 2:
        sid, val = rune.prefix_eff[0], rune.prefix_eff[1]
        if sid in stats and sid != 0 and val != 0:
            stats[sid] += val

    for sub in (rune.sec_eff or []):
        if sub and len(sub) >= 2:
            sid   = sub[0]
            val   = sub[1]
            grind = sub[3] if len(sub) >= 4 else 0
            if sid in stats:
                stats[sid] += val + grind

    return stats


def calc_set_bonuses(set_counts: dict[int, int], base_speed: int) -> dict[int, float]:
    """Return stat bonuses from active rune sets given set piece counts."""
    bonus: dict[int, float] = {sid: 0.0 for sid in ALL_STAT_IDS}

    for set_id, count in set_counts.items():
        piece_size  = 4 if set_id in FOUR_PIECE_SET_IDS else 2
        activations = count // piece_size
        if activations == 0:
            continue
        bonus_data = SET_BONUSES.get(set_id)
        if bonus_data is None:
            continue
        stat_id, value = bonus_data
        if stat_id == SPD and value is None:
            # Swift rounds UP in-game (e.g. base 101 -> +26)
            import math as _math
            bonus[SPD] += _math.ceil(base_speed * 0.25) * activations
        elif value is not None:
            bonus[stat_id] += value * activations

    return bonus


def calc_final_stats(
    monster: Monster,
    rune_stat_totals: dict[int, float],
    set_counts: dict[int, int],
) -> dict[str, int]:
    """Compute final in-game stats for a monster with the given rune stat totals."""
    base_hp  = monster.max_lvl_hp      or 0
    base_atk = monster.max_lvl_attack  or 0
    base_def = monster.max_lvl_defense or 0
    base_spd = monster.base_speed      or 100
    base_cr  = monster.crit_rate       or 15
    base_cd  = monster.crit_damage     or 50
    base_res = monster.resistance      or 15
    base_acc = monster.accuracy        or 0

    sb = calc_set_bonuses(set_counts, base_spd)

    hp_pct  = rune_stat_totals.get(HP_PCT,  0) + sb.get(HP_PCT,  0)
    atk_pct = rune_stat_totals.get(ATK_PCT, 0) + sb.get(ATK_PCT, 0)
    def_pct = rune_stat_totals.get(DEF_PCT, 0) + sb.get(DEF_PCT, 0)

    return {
        "hp":       int(base_hp  * (1 + hp_pct  / 100) + rune_stat_totals.get(HP_FLAT,  0)),
        "atk":      int(base_atk * (1 + atk_pct / 100) + rune_stat_totals.get(ATK_FLAT, 0)),
        "def":      int(base_def * (1 + def_pct / 100) + rune_stat_totals.get(DEF_FLAT, 0)),
        "spd":      int(base_spd + rune_stat_totals.get(SPD, 0) + sb.get(SPD, 0)),
        "cr":       min(100, int(base_cr  + rune_stat_totals.get(CR,  0) + sb.get(CR,  0))),
        "cd":       int(base_cd  + rune_stat_totals.get(CD,  0) + sb.get(CD,  0)),
        "res":      min(100, int(base_res + rune_stat_totals.get(RES, 0) + sb.get(RES, 0))),
        "acc":      min(100, int(base_acc + rune_stat_totals.get(ACC, 0) + sb.get(ACC, 0))),
        "base_hp":  base_hp,
        "base_atk": base_atk,
        "base_def": base_def,
        "base_spd": base_spd,
        "base_cr":  base_cr,
        "base_cd":  base_cd,
        "base_res": base_res,
        "base_acc": base_acc,
    }
