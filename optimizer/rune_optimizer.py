"""Rune optimizer engine (target-driven beam search).

Given constraints (set requirements, main-stat requirements, target FINAL
stats) and a pool of candidate runes, finds builds that:

  1. Meet every stat target if possible (targets are evaluated on the
     monster's FINAL stats: base + runes + set bonuses + leader/building
     bonuses + artifact flat stats — exactly what you see in-game).
  2. If targets cannot be reached, get as CLOSE as possible (minimum total
     normalized shortfall), and report exactly which stats fell short.
  3. Never silently break a required set: builds with complete sets always
     rank above broken-set fallbacks, and `sets_complete` reports the truth.
  4. Respect optional max-stat caps (used by the team optimizer for speed
     tuning, e.g. "must stay slower than the slot before it").

Target key semantics
--------------------
  SPD / CR% / CD% / RES% / ACC%  — absolute final stat value
                                   (e.g. SPD 175 means final speed >= 175).
  HP% / ATK% / DEF%              — total % bonus over base from runes + sets
                                   (e.g. ATK% 100 means at least +100% ATK).

Algorithm
---------
1. Enumerate valid slot->set assignments for the required sets.
2. Per assignment, keep the top-K candidate runes per slot (ranked by a
   blend of base score and contribution toward unmet targets).
3. Beam search across slots 1..6, tracking accumulated stat vectors and
   incidental set completions.
4. Score each complete build on final stats: (targets met, sets complete,
   -shortfall, score) and return the top N unique builds.
"""
from __future__ import annotations

import json as _json
import math
from functools import lru_cache
from itertools import combinations
from typing import Callable, NamedTuple

class OptimizationCancelled(Exception):
    """Raised when a cooperative optimizer cancellation is requested."""


def _raise_if_cancelled(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is not None and cancel_check():
        raise OptimizationCancelled("Optimization cancelled")


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

ALL_SLOTS: tuple[int, ...] = (1, 2, 3, 4, 5, 6)

# stat_id -> short name used in target_stats keys
_STAT_ID_NAME: dict[int, str] = {
    1: "HP+", 2: "HP%", 3: "ATK+", 4: "ATK%", 5: "DEF+", 6: "DEF%",
    8: "SPD", 9: "CR%", 10: "CD%", 11: "RES%", 12: "ACC%",
}
_NAME_TO_STAT_ID = {v: k for k, v in _STAT_ID_NAME.items()}
# The DB importer stores names as 'Flat HP'/'CR'/'CD'/'RES'/'ACC' while the
# UI uses 'HP+'/'CR%'/'CD%'/'RES%'/'ACC%'. Accept both everywhere.
_NAME_TO_STAT_ID.update({
    "Flat HP": 1, "Flat ATK": 3, "Flat DEF": 5,
    "CR": 9, "CD": 10, "RES": 11, "ACC": 12,
})


def _canon_stat_id(name: str | None) -> int | None:
    """Stat name (either naming convention) -> stat id."""
    if not name:
        return None
    return _NAME_TO_STAT_ID.get(name.strip())

# Indices into the 11-float stat vector (matches stat ids 1..6, 8..12)
_VEC_IDX = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 8: 6, 9: 7, 10: 8, 11: 9, 12: 10}
_HPF, _HPP, _ATF, _ATP, _DFF, _DFP, _SPD, _CR, _CD, _RES, _ACC = range(11)

# Tuning knobs
TOP_K_PER_SLOT = 14
BEAM_WIDTH     = 500
_TARGET_WEIGHT = 220.0   # beam bonus per fully-satisfied target
_CAP_PENALTY   = 400.0   # beam penalty for blowing past a max-stat cap

# Default slot main-stat suggestions for weak-slot advice
_SLOT_FIXED_MAIN = {1: "ATK+", 3: "DEF+", 5: "HP+"}
_TGT_TO_MAIN = {
    "SPD": {2: "SPD"}, "CR%": {4: "CR%"}, "CD%": {4: "CD%"},
    "HP%": {2: "HP%", 4: "HP%", 6: "HP%"},
    "ATK%": {2: "ATK%", 4: "ATK%", 6: "ATK%"},
    "DEF%": {2: "DEF%", 4: "DEF%", 6: "DEF%"},
    "ACC%": {6: "ACC%"}, "RES%": {6: "RES%"},
}


