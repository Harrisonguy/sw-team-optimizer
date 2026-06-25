from __future__ import annotations
from collections import defaultdict
import json
from pathlib import Path
from typing import Any

from src.core.monsters.monster_library import (
    monster_data_from_master_id,
    monster_name_from_master_id,
)
from src.core.skills.skill_library import skill_data_from_id
from src.core.account.account_model import Account, Artifact, ArtifactEffect, Monster, Rune

def import_swex_account(path: Path) -> Account:
    """
    Import a SWEX Summoners War JSON export.

    This first version is intentionally tolerant.
    SWEX exports can vary slightly depending on game version and export source.
    """

    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError("SWEX JSON root must be an object.")
    recognized_keys = {
        "wizard_info", "unit_list", "runes", "artifacts",
        "building_list", "deco_list", "wizard_skill_list",
    }
    if not recognized_keys.intersection(data):
        raise ValueError("File does not appear to be a SWEX account export.")
    for list_key in ("unit_list", "runes", "artifacts", "building_list", "deco_list"):
        value = data.get(list_key)
        if value is not None and not isinstance(value, list):
            raise ValueError("SWEX field '%s' must be a list." % list_key)

    account = Account(
        player_name=_safe_get(data, ["wizard_info", "wizard_name"], default="Unknown"),
        wizard_id=_safe_get(data, ["wizard_info", "wizard_id"], default=None),
        raw_keys=list(data.keys()),
    )

    monsters = _parse_monsters(data)
    inventory_runes = _parse_inventory_runes(data)
    equipped_runes = _parse_equipped_runes_from_monsters(monsters)
    inventory_artifacts = _parse_inventory_artifacts(data)
    equipped_artifacts = _parse_equipped_artifacts_from_monsters(monsters)

    account.monsters = monsters
    account.inventory_runes = inventory_runes
    account.equipped_runes = equipped_runes
    account.inventory_artifacts = inventory_artifacts
    account.equipped_artifacts = equipped_artifacts

    account.building_list = data.get("building_list", []) or []
    account.deco_list = data.get("deco_list", []) or []
    account.wizard_level = _safe_get(data, ["wizard_info", "wizard_level"], default=None)
    account.wizard_skill_list = data.get("wizard_skill_list", {}) or {}
    account.guild_level = _safe_get(data, ["guild", "guild_info", "level"], default=None)
    account.guild_skill_info = _safe_get(
        data, ["guild", "guild_info", "skill_info"], default={}
    ) or {}

    return account

