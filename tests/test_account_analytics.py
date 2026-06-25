from __future__ import annotations

import json
import unittest

from optimizer.account_analytics import analyze_account


def rune(
    rune_id: int,
    set_name: str,
    slot: int,
    desirability: float = 60,
    efficiency: float = 70,
    speed: int = 0,
    grind: int = 0,
    occupied_id: int = 0,
) -> dict:
    subs = [[8, speed - grind, 0, grind]] if speed else [[2, 8, 0, grind]]
    return {
        "rune_id": rune_id,
        "set_name": set_name,
        "slot_no": slot,
        "stars": 6,
        "desirability": desirability,
        "efficiency": efficiency,
        "sec_eff": json.dumps(subs),
        "occupied_id": occupied_id,
    }


class AccountAnalyticsTests(unittest.TestCase):
    def test_report_measures_set_slot_speed_and_grind_depth(self) -> None:
        runes = []
        rune_id = 1
        for set_name in ("Swift", "Violent", "Will"):
            for slot in range(1, 7):
                runes.append(rune(rune_id, set_name, slot, speed=10 + slot, grind=2))
                rune_id += 1

        report = analyze_account(runes)
        swift = next(row for row in report["sets"] if row["set_name"] == "Swift")

        self.assertEqual(6, swift["usable_count"])
        self.assertEqual(18, report["speed"]["runes_with_speed"])
        self.assertEqual(100.0, report["grinds"]["coverage_pct"])
        self.assertEqual(6, len(report["slots"]))
        self.assertGreater(report["account_score"], 0)
        self.assertIn(report["account_tier"], {"Developing", "Established", "Strong", "Elite"})

    def test_farming_focus_follows_the_largest_core_set_gap(self) -> None:
        runes = []
        rune_id = 1
        for set_name in ("Swift", "Despair", "Fatal", "Blade", "Will", "Rage", "Nemesis", "Vampire", "Fight", "Determination", "Enhance", "Accuracy"):
            for copy in range(4):
                for slot in range(1, 7):
                    runes.append(rune(rune_id, set_name, slot, desirability=70, speed=20))
                    rune_id += 1

        report = analyze_account(runes)

        self.assertEqual("Dragon's Lair", report["farming"][0]["dungeon"])
        self.assertEqual("Dragon's Lair", report["recommendations"][0]["title"].removeprefix("Farm "))
        self.assertIn("Violent", report["farming"][0]["targets"])

    def test_monster_upgrade_targets_missing_slots_then_low_quality(self) -> None:
        runes = [
            rune(i, "Energy", i, desirability=20, occupied_id=101)
            for i in range(1, 5)
        ]
        runes.extend(
            rune(10 + i, "Energy", i, desirability=10, occupied_id=202)
            for i in range(1, 7)
        )
        monsters = [
            {"unit_id": 101, "display_name": "Needs Slots", "stars": 6, "level": 40},
            {"unit_id": 202, "display_name": "Weak Build", "stars": 6, "level": 40},
        ]

        report = analyze_account(runes, monsters)

        self.assertEqual("Needs Slots", report["upgrade_targets"][0]["name"])
        self.assertEqual(2, report["upgrade_targets"][0]["missing_slots"])
        upgrade = next(item for item in report["recommendations"] if item["title"] == "Upgrade Needs Slots")
        self.assertIn("2 missing", upgrade["action"])

    def test_empty_account_returns_import_action(self) -> None:
        report = analyze_account([])

        self.assertEqual(0.0, report["account_score"])
        self.assertEqual("Import an account", report["recommendations"][0]["title"])


if __name__ == "__main__":
    unittest.main()
