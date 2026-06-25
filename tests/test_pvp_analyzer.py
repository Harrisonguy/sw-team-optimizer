from __future__ import annotations

import unittest

from optimizer.pvp_analyzer import (
    PvpUnit,
    analyze_pvp_team,
    combat_speed,
    leader_speed_bonus,
    rank_pvp_candidates,
    speed_contest_probability,
)


def unit(
    unit_id: int,
    name: str,
    speed: int,
    capabilities: tuple[str, ...] = (),
    *,
    element: str = "Water",
    offense: int = 3500,
    hp: int = 30000,
    defense: int = 1000,
    leader_amount: int = 0,
    leader_area: str = "General",
) -> PvpUnit:
    return PvpUnit(
        unit_id=unit_id,
        name=name,
        element=element,
        archetype="Attack" if "damage" in capabilities else "Support",
        base_speed=100,
        stats={
            "spd": speed,
            "atk": offense,
            "cr": 100,
            "cd": 200,
            "hp": hp,
            "def_": defense,
        },
        capabilities=frozenset(capabilities),
        leader_attribute="Attack Speed" if leader_amount else "",
        leader_amount=leader_amount,
        leader_area=leader_area,
    )


class PvpAnalyzerTests(unittest.TestCase):
    def test_speed_leader_applies_only_to_matching_content(self) -> None:
        leader = unit(1, "Lead", 200, ("speed_lead",), leader_amount=24, leader_area="Arena")
        ally = unit(2, "Ally", 200)

        self.assertEqual(24, leader_speed_bonus(leader, ally, "arena_offense"))
        self.assertEqual(224, combat_speed(ally, leader, "arena_offense"))
        self.assertEqual(0, leader_speed_bonus(leader, ally, "siege_offense"))
        self.assertEqual(200, combat_speed(ally, leader, "siege_offense"))

    def test_speed_contest_probability_respects_enemy_range_and_lead(self) -> None:
        losing = speed_contest_probability(290, 290, 310, enemy_lead_pct=24, enemy_base_speed=100)
        winning = speed_contest_probability(340, 290, 310, enemy_lead_pct=24, enemy_base_speed=100)

        self.assertEqual(0.0, losing.win_probability)
        self.assertEqual(100.0, winning.win_probability)
        self.assertEqual((314, 334), (winning.enemy_min_speed, winning.enemy_max_speed))

    def test_atb_boost_detects_safe_and_unsafe_followups(self) -> None:
        opener = unit(1, "Opener", 300, ("strip", "setup"))
        safe_follow = unit(2, "Safe", 230, ("damage",))
        slow_follow = unit(3, "Slow", 200, ("damage",))

        safe = analyze_pvp_team(
            [opener, safe_follow], "arena_offense", atb_boost_pct=25,
            enemy_min_speed=250, enemy_max_speed=260,
        )
        unsafe = analyze_pvp_team(
            [opener, slow_follow], "arena_offense", atb_boost_pct=25,
            enemy_min_speed=250, enemy_max_speed=260,
        )

        self.assertTrue(safe["cut_safe"])
        self.assertFalse(unsafe["cut_safe"])
        self.assertTrue(any("cut" in risk for risk in unsafe["risks"]))

    def test_planned_order_reports_actual_combat_order(self) -> None:
        slow = unit(1, "Slow", 200)
        fast = unit(2, "Fast", 300)

        report = analyze_pvp_team([slow, fast], "siege_offense")

        self.assertFalse(report["order_ok"])
        self.assertEqual(["Fast", "Slow"], report["actual_order"])

    def test_candidate_ranking_prioritizes_missing_coverage(self) -> None:
        selected = [unit(1, "Damage", 250, ("damage",))]
        report = analyze_pvp_team(selected, "rta")
        roster = selected + [
            unit(2, "Fast Only", 310, ("damage",)),
            unit(3, "Coverage", 260, ("strip", "control", "protection")),
        ]

        candidates = rank_pvp_candidates(roster, selected, report, "rta")

        self.assertEqual("Coverage", candidates[0]["name"])
        self.assertEqual({"strip", "control", "protection"}, set(candidates[0]["fills"]))

    def test_defense_analysis_flags_element_concentration(self) -> None:
        team = [
            unit(index, "Water " + str(index), 250 - index, ("damage",), element="Water")
            for index in range(1, 5)
        ]

        report = analyze_pvp_team(team, "arena_defense")

        self.assertTrue(any("element concentration" in risk for risk in report["risks"]))
        self.assertIn("control", report["missing_capabilities"])
        self.assertLess(report["score"], 80)


if __name__ == "__main__":
    unittest.main()
