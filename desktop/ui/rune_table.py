"""Rune inventory viewer widget."""
from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QComboBox, QPushButton, QCheckBox,
    QTableView, QAbstractItemView, QFrame,
    QSizePolicy, QHeaderView, QMenu,
)

from desktop.db import queries
from desktop.models.rune_model import RuneTableModel, RuneSortProxy
from desktop.ui.theme import BG_CARD, BORDER, TEXT_DIM

# Ordered list of substat type names shown in the filter dropdown
_SUBSTAT_OPTIONS = [
    "SPD", "CR", "CD",
    "ATK%", "HP%", "DEF%",
    "ACC", "RES",
    "Flat ATK", "Flat HP", "Flat DEF",
]


class RuneTableWidget(QWidget):
    """
    Full rune inventory panel with filter bar, sortable table, and row count.
    Call ``refresh()`` after a new import.
    Right-click any row to lock / unlock it (excluded from optimizer pool when locked).
    """

    def __init__(self, conn: sqlite3.Connection, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._conn = conn
        self._build_ui()
        self._connect_signals()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Title row
        title_row = QHBoxLayout()
        lbl = QLabel("Rune Inventory")
        lbl.setObjectName("title")
        title_row.addWidget(lbl)
        title_row.addStretch()
        self._count_label = QLabel("0 runes")
        self._count_label.setObjectName("subtitle")
        title_row.addWidget(self._count_label)
        root.addLayout(title_row)

        # Filter bar (two rows)
        root.addWidget(self._build_filter_bar())

        # Table backed by source model + sort proxy
        self._model = RuneTableModel(self)
        self._proxy = RuneSortProxy(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortCaseSensitivity(Qt.CaseInsensitive)

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setSortingEnabled(True)
        self._table.sortByColumn(9, Qt.DescendingOrder)   # default: sort by Desr%
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)

        # Right-click context menu
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)

        root.addWidget(self._table)

        # Default column widths
        # Col 12 = Lock (new, narrow), col 13 = Location (stretch-last)
        for col, width in {
            0: 50, 1: 100, 2: 40,  3: 50,
            4: 90, 5: 50,  6: 120, 7: 310,
            8: 55, 9: 55,  10: 55, 11: 80,
            12: 46,
        }.items():
            self._table.setColumnWidth(col, width)

        # Debounce timer for text search
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
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(6)

        # ── Row 1: set / slot / stars / main / grade / location ──────────────
        row1 = QHBoxLayout()
        row1.setSpacing(8)

        def combo(placeholder: str, fixed_width: int, items: list[str] = []) -> QComboBox:
            c = QComboBox()
            c.addItem(placeholder, None)
            for it in items:
                c.addItem(it, it)
            c.setFixedWidth(fixed_width)
            return c

        self._filter_slot  = combo("All Slots",      100, ["1","2","3","4","5","6"])
        self._filter_set   = combo("All Sets",        130)
        self._filter_stars = combo("All ★",            90, ["4★","5★","6★"])
        self._filter_main  = combo("Any Main",        120)
        self._filter_grade = combo("All Grades",      105, ["S","A","B","C","D"])
        self._filter_loc   = combo("All Locations",   130, ["Equipped","Storage"])

        for lbl_text, widget in [
            ("Slot:",     self._filter_slot),
            ("Set:",      self._filter_set),
            ("Stars:",    self._filter_stars),
            ("Main:",     self._filter_main),
            ("Grade:",    self._filter_grade),
            ("Location:", self._filter_loc),
        ]:
            row1.addWidget(QLabel(lbl_text))
            row1.addWidget(widget)
        row1.addStretch()
        outer.addLayout(row1)

        # ── Row 2: substat / search / hide-locked / reset ────────────────────
        row2 = QHBoxLayout()
        row2.setSpacing(8)

        self._filter_sub = combo("Any Substat", 130, _SUBSTAT_OPTIONS)
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search name, set, substat…")
        self._search_box.setClearButtonEnabled(True)
        self._search_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._hide_locked_chk = QCheckBox("Hide locked")
        self._hide_locked_chk.setToolTip(
            "Hide runes you've locked (right-click a row to lock/unlock).\n"
            "Locked runes are automatically excluded from the optimizer."
        )

        self._reset_btn = QPushButton("Reset")
        self._reset_btn.setStyleSheet(
            f"QPushButton {{ color: {TEXT_DIM}; padding: 4px 8px; }}")

        row2.addWidget(QLabel("Substat:"))
        row2.addWidget(self._filter_sub)
        row2.addWidget(self._search_box)
        row2.addWidget(self._hide_locked_chk)
        row2.addWidget(self._reset_btn)
        outer.addLayout(row2)

        return bar

    # ── Signals ───────────────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        for combo in (self._filter_slot, self._filter_set, self._filter_stars,
                      self._filter_main, self._filter_sub,
                      self._filter_grade, self._filter_loc):
            combo.currentIndexChanged.connect(self._apply_filters)
        self._search_box.textChanged.connect(self._search_timer.start)
        self._hide_locked_chk.toggled.connect(self._on_hide_locked_toggled)
        self._reset_btn.clicked.connect(self._reset_filters)

    # ── Public ────────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Reload filter options and rune data from the database."""
        sets       = queries.get_distinct_sets(self._conn)
        main_stats = queries.get_distinct_main_stats(self._conn)

        def repopulate(combo: QComboBox, items: list[str], placeholder: str) -> None:
            old = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(placeholder, None)
            for it in items:
                combo.addItem(it, it)
            idx = combo.findData(old)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.blockSignals(False)

        repopulate(self._filter_set,  sets,       "All Sets")
        repopulate(self._filter_main, main_stats, "Any Main")
        self._apply_filters()

    # ── Private ───────────────────────────────────────────────────────────────

    def _apply_filters(self) -> None:
        slot_val  = self._filter_slot.currentData()
        set_val   = self._filter_set.currentData()
        stars_val = self._filter_stars.currentData()
        main_val  = self._filter_main.currentData()
        sub_val   = self._filter_sub.currentData()
        grade_val = self._filter_grade.currentData()
        loc_val   = self._filter_loc.currentData()
        search    = self._search_box.text().strip()

        stars_int: int | None = None
        if stars_val:
            try:
                stars_int = int(str(stars_val).replace("★", ""))
            except ValueError:
                pass

        slot_int: int | None = None
        if slot_val:
            try:
                slot_int = int(slot_val)
            except ValueError:
                pass

        loc_key = {"Equipped": "equipped", "Storage": "storage"}.get(loc_val or "", None)

        rows = queries.get_runes(
            self._conn,
            slot     = slot_int,
            set_name = set_val,
            stars    = stars_int,
            main_stat= main_val,
            substat  = sub_val,
            grade    = grade_val,
            location = loc_key,
            search   = search,
        )

        self._model.set_runes(rows)
        self._update_count()

    def _update_count(self) -> None:
        total  = self._model.rowCount()
        locked = sum(
            1 for i in range(total)
            if (self._model.row_data(i) or {}).get("user_locked")
        )
        shown = self._proxy.rowCount()
        if locked:
            self._count_label.setText(
                f"{shown:,} shown  ({total:,} total, {locked:,} locked)"
            )
        else:
            self._count_label.setText(f"{shown:,} runes")

    def _on_hide_locked_toggled(self, checked: bool) -> None:
        self._proxy.set_hide_locked(checked)
        self._update_count()

    def _reset_filters(self) -> None:
        for combo in (self._filter_slot, self._filter_set, self._filter_stars,
                      self._filter_main, self._filter_sub,
                      self._filter_grade, self._filter_loc):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self._search_box.clear()
        self._hide_locked_chk.setChecked(False)
        self._apply_filters()

    # ── Context menu (right-click to lock/unlock) ─────────────────────────────

    def _on_context_menu(self, pos) -> None:
        proxy_index = self._table.indexAt(pos)
        if not proxy_index.isValid():
            return

        # Map to source model row
        source_index = self._proxy.mapToSource(proxy_index)
        source_row   = source_index.row()
        rune         = self._model.row_data(source_row)
        if not rune:
            return

        rune_id = rune.get("rune_id")
        locked  = bool(rune.get("user_locked"))

        menu = QMenu(self)
        if locked:
            action = menu.addAction("Unlock rune  (include in optimizer)")
        else:
            action = menu.addAction("Lock rune  (exclude from optimizer)")

        chosen = menu.exec(self._table.viewport().mapToGlobal(pos))
        if chosen is None or chosen != action:
            return

        # Persist the change
        if rune_id is not None:
            queries.set_rune_locked(self._conn, rune_id, not locked)

        # Update the in-memory model without a full reload
        new_locked = self._model.toggle_lock_at(source_row)

        # Update count badge
        self._update_count()
