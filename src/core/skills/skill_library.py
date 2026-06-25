from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src.core.resources import DATA_DIR


SKILLS_FILE = DATA_DIR / "skills.json"
SKILL_EFFECTS_FILE = DATA_DIR / "skill_effects.json"


class SkillEffectData(BaseModel):
    id: int
    name: str | None = None
    description: str | None = None
    is_buff: bool | None = None
    icon_filename: str | None = None


class SkillUpgradeData(BaseModel):
    effect: str
    amount: int | float | None = None


class SkillEffectApplicationData(BaseModel):
    effect_id: int | None = None
    effect_name: str | None = None
    chance: int | None = None
    aoe: bool | None = None
    single_target: bool | None = None
    self_effect: bool | None = None
    on_crit: bool | None = None
    on_death: bool | None = None
    random: bool | None = None
    damage: bool | None = None
    note: str | None = None


class SkillData(BaseModel):
    id: int
    com2us_id: int | None = None

    name: str
    description: str | None = None

    slot: int | None = None
    cooldown: int | None = None
    hits: int | None = None

    passive: bool = False
    aoe: bool = False
    random: bool = False

    max_level: int | None = None

    multiplier_formula: str | None = None
    multiplier_formula_raw: str | None = None
    scales_with: list[str] = Field(default_factory=list)

    icon_filename: str | None = None

    effects: list[int] = Field(default_factory=list)
    effect_names: list[str] = Field(default_factory=list)
    effect_applications: list[SkillEffectApplicationData] = Field(default_factory=list)

    upgrades: list[SkillUpgradeData] = Field(default_factory=list)
    level_progress_description: list[str] = Field(default_factory=list)

    used_on: list[int] = Field(default_factory=list)

    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def total_skillup_damage_bonus_percent(self) -> int:
        total = 0

        for upgrade in self.upgrades:
            if upgrade.effect.startswith("Damage +") and upgrade.amount:
                total += int(upgrade.amount)

        return total

    @property
    def total_skillup_damage_multiplier(self) -> float:
        return 1 + (self.total_skillup_damage_bonus_percent / 100)

    @property
    def is_ignore_defense(self) -> bool:
        return any(name == "Ignore DEF" for name in self.effect_names)

    @property
    def is_damage_skill(self) -> bool:
        return self.multiplier_formula is not None


@lru_cache(maxsize=1)
def load_skill_effect_map() -> dict[int, SkillEffectData]:
    if not SKILL_EFFECTS_FILE.exists():
        return {}

    with SKILL_EFFECTS_FILE.open("r", encoding="utf-8") as file:
        raw_effects: list[dict[str, Any]] = json.load(file)

    effects: dict[int, SkillEffectData] = {}

    for raw in raw_effects:
        effect_id = raw.get("id")

        if effect_id is None:
            continue

        effects[int(effect_id)] = SkillEffectData(
            id=int(effect_id),
            name=raw.get("name"),
            description=raw.get("description"),
            is_buff=raw.get("is_buff"),
            icon_filename=raw.get("icon_filename"),
        )

    return effects


