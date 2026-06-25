from __future__ import annotations

import unittest

import optimizer.team_optimizer as team_optimizer
from optimizer.rune_optimizer import BuildResult, SlotResult
from optimizer.team_optimizer import MonsterRequest, optimize_team


def _build(
    rune_id: int,
    score: float,
    avg_desr: float = 50.0,
    final_stats: dict | None = None,
) -> BuildResult:
    return BuildResult(
        slots=[SlotResult(slot_no=1, rune={"rune_id": rune_id}, required_set=None, is_upgrade=True)],
        avg_desr=avg_desr,
        set_summary={},
        stat_totals={},
        meets_targets=True,
        final_stats=final_stats or {"spd": 100 + rune_id},
        target_report={},
        sets_complete=True,
        weak_slot=None,
        score=score,
        assumed_max=True,
    )


class GlobalTeamOptimizerTests(unittest.TestCase):
    def test_selects_best_team_instead_of_priority_greedy_leftovers(self) -> None:
        original_optimize = team_optimizer.optimize
        a_greedy = _build(1, 100.0)
        a_global = _build(2, 80.0)
        b_conflict = _build(1, 1000.0, avg_desr=90.0)
        b_fallback = _build(3, 10.0)

        def fake_optimize(**kwargs):
            uid = kwargs["monster_info"]["unit_id"]
            if uid == 101:
                return [a_greedy, a_global]
            if uid == 202:
                return [b_conflict, b_fallback]
            return []

        team_optimizer.optimize = fake_optimize
        try:
            requests = [
                MonsterRequest(
                    unit_id=101,
                    display_name="Priority Monster",
                    priority=1,
                    set_reqs=[],
                    main_stat_constraints={},
                    target_stats={},
                    current_build={},
                    monster_info={"unit_id": 101},
                ),
                MonsterRequest(
                    unit_id=202,
                    display_name="Team Carry",
                    priority=2,
                    set_reqs=[],
                    main_stat_constraints={},
                    target_stats={},
                    current_build={},
                    monster_info={"unit_id": 202},
                ),
            ]

            result = optimize_team(rune_pool=[{"rune_id": 1}, {"rune_id": 2}, {"rune_id": 3}], requests=requests)
        finally:
            team_optimizer.optimize = original_optimize

        chosen = {monster.unit_id: monster.build for monster in result.monsters}
        self.assertEqual({2}, set(team_optimizer._build_rune_ids(chosen[101])))
        self.assertEqual({1}, set(team_optimizer._build_rune_ids(chosen[202])))

        all_ids = []
        for build in chosen.values():
            all_ids.extend(team_optimizer._build_rune_ids(build))
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_each_team_state_uses_only_remaining_runes(self) -> None:
        original_optimize = team_optimizer.optimize
        seen_pools: dict[int, list[set[int]]] = {101: [], 202: [], 303: []}

        def fake_optimize(**kwargs):
            uid = kwargs["monster_info"]["unit_id"]
            available = {
                int(rune["rune_id"])
                for rune in kwargs["rune_pool"]
            }
            seen_pools[uid].append(available)
            return [
                _build(rune_id, score=100.0 - rune_id)
                for rune_id in sorted(available)[:2]
            ]

        team_optimizer.optimize = fake_optimize
        try:
            requests = [
                MonsterRequest(
                    unit_id=unit_id,
                    display_name="Monster %s" % unit_id,
                    priority=priority,
                    set_reqs=[],
                    main_stat_constraints={},
                    target_stats={},
                    current_build={},
                    monster_info={"unit_id": unit_id},
                )
                for priority, unit_id in enumerate((101, 202, 303), 1)
            ]
            result = optimize_team(
                rune_pool=[
                    {"rune_id": 1},
                    {"rune_id": 2},
                    {"rune_id": 3},
                    {"rune_id": 4},
                ],
                requests=requests,
            )
        finally:
            team_optimizer.optimize = original_optimize

        used = [
            rune_id
            for monster in result.monsters
            for rune_id in team_optimizer._build_rune_ids(monster.build)
        ]
        self.assertEqual(3, len(used))
        self.assertEqual(3, len(set(used)))
        self.assertTrue(
            all(len(pool) == 3 for pool in seen_pools[202]),
            seen_pools[202],
        )
        self.assertTrue(
            all(len(pool) == 2 for pool in seen_pools[303]),
            seen_pools[303],
        )

    def test_dungeon_score_can_choose_lower_individual_score(self) -> None:
        original_optimize = team_optimizer.optimize
        pretty_but_weak = _build(
            10,
            score=1000,
            final_stats={
                "hp": 25000,
                "atk": 300,
                "def_": 1200,
                "spd": 180,
                "cr": 100,
                "cd": 200,
                "acc": 0,
            },
        )
        dungeon_build = _build(
            11,
            score=0,
            final_stats={
                "hp": 25000,
                "atk": 4000,
                "def_": 1200,
                "spd": 180,
                "cr": 100,
                "cd": 200,
                "acc": 0,
            },
        )

        def fake_optimize(**kwargs):
            return [pretty_but_weak, dungeon_build]

        team_optimizer.optimize = fake_optimize
        try:
            request = MonsterRequest(
                unit_id=101,
                display_name="Wave Clear",
                priority=1,
                set_reqs=[],
                main_stat_constraints={},
                target_stats={},
                current_build={},
                monster_info={"unit_id": 101},
                combat_role="attacker",
                skill_atk_multiplier=5.0,
                skill_aoe=True,
            )
            waves = {
                1: [
                    {
                        "monster_name": "Wave",
                        "hp": 60000,
                        "atk": 500,
                        "def": 500,
                        "spd": 150,
                        "res": 30,
                    }
                ],
                2: [
                    {
                        "monster_name": "Boss",
                        "hp": 100000,
                        "atk": 800,
                        "def": 800,
                        "spd": 140,
                        "res": 30,
                    }
                ],
            }
            result = optimize_team(
                rune_pool=[{"rune_id": 10}, {"rune_id": 11}],
                requests=[request],
                dungeon_waves=waves,
            )
        finally:
            team_optimizer.optimize = original_optimize

        self.assertEqual(
            {11},
            set(team_optimizer._build_rune_ids(result.monsters[0].build)),
        )
        self.assertIsNotNone(result.dungeon_score)
        self.assertIsNotNone(result.estimated_success)


if __name__ == "__main__":
    unittest.main()
