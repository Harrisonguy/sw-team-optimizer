"""Account progression analysis and prioritized farming recommendations.

The analyzer is deliberately UI and database agnostic. It accepts dictionary-like
rows so its decisions can be tested independently from SQLite and PySide6.
"""
from __future__ import annotations

from collections import defaultdict
import json
import math
from typing import Any, Iterable


CORE_SETS: dict[str, dict[str, Any]] = {
    "Swift": {"pieces": 4, "dungeon": "Giant's Keep", "demand": 1.45},
    "Despair": {"pieces": 4, "dungeon": "Giant's Keep", "demand": 0.85},
    "Fatal": {"pieces": 4, "dungeon": "Giant's Keep", "demand": 0.55},
    "Blade": {"pieces": 2, "dungeon": "Giant's Keep", "demand": 0.55},
    "Violent": {"pieces": 4, "dungeon": "Dragon's Lair", "demand": 1.60},
    "Revenge": {"pieces": 2, "dungeon": "Dragon's Lair", "demand": 0.55},
    "Focus": {"pieces": 2, "dungeon": "Dragon's Lair", "demand": 0.45},
    "Shield": {"pieces": 2, "dungeon": "Dragon's Lair", "demand": 0.40},
    "Will": {"pieces": 2, "dungeon": "Necropolis", "demand": 1.35},
    "Rage": {"pieces": 4, "dungeon": "Necropolis", "demand": 0.95},
    "Nemesis": {"pieces": 2, "dungeon": "Necropolis", "demand": 0.45},
    "Vampire": {"pieces": 4, "dungeon": "Necropolis", "demand": 0.35},
    "Fight": {"pieces": 2, "dungeon": "Spiritual Realm", "demand": 0.90},
    "Determination": {"pieces": 2, "dungeon": "Spiritual Realm", "demand": 0.45},
    "Enhance": {"pieces": 2, "dungeon": "Spiritual Realm", "demand": 0.35},
    "Accuracy": {"pieces": 2, "dungeon": "Spiritual Realm", "demand": 0.30},
}

DUNGEON_SETS: dict[str, tuple[str, ...]] = {
    "Giant's Keep": ("Swift", "Despair", "Fatal", "Blade"),
    "Dragon's Lair": ("Violent", "Revenge", "Focus", "Shield"),
    "Necropolis": ("Will", "Rage", "Nemesis", "Vampire"),
    "Spiritual Realm": ("Fight", "Determination", "Enhance", "Accuracy"),
}

_GRINDABLE_STATS = frozenset({1, 2, 3, 4, 5, 6, 8})
_GRIND_MAX = {1: 550.0, 2: 10.0, 3: 30.0, 4: 10.0, 5: 30.0, 6: 10.0, 8: 5.0}


def _row_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    try:
        return dict(row)
    except (TypeError, ValueError):
        return {}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _percentile(values: Iterable[float], percentile: float) -> float:
    ordered = sorted(_number(value) for value in values)
    if not ordered:
        return 0.0
    position = max(0.0, min(1.0, percentile)) * (len(ordered) - 1)
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return ordered[low]
    fraction = position - low
    return ordered[low] * (1.0 - fraction) + ordered[high] * fraction


def _parse_substats(raw: Any) -> list[list[Any]]:
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def _speed_value(rune: dict[str, Any]) -> float:
    total = 0.0
    for sub in _parse_substats(rune.get("sec_eff")):
        if not sub or len(sub) < 2 or sub[0] != 8:
            continue
        total += _number(sub[1])
        if len(sub) >= 4:
            total += _number(sub[3])
    if rune.get("prefix_stat_id") == 8:
        total += _number(rune.get("prefix_stat_value"))
    return total


