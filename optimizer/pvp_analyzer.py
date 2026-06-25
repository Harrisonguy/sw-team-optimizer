"""PvP speed, draft coverage, and defense-risk analysis."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from optimizer.stat_utils import effective_hp, effective_offense
from src.core.skills.skill_library import load_skill_map, monster_skill_profiles


MODE_TEAM_SIZE = {
    "arena_offense": 4,
    "arena_defense": 4,
    "siege_offense": 3,
    "siege_defense": 3,
    "guild_offense": 3,
    "guild_defense": 3,
    "rta": 5,
}

MODE_LABELS = {
    "arena_offense": "Arena Offense",
    "arena_defense": "Arena Defense",
    "siege_offense": "Siege Offense",
    "siege_defense": "Siege Defense",
    "guild_offense": "Guild War Offense",
    "guild_defense": "Guild War Defense",
    "rta": "World Arena Draft",
}

_REQUIRED_CAPABILITIES = {
    "arena_offense": ("speed_lead", "strip", "setup", "damage"),
    "arena_defense": ("speed_lead", "control", "protection", "damage", "durable"),
    "siege_offense": ("setup", "sustain", "protection", "damage"),
    "siege_defense": ("control", "sustain", "damage", "durable"),
    "guild_offense": ("setup", "sustain", "protection", "damage"),
    "guild_defense": ("control", "sustain", "damage", "durable"),
    "rta": ("speed_lead", "strip", "control", "protection", "sustain", "damage"),
}

_STRIP_EFFECTS = frozenset({37, 42, 68, 91})
_CONTROL_EFFECTS = frozenset({21, 24, 25, 27, 28, 33, 75, 127, 143})
_SUSTAIN_EFFECTS = frozenset({35, 36, 45})
_PROTECTION_EFFECTS = frozenset({9, 12, 34, 50})
_SETUP_EFFECTS = frozenset({1, 5, 17, 20, 151})


@dataclass(frozen=True)
class PvpUnit:
    unit_id: int
    name: str
    element: str = ""
    archetype: str = ""
    base_speed: float = 0.0
    stats: dict[str, float] = field(default_factory=dict)
    capabilities: frozenset[str] = field(default_factory=frozenset)
    leader_attribute: str = ""
    leader_amount: float = 0.0
    leader_area: str = ""
    leader_element: str = ""

    @property
    def speed(self) -> float:
        return float(self.stats.get("spd") or self.stats.get("speed") or 0.0)

    @property
    def offense(self) -> float:
        return float(effective_offense(self.stats))

    @property
    def durability(self) -> float:
        return float(effective_hp(self.stats))


@dataclass(frozen=True)
class SpeedContestResult:
    own_speed: int
    enemy_min_speed: int
    enemy_max_speed: int
    win_probability: float
    margin_to_midpoint: int


def _mode_group(mode: str) -> str:
    if mode.startswith("arena") or mode == "rta":
        return "arena"
    if mode.startswith("siege") or mode.startswith("guild"):
        return "guild"
    return "general"


def leader_speed_bonus(leader: PvpUnit | None, ally: PvpUnit, mode: str) -> float:
    if leader is None or "speed" not in leader.leader_attribute.lower():
        return 0.0
    area = leader.leader_area.lower()
    group = _mode_group(mode)
    if area not in {"", "general", "all"} and group not in area:
        if "element" not in area:
            return 0.0
    restriction = leader.leader_element.strip().lower()
    if restriction and restriction not in {"all", ally.element.strip().lower()}:
        return 0.0
    return float(leader.leader_amount or 0.0)


def combat_speed(unit: PvpUnit, leader: PvpUnit | None, mode: str) -> int:
    bonus = leader_speed_bonus(leader, unit, mode)
    return int(round(unit.speed + unit.base_speed * bonus / 100.0))


def speed_contest_probability(
    own_speed: int,
    enemy_min_speed: int,
    enemy_max_speed: int,
    enemy_lead_pct: float = 0.0,
    enemy_base_speed: float = 100.0,
) -> SpeedContestResult:
    low = int(round(min(enemy_min_speed, enemy_max_speed) + enemy_base_speed * enemy_lead_pct / 100.0))
    high = int(round(max(enemy_min_speed, enemy_max_speed) + enemy_base_speed * enemy_lead_pct / 100.0))
    if high <= low:
        probability = 100.0 if own_speed > high else 0.0
    elif own_speed <= low:
        probability = 0.0
    elif own_speed > high:
        probability = 100.0
    else:
        probability = 100.0 * (own_speed - low) / (high - low)
    midpoint = int(round((low + high) / 2.0))
    return SpeedContestResult(
        own_speed=int(own_speed),
        enemy_min_speed=low,
        enemy_max_speed=high,
        win_probability=round(max(0.0, min(100.0, probability)), 1),
        margin_to_midpoint=int(own_speed - midpoint),
    )


def capabilities_from_monster(monster: dict[str, Any], stats: dict[str, float]) -> frozenset[str]:
    skill_ids = [int(value) for value in (monster.get("skills") or [])]
    levels = {int(key): int(value) for key, value in (monster.get("skill_levels") or {}).items()}
    skills = load_skill_map()
    effect_ids = {
        effect_id
        for skill_id in skill_ids
        for effect_id in (skills.get(skill_id).effects if skills.get(skill_id) else [])
    }
    profiles = monster_skill_profiles(skill_ids, levels)
    capabilities: set[str] = set()
    if effect_ids & _STRIP_EFFECTS:
        capabilities.add("strip")
    if effect_ids & _CONTROL_EFFECTS:
        capabilities.add("control")
    if effect_ids & _SUSTAIN_EFFECTS:
        capabilities.add("sustain")
    if effect_ids & _PROTECTION_EFFECTS:
        capabilities.add("protection")
    if effect_ids & _SETUP_EFFECTS:
        capabilities.add("setup")
    if any(profile.provides_defense_break or profile.provides_atk_buff for profile in profiles):
        capabilities.add("setup")
    archetype = str(monster.get("archetype") or "").lower()
    if archetype == "attack" or effective_offense(stats) >= 4500:
        capabilities.add("damage")
    if effective_hp(stats) >= 90000:
        capabilities.add("durable")
    leader_attribute = str(monster.get("leader_skill_attribute") or "")
    leader_area = str(monster.get("leader_skill_area") or "")
    if "speed" in leader_attribute.lower() and leader_area.lower() != "dungeon":
        capabilities.add("speed_lead")
    return frozenset(capabilities)


def pvp_unit_from_data(monster: dict[str, Any], stats: dict[str, float]) -> PvpUnit:
    return PvpUnit(
        unit_id=int(monster.get("unit_id") or 0),
        name=str(monster.get("display_name") or monster.get("base_name") or "Unknown"),
        element=str(monster.get("element") or ""),
        archetype=str(monster.get("archetype") or ""),
        base_speed=float(monster.get("base_speed") or 0.0),
        stats={key: float(value or 0.0) for key, value in stats.items()},
        capabilities=capabilities_from_monster(monster, stats),
        leader_attribute=str(monster.get("leader_skill_attribute") or ""),
        leader_amount=float(monster.get("leader_skill_amount") or 0.0),
        leader_area=str(monster.get("leader_skill_area") or ""),
        leader_element=str(monster.get("leader_skill_element") or ""),
    )


def analyze_pvp_team(
    units: Iterable[PvpUnit],
    mode: str,
    leader_unit_id: int | None = None,
    enemy_min_speed: int = 280,
    enemy_max_speed: int = 330,
    enemy_lead_pct: float = 0.0,
    enemy_base_speed: float = 100.0,
    atb_boost_pct: float = 0.0,
) -> dict[str, Any]:
    selected = list(units)
    leader = next((unit for unit in selected if unit.unit_id == leader_unit_id), None)
    speeds = {unit.unit_id: combat_speed(unit, leader, mode) for unit in selected}
    actual_order = sorted(selected, key=lambda unit: (-speeds[unit.unit_id], unit.name))
    intended_ids = [unit.unit_id for unit in selected]
    actual_ids = [unit.unit_id for unit in actual_order]
    order_ok = intended_ids == actual_ids

    opener_speed = speeds[actual_order[0].unit_id] if actual_order else 0
    turn_rows = []
    cut_safe = bool(actual_order)
    for position, unit in enumerate(selected, 1):
        speed = speeds[unit.unit_id]
        atb = 100.0 if position == 1 else (
            100.0 * speed / opener_speed + max(0.0, atb_boost_pct)
            if opener_speed else 0.0
        )
        ready = position == 1 or atb >= 100.0
        if position > 1 and atb_boost_pct > 0 and not ready:
            cut_safe = False
        turn_rows.append({
            "position": position,
            "unit_id": unit.unit_id,
            "name": unit.name,
            "speed": speed,
            "atb_after_opener": round(atb, 1),
            "ready_after_boost": ready,
            "actual_position": actual_ids.index(unit.unit_id) + 1 if unit.unit_id in actual_ids else 0,
        })
    if atb_boost_pct <= 0:
        cut_safe = order_ok

    own_fastest = opener_speed
    contest = speed_contest_probability(
        own_fastest,
        enemy_min_speed,
        enemy_max_speed,
        enemy_lead_pct,
        enemy_base_speed,
    )
    team_capabilities = set().union(*(unit.capabilities for unit in selected)) if selected else set()
    if leader and leader_speed_bonus(leader, leader, mode) > 0:
        team_capabilities.add("speed_lead")
    required = _REQUIRED_CAPABILITIES.get(mode, _REQUIRED_CAPABILITIES["rta"])
    missing = [capability for capability in required if capability not in team_capabilities]
    coverage_score = 100.0 * (len(required) - len(missing)) / max(1, len(required))
    average_durability = sum(unit.durability for unit in selected) / len(selected) if selected else 0.0
    average_offense = sum(unit.offense for unit in selected) / len(selected) if selected else 0.0
    size_target = MODE_TEAM_SIZE.get(mode, 5)
    size_score = min(100.0, len(selected) / size_target * 100.0)
    score = (
        coverage_score * 0.38
        + contest.win_probability * 0.22
        + (100.0 if order_ok else 35.0) * 0.12
        + (100.0 if cut_safe else 40.0) * 0.10
        + min(100.0, average_durability / 1300.0) * 0.10
        + min(100.0, average_offense / 70.0) * 0.05
        + size_score * 0.03
    )

    risks = []
    if len(selected) < size_target:
        risks.append("Select %d more monster%s for this mode." % (size_target - len(selected), "" if size_target - len(selected) == 1 else "s"))
    if not order_ok:
        actual_names = " -> ".join(unit.name for unit in actual_order)
        risks.append("Planned order does not match combat speed; actual order is " + actual_names + ".")
    if atb_boost_pct > 0 and not cut_safe:
        unsafe = [row["name"] for row in turn_rows[1:] if not row["ready_after_boost"]]
        risks.append("Enemy turns can cut before " + ", ".join(unsafe) + " after the boost.")
    if contest.win_probability < 50:
        risks.append("The opener is unfavored against the selected enemy speed range.")
    for capability in missing:
        risks.append("Missing " + capability.replace("_", " ") + " coverage.")
    elements = [unit.element for unit in selected if unit.element]
    if elements and max(elements.count(element) for element in set(elements)) >= 3:
        risks.append("Heavy element concentration makes the team easier to counter-pick.")

    recommendations = []
    if contest.win_probability < 75:
        needed = contest.enemy_max_speed + 1 - own_fastest
        recommendations.append("Add %d combat SPD to the opener or choose a stronger speed lead." % max(1, needed))
    if not order_ok:
        recommendations.append("Reorder the draft by combat speed or retune the selected turn sequence.")
    if atb_boost_pct > 0 and not cut_safe and opener_speed:
        minimum = int(opener_speed * max(0.0, 1.0 - atb_boost_pct / 100.0) + 0.999)
        recommendations.append("Tune every follow-up to at least %d combat SPD for this boost." % minimum)
    if missing:
        recommendations.append("Add coverage for: " + ", ".join(item.replace("_", " ") for item in missing) + ".")

    return {
        "mode": mode,
        "mode_label": MODE_LABELS.get(mode, mode),
        "team_size": len(selected),
        "target_team_size": size_target,
        "leader_unit_id": leader.unit_id if leader else None,
        "leader_name": leader.name if leader else "None",
        "speed_contest": contest,
        "turn_order": turn_rows,
        "actual_order": [unit.name for unit in actual_order],
        "order_ok": order_ok,
        "cut_safe": cut_safe,
        "capabilities": sorted(team_capabilities),
        "missing_capabilities": missing,
        "coverage_score": round(coverage_score, 1),
        "average_durability": round(average_durability),
        "average_offense": round(average_offense),
        "score": round(max(0.0, min(100.0, score)), 1),
        "risks": risks,
        "recommendations": recommendations,
    }


def rank_pvp_candidates(
    roster: Iterable[PvpUnit],
    selected: Iterable[PvpUnit],
    report: dict[str, Any],
    mode: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    chosen_ids = {unit.unit_id for unit in selected}
    missing = set(report.get("missing_capabilities") or [])
    candidates = []
    for unit in roster:
        if unit.unit_id in chosen_ids:
            continue
        fills = sorted(missing & set(unit.capabilities))
        valid_lead = "speed_lead" in unit.capabilities and leader_speed_bonus(unit, unit, mode) > 0
        if "speed_lead" in missing and valid_lead and "speed_lead" not in fills:
            fills.append("speed_lead")
        build_score = min(100.0, unit.offense / 70.0) * 0.45 + min(100.0, unit.durability / 1300.0) * 0.35 + min(100.0, unit.speed / 3.2) * 0.20
        score = len(fills) * 35.0 + build_score
        candidates.append({
            "unit_id": unit.unit_id,
            "name": unit.name,
            "element": unit.element,
            "speed": round(unit.speed),
            "offense": round(unit.offense),
            "durability": round(unit.durability),
            "fills": fills,
            "capabilities": sorted(unit.capabilities),
            "score": round(score, 1),
        })
    return sorted(candidates, key=lambda row: (-row["score"], -row["speed"], row["name"]))[:max(1, int(limit))]
