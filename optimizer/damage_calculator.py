"""Dungeon damage calculation helpers.

This module is intentionally UI-agnostic. It provides deterministic building
blocks for wave-clear checks and future dungeon simulation: skill scaling,
buffs/debuffs, crit damage, defense mitigation, skillups, and artifact-style
bonus multipliers.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class UnitStats:
    hp: float = 0.0
    atk: float = 0.0
    defense: float = 0.0
    speed: float = 0.0
    crit_rate: float = 0.0
    crit_damage: float = 50.0


@dataclass(frozen=True)
class SkillScaling:
    atk: float = 0.0
    hp: float = 0.0
    defense: float = 0.0
    speed: float = 0.0
    target_hp: float = 0.0
    flat: float = 0.0
    hits: int = 1


@dataclass(frozen=True)
class DamageContext:
    atk_buff: bool = False
    defense_buff: bool = False
    speed_buff: bool = False
    defense_break: bool = False
    brand: bool = False
    beneficial_effects_on_enemy: int = 0
    skillup_bonus_pct: float = 0.0
    artifact_bonus_pct: float = 0.0
    element_bonus_pct: float = 0.0
    additional_damage_by_hp_pct: float = 0.0
    additional_damage_by_atk_pct: float = 0.0
    additional_damage_by_def_pct: float = 0.0
    additional_damage_by_spd_pct: float = 0.0
    extra_multipliers: tuple[float, ...] = field(default_factory=tuple)
    target_crit_damage_reduction_pct: float = 0.0
    force_crit: bool = True
    ignore_defense: bool = False


@dataclass(frozen=True)
class EnemyDamageResult:
    name: str
    hp: int
    defense: int
    damage: int
    one_shot: bool


@dataclass(frozen=True)
class WaveDamageResult:
    wave_number: int
    enemies: tuple[EnemyDamageResult, ...]

    @property
    def defeated_count(self) -> int:
        return sum(1 for enemy in self.enemies if enemy.one_shot)

    @property
    def clears_wave(self) -> bool:
        return bool(self.enemies) and self.defeated_count == len(self.enemies)


def effective_defense(defense: float, defense_break: bool = False) -> float:
    value = max(0.0, float(defense or 0.0))
    if defense_break:
        value *= 0.3
    return value


def defense_mitigation(defense: float) -> float:
    """Summoners War defense reduction multiplier.

    This is the inverse of the common EHP formula used elsewhere in the app:
    EHP = HP * (1140 + 3.75 * DEF) / 1000.
    """
    return 1000.0 / (1140.0 + 3.75 * max(0.0, float(defense or 0.0)))


def scaled_skill_power(attacker: UnitStats, scaling: SkillScaling,
                       context: DamageContext | None = None,
                       defender: UnitStats | None = None) -> float:
    ctx = context or DamageContext()
    atk = attacker.atk * (1.5 if ctx.atk_buff else 1.0)
    defense = attacker.defense * (1.7 if ctx.defense_buff else 1.0)
    speed = attacker.speed * (1.3 if ctx.speed_buff else 1.0)
    return (
        scaling.flat
        + atk * scaling.atk
        + attacker.hp * scaling.hp
        + defense * scaling.defense
        + speed * scaling.speed
        + (defender.hp if defender is not None else 0.0) * scaling.target_hp
    )


def critical_multiplier(attacker: UnitStats, context: DamageContext | None = None) -> float:
    ctx = context or DamageContext()
    crit_damage = max(
        0.0,
        attacker.crit_damage - max(0.0, ctx.target_crit_damage_reduction_pct),
    )
    if not ctx.force_crit:
        cr = max(0.0, min(100.0, attacker.crit_rate)) / 100.0
        return 1.0 + cr * crit_damage / 100.0
    return 1.0 + crit_damage / 100.0


def damage_multiplier(context: DamageContext | None = None) -> float:
    ctx = context or DamageContext()
    mult = 1.0
    mult *= 1.0 + max(0.0, ctx.skillup_bonus_pct) / 100.0
    mult *= 1.0 + max(0.0, ctx.artifact_bonus_pct) / 100.0
    mult *= 1.0 + max(0.0, ctx.element_bonus_pct) / 100.0
    if ctx.brand:
        mult *= 1.25
    for extra in ctx.extra_multipliers:
        mult *= float(extra)
    return mult


def calculate_damage(attacker: UnitStats, defender: UnitStats, scaling: SkillScaling,
                     context: DamageContext | None = None) -> int:
    ctx = context or DamageContext()
    per_hit_power = scaled_skill_power(attacker, scaling, ctx, defender)
    per_hit_power += (
        attacker.hp * max(0.0, ctx.additional_damage_by_hp_pct) / 100.0
        + attacker.atk * max(0.0, ctx.additional_damage_by_atk_pct) / 100.0
        + attacker.defense * max(0.0, ctx.additional_damage_by_def_pct) / 100.0
        + attacker.speed * max(0.0, ctx.additional_damage_by_spd_pct) / 100.0
    )
    per_hit = per_hit_power
    per_hit *= critical_multiplier(attacker, ctx)
    if not ctx.ignore_defense:
        per_hit *= defense_mitigation(
            effective_defense(defender.defense, ctx.defense_break)
        )
    per_hit *= damage_multiplier(ctx)
    return int(max(0.0, per_hit) * max(1, int(scaling.hits or 1)))


def can_kill_wave(attacker: UnitStats, enemies: list[UnitStats], scaling: SkillScaling,
                  context: DamageContext | None = None) -> bool:
    return all(calculate_damage(attacker, enemy, scaling, context) >= enemy.hp
               for enemy in enemies)


def analyze_waves(
    attacker: UnitStats,
    waves: dict[int, list[dict]],
    scaling: SkillScaling,
    context: DamageContext | None = None,
) -> dict[int, WaveDamageResult]:
    """Calculate per-enemy damage and one-shot status for imported dungeon waves."""
    base_context = context or DamageContext()
    results: dict[int, WaveDamageResult] = {}
    for wave_number, enemies in waves.items():
        enemy_results = []
        for enemy in enemies:
            hp = int(enemy.get("hp") or 0)
            defense = int(enemy.get("def") or enemy.get("defense") or 0)
            enemy_context = replace(
                base_context,
                target_crit_damage_reduction_pct=float(
                    enemy.get("cdmg_reduction") or 0
                ),
            )
            damage = calculate_damage(
                attacker,
                UnitStats(hp=hp, defense=defense),
                scaling,
                enemy_context,
            )
            enemy_results.append(
                EnemyDamageResult(
                    name=str(enemy.get("monster_name") or enemy.get("name") or "?"),
                    hp=hp,
                    defense=defense,
                    damage=damage,
                    one_shot=damage >= hp,
                )
            )
        results[int(wave_number)] = WaveDamageResult(
            wave_number=int(wave_number),
            enemies=tuple(enemy_results),
        )
    return results
