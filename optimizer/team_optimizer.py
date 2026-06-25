"""Team optimizer engine.

Searches team allocation states jointly. For every surviving state, the
single-monster solver runs against only the runes still available in that
state, then a bounded team beam preserves competing allocations. Rune
availability is therefore part of candidate generation, not a conflict check
performed after independently optimizing every monster.

Priority still matters as a tie-breaker and UI concept, but it no longer means
"optimize this monster first and make everyone else live with the leftovers."
Turn-order plans are evaluated on the final selected team and heavily rewarded
when the achieved final speeds respect the requested order.
"""
from __future__ import annotations

from typing import Callable, NamedTuple

from optimizer.damage_calculator import DamageContext, SkillScaling
from optimizer.dungeon_simulator import (
    DungeonCombatant,
    DungeonTeamEvaluation,
    evaluate_dungeon_team,
)
from optimizer.rune_optimizer import optimize, BuildResult, OptimizationCancelled


class MonsterRequest(NamedTuple):
    unit_id:               int
    display_name:          str
    priority:              int          # 1 = first pick from pool
    set_reqs:              list[str]
    main_stat_constraints: dict[int, str]
    target_stats:          dict[str, int]
    current_build:         dict[int, dict]
    target_mode:           str = "total"
    scoring_mode:          str = "desirability"  # "desirability" | "effective_offense"
    ref_atk:               float = 3000.0
    ref_cr:                float = 85.0
    ref_cd:                float = 200.0
    monster_info:          dict | None = None    # base stats (enables final-stat targets)
    artifact_flat:         dict | None = None    # equipped artifact flat bonuses
    bonuses:               dict | None = None    # merged building + leader bonuses
    turn_pos:              int | None = None     # planned turn position (1 = first)
    max_stats:             dict | None = None    # static caps, e.g. {"SPD": 168}
    assume_max:            bool = True           # value mains at +15 projection
    combat_role:          str = "attacker"
    skill_atk_multiplier: float = 3.0
    skill_hp_multiplier:  float = 0.0
    skill_def_multiplier: float = 0.0
    skill_spd_multiplier: float = 0.0
    skill_target_hp_multiplier: float = 0.0
    skill_flat_damage:    float = 0.0
    skill_hits:           int = 1
    skillup_bonus_pct:    float = 0.0
    skill_ignore_defense: bool = False
    skill_aoe:            bool = False
    provides_defense_break: bool = False
    provides_atk_buff:      bool = False
    provides_brand:         bool = False
    provides_healing:       bool = False
    provides_control:       bool = False
    skill_cooldown:         int = 1
    skill_effect_chance:    float = 100.0


class MonsterResult(NamedTuple):
    unit_id:      int
    display_name: str
    priority:     int
    build:        BuildResult | None    # None = no runes found
    meets_targets: bool
    turn_pos:     int | None = None


class TeamResult(NamedTuple):
    monsters:      list[MonsterResult]
    team_avg_desr: float
    turn_order_ok: bool = True   # achieved SPDs respect the planned order
    dungeon_score: float | None = None
    estimated_success: float | None = None
    dungeon_evaluation: DungeonTeamEvaluation | None = None


_SPD_GAP = 1   # minimum SPD separation enforced between planned positions


def _build_rune_ids(build: BuildResult | None) -> frozenset[int]:
    if not build:
        return frozenset()
    return frozenset(
        int(sr.rune["rune_id"])
        for sr in build.slots
        if sr.rune and sr.rune.get("rune_id") is not None
    )


def _normalized_shortfall(build: BuildResult | None) -> float:
    if not build or not build.target_report:
        return 0.0 if build else 99.0
    total = 0.0
    for item in build.target_report.values():
        target = float(item.get("target") or 0)
        if target > 0:
            total += float(item.get("miss") or 0) / target
    return total


def _build_value(build: BuildResult | None) -> float:
    if not build:
        return -1_000_000.0
    value = float(build.score or 0.0) + float(build.avg_desr or 0.0) * 5.0
    value += 10_000.0 if build.meets_targets else -6_000.0 * _normalized_shortfall(build)
    value += 3_000.0 if build.sets_complete else -3_000.0
    return value


def _turn_order_ok(results: list[MonsterResult]) -> bool:
    planned = sorted(
        [(r.turn_pos, r) for r in results if r.turn_pos is not None and r.build
         and r.build.final_stats],
        key=lambda x: x[0],
    )
    for (_p1, r1), (_p2, r2) in zip(planned, planned[1:]):
        if int(r1.build.final_stats["spd"]) <= int(r2.build.final_stats["spd"]):
            return False
    return True


