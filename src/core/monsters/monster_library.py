from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src.core.resources import DATA_DIR


MONSTER_DATA_FILE = DATA_DIR / "monsters.json"


class LeaderSkillData(BaseModel):
    id: int | None = None
    attribute: str | None = None
    amount: int | None = None
    area: str | None = None
    element: str | None = None


class MonsterStaticData(BaseModel):
    com2us_id: int
    swarfarm_id: int | None = None

    name: str
    element: str | None = None
    archetype: str | None = None

    family_id: int | None = None
    skill_group_id: int | None = None

    base_stars: int | None = None
    natural_stars: int | None = None
    awaken_level: int | None = None
    awaken_bonus: str | None = None

    base_hp: int | None = None
    base_attack: int | None = None
    base_defense: int | None = None
    base_speed: int | None = None

    crit_rate: int | None = None
    crit_damage: int | None = None
    resistance: int | None = None
    accuracy: int | None = None

    max_lvl_hp: int | None = None
    max_lvl_attack: int | None = None
    max_lvl_defense: int | None = None

    image_filename: str | None = None
    bestiary_slug: str | None = None

    skills: list[int] = Field(default_factory=list)
    skill_ups_to_max: int | None = None

    leader_skill: LeaderSkillData | None = None

    obtainable: bool | None = None
    fusion_food: bool | None = None
    homunculus: bool | None = None


@lru_cache(maxsize=1)
def load_monster_data_map() -> dict[int, MonsterStaticData]:
    """
    Load local Swarfarm monster data and return:

    com2us_id -> MonsterStaticData

    SWEX unit_master_id maps to Swarfarm com2us_id.
    """

    if not MONSTER_DATA_FILE.exists():
        return {}

    with MONSTER_DATA_FILE.open("r", encoding="utf-8") as file:
        monsters: list[dict[str, Any]] = json.load(file)

    data_map: dict[int, MonsterStaticData] = {}

    for raw in monsters:
        com2us_id = raw.get("com2us_id")
        name = raw.get("name")

        if com2us_id is None or not name:
            continue

        raw_leader_skill = raw.get("leader_skill")
        leader_skill = None

        if isinstance(raw_leader_skill, dict):
            leader_skill = LeaderSkillData(
                id=raw_leader_skill.get("id"),
                attribute=raw_leader_skill.get("attribute"),
                amount=raw_leader_skill.get("amount"),
                area=raw_leader_skill.get("area"),
                element=raw_leader_skill.get("element"),
            )

        monster_data = MonsterStaticData(
            com2us_id=int(com2us_id),
            swarfarm_id=raw.get("id"),
            name=str(name),
            element=raw.get("element"),
            archetype=raw.get("archetype"),
            family_id=raw.get("family_id"),
            skill_group_id=raw.get("skill_group_id"),
            base_stars=raw.get("base_stars"),
            natural_stars=raw.get("natural_stars"),
            awaken_level=raw.get("awaken_level"),
            awaken_bonus=raw.get("awaken_bonus"),
            base_hp=raw.get("base_hp"),
            base_attack=raw.get("base_attack"),
            base_defense=raw.get("base_defense"),
            base_speed=raw.get("speed"),
            crit_rate=raw.get("crit_rate"),
            crit_damage=raw.get("crit_damage"),
            resistance=raw.get("resistance"),
            accuracy=raw.get("accuracy"),
            max_lvl_hp=raw.get("max_lvl_hp"),
            max_lvl_attack=raw.get("max_lvl_attack"),
            max_lvl_defense=raw.get("max_lvl_defense"),
            image_filename=raw.get("image_filename"),
            bestiary_slug=raw.get("bestiary_slug"),
            skills=raw.get("skills") or [],
            skill_ups_to_max=raw.get("skill_ups_to_max"),
            leader_skill=leader_skill,
            obtainable=raw.get("obtainable"),
            fusion_food=raw.get("fusion_food"),
            homunculus=raw.get("homunculus"),
        )

        data_map[int(com2us_id)] = monster_data

    return data_map


def monster_data_from_master_id(
    unit_master_id: int | None,
) -> MonsterStaticData | None:
    if unit_master_id is None:
        return None

    return load_monster_data_map().get(int(unit_master_id))


def monster_name_from_master_id(unit_master_id: int | None) -> str:
    monster_data = monster_data_from_master_id(unit_master_id)

    if monster_data:
        return monster_data.name

    if unit_master_id is None:
        return "Unknown Monster"

    return f"Monster {unit_master_id}"