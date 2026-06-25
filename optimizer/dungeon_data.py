"""Bundled dungeon wave access for optimizer profiles."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

from src.core.dungeons.dungeon_library import get_level_by_id


_PROFILE_LEVELS: dict[str, tuple[int, float]] = {
    "gb_b10": (364, 1.0),
    "gb_abyss_normal": (798, 1.0),
    "gb_abyss_hard": (799, 1.0),
    "db_b10": (374, 1.0),
    "db_abyss_normal": (800, 1.0),
    "db_abyss_hard": (801, 1.0),
    "nb_b10": (384, 1.0),
    "nb_abyss_normal": (812, 1.0),
    "nb_abyss_hard": (813, 1.0),
    "sf_b10": (703, 1.0),
    "sf_abyss_normal": (703, 1.15),
    "sf_abyss_hard": (703, 1.30),
    "pc_b10": (705, 1.0),
    "pc_abyss_normal": (705, 1.15),
    "pc_abyss_hard": (705, 1.30),
    "abyss_b10": (811, 1.0),
    "abyss_normal": (850, 1.0),
    "abyss_hard": (849, 1.0),
}


@lru_cache(maxsize=1)
def _monster_names_by_id() -> dict[int, str]:
    path = Path(__file__).resolve().parents[1] / "data" / "monsters.json"
    if not path.exists():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {
        int(row["id"]): str(row.get("name") or "Enemy")
        for row in rows
        if row.get("id") is not None
    }


@lru_cache(maxsize=None)
def load_dungeon_profile_waves(profile_key: str) -> dict[int, list[dict]]:
    """Return normalized bundled wave data for a Team Optimizer profile.

    Steel Fortress and Punisher's Crypt do not have complete separate Abyss
    records in the bundled source, so their Abyss profiles use conservative
    scaled B10 enemy stats.
    """
    mapping = _PROFILE_LEVELS.get(profile_key)
    if mapping is None:
        return {}
    level_id, scale = mapping
    level = get_level_by_id(level_id)
    if level is None:
        return {}

    waves: dict[int, list[dict]] = {}
    for wave in level.waves:
        rows = []
        for enemy in wave.enemies:
            rows.append(
                {
                    "monster_name": (
                        _monster_names_by_id().get(
                            int(enemy.monster_id),
                            "Monster %s" % enemy.monster_id,
                        )
                        if enemy.monster_id is not None
                        else "Enemy"
                    ),
                    "monster_id": enemy.monster_id,
                    "hp": int(round(enemy.hp * scale)),
                    "atk": int(round(enemy.attack * scale)),
                    "def": int(round(enemy.defense * scale)),
                    "spd": int(enemy.speed),
                    "res": int(enemy.resistance),
                    "acc": int(enemy.accuracy_bonus),
                    "cr": int(enemy.crit_rate_bonus),
                    "cdmg_reduction": int(enemy.crit_damage_reduction),
                }
            )
        waves[int(wave.wave_number)] = rows
    return waves
