"""
Core beam-search optimization engine for the SW Team Rune Optimizer.

Algorithm overview
──────────────────
For each monster (processed in priority order so earlier monsters get
first pick of the rune pool):

  1. Group available runes by slot and quick-score them for this monster's
     stat targets. Keep the top TOP_K candidates per slot.

  2. Run a beam search across slots 1→6:
       • For each (partial_build, rune_to_add) pair, update cumulative
         rune-stat totals and set counts.
       • Prune states where remaining slots can no longer satisfy the
         required set counts.
       • Keep the top BEAM_WIDTH partial states at each step.

  3. After the beam search, pick the complete build with the highest
     final score.  If no build meets all minimums, return the best attempt
     anyway (the UI will highlight which targets were missed).

  4. Remove the 6 assigned runes from the shared pool before the next
     monster.
"""
from __future__ import annotations

from src.core.account.account_model import Rune, Monster
from optimizer.stat_calc import (
    extract_rune_stats,
    calc_final_stats,
    STAT_KEY_TO_IDS,
    FOUR_PIECE_SET_IDS,
    ALL_STAT_IDS,
    STAT_ID_TO_IDX,
    HP_PCT, ATK_PCT, DEF_PCT,
)

# ── Tuning knobs ─────────────────────────────────────────────────────────────
TOP_K      = 60    # rune candidates kept per slot after quick-scoring
BEAM_WIDTH = 2000  # partial states kept between each slot step


# ── Scoring helpers ──────────────────────────────────────────────────────────

def _monster_bases(monster: Monster) -> tuple[dict, float, float, float]:
    """Return (base_by_key, base_hp, base_atk, base_def) for a monster."""
    bh = monster.max_lvl_hp      or 1
    ba = monster.max_lvl_attack  or 1
    bd = monster.max_lvl_defense or 1
    return (
        {
            "hp":  monster.max_lvl_hp      or 0,
            "atk": monster.max_lvl_attack  or 0,
            "def": monster.max_lvl_defense or 0,
            "spd": monster.base_speed      or 0,
            "cr":  monster.crit_rate       or 0,
            "cd":  monster.crit_damage     or 0,
            "res": monster.resistance      or 0,
            "acc": monster.accuracy        or 0,
        },
        bh, ba, bd,
    )


def _quick_score(rune: Rune, targets: dict, monster: Monster | None = None) -> float:
    """
    Single-rune heuristic used to pre-filter candidates.

    Targets are treated as *final* values (base + runes).  When a monster is
    supplied the scoring accounts for base stats so that percentage stats
    (HP%/ATK%/DEF%) are properly valued relative to the remaining deficit.
    """
    rune_stats = extract_rune_stats(rune)
    score = 0.0

    if monster is not None:
        base_by_key, bh, ba, bd = _monster_bases(monster)
    else:
        base_by_key, bh, ba, bd = {}, 1, 1, 1

    for stat_key, t in targets.items():
        min_val = t.get("min", 0)
        if min_val <= 0:
            continue
        # How much still needs to come from runes
        effective_min = max(1.0, min_val - base_by_key.get(stat_key, 0))
        for sid in STAT_KEY_TO_IDS.get(stat_key, []):
            raw = rune_stats.get(sid, 0)
            # Convert percentage stats to flat-HP/ATK/DEF equivalent
            if   sid == HP_PCT:  contrib = raw * bh / 100.0
            elif sid == ATK_PCT: contrib = raw * ba / 100.0
            elif sid == DEF_PCT: contrib = raw * bd / 100.0
            else:                contrib = raw
            score += contrib / effective_min
    return score


def _build_score_coeffs(targets: dict, monster: Monster | None = None) -> list[float]:
    """
    Pre-compute a coefficient vector (aligned to ALL_STAT_IDS) so that
    partial scoring is a single dot-product in the inner beam loop.

    When monster is supplied, coefficients reflect the remaining rune deficit
    after base stats and properly weight % stats by the monster's base values.
    """
    if monster is not None:
        base_by_key, bh, ba, bd = _monster_bases(monster)
    else:
        base_by_key, bh, ba, bd = {}, 1, 1, 1

    coeffs = [0.0] * len(ALL_STAT_IDS)
    for stat_key, t in targets.items():
        min_val = t.get("min", 0)
        if min_val <= 0:
            continue
        effective_min = max(1.0, min_val - base_by_key.get(stat_key, 0))
        for sid in STAT_KEY_TO_IDS.get(stat_key, []):
            idx = STAT_ID_TO_IDX.get(sid)
            if idx is None:
                continue
            if   sid == HP_PCT:  coeffs[idx] += (bh / 100.0) / effective_min
            elif sid == ATK_PCT: coeffs[idx] += (ba / 100.0) / effective_min
            elif sid == DEF_PCT: coeffs[idx] += (bd / 100.0) / effective_min
            else:                coeffs[idx] += 1.0 / effective_min
    return coeffs


def _partial_score(stat_totals: list, coeffs: list[float]) -> float:
    """Fast dot-product score for a partial build."""
    return sum(a * b for a, b in zip(stat_totals, coeffs))