@lru_cache(maxsize=1)
def load_skill_map() -> dict[int, SkillData]:
    if not SKILLS_FILE.exists():
        return {}

    with SKILLS_FILE.open("r", encoding="utf-8") as file:
        raw_skills: list[dict[str, Any]] = json.load(file)

    effect_map = load_skill_effect_map()

    skills: dict[int, SkillData] = {}

    for raw in raw_skills:
        skill_id = raw.get("id")

        if skill_id is None:
            continue

        raw_effects = raw.get("effects") or []
        effect_ids: list[int] = []
        effect_applications: list[SkillEffectApplicationData] = []

        for effect_entry in raw_effects:
            effect_id = None
            effect_name = None

            if isinstance(effect_entry, int):
                effect_id = effect_entry

            elif isinstance(effect_entry, dict):
                raw_effect = effect_entry.get("effect")

                if isinstance(raw_effect, dict):
                    effect_id = raw_effect.get("id")
                    effect_name = raw_effect.get("name")

                elif isinstance(raw_effect, int):
                    effect_id = raw_effect

                effect_applications.append(
                    SkillEffectApplicationData(
                        effect_id=effect_id,
                        effect_name=effect_name,
                        chance=effect_entry.get("chance"),
                        aoe=effect_entry.get("aoe"),
                        single_target=effect_entry.get("single_target"),
                        self_effect=effect_entry.get("self_effect"),
                        on_crit=effect_entry.get("on_crit"),
                        on_death=effect_entry.get("on_death"),
                        random=effect_entry.get("random"),
                        damage=effect_entry.get("damage"),
                        note=effect_entry.get("note"),
                    )
                )

            if effect_id is not None:
                effect_ids.append(int(effect_id))

        effect_names: list[str] = []

        for effect_id in effect_ids:
            effect_data = effect_map.get(effect_id)

            if effect_data and effect_data.name:
                effect_names.append(effect_data.name)
            else:
                matched_application = next(
                    (
                        application
                        for application in effect_applications
                        if application.effect_id == effect_id and application.effect_name
                    ),
                    None,
                )

                if matched_application:
                    effect_names.append(
                        matched_application.effect_name or f"Skill Effect {effect_id}"
                    )
                else:
                    effect_names.append(f"Skill Effect {effect_id}")

        skill = SkillData(
            id=int(skill_id),
            com2us_id=raw.get("com2us_id"),
            name=raw.get("name") or f"Skill {skill_id}",
            description=raw.get("description"),
            slot=raw.get("slot"),
            cooldown=raw.get("cooltime") or raw.get("cooldown"),
            hits=raw.get("hits"),
            passive=bool(raw.get("passive", False)),
            aoe=bool(raw.get("aoe", False)),
            random=bool(raw.get("random", False)),
            max_level=raw.get("max_level"),
            multiplier_formula=(
                raw.get("multiplier_formula")
                or raw.get("multiplier")
                or raw.get("formula")
            ),
            multiplier_formula_raw=raw.get("multiplier_formula_raw"),
            scales_with=raw.get("scales_with") or [],
            icon_filename=raw.get("icon_filename"),
            effects=effect_ids,
            effect_names=effect_names,
            effect_applications=effect_applications,
            upgrades=[
                SkillUpgradeData(
                    effect=upgrade.get("effect", ""),
                    amount=upgrade.get("amount"),
                )
                for upgrade in raw.get("upgrades", []) or []
            ],
            level_progress_description=raw.get("level_progress_description") or [],
            used_on=raw.get("used_on") or [],
            raw=raw,
        )

        skills[int(skill_id)] = skill

    return skills


def skill_data_from_id(skill_id: int | None) -> SkillData | None:
    if skill_id is None:
        return None

    return load_skill_map().get(int(skill_id))


def skill_name_from_id(skill_id: int | None) -> str:
    skill = skill_data_from_id(skill_id)

    if skill:
        return skill.name

    if skill_id is None:
        return "Unknown Skill"

    return f"Skill {skill_id}"

@dataclass(frozen=True)
class SkillCombatProfile:
    skill_id: int
    name: str
    slot: int
    level: int
    max_level: int
    formula: str
    atk: float = 0.0
    hp: float = 0.0
    defense: float = 0.0
    speed: float = 0.0
    target_hp: float = 0.0
    flat: float = 0.0
    hits: int = 1
    aoe: bool = False
    skillup_bonus_pct: float = 0.0
    supported: bool = False
    fixed_damage: bool = False
    ignores_defense: bool = False
    provides_defense_break: bool = False
    provides_atk_buff: bool = False
    provides_brand: bool = False
    provides_healing: bool = False
    provides_control: bool = False
    cooldown: int = 1
    effect_chance: float = 100.0
    reason: str = ""


_LINEAR_VARIABLES = {
    "ATK": "atk",
    "DEF": "defense",
    "ATTACK_TOT_HP": "hp",
    "ATTACK_CUR_HP": "hp",
    "TARGET_TOT_HP": "target_hp",
    "TARGET_CUR_HP": "target_hp",
    "ATTACK_SPEED": "speed",
}


@lru_cache(maxsize=1)
def load_skill_com2us_map() -> dict[int, SkillData]:
    return {
        int(skill.com2us_id): skill
        for skill in load_skill_map().values()
        if skill.com2us_id is not None
    }


def skill_data_from_com2us_id(com2us_id: int | None) -> SkillData | None:
    if com2us_id is None:
        return None
    return load_skill_com2us_map().get(int(com2us_id))


def skillup_damage_bonus_percent(skill: SkillData, level: int | None) -> float:
    current_level = max(1, int(level or 1))
    applied_steps = min(len(skill.upgrades), current_level - 1)
    total = 0.0
    for upgrade in skill.upgrades[:applied_steps]:
        if upgrade.effect.startswith("Damage +") and upgrade.amount is not None:
            total += float(upgrade.amount)
    return total


