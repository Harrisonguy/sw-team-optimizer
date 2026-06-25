"""PvP planner for Arena, Guild/Siege, and World Arena."""
from __future__ import annotations

import json
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame,
    QComboBox, QPushButton, QSpinBox, QDoubleSpinBox, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QListWidget, QInputDialog, QMessageBox, QSizePolicy,
)

from desktop.db import queries
from desktop.ui.theme import BG_CARD, BG_PANEL, BORDER, TEXT_DIM, TEXT_MAIN, ACCENT
from optimizer.pvp_analyzer import (
    MODE_LABELS,
    MODE_TEAM_SIZE,
    PvpUnit,
    analyze_pvp_team,
    rank_pvp_candidates,
)


class _Metric(QFrame):
    def __init__(self, label: str, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            "QFrame { background: " + BG_CARD + "; border: 1px solid " + BORDER
            + "; border-radius: 6px; } QLabel { border: none; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)
        self._value = QLabel("--")
        self._value.setFont(QFont("Segoe UI", 16, QFont.Bold))
        self._value.setAlignment(Qt.AlignCenter)
        self._value.setStyleSheet("color: " + ACCENT + ";")
        caption = QLabel(label)
        caption.setAlignment(Qt.AlignCenter)
        caption.setStyleSheet("color: " + TEXT_DIM + ";")
        layout.addWidget(self._value)
        layout.addWidget(caption)

    def set_value(self, value: str, color: str | None = None) -> None:
        self._value.setText(value)
        self._value.setStyleSheet("color: " + (color or ACCENT) + ";")


class PvpPlannerWidget(QWidget):
    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self._conn = conn
        self._roster: list[PvpUnit] = []
        self._last_report: dict | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("PvP Planner")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        header.addWidget(title)
        header.addStretch()
        self._roster_lbl = QLabel("")
        self._roster_lbl.setStyleSheet("color: " + TEXT_DIM + ";")
        header.addWidget(self._roster_lbl)
        root.addLayout(header)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Saved plan"))
        self._preset_combo = QComboBox()
        self._preset_combo.setMinimumWidth(220)
        preset_row.addWidget(self._preset_combo)
        self._load_btn = QPushButton("Load")
        self._save_btn = QPushButton("Save")
        self._delete_btn = QPushButton("Delete")
        self._load_btn.clicked.connect(self._load_plan)
        self._save_btn.clicked.connect(self._save_plan)
        self._delete_btn.clicked.connect(self._delete_plan)
        for button in (self._load_btn, self._save_btn, self._delete_btn):
            preset_row.addWidget(button)
        preset_row.addStretch()
        root.addLayout(preset_row)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_controls())
        splitter.addWidget(self._build_results())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([360, 980])
        root.addWidget(splitter, 1)

    def _panel(self) -> QFrame:
        panel = QFrame()
        panel.setStyleSheet(
            "QFrame { background: " + BG_PANEL + "; border: 1px solid " + BORDER
            + "; border-radius: 6px; } QLabel { border: none; }"
        )
        return panel

    def _build_controls(self) -> QWidget:
        panel = self._panel()
        panel.setMinimumWidth(330)
        panel.setMaximumWidth(430)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Content"))
        self._mode_combo = QComboBox()
        for key in (
            "arena_offense", "arena_defense", "siege_offense", "siege_defense",
            "guild_offense", "guild_defense", "rta",
        ):
            self._mode_combo.addItem(MODE_LABELS[key], key)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self._mode_combo, 1)
        layout.addLayout(mode_row)

        team_title = QLabel("Planned Turn Order")
        team_title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        layout.addWidget(team_title)
        self._team_rows: list[QWidget] = []
        self._team_combos: list[QComboBox] = []
        for index in range(5):
            row_widget = QWidget()
            row_widget.setStyleSheet("background: transparent;")
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            label = QLabel(str(index + 1))
            label.setFixedWidth(18)
            combo = QComboBox()
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.NoInsert)
            combo.lineEdit().setPlaceholderText("Select monster")
            completer = combo.completer()
            if completer:
                completer.setFilterMode(Qt.MatchContains)
                completer.setCaseSensitivity(Qt.CaseInsensitive)
            combo.currentIndexChanged.connect(self._update_leaders)
            row.addWidget(label)
            row.addWidget(combo, 1)
            self._team_rows.append(row_widget)
            self._team_combos.append(combo)
            layout.addWidget(row_widget)

        leader_row = QHBoxLayout()
        leader_row.addWidget(QLabel("Leader"))
        self._leader_combo = QComboBox()
        leader_row.addWidget(self._leader_combo, 1)
        layout.addLayout(leader_row)

        assumptions = QLabel("Matchup Assumptions")
        assumptions.setFont(QFont("Segoe UI", 10, QFont.Bold))
        layout.addWidget(assumptions)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        self._enemy_min = QSpinBox()
        self._enemy_min.setRange(0, 500)
        self._enemy_min.setValue(280)
        self._enemy_max = QSpinBox()
        self._enemy_max.setRange(0, 500)
        self._enemy_max.setValue(330)
        self._enemy_lead = QDoubleSpinBox()
        self._enemy_lead.setRange(0, 40)
        self._enemy_lead.setValue(24)
        self._enemy_lead.setSuffix("%")
        self._enemy_base = QSpinBox()
        self._enemy_base.setRange(50, 150)
        self._enemy_base.setValue(100)
        self._boost = QDoubleSpinBox()
        self._boost.setRange(0, 100)
        self._boost.setValue(30)
        self._boost.setSuffix("%")
        controls = (
            ("Enemy SPD low", self._enemy_min),
            ("Enemy SPD high", self._enemy_max),
            ("Enemy lead", self._enemy_lead),
            ("Enemy base SPD", self._enemy_base),
            ("Opener ATB boost", self._boost),
        )
        for row, (label, control) in enumerate(controls):
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(control, row, 1)
        layout.addLayout(grid)

        self._analyze_btn = QPushButton("Analyze Matchup")
        self._analyze_btn.setMinimumHeight(34)
        self._analyze_btn.clicked.connect(self._analyze)
        layout.addWidget(self._analyze_btn)
        layout.addStretch()
        return panel

    def _build_results(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        metrics = QHBoxLayout()
        self._score_metric = _Metric("Team Score")
        self._speed_metric = _Metric("Speed Win")
        self._coverage_metric = _Metric("Role Coverage")
        self._tuning_metric = _Metric("Turn Tuning")
        for metric in (
            self._score_metric, self._speed_metric,
            self._coverage_metric, self._tuning_metric,
        ):
            metrics.addWidget(metric)
        layout.addLayout(metrics)

        self._coverage_lbl = QLabel("Select a team and analyze the matchup.")
        self._coverage_lbl.setWordWrap(True)
        self._coverage_lbl.setStyleSheet("color: " + TEXT_DIM + ";")
        layout.addWidget(self._coverage_lbl)

        self._turn_table = QTableWidget(0, 6)
        self._turn_table.setHorizontalHeaderLabels(
            ["Plan", "Monster", "Combat SPD", "Actual", "ATB After Opener", "Ready"]
        )
        self._turn_table.verticalHeader().setVisible(False)
        self._turn_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._turn_table.setSelectionMode(QAbstractItemView.NoSelection)
        self._turn_table.setAlternatingRowColors(True)
        self._turn_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._turn_table.horizontalHeader().setStretchLastSection(True)
        self._turn_table.setFixedHeight(180)
        layout.addWidget(self._turn_table)

        notes_row = QHBoxLayout()
        risk_panel = self._panel()
        risk_layout = QVBoxLayout(risk_panel)
        risk_title = QLabel("Risks")
        risk_title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self._risk_list = QListWidget()
        risk_layout.addWidget(risk_title)
        risk_layout.addWidget(self._risk_list)
        notes_row.addWidget(risk_panel, 1)

        recommendation_panel = self._panel()
        recommendation_layout = QVBoxLayout(recommendation_panel)
        recommendation_title = QLabel("Next Adjustments")
        recommendation_title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self._recommendation_list = QListWidget()
        recommendation_layout.addWidget(recommendation_title)
        recommendation_layout.addWidget(self._recommendation_list)
        notes_row.addWidget(recommendation_panel, 1)
        layout.addLayout(notes_row, 1)

        candidate_title = QLabel("Best Account Candidates")
        candidate_title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        layout.addWidget(candidate_title)
        self._candidate_table = QTableWidget(0, 7)
        self._candidate_table.setHorizontalHeaderLabels(
            ["Monster", "Element", "SPD", "EO", "EHP", "Fills", "Score"]
        )
        self._candidate_table.verticalHeader().setVisible(False)
        self._candidate_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._candidate_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._candidate_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._candidate_table.setAlternatingRowColors(True)
        self._candidate_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._candidate_table.horizontalHeader().setStretchLastSection(True)
        self._candidate_table.doubleClicked.connect(self._add_candidate)
        self._candidate_table.setFixedHeight(205)
        layout.addWidget(self._candidate_table)
        return container

    def refresh(self) -> None:
        self._roster = queries.get_pvp_roster(self._conn, min_equipped_runes=4)
        self._roster_lbl.setText(str(len(self._roster)) + " built monsters")
        selected_ids = [self._selected_id(combo) for combo in self._team_combos]
        labels = self._roster_labels()
        for combo, selected_id in zip(self._team_combos, selected_ids):
            combo.blockSignals(True)
            combo.clear()
            for label, unit in zip(labels, self._roster):
                combo.addItem(label, unit)
            index = self._find_unit_index(combo, selected_id)
            combo.setCurrentIndex(index)
            if index < 0:
                combo.lineEdit().clear()
            combo.blockSignals(False)
        self._refresh_presets()
        self._on_mode_changed()

    def _roster_labels(self) -> list[str]:
        name_counts: dict[str, int] = {}
        labels = []
        for unit in self._roster:
            name_counts[unit.name] = name_counts.get(unit.name, 0) + 1
            labels.append(
                "%s | %s | %d SPD" % (unit.name, unit.element or "?", round(unit.speed))
            )
        return labels

    @staticmethod
    def _selected_id(combo: QComboBox) -> int | None:
        data = combo.currentData()
        return data.unit_id if isinstance(data, PvpUnit) else None

    @staticmethod
    def _find_unit_index(combo: QComboBox, unit_id: int | None) -> int:
        if unit_id is None:
            return -1
        for index in range(combo.count()):
            data = combo.itemData(index)
            if isinstance(data, PvpUnit) and data.unit_id == unit_id:
                return index
        return -1

    def _active_team_size(self) -> int:
        return MODE_TEAM_SIZE.get(str(self._mode_combo.currentData()), 5)

    def _selected_units(self) -> list[PvpUnit]:
        result = []
        seen = set()
        for combo in self._team_combos[:self._active_team_size()]:
            unit = combo.currentData()
            if isinstance(unit, PvpUnit) and unit.unit_id not in seen:
                result.append(unit)
                seen.add(unit.unit_id)
        return result

    def _on_mode_changed(self) -> None:
        size = self._active_team_size()
        for index, row in enumerate(self._team_rows):
            row.setVisible(index < size)
        self._update_leaders()

    def _update_leaders(self) -> None:
        selected_id = self._leader_combo.currentData()
        units = self._selected_units()
        self._leader_combo.blockSignals(True)
        self._leader_combo.clear()
        self._leader_combo.addItem("No leader", None)
        for unit in units:
            label = unit.name
            if unit.leader_attribute:
                label += " | %s +%g%%" % (unit.leader_attribute, unit.leader_amount)
            self._leader_combo.addItem(label, unit.unit_id)
        index = self._leader_combo.findData(selected_id)
        self._leader_combo.setCurrentIndex(index if index >= 0 else 0)
        self._leader_combo.blockSignals(False)

    def _analyze(self) -> None:
        units = self._selected_units()
        mode = str(self._mode_combo.currentData() or "arena_offense")
        report = analyze_pvp_team(
            units,
            mode,
            leader_unit_id=self._leader_combo.currentData(),
            enemy_min_speed=self._enemy_min.value(),
            enemy_max_speed=self._enemy_max.value(),
            enemy_lead_pct=self._enemy_lead.value(),
            enemy_base_speed=self._enemy_base.value(),
            atb_boost_pct=self._boost.value(),
        )
        self._last_report = report
        self._show_report(report, units)

    @staticmethod
    def _metric_color(value: float) -> str:
        if value >= 75:
            return "#3fb950"
        if value >= 50:
            return "#d29922"
        return "#f85149"

    def _show_report(self, report: dict, units: list[PvpUnit]) -> None:
        contest = report["speed_contest"]
        score = float(report["score"])
        coverage = float(report["coverage_score"])
        speed_win = float(contest.win_probability)
        self._score_metric.set_value("%.0f/100" % score, self._metric_color(score))
        self._speed_metric.set_value("%.0f%%" % speed_win, self._metric_color(speed_win))
        self._coverage_metric.set_value("%.0f%%" % coverage, self._metric_color(coverage))
        tuning_text = "Ready" if report["order_ok"] and report["cut_safe"] else "At Risk"
        self._tuning_metric.set_value(tuning_text, "#3fb950" if tuning_text == "Ready" else "#f85149")
        capabilities = ", ".join(item.replace("_", " ") for item in report["capabilities"]) or "none"
        missing = ", ".join(item.replace("_", " ") for item in report["missing_capabilities"]) or "none"
        self._coverage_lbl.setText(
            "Coverage: %s | Missing: %s | Enemy combat SPD: %d-%d"
            % (capabilities, missing, contest.enemy_min_speed, contest.enemy_max_speed)
        )

        rows = report["turn_order"]
        self._turn_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                row["position"], row["name"], row["speed"], row["actual_position"],
                "%.1f%%" % row["atb_after_opener"],
                "Yes" if row["ready_after_boost"] else "No",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column != 1:
                    item.setTextAlignment(Qt.AlignCenter)
                if column == 5:
                    item.setForeground(QColor("#3fb950" if row["ready_after_boost"] else "#f85149"))
                self._turn_table.setItem(row_index, column, item)

        self._risk_list.clear()
        self._risk_list.addItems(report["risks"] or ["No major modeled risks found."])
        self._recommendation_list.clear()
        self._recommendation_list.addItems(
            report["recommendations"] or ["Current selections meet the modeled checks."]
        )

        candidates = rank_pvp_candidates(
            self._roster, units, report, str(report["mode"]), limit=8
        )
        self._candidate_table.setRowCount(len(candidates))
        for row_index, candidate in enumerate(candidates):
            values = [
                candidate["name"], candidate["element"], candidate["speed"],
                candidate["offense"], candidate["durability"],
                ", ".join(item.replace("_", " ") for item in candidate["fills"]) or "Build strength",
                candidate["score"],
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.UserRole, candidate["unit_id"])
                if column in (2, 3, 4, 6):
                    item.setTextAlignment(Qt.AlignCenter)
                self._candidate_table.setItem(row_index, column, item)

    def _add_candidate(self, index) -> None:
        item = self._candidate_table.item(index.row(), 0)
        unit_id = item.data(Qt.UserRole) if item else None
        if unit_id is None:
            return
        for combo in self._team_combos[:self._active_team_size()]:
            if combo.currentIndex() < 0:
                combo.setCurrentIndex(self._find_unit_index(combo, int(unit_id)))
                self._update_leaders()
                self._analyze()
                return

    def _plan_config(self) -> dict:
        return {
            "mode": self._mode_combo.currentData(),
            "unit_ids": [self._selected_id(combo) for combo in self._team_combos],
            "leader_unit_id": self._leader_combo.currentData(),
            "enemy_min_speed": self._enemy_min.value(),
            "enemy_max_speed": self._enemy_max.value(),
            "enemy_lead_pct": self._enemy_lead.value(),
            "enemy_base_speed": self._enemy_base.value(),
            "atb_boost_pct": self._boost.value(),
        }

    def _refresh_presets(self, selected_id: int | None = None) -> None:
        current = selected_id if selected_id is not None else self._preset_combo.currentData()
        self._preset_combo.clear()
        self._preset_combo.addItem("Select saved plan", None)
        for config in queries.list_pvp_configs(self._conn):
            self._preset_combo.addItem(
                "%s | %s" % (config["name"], MODE_LABELS.get(config["mode"], config["mode"])),
                config["id"],
            )
        index = self._preset_combo.findData(current)
        if index >= 0:
            self._preset_combo.setCurrentIndex(index)

    def _save_plan(self) -> None:
        name, accepted = QInputDialog.getText(self, "Save PvP Plan", "Plan name")
        if not accepted or not name.strip():
            return
        config_id = queries.save_pvp_config(
            self._conn,
            name.strip(),
            str(self._mode_combo.currentData()),
            json.dumps(self._plan_config()),
        )
        self._refresh_presets(config_id)

    def _load_plan(self) -> None:
        config_id = self._preset_combo.currentData()
        if config_id is None:
            return
        stored = queries.load_pvp_config(self._conn, int(config_id))
        if not stored:
            return
        try:
            config = json.loads(stored["config_json"])
        except (TypeError, ValueError):
            return
        mode_index = self._mode_combo.findData(config.get("mode"))
        if mode_index >= 0:
            self._mode_combo.setCurrentIndex(mode_index)
        for combo, unit_id in zip(self._team_combos, config.get("unit_ids", [])):
            combo.setCurrentIndex(self._find_unit_index(combo, unit_id))
            if combo.currentIndex() < 0:
                combo.lineEdit().clear()
        self._update_leaders()
        leader_index = self._leader_combo.findData(config.get("leader_unit_id"))
        self._leader_combo.setCurrentIndex(leader_index if leader_index >= 0 else 0)
        self._enemy_min.setValue(int(config.get("enemy_min_speed", 280)))
        self._enemy_max.setValue(int(config.get("enemy_max_speed", 330)))
        self._enemy_lead.setValue(float(config.get("enemy_lead_pct", 0)))
        self._enemy_base.setValue(int(config.get("enemy_base_speed", 100)))
        self._boost.setValue(float(config.get("atb_boost_pct", 0)))
        self._analyze()

    def _delete_plan(self) -> None:
        config_id = self._preset_combo.currentData()
        if config_id is None:
            return
        response = QMessageBox.question(
            self, "Delete PvP Plan", "Delete the selected saved plan?"
        )
        if response == QMessageBox.Yes:
            queries.delete_pvp_config(self._conn, int(config_id))
            self._refresh_presets()