# ---------------------------------------------------------------------------
# Rune stat vector helpers
# ---------------------------------------------------------------------------

def _rune_vec(rune: dict, projected: bool = False) -> tuple:
    """11-float vector of all stats on a rune (main + innate + subs + grinds).

    projected=True values the main stat at its deterministic +15 maximum
    (substats stay as-rolled). Cached on the rune dict ('_vec' / '_vec15').
    """
    cache_key = "_vec15" if projected else "_vec"
    cached = rune.get(cache_key)
    if cached is not None:
        return cached
    if projected:
        from optimizer.stat_utils import projected_main_value
        main_val = projected_main_value(rune)
    else:
        main_val = float(rune.get("main_stat_value") or 0)
    vec = [0.0] * 11
    # Main stat
    mid = rune.get("main_stat_id")
    if mid in _VEC_IDX:
        vec[_VEC_IDX[mid]] += main_val
    elif rune.get("main_stat_name") in _NAME_TO_STAT_ID:
        vec[_VEC_IDX[_NAME_TO_STAT_ID[rune["main_stat_name"]]]] += main_val
    # Prefix / innate (stored by name)
    pname = (rune.get("prefix_stat_name") or "").strip()
    if pname in _NAME_TO_STAT_ID:
        vec[_VEC_IDX[_NAME_TO_STAT_ID[pname]]] += float(rune.get("prefix_stat_value") or 0)
    # Substats: sec_eff = [[stat_id, base, enchanted, grind], ...]
    raw = rune.get("sec_eff")
    if raw:
        try:
            subs = _json.loads(raw) if isinstance(raw, str) else raw
            for sub in (subs or []):
                if not sub or len(sub) < 2:
                    continue
                sid = sub[0]
                if sid in _VEC_IDX:
                    val = float(sub[1] or 0) + float(sub[3] if len(sub) >= 4 else 0)
                    vec[_VEC_IDX[sid]] += val
        except Exception:
            pass
    t = tuple(vec)
    rune[cache_key] = t
    return t


def _sum_stat_from_rune(rune: dict, stat_name: str) -> float:
    """Total contribution of stat_name from one rune (kept for compat)."""
    sid = _NAME_TO_STAT_ID.get(stat_name)
    if sid is None:
        return 0.0
    return _rune_vec(rune)[_VEC_IDX[sid]]


# ---------------------------------------------------------------------------
# Set assignment helpers
# ---------------------------------------------------------------------------

def _expand_requirements(set_reqs: list[str]) -> list[str] | None:
    expanded: list[str] = []
    for s in set_reqs:
        expanded.extend([s] * SET_SIZE.get(s, 2))
    return expanded if len(expanded) <= 6 else None


@lru_cache(maxsize=128)
def _slot_assignments(req_pieces: tuple[str, ...]) -> list[dict[int, str | None]]:
    counts: dict[str, int] = {}
    for s in req_pieces:
        counts[s] = counts.get(s, 0) + 1
    sets_ordered = sorted(counts.items(), key=lambda x: -x[1])
    results: list[dict[int, str | None]] = []

    def backtrack(remaining_sets, available_slots, assignment):
        if not remaining_sets:
            full = dict(assignment)
            for fs in available_slots:
                full[fs] = None
            results.append(full)
            return
        set_name, count = remaining_sets[0]
        rest = remaining_sets[1:]
        for chosen_slots in combinations(available_slots, count):
            new_assignment = dict(assignment)
            for sl in chosen_slots:
                new_assignment[sl] = set_name
            new_available = [s for s in available_slots if s not in chosen_slots]
            backtrack(rest, new_available, new_assignment)

    backtrack(sets_ordered, list(ALL_SLOTS), {})
    return results


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class SlotResult(NamedTuple):
    slot_no:      int
    rune:         dict | None
    required_set: str | None
    is_upgrade:   bool


class BuildResult(NamedTuple):
    slots:           list[SlotResult]
    avg_desr:        float
    set_summary:     dict[str, int]
    stat_totals:     dict[str, int]      # summed rune contributions per target
    meets_targets:   bool
    final_stats:     dict | None = None  # full final stats (if monster known)
    target_report:   dict | None = None  # {stat: {"actual","target","met","miss"}}
    sets_complete:   bool = True
    weak_slot:       dict | None = None  # weakest-slot advice
    score:           float = 0.0
    assumed_max:     bool = False        # True = mains valued at +15 projection


