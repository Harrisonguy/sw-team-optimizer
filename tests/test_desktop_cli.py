from __future__ import annotations

import unittest

import run_desktop


class DesktopCliTests(unittest.TestCase):
    def test_option_value_reads_the_following_argument(self) -> None:
        self.assertEqual("5", run_desktop._option_value(["app", "--page", "5"], "--page"))
        self.assertIsNone(run_desktop._option_value(["app"], "--page"))

    def test_positive_integer_options_reject_zero_and_invalid_values(self) -> None:
        with self.assertRaises(ValueError):
            run_desktop._int_option(["app", "--width", "0"], "--width", 1400)
        with self.assertRaises(ValueError):
            run_desktop._int_option(["app", "--width", "wide"], "--width", 1400)

    def test_missing_screenshot_path_fails_before_loading_qt(self) -> None:
        self.assertEqual(2, run_desktop.main(["app", "--screenshot"]))

    def test_invalid_headless_dimensions_fail_before_loading_qt(self) -> None:
        self.assertEqual(2, run_desktop.main(["app", "--smoke-test", "--width", "bad"]))
        self.assertEqual(2, run_desktop.main(["app", "--smoke-test", "--page", "0"]))


if __name__ == "__main__":
    unittest.main()
