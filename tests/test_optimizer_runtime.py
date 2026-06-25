from __future__ import annotations

import unittest

from optimizer.artifact_optimizer import ArtifactRequest, optimize_team_artifacts
from optimizer.dungeon_simulator import DungeonTeamEvaluation, DungeonWaveEvaluation, simulate_dungeon_runs
from optimizer.rune_optimizer import (
    OptimizationCancelled,
    _slot_assignments,
    optimize,
)
from optimizer.team_optimizer import MonsterRequest, optimize_team


def rune(rune_id: int, slot: int, atk_percent: int = 0) -> dict:
    return {
        "rune_id": rune_id,
        "slot_no": slot,
        "set_name": "Will",
        "stars": 6,
        "main_stat_id": 4 if atk_percent else ({1: 3, 3: 5, 5: 1}.get(slot, 2)),
        "main_stat_value": atk_percent or 10,
        "prefix_stat_name": "",
        "prefix_stat_value": 0,
        "sec_eff": "[]",
        "desirability": 50,
    }


class OptimizerRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pool = [rune(slot, slot, 63 if slot == 6 else 0) for slot in range(1, 7)]

    def test_single_optimizer_honors_immediate_cancellation(self) -> None:
        with self.assertRaises(OptimizationCancelled):
            optimize(self.pool, [], {}, cancel_check=lambda: True)

    def test_team_optimizer_honors_immediate_cancellation(self) -> None:
        request = MonsterRequest(1, "Test", 1, [], {}, {}, {})
        with self.assertRaises(OptimizationCancelled):
            optimize_team(self.pool, [request], cancel_check=lambda: True)

    def test_progress_callback_reaches_completion(self) -> None:
        events = []
        result = optimize(
            self.pool,
            ["Will"],
            {},
            progress_callback=lambda done, total, message: events.append((done, total, message)),
        )

        self.assertTrue(result)
        self.assertTrue(events)
        self.assertEqual(events[-1][0], events[-1][1])
        self.assertIn("Searching", events[-1][2])

    def test_set_assignment_cache_is_reused(self) -> None:
        _slot_assignments.cache_clear()
        optimize(self.pool, ["Will"], {})
        first = _slot_assignments.cache_info()
        optimize(self.pool, ["Will"], {})
        second = _slot_assignments.cache_info()

        self.assertEqual(1, first.misses)
        self.assertGreater(second.hits, first.hits)

    def test_effective_offense_cache_is_context_specific(self) -> None:
        low_reference = optimize(
            self.pool, [], {}, scoring_mode="effective_offense", ref_atk=1000,
            ref_cr=85, ref_cd=200, top_n=1,
        )[0]
        high_reference = optimize(
            self.pool, [], {}, scoring_mode="effective_offense", ref_atk=4000,
            ref_cr=85, ref_cd=200, top_n=1,
        )[0]

        self.assertGreater(high_reference.score, low_reference.score)
        cache = self.pool[-1].get("_eo_score_cache", {})
        self.assertEqual(2, len(cache))

    def test_bonus_target_mode_reports_green_speed_bonus(self) -> None:
        pool = [rune(slot, slot, 0) for slot in range(1, 7)]
        for item in pool:
            if item["slot_no"] == 2:
                item["main_stat_id"] = 8
                item["main_stat_name"] = "SPD"
                item["main_stat_value"] = 42
        result = optimize(
            pool, [], {}, target_stats={"SPD": 150},
            monster_info={"base_speed": 100}, target_mode="total", top_n=1,
        )[0]
        self.assertFalse(result.meets_targets)
        self.assertEqual(142, result.target_report["SPD"]["actual"])

        bonus_result = optimize(
            pool, [], {}, target_stats={"SPD": 40},
            monster_info={"base_speed": 100}, target_mode="bonus", top_n=1,
        )[0]
        self.assertTrue(bonus_result.meets_targets)
        self.assertEqual(42, bonus_result.target_report["SPD"]["actual"])
        self.assertEqual("bonus", bonus_result.target_report["SPD"]["mode"])

    def test_flat_hp_target_mode_can_use_total_or_green_bonus(self) -> None:
        pool = [rune(slot, slot, 0) for slot in range(1, 7)]
        for item in pool:
            if item["slot_no"] == 6:
                item["main_stat_id"] = 1
                item["main_stat_name"] = "HP%"
                item["main_stat_value"] = 63
        monster = {"max_lvl_hp": 10000}
        total = optimize(pool, [], {}, target_stats={"HP": 16000}, monster_info=monster, target_mode="total", top_n=1)[0]
        bonus = optimize(pool, [], {}, target_stats={"HP": 6000}, monster_info=monster, target_mode="bonus", top_n=1)[0]
        self.assertTrue(total.meets_targets)
        self.assertTrue(bonus.meets_targets)
        self.assertGreaterEqual(total.target_report["HP"]["actual"], 16000)
        self.assertGreaterEqual(bonus.target_report["HP"]["actual"], 6000)

    def test_artifact_team_optimizer_honors_cancellation(self) -> None:
        request = ArtifactRequest(
            unit_id=1,
            display_name="Test",
            monster_info={"unit_id": 1, "element": "Water", "archetype": "Attack"},
            stats={"hp": 10000, "atk": 2000, "def_": 700, "spd": 200, "cr": 100, "cd": 150},
        )
        with self.assertRaises(OptimizationCancelled):
            optimize_team_artifacts([], [request], cancel_check=lambda: True)

    def test_simulation_honors_cancellation(self) -> None:
        wave = DungeonWaveEvaluation(
            wave_number=1,
            is_boss_wave=False,
            rounds_to_clear=1,
            turn_budget=4,
            damage_score=100,
            survivability_score=100,
            speed_score=100,
            control_score=100,
            readiness_score=100,
            success_probability=100,
            limiting_enemy="None",
        )
        evaluation = DungeonTeamEvaluation(100, 100, (wave,), ())
        with self.assertRaises(OptimizationCancelled):
            simulate_dungeon_runs(evaluation, trials=1000, cancel_check=lambda: True)


if __name__ == "__main__":
    unittest.main()
