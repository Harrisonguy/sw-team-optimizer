from __future__ import annotations

import unittest

from src.core.skills.skill_library import (
    skill_combat_profile,
    skill_data_from_id,
    skillup_damage_bonus_percent,
)


class SkillLibraryTests(unittest.TestCase):
    def profile(self, skill_id: int, level: int | None = None):
        skill = skill_data_from_id(skill_id)
        self.assertIsNotNone(skill)
        return skill_combat_profile(skill, level or skill.max_level)

    def test_linear_attack_formula_and_partial_skillups(self) -> None:
        skill = skill_data_from_id(4)
        self.assertIsNotNone(skill)
        profile = skill_combat_profile(skill, 3)

        self.assertTrue(profile.supported)
        self.assertEqual(3.6, profile.atk)
        self.assertEqual(1, profile.hits)
        self.assertEqual(10.0, skillup_damage_bonus_percent(skill, 3))

    def test_mixed_attack_defense_and_target_hp_formulas(self) -> None:
        mixed = self.profile(176)
        target_hp = self.profile(50)

        self.assertEqual((2.4, 3.0), (mixed.atk, mixed.defense))
        self.assertEqual(4.1, target_hp.atk)
        self.assertEqual(0.1, target_hp.target_hp)

    def test_multihit_and_combat_effect_flags_are_imported(self) -> None:
        defense_break = self.profile(24)
        attack_buff = self.profile(372)

        self.assertEqual(4, defense_break.hits)
        self.assertTrue(defense_break.provides_defense_break)
        self.assertEqual(3, defense_break.cooldown)
        self.assertEqual(40.0, defense_break.effect_chance)
        self.assertTrue(attack_buff.provides_atk_buff)

    def test_fixed_damage_ignores_defense_and_critical_hits(self) -> None:
        profile = self.profile(704)

        self.assertTrue(profile.supported)
        self.assertTrue(profile.fixed_damage)
        self.assertTrue(profile.ignores_defense)
        self.assertEqual(0.3, profile.hp)

    def test_nonlinear_formula_is_not_silently_approximated(self) -> None:
        profile = self.profile(116)

        self.assertFalse(profile.supported)
        self.assertIn("combat state", profile.reason)


if __name__ == "__main__":
    unittest.main()