def _set_analysis(runes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rune in runes:
        if rune.get("set_name"):
            grouped[str(rune["set_name"])].append(rune)

    names = sorted(set(grouped) | set(CORE_SETS))
    result: list[dict[str, Any]] = []
    for name in names:
        items = grouped.get(name, [])
        desirabilities = [_number(r.get("desirability")) for r in items]
        efficiencies = [_number(r.get("efficiency")) for r in items]
        speeds = [value for value in (_speed_value(r) for r in items) if value > 0]
        usable = [r for r in items if _number(r.get("desirability")) >= 35 and int(_number(r.get("stars"))) >= 6]
        best = sorted(desirabilities, reverse=True)[:24]
        pieces = int(CORE_SETS.get(name, {}).get("pieces", 2))
        quality = min(100.0, ((_number(sum(best) / len(best)) if best else 0.0) / 75.0) * 100.0)
        depth = min(100.0, len(usable) / max(1, pieces * 6) * 100.0)
        per_slot = [sum(1 for r in usable if int(_number(r.get("slot_no"))) == slot) for slot in range(1, 7)]
        balance = min(100.0, (min(per_slot) if per_slot else 0) / 4.0 * 100.0)
        score = 0.60 * quality + 0.25 * depth + 0.15 * balance
        result.append({
            "set_name": name,
            "count": len(items),
            "usable_count": len(usable),
            "build_depth": round(len(usable) / max(1, pieces), 1),
            "avg_efficiency": round(sum(efficiencies) / len(efficiencies), 1) if efficiencies else 0.0,
            "avg_desirability": round(sum(desirabilities) / len(desirabilities), 1) if desirabilities else 0.0,
            "top_10_pct": round(_percentile(desirabilities, 0.90), 1),
            "bottom_10_pct": round(_percentile(desirabilities, 0.10), 1),
            "avg_speed": round(sum(speeds) / len(speeds), 1) if speeds else 0.0,
            "quality_score": round(score, 1),
            "weak_slots": [slot for slot, count in enumerate(per_slot, 1) if count == min(per_slot or [0])],
            "dungeon": CORE_SETS.get(name, {}).get("dungeon", ""),
        })
    return sorted(result, key=lambda item: (-item["quality_score"], item["set_name"]))


def _slot_analysis(runes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for slot in range(1, 7):
        items = [r for r in runes if int(_number(r.get("slot_no"))) == slot]
        values = sorted((_number(r.get("desirability")) for r in items), reverse=True)
        top = values[:40]
        result.append({
            "slot": slot,
            "count": len(items),
            "usable_count": sum(1 for r in items if _number(r.get("desirability")) >= 35 and int(_number(r.get("stars"))) >= 6),
            "top_quality": round(sum(top) / len(top), 1) if top else 0.0,
        })
    return result


def _speed_analysis(runes: list[dict[str, Any]]) -> dict[str, Any]:
    speeds = [_speed_value(rune) for rune in runes]
    speeds = [speed for speed in speeds if speed > 0]
    return {
        "runes_with_speed": len(speeds),
        "average": round(sum(speeds) / len(speeds), 1) if speeds else 0.0,
        "p90": round(_percentile(speeds, 0.90), 1),
        "fastest": round(max(speeds), 1) if speeds else 0.0,
        "at_least_15": sum(1 for speed in speeds if speed >= 15),
        "at_least_20": sum(1 for speed in speeds if speed >= 20),
        "at_least_25": sum(1 for speed in speeds if speed >= 25),
    }


def _grind_analysis(runes: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = 0
    ground = 0
    total_value = 0.0
    quality_values: list[float] = []
    for rune in runes:
        for sub in _parse_substats(rune.get("sec_eff")):
            if not sub or len(sub) < 2 or sub[0] not in _GRINDABLE_STATS:
                continue
            eligible += 1
            grind = _number(sub[3]) if len(sub) >= 4 else 0.0
            if grind > 0:
                ground += 1
                total_value += grind
                quality_values.append(min(1.0, grind / _GRIND_MAX[sub[0]]) * 100.0)
    return {
        "eligible_substats": eligible,
        "ground_substats": ground,
        "coverage_pct": round(100.0 * ground / eligible, 1) if eligible else 0.0,
        "average_grind": round(total_value / ground, 1) if ground else 0.0,
        "quality_pct": round(sum(quality_values) / len(quality_values), 1) if quality_values else 0.0,
    }


def _artifact_analysis(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    if not artifacts:
        return {"count": 0, "score": 0.0, "maxed": 0, "legend": 0, "attribute_score": 0.0, "type_score": 0.0}

    from optimizer.artifact_analyzer import analyze_artifact_inventory

    report = analyze_artifact_inventory(artifacts)
    scored = report["artifacts"]

    def group_score(items: list[dict[str, Any]], limit: int) -> float:
        if not items:
            return 0.0
        values = sorted(
            (float(item.get("artifact_value") or 0.0) for item in items),
            reverse=True,
        )[:limit]
        quality = sum(values) / len(values)
        depth = min(100.0, len(items) / max(1, limit) * 100.0)
        return round(min(100.0, quality * 0.85 + depth * 0.15), 1)

    attribute = [a for a in scored if "attribute" in str(a.get("slot_label", "")).lower()]
    type_items = [a for a in scored if "type" in str(a.get("slot_label", "")).lower()]
    return {
        "count": len(artifacts),
        "score": group_score(scored, 160),
        "maxed": sum(1 for a in artifacts if _number(a.get("level")) >= 15),
        "legend": sum(1 for a in artifacts if _number(a.get("rank")) >= 5),
        "attribute_score": group_score(attribute, 80),
        "type_score": group_score(type_items, 80),
        "average_efficiency": report["average_efficiency"],
        "average_value": report["average_value"],
        "review_counts": report["counts"],
    }


def _monster_upgrades(monsters: list[dict[str, Any]], runes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_monster: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for rune in runes:
        unit_id = int(_number(rune.get("occupied_id")))
        if unit_id:
            by_monster[unit_id].append(rune)

    targets = []
    for monster in monsters:
        unit_id = int(_number(monster.get("unit_id")))
        equipped = by_monster.get(unit_id, [])
        if (
            not equipped
            or int(_number(monster.get("stars"))) < 6
            or int(_number(monster.get("level"))) < 35
        ):
            continue
        values = [_number(r.get("desirability")) for r in equipped]
        missing = max(0, 6 - len({int(_number(r.get("slot_no"))) for r in equipped}))
        targets.append({
            "unit_id": unit_id,
            "name": monster.get("display_name") or monster.get("base_name") or ("Monster " + str(unit_id)),
            "rune_count": len(equipped),
            "missing_slots": missing,
            "avg_desirability": round(sum(values) / len(values), 1) if values else 0.0,
            "stars": int(_number(monster.get("stars"))),
            "level": int(_number(monster.get("level"))),
        })
    return sorted(targets, key=lambda item: (item["missing_slots"] == 0, item["avg_desirability"], -item["stars"]))[:8]


def _farming_priorities(set_rows: list[dict[str, Any]], artifact: dict[str, Any]) -> list[dict[str, Any]]:
    by_name = {row["set_name"]: row for row in set_rows}
    result = []
    for dungeon, set_names in DUNGEON_SETS.items():
        weighted_need = 0.0
        weight_total = 0.0
        limiting = []
        for name in set_names:
            weight = _number(CORE_SETS[name]["demand"], 1.0)
            quality = _number(by_name.get(name, {}).get("quality_score"))
            weighted_need += weight * (100.0 - quality)
            weight_total += weight
            limiting.append((weight * (100.0 - quality), name, by_name.get(name, {}).get("weak_slots", [])))
        priority = weighted_need / max(weight_total, 1.0)
        limiting.sort(reverse=True)
        targets = [item[1] for item in limiting[:2]]
        slots = sorted({slot for _, _, weak_slots in limiting[:2] for slot in weak_slots})
        reason = "Improve " + " and ".join(targets)
        if len(slots) == 6:
            reason += " across all slots"
        elif slots:
            reason += ", especially slots " + ", ".join(str(slot) for slot in slots)
        result.append({"dungeon": dungeon, "priority": round(priority, 1), "targets": targets, "reason": reason})

    for dungeon, key, label in (
        ("Steel Fortress", "attribute_score", "attribute artifacts"),
        ("Punisher's Crypt", "type_score", "type artifacts"),
    ):
        quality = _number(artifact.get(key))
        result.append({
            "dungeon": dungeon,
            "priority": round(max(0.0, 100.0 - quality) * 0.80, 1),
            "targets": [label],
            "reason": "Improve " + label + "; current readiness is " + str(round(quality)) + "/100",
        })
    return sorted(result, key=lambda item: (-item["priority"], item["dungeon"]))


def analyze_account(
    runes: Iterable[Any],
    monsters: Iterable[Any] = (),
    artifacts: Iterable[Any] = (),
    buildings: Iterable[Any] = (),
) -> dict[str, Any]:
    """Return an actionable account progression report."""
    rune_rows = [_row_dict(row) for row in runes]
    monster_rows = [_row_dict(row) for row in monsters]
    artifact_rows = [_row_dict(row) for row in artifacts]
    building_rows = [_row_dict(row) for row in buildings]

    sets = _set_analysis(rune_rows)
    slots = _slot_analysis(rune_rows)
    speed = _speed_analysis(rune_rows)
    grinds = _grind_analysis(rune_rows)
    artifact = _artifact_analysis(artifact_rows)
    upgrades = _monster_upgrades(monster_rows, rune_rows)
    farming = _farming_priorities(sets, artifact)

    desirabilities = sorted((_number(r.get("desirability")) for r in rune_rows), reverse=True)
    top_runes = desirabilities[:120]
    quality_score = min(100.0, ((sum(top_runes) / len(top_runes)) if top_runes else 0.0) / 75.0 * 100.0)
    usable_count = sum(1 for r in rune_rows if int(_number(r.get("stars"))) >= 6 and _number(r.get("desirability")) >= 35)
    depth_score = min(100.0, usable_count / 300.0 * 100.0)
    speed_score = min(100.0, _number(speed["p90"]) / 25.0 * 100.0)
    rune_score = 0.55 * quality_score + 0.25 * depth_score + 0.20 * speed_score
    maxed_monsters = sum(1 for m in monster_rows if int(_number(m.get("stars"))) >= 6 and int(_number(m.get("level"))) >= 40)
    roster_score = min(100.0, maxed_monsters / 40.0 * 100.0)
    building_score = min(100.0, sum(_number(row.get("bonus_pct")) for row in building_rows) / 1.2)
    account_score = round(0.70 * rune_score + 0.15 * artifact["score"] + 0.10 * roster_score + 0.05 * building_score, 1)
    tier = "Developing" if account_score < 35 else "Established" if account_score < 55 else "Strong" if account_score < 75 else "Elite"

    core_rows = [
        row for row in sets
        if row["set_name"] in CORE_SETS and _number(CORE_SETS[row["set_name"]]["demand"]) >= 0.80
    ]
    strongest = max(core_rows, key=lambda row: row["quality_score"], default={"set_name": "--", "quality_score": 0})
    weakest = min(core_rows, key=lambda row: row["quality_score"], default={"set_name": "--", "quality_score": 0})
    weakest_slot = min(slots, key=lambda row: row["top_quality"], default={"slot": 0, "top_quality": 0})

    recommendations: list[dict[str, str]] = []
    if not rune_rows:
        recommendations.append({"priority": "Now", "title": "Import an account", "action": "Import a SWEX JSON file to generate a personal progression plan.", "reason": "No rune inventory is loaded."})
    else:
        focus = farming[0]
        recommendations.append({"priority": "Now", "title": "Farm " + focus["dungeon"], "action": focus["reason"] + ".", "reason": "This is the largest weighted gap across the account's core builds."})
        recommendations.append({"priority": "High", "title": "Strengthen slot " + str(weakest_slot["slot"]), "action": "Prioritize six-star runes with useful main stats in this slot.", "reason": "Its top inventory quality is " + str(weakest_slot["top_quality"]) + ", the lowest of all six slots."})
        if speed["at_least_20"] < 30:
            recommendations.append({"priority": "High", "title": "Build more speed depth", "action": "Keep and roll promising Swift, Violent, and Will runes with SPD.", "reason": "Only " + str(speed["at_least_20"]) + " runes currently reach 20+ SPD."})
        if grinds["coverage_pct"] < 65:
            recommendations.append({"priority": "Medium", "title": "Finish priority grinds", "action": "Grind SPD and percentage stats on runes used by dungeon teams first.", "reason": "Only " + str(grinds["coverage_pct"]) + "% of grindable substats have a grind."})
        if upgrades:
            target = upgrades[0]
            action = "Fill " + str(target["missing_slots"]) + " missing rune slots." if target["missing_slots"] else "Replace the weakest rune in this equipped build."
            recommendations.append({"priority": "Medium", "title": "Upgrade " + str(target["name"]), "action": action, "reason": "Its equipped rune average is " + str(target["avg_desirability"]) + "."})
        if artifact["score"] < 65:
            dungeon = "Steel Fortress" if artifact["attribute_score"] <= artifact["type_score"] else "Punisher's Crypt"
            recommendations.append({"priority": "Medium", "title": "Improve artifacts", "action": "Farm " + dungeon + " and upgrade high-value secondary effects.", "reason": "Artifact readiness is " + str(artifact["score"]) + "/100."})

    return {
        "account_score": account_score,
        "account_tier": tier,
        "rune_score": round(rune_score, 1),
        "strongest_set": strongest,
        "weakest_set": weakest,
        "weakest_slot": weakest_slot,
        "speed": speed,
        "grinds": grinds,
        "artifacts": artifact,
        "sets": sets,
        "slots": slots,
        "farming": farming,
        "upgrade_targets": upgrades,
        "recommendations": recommendations,
        "core_set_quality": [(row["set_name"], int(round(row["quality_score"]))) for row in sorted(core_rows, key=lambda item: item["quality_score"], reverse=True)[:12]],
    }
