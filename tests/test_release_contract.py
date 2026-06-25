from __future__ import annotations

from pathlib import Path
import tomllib
import unittest
import xml.etree.ElementTree as ET

from desktop.app_info import APP_NAME, APP_VERSION


ROOT = Path(__file__).resolve().parents[1]


class ReleaseContractTests(unittest.TestCase):
    def test_version_is_synchronized_across_release_manifests(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        installer = (ROOT / "packaging/windows/installer.iss").read_text(encoding="utf-8")
        version_info = (ROOT / "packaging/version_info.txt").read_text(encoding="utf-8")
        self.assertEqual(APP_VERSION, pyproject["project"]["version"])
        self.assertIn('#define MyAppVersion "%s"' % APP_VERSION, installer)
        self.assertIn("StringStruct('ProductVersion', '%s')" % APP_VERSION, version_info)

    def test_release_build_has_runtime_validation_gates(self) -> None:
        script = (ROOT / "build_release.ps1").read_text(encoding="utf-8")
        self.assertIn("-m unittest discover", script)
        self.assertIn("-m compileall", script)
        self.assertIn("--smoke-test", script)
        self.assertIn("--screenshot", script)
        self.assertIn("SWTeamOptimizer.exe", script)

    def test_bundle_spec_ships_data_and_visual_assets(self) -> None:
        spec = (ROOT / "packaging/sw_team_optimizer.spec").read_text(encoding="utf-8")
        self.assertIn('ROOT / "data"', spec)
        self.assertIn('ROOT / "assets"', spec)
        self.assertTrue((ROOT / "data/skills.json").is_file())
        icon = ROOT / "assets/app_icon.svg"
        self.assertTrue(icon.is_file())
        root = ET.parse(icon).getroot()
        self.assertTrue(root.tag.endswith("svg"))
        self.assertTrue((ROOT / "assets/app_icon.ico").is_file())
        font_dir = ROOT / "assets/fonts"
        self.assertTrue((font_dir / "Vera.ttf").is_file())
        self.assertTrue((font_dir / "VeraBd.ttf").is_file())
        self.assertTrue((font_dir / "bitstream-vera-license.txt").is_file())

    def test_public_identity_is_release_ready(self) -> None:
        self.assertEqual("SW Team Optimizer", APP_NAME)
        self.assertRegex(APP_VERSION, r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
