"""Monster roster viewer widget -- sortable table + build detail panel."""
from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTableView, QAbstractItemView, QHeaderView, QSizePolicy,
    QSplitter,
)

from desktop.db import queries
from desktop.ui.theme import ELEMENT_COLORS
from desktop.ui.monster_build import MonsterBuildPanel


# ---- Columns ----------------------------------------------------------------

_COLS = [
    ("display_name",    "Monster"),
    ("element",         "Element"),
    ("archetype",       "Type"),
    ("natural_stars",   "Nat★"),
    ("stars",           "★"),
    ("level",           "Lvl"),
    ("max_lvl_hp",      "HP"),
    ("max_lvl_attack",  "ATK"),
    ("max_lvl_defense", "DEF"),
    ("base_speed",      "SPD"),
    ("crit_rate",       "CR%"),
    ("crit_damage",     "CD%"),
    ("resistance",      "RES%"),
    ("accuracy",        "ACC%"),
]

_NUM_COLS: set[int] = {3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13}


# ---- Table model ------------------------------------------------------------

class MonsterTableModel(QAbstractTableModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[dict] = []

    def set_monsters(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = rows
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
            return "—" if val is None else str(val)

        if role == Qt.UserRole:
            if col in _NUM_COLS:
                try:
                    return float(row.get(key) or 0)
                except (ValueError, TypeError):
                    return 0.0
            return row

        if role == Qt.ForegroundRole and key == "element":
            color = ELEMENT_COLORS.get(row.get("element", ""))
            if color:
                return QColor(color)

        if role == Qt.TextAlignmentRole and key != "display_name":
            return Qt.AlignCenter

        return None

    def get_row(self, visual_row: int) -> dict | None:
        if 0 <= visual_row < len(self._rows):
            return self._rows[visual_row]
        return None


class MonsterSortProxy(QSortFilterProxyModel):
    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        col = left.column()
        if col in _NUM_COLS:
            lv = self.sourceModel().data(left,  Qt.UserRole)
            rv = self.sourceModel().data(right, Qt.UserRole)
            try:
                return float(lv or 0) < float(rv or 0)
            except (ValueError, TypeError):
                pass
        return super().lessThan(left, right)


# ---- Widget -----------------------------------------------------------------

class MonsterRosterWidget(QWidget):
    """
    Split-pane monster browser.
    Left: sortable roster table with search.
    Right: MonsterBuildPanel showing equipped runes + storage upgrades.
    """

    def __init__(self, conn: sqlite3.Connection, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._conn = conn
        self._build_ui()
        self._connect_signals()

    # ---- Build UI -----------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Title row
        hdr = QHBoxLayout()
        lbl = QLabel("Monster Roster")
        lbl.setObjectName("title")
        lbl.setFont(QFont("Segoe UI", 16, QFont.Bold))
        hdr.addWidget(lbl)
        hdr.addStretch()
        self._count_lbl = QLabel("0 monsters")
        self._count_lbl.setObjectName("subtitle")
        hdr.addWidget(self._count_lbl)
        root.addLayout(hdr)

        # Main splitter: left = roster list, right = build detail
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(6)
        splitter.setChildrenCollapsible(False)

        # ---- Left panel: search + table ------------------------------------
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search name, element, type...")
        self._search.setClearButtonEnabled(True)
        self._search.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        search_row.addWidget(QLabel("Search:"))
        search_row.addWidget(self._search)
        left_layout.addLayout(search_row)

        self._model = MonsterTableModel(self)
        self._proxy = MonsterSortProxy(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortCaseSensitivity(Qt.CaseInsensitive)

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setSortingEnabled(True)
        self._table.sortByColumn(0, Qt.AscendingOrder)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)
        # fixed widths for non-stretch columns
        for col, w in {0: 160, 1: 70, 2: 80, 3: 40, 4: 35, 5: 40,
                       6: 65, 7: 60, 8: 60, 9: 45, 10: 40, 11: 40, 12: 40}.items():
            self._table.setColumnWidth(col, w)
        left_layout.addWidget(self._table)

        splitter.addWidget(left)

        # ---- Right panel: monster build detail -----------------------------
        self._build_panel = MonsterBuildPanel(self._conn)
        splitter.addWidget(self._build_panel)

        # Give roster ~40% and build panel ~60% of the space
        splitter.setSizes([420, 580])

        root.addWidget(splitter, 1)

    # ---- Signals ------------------------------------------------------------

    def _connect_signals(self) -> None:
        self._search.textChanged.connect(self._apply_search)
        self._table.selectionModel().currentRowChanged.connect(self._on_row_changed)

    def _apply_search(self, text: str) -> None:
        rows = queries.get_monsters(self._conn, search=text.strip())
        self._model.set_monsters(rows)
        self._count_lbl.setText(str(len(rows)) + " monsters")
        # clear build panel when the list changes (selection will re-trigger)
        self._build_panel.clear()

    def _on_row_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if not current.isValid():
            self._build_panel.clear()
            return
        # Map proxy row -> source row -> dict
        source_idx = self._proxy.mapToSource(current)
        monster = self._model.get_row(source_idx.row())
        if monster:
            self._build_panel.show_monster(monster)
        else:
            self._build_panel.clear()

    # ---- Public API ---------------------------------------------------------

    def refresh(self) -> None:
        """Reload monster data from the database."""
        rows = queries.get_monsters(self._conn)
        self._model.set_monsters(rows)
        self._count_lbl.setText(str(len(rows)) + " monsters")
        self._build_panel.clear()
