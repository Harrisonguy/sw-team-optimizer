"""SQLite schema for the SW Team Optimizer desktop app."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DB_PATH = Path(
    os.environ.get(
        "SW_OPTIMIZER_DB_PATH",
        str(Path.home() / ".sw_optimizer" / "sw_optimizer.db"),
    )
).expanduser()


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def create_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS account_profiles ("
        " profile_id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " profile_name TEXT NOT NULL,"
        " wizard_id INTEGER,"
        " created_at TEXT NOT NULL,"
        " last_imported_at TEXT,"
        " UNIQUE(wizard_id)"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS app_state ("
        " key TEXT PRIMARY KEY,"
        " value TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS account ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " profile_id INTEGER,"
        " player_name TEXT NOT NULL DEFAULT 'Unknown',"
        " wizard_id INTEGER,"
        " imported_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS account_progression ("
        " progression_key TEXT PRIMARY KEY,"
        " payload TEXT NOT NULL DEFAULT 'null'"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS monsters ("
        " unit_id INTEGER PRIMARY KEY,"
        " unit_master_id INTEGER,"
        " display_name TEXT NOT NULL,"
        " base_name TEXT NOT NULL,"
        " element TEXT, archetype TEXT, natural_stars INTEGER,"
        " stars INTEGER, level INTEGER, awaken INTEGER,"
        " max_lvl_hp INTEGER, max_lvl_attack INTEGER, max_lvl_defense INTEGER,"
        " base_speed INTEGER, crit_rate INTEGER, crit_damage INTEGER,"
        " resistance INTEGER, accuracy INTEGER,"
        " skills_json TEXT NOT NULL DEFAULT '[]',"
        " skill_levels_json TEXT NOT NULL DEFAULT '{}'"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS runes ("
        " rune_id INTEGER PRIMARY KEY,"
        " set_id INTEGER, set_name TEXT, slot_no INTEGER,"
        " raw_class INTEGER, stars INTEGER, quality TEXT, original_quality TEXT,"
        " upgrade_curr INTEGER,"
        " main_stat_id INTEGER, main_stat_name TEXT, main_stat_value INTEGER,"
        " prefix_stat_id INTEGER, prefix_stat_name TEXT, prefix_stat_value INTEGER,"
        " sec_eff TEXT, substat_labels TEXT, substat_types TEXT,"
        " efficiency REAL, desirability REAL, grade TEXT,"
        " occupied_id INTEGER, occupied_name TEXT, location_label TEXT"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS artifacts ("
        " artifact_id INTEGER PRIMARY KEY,"
        " slot INTEGER, slot_label TEXT,"
        " attribute INTEGER, attribute_label TEXT,"
        " unit_style INTEGER, requirement_label TEXT,"
        " natural_rank INTEGER, rank INTEGER, level INTEGER,"
        " pri_effect TEXT, sec_effects TEXT, locked INTEGER DEFAULT 0,"
        " occupied_id INTEGER, occupied_name TEXT, location_label TEXT"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS dungeon_waves ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " dungeon_name TEXT NOT NULL,"
        " wave_number INTEGER NOT NULL,"
        " monster_index INTEGER NOT NULL,"
        " monster_name TEXT NOT NULL,"
        " level INTEGER,"
        " hp INTEGER,"
        " atk INTEGER,"
        " def INTEGER,"
        " spd INTEGER,"
        " res INTEGER,"
        " acc INTEGER,"
        " cr INTEGER,"
        " cdmg_reduction INTEGER DEFAULT 0"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS team_configs ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " name TEXT NOT NULL,"
        " created_at TEXT,"
        " updated_at TEXT,"
        " dungeon_key TEXT DEFAULT 'custom',"
        " config_json TEXT NOT NULL DEFAULT '{}'"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS pvp_configs ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " name TEXT NOT NULL,"
        " mode TEXT NOT NULL DEFAULT 'arena_offense',"
        " config_json TEXT NOT NULL DEFAULT '{}',"
        " created_at TEXT,"
        " updated_at TEXT"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS user_rune_prefs ("
        " rune_id INTEGER PRIMARY KEY,"   # same ID as runes.rune_id — survives re-import
        " locked  INTEGER DEFAULT 0,"     # 1 = excluded from optimizer pool
        " note    TEXT    DEFAULT ''"     # user memo (future use)
        ")"
    )
    for ddl in [
        "CREATE INDEX IF NOT EXISTS idx_dungeon_name   ON dungeon_waves(dungeon_name)",
        "CREATE INDEX IF NOT EXISTS idx_profiles_wizard ON account_profiles(wizard_id)",
        "CREATE INDEX IF NOT EXISTS idx_runes_slot     ON runes(slot_no)",
        "CREATE INDEX IF NOT EXISTS idx_runes_set      ON runes(set_id)",
        "CREATE INDEX IF NOT EXISTS idx_runes_grade    ON runes(grade)",
        "CREATE INDEX IF NOT EXISTS idx_runes_main     ON runes(main_stat_name)",
        "CREATE INDEX IF NOT EXISTS idx_runes_occupied ON runes(occupied_id)",
        "CREATE INDEX IF NOT EXISTS idx_art_occupied   ON artifacts(occupied_id)",
    ]:
        conn.execute(ddl)
    conn.commit()
    _add_column_if_missing(conn, "account",  "profile_id",             "INTEGER")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_account_profile ON account(profile_id)")
    conn.commit()
    _add_column_if_missing(conn, "runes",    "substat_types",          "TEXT")
    _add_column_if_missing(conn, "monsters", "leader_skill_attribute", "TEXT")
    _add_column_if_missing(conn, "monsters", "leader_skill_amount",    "INTEGER")
    _add_column_if_missing(conn, "monsters", "leader_skill_area",      "TEXT")
    _add_column_if_missing(conn, "monsters", "leader_skill_element",   "TEXT")
    _add_column_if_missing(conn, "monsters", "skills_json",            "TEXT NOT NULL DEFAULT '[]'")
    _add_column_if_missing(conn, "monsters", "skill_levels_json",      "TEXT NOT NULL DEFAULT '{}'")
    _add_column_if_missing(conn, "artifacts", "pri_effect_id",    "INTEGER")
    _add_column_if_missing(conn, "artifacts", "pri_effect_value",  "REAL")
    _add_column_if_missing(conn, "artifacts", "sec_effect_data",   "TEXT")
    _migrate_legacy_account_profile(conn)
    ensure_buildings_table(conn)
    _ensure_profile_storage_tables(conn)
    _migrate_active_profile_snapshot(conn)
    conn.commit()


def _migrate_legacy_account_profile(conn: sqlite3.Connection) -> None:
    """Register the old single-account snapshot as a profile once."""
    if conn.execute("SELECT COUNT(*) FROM account_profiles").fetchone()[0]:
        return
    row = conn.execute(
        "SELECT id, player_name, wizard_id, imported_at"
        " FROM account ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not row:
        return
    cur = conn.execute(
        "INSERT INTO account_profiles"
        " (profile_name, wizard_id, created_at, last_imported_at)"
        " VALUES (?, ?, ?, ?)",
        (row[1], row[2], row[3], row[3]),
    )
    profile_id = int(cur.lastrowid)
    conn.execute("UPDATE account SET profile_id = ? WHERE id = ?", (profile_id, row[0]))
    conn.execute(
        "INSERT INTO app_state (key, value) VALUES ('active_profile_id', ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(profile_id),),
    )
    conn.commit()


def _add_column_if_missing(conn, table, column, col_type):
    existing = {row[1] for row in conn.execute("PRAGMA table_info(%s)" % table)}
    if column not in existing:
        conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, col_type))
        conn.commit()


_PROFILE_CACHE_KEYS = {
    "monsters": "unit_id",
    "account_progression": "progression_key",
    "runes": "rune_id",
    "artifacts": "artifact_id",
    "buildings": "building_master_id",
    "team_configs": "id",
    "pvp_configs": "id",
    "user_rune_prefs": "rune_id",
}


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _table_columns(conn: sqlite3.Connection, table: str) -> list[tuple[str, str]]:
    return [(row[1], row[2] or "TEXT") for row in conn.execute(
        "PRAGMA table_info(%s)" % _quote_identifier(table)
    )]


def _profile_table_name(source_table: str) -> str:
    return "profile_" + source_table


def _ensure_profile_storage_tables(conn: sqlite3.Connection) -> None:
    """Create normalized per-profile copies of all account-owned data tables."""
    for source_table, key_column in _PROFILE_CACHE_KEYS.items():
        columns = _table_columns(conn, source_table)
        if not columns:
            continue
        profile_table = _profile_table_name(source_table)
        definitions = ['"profile_id" INTEGER NOT NULL']
        definitions.extend(
            "%s %s" % (_quote_identifier(name), col_type)
            for name, col_type in columns
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS %s (%s)"
            % (_quote_identifier(profile_table), ", ".join(definitions))
        )

        existing = {name for name, _ in _table_columns(conn, profile_table)}
        for name, col_type in columns:
            if name not in existing:
                conn.execute(
                    "ALTER TABLE %s ADD COLUMN %s %s"
                    % (
                        _quote_identifier(profile_table),
                        _quote_identifier(name),
                        col_type,
                    )
                )

        index_name = "idx_%s_profile_key" % profile_table
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS %s ON %s (%s, %s)"
            % (
                _quote_identifier(index_name),
                _quote_identifier(profile_table),
                _quote_identifier("profile_id"),
                _quote_identifier(key_column),
            )
        )


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


def save_active_profile_snapshot(
    conn: sqlite3.Connection,
    profile_id: int,
) -> None:
    """Persist the active compatibility tables into one profile's storage."""
    _ensure_profile_storage_tables(conn)
    for source_table in _PROFILE_CACHE_KEYS:
        profile_table = _profile_table_name(source_table)
        columns = [name for name, _ in _table_columns(conn, source_table)]
        if not columns:
            continue
        quoted_columns = ", ".join(_quote_identifier(name) for name in columns)
        conn.execute(
            "DELETE FROM %s WHERE profile_id = ?"
            % _quote_identifier(profile_table),
            (profile_id,),
        )
        conn.execute(
            "INSERT INTO %s (%s, %s) SELECT ?, %s FROM %s"
            % (
                _quote_identifier(profile_table),
                _quote_identifier("profile_id"),
                quoted_columns,
                quoted_columns,
                _quote_identifier(source_table),
            ),
            (profile_id,),
        )


