from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import os
import unittest

from src.core.artifacts.artifact_constants import ARTIFACT_EFFECTS_FILE
from src.core.dungeons.dungeon_library import DUNGEONS_FILE, LEVELS_FILE
from src.core.dungeons.dungeon_override_library import OVERRIDES_FILE
from src.core.monsters.monster_library import MONSTER_DATA_FILE
from src.core.resources import DATA_DIR, resource_path
from src.core.skills.skill_library import SKILLS_FILE, SKILL_EFFECTS_FILE


class ResourcePathTests(unittest.TestCase):
    def test_all_shipped_data_paths_are_absolute_and_present(self) -> None:
        paths = [
            ARTIFACT_EFFECTS_FILE,
            DUNGEONS_FILE,
            LEVELS_FILE,
            OVERRIDES_FILE,
            MONSTER_DATA_FILE,
            SKILLS_FILE,
            SKILL_EFFECTS_FILE,
        ]
        self.assertTrue(DATA_DIR.is_absolute())
        for path in paths:
            self.assertTrue(path.is_absolute(), path)
            self.assertTrue(path.is_file(), path)

    def test_resources_do_not_depend_on_current_working_directory(self) -> None:
        original = Path.cwd()
        with TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                self.assertTrue(resource_path("data/skills.json").is_file())
                self.assertTrue(resource_path("data/monsters.json").is_file())
            finally:
                os.chdir(original)


if __name__ == "__main__":
    unittest.main()
