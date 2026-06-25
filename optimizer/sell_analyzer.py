"""
Rune sell analysis for the SW Team Rune Optimizer.

Provides:
  - rune efficiency scoring  (0-100 scale)
  - sell candidate identification
  - in-game Sell Exclusion Rule generation (5 rules for SW's UI)
"""
from __future__ import annotations

from collections import defaultdict
from src.core.account.account_model import Rune
from src.core.runes.rune_decode import rune_stars_from_class

# ---- Per-roll maximums for each stat at 6-star Legendary --------------------
# Source: SW wiki community-established efficiency tables.
# Stat IDs: 1=HP+, 2=HP%, 3=ATK+, 4=ATK%, 5=DEF+, 6=DEF%,
#           8=SPD,  9=CR,  10=CD, 11=RES, 12=ACC
MAX_PER_ROLL: dict[int, float] = {
    1: 500.0,   # HP+
    2:   8.0,   # HP%
    3:  40.0,   # ATK+
    4:   8.0,   # ATK%
    5:  40.0,   # DEF+
    6:   8.0,   # DEF%
    8:   6.0,   # SPD
    9:   6.0,   # CR
    10:  7.0,   # CD
    11:  8.0,   # RES
    12:  8.0,   # ACC
}

# Max total roll-ups per rune (5 upgrade ticks: +3/+6/+9/+12/+15)
MAX_ROLLS = 5.0

# How desirable each sub-stat is (1.0 = best, lower = less wanted)
STAT_DESIRABILITY: dict[int, float] = {
    8:  1.00,   # SPD
    9:  0.90,   # CR
    10: 0.90,   # CD
    4:  0.80,   # ATK%
    2:  0.70,   # HP%
    6:  0.70,   # DEF%
    12: 0.60,   # ACC
    11: 0.60,   # RES
    3:  0.15,   # ATK+
    1:  0.10,   # HP+
    5:  0.10,   # DEF+
}

STAT_ID_TO_KEY: dict[int, str] = {
    1: "HP+", 2: "HP%", 3: "ATK+", 4: "ATK%",
    5: "DEF+", 6: "DEF%", 8: "SPD", 9: "CR",
    10: "CD", 11: "RES", 12: "ACC",
}

# ---- Flat stat IDs (HP+, ATK+, DEF+) ----------------------------------------
# Used to detect instant-sell main stats on even slots.
_FLAT_STAT_IDS: frozenset[int] = frozenset({1, 3, 5})

# ---- Per-slot forbidden substats --------------------------------------------
# These stats physically cannot roll as a substat on the given slot.
# Slot 1 (ATK+ main): no DEF+/DEF%  -- offensive slot, defensive flat banned
# Slot 3 (DEF+ main): no ATK+/ATK%  -- defensive slot, offensive flat banned
# Slot 5 (HP+ main):  only the main stat (HP+) is forbidden, handled generically
# stat IDs: 1=HP+, 2=HP%, 3=ATK+, 4=ATK%, 5=DEF+, 6=DEF%
_SLOT_FORBIDDEN_SUBS: dict[int, frozenset[int]] = {
    1: frozenset({5, 6}),   # no DEF+, no DEF%
    3: frozenset({3, 4}),   # no ATK+, no ATK%
}

# ---- Set tier multipliers ---------------------------------------------------
# Higher-tier sets need weaker subs to be worth keeping.
# Scores are multiplied by the tier multiplier before grading.
#
# Tier 1  Violent, Swift, Will, Rage, Blade     -- most sought after
# Tier 2  Despair, Vampire, Fight, Fatal         -- good situational
# Tier 3  Destroy, Nemesis, Revenge, Focus       -- niche / mediocre
# Tier 4  Everything else (Energy, Guard, etc.)  -- usually weak
_SET_TIER: dict[str, int] = {
    "Violent": 1, "Swift": 1, "Will": 1, "Rage": 1, "Blade": 1,
    "Despair": 2, "Vampire": 2, "Fight": 2, "Fatal": 2,
    "Destroy": 3, "Nemesis": 3, "Revenge": 3, "Focus": 3, "Shield": 3,
}