def activate_profile(conn: sqlite3.Connection, profile_id: int) -> None:
    """Make a stored account profile active without losing the current profile."""
    profile = conn.execute(
        "SELECT profile_name, wizard_id, last_imported_at"
        " FROM account_profiles WHERE profile_id = ?",
        (profile_id,),
    ).fetchone()
    if profile is None:
        raise ValueError("Unknown account profile: %s" % profile_id)

    current_id = get_active_profile_id(conn)
    if current_id is not None and current_id != profile_id:
        save_active_profile_snapshot(conn, current_id)

    _ensure_profile_storage_tables(conn)
    if current_id != profile_id:
        for source_table in _PROFILE_CACHE_KEYS:
            profile_table = _profile_table_name(source_table)
            columns = [name for name, _ in _table_columns(conn, source_table)]
            quoted_columns = ", ".join(_quote_identifier(name) for name in columns)
            conn.execute("DELETE FROM %s" % _quote_identifier(source_table))
            conn.execute(
                "INSERT INTO %s (%s) SELECT %s FROM %s WHERE profile_id = ?"
                % (
                    _quote_identifier(source_table),
                    quoted_columns,
                    quoted_columns,
                    _quote_identifier(profile_table),
                ),
                (profile_id,),
            )

    conn.execute("DELETE FROM account")
    conn.execute(
        "INSERT INTO account (profile_id, player_name, wizard_id, imported_at)"
        " VALUES (?, ?, ?, ?)",
        (
            profile_id,
            profile[0],
            profile[1],
            profile[2] or "",
        ),
    )
    conn.execute(
        "INSERT INTO app_state (key, value) VALUES ('active_profile_id', ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(profile_id),),
    )


