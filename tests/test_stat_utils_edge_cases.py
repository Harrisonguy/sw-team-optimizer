from __future__ import annotations

import unittest

from optimizer.rune_optimizer import BuildResult, SlotResult
from optimizer.stat_utils import (
    compute_final_stats,
    merge_bonuses,
    projected_main_value,
)


BASE_MONSTER = {
    "max_lvl_hp": 10000,
    "max_lvl_attack": 1000,
    "max_lvl_defense": 500,
    "base_speed": 101,
    "crit_rate": 15,
    "crit_damage": 50,
    "resistance": 15,
    "accuracy": 0,
}


def build_with_sets(set_summary: dict[str, int]) -> BuildResult:
    slots = [
        SlotResult(
            slot_no=slot,
            rune={
                "rune_id": slot,
                "slot_no": slot,
                "set_name": next(iter(set_summary), "Broken"),
                "main_stat_id": 0,
                "main_stat_value": 0,
            },
            required_set=None,
            is_upgrade=False,
        )
        for slot in range(1, 7)
    ]
    return BuildResult(slots, 0.0, set_summary, {}, True)


class StatUtilsEdgeCaseTests(unittest.TestCase):
    def test_multiple_copies_of_a_two_piece_set_stack(self) -> None:
        result = compute_final_stats(
            BASE_MONSTER,
            build_with_sets({"Energy": 6}),
        )
        self.assertEqual(14500, result["hp"])

    def test_incomplete_set_does_not_grant_a_bonus(self) -> None:
        result = compute_final_stats(
            BASE_MONSTER,
            build_with_sets({"Swift": 3, "Blade": 1}),
        )
        self.assertEqual(BASE_MONSTER["base_speed"], result["spd"])
        self.assertEqual(BASE_MONSTER["crit_rate"], result["cr"])

    def test_swift_rounds_up_and_multiple_blade_sets_stack(self) -> None:
        result = compute_final_stats(
            BASE_MONSTER,
            build_with_sets({"Swift": 4, "Blade": 4}),
        )
        self.assertEqual(127, result["spd"])
        self.assertEqual(39, result["cr"])

    def test_projected_main_stat_handles_normal_ancient_and_unknown(self) -> None:
        normal = {
            "main_stat_id": 8,
            "main_stat_value": 7,
            "upgrade_curr": 3,
            "stars": 6,
            "raw_class": 6,
        }
        ancient = {**normal, "raw_class": 11}
        unknown = {**normal, "main_stat_id": 999, "main_stat_value": 12}
        self.assertEqual(42.0, projected_main_value(normal))
        self.assertEqual(48.0, projected_main_value(ancient))
        self.assertEqual(12.0, projected_main_value(unknown))

    def test_malformed_substats_are_ignored_without_losing_main_stats(self) -> None:
        build = build_with_sets({})
        rune = dict(build.slots[0].rune or {})
        rune.update({"main_stat_id": 3, "main_stat_value": 160, "sec_eff": "not-json"})
        slots = list(build.slots)
        slots[0] = slots[0]._replace(rune=rune)
        result = compute_final_stats(BASE_MONSTER, build._replace(slots=slots))
        self.assertEqual(1160, result["atk"])

    def test_bonus_merge_skips_missing_sources_and_sums_values(self) -> None:
        self.assertEqual(
            {"atk_pct": 18.0, "spd_pct": 15.0},
            merge_bonuses(None, {"atk_pct": 10}, {"atk_pct": 8, "spd_pct": 15}),
        )


if __name__ == "__main__":
    unittest.main()