_SET_MULT: dict[int, float] = {
    1: 1.00,   # Tier 1: no adjustment
    2: 0.92,   # Tier 2: slight reduction
    3: 0.82,   # Tier 3: moderate reduction
    4: 0.68,   # Tier 4: significant reduction (Energy, Guard, Endure, Shield, etc.)
}

# ---- Slot-specific main stat scoring ----------------------------------------
# Per the SW wiki, odd slots (1,3,5) have a fixed flat main stat -- there is
# no choice and no quality dimension to the main stat on those slots.
# Even slots (2,4,6) offer a range of main stats.  A percentage or SPD main is
# far more impactful than a flat main, so we factor this into desirability.
#
# Values are 0-100 (100 = best possible main for that slot).
# Slots 1/3/5 are not in this table; they use pure sub-stat scoring.
#
# Note: flat mains (HP+/ATK+/DEF+) on even slots are overridden to grade D
# before this table is consulted, so their numeric values here are moot.
_MAIN_SCORE: dict[int, dict[int, int]] = {
    2: {
        8:  100,   # SPD  (best slot-2 main)
        2:   90,   # HP%
        4:   90,   # ATK%
        6:   80,   # DEF%
        1:    0,   # HP+  (flat -- instant sell, overridden before this is used)
        3:    0,   # ATK+ (flat)
        5:    0,   # DEF+ (flat)
    },
    4: {
        10: 100,   # CRI Dmg%
        9:   95,   # CRI Rate%
        4:   88,   # ATK%
        2:   72,   # HP%
        6:   72,   # DEF%
        1:    0,   # HP+  (flat -- instant sell)
        3:    0,   # ATK+ (flat)
        5:    0,   # DEF+ (flat)
    },
    6: {
        4:  100,   # ATK%  (best slot-6 main for offense)
        2:   90,   # HP%
        6:   85,   # DEF%
        12:  72,   # ACC%
        11:  20,   # RES%  (user: "for the most part" sell on slot-6; low but not 0)
        1:    0,   # HP+  (flat -- instant sell)
        3:    0,   # ATK+ (flat)
        5:    0,   # DEF+ (flat)
    },
}

# Weight split between sub-stat quality and main-stat quality for even slots.
_SUB_WEIGHT  = 0.75
_MAIN_WEIGHT = 0.25

# ---- Max single-roll increase per upgrade tick at 6-star --------------------
# Used to project a rune's maximum possible value at +15.
# Source: SW wiki per-level sub-stat range for 6-star runes.
MAX_ROLL_PER_UPGRADE: dict[int, float] = {
    1: 375.0,   # HP+
    2:   8.0,   # HP%
    3:  20.0,   # ATK+
    4:   8.0,   # ATK%
    5:  20.0,   # DEF+
    6:   8.0,   # DEF%
    8:   6.0,   # SPD
    9:   6.0,   # CR
    10:  7.0,   # CD
    11:  8.0,   # RES
    12:  8.0,   # ACC
}


# ---- Rune scoring -----------------------------------------------------------