def _migrate_active_profile_snapshot(conn: sqlite3.Connection) -> None:
    """Capture a legacy active inventory the first time profile storage appears."""
    profile_id = get_active_profile_id(conn)
    if profile_id is None:
        return
    has_stored_rows = any(
        conn.execute(
            "SELECT 1 FROM %s WHERE profile_id = ? LIMIT 1"
            % _quote_identifier(_profile_table_name(table)),
            (profile_id,),
        ).fetchone()
        for table in _PROFILE_CACHE_KEYS
    )
    has_active_rows = any(
        conn.execute(
            "SELECT 1 FROM %s LIMIT 1" % _quote_identifier(table)
        ).fetchone()
        for table in _PROFILE_CACHE_KEYS
    )
    if has_active_rows and not has_stored_rows:
        save_active_profile_snapshot(conn, profile_id)


def ensure_buildings_table(conn: sqlite3.Connection) -> None:
    """Create/migrate the buildings table (called during import)."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS buildings ("
        " building_master_id INTEGER PRIMARY KEY,"
        " name TEXT NOT NULL DEFAULT '',"
        " stat TEXT NOT NULL DEFAULT '',"
        " element INTEGER NOT NULL DEFAULT 0,"
        " bonus_pct REAL NOT NULL DEFAULT 0.0"
        ")"
    )
