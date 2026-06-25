"""SW Team Optimizer - PySide6 main window."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QSettings
from PySide6.QtGui import QAction, QFont, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QFrame, QLabel, QPushButton, QStackedWidget,
    QFileDialog, QMessageBox, QProgressDialog, QApplication,
    QSizePolicy, QStatusBar, QComboBox,
)

from desktop.app_info import APP_NAME, APP_VERSION
from desktop.db.schema import DB_PATH, get_connection, create_tables
from desktop.db import queries
from desktop.ui.rune_table import RuneTableWidget
from desktop.ui.monster_roster import MonsterRosterWidget
from desktop.ui.artifact_table import ArtifactTableWidget
from desktop.ui.analytics import AnalyticsWidget
from desktop.ui.sell_analysis import SellAnalysisWidget
from desktop.ui.rune_optimizer import RuneOptimizerWidget
from desktop.ui.team_optimizer import TeamOptimizerWidget
from desktop.ui.dungeon_builder import DungeonBuilderWidget
from desktop.ui.pvp_planner import PvpPlannerWidget


class ImportWorker(QThread):
    progress = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, json_path: Path, db_path: Path) -> None:
        super().__init__()
        self.json_path = json_path
        self.db_path   = db_path

    def run(self) -> None:
        try:
            self.progress.emit("Parsing JSON...")
            from src.core.account.swex_importer import import_swex_account
            account = import_swex_account(self.json_path)
            n_runes = len(account.equipped_runes) + len(account.inventory_runes)
            self.progress.emit(
                "Parsed %d monsters, %d runes - writing to database..."
                % (len(account.monsters), n_runes)
            )
            from desktop.db.importer import import_account
            import_account(account, self.db_path)
            self.finished.emit(True, "")
        except Exception as exc:
            self.finished.emit(False, str(exc))


class NavButton(QPushButton):
    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, parent)
        self.setObjectName("navbtn")
        self.setCheckable(True)
        self.setChecked(False)
        self.setFlat(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(42)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1400, 900)
        self._settings = QSettings()
        self._worker: ImportWorker | None = None
        self._page_actions: list[QAction] = []
        self._db_path = DB_PATH
        self._conn    = get_connection(self._db_path)
        create_tables(self._conn)
        self._build_ui()
        self._restore_window_state()
        self._refresh_account_info()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_topbar())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_stack())
        root.addLayout(body)
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("Ready")
        self._build_menu()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        import_action = QAction("Import &SWEX JSON...", self)
        import_action.setShortcut(QKeySequence.Open)
        import_action.triggered.connect(self._on_import_clicked)
        file_menu.addAction(import_action)

        dungeon_action = QAction("Import &Dungeon Data...", self)
        dungeon_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        dungeon_action.triggered.connect(self._on_dungeon_import_clicked)
        file_menu.addAction(dungeon_action)
        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        view_menu = self.menuBar().addMenu("&View")
        page_names = [
            "Runes", "Monsters", "Artifacts", "Rune Optimizer",
            "Team Optimizer", "Dungeon Builder", "Sell Analysis",
            "Analytics", "PvP Planner",
        ]
        for index, name in enumerate(page_names):
            action = QAction(name, self)
            action.setCheckable(True)
            action.setShortcut(QKeySequence("Ctrl+" + str(index + 1)))
            action.triggered.connect(
                lambda checked=False, page=index: self._switch_page(page)
            )
            view_menu.addAction(action)
            self._page_actions.append(action)

        help_menu = self.menuBar().addMenu("&Help")
        about_action = QAction("&About " + APP_NAME, self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topbar")
        bar.setFixedHeight(56)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 0, 20, 0)

        logo = QLabel(APP_NAME)
        logo.setObjectName("title")
        logo.setFont(QFont("Segoe UI", 15, QFont.Bold))
        layout.addWidget(logo)
        layout.addStretch()

        self._player_lbl = QLabel("Account")
        self._player_lbl.setObjectName("subtitle")
        self._profile_combo = QComboBox()
        self._profile_combo.setMinimumWidth(150)
        self._profile_combo.setToolTip("Switch account profile")
        self._profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        self._rune_lbl     = QLabel("")
        self._rune_lbl.setObjectName("stat_badge")
        self._monster_lbl  = QLabel("")
        self._monster_lbl.setObjectName("stat_badge")
        self._artifact_lbl = QLabel("")
        self._artifact_lbl.setObjectName("stat_badge")

        layout.addWidget(self._player_lbl)
        layout.addSpacing(6)
        layout.addWidget(self._profile_combo)
        layout.addSpacing(12)
        for w in [self._rune_lbl, self._monster_lbl, self._artifact_lbl]:
            layout.addWidget(w)
            layout.addSpacing(6)
        layout.addSpacing(14)

        # Dungeon data import button (separate from account import)
        self._dungeon_import_btn = QPushButton("  Dungeon Data")
        self._dungeon_import_btn.setObjectName("navbtn")
        self._dungeon_import_btn.setFixedHeight(36)
        self._dungeon_import_btn.setToolTip(
            "Import dungeon_monsters_by_wave.json to populate Dungeon Builder"
        )
        self._dungeon_import_btn.clicked.connect(self._on_dungeon_import_clicked)
        layout.addWidget(self._dungeon_import_btn)
        layout.addSpacing(6)

        self._import_btn = QPushButton("  Import JSON")
        self._import_btn.setObjectName("import_btn")
        self._import_btn.setFixedHeight(36)
        self._import_btn.clicked.connect(self._on_import_clicked)
        layout.addWidget(self._import_btn)
        return bar

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(180)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(8, 16, 8, 16)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignTop)
        self._nav_btns: list[NavButton] = []

        def section_lbl(text):
            lbl = QLabel("  " + text)
            lbl.setObjectName("subtitle")
            lbl.setFont(QFont("Segoe UI", 10, QFont.Bold))
            lbl.setContentsMargins(8, 8, 0, 4)
            return lbl

        def add_pages(items):
            for label, idx in items:
                btn = NavButton(label)
                btn.clicked.connect(lambda checked, i=idx: self._switch_page(i))
                layout.addWidget(btn)
                self._nav_btns.append(btn)

        layout.addWidget(section_lbl("INVENTORY"))
        add_pages([("Runes", 0), ("Monsters", 1), ("Artifacts", 2)])
        layout.addWidget(section_lbl("OPTIMIZER"))
        add_pages([("Rune Optimizer", 3), ("Team Optimizer", 4), ("Dungeon Builder", 5)])
        layout.addWidget(section_lbl("ANALYSIS"))
        add_pages([("Sell Analysis", 6), ("Analytics", 7)])
        layout.addWidget(section_lbl("PVP"))
        add_pages([("PvP Planner", 8)])
        layout.addStretch()
        return sidebar

    def _build_stack(self) -> QStackedWidget:
        self._stack = QStackedWidget()
        self._rune_page      = RuneTableWidget(self._conn)
        self._monster_page   = MonsterRosterWidget(self._conn)
        self._artifact_page  = ArtifactTableWidget(self._conn)
        self._sell_page      = SellAnalysisWidget(self._conn)
        self._analytics_page = AnalyticsWidget(self._conn)

        # index 0-2: inventory
        self._stack.addWidget(self._rune_page)
        self._stack.addWidget(self._monster_page)
        self._stack.addWidget(self._artifact_page)

        # index 3-5: optimizer
        self._rune_opt_page = RuneOptimizerWidget(self._conn)
        self._stack.addWidget(self._rune_opt_page)

        self._team_opt_page = TeamOptimizerWidget(self._conn)
        self._stack.addWidget(self._team_opt_page)

        self._dungeon_page = DungeonBuilderWidget(self._conn)
        self._stack.addWidget(self._dungeon_page)

        # index 6-7: analysis
        self._stack.addWidget(self._sell_page)
        self._stack.addWidget(self._analytics_page)

        # index 8: PvP planning
        self._pvp_page = PvpPlannerWidget(self._conn)
        self._stack.addWidget(self._pvp_page)

        self._switch_page(0)
        return self._stack

    def _switch_page(self, index: int) -> None:
        if index < 0 or index >= self._stack.count():
            return
        self._stack.setCurrentIndex(index)
        for i, btn in enumerate(self._nav_btns):
            btn.setChecked(i == index)
        for i, action in enumerate(self._page_actions):
            action.setChecked(i == index)

    def _restore_window_state(self) -> None:
        geometry = self._settings.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        page = self._settings.value("window/page", 0, type=int)
        self._switch_page(page)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About " + APP_NAME,
            "<h3>" + APP_NAME + " " + APP_VERSION + "</h3>"
            "<p>Team-first rune and artifact optimization for Summoners War.</p>"
            "<p>Includes SWEX profiles, dungeon simulation, account analytics, "
            "sell guidance, and PvP planning.</p>",
        )

    # ------------------------------------------------------------------
    # Account import
    # ------------------------------------------------------------------

    def _on_import_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select SWEX JSON export",
            str(Path.home()), "JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        self._import_btn.setEnabled(False)
        self._status.showMessage("Importing...")
        self._progress = QProgressDialog("Importing account data...", None, 0, 0, self)
        self._progress.setWindowTitle("Importing")
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.setCancelButton(None)
        self._progress.show()
        self._worker = ImportWorker(Path(path), self._db_path)
        self._worker.progress.connect(self._on_import_progress)
        self._worker.finished.connect(self._on_import_finished)
        self._worker.start()

    def _on_import_progress(self, msg: str) -> None:
        self._progress.setLabelText(msg)
        self._status.showMessage(msg)
        QApplication.processEvents()

    def _on_import_finished(self, success: bool, error: str) -> None:
        self._progress.close()
        self._import_btn.setEnabled(True)
        if success:
            self._refresh_all()
            info = queries.get_account_info(self._conn)
            self._status.showMessage(
                "Import complete -- %d runes, %d monsters, %d artifacts" % (
                    info.get("rune_count", 0),
                    info.get("monster_count", 0),
                    info.get("artifact_count", 0),
                )
            )
        else:
            self._status.showMessage("Import failed")
            QMessageBox.critical(self, "Import Failed", "Error:\n\n" + error)

    # ------------------------------------------------------------------
    # Dungeon data import
    # ------------------------------------------------------------------

    def _on_dungeon_import_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select dungeon_monsters_by_wave.json",
            str(Path.home()),
            "JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            self._dungeon_import_btn.setEnabled(False)
            self._status.showMessage("Loading dungeon data...")
            QApplication.processEvents()
            n = self._dungeon_page.load_dungeon_data(path)
            self._status.showMessage(
                "Dungeon data loaded — %d enemy entries across all dungeons" % n
            )
            # Jump to dungeon builder
            self._switch_page(5)
        except Exception as exc:
            QMessageBox.critical(
                self, "Dungeon Import Failed", "Error:\n\n" + str(exc)
            )
            self._status.showMessage("Dungeon import failed")
        finally:
            self._dungeon_import_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def _on_profile_changed(self, index: int) -> None:
        profile_id = self._profile_combo.itemData(index)
        if profile_id is None or profile_id == queries.get_active_profile_id(self._conn):
            return
        try:
            info = queries.activate_account_profile(self._conn, int(profile_id))
            self._refresh_all()
            self._status.showMessage(
                "Switched to %s -- %d runes, %d monsters"
                % (
                    info.get("player_name", "account"),
                    info.get("rune_count", 0),
                    info.get("monster_count", 0),
                )
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Account Switch Failed",
                "Could not switch accounts:\n\n" + str(exc),
            )
            self._refresh_account_info()

    def _refresh_account_info(self) -> None:
        info = queries.get_account_info(self._conn)
        profiles = queries.list_account_profiles(self._conn)
        active_id = queries.get_active_profile_id(self._conn)

        self._profile_combo.blockSignals(True)
        try:
            self._profile_combo.clear()
            active_index = -1
            for index, profile in enumerate(profiles):
                self._profile_combo.addItem(
                    profile["profile_name"],
                    profile["profile_id"],
                )
                if profile["profile_id"] == active_id:
                    active_index = index
            if active_index >= 0:
                self._profile_combo.setCurrentIndex(active_index)
            self._profile_combo.setEnabled(bool(profiles))
        finally:
            self._profile_combo.blockSignals(False)

        if info:
            self._player_lbl.setText("Account")
            self._profile_combo.setToolTip(
                "%d saved account profile%s"
                % (
                    len(profiles),
                    "" if len(profiles) == 1 else "s",
                )
            )
            self._rune_lbl.setText("%d runes" % info["rune_count"])
            self._monster_lbl.setText("%d monsters" % info["monster_count"])
            self._artifact_lbl.setText("%d artifacts" % info["artifact_count"])
        else:
            self._player_lbl.setText("Account")
            self._profile_combo.setToolTip("Import a SWEX JSON account")
            self._rune_lbl.setText("")
            self._monster_lbl.setText("")
            self._artifact_lbl.setText("")

    def _refresh_all(self) -> None:
        self._refresh_account_info()
        self._rune_page.refresh()
        self._monster_page.refresh()
        self._artifact_page.refresh()
        self._sell_page.refresh()
        self._analytics_page.refresh()
        self._rune_opt_page.refresh()
        self._team_opt_page.refresh()
        self._dungeon_page.refresh()
        self._pvp_page.refresh()

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self,
                "Import in Progress",
                "Please let the account import finish before closing the app.",
            )
            event.ignore()
            return

        active_pages = [
            page
            for page in (self._rune_opt_page, self._team_opt_page)
            if page.is_task_running()
        ]
        if active_pages:
            answer = QMessageBox.question(
                self,
                "Optimization in Progress",
                "Cancel the running optimization and exit?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            stopped = [page.cancel_active_task() for page in active_pages]
            if not all(stopped):
                QMessageBox.warning(
                    self,
                    "Still Shutting Down",
                    "The optimizer is still stopping. Please try closing again in a moment.",
                )
                event.ignore()
                return

        self._settings.setValue("window/geometry", self.saveGeometry())
        self._settings.setValue("window/page", self._stack.currentIndex())
        self._settings.sync()
        self._conn.close()
        event.accept()
        super().closeEvent(event)