# ---------------------------------------------------------------------------
# Final-stat math
# ---------------------------------------------------------------------------

def _set_stat_bonuses(set_counts: dict[str, int]) -> dict:
    """Aggregate set stat bonuses for COMPLETE sets only."""
    from optimizer.stat_utils import SET_STAT_BONUS
    out = {"hp_pct": 0.0, "atk_pct": 0.0, "def_pct": 0.0, "spd_pct": 0.0,
           "cr": 0.0, "cd": 0.0, "res": 0.0, "acc": 0.0}
    for sname, cnt in set_counts.items():
        need = SET_SIZE.get(sname, 2)
        b = SET_STAT_BONUS.get(sname)
        if not b or cnt < need:
            continue
        stat, btype, bval = b
        mult = cnt // need   # e.g. Energy x3
        if btype == "pct":
            out[stat + "_pct"] += bval * mult
        else:
            out[stat] += bval * mult
    return out


def _final_from_vec(
    monster_info: dict,
    vec,
    set_counts: dict[str, int],
    artifact_flat: dict | None,
    bonuses: dict | None,
) -> dict:
    """Final in-game stats from an accumulated rune-stat vector."""
    bb = bonuses or {}
    af = artifact_flat or {}
    base_hp  = float(monster_info.get("max_lvl_hp",      0) or 0)
    base_atk = float(monster_info.get("max_lvl_attack",  0) or 0)
    base_def = float(monster_info.get("max_lvl_defense", 0) or 0)
    base_spd = float(monster_info.get("base_speed",      0) or 0)
    base_cr  = float(monster_info.get("crit_rate",       0) or 0)
    base_cd  = float(monster_info.get("crit_damage",     0) or 0)
    base_res = float(monster_info.get("resistance",      0) or 0)
    base_acc = float(monster_info.get("accuracy",        0) or 0)

    sb = _set_stat_bonuses(set_counts)

    hp_pct  = vec[_HPP] + sb["hp_pct"]  + float(bb.get("hp_pct",  0))
    atk_pct = vec[_ATP] + sb["atk_pct"] + float(bb.get("atk_pct", 0))
    def_pct = vec[_DFP] + sb["def_pct"] + float(bb.get("def_pct", 0))
    spd_pct = sb["spd_pct"] + float(bb.get("spd_pct", 0))

    set_spd = math.ceil(base_spd * sb["spd_pct"] / 100) if sb["spd_pct"] else 0
    bb_spd  = int(base_spd * float(bb.get("spd_pct", 0)) / 100) if bb.get("spd_pct") else 0

    hp_final = int(base_hp  * (1 + hp_pct  / 100) + vec[_HPF] + float(af.get("hp",  0) or 0))
    atk_final = int(base_atk * (1 + atk_pct / 100) + vec[_ATF] + float(af.get("atk", 0) or 0))
    def_final = int(base_def * (1 + def_pct / 100) + vec[_DFF] + float(af.get("def", 0) or 0))
    return {
        "hp":   hp_final,
        "atk":  atk_final,
        "def_": def_final,
        "_hp_bonus":  int(hp_final - base_hp),
        "_atk_bonus": int(atk_final - base_atk),
        "_def_bonus": int(def_final - base_def),
        "spd":  int(base_spd + vec[_SPD] + set_spd + bb_spd),
        "_spd_bonus": int(vec[_SPD] + set_spd + bb_spd),
        "cr":   min(100.0, round(base_cr + vec[_CR] + sb["cr"] + float(bb.get("cr_add", 0)), 1)),
        "cd":   round(base_cd  + vec[_CD]  + sb["cd"]  + float(bb.get("cd_add",  0)), 1),
        # RES and ACC are capped at 100% in-game
        "res":  min(100.0, round(base_res + vec[_RES] + sb["res"] + float(bb.get("res_add", 0)), 1)),
        "acc":  min(100.0, round(base_acc + vec[_ACC] + sb["acc"] + float(bb.get("acc_add", 0)), 1)),
        # extra: rune+set pct bonuses (for HP%/ATK%/DEF% targets)
        "_hp_pct_total":  hp_pct,
        "_atk_pct_total": atk_pct,
        "_def_pct_total": def_pct,
    }


