"""Import dungeon wave data from dungeon_monsters_by_wave.json into the DB."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def _pct(val) -> int:
    """'54%' -> 54, 54 -> 54, None -> 0."""
    if val is None:
        return 0
    s = str(val).replace('%', '').strip()
    try:
        return int(float(s))
    except ValueError:
        return 0


def import_dungeon_data(conn: sqlite3.Connection, json_path: Path) -> int:
    """Load dungeon wave JSON into dungeon_waves table.
    
    Returns number of rows inserted.
    """
    data = json.loads(json_path.read_text(encoding='utf-8'))
    dungeons: dict = data.get('dungeons', {})

    conn.execute("DELETE FROM dungeon_waves")

    rows = []
    for dungeon_name, ddata in dungeons.items():
        waves: dict = ddata.get('waves', {})
        for wave_key, monsters in waves.items():
            wave_num = int(wave_key)
            for idx, m in enumerate(monsters):
                rows.append((
                    dungeon_name,
                    wave_num,
                    idx,
                    m.get('name') or '?',
                    m.get('level'),
                    m.get('hp'),
                    m.get('atk'),
                    m.get('def'),
                    m.get('spd'),
                    _pct(m.get('res')),
                    _pct(m.get('acc')),
                    _pct(m.get('cr')),
                    _pct(m.get('cdmg_reduction', 0)),
                ))

    conn.executemany(
        "INSERT INTO dungeon_waves"
        " (dungeon_name, wave_number, monster_index, monster_name,"
        "  level, hp, atk, def, spd, res, acc, cr, cdmg_reduction)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    return len(rows)