def _final_score(stats: dict, targets: dict) -> float:
    """
    Full score for a completed 6-rune build.
    Adds a large bonus when ALL min targets are met so valid builds always
    rank above near-miss builds.  Excess over each target is also rewarded
    so the optimizer maximises stat efficiency after constraints are met.
    """
    score = 0.0
    all_mins_met = True

    for stat_key, t in targets.items():
        val = stats.get(stat_key, 0)

        if "min" in t:
            if val < t["min"]:
                all_mins_met = False
                score -= (t["min"] - val) / max(1, t["min"]) * 100
            else:
                score += val / max(1, t["min"])

        if "max" in t and val > t["max"]:
            score -= (val - t["max"]) / max(1, t["max"]) * 50

    if all_mins_met:
        score += 1000   # dominant bonus — valid beats invalid

    return score


def _feasible(set_counts: dict[int, int],
              required_sets: list[tuple[int, int]],
              slots_remaining: int) -> bool:
    """
    Return True if it is still possible to satisfy all required sets
    given the current set counts and how many rune slots are left to fill.
    """
    deficit = sum(
        max(0, needed - set_counts.get(sid, 0))
        for sid, needed in required_sets
    )
    return deficit <= slots_remaining


# ── Single-monster optimizer ─────────────────────────────────────────────────

def optimize_monster(
    monster: Monster,
    available_runes: list[Rune],
    targets: dict,
    required_sets: list[tuple[int, int]],  # [(set_id, min_count), …]
    main_stat_prefs: dict[int, int],        # {slot: stat_id}
) -> tuple[list[Rune] | None, dict]:
    """
    Find the best 6-rune combination for *monster* drawn from
    *available_runes*.

    Returns
    -------
    (assigned_runes, final_stats)
        assigned_runes is None only if there are no runes at all for some
        slot.  Otherwise the best attempt is always returned even when some
        targets are not met.
    """
    # ── 1. Group by slot ──────────────────────────────────────────────────
    by_slot: dict[int, list[Rune]] = {s: [] for s in range(1, 7)}
    for r in available_runes:
        if r.slot_no and 1 <= r.slot_no <= 6:
            by_slot[r.slot_no].append(r)

    # ── 2. Pre-filter: main stat preferences + quick-score top K ─────────
    # Each slot entry: list of (rune, rune_stat_list) where rune_stat_list
    # is pre-extracted and aligned to ALL_STAT_IDS to avoid repeated work.
    N_STATS = len(ALL_STAT_IDS)
    prepped_slots: dict[int, list[tuple]] = {}

    for slot in range(1, 7):
        candidates = by_slot[slot]

        # Apply main-stat filter (only for slots 2, 4, 6)
        if slot in main_stat_prefs and main_stat_prefs[slot] is not None:
            req = main_stat_prefs[slot]
            filtered = [r for r in candidates if r.pri_eff and r.pri_eff[0] == req]
            if filtered:                   # fall back to all if nothing matches
                candidates = filtered

        # Score and keep top K
        scored = sorted(candidates, key=lambda r: _quick_score(r, targets, monster), reverse=True)
        top_k  = scored[:TOP_K]

        if not top_k:
            return None, {}

        # Pre-extract rune stats ONCE as a list aligned to ALL_STAT_IDS
        prepped: list[tuple] = []
        for r in top_k:
            rs = extract_rune_stats(r)
            prepped.append((r, [rs.get(sid, 0.0) for sid in ALL_STAT_IDS]))
        prepped_slots[slot] = prepped

    # ── 3. Beam search ───────────────────────────────────────────────────
    # Pre-build scoring coefficient vector once (base-stat-aware)
    score_coeffs = _build_score_coeffs(targets, monster)

    # State: (runes_list, stat_totals_list, set_counts_dict, score)
    # stat_totals_list is a list of N_STATS floats aligned to ALL_STAT_IDS.
    zero = [0.0] * N_STATS
    beam: list[tuple] = [
        ([], zero, {}, 0.0)
    ]

    for slot in range(1, 7):
        slot_runes = prepped_slots[slot]
        remaining_after = 6 - slot   # slots still to fill after this one
        next_beam: list[tuple] = []

        for (runes, totals, set_counts, _) in beam:
            for (rune, rune_vals) in slot_runes:
                # Update set counts
                sid = rune.set_id
                new_sc = dict(set_counts)
                if sid:
                    new_sc[sid] = new_sc.get(sid, 0) + 1

                # Feasibility pruning
                if not _feasible(new_sc, required_sets, remaining_after):
                    continue

                # Update stat totals (list addition — no dict.get overhead)
                new_totals = [totals[i] + rune_vals[i] for i in range(N_STATS)]

                next_beam.append((
                    runes + [rune],
                    new_totals,
                    new_sc,
                    _partial_score(new_totals, score_coeffs),
                ))

        if not next_beam:
            return None, {}

        # Prune to beam width
        next_beam.sort(key=lambda x: x[3], reverse=True)
        beam = next_beam[:BEAM_WIDTH]

    # ── 4. Pick best complete build ───────────────────────────────────────
    best_runes: list[Rune] | None = None
    best_stats: dict = {}
    best_score = float("-inf")

    def _totals_to_dict(totals: list) -> dict:
        return {ALL_STAT_IDS[i]: totals[i] for i in range(N_STATS)}

    for (runes, totals, set_counts, _) in beam:
        if len(runes) != 6:
            continue
        # Verify set requirements are fully met
        if not all(set_counts.get(s, 0) >= n for s, n in required_sets):
            continue

        stats = calc_final_stats(monster, _totals_to_dict(totals), set_counts)
        sc    = _final_score(stats, targets)
        if sc > best_score:
            best_score = sc
            best_runes = runes
            best_stats = stats

    # Fall back to the beam-best state if no set-valid build was found
    if best_runes is None and beam:
        runes, totals, set_counts, _ = beam[0]
        best_runes = runes
        best_stats = calc_final_stats(monster, _totals_to_dict(totals), set_counts)

    return best_runes, best_stats


