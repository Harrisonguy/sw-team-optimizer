from __future__ import annotations

import random
import sqlite3
import unittest

from desktop.db import queries
from desktop.db.schema import create_tables
from optimizer.damage_calculator import DamageContext, SkillScaling
from optimizer.dungeon_data import load_dungeon_profile_waves
from optimizer.dungeon_simulator import (
    DungeonCombatant,
    DungeonTeamEvaluation,
    DungeonWaveEvaluation,
    _simulate_wave_once,
    evaluate_dungeon_team,
    simulate_dungeon_runs,
)


class DungeonSimulatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.waves = {
            1: [
                {"monster_name": "Wave A", "hp": 18000, "atk": 1200, "def": 800, "spd": 150, "res": 40},
                {"monster_name": "Wave B", "hp": 18000, "atk": 1200, "def": 800, "spd": 150, "res": 40},
            ],
            2: [
                {"monster_name": "Boss", "hp": 150000, "atk": 2500, "def": 1200, "spd": 140, "res": 50}
            ],
        }

    @staticmethod
    def member(
        unit_id: int,
        atk: int,
        hp: int = 25000,
        defense: int = 1200,
        speed: int = 180,
        aoe: bool = True,
        defense_break: bool = False,
    ) -> DungeonCombatant:
        return DungeonCombatant(
            unit_id=unit_id,
            display_name="Unit %d" % unit_id,
            stats={
                "hp": hp,
                "atk": atk,
                "def_": defense,
                "spd": speed,
                "cr": 100,
                "cd": 200,
                "acc": 85 if defense_break else 0,
            },
            scaling=SkillScaling(atk=4.0),
            context=DamageContext(force_crit=False),
            role="attacker",
            aoe=aoe,
            provides_defense_break=defense_break,
        )

    def test_bundled_profiles_have_wave_data(self) -> None:
        for key in (
            "gb_abyss_hard",
            "db_abyss_hard",
            "nb_abyss_hard",
            "sf_abyss_hard",
            "pc_abyss_hard",
            "abyss_hard",
        ):
            waves = load_dungeon_profile_waves(key)
            self.assertGreaterEqual(len(waves), 4, key)
            self.assertTrue(all(waves.values()), key)

    def test_queries_fall_back_to_bundled_dungeon_data(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        create_tables(conn)

        names = queries.get_dungeon_names(conn)
        waves = queries.get_dungeon_waves(
            conn,
            "Giant's Keep - Abyss Hard",
        )
        summary = queries.get_dungeon_summary(
            conn,
            "Giant's Keep - Abyss Hard",
        )

        self.assertIn("Giant's Keep - Abyss Hard", names)
        self.assertEqual(4, len(waves))
        self.assertGreater(summary["max_hp"], 0)
        self.assertTrue(queries.has_dungeon_data(conn))
        conn.close()

    def test_stronger_team_scores_higher(self) -> None:
        weak = [self.member(1, atk=1000, hp=10000, defense=500, speed=120)]
        strong = [
            self.member(1, atk=4000, defense_break=True),
            self.member(2, atk=3500),
            self.member(3, atk=3000),
        ]

        weak_result = evaluate_dungeon_team(weak, self.waves)
        strong_result = evaluate_dungeon_team(strong, self.waves)

        self.assertGreater(strong_result.readiness_score, weak_result.readiness_score)
        self.assertGreater(
            strong_result.success_probability,
            weak_result.success_probability,
        )

    def test_aoe_and_defense_break_improve_wave_clear(self) -> None:
        single_target = [
            self.member(1, atk=2500, aoe=False),
            self.member(2, atk=2500, aoe=False),
        ]
        aoe_break = [
            self.member(1, atk=2500, aoe=True, defense_break=True),
            self.member(2, atk=2500, aoe=True),
        ]

        single_result = evaluate_dungeon_team(single_target, self.waves)
        aoe_result = evaluate_dungeon_team(aoe_break, self.waves)

        self.assertLess(
            aoe_result.waves[0].rounds_to_clear,
            single_result.waves[0].rounds_to_clear,
        )
        self.assertGreater(
            aoe_result.waves[0].control_score,
            single_result.waves[0].control_score,
        )

    def test_conditional_battle_model_rewards_debuffs_and_control(self) -> None:
        plain = [
            self.member(1, atk=600, speed=170),
            self.member(2, atk=600, speed=170),
        ]
        conditional = [
            DungeonCombatant(
                **{
                    **plain[0].__dict__,
                    "provides_defense_break": True,
                    "provides_control": True,
                    "effect_chance": 100.0,
                }
            ),
            DungeonCombatant(
                **{
                    **plain[1].__dict__,
                    "provides_brand": True,
                    "effect_chance": 100.0,
                }
            ),
        ]
        evaluation = evaluate_dungeon_team(conditional, self.waves)
        plain_rate = simulate_dungeon_runs(
            evaluation, trials=300, seed=7, members=plain, waves=self.waves
        )
        conditional_rate = simulate_dungeon_runs(
            evaluation, trials=300, seed=7, members=conditional, waves=self.waves
        )
        self.assertGreater(conditional_rate, plain_rate)

    def test_skill_cooldown_changes_turn_by_turn_damage(self) -> None:
        fast_skill = self.member(1, atk=2800, hp=30000, defense=1400)
        slow_skill = DungeonCombatant(
            **{**fast_skill.__dict__, "skill_cooldown": 4}
        )
        evaluation = evaluate_dungeon_team([fast_skill], self.waves)
        frequent_rate = simulate_dungeon_runs(
            evaluation, trials=250, seed=11, members=[fast_skill], waves=self.waves
        )
        cooldown_rate = simulate_dungeon_runs(
            evaluation, trials=250, seed=11, members=[slow_skill], waves=self.waves
        )
        self.assertGreater(frequent_rate, cooldown_rate)

    def test_health_and_cooldowns_persist_between_waves(self) -> None:
        fragile = DungeonCombatant(
            unit_id=1,
            display_name="Fragile attacker",
            stats={
                "hp": 3000,
                "atk": 800,
                "def_": 500,
                "spd": 150,
                "cr": 0,
                "cd": 50,
                "acc": 0,
            },
            scaling=SkillScaling(atk=2.0),
            context=DamageContext(force_crit=False),
            role="attacker",
            skill_cooldown=2,
        )
        enemy = {
            "monster_name": "Attrition enemy",
            "hp": 2000,
            "atk": 1000,
            "def": 500,
            "spd": 100,
            "res": 0,
        }
        rng = random.Random(1)
        first_clear, carried_state, buff_rounds = _simulate_wave_once(
            [fragile], [enemy], 8, rng
        )
        second_clear, _, _ = _simulate_wave_once(
            [fragile], [enemy], 8, rng, carried_state, buff_rounds
        )
        fresh_clear, _, _ = _simulate_wave_once(
            [fragile], [enemy], 8, random.Random(1)
        )

        self.assertTrue(first_clear)
        self.assertFalse(second_clear)
        self.assertTrue(fresh_clear)
        self.assertLess(carried_state[0]["hp"], carried_state[0]["max_hp"])

    def test_fractional_trial_count_uses_executed_trial_denominator(self) -> None:
        perfect_wave = DungeonWaveEvaluation(
            wave_number=1,
            is_boss_wave=False,
            rounds_to_clear=1.0,
            turn_budget=1,
            damage_score=100.0,
            survivability_score=100.0,
            speed_score=100.0,
            control_score=100.0,
            readiness_score=100.0,
            success_probability=100.0,
            limiting_enemy="None",
        )
        evaluation = DungeonTeamEvaluation(
            readiness_score=100.0,
            success_probability=100.0,
            waves=(perfect_wave,),
            bottlenecks=(),
        )

        self.assertEqual(100.0, simulate_dungeon_runs(evaluation, trials=2.9))

    def test_seeded_battle_simulation_is_reproducible(self) -> None:
        members = [
            self.member(1, 3500),
            self.member(2, 3000, defense_break=True),
        ]
        result = evaluate_dungeon_team(members, self.waves)
        first = simulate_dungeon_runs(
            result, trials=200, seed=42, members=members, waves=self.waves
        )
        second = simulate_dungeon_runs(
            result, trials=200, seed=42, members=members, waves=self.waves
        )
        self.assertEqual(first, second)

    def test_seeded_simulation_is_reproducible(self) -> None:
        result = evaluate_dungeon_team(
            [self.member(1, 3500), self.member(2, 3000, defense_break=True)],
            self.waves,
        )
        first = simulate_dungeon_runs(result, trials=500, seed=42)
        second = simulate_dungeon_runs(result, trials=500, seed=42)

        self.assertEqual(first, second)
        self.assertGreaterEqual(first, 0)
        self.assertLessEqual(first, 100)


if __name__ == "__main__":
    unittest.main()
