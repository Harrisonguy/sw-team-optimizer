"""Artifact inventory viewer widget."""
from __future__ import annotations

import json
import sqlite3

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QComboBox, QPushButton,
    QTableView, QAbstractItemView, QFrame,
    QSizePolicy, QHeaderView, QCheckBox, QTableWidget, QTableWidgetItem,
)

from desktop.db import queries
from desktop.ui.theme import BG_CARD, BORDER, TEXT_DIM
from optimizer.artifact_optimizer import ArtifactProfile, rank_artifact_pairs
from optimizer.artifact_analyzer import analyze_artifact_inventory

# ── Quality rank → label ──────────────────────────────────────────────────────
_RANK_LABELS = {1: "Common", 2: "Magic", 3: "Rare", 4: "Hero", 5: "Legend"}

# ── Columns ───────────────────────────────────────────────────────────────────
_COLS = [
    ("slot_label",          "Slot"),
    ("requirement_label",   "Applies To"),
    ("quality",             "Quality"),
    ("level",               "Lvl"),
    ("artifact_efficiency", "Efficiency"),
    ("artifact_value",      "Value"),
    ("artifact_potential",  "Potential"),
    ("artifact_profile",    "Build"),
    ("artifact_action",     "Action"),
    ("pri_effect",          "Primary Effect"),
    ("sec1",                "Effect 2"),
    ("sec2",                "Effect 3"),
    ("sec3",                "Effect 4"),
    ("locked_str",          "Locked"),
    ("location_label",      "Location"),
]

_NUM_KEYS = {"level", "artifact_efficiency", "artifact_value", "artifact_potential"}
_NUM_COLS: set[int] = {index for index, (key, _) in enumerate(_COLS) if key in _NUM_KEYS}
_ACTION_ORDER = {"Sell": 0, "Review": 1, "Upgrade": 2, "Keep": 3}


# ── Model ─────────────────────────────────────────────────────────────────────