# ── Team optimizer ───────────────────────────────────────────────────────────

def optimize_team(
    team_configs: list[dict],
    all_runes: list[Rune],
) -> list[dict]:
    """
    Optimise runes for an entire team in priority order.

    Each config dict must contain:
        monster          Monster instance
        targets          {stat_key: {"min": X, "max": Y}}
        required_sets    [(set_id, min_count), …]
        main_stat_prefs  {slot: stat_id}

    Runes assigned to an earlier monster are removed from the pool
    before the next monster is processed.
    """
    pool = list(all_runes)
    results: list[dict] = []

    for config in team_configs:
        monster         = config["monster"]
        targets         = config.get("targets", {})
        required_sets   = config.get("required_sets", [])
        main_stat_prefs = config.get("main_stat_prefs", {})

        assigned, stats = optimize_monster(
            monster, pool, targets, required_sets, main_stat_prefs
        )

        if assigned:
            assigned_ids = {r.rune_id for r in assigned}
            pool = [r for r in pool if r.rune_id not in assigned_ids]

        # Determine which targets were met
        targets_met: dict[str, bool] = {}
        for stat_key, t in targets.items():
            val  = stats.get(stat_key, 0) if stats else 0
            met  = True
            if "min" in t and val < t["min"]:
                met = False
            if "max" in t and val > t["max"]:
                met = False
            targets_met[stat_key] = met

        weak_slots: list[dict] = []
        if assigned and not all(targets_met.values()):
            weak_slots = identify_weak_slots(assigned, targets, stats)

        results.append({
            "unit_id":         monster.unit_id,
            "name":            monster.display_name,
            "success":         assigned is not None,
            "all_targets_met": all(targets_met.values()),
            "assigned_runes":  assigned or [],
            "stats":           stats,
            "targets_met":     targets_met,
            "weak_slots":      weak_slots,
        })

    return results


# ── Weak slot analysis ────────────────────────────────────────────────────────

def identify_weak_slots(
    assigned_runes: list[Rune],
    targets: dict,
    final_stats: dict,
) -> list[dict]:
    """
    For a build that doesn't fully meet all targets, rank each of the 6 rune
    slots by how little it contributes to the *unmet* targets.

    Returns a list sorted weakest -> strongest, each entry:
        slot            int
        main            str
        subs            list[str]
        contrib_score   float   (higher = contributes more)
        missing_stats   list[str]  e.g. ["SPD", "CR"]
        hint            str     human-readable fix suggestion
    """
    # Only care about unmet minimums
    unmet = {
        k: t for k, t in targets.items()
        if "min" in t and final_stats.get(k, 0) < t["min"]
    }
    if not unmet:
        return []

    SLOT_MAIN_HINTS = {
        2: "consider a SPD, CR, CD, ATK%, HP%, or DEF% main",
        4: "consider a CR, CD, ATK%, or SPD main",
        6: "consider an ATK%, HP%, DEF%, SPD, or ACC main",
        1: "slot 1 is always Flat HP — focus on substats",
        3: "slot 3 is always Flat ATK — focus on substats",
        5: "slot 5 is always Flat DEF — focus on substats",
    }

    slot_info: list[dict] = []
    for rune in sorted(assigned_runes, key=lambda r: r.slot_no or 0):
        rs = extract_rune_stats(rune)

        total_contrib = 0.0
        missing: list[str] = []

        for stat_key, t in unmet.items():
            min_val  = max(1.0, t["min"])
            stat_ids = STAT_KEY_TO_IDS.get(stat_key, [])
            contrib  = sum(rs.get(sid, 0) for sid in stat_ids)
            total_contrib += contrib / min_val
            if contrib < min_val * 0.04:
                missing.append(stat_key.upper())

        if missing:
            hint = f"Needs {', '.join(missing)} -- {SLOT_MAIN_HINTS.get(rune.slot_no, 'improve substats')}"
        else:
            hint = "Low overall contribution -- look for better subs"

        slot_info.append({
            "slot":          rune.slot_no,
            "main":          rune.main_stat_label,
            "subs":          rune.substat_labels,
            "contrib_score": round(total_contrib, 4),
            "missing_stats": missing,
            "hint":          hint,
        })

    slot_info.sort(key=lambda x: x["contrib_score"])
    return slot_info
