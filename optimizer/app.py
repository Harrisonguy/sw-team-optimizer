"""
Flask web server for the SW Team Rune Optimizer.

Endpoints
─────────
GET  /                    Serve the single-page UI
POST /api/load            Load a SWEX JSON export; returns account summary
GET  /api/monsters        Search monsters in the loaded account
POST /api/optimize        Run the team optimizer; returns per-monster results
GET  /api/sell-analysis   Score all runes + generate 5 sell exclusion rules
"""
from __future__ import annotations

import traceback
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from src.core.account.swex_importer import import_swex_account
from src.core.account.account_model import Account
from src.core.runes.rune_constants import RUNE_SET_NAMES, RUNE_STAT_NAMES
from optimizer.stat_calc import FOUR_PIECE_SET_IDS
from optimizer.optimizer_engine import optimize_team
from optimizer.sell_analyzer import get_sell_candidates, generate_exclusion_rules, score_rune

app = Flask(__name__)

# ── Global account state (single-user local tool) ────────────────────────────
_account: Account | None = None

# Set name → set_id lookup (case-insensitive)
_SET_NAME_TO_ID: dict[str, int] = {v.lower(): k for k, v in RUNE_SET_NAMES.items()}

# Stat name / shorthand → stat_id lookup
_STAT_SHORTHANDS: dict[str, int] = {
    "hp%": 2,  "hp pct": 2,   "hp percent": 2,
    "atk%": 4, "atk pct": 4,  "atk percent": 4,  "attack%": 4,
    "def%": 6, "def pct": 6,  "def percent": 6,  "defense%": 6,
    "spd":  8, "speed": 8,
    "cr":   9, "crit rate": 9,  "crit_rate": 9,
    "cd":  10, "crit dmg": 10, "crit damage": 10, "crit_damage": 10,
    "res": 11, "resistance": 11,
    "acc": 12, "accuracy": 12,
    **{v.lower(): k for k, v in RUNE_STAT_NAMES.items()},
}


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/load", methods=["POST"])
def load_account():
    global _account
    data     = request.json or {}
    path_str = data.get("path", "uuboram-17666244.json").strip().strip('"')

    try:
        path     = Path(path_str)
        _account = import_swex_account(path)

        all_runes = _account.equipped_runes + _account.inventory_runes
        return jsonify({
            "success":       True,
            "player_name":   _account.player_name,
            "wizard_id":     _account.wizard_id,
            "monster_count": len(_account.monsters),
            "rune_count":    len(all_runes),
        })
    except FileNotFoundError:
        return jsonify({"success": False, "error": f"File not found: {path_str}"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/monsters")
def get_monsters():
    if not _account:
        return jsonify({"error": "No account loaded"}), 400

    query = request.args.get("q", "").lower().strip()

    monsters = []
    for m in _account.monsters:
        if query and query not in m.display_name.lower():
            continue
        monsters.append({
            "unit_id":  m.unit_id,
            "name":     m.display_name,
            "element":  m.element or "",
            "archetype": m.archetype or "",
            "stars":    m.stars,
            "base_hp":  m.max_lvl_hp     or 0,
            "base_atk": m.max_lvl_attack  or 0,
            "base_def": m.max_lvl_defense or 0,
            "base_spd": m.base_speed      or 0,
            "base_cr":  m.crit_rate       or 15,
            "base_cd":  m.crit_damage     or 50,
            "base_res": m.resistance      or 15,
            "base_acc": m.accuracy        or 0,
        })

    monsters.sort(key=lambda m: m["name"])
    return jsonify({"monsters": monsters[:100]})


@app.route("/api/optimize", methods=["POST"])
def run_optimize():
    if not _account:
        return jsonify({"error": "No account loaded"}), 400

    data      = request.json or {}
    team_data = data.get("team", [])
    if not team_data:
        return jsonify({"error": "Team is empty"}), 400

    all_runes = _account.equipped_runes + _account.inventory_runes

    team_configs = []
    for item in team_data:
        unit_id = item.get("unit_id")
        monster = _account.get_monster_by_unit_id(unit_id)
        if monster is None:
            return jsonify({"error": f"Monster unit_id {unit_id} not found"}), 400

        # ── Parse targets ────────────────────────────────────────────────
        targets: dict = {}
        for stat_key, bounds in (item.get("targets") or {}).items():
            entry: dict = {}
            if bounds.get("min") not in (None, ""):
                try:
                    entry["min"] = float(bounds["min"])
                except (ValueError, TypeError):
                    pass
            if bounds.get("max") not in (None, ""):
                try:
                    entry["max"] = float(bounds["max"])
                except (ValueError, TypeError):
                    pass
            if entry:
                targets[stat_key] = entry

        # ── Parse required sets ──────────────────────────────────────────
        required_sets: list[tuple[int, int]] = []
        total_pieces = 0
        for set_name in (item.get("sets") or []):
            sid = _SET_NAME_TO_ID.get(set_name.lower().strip())
            if sid is None:
                continue
            pieces = 4 if sid in FOUR_PIECE_SET_IDS else 2
            if total_pieces + pieces <= 6:
                required_sets.append((sid, pieces))
                total_pieces += pieces

        # ── Parse main stat prefs ────────────────────────────────────────
        main_stat_prefs: dict[int, int] = {}
        for slot_str, stat_name in (item.get("main_stats") or {}).items():
            slot = int(slot_str)
            if slot not in (2, 4, 6):
                continue
            if isinstance(stat_name, int):
                main_stat_prefs[slot] = stat_name
            elif stat_name:
                sid = _STAT_SHORTHANDS.get(str(stat_name).lower().strip())
                if sid:
                    main_stat_prefs[slot] = sid

        team_configs.append({
            "monster":         monster,
            "targets":         targets,
            "required_sets":   required_sets,
            "main_stat_prefs": main_stat_prefs,
        })

    try:
        raw_results = optimize_team(team_configs, all_runes)
    except Exception as e:
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500

    # ── Serialise results ────────────────────────────────────────────────
    output = []
    for r in raw_results:
        rune_details = []
        for rune in r["assigned_runes"]:
            rune_details.append({
                "rune_id":  rune.rune_id,
                "slot":     rune.slot_no,
                "set":      rune.set_name,
                "stars":    rune.stars_label,
                "type":     rune.rune_type,
                "upgrade":  rune.upgrade_curr,
                "main":     rune.main_stat_label,
                "prefix":   rune.prefix_stat_label,
                "subs":     rune.substat_labels,
            })

        output.append({
            "unit_id":         r["unit_id"],
            "name":            r["name"],
            "success":         r["success"],
            "all_targets_met": r["all_targets_met"],
            "stats":           r["stats"],
            "targets_met":     r["targets_met"],
            "weak_slots":      r.get("weak_slots", []),
            "runes":           rune_details,
        })

    return jsonify({"success": True, "results": output})


@app.route("/api/sell-analysis")
def sell_analysis():
    if not _account:
        return jsonify({"error": "No account loaded"}), 400

    data = request.args
    min_stars    = int(data.get("min_stars",    5))
    grade_thresh = data.get("grade_threshold", "C")
    max_upgrade  = int(data.get("max_upgrade",  9))

    all_runes = _account.equipped_runes + _account.inventory_runes
    protected_ids: set[int] = set()

    candidates = get_sell_candidates(
        all_runes, protected_ids,
        min_stars=min_stars, grade_threshold=grade_thresh, max_upgrade=max_upgrade,
    )
    rules = generate_exclusion_rules(all_runes)

    # Grade distribution across full pool
    grade_dist: dict[str, int] = {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0}
    for rune in all_runes:
        from src.core.runes.rune_decode import rune_stars_from_class
        if (rune_stars_from_class(rune.raw_class) or 0) >= min_stars:
            g = score_rune(rune)["grade"]
            grade_dist[g] = grade_dist.get(g, 0) + 1

    return jsonify({
        "success":     True,
        "total_runes": len(all_runes),
        "sell_count":  len(candidates),
        "grade_dist":  grade_dist,
        "candidates":  candidates[:500],
        "rules":       rules,
    })