def score_rune(rune: Rune) -> dict:
    """
    Score a single rune.  Returns a dict with:
        rune_id, slot, set, set_id, stars, type, upgrade,
        main, prefix, subs,
        efficiency    (0-100, raw sub-stat quality),
        desirability  (0-100, weighted by stat importance + main stat quality
                       + set tier multiplier),
        grade         ('S' / 'A' / 'B' / 'C' / 'D'),
        sub_details   list of {stat, value, pct}

    Scoring notes
    -------------
    efficiency    = how much of the theoretical maximum sub-stat value is
                    achieved (pure quantity, no weighting).
    desirability  = how valuable the rune is in practice:
                    - For odd slots (1,3,5): sub-stat quality only.
                    - For even slots (2,4,6): 75% sub-stat quality +
                      25% main stat quality, except that a flat main
                      (HP+/ATK+/DEF+) is an instant sell (grade D).
                    - Final score is multiplied by the set tier multiplier
                      so lower-value sets produce lower grades.
    """
    raw_eff  = 0.0
    weighted = 0.0
    sub_details: list[dict] = []

    for sub in (rune.sec_eff or []):
        if not sub or len(sub) < 2:
            continue
        sid   = sub[0]
        val   = sub[1] + (sub[3] if len(sub) >= 4 else 0)   # base + grind
        max_v = MAX_PER_ROLL.get(sid, 1.0) * MAX_ROLLS
        eff   = val / max_v if max_v > 0 else 0.0

        raw_eff  += eff
        weighted += eff * STAT_DESIRABILITY.get(sid, 0.3)
        sub_details.append({
            "stat":  STAT_ID_TO_KEY.get(sid, "?" + str(sid)),
            "value": val,
            "pct":   round(eff * 100, 1),
        })

    # Normalise sub-stat quality to 0-100 (4 perfectly rolled subs = 100)
    eff_score  = min(100.0, raw_eff  / 4 * 100)
    sub_desr   = min(100.0, weighted / 4 * 100)

    slot    = rune.slot_no or 0
    main_id = rune.pri_eff[0] if (rune.pri_eff and len(rune.pri_eff) >= 1) else None

    # ---- Instant sell: flat main on even slot -------------------------------
    # HP+, ATK+, or DEF+ as the main stat on slots 2/4/6 is always garbage.
    # Grade D regardless of how good the substats are.
    if slot in (2, 4, 6) and main_id in _FLAT_STAT_IDS:
        return {
            "rune_id":      rune.rune_id,
            "slot":         slot,
            "set":          rune.set_name,
            "set_id":       rune.set_id,
            "stars":        rune.stars_label,
            "type":         rune.rune_type,
            "upgrade":      rune.upgrade_curr,
            "main":         rune.main_stat_label,
            "prefix":       rune.prefix_stat_label if rune.prefix_stat_label != "No prefix" else "",
            "subs":         rune.substat_labels,
            "efficiency":   round(eff_score,  1),
            "desirability": 3.0,
            "grade":        "D",
            "sub_details":  sub_details,
        }

    # ---- Main stat quality for even slots -----------------------------------
    if slot in _MAIN_SCORE and main_id is not None:
        main_score = float(_MAIN_SCORE[slot].get(main_id, 50.0))
        desr_score = min(100.0, sub_desr * _SUB_WEIGHT + main_score * _MAIN_WEIGHT)
    else:
        desr_score = sub_desr

    # ---- Set tier multiplier ------------------------------------------------
    set_tier  = _SET_TIER.get(rune.set_name or "", 4)
    set_mult  = _SET_MULT.get(set_tier, 0.68)
    desr_score = round(desr_score * set_mult, 1)

    if   desr_score >= 75: grade = "S"
    elif desr_score >= 55: grade = "A"
    elif desr_score >= 35: grade = "B"
    elif desr_score >= 20: grade = "C"
    else:                  grade = "D"

    return {
        "rune_id":      rune.rune_id,
        "slot":         rune.slot_no,
        "set":          rune.set_name,
        "set_id":       rune.set_id,
        "stars":        rune.stars_label,
        "type":         rune.rune_type,
        "upgrade":      rune.upgrade_curr,
        "main":         rune.main_stat_label,
        "prefix":       rune.prefix_stat_label if rune.prefix_stat_label != "No prefix" else "",
        "subs":         rune.substat_labels,
        "efficiency":   round(eff_score,  1),
        "desirability": desr_score,
        "grade":        grade,
        "sub_details":  sub_details,
    }


