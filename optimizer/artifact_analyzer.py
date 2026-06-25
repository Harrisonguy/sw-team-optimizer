"""Artifact inventory efficiency and upgrade/sell recommendations.

Scores are relative to the active account. This avoids presenting uncertain
community roll ranges as exact game constants while still finding which
artifacts are genuinely stronger than the alternatives already owned.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
import json
import math
from typing import Any, Iterable

from src.core.artifacts.artifact_constants import artifact_effect_definition


_UPGRADE_THRESHOLDS = (3, 6, 9, 12)
_OFFENSE_IDS = frozenset(
    set(range(208, 213))
    | set(range(218, 227))
    | set(range(300, 305))
    | set(range(400, 404))
    | {410, 411}
)
_SURVIVAL_IDS = frozenset(
    {200, 201, 205, 213, 214, 215, 216}
    | set(range(305, 310))
    | set(range(404, 407))
)
_SUPPORT_IDS = frozenset({202, 203, 204, 206, 207, 217, 226, 407, 408, 409})
_HIGH_VALUE_IDS = frozenset({218, 219, 220, 221, 222, 223, 224, 300, 301, 302, 303, 304, 400, 401, 402, 403, 410, 411})


def _row_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except (TypeError, ValueError):
        return {}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _secondary_effects(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    raw = artifact.get("sec_effect_data")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            raw = []
    result = []
    for item in raw or []:
        if isinstance(item, dict):
            effect_id = item.get("effect_id")
            value = item.get("value")
            roll_count = item.get("roll_count")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            effect_id = item[0]
            value = item[1]
            roll_count = item[2] if len(item) >= 3 else 0
        else:
            continue
        try:
            result.append({
                "effect_id": int(effect_id),
                "value": max(0.0, float(value or 0.0)),
                "roll_count": max(0, int(roll_count or 0)),
            })
        except (TypeError, ValueError):
            continue
    return result


def _percentile_rank(ordered: list[float], value: float) -> float:
    if not ordered:
        return 0.0
    return max(0.0, min(100.0, 100.0 * (bisect_right(ordered, value) - 0.5) / len(ordered)))


def _effect_bucket(effect_id: int) -> str:
    if effect_id in _OFFENSE_IDS:
        return "Offense"
    if effect_id in _SURVIVAL_IDS:
        return "Survival"
    if effect_id in _SUPPORT_IDS:
        return "Support"
    definition = artifact_effect_definition(effect_id) or {}
    category = str(definition.get("category") or "")
    if "damage" in category or "crit" in category:
        return "Offense"
    if "recovery" in category or "reduction" in category:
        return "Survival"
    return "Utility"


def _utility_weight(effect_id: int) -> float:
    if effect_id in _HIGH_VALUE_IDS:
        return 1.0
    definition = artifact_effect_definition(effect_id) or {}
    category = str(definition.get("category") or "")
    if definition.get("damage_relevant"):
        return 0.90
    if category in {"damage_reduction", "skill_crit_damage", "crit_damage_condition"}:
        return 0.90
    if definition.get("stat_relevant"):
        return 0.78
    if "accuracy" in category or "recovery" in category or "buff" in category:
        return 0.72
    return 0.58


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = max(0.0, min(1.0, percentile)) * (len(ordered) - 1)
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return ordered[low]
    fraction = position - low
    return ordered[low] * (1.0 - fraction) + ordered[high] * fraction


def _score_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    per_roll: dict[int, list[float]] = defaultdict(list)
    totals: dict[int, list[float]] = defaultdict(list)
    decoded: dict[int, list[dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        effects = _secondary_effects(row)
        decoded[index] = effects
        for effect in effects:
            rolls = effect["roll_count"] + 1
            per_roll[effect["effect_id"]].append(effect["value"] / rolls)
            totals[effect["effect_id"]].append(effect["value"])
    for values in per_roll.values():
        values.sort()
    for values in totals.values():
        values.sort()

    scored = []
    for index, row in enumerate(rows):
        effects = decoded[index]
        raw_quality = []
        weighted_quality = []
        roll_weights = []
        bucket_weights: dict[str, float] = defaultdict(float)
        for effect in effects:
            effect_id = effect["effect_id"]
            rolls = effect["roll_count"] + 1
            roll_rank = _percentile_rank(per_roll[effect_id], effect["value"] / rolls)
            total_rank = _percentile_rank(totals[effect_id], effect["value"])
            quality = 0.55 * roll_rank + 0.45 * total_rank
            utility = _utility_weight(effect_id)
            weight = float(rolls)
            raw_quality.append(quality)
            weighted_quality.append(quality * utility * weight)
            roll_weights.append(weight)
            bucket_weights[_effect_bucket(effect_id)] += weight * utility

        efficiency = sum(raw_quality) / len(raw_quality) if raw_quality else 0.0
        practical = sum(weighted_quality) / sum(roll_weights) if roll_weights else 0.0
        total_bucket = sum(bucket_weights.values())
        synergy = 100.0 * max(bucket_weights.values(), default=0.0) / total_bucket if total_bucket else 0.0
        natural_rank = int(_number(row.get("natural_rank") or row.get("rank")))
        rank_score = min(100.0, natural_rank / 5.0 * 100.0)
        revealed_score = min(100.0, len(effects) / 4.0 * 100.0)
        value_score = 0.62 * practical + 0.18 * synergy + 0.12 * rank_score + 0.08 * revealed_score
        level = int(_number(row.get("level")))
        remaining = sum(1 for threshold in _UPGRADE_THRESHOLDS if threshold > level)
        potential = min(100.0, value_score + remaining * (6.0 + natural_rank * 0.8))
        profile = max(bucket_weights, key=bucket_weights.get) if bucket_weights else "Unclear"

        item = dict(row)
        item.update({
            "artifact_efficiency": round(efficiency, 1),
            "artifact_value": round(value_score, 1),
            "artifact_potential": round(potential, 1),
            "artifact_synergy": round(synergy, 1),
            "artifact_profile": profile,
            "artifact_effect_count": len(effects),
            "artifact_remaining_rolls": remaining,
        })
        scored.append(item)
    return scored


def analyze_artifact_inventory(artifacts: Iterable[Any]) -> dict[str, Any]:
    """Score an inventory and add conservative keep/upgrade/sell actions."""
    rows = [_row_dict(row) for row in artifacts]
    scored = _score_rows(rows)
    completed_storage = [
        row for row in scored
        if int(_number(row.get("level"))) >= 12
        and not row.get("occupied_id")
        and not row.get("locked")
    ]
    completed_scores = [row["artifact_value"] for row in completed_storage]
    keep_bar = max(38.0, min(65.0, _percentile(completed_scores, 0.35))) if completed_scores else 45.0

    groups: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in scored:
        key = (
            str(row.get("slot_label") or ""),
            str(row.get("requirement_label") or ""),
        )
        groups[key].append(row["artifact_value"])
    for values in groups.values():
        values.sort(reverse=True)

    counts = {"Keep": 0, "Upgrade": 0, "Review": 0, "Sell": 0}
    for row in scored:
        level = int(_number(row.get("level")))
        natural_rank = int(_number(row.get("natural_rank") or row.get("rank")))
        value = float(row["artifact_value"])
        potential = float(row["artifact_potential"])
        key = (
            str(row.get("slot_label") or ""),
            str(row.get("requirement_label") or ""),
        )
        better_count = sum(1 for candidate in groups[key] if candidate > value + 0.01)

        if row.get("locked"):
            action = "Keep"
            reason = "Locked by the player."
        elif row.get("occupied_id"):
            action = "Keep"
            reason = "Equipped; compare it in the artifact optimizer before replacing it."
        elif (
            "unknown" in str(row.get("slot_label") or "").lower()
            or "unknown" in str(row.get("requirement_label") or "").lower()
            or (level >= 12 and int(row.get("artifact_effect_count") or 0) < 4)
        ):
            action = "Review"
            reason = "Import data is incomplete or uses an unsupported requirement code."
        elif level < 12:
            if natural_rank >= 4 and potential >= keep_bar:
                action = "Upgrade"
                reason = (
                    str(row["artifact_remaining_rolls"])
                    + " upgrade events remain and projected value reaches "
                    + str(round(potential))
                    + "."
                )
            else:
                action = "Review"
                reason = "Not enough effects are revealed for a safe sell decision."
        elif value >= keep_bar:
            action = "Keep"
            reason = "Value is above this account's keep bar of " + str(round(keep_bar)) + "."
        elif value >= keep_bar - 10.0 or better_count < 3:
            action = "Review"
            reason = "Below the keep bar, but the account lacks enough clearly better replacements."
        else:
            action = "Sell"
            reason = (
                str(better_count)
                + " stronger "
                + (str(row.get("requirement_label") or "matching"))
                + " "
                + (str(row.get("slot_label") or "artifact").lower())
                + " artifacts are already owned."
            )
        row["artifact_action"] = action
        row["artifact_reason"] = reason
        row["artifact_better_count"] = better_count
        counts[action] += 1

    action_order = {"Upgrade": 0, "Review": 1, "Sell": 2, "Keep": 3}
    scored.sort(
        key=lambda row: (
            action_order.get(row["artifact_action"], 9),
            -row["artifact_potential"] if row["artifact_action"] == "Upgrade" else row["artifact_value"],
            int(_number(row.get("artifact_id"))),
        )
    )
    return {
        "artifacts": scored,
        "counts": counts,
        "keep_bar": round(keep_bar, 1),
        "average_efficiency": round(
            sum(row["artifact_efficiency"] for row in scored) / len(scored), 1
        ) if scored else 0.0,
        "average_value": round(
            sum(row["artifact_value"] for row in scored) / len(scored), 1
        ) if scored else 0.0,
    }