def build_dungeon_combatants(
    results: list[MonsterResult],
    requests: list[MonsterRequest],
) -> list[DungeonCombatant]:
    """Build the battle-model inputs shared by scoring and Monte Carlo runs."""
    requests_by_id = {request.unit_id: request for request in requests}
    members = []
    for result in results:
        request = requests_by_id.get(result.unit_id)
        if request is None or result.build is None or not result.build.final_stats:
            continue
        stats = dict(result.build.final_stats)
        artifact = request.artifact_flat or {}
        stats["cd"] = float(stats.get("cd") or 0) + float(
            artifact.get("cd_bonus") or 0
        )
        members.append(
            DungeonCombatant(
                unit_id=result.unit_id,
                display_name=result.display_name,
                stats=stats,
                scaling=SkillScaling(
                    atk=float(request.skill_atk_multiplier or 0),
                    hp=float(request.skill_hp_multiplier or 0),
                    defense=float(request.skill_def_multiplier or 0),
                    speed=float(request.skill_spd_multiplier or 0),
                    target_hp=float(request.skill_target_hp_multiplier or 0),
                    flat=float(request.skill_flat_damage or 0),
                    hits=max(1, int(request.skill_hits or 1)),
                ),
                context=DamageContext(
                    artifact_bonus_pct=float(
                        artifact.get("damage_bonus_pct") or 0
                    ),
                    element_bonus_pct=float(
                        artifact.get("element_bonus_pct") or 0
                    ),
                    additional_damage_by_hp_pct=float(
                        artifact.get("addl_hp_pct") or 0
                    ),
                    additional_damage_by_atk_pct=float(
                        artifact.get("addl_atk_pct") or 0
                    ),
                    additional_damage_by_def_pct=float(
                        artifact.get("addl_def_pct") or 0
                    ),
                    additional_damage_by_spd_pct=float(
                        artifact.get("addl_spd_pct") or 0
                    ),
                    skillup_bonus_pct=float(request.skillup_bonus_pct or 0),
                    force_crit=False,
                    ignore_defense=bool(request.skill_ignore_defense),
                ),
                role=request.combat_role,
                aoe=bool(request.skill_aoe),
                provides_defense_break=bool(request.provides_defense_break),
                provides_atk_buff=bool(request.provides_atk_buff),
                provides_brand=bool(request.provides_brand),
                provides_healing=bool(request.provides_healing),
                provides_control=bool(request.provides_control),
                skill_cooldown=max(1, int(request.skill_cooldown or 1)),
                effect_chance=float(request.skill_effect_chance or 0),
            )
        )
    return members


def score_team_for_dungeon(
    results: list[MonsterResult],
    requests: list[MonsterRequest],
    dungeon_waves: dict[int, list[dict]] | None,
) -> DungeonTeamEvaluation | None:
    """Evaluate selected builds against dungeon waves."""
    if not dungeon_waves:
        return None
    members = build_dungeon_combatants(results, requests)
    if not members:
        return None
    return evaluate_dungeon_team(members, dungeon_waves)


def _team_value(
    results: list[MonsterResult],
    requests: list[MonsterRequest],
    dungeon_waves: dict[int, list[dict]] | None,
) -> tuple[float, bool, DungeonTeamEvaluation | None]:
    score = 0.0
    for idx, result in enumerate(sorted(results, key=lambda r: r.priority)):
        score += _build_value(result.build)
        if result.build and result.build.meets_targets:
            score += max(0.0, 100.0 - float(idx))
    order_ok = _turn_order_ok(results)
    score += 15_000.0 if order_ok else -15_000.0
    built = sum(1 for r in results if r.build)
    score += built * 500.0
    dungeon_evaluation = score_team_for_dungeon(
        results,
        requests,
        dungeon_waves,
    )
    if dungeon_evaluation is not None:
        score += dungeon_evaluation.readiness_score * 1200.0
        score += dungeon_evaluation.success_probability * 300.0
    return score, order_ok, dungeon_evaluation