# Map target key -> (final_stats key, is_pct_bonus_semantics)
_TARGET_FINAL_KEY = {
    "SPD":  ("spd",  False),
    "CR%":  ("cr",   False),
    "CD%":  ("cd",   False),
    "RES%": ("res",  False),
    "ACC%": ("acc",  False),
    "HP%":  ("_hp_pct_total",  True),
    "ATK%": ("_atk_pct_total", True),
    "DEF%": ("_def_pct_total", True),
    # absolute fallbacks
    "HP":   ("hp",   False),
    "ATK":  ("atk",  False),
    "DEF":  ("def_", False),
}


def _target_report(final_stats: dict, targets: dict[str, float],
                   max_stats: dict[str, float] | None = None,
                   target_mode: str = "total") -> dict:
    """Per-target actual/target/met report.

    total mode compares against final in-game stats. bonus mode compares
    rune/set/bonus contribution for SPD and HP/ATK/DEF percentage targets,
    matching the green "+bonus" stat style shown in Summoners War.
    """
    report: dict = {}
    bonus_mode = target_mode == "bonus"
    for key, tval in (targets or {}).items():
        if not tval:
            continue
        fk = _TARGET_FINAL_KEY.get(key)
        if not fk:
            continue
        actual_key = fk[0]
        if bonus_mode and key == "SPD":
            actual = float(final_stats.get("_spd_bonus", 0) or 0)
        elif bonus_mode and key in ("HP", "ATK", "DEF"):
            actual = float(final_stats.get("_" + key.lower() + "_bonus", 0) or 0)
        elif bonus_mode and key in ("HP%", "ATK%", "DEF%"):
            actual = float(final_stats.get(actual_key, 0) or 0)
        else:
            actual = float(final_stats.get(actual_key, 0) or 0)
        miss = max(0.0, float(tval) - actual)
        report[key] = {"actual": round(actual, 1), "target": float(tval),
                       "met": miss <= 0, "miss": round(miss, 1),
                       "kind": "min", "mode": target_mode}
    for key, cval in (max_stats or {}).items():
        if cval is None:
            continue
        fk = _TARGET_FINAL_KEY.get(key)
        if not fk:
            continue
        actual = float(final_stats.get(fk[0], 0) or 0)
        over = max(0.0, actual - float(cval))
        report["max " + key] = {"actual": round(actual, 1), "target": float(cval),
                                "met": over <= 0, "miss": round(over, 1), "kind": "max"}
    return report


def _shortfall(report: dict) -> float:
    """Total normalized shortfall across all min targets and max caps."""
    total = 0.0
    for v in report.values():
        if v["target"] > 0:
            total += v["miss"] / v["target"]
    return total


# ---------------------------------------------------------------------------
# Weak-slot analysis
# ---------------------------------------------------------------------------