def compute_projected_desirability(
    sec_eff_list: list,
    upgrade_curr: int,
    slot_no: int,
    main_stat_id: int | None,
    set_name: str,
) -> float:
    """
    Project the maximum desirability this rune could reach at +15.

    Assumes the best case: all remaining upgrade ticks go to the most valuable
    known sub-stat at the maximum possible roll value.  This is optimistic by
    design -- if even the best case cannot reach the account bar, the rune is
    definitely below the bar and should be sold.

    Parameters
    ----------
    sec_eff_list  Raw sec_eff list already parsed from JSON.
    upgrade_curr  Current rune upgrade level (0-15).
    slot_no       Rune slot (1-6).
    main_stat_id  Main stat integer ID, or None.
    set_name      Rune set name (e.g. 'Violent').

    Returns
    -------
    Projected desirability float (0-100), including set-tier multiplier.
    """
    # Substat rolls happen at +3/+6/+9/+12 only (4 total). The old formula
    # (15 - lvl) // 3 over-counted: 5 rolls at +0 and 1 roll at +12.
    remaining = sum(1 for t in (3, 6, 9, 12) if t > (upgrade_curr or 0))

    raw_eff  = 0.0
    weighted = 0.0

    forbidden = _SLOT_FORBIDDEN_SUBS.get(slot_no, frozenset())

    for sub in (sec_eff_list or []):
        if not sub or len(sub) < 2:
            continue
        sid = sub[0]
        # Skip stats that can't physically appear on this slot
        if sid in forbidden:
            continue
        val      = sub[1] + (sub[3] if len(sub) >= 4 else 0)
        # Best case: every remaining tick improves this sub at max roll
        proj_val = val + remaining * MAX_ROLL_PER_UPGRADE.get(sid, 0.0)
        max_v    = MAX_PER_ROLL.get(sid, 1.0) * MAX_ROLLS
        eff      = min(1.0, proj_val / max_v) if max_v > 0 else 0.0

        raw_eff  += eff
        weighted += eff * STAT_DESIRABILITY.get(sid, 0.3)

    sub_desr = min(100.0, weighted / 4 * 100)

    # Instant sell check (flat main on even slot)
    if slot_no in (2, 4, 6) and main_stat_id in _FLAT_STAT_IDS:
        return 3.0

    # Main stat quality
    if slot_no in _MAIN_SCORE and main_stat_id is not None:
        main_score = float(_MAIN_SCORE[slot_no].get(main_stat_id, 50.0))
        proj_desr  = min(100.0, sub_desr * _SUB_WEIGHT + main_score * _MAIN_WEIGHT)
    else:
        proj_desr = sub_desr

    # Set tier multiplier
    set_tier  = _SET_TIER.get(set_name or "", 4)
    set_mult  = _SET_MULT.get(set_tier, 0.68)
    return round(proj_desr * set_mult, 1)


def get_sell_candidates(
    all_runes: list[Rune],
    protected_rune_ids: set[int],
    min_stars: int       = 5,
    grade_threshold: str = "C",
    max_upgrade: int     = 9,
) -> list[dict]:
    """Return runes that are sell candidates, worst first."""
    GRADE_ORDER = {"D": 0, "C": 1, "B": 2, "A": 3, "S": 4}
    threshold_val = GRADE_ORDER.get(grade_threshold, 1)

    candidates: list[dict] = []
    for rune in all_runes:
        if rune.rune_id in protected_rune_ids:
            continue
        stars = rune_stars_from_class(rune.raw_class) or 0
        if stars < min_stars:
            continue
        if (rune.upgrade_curr or 0) > max_upgrade:
            continue

        scored = score_rune(rune)
        if GRADE_ORDER.get(scored["grade"], 0) <= threshold_val:
            candidates.append(scored)

    candidates.sort(key=lambda x: x["desirability"])
    return candidates


# ---- Exclusion rule generation ----------------------------------------------

