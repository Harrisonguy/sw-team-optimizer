from __future__ import annotations

import json
import unittest

from optimizer.artifact_analyzer import analyze_artifact_inventory


def artifact(
    artifact_id: int,
    value: float,
    *,
    level: int = 15,
    natural_rank: int = 5,
    roll_count: int = 0,
    occupied_id: int = 0,
    locked: int = 0,
    effect_id: int = 218,
) -> dict:
    effect_ids = [effect_id] if level < 12 else [effect_id, 219, 220, 221]
    effects = [] if value < 0 else [
        {"effect_id": current_id, "value": value, "roll_count": roll_count}
        for current_id in effect_ids
    ]
    return {
        "artifact_id": artifact_id,
        "slot_label": "Attribute",
        "requirement_label": "Water",
        "natural_rank": natural_rank,
        "rank": 5 if level >= 12 else natural_rank,
        "level": level,
        "sec_effect_data": json.dumps(effects),
        "occupied_id": occupied_id,
        "locked": locked,
    }


class ArtifactAnalyzerTests(unittest.TestCase):
    def test_higher_rolls_receive_higher_efficiency_and_value(self) -> None:
        report = analyze_artifact_inventory([
            artifact(1, 2),
            artifact(2, 6),
            artifact(3, 12),
        ])
        by_id = {row["artifact_id"]: row for row in report["artifacts"]}

        self.assertGreater(by_id[3]["artifact_efficiency"], by_id[1]["artifact_efficiency"])
        self.assertGreater(by_id[3]["artifact_value"], by_id[1]["artifact_value"])
        self.assertEqual("Offense", by_id[3]["artifact_profile"])

    def test_unrevealed_artifacts_are_never_sell_recommendations(self) -> None:
        rows = [artifact(index, 5 + index) for index in range(1, 6)]
        rows.append(artifact(10, -1, level=0, natural_rank=3))

        report = analyze_artifact_inventory(rows)
        target = next(row for row in report["artifacts"] if row["artifact_id"] == 10)

        self.assertEqual("Review", target["artifact_action"])
        self.assertGreater(target["artifact_remaining_rolls"], 0)

    def test_promising_legend_artifact_is_marked_for_upgrade(self) -> None:
        rows = [artifact(index, value) for index, value in enumerate((2, 4, 6, 8, 10), 1)]
        rows.append(artifact(20, 10, level=0, natural_rank=5))

        report = analyze_artifact_inventory(rows)
        target = next(row for row in report["artifacts"] if row["artifact_id"] == 20)

        self.assertEqual("Upgrade", target["artifact_action"])
        self.assertGreater(target["artifact_potential"], target["artifact_value"])

    def test_equipped_and_locked_artifacts_are_protected(self) -> None:
        rows = [artifact(index, 20 + index) for index in range(1, 5)]
        rows.extend([
            artifact(10, 1, occupied_id=123),
            artifact(11, 1, locked=1),
        ])

        report = analyze_artifact_inventory(rows)
        by_id = {row["artifact_id"]: row for row in report["artifacts"]}

        self.assertEqual("Keep", by_id[10]["artifact_action"])
        self.assertEqual("Keep", by_id[11]["artifact_action"])

    def test_unknown_requirement_is_held_for_review(self) -> None:
        rows = [artifact(index, 20 + index) for index in range(1, 5)]
        unknown = artifact(10, 1)
        unknown["requirement_label"] = "Unknown Attribute 98"
        rows.append(unknown)

        report = analyze_artifact_inventory(rows)
        target = next(row for row in report["artifacts"] if row["artifact_id"] == 10)

        self.assertEqual("Review", target["artifact_action"])
        self.assertIn("unsupported", target["artifact_reason"])

    def test_dominated_completed_artifact_can_be_flagged_for_sell(self) -> None:
        rows = [artifact(1, 1)]
        rows.extend(artifact(index, value) for index, value in enumerate((10, 15, 20, 25), 2))

        report = analyze_artifact_inventory(rows)
        weak = next(row for row in report["artifacts"] if row["artifact_id"] == 1)

        self.assertEqual("Sell", weak["artifact_action"])
        self.assertGreaterEqual(weak["artifact_better_count"], 3)
        self.assertEqual(sum(report["counts"].values()), len(rows))


if __name__ == "__main__":
    unittest.main()