def optimize_team(
    rune_pool:  list[dict],
    requests:   list[MonsterRequest],
    top_n:      int = 1,
    dungeon_waves: dict[int, list[dict]] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> TeamResult:
    """Optimize rune assignment for a team of monsters.

    The optimizer expands multiple complete-team allocation states. Each
    monster is optimized against the remaining runes in each state, so later
    constraints can change which earlier allocation survives. Final states are
    scored for targets, sets, turn order, and optional dungeon readiness.
    """
    if cancel_check is not None and cancel_check():
        raise OptimizationCancelled("Optimization cancelled")
    if not requests:
        return TeamResult(monsters=[], team_avg_desr=0.0, turn_order_ok=True)

    branch_count = max(int(top_n or 1), 5)
    team_beam_width = max(20, len(requests) * 4)
    sorted_requests = sorted(requests, key=lambda request: request.priority)
    search_requests = sorted(
        sorted_requests,
        key=lambda request: (
            -len(request.set_reqs or []),
            -len(request.target_stats or {}),
            request.priority,
        ),
    )

    # Each state is (partial score, used rune IDs, selected results). Unlike
    # independent candidate generation, every optimize() call sees only runes
    # still available in that particular team allocation state.
    states: list[tuple[float, frozenset[int], list[MonsterResult]]] = [
        (0.0, frozenset(), [])
    ]
    total_requests = len(search_requests)
    for request_index, request in enumerate(search_requests):
        if cancel_check is not None and cancel_check():
            raise OptimizationCancelled("Optimization cancelled")
        if progress_callback is not None:
            progress_callback(
                request_index, total_requests,
                "Optimizing " + request.display_name,
            )
        next_states: list[
            tuple[float, frozenset[int], list[MonsterResult]]
        ] = []
        for state_index, (partial_score, used_ids, partial_results) in enumerate(states):
            if state_index % 4 == 0 and cancel_check is not None and cancel_check():
                raise OptimizationCancelled("Optimization cancelled")
            available_pool = [
                rune
                for rune in rune_pool
                if rune.get("rune_id") is None
                or int(rune["rune_id"]) not in used_ids
            ]
            builds = optimize(
                rune_pool=available_pool,
                set_reqs=request.set_reqs,
                current_build=request.current_build,
                main_stat_constraints=request.main_stat_constraints,
                target_stats=dict(request.target_stats or {}),
                top_n=branch_count,
                target_mode=request.target_mode,
                scoring_mode=request.scoring_mode,
                ref_atk=request.ref_atk,
                ref_cr=request.ref_cr,
                ref_cd=request.ref_cd,
                monster_info=request.monster_info,
                artifact_flat=request.artifact_flat,
                extra_bonuses=request.bonuses,
                max_stats=dict(request.max_stats or {}) or None,
                assume_max=request.assume_max,
                cancel_check=cancel_check,
            )
            valid_builds = [
                build
                for build in builds
                if not (_build_rune_ids(build) & used_ids)
            ]
            if not valid_builds:
                next_states.append(
                    (
                        partial_score + _build_value(None),
                        used_ids,
                        partial_results + [
                            MonsterResult(
                                unit_id=request.unit_id,
                                display_name=request.display_name,
                                priority=request.priority,
                                build=None,
                                meets_targets=False,
                                turn_pos=request.turn_pos,
                            )
                        ],
                    )
                )
                continue

            for build in valid_builds:
                rune_ids = _build_rune_ids(build)
                result = MonsterResult(
                    unit_id=request.unit_id,
                    display_name=request.display_name,
                    priority=request.priority,
                    build=build,
                    meets_targets=bool(build.meets_targets),
                    turn_pos=request.turn_pos,
                )
                priority_bonus = max(0.0, 100.0 - float(request.priority))
                next_states.append(
                    (
                        partial_score
                        + _build_value(build)
                        + (priority_bonus if build.meets_targets else 0.0),
                        used_ids | rune_ids,
                        partial_results + [result],
                    )
                )

        # Keep the best distinct allocations. This bounds runtime while still
        # preserving multiple competing allocations for later monsters.
        next_states.sort(key=lambda state: state[0], reverse=True)
        deduped = []
        seen_allocations: set[frozenset[int]] = set()
        for state in next_states:
            if state[1] in seen_allocations:
                continue
            seen_allocations.add(state[1])
            deduped.append(state)
            if len(deduped) >= team_beam_width:
                break
        states = deduped
        if progress_callback is not None:
            progress_callback(
                request_index + 1, total_requests,
                request.display_name + " complete",
            )
        if not states:
            break

    best_score = float("-inf")
    best_results: list[MonsterResult] | None = None
    best_order_ok = False
    best_dungeon_evaluation: DungeonTeamEvaluation | None = None
    for state_index, (_partial_score, _used_ids, complete_results) in enumerate(states):
        if state_index % 4 == 0 and cancel_check is not None and cancel_check():
            raise OptimizationCancelled("Optimization cancelled")
        score, order_ok, dungeon_evaluation = _team_value(
            complete_results,
            sorted_requests,
            dungeon_waves,
        )
        if score > best_score:
            best_score = score
            best_results = list(complete_results)
            best_order_ok = order_ok
            best_dungeon_evaluation = dungeon_evaluation

    if best_results is None:
        best_results = [
            MonsterResult(
                unit_id=request.unit_id,
                display_name=request.display_name,
                priority=request.priority,
                build=None,
                meets_targets=False,
                turn_pos=request.turn_pos,
            )
            for request in sorted_requests
        ]
        best_order_ok = False

    best_results.sort(key=lambda r: r.priority)
    desrs = [r.build.avg_desr for r in best_results if r.build]
    team_avg = round(sum(desrs) / len(desrs), 1) if desrs else 0.0

    return TeamResult(
        monsters=best_results,
        team_avg_desr=team_avg,
        turn_order_ok=best_order_ok,
        dungeon_score=(
            best_dungeon_evaluation.readiness_score
            if best_dungeon_evaluation is not None
            else None
        ),
        estimated_success=(
            best_dungeon_evaluation.success_probability
            if best_dungeon_evaluation is not None
            else None
        ),
        dungeon_evaluation=best_dungeon_evaluation,
    )