def _parse_monsters(data: dict[str, Any]) -> list[Monster]:
    raw_monsters = data.get("unit_list", []) or []

    monsters: list[Monster] = []

    for raw in raw_monsters:
        unit_id = raw.get("unit_id")
        if unit_id is None:
            continue

        unit_master_id = raw.get("unit_master_id")
        static_data = monster_data_from_master_id(unit_master_id)

        base_name = monster_name_from_master_id(unit_master_id)

        runes = raw.get("runes", []) or []
        artifacts = raw.get("artifacts", []) or []

        equipped_rune_ids = [
            rune.get("rune_id")
            for rune in runes
            if rune.get("rune_id") is not None
        ]

        equipped_artifact_ids = [
            artifact.get("rid") or artifact.get("artifact_id")
            for artifact in artifacts
            if artifact.get("rid") is not None or artifact.get("artifact_id") is not None
        ]

        monster = Monster(
            unit_id=unit_id,
            unit_master_id=unit_master_id,
            base_name=base_name,
            display_name=base_name,
            level=raw.get("unit_level"),
            stars=raw.get("class"),
            awaken=raw.get("awaken"),
            class_level=raw.get("class"),
            con=raw.get("con"),
            equipped_rune_ids=equipped_rune_ids,
            equipped_artifact_ids=equipped_artifact_ids,
            raw=raw,
        )

        if static_data:
            monster.element = static_data.element
            monster.archetype = static_data.archetype
            monster.natural_stars = static_data.natural_stars
            monster.base_stars = static_data.base_stars
            monster.awaken_level = static_data.awaken_level
            monster.awaken_bonus = static_data.awaken_bonus

            monster.base_hp = static_data.base_hp
            monster.base_attack = static_data.base_attack
            monster.base_defense = static_data.base_defense
            monster.base_speed = static_data.base_speed

            monster.crit_rate = static_data.crit_rate
            monster.crit_damage = static_data.crit_damage
            monster.resistance = static_data.resistance
            monster.accuracy = static_data.accuracy

            monster.max_lvl_hp = static_data.max_lvl_hp
            monster.max_lvl_attack = static_data.max_lvl_attack
            monster.max_lvl_defense = static_data.max_lvl_defense

            monster.image_filename = static_data.image_filename
            monster.bestiary_slug = static_data.bestiary_slug

            monster.skills = static_data.skills
            raw_skill_levels = {
                int(item[0]): int(item[1])
                for item in (raw.get("skills") or [])
                if isinstance(item, (list, tuple)) and len(item) >= 2
            }
            monster.skill_levels = {
                int(skill_id): int(
                    raw_skill_levels.get(skill.com2us_id, 1)
                    if skill is not None and skill.com2us_id is not None
                    else 1
                )
                for skill_id in monster.skills
                for skill in [skill_data_from_id(skill_id)]
            }
            monster.skill_ups_to_max = static_data.skill_ups_to_max
            monster.leader_skill = static_data.leader_skill

        monsters.append(monster)

    _assign_duplicate_display_names(monsters)

    return monsters

def _assign_duplicate_display_names(monsters: list[Monster]) -> None:
    """
    Assign display names like:
    Lushen
    Lushen #2
    Lushen #3

    Internal identity must always remain unit_id.
    """

    grouped: dict[str, list[Monster]] = defaultdict(list)

    for monster in monsters:
        grouped[monster.base_name].append(monster)

    for base_name, copies in grouped.items():
        copies.sort(key=lambda monster: monster.unit_id)

        duplicate_count = len(copies)

        for index, monster in enumerate(copies, start=1):
            monster.duplicate_index = index
            monster.duplicate_count = duplicate_count

            if duplicate_count == 1:
                monster.display_name = base_name
            else:
                monster.display_name = f"{base_name} #{index}"

def _parse_equipped_runes_from_monsters(monsters: list[Monster]) -> list[Rune]:
    equipped_runes: list[Rune] = []

    for monster in monsters:
        raw_runes = monster.raw.get("runes", []) or []

        for raw in raw_runes:
            rune_id = raw.get("rune_id")
            if rune_id is None:
                continue

            rune = Rune(
                rune_id=rune_id,
                set_id=raw.get("set_id"),
                slot_no=raw.get("slot_no"),
                raw_class=raw.get("class"),
                rank=raw.get("rank"),
                extra=raw.get("extra"),
                upgrade_curr=raw.get("upgrade_curr"),
                pri_eff=raw.get("pri_eff", []),
                prefix_eff=raw.get("prefix_eff", []),
                sec_eff=raw.get("sec_eff", []),
                occupied_id=raw.get("occupied_id"),
                source="inventory",
            )

            equipped_runes.append(rune)

    return equipped_runes

def _parse_inventory_runes(data: dict[str, Any]) -> list[Rune]:
    raw_runes = data.get("runes", []) or []

    inventory_runes: list[Rune] = []

    for raw in raw_runes:
        rune_id = raw.get("rune_id")
        if rune_id is None:
            continue

        rune = Rune(
            rune_id=rune_id,
            set_id=raw.get("set_id"),
            slot_no=raw.get("slot_no"),
            raw_class=raw.get("class"),
            rank=raw.get("rank"),
            extra=raw.get("extra"),
            upgrade_curr=raw.get("upgrade_curr"),
            pri_eff=raw.get("pri_eff", []),
            prefix_eff=raw.get("prefix_eff", []),
            sec_eff=raw.get("sec_eff", []),
            occupied_id=raw.get("occupied_id"),
            source="inventory",
        )
        inventory_runes.append(rune)

    return inventory_runes

