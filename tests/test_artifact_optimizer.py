from __future__ import annotations

import json
import unittest

from optimizer.artifact_optimizer import (
    ArtifactProfile,
    ArtifactRequest,
    aggregate_artifact_bonuses,
    artifact_matches_monster,
    optimize_team_artifacts,
    rank_artifact_pairs,
)


def artifact(
    artifact_id: int,
    slot_label: str,
    requirement: str,
    main_id: int,
    main_value: float,
    secondary: list[tuple[int, float]] | None = None,
    occupied_id: int = 0,
) -> dict:
    secondary = secondary or []
    return {
        "artifact_id": artifact_id,
        "slot_label": slot_label,
        "requirement_label": requirement,
        "pri_effect_id": main_id,
        "pri_effect_value": main_value,
        "pri_effect": f"Main {main_id}: {main_value:g}",
        "sec_effect_data": json.dumps(
            [{"effect_id": effect_id, "value": value} for effect_id, value in secondary]
        ),
        "sec_effects": json.dumps(
            [f"Effect {effect_id}: {value:g}" for effect_id, value in secondary]
        ),
        "occupied_id": occupied_id,
    }


class ArtifactOptimizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.monster = {
            "unit_id": 1,
            "display_name": "Test",
            "element": "Water",
            "archetype": "Attack",
        }
        self.stats = {
            "hp": 12000,
            "atk": 2500,
            "def_": 800,
            "spd": 200,
            "cr": 100,
            "cd": 200,
        }

    def test_artifact_eligibility_uses_element_and_archetype(self) -> None:
        self.assertTrue(
            artifact_matches_monster(
                artifact(1, "Attribute", "Water", 100, 1000),
                self.monster,
            )
        )
        self.assertFalse(
            artifact_matches_monster(
                artifact(2, "Attribute", "Fire", 100, 1000),
                self.monster,
            )
        )
        self.assertTrue(
            artifact_matches_monster(
                artifact(3, "Type", "Attack", 101, 100),
                self.monster,
            )
        )
        self.assertFalse(
            artifact_matches_monster(
                artifact(4, "Type", "Support", 101, 100),
                self.monster,
            )
        )

    def test_aggregate_uses_skill_and_element_context(self) -> None:
        rows = [
            artifact(
                1,
                "Attribute",
                "Water",
                101,
                100,
                [(301, 20), (400, 15), (401, 50), (219, 5)],
            )
        ]
        bonuses = aggregate_artifact_bonuses(
            rows,
            ArtifactProfile(
                target_element="Water",
                skill_number=1,
                single_target=False,
            ),
        )

        self.assertEqual(100, bonuses["atk"])
        self.assertEqual(20, bonuses["element_bonus_pct"])
        self.assertEqual(15, bonuses["cd_bonus"])
        self.assertEqual(5, bonuses["addl_atk_pct"])

    def test_pair_optimizer_selects_context_relevant_artifacts(self) -> None:
        rows = [
            artifact(1, "Attribute", "Water", 101, 100, [(301, 20)]),
            artifact(2, "Attribute", "Water", 101, 150, [(300, 50)]),
            artifact(3, "Type", "Attack", 101, 50, [(400, 25)]),
            artifact(4, "Type", "Attack", 101, 80, [(401, 40)]),
        ]

        result = rank_artifact_pairs(
            rows,
            self.monster,
            self.stats,
            ArtifactProfile(target_element="Water", skill_number=1),
            top_n=1,
        )[0]

        self.assertEqual({1, 3}, set(result.artifact_ids))
        self.assertGreater(result.damage_gain, 0)

    def test_team_optimizer_never_reuses_an_artifact(self) -> None:
        rows = [
            artifact(1, "Attribute", "Water", 101, 500),
            artifact(2, "Attribute", "Water", 101, 350),
            artifact(3, "Attribute", "Water", 101, 200),
            artifact(10, "Type", "Attack", 101, 300),
            artifact(11, "Type", "Attack", 101, 200),
            artifact(12, "Type", "Attack", 101, 100),
        ]
        requests = [
            ArtifactRequest(1, "One", dict(self.monster), dict(self.stats)),
            ArtifactRequest(
                2,
                "Two",
                {**self.monster, "unit_id": 2},
                dict(self.stats),
            ),
        ]

        result = optimize_team_artifacts(rows, requests, top_n_per_monster=8)
        used = [
            artifact_id
            for member in result.members
            for artifact_id in (member.pair.artifact_ids if member.pair else ())
        ]

        self.assertEqual(4, len(used))
        self.assertEqual(4, len(set(used)))
        self.assertGreater(result.total_score, 0)


if __name__ == "__main__":
    unittest.main()
