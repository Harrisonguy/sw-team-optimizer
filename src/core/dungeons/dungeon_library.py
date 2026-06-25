from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.core.resources import DATA_DIR
from src.core.dungeons.dungeon_model import (
    DungeonEnemy,
    DungeonLevelProfile,
    DungeonSummary,
    DungeonWave,
)


DUNGEONS_FILE = DATA_DIR / "dungeons.json"
LEVELS_FILE = DATA_DIR / "levels.json"


@lru_cache(maxsize=1)
def load_dungeon_summaries() -> dict[int, DungeonSummary]:
    if not DUNGEONS_FILE.exists():
        return {}

    with DUNGEONS_FILE.open("r", encoding="utf-8") as file:
        raw_dungeons: list[dict[str, Any]] = json.load(file)

    summaries: dict[int, DungeonSummary] = {}

    for raw in raw_dungeons:
        dungeon_id = raw.get("id")

        if dungeon_id is None:
            continue

        summaries[int(dungeon_id)] = DungeonSummary(
            dungeon_id=int(dungeon_id),
            name=raw.get("name", f"Dungeon {dungeon_id}"),
            slug=raw.get("slug", f"dungeon-{dungeon_id}"),
            category=raw.get("category"),
            icon=raw.get("icon"),
            level_ids=raw.get("levels") or [],
        )

    return summaries


@lru_cache(maxsize=1)
def load_raw_levels() -> dict[int, dict[str, Any]]:
    if not LEVELS_FILE.exists():
        return {}

    with LEVELS_FILE.open("r", encoding="utf-8") as file:
        raw_levels: list[dict[str, Any]] = json.load(file)

    return {
        int(level["id"]): level
        for level in raw_levels
        if level.get("id") is not None
    }


def get_dungeon_by_slug(slug: str) -> DungeonSummary | None:
    slug = slug.lower().strip()

    for dungeon in load_dungeon_summaries().values():
        if dungeon.slug.lower() == slug:
            return dungeon

    return None


def search_dungeons(search: str) -> list[DungeonSummary]:
    search = search.lower().strip()

    results = []

    for dungeon in load_dungeon_summaries().values():
        if (
            search in dungeon.name.lower()
            or search in dungeon.slug.lower()
            or search in str(dungeon.dungeon_id)
        ):
            results.append(dungeon)

    return results


def get_level_by_id(level_id: int) -> DungeonLevelProfile | None:
    raw_levels = load_raw_levels()
    raw_level = raw_levels.get(int(level_id))

    if not raw_level:
        return None

    dungeon_id = raw_level.get("dungeon")
    dungeon_summary = load_dungeon_summaries().get(dungeon_id)

    if dungeon_summary is None:
        dungeon_name = f"Dungeon {dungeon_id}"
        dungeon_slug = f"dungeon-{dungeon_id}"
    else:
        dungeon_name = dungeon_summary.name
        dungeon_slug = dungeon_summary.slug

    return parse_level_profile(
        raw_level=raw_level,
        dungeon_name=dungeon_name,
        dungeon_slug=dungeon_slug,
    )


def get_levels_for_dungeon(dungeon: DungeonSummary) -> list[DungeonLevelProfile]:
    levels = []

    for level_id in dungeon.level_ids:
        level = get_level_by_id(level_id)

        if level:
            levels.append(level)

    return levels


def get_levels_for_dungeon_slug(slug: str) -> list[DungeonLevelProfile]:
    dungeon = get_dungeon_by_slug(slug)

    if not dungeon:
        return []

    return get_levels_for_dungeon(dungeon)


def parse_level_profile(
    raw_level: dict[str, Any],
    dungeon_name: str,
    dungeon_slug: str,
) -> DungeonLevelProfile:
    waves: list[DungeonWave] = []

    for wave_index, raw_wave in enumerate(raw_level.get("waves", []) or [], start=1):
        enemies: list[DungeonEnemy] = []

        for raw_enemy in raw_wave.get("enemies", []) or []:
            enemy = DungeonEnemy(
                enemy_id=raw_enemy.get("id"),
                monster_id=raw_enemy.get("monster"),
                stars=raw_enemy.get("stars"),
                level=raw_enemy.get("level"),
                hp=raw_enemy.get("hp") or 0,
                attack=raw_enemy.get("attack") or 0,
                defense=raw_enemy.get("defense") or 0,
                speed=raw_enemy.get("speed") or 0,
                resistance=raw_enemy.get("resist") or 0,
                crit_rate_bonus=raw_enemy.get("crit_bonus") or 0,
                crit_damage_reduction=raw_enemy.get("crit_damage_reduction") or 0,
                accuracy_bonus=raw_enemy.get("accuracy_bonus") or 0,
            )

            enemies.append(enemy)

        waves.append(
            DungeonWave(
                wave_number=wave_index,
                enemies=enemies,
            )
        )

    return DungeonLevelProfile(
        level_id=raw_level["id"],
        dungeon_id=raw_level["dungeon"],
        dungeon_name=dungeon_name,
        dungeon_slug=dungeon_slug,
        floor=raw_level.get("floor"),
        difficulty=raw_level.get("difficulty"),
        energy_cost=raw_level.get("energy_cost"),
        total_slots=raw_level.get("total_slots"),
        waves=waves,
    )