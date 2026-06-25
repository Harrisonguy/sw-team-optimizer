"""Sell Analysis panel — sell candidates + SW exclusion rules."""
from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QTabWidget, QComboBox, QPushButton, QSizePolicy,
    QScrollArea, QTableView, QAbstractItemView, QHeaderView,
)

from desktop.db import queries
from desktop.models.rune_model import RuneTableModel, RuneSortProxy
from desktop.ui.theme import BG_CARD, BORDER, TEXT_DIM, ACCENT

# Approximate mana per sell by star count
_MANA = {1: 1500, 2: 2500, 3: 5000, 4: 10000, 5: 22000, 6: 45000}

_GRADE_OPTIONS = ["D", "C", "B", "A", "S"]
_STAR_OPTIONS  = [("4+", 4), ("5+", 5), ("6", 6)]
_LVL_OPTIONS   = [("Any", 15), ("+9 or less", 9), ("+6 or less", 6), ("+3 or less", 3), ("Unleveled", 0)]
_LOC_OPTIONS   = [("Storage only", True), ("All (incl. equipped)", False)]


# ── Exclusion rule card ───────────────────────────────────────────────────────

class _RuleCard(QFrame):
    def __init__(self, rule: dict, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("rule_card")
        self.setStyleSheet(
            "QFrame#rule_card {"
            "  background: " + BG_CARD + ";"
            "  border: 1px solid " + BORDER + ";"
            "  border-radius: 8px;"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(6)

        # Header row
        hdr = QHBoxLayout()
        tab_lbl = QLabel("Tab " + str(rule["tab"]))
        tab_lbl.setStyleSheet(
            "background: " + ACCENT + ";"
            " color: white; border-radius: 4px;"
            " padding: 2px 8px; font-weight: bold;"
            " border: none;"
        )
        tab_lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
        tab_lbl.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        name_lbl = QLabel(rule["name"])
        name_lbl.setFont(QFont("Segoe UI", 12, QFont.Bold))
        name_lbl.setStyleSheet("color: #c9d1d9; border: none;")

        hdr.addWidget(tab_lbl)
        hdr.addSpacing(10)
        hdr.addWidget(name_lbl)
        hdr.addStretch()
        layout.addLayout(hdr)

        desc_lbl = QLabel(rule["description"])
        desc_lbl.setStyleSheet("color: " + TEXT_DIM + "; border: none;")
        desc_lbl.setFont(QFont("Segoe UI", 9))
        layout.addWidget(desc_lbl)

        keep_lbl = QLabel(
            "Keep rune if it has "
            + str(rule["subs_needed"])
            + "+ of these substats:"
        )
        keep_lbl.setStyleSheet("color: #8b949e; border: none;")
        keep_lbl.setFont(QFont("Segoe UI", 9))
        layout.addWidget(keep_lbl)

        for cond in rule["conditions"]:
            row = QHBoxLayout()
            bullet = QLabel("●")
            bullet.setStyleSheet("color: " + ACCENT + "; border: none;")
            bullet.setFixedWidth(16)
            cond_lbl = QLabel(cond["label"])
            cond_lbl.setStyleSheet("color: #c9d1d9; border: none;")
            cond_lbl.setFont(QFont("Segoe UI", 10))
            row.addWidget(bullet)
            row.addWidget(cond_lbl)
            row.addStretch()
            layout.addLayout(row)


# ── Main widget ───────────────────────────────────────────────────────────────

class SellAnalysisWidget(QWidget):
    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self._conn = conn
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Title row
        hdr = QHBoxLayout()
        title = QLabel("Sell Analysis")
        title.setObjectName("title")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        hdr.addWidget(title)
        hdr.addStretch()
        recalc_btn = QPushButton("Recalculate")
        recalc_btn.setFixedHeight(32)
        recalc_btn.clicked.connect(self.refresh)
        hdr.addWidget(recalc_btn)
        root.addLayout(hdr)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_candidates_tab(), "Sell Candidates")
        self._tabs.addTab(self._build_rules_tab(),      "Exclusion Rules")
        root.addWidget(self._tabs)

    # ── Sell candidates tab ───────────────────────────────────────────────────

    def _build_candidates_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(self._build_filter_bar())

        self._rune_model = RuneTableModel(self)
        self._proxy      = RuneSortProxy(self)
        self._proxy.setSourceModel(self._rune_model)
        self._proxy.setSortCaseSensitivity(Qt.CaseInsensitive)

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setSortingEnabled(True)
        self._table.sortByColumn(9, Qt.AscendingOrder)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.setShowGrid(False)
        # col 12 (Location) is the stretch-last column; set explicit widths for 0-11
        for col, w_ in {0:50, 1:100, 2:40, 3:45, 4:90, 5:55,
                        6:80, 7:200, 8:65, 9:65, 10:60, 11:80}.items():
            self._table.setColumnWidth(col, w_)
        layout.addWidget(self._table)

        self._status_lbl = QLabel("")
        self._status_lbl.setObjectName("subtitle")
        self._status_lbl.setStyleSheet("color: " + TEXT_DIM + ";")
        layout.addWidget(self._status_lbl)

        self._unleveled_lbl = QLabel("")
        self._unleveled_lbl.setObjectName("subtitle")
        self._unleveled_lbl.setStyleSheet(
            "color: #e6a817;"
            " background: rgba(230,168,23,0.10);"
            " border: 1px solid rgba(230,168,23,0.30);"
            " border-radius: 4px; padding: 3px 8px;"
        )
        self._unleveled_lbl.setWordWrap(True)
        self._unleveled_lbl.setVisible(False)
        layout.addWidget(self._unleveled_lbl)

        self._below_bar_lbl = QLabel("")
        self._below_bar_lbl.setObjectName("subtitle")
        self._below_bar_lbl.setStyleSheet(
            "color: #e05c5c;"
            " background: rgba(220,80,80,0.08);"
            " border: 1px solid rgba(220,80,80,0.25);"
            " border-radius: 4px; padding: 3px 8px;"
        )
        self._below_bar_lbl.setWordWrap(True)
        self._below_bar_lbl.setVisible(False)
        layout.addWidget(self._below_bar_lbl)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._apply_filters)

        return w

    def _build_filter_bar(self) -> QFrame:
        bar = QFrame()
        bar.setFrameShape(QFrame.StyledPanel)
        bar.setStyleSheet(
            "background-color: " + BG_CARD + ";"
            " border: 1px solid " + BORDER + ";"
            " border-radius: 6px;"
        )
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        def combo(w, items):
            c = QComboBox()
            c.setFixedWidth(w)
            for label, data in items:
                c.addItem(label, data)
            return c

        self._grade_combo = combo(80,  [(g, g) for g in _GRADE_OPTIONS])
        self._grade_combo.setCurrentIndex(1)   # default: ≤ C

        self._stars_combo = combo(60,  _STAR_OPTIONS)
        self._stars_combo.setCurrentIndex(1)   # default: 5+

        self._lvl_combo   = combo(120, _LVL_OPTIONS)
        self._lvl_combo.setCurrentIndex(1)     # default: +9 or less

        self._loc_combo   = combo(160, _LOC_OPTIONS)

        for lbl_text, widget in [
            ("Grade ≤", self._grade_combo),
            ("Stars",   self._stars_combo),
            ("Max Lvl", self._lvl_combo),
            ("Location", self._loc_combo),
        ]:
            layout.addWidget(QLabel(lbl_text))
            layout.addWidget(widget)
        layout.addStretch()

        reset_btn = QPushButton("Reset")
        reset_btn.setStyleSheet(
            "QPushButton { color: " + TEXT_DIM + "; padding: 4px 8px; }")
        reset_btn.clicked.connect(self._reset_filters)
        layout.addWidget(reset_btn)
        return bar

    def _connect_filter_signals(self) -> None:
        for c in (self._grade_combo, self._stars_combo,
                  self._lvl_combo, self._loc_combo):
            c.currentIndexChanged.connect(self._apply_filters)

    def _apply_filters(self) -> None:
        grade     = self._grade_combo.currentData()
        min_stars = self._stars_combo.currentData()
        max_lvl   = self._lvl_combo.currentData()
        storage   = self._loc_combo.currentData()

        rows = queries.get_sell_candidates_db(
            self._conn,
            grade_threshold  = grade,
            min_stars        = min_stars,
            max_upgrade      = max_lvl,
            storage_only     = storage,
            exclude_unleveled = True,
        )

        # Annotate each row with projected_desr and below_bar flag
        queries.annotate_sell_potential(
            self._conn, rows, min_stars=min_stars
        )

        self._rune_model.set_runes(rows)

        total_mana = sum(_MANA.get(r.get("stars") or 0, 0) for r in rows)
        if total_mana >= 1_000_000:
            mana_str = "~%.1fM mana" % (total_mana / 1_000_000)
        else:
            mana_str = "~%dK mana" % (total_mana // 1000)

        below_bar = sum(1 for r in rows if r.get("below_bar"))
        status_parts = [str(len(rows)) + " sell candidates", mana_str + " if all sold"]
        if below_bar:
            status_parts.append(str(below_bar) + " below account bar")
        self._status_lbl.setText("  •  ".join(status_parts))

        # Show runes excluded because too few substats are visible to judge
        # (per the SW rarity table: Rare/Magic/Normal need +9 for 3 of 4 subs)
        hidden = queries.count_under_evaluated(
            self._conn,
            grade_threshold = grade,
            min_stars       = min_stars,
            storage_only    = storage,
        )
        if hidden > 0:
            self._unleveled_lbl.setText(
                "⚠  " + str(hidden) + " Rare / Magic / Normal rune"
                + ("s" if hidden != 1 else "")
                + " hidden (below +9). At +0 to +6 fewer than 3 of 4 substats are visible,"
                " so a sell recommendation would be unreliable."
                " Level to +9 to evaluate. Legend and Hero runes are always shown."
            )
            self._unleveled_lbl.setVisible(True)
        else:
            self._unleveled_lbl.setVisible(False)

        # Below-bar banner: runes whose projected max at +15 < account 35th percentile
        if below_bar:
            self._below_bar_lbl.setText(
                "⬇  " + str(below_bar) + " rune"
                + ("s" if below_bar != 1 else "")
                + " flagged below account bar -- even at +15 with optimal rolls"
                " they cannot reach the 35th percentile of your storage runes."
                " Strong sell signal regardless of current grade."
            )
            self._below_bar_lbl.setVisible(True)
        else:
            self._below_bar_lbl.setVisible(False)

    def _reset_filters(self) -> None:
        self._grade_combo.setCurrentIndex(1)
        self._stars_combo.setCurrentIndex(1)
        self._lvl_combo.setCurrentIndex(1)
        self._loc_combo.setCurrentIndex(0)
        self._apply_filters()

    # ── Exclusion rules tab ───────────────────────────────────────────────────

    def _build_rules_tab(self) -> QWidget:
        outer = QWidget()
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(0, 8, 0, 0)

        intro = QLabel(
            "Enter these settings in Summoners War under  "
            "Inventory → Runes → Sell → Exclusion Settings.\n"
            "Each rule protects runes that have 2+ matching substats."
        )
        intro.setObjectName("subtitle")
        intro.setStyleSheet("color: " + TEXT_DIM + ";")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(scroll)

        self._rules_container = QWidget()
        self._rules_layout    = QVBoxLayout(self._rules_container)
        self._rules_layout.setSpacing(10)
        self._rules_layout.addStretch()
        scroll.setWidget(self._rules_container)

        return outer

    def _refresh_rules(self) -> None:
        # Remove old cards (but keep the trailing stretch)
        while self._rules_layout.count() > 1:
            item = self._rules_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        rules = queries.compute_exclusion_rules(self._conn)
        for i, rule in enumerate(rules):
            self._rules_layout.insertWidget(i, _RuleCard(rule))

    # ── Public API ────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        self._apply_filters()
        self._refresh_rules()

    def showEvent(self, event) -> None:
        """Wire filter signals lazily on first show (avoids signal fire during build)."""
        super().showEvent(event)
        if not getattr(self, "_signals_connected", False):
            self._connect_filter_signals()
            self._signals_connected = True

        if below_bar:
            self._below_bar_lbl.setText(
                "⬇  " + str(below_bar) + " rune"
                + ("s" if below_bar != 1 else "")
                + " flagged below account bar -- even at +15 with optimal rolls"
                " they cannot reach the 35th percentile of your storage runes."
                " Strong sell signal regardless of current grade."
            )
            self._below_bar_lbl.setVisible(True)
        else:
            self._below_bar_lbl.setVisible(False)

    def _reset_filters(self) -> None:
        self._grade_combo.setCurrentIndex(1)
        self._stars_combo.setCurrentIndex(1)
        self._lvl_combo.setCurrentIndex(1)
        self._loc_combo.setCurrentIndex(0)
        self._apply_filters()

    # ---- Exclusion rules tab ────────────────────────────────────────────────

    def _build_rules_tab(self) -> QWidget:
        outer = QWidget()
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(0, 8, 0, 0)

        intro = QLabel(
            "Enter these settings in Summoners War under  "
            "Inventory -> Runes -> Sell -> Exclusion Settings.\n"
            "Each rule protects runes that have 2+ matching substats."
        )
        intro.setObjectName("subtitle")
        intro.setStyleSheet("color: " + TEXT_DIM + ";")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(scroll)

        self._rules_container = QWidget()
        self._rules_layout    = QVBoxLayout(self._rules_container)
        self._rules_layout.setSpacing(10)
        self._rules_layout.addStretch()
        scroll.setWidget(self._rules_container)

        return outer

    def _refresh_rules(self) -> None:
        # Remove old cards (but keep the trailing stretch)
        while self._rules_layout.count() > 1:
            item = self._rules_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        rules = queries.compute_exclusion_rules(self._conn)
        for i, rule in enumerate(rules):
            self._rules_layout.insertWidget(i, _RuleCard(rule))

    # ---- Public API ─────────────────────────────────────────────────────────

    def refresh(self) -> None:
        self._apply_filters()
        self._refresh_rules()

    def showEvent(self, event) -> None:
        """Wire filter signals lazily on first show (avoids signal fire during build)."""
        super().showEvent(event)
        if not getattr(self, "_signals_connected", False):
            self._connect_filter_signals()
            self._signals_connected = True