class ArtifactTableModel(QAbstractTableModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[dict] = []

    def set_artifacts(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = [_enrich(r) for r in rows]
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(_COLS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return _COLS[section][1]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        key = _COLS[index.column()][0]
        col = index.column()

        if role == Qt.DisplayRole:
            val = row.get(key)
            return "" if val is None else str(val)

        if role == Qt.UserRole:
            if col in _NUM_COLS:
                try:
                    return float(row.get(key) or 0)
                except (ValueError, TypeError):
                    return 0.0
            return row

        if role == Qt.TextAlignmentRole:
            if key in (
                "slot_label", "quality", "level", "artifact_efficiency",
                "artifact_value", "artifact_potential", "artifact_profile",
                "artifact_action", "locked_str",
            ):
                return Qt.AlignCenter

        if role == Qt.ForegroundRole and key == "artifact_action":
            colors = {
                "Upgrade": "#58a6ff", "Review": "#d29922",
                "Sell": "#f85149", "Keep": "#3fb950",
            }
            return QColor(colors.get(str(row.get(key)), "#8b949e"))

        if role == Qt.ToolTipRole and key in {
            "artifact_efficiency", "artifact_value", "artifact_potential",
            "artifact_profile", "artifact_action",
        }:
            return str(row.get("artifact_reason") or "")

        return None


class ArtifactSortProxy(QSortFilterProxyModel):
    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        key = _COLS[left.column()][0]
        if key == "artifact_action":
            left_row = self.sourceModel().data(left, Qt.UserRole) or {}
            right_row = self.sourceModel().data(right, Qt.UserRole) or {}
            return _ACTION_ORDER.get(left_row.get(key), 9) < _ACTION_ORDER.get(right_row.get(key), 9)
        if left.column() in _NUM_COLS:
            lv = self.sourceModel().data(left,  Qt.UserRole)
            rv = self.sourceModel().data(right, Qt.UserRole)
            try:
                return float(lv or 0) < float(rv or 0)
            except (ValueError, TypeError):
                pass
        return super().lessThan(left, right)


# ── Widget ────────────────────────────────────────────────────────────────────

class ArtifactTableWidget(QWidget):
    """
    Artifact inventory panel with filter bar and sortable table.
    Call ``refresh()`` after a new import.
    """

    def __init__(self, conn: sqlite3.Connection, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._conn = conn
        self._build_ui()
        self._connect_signals()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Title row
        hdr = QHBoxLayout()
        lbl = QLabel("Artifact Inventory")
        lbl.setObjectName("title")
        hdr.addWidget(lbl)
        hdr.addStretch()
        self._analysis_lbl = QLabel("")
        self._analysis_lbl.setStyleSheet("color: " + TEXT_DIM + ";")
        hdr.addWidget(self._analysis_lbl)
        self._count_lbl = QLabel("0 artifacts")
        self._count_lbl.setObjectName("subtitle")
        hdr.addWidget(self._count_lbl)
        root.addLayout(hdr)

        root.addWidget(self._build_filter_bar())
        root.addWidget(self._build_optimizer_bar())

        self._recommend_table = QTableWidget(0, 7)
        self._recommend_table.setHorizontalHeaderLabels(
            ["#", "Attribute Artifact", "Type Artifact", "Damage Gain",
             "Survival Gain", "Support", "Score"]
        )
        self._recommend_table.verticalHeader().setVisible(False)
        self._recommend_table.setSelectionMode(QAbstractItemView.NoSelection)
        self._recommend_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._recommend_table.setAlternatingRowColors(True)
        self._recommend_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self._recommend_table.horizontalHeader().setStretchLastSection(True)
        self._recommend_table.setFixedHeight(168)
        self._recommend_table.hide()
        root.addWidget(self._recommend_table)

        # Table
        self._model = ArtifactTableModel(self)
        self._proxy = ArtifactSortProxy(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortCaseSensitivity(Qt.CaseInsensitive)

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setSortingEnabled(True)
        self._table.sortByColumn(3, Qt.DescendingOrder)   # default: highest level first
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.setShowGrid(False)
        root.addWidget(self._table)

        for col, width in {
            0: 80, 1: 130, 2: 75, 3: 45,
            4: 75, 5: 65, 6: 70, 7: 80, 8: 70,
            9: 210, 10: 180, 11: 180, 12: 180,
            13: 55, 14: 180,
        }.items():
            self._table.setColumnWidth(col, width)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._apply_filters)

    def _build_filter_bar(self) -> QWidget:
        bar = QFrame()
        bar.setFrameShape(QFrame.StyledPanel)
        bar.setStyleSheet(
            f"background-color: {BG_CARD}; border: 1px solid {BORDER}; border-radius: 6px;"
        )
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        def combo(placeholder: str, width: int, items: list[str] = []) -> QComboBox:
            c = QComboBox()
            c.addItem(placeholder, None)
            for it in items:
                c.addItem(it, it)
            c.setFixedWidth(width)
            return c

        self._filter_slot    = combo("All Slots",      110, ["Attribute", "Type"])
        self._filter_req     = combo("All",             140)
        self._filter_quality = combo("All Quality",     110,
                                     ["Legend", "Hero", "Rare", "Magic", "Common"])
        self._filter_action  = combo("All Actions",     110,
                                     ["Upgrade", "Review", "Sell", "Keep"])
        self._filter_loc     = combo("All Locations",  130, ["Equipped", "Storage"])

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search effect, monster…")
        self._search_box.setClearButtonEnabled(True)
        self._search_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._reset_btn = QPushButton("Reset")
        self._reset_btn.setStyleSheet(
            f"QPushButton {{ color: {TEXT_DIM}; padding: 4px 8px; }}")

        for lbl_text, widget in [
            ("Slot:",      self._filter_slot),
            ("Applies To:",self._filter_req),
            ("Quality:",   self._filter_quality),
            ("Action:",    self._filter_action),
            ("Location:",  self._filter_loc),
        ]:
            layout.addWidget(QLabel(lbl_text))
            layout.addWidget(widget)
        layout.addWidget(self._search_box)
        layout.addWidget(self._reset_btn)

        return bar

    def _build_optimizer_bar(self) -> QWidget:
        bar = QFrame()
        bar.setFrameShape(QFrame.StyledPanel)
        bar.setStyleSheet(
            f"background-color: {BG_CARD}; border: 1px solid {BORDER}; border-radius: 6px;"
        )
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        self._optimizer_monster = QComboBox()
        self._optimizer_monster.setMinimumWidth(210)

        self._optimizer_goal = QComboBox()
        self._optimizer_goal.addItem("Damage", "damage")
        self._optimizer_goal.addItem("Survivability", "survivability")
        self._optimizer_goal.addItem("Support", "support")
        self._optimizer_goal.addItem("Balanced", "balanced")

        self._optimizer_element = QComboBox()
        self._optimizer_element.addItem("Any Target", None)
        for element in ("Fire", "Water", "Wind", "Light", "Dark"):
            self._optimizer_element.addItem(element, element)

        self._optimizer_skill = QComboBox()
        self._optimizer_skill.addItem("Any Skill", None)
        for skill_number in range(1, 5):
            self._optimizer_skill.addItem("Skill " + str(skill_number), skill_number)

        self._optimizer_equipped = QCheckBox("Use artifacts on other monsters")
        self._optimizer_btn = QPushButton("Find Best Pair")
        self._optimizer_btn.clicked.connect(self._run_artifact_optimizer)

        for label, widget in (
            ("Monster:", self._optimizer_monster),
            ("Goal:", self._optimizer_goal),
            ("Enemy:", self._optimizer_element),
            ("Skill:", self._optimizer_skill),
        ):
            layout.addWidget(QLabel(label))
            layout.addWidget(widget)
        layout.addWidget(self._optimizer_equipped)
        layout.addStretch()
        layout.addWidget(self._optimizer_btn)
        return bar

    def _connect_signals(self) -> None:
        for combo in (self._filter_slot, self._filter_req,
                      self._filter_quality, self._filter_action,
                      self._filter_loc):
            combo.currentIndexChanged.connect(self._apply_filters)
        self._search_box.textChanged.connect(self._search_timer.start)
        self._reset_btn.clicked.connect(self._reset_filters)

    def refresh(self) -> None:
        """Reload filter options and artifact data."""
        self._populate_optimizer_monsters()
        # Repopulate "Applies To" from actual DB content
        rows = self._conn.execute(
            "SELECT DISTINCT requirement_label FROM artifacts "
            "WHERE requirement_label IS NOT NULL ORDER BY requirement_label"
        ).fetchall()
        req_items = [r[0] for r in rows]

        old = self._filter_req.currentData()
        self._filter_req.blockSignals(True)
        self._filter_req.clear()
        self._filter_req.addItem("All", None)
        for it in req_items:
            self._filter_req.addItem(it, it)
        idx = self._filter_req.findData(old)
        if idx >= 0:
            self._filter_req.setCurrentIndex(idx)
        self._filter_req.blockSignals(False)

        self._artifact_report = analyze_artifact_inventory(
            queries.get_artifacts(self._conn)
        )
        counts = self._artifact_report["counts"]
        self._analysis_lbl.setText(
            "Upgrade %s  |  Review %s  |  Sell %s  |  Keep bar %.0f"
            % (
                counts["Upgrade"], counts["Review"], counts["Sell"],
                self._artifact_report["keep_bar"],
            )
        )
        self._apply_filters()

    def _populate_optimizer_monsters(self) -> None:
        selected_id = self._optimizer_monster.currentData()
        monsters = queries.get_monsters(self._conn)
        self._optimizer_monster.blockSignals(True)
        try:
            self._optimizer_monster.clear()
            for monster in monsters:
                self._optimizer_monster.addItem(
                    "%s (%s %s)"
                    % (
                        monster["display_name"],
                        monster.get("element") or "?",
                        monster.get("archetype") or "?",
                    ),
                    monster["unit_id"],
                )
            if selected_id is not None:
                index = self._optimizer_monster.findData(selected_id)
                if index >= 0:
                    self._optimizer_monster.setCurrentIndex(index)
            self._optimizer_monster.setEnabled(bool(monsters))
            self._optimizer_btn.setEnabled(bool(monsters))
        finally:
            self._optimizer_monster.blockSignals(False)

    @staticmethod
    def _artifact_result_label(artifact: dict | None) -> str:
        if artifact is None:
            return "None"
        return "#%s  %s  |  %s" % (
            artifact.get("artifact_id", "?"),
            artifact.get("requirement_label") or "?",
            artifact.get("pri_effect") or "No main effect",
        )

    def _run_artifact_optimizer(self) -> None:
        unit_id = self._optimizer_monster.currentData()
        if unit_id is None:
            return
        monsters = {
            monster["unit_id"]: monster
            for monster in queries.get_monsters(self._conn)
        }
        monster = monsters.get(int(unit_id))
        if not monster:
            return
        stats = queries.compute_monster_stats(
            self._conn,
            int(unit_id),
            include_artifacts=False,
        )
        if not stats:
            return
        profile = ArtifactProfile(
            goal=str(self._optimizer_goal.currentData() or "damage"),
            target_element=self._optimizer_element.currentData(),
            skill_number=self._optimizer_skill.currentData(),
            single_target=True,
            enemy_hp_ratio=1.0,
        )
        results = rank_artifact_pairs(
            queries.get_artifacts(self._conn),
            monster,
            stats,
            profile,
            top_n=5,
            include_equipped=self._optimizer_equipped.isChecked(),
        )

        self._recommend_table.setRowCount(len(results))
        for row_index, result in enumerate(results):
            values = [
                str(row_index + 1),
                self._artifact_result_label(result.attribute_artifact),
                self._artifact_result_label(result.type_artifact),
                "+%s" % f"{result.damage_gain:,.0f}",
                "+%s" % f"{result.survivability_gain:,.0f}",
                f"{result.support_score:,.1f}",
                f"{result.score:,.0f}",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in (0, 3, 4, 5, 6):
                    item.setTextAlignment(Qt.AlignCenter)
                if column in (1, 2):
                    item.setToolTip("\n".join(result.reasons))
                self._recommend_table.setItem(row_index, column, item)
        self._recommend_table.setVisible(bool(results))

    def _apply_filters(self) -> None:
        slot_val    = self._filter_slot.currentData()
        req_val     = self._filter_req.currentData()
        quality_val = self._filter_quality.currentData()
        action_val  = self._filter_action.currentData()
        loc_val     = self._filter_loc.currentData()
        search      = self._search_box.text().strip()

        # Map quality label → rank int for filtering
        quality_rank_map = {
            "Legend": 5, "Hero": 4, "Rare": 3, "Magic": 2, "Common": 1,
        }

        report = getattr(self, "_artifact_report", {"artifacts": []})
        rows = [dict(row) for row in report.get("artifacts", [])]
        if req_val:
            rows = [row for row in rows if row.get("requirement_label") == req_val]
        if search:
            needle = search.lower()
            rows = [
                row for row in rows
                if needle in " ".join(
                    str(row.get(key) or "")
                    for key in (
                        "requirement_label", "pri_effect", "sec_effects",
                        "occupied_name", "artifact_profile", "artifact_action",
                    )
                ).lower()
            ]

        # Apply slot + quality + location filters in Python
        # (simple enough that we don't need to plumb them through queries.py)
        if slot_val:
            rows = [r for r in rows if r.get("slot_label") == slot_val]
        if quality_val:
            target_rank = quality_rank_map.get(quality_val)
            if target_rank:
                rows = [r for r in rows if r.get("rank") == target_rank]
        if action_val:
            rows = [r for r in rows if r.get("artifact_action") == action_val]
        if loc_val == "Equipped":
            rows = [r for r in rows if r.get("occupied_name")]
        elif loc_val == "Storage":
            rows = [r for r in rows if not r.get("occupied_name")]

        self._model.set_artifacts(rows)
        self._count_lbl.setText(f"{len(rows):,} artifacts")

    def _reset_filters(self) -> None:
        for combo in (self._filter_slot, self._filter_req,
                      self._filter_quality, self._filter_action,
                      self._filter_loc):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self._search_box.clear()
        self._apply_filters()


# ── Row enrichment ────────────────────────────────────────────────────────────

def _enrich(row: dict) -> dict:
    r = dict(row)

    # Parse sec_effects JSON into separate columns
    raw = r.get("sec_effects", "[]")
    try:
        secs: list[str] = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except (ValueError, TypeError):
        secs = []
    r["sec1"] = secs[0] if len(secs) > 0 else ""
    r["sec2"] = secs[1] if len(secs) > 1 else ""
    r["sec3"] = secs[2] if len(secs) > 2 else ""

    # Human-readable quality
    rank = r.get("rank")
    r["quality"]      = _RANK_LABELS.get(rank, f"Rank {rank}" if rank else "—")
    r["quality_rank"] = rank   # keep raw for filtering

    r["locked_str"] = "🔒" if r.get("locked") else ""

    return r