def generate_exclusion_rules(all_runes: list[Rune]) -> list[dict]:
    """
    Analyse the rune pool and produce 5 sell exclusion rules tailored to the
    account's actual stat distribution.

    Each rule maps to one tab in SW's Sell Exclusion Settings:
        Keep rune if it has 2+ subs that meet the listed conditions.
    """
    stat_values: dict[int, list[float]] = defaultdict(list)
    for rune in all_runes:
        for sub in (rune.sec_eff or []):
            if not sub or len(sub) < 2:
                continue
            sid = sub[0]
            val = sub[1] + (sub[3] if len(sub) >= 4 else 0)
            if val > 0:
                stat_values[sid].append(val)

    def pct(sid: int, p: float) -> float:
        vals = sorted(stat_values.get(sid, [1.0]))
        idx  = max(0, min(int(len(vals) * p), len(vals) - 1))
        return vals[idx]

    spd_t  = max(4,  int(pct(8,  0.35)))
    cr_t   = max(4,  int(pct(9,  0.35)))
    cd_t   = max(5,  int(pct(10, 0.35)))
    atkp_t = max(5,  int(pct(4,  0.35)))
    hpp_t  = max(5,  int(pct(2,  0.35)))
    defp_t = max(5,  int(pct(6,  0.35)))
    acc_t  = max(5,  int(pct(12, 0.35)))
    res_t  = max(5,  int(pct(11, 0.35)))

    rules = [
        {
            "name":        "Speed + Offense",
            "tab":         1,
            "description": "Offense runes with speed -- core for most damage dealers",
            "subs_needed": 2,
            "conditions": [
                {"stat": "SPD",  "min": spd_t,  "label": "SPD >= "  + str(spd_t)},
                {"stat": "ATK%", "min": atkp_t, "label": "ATK% >= " + str(atkp_t) + "%"},
                {"stat": "CR",   "min": cr_t,   "label": "CR >= "   + str(cr_t)   + "%"},
                {"stat": "CD",   "min": cd_t,   "label": "CD >= "   + str(cd_t)   + "%"},
            ],
        },
        {
            "name":        "Speed + Tank",
            "tab":         2,
            "description": "Tanky runes with speed -- supports, bruisers, and utility",
            "subs_needed": 2,
            "conditions": [
                {"stat": "SPD",  "min": spd_t,  "label": "SPD >= "  + str(spd_t)},
                {"stat": "HP%",  "min": hpp_t,  "label": "HP% >= "  + str(hpp_t)  + "%"},
                {"stat": "DEF%", "min": defp_t, "label": "DEF% >= " + str(defp_t) + "%"},
            ],
        },
        {
            "name":        "Pure Crit",
            "tab":         3,
            "description": "High crit stats -- staple for all damage dealers",
            "subs_needed": 2,
            "conditions": [
                {"stat": "CR",   "min": cr_t,   "label": "CR >= "   + str(cr_t)   + "%"},
                {"stat": "CD",   "min": cd_t,   "label": "CD >= "   + str(cd_t)   + "%"},
                {"stat": "ATK%", "min": atkp_t, "label": "ATK% >= " + str(atkp_t) + "%"},
            ],
        },
        {
            "name":        "Defense / HP",
            "tab":         4,
            "description": "Pure tank runes -- healers, revivers, protectors",
            "subs_needed": 2,
            "conditions": [
                {"stat": "HP%",  "min": hpp_t,  "label": "HP% >= "  + str(hpp_t)  + "%"},
                {"stat": "DEF%", "min": defp_t, "label": "DEF% >= " + str(defp_t) + "%"},
                {"stat": "SPD",  "min": spd_t,  "label": "SPD >= "  + str(spd_t)},
            ],
        },
        {
            "name":        "Support / Utility",
            "tab":         5,
            "description": "Accuracy and resistance -- debuffers and supports",
            "subs_needed": 2,
            "conditions": [
                {"stat": "ACC",  "min": acc_t,  "label": "ACC >= " + str(acc_t) + "%"},
                {"stat": "RES",  "min": res_t,  "label": "RES >= " + str(res_t) + "%"},
                {"stat": "SPD",  "min": spd_t,  "label": "SPD >= " + str(spd_t)},
            ],
        },
    ]
    return rules