def analyze_weak_slot(build_slots: list[SlotResult], report: dict | None,
                      set_reqs: list[str]) -> dict | None:
    """Identify the weakest rune slot and recommend what to farm for it.

    Weakest = empty slot first, otherwise lowest desirability rune.
    The recommendation names the set, the main stat to look for, and which
    substats matter most given the unmet targets.
    """
    if not build_slots:
        return None
    # Pick weakest slot: empty first, then slots where the required set
    # could not be filled (most actionable), then lowest-quality rune.
    weak = None
    set_broken = False
    for sr in build_slots:
        if sr.rune is None:
            weak = sr
            break
    if weak is None:
        mismatched = [sr for sr in build_slots
                      if sr.required_set and sr.rune
                      and (sr.rune.get("set_name") or "") != sr.required_set]
        if mismatched:
            weak = min(mismatched,
                       key=lambda sr: float(sr.rune.get("desirability") or 0))
            set_broken = True
    if weak is None:
        weak = min(
            build_slots,
            key=lambda sr: float(sr.rune.get("desirability") or 0),
        )
    slot_no = weak.slot_no

    # Suggested set: the required set at that slot, else the largest req set
    sugg_set = weak.required_set
    if not sugg_set and set_reqs:
        sugg_set = sorted(set_reqs, key=lambda s: -SET_SIZE.get(s, 2))[0]

    # Unmet min targets, biggest relative miss first
    misses = sorted(
        [(k, v) for k, v in (report or {}).items()
         if v.get("kind") == "min" and not v["met"]],
        key=lambda kv: -(kv[1]["miss"] / kv[1]["target"] if kv[1]["target"] else 0),
    )
    miss_keys = [k for k, _ in misses]

    # Suggested main stat
    if slot_no in _SLOT_FIXED_MAIN:
        sugg_main = _SLOT_FIXED_MAIN[slot_no]
    else:
        sugg_main = None
        for mk in miss_keys:
            cand = _TGT_TO_MAIN.get(mk, {}).get(slot_no)
            if cand:
                sugg_main = cand
                break
        if sugg_main is None:
            # keep what the build uses now, else a sane default
            cur = (weak.rune or {}).get("main_stat_name")
            sugg_main = cur or {2: "SPD", 4: "CD%", 6: "HP%"}.get(slot_no, "?")

    # Suggested substats: unmet targets first, then universal value subs
    sugg_subs = [k for k in miss_keys if _TGT_TO_MAIN.get(k, {}).get(slot_no) != sugg_main][:3]
    for filler in ("SPD", "CR%", "CD%", "HP%"):
        if len(sugg_subs) >= 3:
            break
        if filler not in sugg_subs and filler != sugg_main:
            sugg_subs.append(filler)

    cur_desc = "empty"
    if weak.rune:
        r = weak.rune
        cur_desc = "%s %s+%s (desr %.0f%%)" % (
            r.get("set_name") or "?", r.get("main_stat_name") or "?",
            r.get("main_stat_value") or 0, float(r.get("desirability") or 0))

    return {
        "slot_no":        slot_no,
        "current":        cur_desc,
        "suggested_set":  sugg_set or "any high-quality set",
        "suggested_main": sugg_main,
        "suggested_subs": sugg_subs,
        "reason": ("no %s rune available for this slot" % weak.required_set)
                  if set_broken else
                  ("targets missed: " + ", ".join(miss_keys)) if miss_keys
                  else "lowest-quality rune in the build",
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def optimize(
    rune_pool:           list[dict],
    set_reqs:            list[str],
    current_build:       dict[int, dict],
    main_stat_constraints: dict[int, str] | None = None,
    target_stats:        dict[str, int] | None = None,
    top_n:               int = 5,
    scoring_mode:        str = "desirability",
    ref_atk:             float = 3000.0,
    ref_cr:              float = 85.0,
    ref_cd:              float = 200.0,
    monster_info:        dict | None = None,
    artifact_flat:       dict | None = None,
    extra_bonuses:       dict | None = None,
    max_stats:           dict[str, float] | None = None,
    top_k:               int = TOP_K_PER_SLOT,
    beam_width:          int = BEAM_WIDTH,
    assume_max:          bool = True,
    target_mode:         str = "total",
    cancel_check:        Callable[[], bool] | None = None,
    progress_callback:   Callable[[int, int, str], None] | None = None,
) -> list[BuildResult]:
    """Find the best builds satisfying constraints from rune_pool.

    When monster_info is provided, targets are evaluated against FINAL stats
    (base + runes + sets + extra_bonuses + artifact_flat). Without it, the
    legacy rune-contribution semantics are used.

    max_stats: optional {target_key: cap} upper bounds on final stats
    (used for speed tuning: keep a monster slower than another).

    assume_max=True values every under-leveled rune's MAIN stat at its
    deterministic +15 maximum, so the optimizer sees each rune's true
    potential (the displayed stats then assume those runes get upgraded).
    Substats are never projected — future rolls are random.
    """
    _raise_if_cancelled(cancel_check)
    msc = main_stat_constraints or {}
    tgt = {k: float(v) for k, v in (target_stats or {}).items() if v}
    mode = "bonus" if target_mode == "bonus" else "total"
    caps = {k: float(v) for k, v in (max_stats or {}).items() if v is not None}

    # ---- per-slot pools (main-stat filtered) ----
    by_slot: dict[int, list[dict]] = {s: [] for s in ALL_SLOTS}
    for r in rune_pool:
        slot = r.get("slot_no")
        if slot not in by_slot:
            continue
        required_main = msc.get(slot)
        if required_main:
            # compare by stat ID so 'CD%' (UI) matches 'CD' (DB) etc.
            want = _canon_stat_id(required_main)
            have = r.get("main_stat_id") or _canon_stat_id(r.get("main_stat_name"))
            if want is not None and have != want:
                continue
        by_slot[slot].append(r)

    # ---- base score per rune ----
    def _vec(r):
        return _rune_vec(r, assume_max)

    if scoring_mode == "effective_offense":
        from optimizer.stat_utils import eo_rune_score as _eo
        _eo_context = (
            bool(assume_max), round(float(ref_atk), 3),
            round(float(ref_cr), 3), round(float(ref_cd), 3),
        )
        def _base_score(r):
            cache = r.setdefault("_eo_score_cache", {})
            s = cache.get(_eo_context)
            if s is None:
                s = _eo(r, ref_atk, ref_cr, ref_cd, projected=assume_max)
                if len(cache) >= 16:
                    cache.pop(next(iter(cache)))
                cache[_eo_context] = s
            return float(s)
    else:
        def _base_score(r):
            return float(r.get("desirability") or 0)

    # ---- target-aware candidate ranking heuristic ----
    base_hp  = float((monster_info or {}).get("max_lvl_hp", 0) or 1)
    base_atk = float((monster_info or {}).get("max_lvl_attack", 0) or 1)
    base_def = float((monster_info or {}).get("max_lvl_defense", 0) or 1)

    def _tgt_contrib(vec, key: str) -> float:
        """A rune-vector's contribution toward one target key."""
        if key == "SPD":  return vec[_SPD]
        if key == "CR%":  return vec[_CR]
        if key == "CD%":  return vec[_CD]
        if key == "RES%": return vec[_RES]
        if key == "ACC%": return vec[_ACC]
        if key == "HP%":
            return vec[_HPP] + (vec[_HPF] / base_hp * 100 if monster_info else 0)
        if key == "ATK%":
            return vec[_ATP] + (vec[_ATF] / base_atk * 100 if monster_info else 0)
        if key == "DEF%":
            return vec[_DFP] + (vec[_DFF] / base_def * 100 if monster_info else 0)
        if key == "HP":
            return vec[_HPF] + (base_hp * vec[_HPP] / 100 if monster_info else 0)
        if key == "ATK":
            return vec[_ATF] + (base_atk * vec[_ATP] / 100 if monster_info else 0)
        if key == "DEF":
            return vec[_DFF] + (base_def * vec[_DFP] / 100 if monster_info else 0)
        return 0.0

    def _cand_rank(r) -> float:
        score = _base_score(r)
        vec = _vec(r)
        for key in tgt:
            score += 2.0 * _tgt_contrib(vec, key)
        return score

    for slot in ALL_SLOTS:
        by_slot[slot].sort(key=_cand_rank, reverse=True)

    # ---- set assignments ----
    req_pieces = _expand_requirements(set_reqs) if set_reqs else []
    if req_pieces is None:
        return []
    assignments = _slot_assignments(tuple(req_pieces)) if req_pieces else [
        {s: None for s in ALL_SLOTS}
    ]

    # ---- needed rune contribution per target (for beam guidance) ----
    def _needs_for_assignment(assignment) -> tuple[dict[str, float], float]:
        """Returns (needs, spd_fixed): how much rune contribution each target
        still needs assuming the assignment's required sets complete, and the
        monster's fixed (non-rune) speed — base + set% + leader/totem% —
        needed to evaluate SPD caps correctly."""
        req_counts: dict[str, int] = {}
        for s in assignment.values():
            if s:
                req_counts[s] = req_counts.get(s, 0) + 1
        sb = _set_stat_bonuses(req_counts)
        bb = extra_bonuses or {}
        mi = monster_info or {}
        _b = float(mi.get("base_speed", 0) or 0)
        spd_fixed = _b \
            + (math.ceil(_b * sb["spd_pct"] / 100) if sb["spd_pct"] else 0) \
            + (int(_b * float(bb.get("spd_pct", 0)) / 100) if bb.get("spd_pct") else 0)
        if not tgt:
            return {}, spd_fixed
        needs: dict[str, float] = {}
        for key, tval in tgt.items():
            if not monster_info:
                needs[key] = tval     # legacy: target = rune contribution
                continue
            if key == "SPD":
                needs[key] = tval if mode == "bonus" else max(0.0, tval - spd_fixed)
            elif key == "CR%":
                needs[key] = max(0.0, tval - float(mi.get("crit_rate", 0) or 0) - sb["cr"] - float(bb.get("cr_add", 0)))
            elif key == "CD%":
                needs[key] = max(0.0, tval - float(mi.get("crit_damage", 0) or 0) - sb["cd"] - float(bb.get("cd_add", 0)))
            elif key == "RES%":
                needs[key] = max(0.0, tval - float(mi.get("resistance", 0) or 0) - sb["res"] - float(bb.get("res_add", 0)))
            elif key == "ACC%":
                needs[key] = max(0.0, tval - float(mi.get("accuracy", 0) or 0) - sb["acc"] - float(bb.get("acc_add", 0)))
            elif key == "HP%":
                needs[key] = max(0.0, tval - sb["hp_pct"] - float(bb.get("hp_pct", 0)))
            elif key == "ATK%":
                needs[key] = max(0.0, tval - sb["atk_pct"] - float(bb.get("atk_pct", 0)))
            elif key == "DEF%":
                needs[key] = max(0.0, tval - sb["def_pct"] - float(bb.get("def_pct", 0)))
            elif key == "HP":
                fixed = 0.0 if mode == "bonus" else float(mi.get("max_lvl_hp", 0) or 0)
                fixed += float(mi.get("max_lvl_hp", 0) or 0) * (sb["hp_pct"] + float(bb.get("hp_pct", 0))) / 100
                fixed += float((artifact_flat or {}).get("hp", 0) or 0)
                needs[key] = max(0.0, tval - fixed)
            elif key == "ATK":
                fixed = 0.0 if mode == "bonus" else float(mi.get("max_lvl_attack", 0) or 0)
                fixed += float(mi.get("max_lvl_attack", 0) or 0) * (sb["atk_pct"] + float(bb.get("atk_pct", 0))) / 100
                fixed += float((artifact_flat or {}).get("atk", 0) or 0)
                needs[key] = max(0.0, tval - fixed)
            elif key == "DEF":
                fixed = 0.0 if mode == "bonus" else float(mi.get("max_lvl_defense", 0) or 0)
                fixed += float(mi.get("max_lvl_defense", 0) or 0) * (sb["def_pct"] + float(bb.get("def_pct", 0))) / 100
                fixed += float((artifact_flat or {}).get("def", 0) or 0)
                needs[key] = max(0.0, tval - fixed)
            else:
                needs[key] = tval
        return needs, spd_fixed

    spd_cap = caps.get("SPD")

    # ---- beam search per assignment ----
    # state = (neg_rank, vec(list), set_counts(dict), score, runes(list), broken(bool))
    completed: list[tuple] = []   # (meets, sets_complete, shortfall, score, slots, set_counts, vec)

    total_steps = max(1, len(assignments) * len(ALL_SLOTS))
    if progress_callback is not None:
        progress_callback(0, total_steps, "Preparing rune candidates")
    for assignment_index, assignment in enumerate(assignments):
        _raise_if_cancelled(cancel_check)
        needs, spd_fixed = _needs_for_assignment(assignment)

        # Per-slot candidate lists for this assignment
        slot_cands: dict[int, list[tuple[dict, bool]]] = {}
        feasible = True
        for slot_no in ALL_SLOTS:
            req_set = assignment.get(slot_no)
            if req_set:
                cands = [(r, False) for r in by_slot[slot_no]
                         if r.get("set_name") == req_set][:top_k]
                if not cands:
                    # broken-set fallback (clearly marked)
                    cands = [(r, True) for r in by_slot[slot_no][:top_k]]
                    if not cands:
                        feasible = False
                        break
            else:
                cands = [(r, False) for r in by_slot[slot_no][:top_k]]
                if not cands:
                    cands = [(None, False)]   # allow an empty free slot
            slot_cands[slot_no] = cands
        if not feasible:
            continue

        states: list[tuple] = [([0.0] * 11, {}, 0.0, [], False, set())]
        for slot_index, slot_no in enumerate(ALL_SLOTS):
            _raise_if_cancelled(cancel_check)
            new_states: list[tuple] = []
            for state_index, (vec, scounts, score, runes, broken, used) in enumerate(states):
                if state_index % 32 == 0:
                    _raise_if_cancelled(cancel_check)
                for r, is_broken in slot_cands[slot_no]:
                    if r is not None and r["rune_id"] in used:
                        continue
                    if r is not None:
                        rv = _vec(r)
                        nvec = [vec[i] + rv[i] for i in range(11)]
                        sn = (r.get("set_name") or "").strip()
                        nsc = dict(scounts)
                        if sn:
                            nsc[sn] = nsc.get(sn, 0) + 1
                        nscore = score + _base_score(r)
                        nused = used | {r["rune_id"]}
                    else:
                        nvec, nsc, nscore, nused = list(vec), dict(scounts), score, used
                    new_states.append((nvec, nsc, nscore,
                                       runes + [(slot_no, r, assignment.get(slot_no))],
                                       broken or is_broken, nused))

            # rank partial states: score + progress toward targets - cap excess
            def _state_key(st):
                vec, _, score, _, broken, _ = st
                val = score - (50.0 if broken else 0.0)
                for key, need in needs.items():
                    if need > 0:
                        val += _TARGET_WEIGHT * min(1.0, _tgt_contrib(vec, key) / need)
                if spd_cap is not None and monster_info:
                    # headroom = cap minus ALL non-rune speed (base + set% +
                    # leader/totem%), otherwise Swift builds blow past the cap
                    room = spd_cap - spd_fixed
                    if vec[_SPD] > room:
                        val -= _CAP_PENALTY * (vec[_SPD] - room) / max(room, 1.0)
                return val

            new_states.sort(key=_state_key, reverse=True)
            states = new_states[:beam_width]
            if progress_callback is not None:
                progress_callback(
                    assignment_index * len(ALL_SLOTS) + slot_index + 1,
                    total_steps,
                    "Searching rune combinations",
                )

        # ---- finalize builds for this assignment ----
        for vec, scounts, score, runes, broken, _used in states[:max(top_n * 8, 24)]:
            slots = [SlotResult(slot_no=sn, rune=r, required_set=rq,
                                is_upgrade=_is_upgrade(r, current_build.get(sn)))
                     for sn, r, rq in runes]
            if monster_info:
                fstats = _final_from_vec(monster_info, vec, scounts,
                                         artifact_flat, extra_bonuses)
                report = _target_report(fstats, tgt, caps, mode)
            else:
                fstats = None
                report = {}
                for key, tval in tgt.items():
                    actual = _tgt_contrib(vec, key)
                    miss = max(0.0, tval - actual)
                    report[key] = {"actual": round(actual, 1), "target": tval,
                                   "met": miss <= 0, "miss": round(miss, 1),
                                   "kind": "min"}
            meets = all(v["met"] for v in report.values()) if report else True
            sf = _shortfall(report)
            completed.append((meets, not broken, sf, score, slots, scounts, vec,
                              fstats, report))

    _raise_if_cancelled(cancel_check)
    if not completed:
        return []

    # ---- rank: sets complete > targets met > smallest shortfall > score ----
    # The requested set is a hard requirement (Violent procs, Will immunity
    # etc. are usually non-negotiable); stat targets degrade gracefully to
    # "as close as possible".
    completed.sort(key=lambda c: (not c[1], not c[0], c[2], -c[3]))

    seen: set[tuple] = set()
    out: list[BuildResult] = []
    for meets, sets_ok, sf, score, slots, scounts, vec, fstats, report in completed:
        key = tuple(sr.rune["rune_id"] if sr.rune else None for sr in slots)
        if key in seen:
            continue
        seen.add(key)

        total_desr = sum(float(sr.rune.get("desirability") or 0)
                         for sr in slots if sr.rune)
        stat_totals = {k: int(round(_tgt_contrib(vec, k))) for k in tgt}
        weak = analyze_weak_slot(slots, report, set_reqs)

        out.append(BuildResult(
            slots         = slots,
            avg_desr      = round(total_desr / 6, 1),
            set_summary   = dict(scounts),
            stat_totals   = stat_totals,
            meets_targets = meets,
            final_stats   = fstats,
            target_report = report,
            sets_complete = sets_ok,
            weak_slot     = weak,
            score         = round(score, 1),
            assumed_max   = assume_max,
        ))
        if len(out) >= top_n:
            break
    return out


def _is_upgrade(rune: dict | None, current_rune: dict | None) -> bool:
    if not rune:
        return False
    cur = float((current_rune or {}).get("desirability") or 0)
    return float(rune.get("desirability") or 0) > cur
