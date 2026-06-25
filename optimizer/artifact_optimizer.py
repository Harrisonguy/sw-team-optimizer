"""Artifact pair and team optimization.

Artifacts are evaluated from their numeric SWEX effect IDs. The optimizer
enforces one Attribute artifact plus one Type artifact per monster, validates
element/archetype eligibility, and can allocate pairs across a team without
reusing an artifact.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import heapq
import json
from typing import Callable, Iterable

from optimizer.stat_utils import effective_hp, effective_offense
from src.core.artifacts.artifact_constants import artifact_effect_definition


_ELEMENT_EFFECT_ID = {
    "Fire": 300,
    "Water": 301,
    "Wind": 302,
    "Light": 303,
    "Dark": 304,
}
_ELEMENT_REDUCTION_ID = {
    "Fire": 305,
    "Water": 306,
    "Wind": 307,
    "Light": 308,
    "Dark": 309,
}
_SKILL_CD_IDS = {
    1: {400},
    2: {401},
    3: {402, 410},
    4: {403, 410},
}
_SUPPORT_CATEGORIES = {
    "buff_effect",
    "skill_accuracy",
    "skill_recovery",
    "recovery",
    "revive_effect",
}
_DAMAGE_BONUS_IDS = {208, 209, 210, 212, 225}


@dataclass(frozen=True)
class ArtifactProfile:
    goal: str = "damage"
    target_element: str | None = None
    skill_number: int | None = None
    single_target: bool = True
    first_attack: bool = False
    counterattack: bool = False
    coop_attack: bool = False
    bomb_damage: bool = False
    crushing_hit: bool = False
    enemy_hp_ratio: float = 1.0


@dataclass(frozen=True)
class ArtifactPairResult:
    attribute_artifact: dict | None
    type_artifact: dict | None
    score: float
    damage_gain: float
    survivability_gain: float
    support_score: float
    bonuses: dict
    reasons: tuple[str, ...]

    @property
    def artifacts(self) -> tuple[dict, ...]:
        return tuple(
            artifact
            for artifact in (self.attribute_artifact, self.type_artifact)
            if artifact is not None
        )

    @property
    def artifact_ids(self) -> frozenset[int]:
        return frozenset(
            int(artifact["artifact_id"])
            for artifact in self.artifacts
            if artifact.get("artifact_id") is not None
        )


@dataclass(frozen=True)
class ArtifactRequest:
    unit_id: int
    display_name: str
    monster_info: dict
    stats: dict
    profile: ArtifactProfile = field(default_factory=ArtifactProfile)


@dataclass(frozen=True)
class TeamArtifactMember:
    unit_id: int
    display_name: str
    pair: ArtifactPairResult | None


@dataclass(frozen=True)
class TeamArtifactResult:
    members: tuple[TeamArtifactMember, ...]
    total_score: float


def _decode_secondary_effects(artifact: dict) -> list[tuple[int, float]]:
    raw = artifact.get("sec_effect_data")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = []
    effects: list[tuple[int, float]] = []
    for item in raw or []:
        if isinstance(item, dict):
            effect_id = item.get("effect_id")
            value = item.get("value")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            effect_id, value = item[0], item[1]
        else:
            continue
        try:
            effects.append((int(effect_id), float(value or 0.0)))
        except (TypeError, ValueError):
            continue
    return effects


def artifact_effects(artifact: dict) -> list[tuple[int, float]]:
    """Return primary and secondary numeric effects for an artifact row."""
    effects: list[tuple[int, float]] = []
    effect_id = artifact.get("pri_effect_id")
    value = artifact.get("pri_effect_value")
    if effect_id is not None and value is not None:
        try:
            effects.append((int(effect_id), float(value)))
        except (TypeError, ValueError):
            pass
    effects.extend(_decode_secondary_effects(artifact))
    return effects


def artifact_matches_monster(artifact: dict, monster_info: dict) -> bool:
    """Check Attribute/Type artifact eligibility for one monster."""
    slot_label = str(artifact.get("slot_label") or "").strip().lower()
    requirement = str(artifact.get("requirement_label") or "").strip().lower()
    if requirement in {"", "universal", "none", "unknown"}:
        return True
    if slot_label == "attribute":
        element = str(monster_info.get("element") or "").strip().lower()
        return requirement == element
    if slot_label == "type":
        archetype = str(monster_info.get("archetype") or "").strip().lower()
        return requirement == archetype
    return False


def _effect_applies(effect_id: int, profile: ArtifactProfile) -> float:
    """Return a 0..1 context multiplier for conditional artifact effects."""
    hp_ratio = max(0.0, min(1.0, float(profile.enemy_hp_ratio)))
    if effect_id == 222:
        return hp_ratio
    if effect_id == 223:
        return 1.0 - hp_ratio
    if effect_id == 224:
        return 1.0 if profile.single_target else 0.0
    if effect_id == 411:
        return 1.0 if profile.first_attack else 0.0
    if effect_id in {400, 401, 402, 403, 410}:
        if profile.skill_number is None:
            return 0.0
        return 1.0 if effect_id in _SKILL_CD_IDS.get(profile.skill_number, set()) else 0.0
    if effect_id == 208:
        return 1.0 if profile.counterattack else 0.0
    if effect_id == 209:
        return 1.0 if profile.coop_attack else 0.0
    if effect_id == 210:
        return 1.0 if profile.bomb_damage else 0.0
    if effect_id == 212:
        return 1.0 if profile.crushing_hit else 0.0
    if effect_id == 225:
        return 1.0 if profile.counterattack or profile.coop_attack else 0.0
    return 1.0


def aggregate_artifact_bonuses(
    artifacts: Iterable[dict],
    profile: ArtifactProfile | None = None,
) -> dict:
    """Aggregate artifact stats and context-aware combat effects."""
    context = profile or ArtifactProfile()
    bonuses = {
        "hp": 0.0,
        "atk": 0.0,
        "def": 0.0,
        "cd_bonus": 0.0,
        "element_dmg": {},
        "addl_hp_pct": 0.0,
        "addl_atk_pct": 0.0,
        "addl_def_pct": 0.0,
        "addl_spd_pct": 0.0,
        "damage_bonus_pct": 0.0,
        "damage_reduction_pct": 0.0,
        "support_value": 0.0,
        "effect_values": {},
    }
    target_element = (context.target_element or "").title()
    target_damage_id = _ELEMENT_EFFECT_ID.get(target_element)
    target_reduction_id = _ELEMENT_REDUCTION_ID.get(target_element)

    for artifact in artifacts:
        for effect_id, value in artifact_effects(artifact):
            bonuses["effect_values"][effect_id] = (
                bonuses["effect_values"].get(effect_id, 0.0) + value
            )
            if effect_id == 100:
                bonuses["hp"] += value
                continue
            if effect_id == 101:
                bonuses["atk"] += value
                continue
            if effect_id == 102:
                bonuses["def"] += value
                continue
            if effect_id == 218:
                bonuses["addl_hp_pct"] += value
                continue
            if effect_id == 219:
                bonuses["addl_atk_pct"] += value
                continue
            if effect_id == 220:
                bonuses["addl_def_pct"] += value
                continue
            if effect_id == 221:
                bonuses["addl_spd_pct"] += value
                continue
            if 300 <= effect_id <= 304:
                bonuses["element_dmg"][effect_id] = (
                    bonuses["element_dmg"].get(effect_id, 0.0) + value
                )
                continue

            definition = artifact_effect_definition(effect_id) or {}
            category = definition.get("category")
            context_weight = _effect_applies(effect_id, context)
            if category in {"crit_damage_condition", "skill_crit_damage"}:
                bonuses["cd_bonus"] += value * context_weight
            elif effect_id in _DAMAGE_BONUS_IDS:
                bonuses["damage_bonus_pct"] += value * context_weight
            elif category in _SUPPORT_CATEGORIES:
                bonuses["support_value"] += value
            elif category == "damage_reduction":
                bonuses["damage_reduction_pct"] += value
            elif effect_id == target_reduction_id:
                bonuses["damage_reduction_pct"] += value

    bonuses["element_bonus_pct"] = float(
        bonuses["element_dmg"].get(target_damage_id, 0.0)
        if target_damage_id is not None
        else 0.0
    )
    return bonuses


def _score_pair(
    attribute_artifact: dict | None,
    type_artifact: dict | None,
    stats: dict,
    profile: ArtifactProfile,
) -> ArtifactPairResult:
    artifacts = [
        artifact
        for artifact in (attribute_artifact, type_artifact)
        if artifact is not None
    ]
    bonuses = aggregate_artifact_bonuses(artifacts, profile)
    updated_stats = dict(stats)
    updated_stats["hp"] = float(stats.get("hp") or 0) + bonuses["hp"]
    updated_stats["atk"] = float(stats.get("atk") or 0) + bonuses["atk"]
    updated_stats["def_"] = float(stats.get("def_") or 0) + bonuses["def"]

    base_eo = effective_offense(stats)
    optimized_eo = effective_offense(
        updated_stats,
        cd_bonus=bonuses["cd_bonus"],
        element_bonus=bonuses["element_bonus_pct"],
        addl_atk_pct=bonuses["addl_atk_pct"],
        addl_hp_pct=bonuses["addl_hp_pct"],
        addl_def_pct=bonuses["addl_def_pct"],
        addl_spd_pct=bonuses["addl_spd_pct"],
    )
    damage_gain = float(optimized_eo - base_eo)
    damage_gain += base_eo * bonuses["damage_bonus_pct"] / 100.0

    base_ehp = effective_hp(stats)
    optimized_ehp = effective_hp(updated_stats)
    survivability_gain = float(optimized_ehp - base_ehp)
    survivability_gain += base_ehp * bonuses["damage_reduction_pct"] / 100.0

    support_score = float(bonuses["support_value"])
    goal = profile.goal.lower()
    if goal == "survivability":
        score = survivability_gain + support_score * 20.0 + damage_gain * 0.05
    elif goal == "support":
        score = support_score * 100.0 + survivability_gain * 0.08 + damage_gain * 0.05
    elif goal == "balanced":
        score = damage_gain + survivability_gain * 0.15 + support_score * 40.0
    else:
        score = damage_gain + survivability_gain * 0.01 + support_score * 2.0

    reasons = []
    for artifact in artifacts:
        label = str(artifact.get("pri_effect") or "").strip()
        if label:
            reasons.append(label)
        raw_labels = artifact.get("sec_effects")
        if isinstance(raw_labels, str):
            try:
                raw_labels = json.loads(raw_labels)
            except (TypeError, ValueError):
                raw_labels = []
        reasons.extend(str(label) for label in (raw_labels or []) if label)

    return ArtifactPairResult(
        attribute_artifact=attribute_artifact,
        type_artifact=type_artifact,
        score=round(score, 3),
        damage_gain=round(damage_gain, 3),
        survivability_gain=round(survivability_gain, 3),
        support_score=round(support_score, 3),
        bonuses=bonuses,
        reasons=tuple(reasons[:8]),
    )


def rank_artifact_pairs(
    artifacts: Iterable[dict],
    monster_info: dict,
    stats: dict,
    profile: ArtifactProfile | None = None,
    top_n: int = 10,
    include_equipped: bool = False,
    cancel_check: Callable[[], bool] | None = None,
) -> list[ArtifactPairResult]:
    """Rank eligible Attribute/Type pairs for one monster."""
    if cancel_check is not None and cancel_check():
        from optimizer.rune_optimizer import OptimizationCancelled
        raise OptimizationCancelled("Optimization cancelled")
    context = profile or ArtifactProfile()
    unit_id = monster_info.get("unit_id")
    eligible = []
    for artifact in artifacts:
        occupied_id = artifact.get("occupied_id")
        if (
            not include_equipped
            and occupied_id not in (None, 0, unit_id)
        ):
            continue
        if artifact_matches_monster(artifact, monster_info):
            eligible.append(artifact)

    attribute_artifacts = [
        artifact for artifact in eligible
        if str(artifact.get("slot_label") or "").lower() == "attribute"
    ]
    type_artifacts = [
        artifact for artifact in eligible
        if str(artifact.get("slot_label") or "").lower() == "type"
    ]
    shortlist_size = max(48, int(top_n) * 4)
    if len(attribute_artifacts) > shortlist_size:
        attribute_artifacts = sorted(
            attribute_artifacts,
            key=lambda artifact: _score_pair(
                artifact,
                None,
                stats,
                context,
            ).score,
            reverse=True,
        )[:shortlist_size]
    if len(type_artifacts) > shortlist_size:
        type_artifacts = sorted(
            type_artifacts,
            key=lambda artifact: _score_pair(
                None,
                artifact,
                stats,
                context,
            ).score,
            reverse=True,
        )[:shortlist_size]

    attribute_options: list[dict | None] = attribute_artifacts or [None]
    type_options: list[dict | None] = type_artifacts or [None]

    limit = max(1, int(top_n))
    heap: list[tuple[float, int, ArtifactPairResult]] = []
    serial = 0
    for attribute_index, attribute_artifact in enumerate(attribute_options):
        if attribute_index % 8 == 0 and cancel_check is not None and cancel_check():
            from optimizer.rune_optimizer import OptimizationCancelled
            raise OptimizationCancelled("Optimization cancelled")
        for type_artifact in type_options:
            result = _score_pair(attribute_artifact, type_artifact, stats, context)
            item = (result.score, serial, result)
            serial += 1
            if len(heap) < limit:
                heapq.heappush(heap, item)
            elif result.score > heap[0][0]:
                heapq.heapreplace(heap, item)
    return [
        item[2]
        for item in sorted(heap, key=lambda item: (item[0], item[1]), reverse=True)
    ]


def optimize_team_artifacts(
    artifacts: Iterable[dict],
    requests: list[ArtifactRequest],
    top_n_per_monster: int = 12,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> TeamArtifactResult:
    """Choose conflict-free artifact pairs for all requested monsters."""
    artifact_rows = list(artifacts)
    candidates = []
    for request_index, request in enumerate(requests):
        if cancel_check is not None and cancel_check():
            from optimizer.rune_optimizer import OptimizationCancelled
            raise OptimizationCancelled("Optimization cancelled")
        candidates.append(
            rank_artifact_pairs(
                artifact_rows, request.monster_info, request.stats,
                request.profile, top_n=max(1, top_n_per_monster),
                include_equipped=True, cancel_check=cancel_check,
            )
        )
        if progress_callback is not None:
            progress_callback(
                request_index + 1, len(requests),
                "Artifact candidates for " + request.display_name,
            )
    best_score = float("-inf")
    best_pairs: list[ArtifactPairResult | None] = [None] * len(requests)
    suffix_max = [0.0] * (len(requests) + 1)
    for index in range(len(requests) - 1, -1, -1):
        best_candidate = candidates[index][0].score if candidates[index] else 0.0
        suffix_max[index] = suffix_max[index + 1] + best_candidate

    def search(
        index: int,
        used_ids: frozenset[int],
        score: float,
        selected: list[ArtifactPairResult | None],
    ) -> None:
        nonlocal best_score, best_pairs
        if cancel_check is not None and cancel_check():
            from optimizer.rune_optimizer import OptimizationCancelled
            raise OptimizationCancelled("Optimization cancelled")
        if score + suffix_max[index] <= best_score:
            return
        if index == len(requests):
            if score > best_score:
                best_score = score
                best_pairs = list(selected)
            return
        options = candidates[index] or [None]
        for pair in options:
            pair_ids = pair.artifact_ids if pair is not None else frozenset()
            if used_ids & pair_ids:
                continue
            selected.append(pair)
            search(
                index + 1,
                used_ids | pair_ids,
                score + (pair.score if pair is not None else 0.0),
                selected,
            )
            selected.pop()

    search(0, frozenset(), 0.0, [])
    members = tuple(
        TeamArtifactMember(
            unit_id=request.unit_id,
            display_name=request.display_name,
            pair=best_pairs[index],
        )
        for index, request in enumerate(requests)
    )
    return TeamArtifactResult(
        members=members,
        total_score=round(0.0 if best_score == float("-inf") else best_score, 3),
    )
