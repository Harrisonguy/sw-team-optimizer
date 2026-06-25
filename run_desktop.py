"""
Entry point for the SW Team Optimizer desktop application.

Usage:
    python run_desktop.py
    python run_desktop.py --smoke-test
    python run_desktop.py --screenshot release/ui-overview.png --page 1
"""
from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _option_value(arguments: list[str], option: str) -> str | None:
    try:
        index = arguments.index(option)
    except ValueError:
        return None
    return arguments[index + 1] if index + 1 < len(arguments) else None


def _int_option(arguments: list[str], option: str, default: int) -> int:
    value = _option_value(arguments, option)
    if value is None:
        return default
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(option + " must be positive")
    return parsed


def main(argv: list[str] | None = None) -> int:
    arguments = list(argv or sys.argv)
    smoke_test = "--smoke-test" in arguments
    screenshot_requested = "--screenshot" in arguments
    screenshot_value = _option_value(arguments, "--screenshot")
    if screenshot_requested and screenshot_value is None:
        return 2
    headless = smoke_test or screenshot_requested
    width, height, page = 1400, 900, 0
    page_value = _option_value(arguments, "--page")
    if headless:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            width = _int_option(arguments, "--width", 1400)
            height = _int_option(arguments, "--height", 900)
            page = _int_option(arguments, "--page", 1) - 1
        except ValueError:
            return 2

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from desktop.app_info import APP_NAME, APP_VERSION, ORGANIZATION_NAME
    from desktop.ui.main_window import MainWindow
    from desktop.ui.theme import STYLESHEET, apply_dark_palette, load_bundled_fonts
    from src.core.resources import resource_path

    app = QApplication([arguments[0]])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(ORGANIZATION_NAME)

    icon = QIcon(str(resource_path("assets/app_icon.svg")))
    if not icon.isNull():
        app.setWindowIcon(icon)
    load_bundled_fonts(app)
    apply_dark_palette(app)
    app.setStyleSheet(STYLESHEET)

    window = MainWindow()
    if not headless:
        window.show()
        return int(app.exec())

    window.resize(width, height)
    if page_value is not None:
        if page < 0 or page >= window._stack.count():
            window.close()
            return 2
        window._switch_page(page)
    window.show()
    app.processEvents()

    saved = True
    if screenshot_value is not None:
        screenshot_path = Path(screenshot_value).expanduser().resolve()
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        saved = window.grab().save(str(screenshot_path))
    window.close()
    app.processEvents()
    return 0 if saved else 2


if __name__ == "__main__":
    raise SystemExit(main())
