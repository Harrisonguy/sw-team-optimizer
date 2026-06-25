"""Dungeon team readiness scoring and seeded run estimation."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
import random
from typing import Callable

from optimizer.damage_calculator import (
    DamageContext,
    SkillScaling,
    UnitStats,
    calculate_damage,
)
from optimizer.stat_utils import effective_hp


@dataclass(frozen=True)
class DungeonCombatant:
    unit_id: int
    display_name: str
    stats: dict
    scaling: SkillScaling = field(default_factory=lambda: SkillScaling(atk=3.0))
    context: DamageContext = field(
        default_factory=lambda: DamageContext(force_crit=False)
    )
    role: str = "attacker"
    aoe: bool = False
    provides_defense_break: bool = False
    provides_atk_buff: bool = False
    provides_brand: bool = False
    provides_healing: bool = False
    provides_control: bool = False
    skill_cooldown: int = 1
    effect_chance: float = 100.0


@dataclass(frozen=True)
class DungeonWaveEvaluation:
    wave_number: int
    is_boss_wave: bool
    rounds_to_clear: float
    turn_budget: int
    damage_score: float
    survivability_score: float
    speed_score: float
    control_score: float
    readiness_score: float
    success_probability: float
    limiting_enemy: str


@dataclass(frozen=True)
class DungeonTeamEvaluation:
    readiness_score: float
    success_probability: float
    waves: tuple[DungeonWaveEvaluation, ...]
    bottlenecks: tuple[str, ...]


def _unit_stats(stats: dict, crit_damage_bonus: float = 0.0) -> UnitStats:
    return UnitStats(
        hp=float(stats.get("hp") or 0),
        atk=float(stats.get("atk") or 0),
        defense=float(stats.get("def_") or stats.get("defense") or 0),
        speed=float(stats.get("spd") or stats.get("speed") or 0),
        crit_rate=float(stats.get("cr") or stats.get("crit_rate") or 0),
        crit_damage=(
            float(stats.get("cd") or stats.get("crit_damage") or 50)
            + crit_damage_bonus
        ),
    )


def _enemy_stats(enemy: dict) -> UnitStats:
    return UnitStats(
        hp=float(enemy.get("hp") or 0),
        atk=float(enemy.get("atk") or enemy.get("attack") or 0),
        defense=float(enemy.get("def") or enemy.get("defense") or 0),
        speed=float(enemy.get("spd") or enemy.get("speed") or 0),
        crit_rate=float(enemy.get("cr") or 15),
        crit_damage=50.0,
    )


def _defense_break_chance(
    members: list[DungeonCombatant],
    enemy_resistance: float,
) -> float:
    providers = [member for member in members if member.provides_defense_break]
    if not providers:
        return 0.0
    failure = 1.0
    for member in providers:
        accuracy = float(member.stats.get("acc") or 0)
        resistance_roll = max(
            0.15,
            min(0.85, 1.0 - max(0.0, enemy_resistance - accuracy) / 100.0),
        )
        activation = max(0.0, min(1.0, member.effect_chance / 100.0))
        uptime = 1.0 / max(1, int(member.skill_cooldown or 1))
        failure *= 1.0 - activation * resistance_roll * uptime
    return 1.0 - failure


def _member_damage(
    member: DungeonCombatant,
    enemy: dict,
    atk_buff: bool,
    defense_break_chance: float,
) -> float:
    attacker = _unit_stats(member.stats)
    defender = _enemy_stats(enemy)
    reduction = float(enemy.get("cdmg_reduction") or 0)
    normal_context = replace(
        member.context,
        atk_buff=member.context.atk_buff or atk_buff,
        defense_break=False,
        target_crit_damage_reduction_pct=reduction,
        force_crit=False,
    )
    broken_context = replace(normal_context, defense_break=True)
    normal = calculate_damage(attacker, defender, member.scaling, normal_context)
    if defense_break_chance <= 0:
        special = float(normal)
    else:
        broken = calculate_damage(attacker, defender, member.scaling, broken_context)
        special = normal * (1.0 - defense_break_chance) + broken * defense_break_chance
    cooldown = max(1, int(member.skill_cooldown or 1))
    if cooldown == 1:
        return special
    basic_scaling = SkillScaling(atk=1.0)
    basic = calculate_damage(attacker, defender, basic_scaling, normal_context)
    return (special + float(basic) * (cooldown - 1)) / cooldown


def _logistic(value: float) -> float:
    value = max(-30.0, min(30.0, value))
    return 1.0 / (1.0 + math.exp(-value))


def evaluate_dungeon_team(
    members: list[DungeonCombatant],
    waves: dict[int, list[dict]],
) -> DungeonTeamEvaluation:
    """Evaluate clear speed, survival, speed tuning, and debuff reliability."""
    if not members or not waves:
        return DungeonTeamEvaluation(0.0, 0.0, tuple(), ("No dungeon team data",))

    final_wave = max(waves)
    has_atk_buff = any(member.provides_atk_buff for member in members)
    has_healer = any("healer" in member.role.lower() for member in members)
    wave_results = []

    for wave_number in sorted(waves):
        enemies = waves[wave_number]
        if not enemies:
            continue
        is_boss = wave_number == final_wave
        target_enemies = (
            [max(enemies, key=lambda enemy: float(enemy.get("hp") or 0))]
            if is_boss
            else enemies
        )
        enemy_count = max(1, len(enemies))
        rounds = 0.0
        limiting_enemy = "Enemy"

        for enemy in target_enemies:
            break_chance = _defense_break_chance(
                members,
                float(enemy.get("res") or 0),
            )
            per_round = 0.0
            for member in members:
                damage = _member_damage(member, enemy, has_atk_buff, break_chance)
                if is_boss or member.aoe:
                    per_round += damage
                else:
                    per_round += damage / enemy_count
            enemy_hp = float(enemy.get("hp") or 0)
            enemy_rounds = enemy_hp / max(1.0, per_round)
            if enemy_rounds > rounds:
                rounds = enemy_rounds
                limiting_enemy = str(enemy.get("monster_name") or "Enemy")

        turn_budget = 60 if is_boss else (20 if wave_number == 2 else 4)
        damage_score = min(1.0, turn_budget / max(0.25, rounds))

        fastest_enemy = max(float(enemy.get("spd") or 0) for enemy in enemies)
        speed_score = sum(
            1.0 if float(member.stats.get("spd") or 0) > fastest_enemy else 0.45
            for member in members
        ) / len(members)

        enemy_resistance = max(float(enemy.get("res") or 0) for enemy in enemies)
        control_score = _defense_break_chance(members, enemy_resistance)
        if control_score <= 0:
            control_score = 0.45

        raw_threat = sum(
            max(1.0, float(enemy.get("atk") or enemy.get("attack") or 0)) * 1.5
            for enemy in enemies
        )
        exposure_limit = 6.0 if is_boss else 3.0
        exposed_rounds = max(1.0, min(rounds, exposure_limit))
        if has_healer:
            raw_threat *= 0.65
        survival_margins = [
            effective_hp(member.stats) / max(1.0, raw_threat * exposed_rounds)
            for member in members
        ]
        minimum_margin = min(survival_margins)
        survivability_score = min(1.0, minimum_margin)

        readiness = 100.0 * (
            damage_score * 0.55
            + survivability_score * 0.25
            + speed_score * 0.10
            + control_score * 0.10
        )
        damage_probability = _logistic(
            (turn_budget / max(0.25, rounds) - 1.0) * 4.0
        )
        survival_probability = _logistic((minimum_margin - 0.60) * 3.0)
        speed_probability = 0.70 + speed_score * 0.30
        control_probability = 0.85 + control_score * 0.15
        wave_probability = (
            damage_probability
            * survival_probability
            * speed_probability
            * control_probability
        )
        wave_results.append(
            DungeonWaveEvaluation(
                wave_number=int(wave_number),
                is_boss_wave=is_boss,
                rounds_to_clear=round(rounds, 2),
                turn_budget=turn_budget,
                damage_score=round(damage_score * 100.0, 1),
                survivability_score=round(survivability_score * 100.0, 1),
                speed_score=round(speed_score * 100.0, 1),
                control_score=round(control_score * 100.0, 1),
                readiness_score=round(readiness, 1),
                success_probability=round(wave_probability * 100.0, 1),
                limiting_enemy=limiting_enemy,
            )
        )

    if not wave_results:
        return DungeonTeamEvaluation(0.0, 0.0, tuple(), ("No dungeon waves",))

    readiness = sum(wave.readiness_score for wave in wave_results) / len(wave_results)
    success = 1.0
    for wave in wave_results:
        success *= wave.success_probability / 100.0

    bottlenecks = []
    worst_damage = min(wave_results, key=lambda wave: wave.damage_score)
    if worst_damage.damage_score < 90:
        bottlenecks.append(
            "Wave %d damage needs %.1f rounds (budget %d)"
            % (
                worst_damage.wave_number,
                worst_damage.rounds_to_clear,
                worst_damage.turn_budget,
            )
        )
    worst_survival = min(wave_results, key=lambda wave: wave.survivability_score)
    if worst_survival.survivability_score < 90:
        bottlenecks.append(
            "Wave %d survivability is %.0f%%"
            % (worst_survival.wave_number, worst_survival.survivability_score)
        )
    worst_speed = min(wave_results, key=lambda wave: wave.speed_score)
    if worst_speed.speed_score < 100:
        bottlenecks.append(
            "Some team members move after enemies on wave %d"
            % worst_speed.wave_number
        )
    if not bottlenecks:
        bottlenecks.append("No major modeled bottleneck")

    return DungeonTeamEvaluation(
        readiness_score=round(readiness, 1),
        success_probability=round(success * 100.0, 1),
        waves=tuple(wave_results),
        bottlenecks=tuple(bottlenecks),
    )




def _effect_lands(
    member: DungeonCombatant,
    enemy: dict,
    rng: random.Random,
) -> bool:
    """Roll activation plus the Summoners War 15% resistance floor."""
    activation = max(0.0, min(1.0, member.effect_chance / 100.0))
    accuracy = float(member.stats.get("acc") or 0)
    resistance = float(enemy.get("res") or 0)
    resistance_roll = max(
        0.15,
        min(0.85, 1.0 - max(0.0, resistance - accuracy) / 100.0),
    )
    return rng.random() <= activation * resistance_roll


def _battle_damage(
    member: DungeonCombatant,
    enemy_state: dict,
    use_skill: bool,
    atk_buff: bool,
) -> int:
    scaling = member.scaling if use_skill else SkillScaling(atk=1.0)
    context = replace(
        member.context,
        atk_buff=member.context.atk_buff or atk_buff,
        defense_break=enemy_state["defense_break"] > 0,
        brand=member.context.brand or enemy_state["brand"] > 0,
        target_crit_damage_reduction_pct=float(
            enemy_state["data"].get("cdmg_reduction") or 0
        ),
        force_crit=False,
    )
    return calculate_damage(
        _unit_stats(member.stats),
        _enemy_stats(enemy_state["data"]),
        scaling,
        context,
    )


def _simulate_wave_once(
    members: list[DungeonCombatant],
    enemies: list[dict],
    max_rounds: int,
    rng: random.Random,
    ally_states: list[dict] | None = None,
    atk_buff_rounds: int = 0,
) -> tuple[bool, list[dict], int]:
    """Resolve one wave while preserving team health, cooldowns, and buffs."""
    if ally_states is None:
        ally_states = [
            {
                "member": member,
                "hp": max(1.0, float(member.stats.get("hp") or 1)),
                "max_hp": max(1.0, float(member.stats.get("hp") or 1)),
                "cooldown": 0,
            }
            for member in members
        ]
    enemy_states = [
        {
            "data": enemy,
            "hp": max(1.0, float(enemy.get("hp") or 1)),
            "defense_break": 0,
            "brand": 0,
            "controlled": 0,
        }
        for enemy in enemies
    ]

    for _round in range(max(1, int(max_rounds))):
        for ally in sorted(
            ally_states,
            key=lambda state: float(state["member"].stats.get("spd") or 0),
            reverse=True,
        ):
            if ally["hp"] <= 0:
                continue
            living_enemies = [enemy for enemy in enemy_states if enemy["hp"] > 0]
            if not living_enemies:
                return True, ally_states, atk_buff_rounds
            member = ally["member"]
            if ally["cooldown"] > 0:
                ally["cooldown"] -= 1
            use_skill = ally["cooldown"] == 0
            if use_skill:
                ally["cooldown"] = max(1, int(member.skill_cooldown or 1))
                if member.provides_atk_buff:
                    atk_buff_rounds = max(atk_buff_rounds, 2)
                if member.provides_healing:
                    for target in ally_states:
                        if target["hp"] > 0:
                            target["hp"] = min(
                                target["max_hp"],
                                target["hp"] + target["max_hp"] * 0.25,
                            )

            primary = max(living_enemies, key=lambda enemy: enemy["hp"])
            targets = living_enemies if use_skill and member.aoe else [primary]
            for target in targets:
                target["hp"] -= _battle_damage(
                    member,
                    target,
                    use_skill,
                    atk_buff_rounds > 0,
                )
                if use_skill and target["hp"] > 0 and _effect_lands(
                    member, target["data"], rng
                ):
                    if member.provides_defense_break:
                        target["defense_break"] = max(target["defense_break"], 2)
                    if member.provides_brand:
                        target["brand"] = max(target["brand"], 2)
                    if member.provides_control:
                        target["controlled"] = max(target["controlled"], 1)

        living_enemies = [enemy for enemy in enemy_states if enemy["hp"] > 0]
        if not living_enemies:
            return True, ally_states, atk_buff_rounds

        for enemy in sorted(
            living_enemies,
            key=lambda state: float(state["data"].get("spd") or 0),
            reverse=True,
        ):
            if enemy["controlled"] > 0:
                enemy["controlled"] -= 1
                continue
            living_allies = [ally for ally in ally_states if ally["hp"] > 0]
            if not living_allies:
                return False, ally_states, atk_buff_rounds
            target = rng.choice(living_allies)
            incoming = calculate_damage(
                _enemy_stats(enemy["data"]),
                _unit_stats(target["member"].stats),
                SkillScaling(atk=1.0),
                DamageContext(force_crit=False),
            )
            target["hp"] -= max(1, incoming)

        for enemy in living_enemies:
            enemy["defense_break"] = max(0, enemy["defense_break"] - 1)
            enemy["brand"] = max(0, enemy["brand"] - 1)
        atk_buff_rounds = max(0, atk_buff_rounds - 1)

    return (
        not any(enemy["hp"] > 0 for enemy in enemy_states),
        ally_states,
        atk_buff_rounds,
    )


def simulate_dungeon_runs(
    evaluation: DungeonTeamEvaluation,
    trials: int = 1000,
    seed: int = 0,
    cancel_check: Callable[[], bool] | None = None,
    members: list[DungeonCombatant] | None = None,
    waves: dict[int, list[dict]] | None = None,
) -> float:
    """Return a reproducible clear rate.

    When members and waves are supplied, resolve cooldowns, conditional effects,
    healing, control, and enemy turns. The probability-only path remains for
    callers that have only an aggregate evaluation.
    """
    trial_count = int(trials)
    if trial_count <= 0 or not evaluation.waves:
        return 0.0
    rng = random.Random(seed)
    clears = 0
    wave_evaluations = {wave.wave_number: wave for wave in evaluation.waves}
    use_battle_model = bool(members and waves)

    for trial in range(trial_count):
        if trial % 64 == 0 and cancel_check is not None and cancel_check():
            from optimizer.rune_optimizer import OptimizationCancelled
            raise OptimizationCancelled("Optimization cancelled")
        if use_battle_model:
            cleared = True
            ally_states = None
            atk_buff_rounds = 0
            for wave_number in sorted(waves or {}):
                enemies = (waves or {}).get(wave_number) or []
                wave_evaluation = wave_evaluations.get(int(wave_number))
                if not enemies or wave_evaluation is None:
                    continue
                cleared, ally_states, atk_buff_rounds = _simulate_wave_once(
                    list(members or []),
                    enemies,
                    wave_evaluation.turn_budget,
                    rng,
                    ally_states,
                    atk_buff_rounds,
                )
                if not cleared:
                    break
        else:
            cleared = all(
                rng.random() <= wave.success_probability / 100.0
                for wave in evaluation.waves
            )
        if cleared:
            clears += 1
    return round(clears * 100.0 / trial_count, 1)