def _linear_formula_terms(skill: SkillData) -> tuple[dict[str, float], bool, str]:
    raw = skill.multiplier_formula_raw
    try:
        expression = json.loads(raw or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}, False, "Formula data is unavailable."
    if not isinstance(expression, list) or not expression:
        return {}, False, "This skill has no direct damage formula."

    values = {"atk": 0.0, "hp": 0.0, "defense": 0.0, "speed": 0.0, "target_hp": 0.0, "flat": 0.0}
    sign = 1.0
    fixed = False
    for component in expression:
        if component == ["+"]:
            sign = 1.0
            continue
        if component == ["-"]:
            sign = -1.0
            continue
        if not isinstance(component, list) or not component:
            return {}, False, "The formula is nonlinear or context dependent."
        tokens = [token for token in component if token not in {"FIXED", "CEIL"}]
        fixed = fixed or "FIXED" in component
        if len(tokens) == 1 and isinstance(tokens[0], (int, float)):
            values["flat"] += sign * float(tokens[0])
            sign = 1.0
            continue
        variable = tokens[0] if tokens else None
        field = _LINEAR_VARIABLES.get(str(variable))
        if field is None:
            return {}, False, "The formula depends on combat state not modeled automatically."
        coefficient = 1.0
        position = 1
        if len(tokens) >= 3 and tokens[1] == "*" and isinstance(tokens[2], (int, float)):
            coefficient = float(tokens[2])
            position = 3
        elif len(tokens) >= 2:
            return {}, False, "The formula is nonlinear or context dependent."
        values[field] += sign * coefficient
        if position < len(tokens):
            if (
                position + 1 < len(tokens)
                and tokens[position] in {"+", "-"}
                and isinstance(tokens[position + 1], (int, float))
                and position + 2 == len(tokens)
            ):
                internal_sign = 1.0 if tokens[position] == "+" else -1.0
                values["flat"] += sign * internal_sign * float(tokens[position + 1])
            else:
                return {}, False, "The formula is nonlinear or context dependent."
        sign = 1.0
    return values, fixed, ""


def skill_combat_profile(skill: SkillData, level: int | None = None) -> SkillCombatProfile:
    current_level = max(1, int(level or 1))
    terms, fixed, reason = _linear_formula_terms(skill)
    supported = bool(terms) and not skill.passive
    effect_names = set(skill.effect_names)
    effect_chances = [
        float(application.chance)
        for application in skill.effect_applications
        if application.chance is not None and application.chance > 0
    ]
    effect_chance = max(effect_chances, default=100.0)
    applied_steps = min(len(skill.upgrades), current_level - 1)
    effect_chance += sum(
        float(upgrade.amount or 0)
        for upgrade in skill.upgrades[:applied_steps]
        if upgrade.effect.startswith("Effect Rate +")
    )
    control_effects = {"Stun", "Freeze", "Sleep"}
    healing_effects = {"Heal", "Self-Heal", "Recovery"}
    return SkillCombatProfile(
        skill_id=skill.id,
        name=skill.name,
        slot=int(skill.slot or 1),
        level=current_level,
        max_level=int(skill.max_level or 1),
        formula=str(skill.multiplier_formula or ""),
        atk=float(terms.get("atk", 0.0)),
        hp=float(terms.get("hp", 0.0)),
        defense=float(terms.get("defense", 0.0)),
        speed=float(terms.get("speed", 0.0)),
        target_hp=float(terms.get("target_hp", 0.0)),
        flat=float(terms.get("flat", 0.0)),
        hits=max(1, int(skill.hits or 1)),
        aoe=bool(skill.aoe),
        skillup_bonus_pct=skillup_damage_bonus_percent(skill, current_level),
        supported=supported,
        fixed_damage=fixed,
        ignores_defense=bool(skill.is_ignore_defense or fixed),
        provides_defense_break="Decrease DEF" in effect_names,
        provides_atk_buff="Increase ATK" in effect_names,
        provides_brand="Brand" in effect_names,
        provides_healing=bool(effect_names & healing_effects),
        provides_control=bool(effect_names & control_effects),
        cooldown=max(1, int(skill.cooldown or 1)),
        effect_chance=min(100.0, max(0.0, effect_chance)),
        reason=reason if not supported else "",
    )


def monster_skill_profiles(
    skill_ids: list[int] | tuple[int, ...],
    skill_levels: dict[int, int] | None = None,
) -> list[SkillCombatProfile]:
    levels = skill_levels or {}
    profiles = []
    for skill_id in skill_ids:
        skill = skill_data_from_id(skill_id)
        if skill is not None:
            profiles.append(skill_combat_profile(skill, levels.get(int(skill_id), 1)))
    return sorted(profiles, key=lambda profile: (profile.slot, profile.skill_id))