def _parse_equipped_artifacts_from_monsters(monsters: list[Monster]) -> list[Artifact]:
    equipped_artifacts: list[Artifact] = []

    for monster in monsters:
        raw_artifacts = monster.raw.get("artifacts", []) or []

        for raw in raw_artifacts:
            artifact_id = raw.get("rid") or raw.get("artifact_id")
            if artifact_id is None:
                continue

            pri_effect = _parse_artifact_effect(raw.get("pri_effect"))

            sec_effects = []
            for raw_effect in raw.get("sec_effects", []) or []:
                effect = _parse_artifact_effect(raw_effect)
                if effect:
                    sec_effects.append(effect)

            artifact = Artifact(
                artifact_id=artifact_id,
                slot=raw.get("slot"),
                type=raw.get("type"),
                attribute=raw.get("attribute"),
                unit_style=raw.get("unit_style"),
                natural_rank=raw.get("natural_rank"),
                rank=raw.get("rank"),
                level=raw.get("level"),
                pri_effect=pri_effect,
                sec_effects=sec_effects,
                locked=bool(raw.get("locked", 0)),
                source_id=raw.get("source"),
                occupied_id=monster.unit_id,
                source="equipped",
                raw=raw,
            )

            equipped_artifacts.append(artifact)

    return equipped_artifacts

def _parse_inventory_artifacts(data: dict[str, Any]) -> list[Artifact]:
    raw_artifacts = (
        data.get("artifacts")
        or data.get("artifact_list")
        or []
    )

    inventory_artifacts: list[Artifact] = []

    for raw in raw_artifacts:
        artifact_id = raw.get("rid") or raw.get("artifact_id")
        if artifact_id is None:
            continue

        pri_effect = _parse_artifact_effect(raw.get("pri_effect"))

        sec_effects = []
        for raw_effect in raw.get("sec_effects", []) or []:
            effect = _parse_artifact_effect(raw_effect)
            if effect:
                sec_effects.append(effect)

        artifact = Artifact(
            artifact_id=artifact_id,
            slot=raw.get("slot"),
            type=raw.get("type"),
            attribute=raw.get("attribute"),
            unit_style=raw.get("unit_style"),
            natural_rank=raw.get("natural_rank"),
            rank=raw.get("rank"),
            level=raw.get("level"),
            pri_effect=pri_effect,
            sec_effects=sec_effects,
            locked=bool(raw.get("locked", 0)),
            source_id=raw.get("source"),
            occupied_id=raw.get("occupied_id"),
            source="inventory",
            raw=raw,
        )

        inventory_artifacts.append(artifact)

    return inventory_artifacts

def _parse_artifact_effect(raw_effect: list[Any] | None) -> ArtifactEffect | None:
    """
    Artifact effects appear as:
    [effect_id, value, roll_count, grind_value, extra_value]

    Example:
    [100, 1500, 15, 0, 0]
    [218, 0.1, 0, 0, 0]
    """
    if not raw_effect or len(raw_effect) < 2:
        return None

    return ArtifactEffect(
        effect_id=int(raw_effect[0]),
        value=raw_effect[1],
        roll_count=raw_effect[2] if len(raw_effect) > 2 else None,
        grind_value=raw_effect[3] if len(raw_effect) > 3 else None,
        extra_value=raw_effect[4] if len(raw_effect) > 4 else None,
    )

def _safe_get(data: dict[str, Any], path: list[str], default: Any = None) -> Any:
    current: Any = data

    for key in path:
        if not isinstance(current, dict):
            return default

        if key not in current:
            return default

        current = current[key]

    return current