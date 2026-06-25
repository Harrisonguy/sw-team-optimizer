from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from src.core.account.swex_importer import import_swex_account


class ImportValidationTests(unittest.TestCase):
    def import_payload(self, payload):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "account.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return import_swex_account(path)

    def test_non_object_root_has_a_clear_validation_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "root must be an object"):
            self.import_payload([])

    def test_unrelated_json_is_not_accepted_as_an_account(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not appear"):
            self.import_payload({"hello": "world"})

    def test_malformed_collection_field_names_the_bad_field(self) -> None:
        with self.assertRaisesRegex(ValueError, "unit_list"):
            self.import_payload({"wizard_info": {}, "unit_list": {}})

    def test_minimal_recognized_export_remains_supported(self) -> None:
        account = self.import_payload(
            {"wizard_info": {"wizard_name": "Minimal", "wizard_id": 7}}
        )
        self.assertEqual("Minimal", account.player_name)
        self.assertEqual(7, account.wizard_id)
        self.assertEqual([], account.monsters)


if __name__ == "__main__":
    unittest.main()

