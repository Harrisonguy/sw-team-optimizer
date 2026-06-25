"""Query helpers for the SW Team Optimizer SQLite database."""
from __future__ import annotations

import sqlite3
from typing import Any


def get_active_profile_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT value FROM app_state WHERE key = 'active_profile_id'"
    ).fetchone()
    if not row:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def activate_account_profile(
    conn: sqlite3.Connection,
    profile_id: int,
) -> dict:
    """Switch the active account and return its refreshed summary."""
    from desktop.db.schema import activate_profile

    with conn:
        activate_profile(conn, profile_id)
    return get_account_info(conn)


def list_account_profiles(conn: sqlite3.Connection) -> list[dict]:
    active_id = get_active_profile_id(conn)
    rows = conn.execute(
        "SELECT profile_id, profile_name, wizard_id, created_at, last_imported_at"
        " FROM account_profiles"
        " ORDER BY last_imported_at DESC, profile_name COLLATE NOCASE"
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["is_active"] = item["profile_id"] == active_id
        result.append(item)
    return result


def get_account_progression(conn: sqlite3.Connection) -> dict:
    """Return raw profile-specific progression and bonus source data."""
    import json as _json

    try:
        rows = conn.execute(
            "SELECT progression_key, payload FROM account_progression"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    result = {}
    for row in rows:
        try:
            result[row["progression_key"]] = _json.loads(row["payload"])
        except (TypeError, ValueError):
            result[row["progression_key"]] = None
    return result


def get_account_info(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT profile_id, player_name, wizard_id, imported_at"
        " FROM account ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not row:
        return {}
    progression = get_account_progression(conn)
    return {
        "profile_id":     row["profile_id"],
        "player_name":    row["player_name"],
        "wizard_id":      row["wizard_id"],
        "imported_at":    row["imported_at"],
        "profile_count":  conn.execute("SELECT COUNT(*) FROM account_profiles").fetchone()[0],
        "rune_count":     conn.execute("SELECT COUNT(*) FROM runes").fetchone()[0],
        "monster_count":  conn.execute("SELECT COUNT(*) FROM monsters").fetchone()[0],
        "artifact_count": conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0],
        "wizard_level": progression.get("wizard_level"),
        "wizard_skill_count": len(progression.get("wizard_skill_list") or {}),
        "guild_level": progression.get("guild_level"),
        "guild_skill_groups": len(progression.get("guild_skill_info") or {}),
    }


_SAFE_RUNE_COLS = {
    "slot_no", "set_name", "stars", "upgrade_curr",
    "main_stat_name", "main_stat_value",
    "efficiency", "desirability", "grade", "occupied_name",
}


def get_runes(
    conn: sqlite3.Connection,
    slot: int | None = None,
    set_name: str | None = None,
    stars: int | None = None,
    main_stat: str | None = None,
    substat: str | None = None,
    grade: str | None = None,
    location: str | None = None,
    search: str = "",
    sort_col: str = "desirability",
    sort_asc: bool = False,
    limit: int = 5000,
) -> list[dict]:
    wheres: list[str] = []
    params: list[Any] = []

    if slot is not None:
        wheres.append("slot_no = ?")
        params.append(slot)
    if set_name:
        wheres.append("set_name = ?")
        params.append(set_name)
    if stars is not None:
        wheres.append("stars = ?")
        params.append(stars)
    if main_stat:
        wheres.append("main_stat_name = ?")
        params.append(main_stat)
    if substat:
        wheres.append("substat_types LIKE ?")
        params.append("%" + substat + "%")
    if grade:
        wheres.append("grade = ?")
        params.append(grade)
    if location == "equipped":
        wheres.append("occupied_id IS NOT NULL AND occupied_id > 0")
    elif location == "storage":
        wheres.append("(occupied_id IS NULL OR occupied_id = 0)")
    if search:
        wheres.append(
            "(set_name LIKE ? OR main_stat_name LIKE ?"
            " OR substat_labels LIKE ? OR occupied_name LIKE ?)"
        )
        s = "%" + search + "%"
        params.extend([s, s, s, s])

    where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
    col  = sort_col if sort_col in _SAFE_RUNE_COLS else "desirability"
    dir_ = "ASC" if sort_asc else "DESC"

    sql = (
        "SELECT r.rune_id, r.slot_no, r.set_name, r.stars, r.quality, r.upgrade_curr,"
        " r.main_stat_name, r.main_stat_value,"
        " r.prefix_stat_name, r.prefix_stat_value,"
        " r.substat_labels, r.efficiency, r.desirability, r.grade,"
        " r.occupied_name, r.location_label,"
        " COALESCE(p.locked, 0) AS user_locked"
        " FROM runes r"
        " LEFT JOIN user_rune_prefs p ON r.rune_id = p.rune_id"
        + (" " + where_sql if where_sql else "") +
        " ORDER BY r." + col + " " + dir_ +
        " LIMIT " + str(int(limit))
    )
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_distinct_sets(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT set_name FROM runes"
        " WHERE set_name IS NOT NULL ORDER BY set_name"
    ).fetchall()
    return [r[0] for r in rows]


def get_distinct_main_stats(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT main_stat_name FROM runes"
        " WHERE main_stat_name IS NOT NULL ORDER BY main_stat_name"
    ).fetchall()
    return [r[0] for r in rows]


def get_monsters(conn: sqlite3.Connection, search: str = "") -> list[dict]:
    params: list[Any] = []
    where = ""
    if search:
        where = "WHERE display_name LIKE ? OR element LIKE ? OR archetype LIKE ?"
        s = "%" + search + "%"
        params = [s, s, s]

    sql = (
        "SELECT unit_id, display_name, base_name, element, archetype,"
        " natural_stars, stars, level,"
        " max_lvl_hp, max_lvl_attack, max_lvl_defense, base_speed,"
        " crit_rate, crit_damage, resistance, accuracy,"
        " leader_skill_attribute, leader_skill_amount,"
        " leader_skill_area, leader_skill_element,"
        " skills_json, skill_levels_json"
        " FROM monsters " + where +
        " ORDER BY display_name ASC"
    )
    result = []
    for row in conn.execute(sql, params).fetchall():
        item = dict(row)
        try:
            item["skills"] = [int(value) for value in __import__("json").loads(item.get("skills_json") or "[]")]
        except (TypeError, ValueError):
            item["skills"] = []
        try:
            item["skill_levels"] = {
                int(key): int(value)
                for key, value in __import__("json").loads(item.get("skill_levels_json") or "{}").items()
            }
        except (AttributeError, TypeError, ValueError):
            item["skill_levels"] = {}
        result.append(item)
    return result


def get_monster_skill_profiles(conn: sqlite3.Connection, unit_id: int) -> list[dict]:
    """Return imported skill levels merged with local combat formula data."""
    from dataclasses import asdict
    from src.core.skills.skill_library import monster_skill_profiles

    row = conn.execute(
        "SELECT skills_json, skill_levels_json FROM monsters WHERE unit_id = ?",
        (unit_id,),
    ).fetchone()
    if not row:
        return []
    import json as _json
    try:
        skill_ids = [int(value) for value in _json.loads(row["skills_json"] or "[]")]
    except (TypeError, ValueError):
        skill_ids = []
    try:
        levels = {
            int(key): int(value)
            for key, value in _json.loads(row["skill_levels_json"] or "{}").items()
        }
    except (AttributeError, TypeError, ValueError):
        levels = {}
    return [asdict(profile) for profile in monster_skill_profiles(skill_ids, levels)]


def get_monster_equipped_sets(conn: sqlite3.Connection, unit_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT set_name FROM runes WHERE occupied_id = ? ORDER BY slot_no",
        (unit_id,),
    ).fetchall()
    return [r[0] for r in rows if r[0]]


_SAFE_ART_COLS = {"level", "rank", "occupied_name", "requirement_label"}


def get_artifacts(
    conn: sqlite3.Connection,
    attribute: str | None = None,
    search: str = "",
    sort_col: str = "level",
    sort_asc: bool = False,
) -> list[dict]:
    wheres: list[str] = []
    params: list[Any] = []

    if attribute:
        wheres.append("requirement_label = ?")
        params.append(attribute)
    if search:
        wheres.append(
            "(requirement_label LIKE ? OR pri_effect LIKE ?"
            " OR sec_effects LIKE ? OR occupied_name LIKE ?)"
        )
        s = "%" + search + "%"
        params.extend([s, s, s, s])

    where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
    col  = sort_col if sort_col in _SAFE_ART_COLS else "level"
    dir_ = "ASC" if sort_asc else "DESC"

    sql = (
        "SELECT artifact_id, slot, slot_label, attribute, attribute_label,"
        " unit_style, requirement_label, natural_rank, rank, level,"
        " pri_effect, pri_effect_id, pri_effect_value,"
        " sec_effects, sec_effect_data, locked,"
        " occupied_id, occupied_name, location_label"
        " FROM artifacts " + where_sql +
        " ORDER BY " + col + " " + dir_
    )
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_monster_artifacts(
    conn: sqlite3.Connection,
    unit_id: int,
) -> list[dict]:
    """Return complete structured artifact rows equipped by one monster."""
    rows = conn.execute(
        "SELECT artifact_id, slot, slot_label, attribute, attribute_label,"
        " unit_style, requirement_label, natural_rank, rank, level,"
        " pri_effect, pri_effect_id, pri_effect_value,"
        " sec_effects, sec_effect_data, locked,"
        " occupied_id, occupied_name, location_label"
        " FROM artifacts WHERE occupied_id = ? ORDER BY slot_label",
        (unit_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_monster_artifact_bonuses(
    conn: sqlite3.Connection,
    unit_id: int,
    profile=None,
) -> dict:
    """Return context-aware bonuses from a monster's equipped artifacts."""
    from optimizer.artifact_optimizer import aggregate_artifact_bonuses

    return aggregate_artifact_bonuses(
        get_monster_artifacts(conn, unit_id),
        profile,
    )


# ---- Grade ordering for display -------------------------------------------------
_GRADE_ORDER = ["Legend", "Hero", "Rare", "Magic", "Normal"]
_ART_RANK_LABEL = {5: "Legend", 4: "Hero", 3: "Rare", 2: "Magic", 1: "Common"}


def get_analytics(conn: sqlite3.Connection) -> dict:
    """Return aggregated analytics data for the analytics panel."""
    result: dict = {}

    result["total_runes"] = conn.execute(
        "SELECT COUNT(*) FROM runes"
    ).fetchone()[0]

    result["total_monsters"] = conn.execute(
        "SELECT COUNT(*) FROM monsters"
    ).fetchone()[0]

    result["total_artifacts"] = conn.execute(
        "SELECT COUNT(*) FROM artifacts"
    ).fetchone()[0]

    avg_row = conn.execute(
        "SELECT AVG(efficiency) FROM runes WHERE efficiency IS NOT NULL"
    ).fetchone()
    result["avg_efficiency"] = float(avg_row[0] or 0.0)

    legend_row = conn.execute(
        "SELECT COUNT(*) FROM runes WHERE grade = 'Legend'"
    ).fetchone()
    total = result["total_runes"] or 1
    result["legend_pct"] = 100.0 * (legend_row[0] or 0) / total

    top_set_row = conn.execute(
        "SELECT set_name, COUNT(*) AS cnt FROM runes"
        " WHERE set_name IS NOT NULL"
        " GROUP BY set_name ORDER BY cnt DESC LIMIT 1"
    ).fetchone()
    result["top_set"] = top_set_row[0] if top_set_row else "--"

    grade_map: dict = {}
    for row in conn.execute(
        "SELECT grade, COUNT(*) FROM runes WHERE grade IS NOT NULL GROUP BY grade"
    ).fetchall():
        grade_map[row[0]] = row[1]
    result["grades"] = [
        (g, grade_map[g]) for g in _GRADE_ORDER if g in grade_map
    ]

    effs = [
        r[0] for r in conn.execute(
            "SELECT efficiency FROM runes WHERE efficiency IS NOT NULL"
        ).fetchall()
    ]
    buckets = [0] * 6
    for e in effs:
        if e < 20:
            buckets[0] += 1
        elif e < 40:
            buckets[1] += 1
        elif e < 60:
            buckets[2] += 1
        elif e < 80:
            buckets[3] += 1
        elif e < 100:
            buckets[4] += 1
        else:
            buckets[5] += 1
    bucket_labels = ["<20%", "20-40%", "40-60%", "60-80%", "80-100%", "100%+"]
    result["efficiency"] = list(zip(bucket_labels, buckets))

    result["sets"] = [
        (r[0], r[1]) for r in conn.execute(
            "SELECT set_name, COUNT(*) AS cnt FROM runes"
            " WHERE set_name IS NOT NULL"
            " GROUP BY set_name ORDER BY cnt DESC LIMIT 12"
        ).fetchall()
    ]

    star_map: dict = {}
    for row in conn.execute(
        "SELECT stars, COUNT(*) FROM runes WHERE stars IS NOT NULL GROUP BY stars"
    ).fetchall():
        star_map[row[0]] = row[1]
    result["stars"] = [
        (str(s) + "★", star_map[s]) for s in range(1, 7) if s in star_map
    ]

    result["elements"] = [
        (r[0], r[1]) for r in conn.execute(
            "SELECT element, COUNT(*) FROM monsters"
            " WHERE element IS NOT NULL"
            " GROUP BY element ORDER BY COUNT(*) DESC"
        ).fetchall()
    ]

    art_map: dict = {}
    for row in conn.execute(
        "SELECT rank, COUNT(*) FROM artifacts WHERE rank IS NOT NULL GROUP BY rank"
    ).fetchall():
        art_map[row[0]] = row[1]
    result["artifact_quality"] = [
        (_ART_RANK_LABEL[k], art_map[k])
        for k in sorted(art_map.keys(), reverse=True)
        if k in _ART_RANK_LABEL
    ]

    from optimizer.account_analytics import analyze_account

    rune_rows = conn.execute(
        "SELECT rune_id, set_name, slot_no, stars, upgrade_curr,"
        " main_stat_id, prefix_stat_id, prefix_stat_value, sec_eff,"
        " efficiency, desirability, grade, occupied_id, occupied_name"
        " FROM runes"
    ).fetchall()
    monster_rows = conn.execute(
        "SELECT unit_id, display_name, base_name, stars, level FROM monsters"
    ).fetchall()
    artifact_rows = conn.execute(
        "SELECT artifact_id, slot_label, requirement_label, natural_rank,"
        " rank, level, sec_effect_data, locked, occupied_id FROM artifacts"
    ).fetchall()
    try:
        building_rows = conn.execute(
            "SELECT stat, element, bonus_pct FROM buildings"
        ).fetchall()
    except sqlite3.OperationalError:
        building_rows = []
    result["progression"] = analyze_account(
        rune_rows, monster_rows, artifact_rows, building_rows
    )

    return result


# ---- Sell analysis ----------------------------------------------------------

_GRADE_RANK = {"D": 0, "C": 1, "B": 2, "A": 3, "S": 4}


def get_sell_candidates_db(
    conn: sqlite3.Connection,
    grade_threshold: str = "C",
    min_stars: int = 5,
    max_upgrade: int = 9,
    storage_only: bool = True,
    exclude_unleveled: bool = True,
    limit: int = 5000,
) -> list[dict]:
    """Return runes that are sell candidates, worst desirability first.

    When exclude_unleveled=True (the default), runes are hidden unless enough
    substats are visible to make a reliable recommendation.

    Per the SW rarity table (subs visible by upgrade level):
      Legendary / Ancient Legendary: 4/4/4/4/4/4  -> include at any level
      Hero      / Ancient Hero:      3/3/3/3/4/4  -> include at any level (3 visible at +0)
      Rare      / Ancient Rare:      2/2/2/3/4/4  -> need +9 (3 subs visible)
      Magic     / Ancient Magic:     1/1/2/3/4/4  -> need +9 (3 subs visible)
      Normal    / Ancient Normal:    0/1/2/3/4/4  -> need +9 (3 subs visible)

    Returns rows with extra fields sec_eff and main_stat_id for potential analysis.
    """
    threshold_val = _GRADE_RANK.get(grade_threshold, 1)
    sell_grades = [g for g, r in _GRADE_RANK.items() if r <= threshold_val]

    placeholders = ",".join("?" * len(sell_grades))
    wheres = [
        "grade IN (" + placeholders + ")",
        "stars >= ?",
        "(upgrade_curr IS NULL OR upgrade_curr <= ?)",
    ]
    params: list[Any] = list(sell_grades) + [min_stars, max_upgrade]

    if storage_only:
        wheres.append("(occupied_id IS NULL OR occupied_id = 0)")

    if exclude_unleveled:
        # Legendary and Hero are always evaluatable (3+ subs visible at +0).
        # Rare/Magic/Normal need at least +9 where 3 of 4 substats are revealed.
        wheres.append(
            "(quality LIKE '%Legend%'"
            " OR quality LIKE '%Hero%'"
            " OR (upgrade_curr IS NOT NULL AND upgrade_curr >= 9))"
        )

    where_sql = "WHERE " + " AND ".join(wheres)

    sql = (
        "SELECT rune_id, slot_no, set_name, stars, quality, upgrade_curr,"
        " main_stat_id, main_stat_name, main_stat_value,"
        " prefix_stat_name, prefix_stat_value,"
        " substat_labels, efficiency, desirability, grade,"
        " occupied_name, location_label, sec_eff"
        " FROM runes " + where_sql +
        " ORDER BY desirability ASC, efficiency ASC"
        " LIMIT " + str(int(limit))
    )
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def count_under_evaluated(
    conn: sqlite3.Connection,
    grade_threshold: str = "C",
    min_stars: int = 5,
    storage_only: bool = True,
) -> int:
    """Count runes that match the sell filters but are hidden because too few
    substats are visible to make a reliable sell decision.

    Rare/Magic/Normal runes need +9 to show 3 of 4 substats.
    Legendary/Hero runes are always included (3-4 subs visible at +0).
    """
    threshold_val = _GRADE_RANK.get(grade_threshold, 1)
    sell_grades = [g for g, r in _GRADE_RANK.items() if r <= threshold_val]
    placeholders = ",".join("?" * len(sell_grades))

    wheres = [
        "grade IN (" + placeholders + ")",
        "stars >= ?",
        "quality NOT LIKE '%Legend%'",
        "quality NOT LIKE '%Hero%'",
        "(upgrade_curr IS NULL OR upgrade_curr < 9)",
    ]
    params: list[Any] = list(sell_grades) + [min_stars]

    if storage_only:
        wheres.append("(occupied_id IS NULL OR occupied_id = 0)")

    where_sql = "WHERE " + " AND ".join(wheres)
    row = conn.execute("SELECT COUNT(*) FROM runes " + where_sql, params).fetchone()
    return int(row[0]) if row else 0


def get_account_desirability_bar(
    conn: sqlite3.Connection,
    min_stars: int = 5,
    percentile: float = 0.25,
) -> float:
    """Return the Nth percentile desirability score from storage runes.

    This is the 'bar' used for potential comparison: runes whose projected
    max desirability (at +15) falls below this value are flagged as
    'below bar' -- they can never compete with the account's existing runes.
    """
    rows = conn.execute(
        "SELECT desirability FROM runes"
        " WHERE desirability IS NOT NULL"
        " AND stars >= ?"
        " AND (occupied_id IS NULL OR occupied_id = 0)"
        " ORDER BY desirability ASC",
        (min_stars,),
    ).fetchall()

    if not rows:
        return 0.0

    vals = [float(r[0]) for r in rows]
    idx  = max(0, min(int(len(vals) * percentile), len(vals) - 1))
    return vals[idx]


def annotate_sell_potential(
    conn: sqlite3.Connection,
    candidates: list[dict],
    min_stars: int = 5,
    percentile: float = 0.25,
) -> list[dict]:
    """Add 'projected_desr' and 'below_bar' fields to each candidate dict.

    projected_desr (float): best-case desirability the rune could reach at +15.
    below_bar (bool): True if projected_desr < account's Nth percentile bar.

    Runes that are below bar cannot reach the minimum level of the account's
    existing rune pool even if perfectly upgraded -- strong sell signal.
    """
    import json as _json
    from optimizer.sell_analyzer import compute_projected_desirability

    bar = get_account_desirability_bar(conn, min_stars=min_stars, percentile=percentile)

    for cand in candidates:
        sec_eff_raw = cand.get("sec_eff")
        try:
            sec_eff = _json.loads(sec_eff_raw) if sec_eff_raw else []
        except (ValueError, TypeError):
            sec_eff = []

        proj = compute_projected_desirability(
            sec_eff_list = sec_eff,
            upgrade_curr = cand.get("upgrade_curr") or 0,
            slot_no      = cand.get("slot_no") or 0,
            main_stat_id = cand.get("main_stat_id"),
            set_name     = cand.get("set_name") or "",
        )
        cand["projected_desr"] = round(proj, 1)
        cand["below_bar"]      = proj < bar

    return candidates


def compute_exclusion_rules(conn: sqlite3.Connection) -> list[dict]:
    """
    Derive the 5 SW sell exclusion rules from the stored rune substats.
    Thresholds are set at the 35th percentile of each stat across the account.
    """
    import json as _json
    from collections import defaultdict

    stat_values: dict = defaultdict(list)
    for row in conn.execute(
        "SELECT sec_eff FROM runes WHERE sec_eff IS NOT NULL"
    ).fetchall():
        try:
            subs = _json.loads(row[0]) if row[0] else []
        except (ValueError, TypeError):
            continue
        for sub in subs:
            if not sub or len(sub) < 2:
                continue
            sid = sub[0]
            val = sub[1] + (sub[3] if len(sub) >= 4 else 0)
            if val > 0:
                stat_values[sid].append(val)

    def pct(sid: int, p: float) -> int:
        vals = sorted(stat_values.get(sid, [1.0]))
        idx  = max(0, min(int(len(vals) * p), len(vals) - 1))
        return int(vals[idx])

    spd_t  = max(4,  pct(8,  0.35))
    cr_t   = max(4,  pct(9,  0.35))
    cd_t   = max(5,  pct(10, 0.35))
    atkp_t = max(5,  pct(4,  0.35))
    hpp_t  = max(5,  pct(2,  0.35))
    defp_t = max(5,  pct(6,  0.35))
    acc_t  = max(5,  pct(12, 0.35))
    res_t  = max(5,  pct(11, 0.35))

    return [
        {
            "name": "Speed + Offense",
            "tab": 1,
            "description": "Offense runes with speed -- core for most damage dealers",
            "subs_needed": 2,
            "conditions": [
                {"stat": "SPD",  "label": "SPD >= "  + str(spd_t)},
                {"stat": "ATK%", "label": "ATK% >= " + str(atkp_t) + "%"},
                {"stat": "CR",   "label": "CR >= "   + str(cr_t)  + "%"},
                {"stat": "CD",   "label": "CD >= "   + str(cd_t)  + "%"},
            ],
        },
        {
            "name": "Speed + Tank",
            "tab": 2,
            "description": "Tanky runes with speed -- supports, bruisers, and utility",
            "subs_needed": 2,
            "conditions": [
                {"stat": "SPD",  "label": "SPD >= "  + str(spd_t)},
                {"stat": "HP%",  "label": "HP% >= "  + str(hpp_t)  + "%"},
                {"stat": "DEF%", "label": "DEF% >= " + str(defp_t) + "%"},
            ],
        },
        {
            "name": "Pure Crit",
            "tab": 3,
            "description": "High crit stats -- staple for all damage dealers",
            "subs_needed": 2,
            "conditions": [
                {"stat": "CR",   "label": "CR >= "   + str(cr_t)   + "%"},
                {"stat": "CD",   "label": "CD >= "   + str(cd_t)   + "%"},
                {"stat": "ATK%", "label": "ATK% >= " + str(atkp_t) + "%"},
            ],
        },
        {
            "name": "Defense / HP",
            "tab": 4,
            "description": "Pure tank runes -- healers, revivers, protectors",
            "subs_needed": 2,
            "conditions": [
                {"stat": "HP%",  "label": "HP% >= "  + str(hpp_t)  + "%"},
                {"stat": "DEF%", "label": "DEF% >= " + str(defp_t) + "%"},
                {"stat": "SPD",  "label": "SPD >= "  + str(spd_t)},
            ],
        },
        {
            "name": "Support / Utility",
            "tab": 5,
            "description": "Accuracy and resistance -- debuffers and supports",
            "subs_needed": 2,
            "conditions": [
                {"stat": "ACC", "label": "ACC >= " + str(acc_t) + "%"},
                {"stat": "RES", "label": "RES >= " + str(res_t) + "%"},
                {"stat": "SPD", "label": "SPD >= " + str(spd_t)},
            ],
        },
    ]


# ---- Monster build viewer ---------------------------------------------------

def get_monster_rune_build(
    conn: sqlite3.Connection,
    unit_id: int,
) -> dict[int, dict]:
    """Return equipped runes for a monster keyed by slot number (1-6).
    Slots with no rune are absent from the result dict.
    """
    rows = conn.execute(
        "SELECT rune_id, slot_no, set_name, stars, raw_class, quality, upgrade_curr,"
        " main_stat_id, main_stat_name, main_stat_value,"
        " prefix_stat_name, prefix_stat_value,"
        " substat_labels, sec_eff, efficiency, desirability, grade, location_label"
        " FROM runes WHERE occupied_id = ?",
        (unit_id,),
    ).fetchall()
    return {r["slot_no"]: dict(r) for r in rows}


def get_best_storage_for_slot(
    conn: sqlite3.Connection,
    slot_no: int,
    min_desr: float = 0.0,
) -> dict | None:
    """Return the highest-desirability unequipped storage rune for a given slot
    that beats min_desr.  Returns None if no upgrade is available.
    """
    row = conn.execute(
        "SELECT rune_id, slot_no, set_name, stars, upgrade_curr,"
        " main_stat_name, main_stat_value,"
        " substat_labels, efficiency, desirability, grade"
        " FROM runes"
        " WHERE slot_no = ? AND desirability > ?"
        " AND (occupied_id IS NULL OR occupied_id = 0)"
        " ORDER BY desirability DESC LIMIT 1",
        (slot_no, min_desr),
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Rune Optimizer queries
# ---------------------------------------------------------------------------


def get_locked_rune_ids(conn: sqlite3.Connection) -> set[int]:
    """Return the set of rune IDs the user has locked (optimizer-excluded)."""
    rows = conn.execute(
        "SELECT rune_id FROM user_rune_prefs WHERE locked = 1"
    ).fetchall()
    return {r[0] for r in rows}


def set_rune_locked(conn: sqlite3.Connection, rune_id: int, locked: bool) -> None:
    """Toggle the user-defined lock on a rune. Survives re-imports."""
    conn.execute(
        "INSERT INTO user_rune_prefs (rune_id, locked) VALUES (?, ?)"
        " ON CONFLICT(rune_id) DO UPDATE SET locked = excluded.locked",
        (rune_id, 1 if locked else 0),
    )
    conn.commit()


def is_rune_locked(conn: sqlite3.Connection, rune_id: int) -> bool:
    row = conn.execute(
        "SELECT locked FROM user_rune_prefs WHERE rune_id = ?", (rune_id,)
    ).fetchone()
    return bool(row and row[0])

def get_rune_pool(
    conn: sqlite3.Connection,
    min_stars: int = 5,
    include_equipped: bool = False,
    exclude_unit_id: int | None = None,
    exclude_user_locked: bool = True,
) -> list[dict]:
    """Return all candidate runes for the optimizer.

    Parameters
    ----------
    min_stars:        Minimum rune stars (default 5).
    include_equipped: If True, runes equipped on OTHER monsters are included.
    exclude_unit_id:  Unit whose currently equipped runes are excluded from the
                      pool (we don't want to suggest a monster's own runes as
                      improvements to itself).
    """
    conditions = ["r.stars >= ?"]
    params: list = [min_stars]

    if not include_equipped:
        conditions.append("(r.occupied_id IS NULL OR r.occupied_id = 0)")
    elif exclude_unit_id is not None:
        conditions.append("(r.occupied_id IS NULL OR r.occupied_id = 0 OR r.occupied_id != ?)")
        params.append(exclude_unit_id)
    if exclude_user_locked:
        conditions.append("COALESCE(p.locked, 0) = 0")

    where = " AND ".join(conditions)
    rows = conn.execute(
        "SELECT r.rune_id, r.slot_no, r.set_name, r.stars, r.raw_class, r.quality,"
        " r.upgrade_curr,"
        " r.main_stat_id, r.main_stat_name, r.main_stat_value,"
        " r.prefix_stat_name, r.prefix_stat_value,"
        " r.substat_labels, r.sec_eff, r.efficiency, r.desirability, r.grade,"
        " r.occupied_id, r.occupied_name, r.location_label,"
        " COALESCE(p.locked, 0) AS user_locked"
        " FROM runes r"
        " LEFT JOIN user_rune_prefs p ON r.rune_id = p.rune_id"
        " WHERE " + where
        + " ORDER BY r.slot_no, r.desirability DESC",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def get_monster_current_build_desr(
    conn: sqlite3.Connection,
    unit_id: int,
) -> float:
    """Return average desirability of the 6 equipped rune slots (0.0 if none)."""
    row = conn.execute(
        "SELECT AVG(desirability) FROM runes"
        " WHERE occupied_id = ? AND desirability IS NOT NULL",
        (unit_id,),
    ).fetchone()
    val = row[0] if row else None
    return round(float(val), 1) if val is not None else 0.0


# ---------------------------------------------------------------------------
# Monster total-stat calculator (base + runes + artifacts)
# ---------------------------------------------------------------------------

# Rune stat_id -> which accumulator bucket
_STAT_FLAT  = {1: "hp",  3: "atk",  5: "def"}
_STAT_PCT   = {2: "hp",  4: "atk",  6: "def"}
_STAT_ADD   = {8: "spd", 9: "cr",  10: "cd", 11: "res", 12: "acc"}


def compute_monster_stats(
    conn: sqlite3.Connection,
    unit_id: int,
    include_artifacts: bool = True,
) -> dict:
    """Return a monster's full in-game stats including rune and artifact bonuses.

    Returns a dict with keys: hp, atk, def_, spd, cr, cd, res, acc
    (all ints/floats, cr/cd/res/acc are percentage points not decimals).
    Returns an empty dict if the monster is not found.
    """
    import json as _json

    monster = conn.execute(
        "SELECT max_lvl_hp, max_lvl_attack, max_lvl_defense,"
        " base_speed, crit_rate, crit_damage, resistance, accuracy"
        " FROM monsters WHERE unit_id = ?",
        (unit_id,),
    ).fetchone()
    if not monster:
        return {}

    base_hp   = monster["max_lvl_hp"]     or 0
    base_atk  = monster["max_lvl_attack"] or 0
    base_def  = monster["max_lvl_defense"] or 0
    base_spd  = monster["base_speed"]     or 0
    base_cr   = monster["crit_rate"]      or 0
    base_cd   = monster["crit_damage"]    or 0
    base_res  = monster["resistance"]     or 0
    base_acc  = monster["accuracy"]       or 0

    # Accumulators
    flat  = {"hp": 0,   "atk": 0,   "def": 0}
    pct   = {"hp": 0.0, "atk": 0.0, "def": 0.0}
    add   = {"spd": 0,  "cr": 0.0,  "cd": 0.0, "res": 0.0, "acc": 0.0}

    # --- Rune contributions -------------------------------------------------
    runes = conn.execute(
        "SELECT main_stat_id, main_stat_value, sec_eff"
        " FROM runes WHERE occupied_id = ?",
        (unit_id,),
    ).fetchall()

    for rune in runes:
        mid = rune["main_stat_id"]
        mv  = rune["main_stat_value"] or 0
        if mid in _STAT_FLAT:
            flat[_STAT_FLAT[mid]] += mv
        elif mid in _STAT_PCT:
            pct[_STAT_PCT[mid]]   += mv
        elif mid in _STAT_ADD:
            add[_STAT_ADD[mid]]   += mv

        raw = rune["sec_eff"]
        if raw:
            try:
                subs = _json.loads(raw) if isinstance(raw, str) else raw
                for sub in (subs or []):
                    if not sub or len(sub) < 2:
                        continue
                    sid   = sub[0]
                    val   = (sub[1] or 0) + (sub[3] if len(sub) >= 4 else 0)
                    if sid in _STAT_FLAT:
                        flat[_STAT_FLAT[sid]] += val
                    elif sid in _STAT_PCT:
                        pct[_STAT_PCT[sid]]   += val
                    elif sid in _STAT_ADD:
                        add[_STAT_ADD[sid]]   += val
            except Exception:
                pass

    # --- Artifact contributions ---------------------------------------------
    # pri_effect stored as label string "HP: 1800" or "ATK: 120" etc.
    arts = []
    if include_artifacts:
        arts = conn.execute(
            "SELECT pri_effect FROM artifacts WHERE occupied_id = ?",
            (unit_id,),
        ).fetchall()

    for art in arts:
        label = art["pri_effect"] or ""
        try:
            stat_part, val_part = label.split(":", 1)
            stat_part = stat_part.strip().upper()
            val       = float(val_part.strip().replace(",", ""))
            if stat_part == "HP":
                flat["hp"]  += int(val)
            elif stat_part == "ATK":
                flat["atk"] += int(val)
            elif stat_part == "DEF":
                flat["def"] += int(val)
        except Exception:
            pass

    # --- Set bonuses --------------------------------------------------------
    from optimizer.stat_utils import SET_SIZE as _SS, SET_STAT_BONUS as _SSB
    _set_counts: dict = {}
    for _sr in conn.execute(
        "SELECT set_name FROM runes WHERE occupied_id = ?", (unit_id,)
    ).fetchall():
        _sn = (_sr[0] or "").strip()
        if _sn:
            _set_counts[_sn] = _set_counts.get(_sn, 0) + 1
    _spct_hp = _spct_atk = _spct_def = _spct_spd = 0.0
    _sadd_cr = _sadd_cd = _sadd_res = _sadd_acc = 0.0
    for _sn, _cnt in _set_counts.items():
        if _cnt < _SS.get(_sn, 2):
            continue
        _b = _SSB.get(_sn)
        if not _b:
            continue
        _stat, _bt, _bv = _b
        if _bt == "pct":
            if _stat == "hp":    _spct_hp  += _bv
            elif _stat == "atk": _spct_atk += _bv
            elif _stat == "def": _spct_def += _bv
            elif _stat == "spd": _spct_spd += _bv
        else:
            if _stat == "cr":    _sadd_cr  += _bv
            elif _stat == "cd":  _sadd_cd  += _bv
            elif _stat == "res": _sadd_res += _bv
            elif _stat == "acc": _sadd_acc += _bv

    # --- Building bonuses ---------------------------------------------------
    element_row = conn.execute(
        "SELECT element FROM monsters WHERE unit_id = ?", (unit_id,)
    ).fetchone()
    _elem = (element_row["element"] if element_row else None) or None
    _bb   = get_building_bonuses(conn, _elem)
    _bld_hp_pct  = float(_bb.get("hp_pct",  0))
    _bld_atk_pct = float(_bb.get("atk_pct", 0))
    _bld_def_pct = float(_bb.get("def_pct", 0))
    _bld_spd_pct = float(_bb.get("spd_pct", 0))
    _bld_cd_add  = float(_bb.get("cd_add",  0))
    _bld_cr_add  = float(_bb.get("cr_add",  0))

    # --- Final stats --------------------------------------------------------
    total_hp  = int(base_hp  * (1 + (pct["hp"]  + _spct_hp  + _bld_hp_pct)  / 100) + flat["hp"])
    total_atk = int(base_atk * (1 + (pct["atk"] + _spct_atk + _bld_atk_pct) / 100) + flat["atk"])
    total_def = int(base_def * (1 + (pct["def"] + _spct_def + _bld_def_pct) / 100) + flat["def"])
    # SPD % bonuses (Swift / totem / leader) apply to BASE speed only.
    import math as _math
    _set_spd = _math.ceil(base_spd * _spct_spd / 100) if _spct_spd else 0
    _bld_spd = int(base_spd * _bld_spd_pct / 100) if _bld_spd_pct else 0
    total_spd = int(base_spd + add["spd"] + _set_spd + _bld_spd)
    total_cr  = min(100, round(base_cr  + add["cr"]  + _sadd_cr  + _bld_cr_add, 1))
    total_cd  = round(base_cd  + add["cd"]  + _sadd_cd  + _bld_cd_add,  1)
    # RES and ACC are capped at 100% in-game
    total_res = min(100, round(base_res + add["res"] + _sadd_res, 1))
    total_acc = min(100, round(base_acc + add["acc"] + _sadd_acc, 1))

    return {
        "hp":   total_hp,
        "atk":  total_atk,
        "def_": total_def,
        "spd":  total_spd,
        "cr":   total_cr,
        "cd":   total_cd,
        "res":  total_res,
        "acc":  total_acc,
    }


def get_pvp_roster(
    conn: sqlite3.Connection,
    min_equipped_runes: int = 4,
):
    """Return built monsters with complete stats and inferred PvP capabilities."""
    from optimizer.pvp_analyzer import pvp_unit_from_data

    minimum = max(0, int(min_equipped_runes))
    if minimum:
        built_ids = {
            int(row[0])
            for row in conn.execute(
                "SELECT occupied_id FROM runes WHERE occupied_id > 0"
                " GROUP BY occupied_id HAVING COUNT(*) >= ?",
                (minimum,),
            ).fetchall()
        }
    else:
        built_ids = {monster["unit_id"] for monster in get_monsters(conn)}
    result = []
    for monster in get_monsters(conn):
        if monster["unit_id"] not in built_ids:
            continue
        stats = compute_monster_stats(conn, monster["unit_id"], include_artifacts=True)
        if stats:
            result.append(pvp_unit_from_data(monster, stats))
    return sorted(result, key=lambda unit: (-unit.speed, unit.name))


# ---------------------------------------------------------------------------
# Dungeon wave queries
# ---------------------------------------------------------------------------

def _bundled_dungeon_profiles_by_name() -> dict[str, str]:
    from optimizer.dungeon_data import load_dungeon_profile_waves
    from optimizer.dungeon_profiles import DUNGEON_PROFILES

    result = {}
    for profile_key, profile in DUNGEON_PROFILES.items():
        dungeon_name = profile.get("dungeon_key") or ""
        if dungeon_name and load_dungeon_profile_waves(profile_key):
            result[dungeon_name] = profile_key
    return result


def get_dungeon_names(conn: sqlite3.Connection) -> list[str]:
    """Return imported and bundled dungeon names."""
    rows = conn.execute(
        "SELECT DISTINCT dungeon_name FROM dungeon_waves ORDER BY dungeon_name"
    ).fetchall()
    names = {r[0] for r in rows}
    names.update(_bundled_dungeon_profiles_by_name())
    return sorted(names)


def get_dungeon_waves(
    conn: sqlite3.Connection,
    dungeon_name: str,
) -> dict[int, list[dict]]:
    """Return all waves for a dungeon as {wave_number: [monster_dict, ...]}."""
    rows = conn.execute(
        "SELECT wave_number, monster_index, monster_name, level,"
        " hp, atk, def, spd, res, acc, cr, cdmg_reduction"
        " FROM dungeon_waves"
        " WHERE dungeon_name = ?"
        " ORDER BY wave_number, monster_index",
        (dungeon_name,),
    ).fetchall()

    waves: dict[int, list[dict]] = {}
    for r in rows:
        wn = r[0]
        if wn not in waves:
            waves[wn] = []
        waves[wn].append(dict(r))
    if waves:
        return waves

    profile_key = _bundled_dungeon_profiles_by_name().get(dungeon_name)
    if not profile_key:
        return {}
    from optimizer.dungeon_data import load_dungeon_profile_waves
    return {
        wave_number: [dict(enemy) for enemy in enemies]
        for wave_number, enemies in load_dungeon_profile_waves(profile_key).items()
    }


def get_dungeon_summary(
    conn: sqlite3.Connection,
    dungeon_name: str,
) -> dict:
    """Return max/avg stats across all monsters in a dungeon."""
    row = conn.execute(
        "SELECT"
        " MAX(spd) as max_spd,"
        " MAX(res) as max_res,"
        " MAX(acc) as max_acc,"
        " MAX(hp)  as max_hp,"
        " MAX(def) as max_def,"
        " COUNT(*) as total_monsters"
        " FROM dungeon_waves WHERE dungeon_name = ?",
        (dungeon_name,),
    ).fetchone()
    result = dict(row) if row else {}
    if int(result.get("total_monsters") or 0) > 0:
        return result

    waves = get_dungeon_waves(conn, dungeon_name)
    enemies = [enemy for wave in waves.values() for enemy in wave]
    if not enemies:
        return {}
    return {
        "max_spd": max(int(enemy.get("spd") or 0) for enemy in enemies),
        "max_res": max(int(enemy.get("res") or 0) for enemy in enemies),
        "max_acc": max(int(enemy.get("acc") or 0) for enemy in enemies),
        "max_hp": max(int(enemy.get("hp") or 0) for enemy in enemies),
        "max_def": max(int(enemy.get("def") or 0) for enemy in enemies),
        "total_monsters": len(enemies),
    }


def has_dungeon_data(conn: sqlite3.Connection) -> bool:
    """True if the dungeon_waves table has been populated."""
    row = conn.execute("SELECT COUNT(*) FROM dungeon_waves").fetchone()
    return (row[0] or 0) > 0 or bool(_bundled_dungeon_profiles_by_name())


# ---------------------------------------------------------------------------
# Building bonuses
# ---------------------------------------------------------------------------

_ELEMENT_TO_INT: dict[str, int] = {
    "water": 1, "fire": 2, "wind": 3, "light": 4, "dark": 5,
}


def get_building_bonuses(
    conn: sqlite3.Connection,
    element: str | None = None,
) -> dict:
    """Return aggregate building stat bonuses for a monster of the given element.

    Returns a dict with zero-defaulted keys:
        hp_pct, atk_pct, def_pct, spd_pct   — percentage of base stat
        cd_add, cr_add                         — flat additions (percentage points)

    Pass element=None (or the monster's element string) to include element-
    specific sanctuary bonuses where applicable.
    """
    bonuses: dict[str, float] = {
        "hp_pct": 0.0, "atk_pct": 0.0, "def_pct": 0.0,
        "spd_pct": 0.0, "cd_add": 0.0, "cr_add": 0.0,
    }

    try:
        rows = conn.execute(
            "SELECT stat, element, bonus_pct FROM buildings"
        ).fetchall()
    except Exception:
        return bonuses

    elem_int = _ELEMENT_TO_INT.get((element or "").lower(), 0)

    for row in rows:
        stat      = row["stat"] if hasattr(row, "keys") else row[0]
        bld_elem  = row["element"] if hasattr(row, "keys") else row[1]
        bonus_pct = row["bonus_pct"] if hasattr(row, "keys") else row[2]

        # Include if building is universal (element=0) or matches the monster's element
        if bld_elem != 0 and bld_elem != elem_int:
            continue

        if stat in bonuses:
            bonuses[stat] += float(bonus_pct or 0.0)

    return bonuses


# ---------------------------------------------------------------------------
# Leader skill helpers
# ---------------------------------------------------------------------------

# Maps swarfarm attribute names -> bonus-dict keys used by stat_utils
_LEADER_ATTR_MAP: dict[str, str] = {
    "HP":            "hp_pct",
    "Attack Power":  "atk_pct",
    "Defense":       "def_pct",
    "Attack Speed":  "spd_pct",
    "Critical Rate": "cr_add",
    "Critical DMG":  "cd_add",
    "Accuracy":      "acc_add",
    "Resistance":    "res_add",
}

# Areas considered active in the Team Optimizer (dungeon context)
_DUNGEON_AREAS = {"General", "Dungeon", "Element"}


def get_leader_skill_monsters(conn: sqlite3.Connection) -> list[dict]:
    """Return all monsters that have a leader skill, sorted by display_name.

    Each entry is a plain dict with keys:
        unit_id, display_name, element,
        leader_skill_attribute, leader_skill_amount,
        leader_skill_area, leader_skill_element
    and a computed 'leader_skill_label' string.
    """
    rows = conn.execute(
        "SELECT unit_id, display_name, element,"
        " leader_skill_attribute, leader_skill_amount,"
        " leader_skill_area, leader_skill_element"
        " FROM monsters"
        " WHERE leader_skill_attribute IS NOT NULL"
        "   AND leader_skill_area IN ('General', 'Dungeon', 'Element')"
        " ORDER BY display_name ASC"
    ).fetchall()

    result = []
    for r in rows:
        attr    = r["leader_skill_attribute"] or ""
        amount  = r["leader_skill_amount"]    or 0
        area    = r["leader_skill_area"]      or "General"
        elem    = r["leader_skill_element"]
        if elem:
            label = "%s +%d%% (%s, %s only)" % (attr, amount, area, elem)
        else:
            label = "%s +%d%% (%s)" % (attr, amount, area)
        d = dict(r)
        d["leader_skill_label"] = label
        result.append(d)
    return result


def compute_leader_bonus(
    leader: dict | None,
    target_element: str | None,
) -> dict:
    """Compute the stat bonus a leader grants to a specific target monster.

    leader       — a monster dict (from get_leader_skill_monsters or get_monsters)
                   with leader_skill_* fields, or None.
    target_element — the target monster's element string (e.g. 'water'), or None.

    Returns a bonus dict with zero-defaulted keys matching stat_utils format:
        hp_pct, atk_pct, def_pct, spd_pct, cd_add, cr_add, res_add, acc_add
    """
    zero: dict = {
        "hp_pct": 0.0, "atk_pct": 0.0, "def_pct": 0.0, "spd_pct": 0.0,
        "cd_add": 0.0,  "cr_add": 0.0,  "res_add": 0.0, "acc_add": 0.0,
    }
    if not leader:
        return zero

    attr   = leader.get("leader_skill_attribute")
    amount = leader.get("leader_skill_amount") or 0
    area   = leader.get("leader_skill_area") or "General"
    ls_elem = leader.get("leader_skill_element")  # None = all elements

    if not attr or not amount:
        return zero

    # Area filter: only apply General, Dungeon, Element in team optimizer context
    if area not in _DUNGEON_AREAS:
        return zero

    # Element filter
    if ls_elem:
        if not target_element:
            return zero
        if ls_elem.lower() != target_element.lower():
            return zero

    stat_key = _LEADER_ATTR_MAP.get(attr)
    if not stat_key:
        return zero

    result = dict(zero)
    result[stat_key] = float(amount)
    return result


# ---------------------------------------------------------------------------
# Team config save / load
# ---------------------------------------------------------------------------

def list_team_configs(conn: sqlite3.Connection) -> list[dict]:
    """Return all saved team configs ordered by name."""
    rows = conn.execute(
        "SELECT id, name, dungeon_key, updated_at FROM team_configs ORDER BY name COLLATE NOCASE"
    ).fetchall()
    return [dict(r) for r in rows]


def save_team_config(conn: sqlite3.Connection, name: str, dungeon_key: str,
                     config_json: str, config_id: int | None = None) -> int:
    """Insert or update a team config. Returns the config id."""
    import json as _json
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    if config_id is not None:
        conn.execute(
            "UPDATE team_configs SET name=?, dungeon_key=?, config_json=?, updated_at=?"
            " WHERE id=?",
            (name, dungeon_key, config_json, now, config_id),
        )
        conn.commit()
        return config_id
    cur = conn.execute(
        "INSERT INTO team_configs (name, dungeon_key, config_json, created_at, updated_at)"
        " VALUES (?,?,?,?,?)",
        (name, dungeon_key, config_json, now, now),
    )
    conn.commit()
    return cur.lastrowid


def load_team_config(conn: sqlite3.Connection, config_id: int) -> dict | None:
    """Load a single config by id. Returns the parsed config dict or None."""
    import json as _json
    row = conn.execute(
        "SELECT id, name, dungeon_key, config_json FROM team_configs WHERE id=?",
        (config_id,),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["config"] = _json.loads(d["config_json"] or "{}")
    except Exception:
        d["config"] = {}
    return d


def delete_team_config(conn: sqlite3.Connection, config_id: int) -> None:
    conn.execute("DELETE FROM team_configs WHERE id=?", (config_id,))
    conn.commit()

# ---------------------------------------------------------------------------
# PvP plan persistence
# ---------------------------------------------------------------------------

def list_pvp_configs(conn: sqlite3.Connection) -> list[dict]:
    return [
        dict(row)
        for row in conn.execute(
            "SELECT id, name, mode, updated_at FROM pvp_configs ORDER BY name COLLATE NOCASE"
        ).fetchall()
    ]


def save_pvp_config(
    conn: sqlite3.Connection,
    name: str,
    mode: str,
    config_json: str,
    config_id: int | None = None,
) -> int:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    if config_id is not None:
        conn.execute(
            "UPDATE pvp_configs SET name=?, mode=?, config_json=?, updated_at=? WHERE id=?",
            (name, mode, config_json, now, config_id),
        )
        result_id = int(config_id)
    else:
        cursor = conn.execute(
            "INSERT INTO pvp_configs (name, mode, config_json, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (name, mode, config_json, now, now),
        )
        result_id = int(cursor.lastrowid)
    conn.commit()
    return result_id


def load_pvp_config(conn: sqlite3.Connection, config_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id, name, mode, config_json FROM pvp_configs WHERE id = ?",
        (config_id,),
    ).fetchone()
    return dict(row) if row else None


def delete_pvp_config(conn: sqlite3.Connection, config_id: int) -> None:
    conn.execute("DELETE FROM pvp_configs WHERE id = ?", (config_id,))
    conn.commit()

