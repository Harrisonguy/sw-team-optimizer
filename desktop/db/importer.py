"""Import a parsed Account object into the SQLite database."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.core.account.account_model import Account, Artifact, Rune
from src.core.runes.rune_decode import rune_stars_from_class
from src.core.runes.rune_constants import rune_stat_name
from optimizer.sell_analyzer import score_rune
from desktop.db.schema import (
    DB_PATH,
    activate_profile,
    create_tables,
    get_connection,
    save_active_profile_snapshot,
)


def _artifact_slot_label(art: Artifact) -> str:
    """
    In SWEX, 'type' (1=Attribute, 2=Type) is the artifact category.
    'slot' is the equipped-position (1 or 2 when on a monster, 0 in storage).
    Use 'type' so storage artifacts get the correct label.
    """
    t = art.type if art.type else art.slot
    if t == 1:
        return "Attribute"
    if t == 2:
        return "Type"
    return "Unknown"


def _upsert_profile(conn: sqlite3.Connection, account: Account, now: str) -> int:
    """Create or update the persistent profile registry entry for an import."""
    row = None
    if account.wizard_id is not None:
        row = conn.execute(
            "SELECT profile_id FROM account_profiles WHERE wizard_id = ?",
            (account.wizard_id,),
        ).fetchone()
    if row is None and account.wizard_id is None:
        row = conn.execute(
            "SELECT profile_id FROM account_profiles"
            " WHERE wizard_id IS NULL AND profile_name = ?"
            " ORDER BY profile_id LIMIT 1",
            (account.player_name,),
        ).fetchone()

    if row is not None:
        profile_id = int(row[0])
        conn.execute(
            "UPDATE account_profiles SET profile_name = ?, last_imported_at = ?"
            " WHERE profile_id = ?",
            (account.player_name, now, profile_id),
        )
    else:
        cur = conn.execute(
            "INSERT INTO account_profiles"
            " (profile_name, wizard_id, created_at, last_imported_at)"
            " VALUES (?, ?, ?, ?)",
            (account.player_name, account.wizard_id, now, now),
        )
        profile_id = int(cur.lastrowid)

    return profile_id


def import_account(account: Account, db_path: Path | None = None) -> int:
    """Import an account, retain every profile, and return its profile ID."""
    conn = get_connection(db_path or DB_PATH)
    create_tables(conn)
    now = datetime.now(timezone.utc).isoformat()
    ref = _load_building_ref()

    with conn:
        profile_id = _upsert_profile(conn, account, now)
        activate_profile(conn, profile_id)

        conn.execute("DELETE FROM artifacts")
        conn.execute("DELETE FROM account_progression")
        conn.execute("DELETE FROM runes")
        conn.execute("DELETE FROM monsters")
        conn.execute("DELETE FROM account")

        conn.execute(
            "INSERT INTO account"
            " (profile_id, player_name, wizard_id, imported_at) VALUES (?, ?, ?, ?)",
            (profile_id, account.player_name, account.wizard_id, now),
        )
        progression_values = {
            "wizard_level": account.wizard_level,
            "wizard_skill_list": account.wizard_skill_list,
            "guild_level": account.guild_level,
            "guild_skill_info": account.guild_skill_info,
            "deco_list": account.deco_list,
        }
        conn.executemany(
            "INSERT INTO account_progression (progression_key, payload) VALUES (?, ?)",
            [
                (key, json.dumps(value))
                for key, value in progression_values.items()
            ],
        )

        for m in account.monsters:
            _ls = m.leader_skill
            conn.execute(
                "INSERT INTO monsters ("
                " unit_id, unit_master_id, display_name, base_name,"
                " element, archetype, natural_stars, stars, level, awaken,"
                " max_lvl_hp, max_lvl_attack, max_lvl_defense, base_speed,"
                " crit_rate, crit_damage, resistance, accuracy,"
                " leader_skill_attribute, leader_skill_amount,"
                " leader_skill_area, leader_skill_element,"
                " skills_json, skill_levels_json"
                ") VALUES (?,?,?,?, ?,?,?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?)",
                (
                    m.unit_id, m.unit_master_id, m.display_name, m.base_name,
                    m.element, m.archetype, m.natural_stars, m.stars, m.level, m.awaken,
                    m.max_lvl_hp, m.max_lvl_attack, m.max_lvl_defense, m.base_speed,
                    m.crit_rate, m.crit_damage, m.resistance, m.accuracy,
                    _ls.attribute if _ls else None,
                    _ls.amount if _ls else None,
                    _ls.area if _ls else None,
                    _ls.element if _ls else None,
                    json.dumps(m.skills),
                    json.dumps(m.skill_levels),
                ),
            )

        id_to_name = {m.unit_id: m.display_name for m in account.monsters}

        for rune in account.equipped_runes + account.inventory_runes:
            _insert_rune(conn, rune, id_to_name)

        # Inventory artifacts come first so equipped location data wins.
        for art in account.inventory_artifacts + account.equipped_artifacts:
            _insert_artifact(conn, art, id_to_name)

        import_buildings(account.building_list or [], conn, ref=ref)
        save_active_profile_snapshot(conn, profile_id)

    conn.close()
    return profile_id

def _insert_rune(conn: sqlite3.Connection, rune: Rune, id_to_name: dict) -> None:
    scored   = score_rune(rune)
    stars    = rune_stars_from_class(rune.raw_class)

    main_id  = rune.pri_eff[0]    if rune.pri_eff    and len(rune.pri_eff)    >= 1 else None
    main_val = rune.pri_eff[1]    if rune.pri_eff    and len(rune.pri_eff)    >= 2 else None
    pfx_id   = rune.prefix_eff[0] if rune.prefix_eff and len(rune.prefix_eff) >= 1 else None
    pfx_val  = rune.prefix_eff[1] if rune.prefix_eff and len(rune.prefix_eff) >= 2 else None

    has_prefix = bool(pfx_id and pfx_id != 0 and pfx_val and pfx_val != 0)
    main_type  = rune_stat_name(main_id) if main_id is not None else None
    pfx_type   = rune_stat_name(pfx_id)  if (has_prefix and pfx_id) else None

    sub_types = []
    for sub in (rune.sec_eff or []):
        if sub and len(sub) >= 1 and sub[0]:
            sub_types.append(rune_stat_name(sub[0]))
    substat_types_str = "|".join(sub_types)

    occ_name = id_to_name.get(rune.occupied_id or -1, "")
    loc      = ("Equipped on " + occ_name) if occ_name else "Storage"

    conn.execute(
        "INSERT OR REPLACE INTO runes ("
        " rune_id, set_id, set_name, slot_no, raw_class, stars,"
        " quality, original_quality, upgrade_curr,"
        " main_stat_id, main_stat_name, main_stat_value,"
        " prefix_stat_id, prefix_stat_name, prefix_stat_value,"
        " sec_eff, substat_labels, substat_types,"
        " efficiency, desirability, grade,"
        " occupied_id, occupied_name, location_label"
        ") VALUES (?,?,?,?,?,?, ?,?,?, ?,?,?, ?,?,?, ?,?,?, ?,?,?, ?,?,?)",
        (
            rune.rune_id, rune.set_id, rune.set_name, rune.slot_no,
            rune.raw_class, stars,
            rune.current_quality, rune.original_quality, rune.upgrade_curr,
            main_id, main_type, main_val,
            pfx_id  if has_prefix else None,
            pfx_type,
            pfx_val if has_prefix else None,
            json.dumps(rune.sec_eff),
            json.dumps(rune.substat_labels),
            substat_types_str,
            scored["efficiency"], scored["desirability"], scored["grade"],
            rune.occupied_id, occ_name, loc,
        ),
    )


def _insert_artifact(conn: sqlite3.Connection, art: Artifact, id_to_name: dict) -> None:
    slot_label = _artifact_slot_label(art)
    pri_label  = art.pri_effect.label if art.pri_effect else None
    pri_eff_id  = art.pri_effect.effect_id if art.pri_effect else None
    pri_eff_val = art.pri_effect.total_value if art.pri_effect else None
    sec_labels = [e.label for e in (art.sec_effects or [])]
    sec_data = [
        {
            "effect_id": int(effect.effect_id),
            "value": float(effect.total_value),
            "roll_count": effect.roll_count,
        }
        for effect in (art.sec_effects or [])
    ]
    occ_name   = id_to_name.get(art.occupied_id or -1, "")
    loc        = ("Equipped on " + occ_name) if occ_name else "Storage"

    conn.execute(
        "INSERT OR REPLACE INTO artifacts ("
        " artifact_id, slot, slot_label, attribute, attribute_label,"
        " unit_style, requirement_label, natural_rank, rank, level,"
        " pri_effect, sec_effects, sec_effect_data, locked,"
        " occupied_id, occupied_name, location_label,"
        " pri_effect_id, pri_effect_value"
        ") VALUES (?,?,?,?,?, ?,?,?,?,?, ?,?,?,?, ?,?,?, ?,?)",
        (
            art.artifact_id, art.slot, slot_label,
            art.attribute, art.attribute_label,
            art.unit_style, art.requirement_label,
            art.natural_rank, art.rank, art.level,
            pri_label, json.dumps(sec_labels), json.dumps(sec_data), int(art.locked),
            art.occupied_id, occ_name, loc,
            pri_eff_id, pri_eff_val,
        ),
    )


# ---------------------------------------------------------------------------
# Building bonus import
# ---------------------------------------------------------------------------

def _load_building_ref() -> dict:
    """Load buildings.json reference — maps building_master_id (str) → bonus info."""
    import json as _json
    ref_path = Path(__file__).resolve().parents[2] / "data" / "buildings.json"
    if not ref_path.exists():
        return {}
    with ref_path.open("r", encoding="utf-8") as f:
        data = _json.load(f)
    # Strip comment key
    return {k: v for k, v in data.items() if not k.startswith("_")}


def import_buildings(building_list: list, conn, ref: dict | None = None) -> int:
    """Import building bonuses into the buildings table.

    Only inserts rows for building_master_ids that appear in buildings.json.
    Returns count of buildings imported.
    """
    from desktop.db.schema import ensure_buildings_table
    ensure_buildings_table(conn)
    conn.execute("DELETE FROM buildings")

    if ref is None:
        ref = _load_building_ref()

    count = 0
    for entry in building_list:
        mid = entry.get("building_master_id")
        if mid is None:
            continue
        info = ref.get(str(mid))
        if info is None:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO buildings "
            "(building_master_id, name, stat, element, bonus_pct) VALUES (?,?,?,?,?)",
            (int(mid), info.get("name", ""), info.get("stat", ""),
             int(info.get("element", 0)), float(info.get("bonus_pct", 0.0))),
        )
        count += 1
    return count
