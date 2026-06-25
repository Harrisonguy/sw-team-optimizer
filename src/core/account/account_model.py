from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.core.runes.rune_constants import rune_set_name, rune_stat_name

from src.core.runes.rune_decode import (
    quality_name,
    rune_stars_label,
    rune_type_label,
)

from src.core.monsters.monster_library import LeaderSkillData

from src.core.artifacts.artifact_constants import (
    artifact_attribute_name,
    artifact_effect_name,
    artifact_quality_name,
    artifact_unit_style_name,
)

class Rune(BaseModel):
    rune_id: int
    set_id: int | None = None
    slot_no: int | None = None

    raw_class: int | None = None
    rank: int | None = None
    extra: int | None = None

    upgrade_curr: int | None = None

    pri_eff: list[Any] = Field(default_factory=list)
    prefix_eff: list[Any] = Field(default_factory=list)
    sec_eff: list[Any] = Field(default_factory=list)

    occupied_id: int | None = None
    source: str = "unknown"

    @property
    def rune_type(self) -> str:
        return rune_type_label(self.raw_class)

    @property
    def stars_label(self) -> str:
        return rune_stars_label(self.raw_class)

    @property
    def current_quality(self) -> str:
        return quality_name(self.rank)

    @property
    def original_quality(self) -> str:
        return quality_name(self.extra)
    
    @property
    def set_name(self) -> str:
        return rune_set_name(self.set_id)

    @property
    def main_stat_label(self) -> str:
        """
        SWEX pri_eff usually looks like:
        [stat_id, value]
        Example:
        [4, 63] = ATK% +63
        """
        if not self.pri_eff or len(self.pri_eff) < 2:
            return "No main stat"

        stat_id = self.pri_eff[0]
        value = self.pri_eff[1]

        return f"{rune_stat_name(stat_id)} +{value}"

    @property
    def prefix_stat_label(self) -> str:
        """
        SWEX prefix_eff usually looks like:
        [stat_id, value]

        [0, 0] means no innate/prefix stat.
        """
        if not self.prefix_eff or len(self.prefix_eff) < 2:
            return "No prefix"

        stat_id = self.prefix_eff[0]
        value = self.prefix_eff[1]

        if stat_id == 0 or value == 0:
            return "No prefix"

        return f"{rune_stat_name(stat_id)} +{value}"

    @property
    def substat_labels(self) -> list[str]:
        """
        SWEX sec_eff usually looks like:
        [
            [stat_id, value, enchanted, grind_value],
            ...
        ]

        Example:
        [8, 18, 0, 5] = SPD +18 with +5 grind
        """
        labels: list[str] = []

        for sub in self.sec_eff:
            if not sub or len(sub) < 2:
                continue

            stat_id = sub[0]
            value = sub[1]
            grind_value = sub[3] if len(sub) >= 4 else 0

            base_label = f"{rune_stat_name(stat_id)} +{value}"

            if grind_value:
                base_label += f" (+{grind_value} grind)"

            labels.append(base_label)

        return labels

    @property
    def location_label(self) -> str:
        if self.occupied_id and self.occupied_id > 0:
            return f"Equipped on monster unit_id {self.occupied_id}"
        return "Storage"


class ArtifactEffect(BaseModel):
    effect_id: int
    value: float
    roll_count: int | None = None
    grind_value: float | None = None
    extra_value: float | None = None

    @property
    def name(self) -> str:
        return artifact_effect_name(self.effect_id)

    @property
    def total_value(self) -> float:
        return self.value + (self.grind_value or 0)

    @property
    def label(self) -> str:
        return f"{self.name}: {self.total_value:g}"


