from __future__ import annotations

import unittest

from optimizer.damage_calculator import (
    DamageContext,
    SkillScaling,
    UnitStats,
    analyze_waves,
    calculate_damage,
    can_kill_wave,
    defense_mitigation,
)


class DamageCalculatorTests(unittest.TestCase):
    def test_defense_mitigation_decreases_as_defense_increases(self) -> None:
        self.assertGreater(defense_mitigation(500), defense_mitigation(1500))

    def test_damage_modifiers_increase_damage(self) -> None:
        attacker = UnitStats(atk=3000, crit_damage=200)
        defender = UnitStats(hp=20000, defense=1000)
        skill = SkillScaling(atk=4.0)

        base = calculate_damage(attacker, defender, skill)
        boosted = calculate_damage(
            attacker,
            defender,
            skill,
            DamageContext(
                atk_buff=True,
                defense_break=True,
                brand=True,
                skillup_bonus_pct=20,
                artifact_bonus_pct=15,
            ),
        )

        self.assertGreater(boosted, base)

    def test_additional_artifact_damage_uses_attacker_stats(self) -> None:
        attacker = UnitStats(
            hp=20000,
            atk=3000,
            defense=1000,
            speed=200,
            crit_rate=100,
            crit_damage=200,
        )
        defender = UnitStats(hp=50000, defense=1000)
        skill = SkillScaling(atk=4.0)

        base = calculate_damage(attacker, defender, skill)
        with_artifacts = calculate_damage(
            attacker,
            defender,
            skill,
            DamageContext(
                additional_damage_by_hp_pct=0.5,
                additional_damage_by_atk_pct=5,
                additional_damage_by_def_pct=5,
                additional_damage_by_spd_pct=20,
            ),
        )

        self.assertGreater(with_artifacts, base)

    def test_can_kill_wave_checks_every_enemy(self) -> None:
        attacker = UnitStats(atk=4000, crit_damage=220)
        skill = SkillScaling(atk=5.0)
        easy_wave = [UnitStats(hp=1000, defense=100), UnitStats(hp=1200, defense=100)]
        hard_wave = [UnitStats(hp=1000, defense=100), UnitStats(hp=100000, defense=2000)]

        self.assertTrue(can_kill_wave(attacker, easy_wave, skill))
        self.assertFalse(can_kill_wave(attacker, hard_wave, skill))

    def test_target_crit_damage_reduction_lowers_critical_damage(self) -> None:
        attacker = UnitStats(atk=3000, crit_rate=100, crit_damage=200)
        defender = UnitStats(hp=20000, defense=800)
        skill = SkillScaling(atk=4.0)

        normal = calculate_damage(attacker, defender, skill)
        reduced = calculate_damage(
            attacker,
            defender,
            skill,
            DamageContext(target_crit_damage_reduction_pct=50),
        )

        self.assertLess(reduced, normal)

    def test_analyze_waves_reports_each_enemy_and_clear_status(self) -> None:
        attacker = UnitStats(atk=4000, crit_rate=100, crit_damage=200)
        waves = {
            1: [
                {"monster_name": "Small", "hp": 1000, "def": 100},
                {"monster_name": "Large", "hp": 100000, "def": 2000},
            ],
            2: [
                {
                    "monster_name": "Reduced",
                    "hp": 1000,
                    "def": 100,
                    "cdmg_reduction": 50,
                }
            ],
        }

        result = analyze_waves(attacker, waves, SkillScaling(atk=4.0))

        self.assertEqual(2, len(result[1].enemies))
        self.assertEqual(1, result[1].defeated_count)
        self.assertFalse(result[1].clears_wave)
        self.assertTrue(result[2].clears_wave)
        self.assertLess(result[2].enemies[0].damage, result[1].enemies[0].damage)


    def test_target_hp_scaling_uses_each_enemy_max_hp(self) -> None:
        attacker = UnitStats(crit_damage=0)
        skill = SkillScaling(target_hp=0.10)
        context = DamageContext(force_crit=False)

        small = calculate_damage(attacker, UnitStats(hp=10000, defense=0), skill, context)
        large = calculate_damage(attacker, UnitStats(hp=50000, defense=0), skill, context)

        self.assertGreater(large, small)
        self.assertEqual(5, large // small)

    def test_ignore_defense_bypasses_mitigation(self) -> None:
        attacker = UnitStats(atk=1000, crit_damage=0)
        defender = UnitStats(hp=10000, defense=3000)
        skill = SkillScaling(atk=1.0)

        mitigated = calculate_damage(
            attacker, defender, skill, DamageContext(force_crit=False)
        )
        ignored = calculate_damage(
            attacker,
            defender,
            skill,
            DamageContext(force_crit=False, ignore_defense=True),
        )

        self.assertEqual(1000, ignored)
        self.assertGreater(ignored, mitigated)


if __name__ == "__main__":
    unittest.main()
