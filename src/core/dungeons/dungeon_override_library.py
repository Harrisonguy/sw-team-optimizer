from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.core.dungeons.dungeon_model import DungeonEnemy, ManualDungeonOverride
from src.core.resources import DATA_DIR


OVERRIDES_FILE = DATA_DIR / "dungeon_overrides.json"


@lru_cache(maxsize=1)
def load_dungeon_overrides() -> dict[str, ManualDungeonOverride]:
    if not OVERRIDES_FILE.exists():
        return {}

    with OVERRIDES_FILE.open("r", encoding="utf-8") as file:
        raw_overrides: dict[str, dict[str, Any]] = json.load(file)

    overrides: dict[str, ManualDungeonOverride] = {}

    for key, raw in raw_overrides.items():
        wave_clear_targets = [
            _parse_override_enemy(raw_enemy)
            for raw_enemy in raw.get("wave_clear_targets", []) or []
        ]

        boss_targets = [
            _parse_override_enemy(raw_enemy)
            for raw_enemy in raw.get("boss_targets", []) or []
        ]

        override = ManualDungeonOverride(
            key=key,
            display_name=raw.get("display_name", key),
            source=raw.get("source", "manual"),
            dungeon_slug=raw.get("dungeon_slug", ""),
            floor=raw.get("floor"),
            level_id=raw.get("level_id"),
            notes=raw.get("notes"),
            max_enemy_speed=raw.get("max_enemy_speed") or 0,
            max_enemy_resistance=raw.get("max_enemy_resistance") or 0,
            wave_clear_targets=wave_clear_targets,
            boss_targets=boss_targets,
        )

        overrides[key] = override

    return overrides


def get_dungeon_override(key: str) -> ManualDungeonOverride | None:
    return load_dungeon_overrides().get(key)


def search_dungeon_overrides(search: str) -> list[ManualDungeonOverride]:
    search = search.lower().strip()

    results = []

    for key, override in load_dungeon_overrides().items():
        if (
            search in key.lower()
            or search in override.display_name.lower()
            or search in override.dungeon_slug.lower()
        ):
            results.append(override)

    return results


def _parse_override_enemy(raw_enemy: dict[str, Any]) -> DungeonEnemy:
    return DungeonEnemy(
        enemy_id=None,
        monster_id=raw_enemy.get("monster_id"),
        stars=None,
        level=None,
        hp=raw_enemy.get("hp") or 0,
        attack=raw_enemy.get("attack") or 0,
        defense=raw_enemy.get("defense") or 0,
        speed=raw_enemy.get("speed") or 0,
        resistance=raw_enemy.get("resistance") or 0,
        crit_rate_bonus=raw_enemy.get("crit_rate_bonus") or 0,
        crit_damage_reduction=raw_enemy.get("crit_damage_reduction") or 0,
        accuracy_bonus=raw_enemy.get("accuracy_bonus") or 0,
    )