class Artifact(BaseModel):
    artifact_id: int

    slot: int | None = None
    type: int | None = None
    attribute: int | None = None
    unit_style: int | None = None

    natural_rank: int | None = None
    rank: int | None = None
    level: int | None = None

    pri_effect: ArtifactEffect | None = None
    sec_effects: list[ArtifactEffect] = Field(default_factory=list)

    locked: bool = False
    source_id: int | None = None

    occupied_id: int | None = None
    source: str = "unknown"

    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def original_quality(self) -> str:
        return artifact_quality_name(self.natural_rank)

    @property
    def current_quality(self) -> str:
        return artifact_quality_name(self.rank)

    @property
    def attribute_label(self) -> str:
        return artifact_attribute_name(self.attribute)

    @property
    def unit_style_label(self) -> str:
        return artifact_unit_style_name(self.unit_style)

    @property
    def requirement_label(self) -> str:
        if self.attribute and self.attribute != 0:
            return self.attribute_label

        if self.unit_style and self.unit_style != 0:
            return self.unit_style_label

        return "Universal"

    @property
    def slot_label(self) -> str:
        if self.slot == 1:
            return "Attribute"
        if self.slot == 2:
            return "Type"
        if self.slot == 0:
            return "Unknown/Storage"
        return f"Unknown Slot {self.slot}"

    @property
    def location_label(self) -> str:
        if self.occupied_id and self.occupied_id > 0:
            return f"Equipped on monster unit_id {self.occupied_id}"
        return "Storage"


class Monster(BaseModel):
    unit_id: int
    unit_master_id: int | None = None

    base_name: str = "Unknown Monster"
    display_name: str = "Unknown Monster"

    level: int | None = None
    stars: int | None = None
    awaken: int | None = None

    class_level: int | None = None
    con: int | None = None

    duplicate_index: int = 1
    duplicate_count: int = 1

    # Static Swarfarm monster data
    element: str | None = None
    archetype: str | None = None
    natural_stars: int | None = None
    base_stars: int | None = None
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
    skill_levels: dict[int, int] = Field(default_factory=dict)
    skill_ups_to_max: int | None = None

    leader_skill: LeaderSkillData | None = None

    equipped_rune_ids: list[int] = Field(default_factory=list)
    equipped_artifact_ids: list[int] = Field(default_factory=list)

    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def name_display(self) -> str:
        """
        Backwards-compatible alias for older code.
        """
        return self.display_name

    @property
    def is_duplicate(self) -> bool:
        return self.duplicate_count > 1

    @property
    def has_leader_skill(self) -> bool:
        return self.leader_skill is not None

    @property
    def leader_skill_label(self) -> str:
        if not self.leader_skill:
            return "No leader skill"

        attribute = self.leader_skill.attribute or "Unknown"
        amount = self.leader_skill.amount
        area = self.leader_skill.area or "All Areas"
        element = self.leader_skill.element

        if element:
            return f"{attribute} +{amount}% for {element} monsters in {area}"

        return f"{attribute} +{amount}% in {area}"

    @property
    def name_display(self) -> str:
        """
        Backwards-compatible alias for older code.
        """
        return self.display_name

    @property
    def is_duplicate(self) -> bool:
        return self.duplicate_count > 1


class Account(BaseModel):
    player_name: str = "Unknown"
    wizard_id: int | None = None

    monsters: list[Monster] = Field(default_factory=list)

    equipped_runes: list[Rune] = Field(default_factory=list)
    inventory_runes: list[Rune] = Field(default_factory=list)

    equipped_artifacts: list[Artifact] = Field(default_factory=list)
    inventory_artifacts: list[Artifact] = Field(default_factory=list)

    # Raw account progression data retained for profile-specific bonuses.
    building_list: list[dict] = Field(default_factory=list)
    deco_list: list[dict] = Field(default_factory=list)
    wizard_level: int | None = None
    wizard_skill_list: dict[str, Any] = Field(default_factory=dict)
    guild_level: int | None = None
    guild_skill_info: dict[str, Any] = Field(default_factory=dict)

    raw_keys: list[str] = Field(default_factory=list)

    def get_monster_by_unit_id(self, unit_id: int) -> Monster | None:
        for monster in self.monsters:
            if monster.unit_id == unit_id:
                return monster
        return None

    def rune_location_label(self, rune: Rune) -> str:
        if rune.occupied_id and rune.occupied_id > 0:
            monster = self.get_monster_by_unit_id(rune.occupied_id)
            if monster:
                return f"Equipped on {monster.name_display} [{monster.unit_id}]"

            return f"Equipped on unknown monster [{rune.occupied_id}]"

        return "Storage"

    def artifact_location_label(self, artifact: Artifact) -> str:
        if artifact.occupied_id and artifact.occupied_id > 0:
            monster = self.get_monster_by_unit_id(artifact.occupied_id)
            if monster:
                return f"Equipped on {monster.name_display} [{monster.unit_id}]"

            return f"Equipped on unknown monster [{artifact.occupied_id}]"

        return "Storage"