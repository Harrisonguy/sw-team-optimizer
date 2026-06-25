from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from desktop.db import queries
from desktop.db.importer import import_account
from desktop.db.schema import create_tables, get_connection
from src.core.account.account_model import Account, Monster, Rune
from src.core.account.swex_importer import import_swex_account


class ImportPipelineTests(unittest.TestCase):
    def test_sample_swex_imports_into_sqlite(self) -> None:
        sample = Path("uuboram-17666244.json")
        self.assertTrue(sample.exists(), "sample SWEX JSON is required for this regression test")

        account = import_swex_account(sample)
        self.assertGreater(len(account.monsters), 0)
        self.assertGreater(len(account.equipped_runes) + len(account.inventory_runes), 0)
        self.assertGreater(len(account.equipped_artifacts) + len(account.inventory_artifacts), 0)

        with TemporaryDirectory() as td:
            db_path = Path(td) / "optimizer.db"
            import_account(account, db_path)
            conn = get_connection(db_path)
            try:
                create_tables(conn)
                info = queries.get_account_info(conn)
                active_id = queries.get_active_profile_id(conn)
                structured_artifacts = conn.execute(
                    "SELECT COUNT(*) FROM artifacts"
                    " WHERE sec_effect_data IS NOT NULL"
                    " AND sec_effect_data != '[]'"
                ).fetchone()[0]
                analytics = queries.get_analytics(conn)
            finally:
                conn.close()

        self.assertEqual(account.player_name, info["player_name"])
        self.assertEqual(len(account.monsters), info["monster_count"])
        self.assertEqual(
            len(account.equipped_runes) + len(account.inventory_runes),
            info["rune_count"],
        )
        self.assertEqual(
            len(account.equipped_artifacts) + len(account.inventory_artifacts),
            info["artifact_count"],
        )
        self.assertEqual(1, info["profile_count"])
        self.assertEqual(info["profile_id"], active_id)
        self.assertEqual(100, info["wizard_level"])
        self.assertEqual(20, info["wizard_skill_count"])
        self.assertEqual(30, info["guild_level"])
        expected_structured = sum(
            bool(artifact.sec_effects)
            for artifact in account.equipped_artifacts + account.inventory_artifacts
        )
        self.assertEqual(expected_structured, structured_artifacts)
        self.assertIn("progression", analytics)
        self.assertGreater(analytics["progression"]["account_score"], 0)
        self.assertTrue(analytics["progression"]["recommendations"])

    def test_profile_registry_survives_account_switches(self) -> None:
        first = Account(player_name="Alpha", wizard_id=101)
        second = Account(player_name="Beta", wizard_id=202)

        with TemporaryDirectory() as td:
            db_path = Path(td) / "profiles.db"
            first_id = import_account(first, db_path)
            second_id = import_account(second, db_path)
            first_again_id = import_account(first, db_path)

            conn = get_connection(db_path)
            try:
                profiles = queries.list_account_profiles(conn)
                info = queries.get_account_info(conn)
                active_id = queries.get_active_profile_id(conn)
            finally:
                conn.close()

        self.assertEqual(first_id, first_again_id)
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(2, len(profiles))
        self.assertEqual(first_id, active_id)
        self.assertEqual("Alpha", info["player_name"])
        self.assertEqual(2, info["profile_count"])
        self.assertEqual(1, sum(1 for profile in profiles if profile["is_active"]))

    def test_profile_switch_restores_isolated_inventory_and_preferences(self) -> None:
        first = Account(
            player_name="Alpha",
            wizard_id=101,
            wizard_level=50,
            wizard_skill_list={"1": {"skill_id": 1, "level": 10}},
            guild_level=12,
            monsters=[
                Monster(
                    unit_id=7, display_name="Alpha Unit", base_name="Alpha Unit",
                    skills=[4], skill_levels={4: 3},
                )
            ],
            inventory_runes=[
                Rune(
                    rune_id=9,
                    set_id=1,
                    slot_no=1,
                    raw_class=6,
                    rank=5,
                    pri_eff=[1, 100],
                )
            ],
        )
        second = Account(
            player_name="Beta",
            wizard_id=202,
            wizard_level=100,
            wizard_skill_list={"1": {"skill_id": 1, "level": 20}},
            guild_level=30,
            monsters=[
                Monster(
                    unit_id=7, display_name="Beta Unit", base_name="Beta Unit",
                    skills=[176], skill_levels={176: 4},
                )
            ],
            inventory_runes=[
                Rune(
                    rune_id=9,
                    set_id=3,
                    slot_no=1,
                    raw_class=6,
                    rank=5,
                    pri_eff=[1, 200],
                )
            ],
        )

        with TemporaryDirectory() as td:
            db_path = Path(td) / "isolated-profiles.db"
            first_id = import_account(first, db_path)

            conn = get_connection(db_path)
            try:
                queries.set_rune_locked(conn, 9, True)
                queries.save_team_config(conn, "Alpha Team", "custom", "{}")
                queries.save_pvp_config(
                    conn, "Alpha Arena", "arena_offense", "{}"
                )
            finally:
                conn.close()

            second_id = import_account(second, db_path)
            conn = get_connection(db_path)
            try:
                beta_info = queries.get_account_info(conn)
                beta_progression = queries.get_account_progression(conn)
                beta_monster = queries.get_monsters(conn)[0]
                beta_rune = queries.get_runes(conn)[0]
                beta_locked = queries.is_rune_locked(conn, 9)
                beta_teams = queries.list_team_configs(conn)
                beta_pvp = queries.list_pvp_configs(conn)

                alpha_info = queries.activate_account_profile(conn, first_id)
                alpha_progression = queries.get_account_progression(conn)
                alpha_monster = queries.get_monsters(conn)[0]
                alpha_rune = queries.get_runes(conn)[0]
                alpha_locked = queries.is_rune_locked(conn, 9)
                alpha_teams = queries.list_team_configs(conn)
                alpha_pvp = queries.list_pvp_configs(conn)

                queries.activate_account_profile(conn, second_id)
                beta_again = queries.get_monsters(conn)[0]
                stored_counts = {
                    row["profile_id"]: row["cnt"]
                    for row in conn.execute(
                        "SELECT profile_id, COUNT(*) AS cnt"
                        " FROM profile_monsters GROUP BY profile_id"
                    ).fetchall()
                }
            finally:
                conn.close()

        self.assertEqual("Beta", beta_info["player_name"])
        self.assertEqual(100, beta_progression["wizard_level"])
        self.assertEqual(30, beta_progression["guild_level"])
        self.assertEqual("Beta Unit", beta_monster["display_name"])
        self.assertEqual([176], beta_monster["skills"])
        self.assertEqual({176: 4}, beta_monster["skill_levels"])
        self.assertEqual("Swift", beta_rune["set_name"])
        self.assertFalse(beta_locked)
        self.assertEqual([], beta_teams)
        self.assertEqual([], beta_pvp)

        self.assertEqual("Alpha", alpha_info["player_name"])
        self.assertEqual(50, alpha_progression["wizard_level"])
        self.assertEqual(12, alpha_progression["guild_level"])
        self.assertEqual("Alpha Unit", alpha_monster["display_name"])
        self.assertEqual([4], alpha_monster["skills"])
        self.assertEqual({4: 3}, alpha_monster["skill_levels"])
        self.assertEqual("Energy", alpha_rune["set_name"])
        self.assertTrue(alpha_locked)
        self.assertEqual("Alpha Team", alpha_teams[0]["name"])
        self.assertEqual("Alpha Arena", alpha_pvp[0]["name"])
        self.assertEqual("arena_offense", alpha_pvp[0]["mode"])

        self.assertEqual("Beta Unit", beta_again["display_name"])
        self.assertEqual({first_id: 1, second_id: 1}, stored_counts)

    def test_legacy_account_is_registered_during_schema_migration(self) -> None:
        with TemporaryDirectory() as td:
            db_path = Path(td) / "legacy.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "CREATE TABLE account ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " player_name TEXT NOT NULL, wizard_id INTEGER, imported_at TEXT NOT NULL)"
            )
            conn.execute(
                "INSERT INTO account (player_name, wizard_id, imported_at) VALUES (?, ?, ?)",
                ("Legacy", 303, "2026-01-01T00:00:00+00:00"),
            )
            conn.commit()
            conn.close()

            conn = get_connection(db_path)
            try:
                create_tables(conn)
                profiles = queries.list_account_profiles(conn)
                info = queries.get_account_info(conn)
            finally:
                conn.close()

        self.assertEqual(1, len(profiles))
        self.assertEqual("Legacy", profiles[0]["profile_name"])
        self.assertTrue(profiles[0]["is_active"])
        self.assertEqual(profiles[0]["profile_id"], info["profile_id"])


if __name__ == "__main__":
    unittest.main()
