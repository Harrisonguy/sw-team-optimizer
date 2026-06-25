"""Account analytics panel."""
from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QProgressBar, QScrollArea, QPushButton, QSizePolicy, QGridLayout,
)

from desktop.db import queries
from desktop.ui.theme import BG_CARD, BORDER, TEXT_DIM, ACCENT


# ── Stat card ─────────────────────────────────────────────────────────────────

class _StatCard(QFrame):
    def __init__(self, value: str, label: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setStyleSheet(
            "QFrame#card {"
            "  background: " + BG_CARD + ";"
            "  border: 1px solid " + BORDER + ";"
            "  border-radius: 8px;"
            "}"
        )
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(140)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        self._val_lbl = QLabel(value)
        self._val_lbl.setFont(QFont("Segoe UI", 20, QFont.Bold))
        self._val_lbl.setStyleSheet("color: " + ACCENT + "; border: none;")
        self._val_lbl.setAlignment(Qt.AlignCenter)

        self._lbl = QLabel(label)
        self._lbl.setObjectName("subtitle")
        self._lbl.setFont(QFont("Segoe UI", 9))
        self._lbl.setStyleSheet("color: " + TEXT_DIM + "; border: none;")
        self._lbl.setAlignment(Qt.AlignCenter)

        layout.addWidget(self._val_lbl)
        layout.addWidget(self._lbl)

    def set_value(self, val: str) -> None:
        self._val_lbl.setText(val)

    def set_label(self, label: str) -> None:
        self._lbl.setText(label)


# ── Bar chart card ────────────────────────────────────────────────────────────

class _BarChart(QFrame):
    """Horizontal bar chart using QProgressBar rows."""

    def __init__(self, title: str, color: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("chart_card")
        self.setStyleSheet(
            "QFrame#chart_card {"
            "  background: " + BG_CARD + ";"
            "  border: 1px solid " + BORDER + ";"
            "  border-radius: 8px;"
            "}"
        )
        self._color = color

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)

        title_lbl = QLabel(title)
        title_lbl.setFont(QFont("Segoe UI", 11, QFont.Bold))
        title_lbl.setStyleSheet("color: #c9d1d9; border: none;")
        layout.addWidget(title_lbl)

        self._rows_layout = QVBoxLayout()
        self._rows_layout.setSpacing(5)
        layout.addLayout(self._rows_layout)

    def set_data(self, data: list[tuple[str, int]]) -> None:
        # Remove old rows
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not data:
            placeholder = QLabel("No data")
            placeholder.setStyleSheet("color: " + TEXT_DIM + "; border: none;")
            self._rows_layout.addWidget(placeholder)
            return

        max_val = max(v for _, v in data) or 1
        bar_style = (
            "QProgressBar {"
            "  background: #1c2128;"
            "  border: none;"
            "  border-radius: 3px;"
            "}"
            "QProgressBar::chunk {"
            "  background: " + self._color + ";"
            "  border-radius: 3px;"
            "}"
        )

        for label, val in data:
            row_w = QWidget()
            row_w.setStyleSheet("background: transparent;")
            row = QHBoxLayout(row_w)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)

            lbl = QLabel(label)
            lbl.setFixedWidth(100)
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl.setStyleSheet("color: #8b949e; border: none; font-size: 9pt;")
            row.addWidget(lbl)

            bar = QProgressBar()
            bar.setRange(0, max_val)
            bar.setValue(val)
            bar.setTextVisible(False)
            bar.setFixedHeight(16)
            bar.setStyleSheet(bar_style)
            row.addWidget(bar, 1)

            count_lbl = QLabel(str(val))
            count_lbl.setFixedWidth(52)
            count_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            count_lbl.setStyleSheet("color: #c9d1d9; border: none; font-size: 9pt;")
            row.addWidget(count_lbl)

            self._rows_layout.addWidget(row_w)


# ── Analytics widget ──────────────────────────────────────────────────────────

class _RecommendationPanel(QFrame):
    """Ranked actions with enough context to make each recommendation useful."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("recommendation_panel")
        self.setStyleSheet(
            "QFrame#recommendation_panel {"
            "  background: " + BG_CARD + ";"
            "  border: 1px solid " + BORDER + ";"
            "  border-radius: 8px;"
            "}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("Recommended Next Steps")
        title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        title.setStyleSheet("color: #c9d1d9; border: none;")
        layout.addWidget(title)

        self._rows = QVBoxLayout()
        self._rows.setSpacing(0)
        layout.addLayout(self._rows)

    def set_data(self, recommendations: list[dict]) -> None:
        while self._rows.count():
            item = self._rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not recommendations:
            label = QLabel("Import an account to create a personal progression plan.")
            label.setStyleSheet("color: " + TEXT_DIM + "; border: none;")
            self._rows.addWidget(label)
            return

        priority_colors = {"Now": "#f85149", "High": "#d29922", "Medium": "#58a6ff"}
        for index, recommendation in enumerate(recommendations[:6]):
            row_widget = QWidget()
            row_widget.setStyleSheet("background: transparent;")
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 8, 0, 8)
            row.setSpacing(12)

            priority = str(recommendation.get("priority", "Next"))
            badge = QLabel(priority)
            badge.setFixedSize(58, 24)
            badge.setAlignment(Qt.AlignCenter)
            badge.setStyleSheet(
                "color: " + priority_colors.get(priority, "#8b949e") + ";"
                "background: #1c2128; border: 1px solid " + BORDER + ";"
                "border-radius: 4px; font-weight: 600;"
            )
            row.addWidget(badge, 0, Qt.AlignTop)

            copy = QVBoxLayout()
            copy.setSpacing(2)
            heading = QLabel(str(recommendation.get("title", "Next step")))
            heading.setFont(QFont("Segoe UI", 10, QFont.Bold))
            heading.setStyleSheet("color: #c9d1d9; border: none;")
            detail = QLabel(
                str(recommendation.get("action", ""))
                + "  "
                + str(recommendation.get("reason", ""))
            )
            detail.setWordWrap(True)
            detail.setStyleSheet("color: " + TEXT_DIM + "; border: none;")
            copy.addWidget(heading)
            copy.addWidget(detail)
            row.addLayout(copy, 1)
            self._rows.addWidget(row_widget)

            if index < min(6, len(recommendations)) - 1:
                separator = QFrame()
                separator.setFrameShape(QFrame.HLine)
                separator.setStyleSheet("color: " + BORDER + ";")
                self._rows.addWidget(separator)


class AnalyticsWidget(QWidget):
    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self._conn = conn
        self._cards: list[_StatCard] = []
        self._charts: list[_BarChart] = []
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(16)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("Account Analytics")
        title.setObjectName("title")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        hdr.addWidget(title)
        hdr.addStretch()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setStyleSheet("QPushButton { padding: 6px 10px; }")
        refresh_btn.setFixedHeight(32)
        refresh_btn.clicked.connect(self.refresh)
        hdr.addWidget(refresh_btn)
        layout.addLayout(hdr)

        self._summary_lbl = QLabel("")
        self._summary_lbl.setWordWrap(True)
        self._summary_lbl.setStyleSheet("color: " + TEXT_DIM + ";")
        layout.addWidget(self._summary_lbl)

        # Stat cards row
        self._cards_layout = QHBoxLayout()
        self._cards_layout.setSpacing(10)
        layout.addLayout(self._cards_layout)

        card_specs = [
            ("--", "Account Strength"),
            ("--", "Rune Readiness"),
            ("--", "Speed P90"),
            ("--", "Grind Coverage"),
            ("--", "Weakest Core Set"),
            ("--", "Farm Next"),
        ]
        for val, lbl in card_specs:
            c = _StatCard(val, lbl)
            self._cards.append(c)
            self._cards_layout.addWidget(c)

        self._recommendations = _RecommendationPanel()
        layout.addWidget(self._recommendations)

        # Charts grid (2 columns)
        self._grid = QGridLayout()
        self._grid.setSpacing(12)
        layout.addLayout(self._grid)

        chart_specs = [
            ("Farming Priority",   "#e94560"),
            ("Core Set Quality",   "#4CAF50"),
            ("Rune Grades",        "#2196F3"),
            ("Efficiency Dist.",   "#9C27B0"),
            ("Top Rune Sets",      "#FF9800"),
            ("Rune Stars",         "#00BCD4"),
            ("Monster Elements",   "#d29922"),
            ("Artifact Quality",   "#58a6ff"),
        ]
        for idx, (title_text, color) in enumerate(chart_specs):
            chart = _BarChart(title_text, color)
            self._charts.append(chart)
            self._grid.addWidget(chart, idx // 2, idx % 2)

        layout.addStretch()

    def refresh(self) -> None:
        data = queries.get_analytics(self._conn)
        if not data:
            return

        progression = data.get("progression", {})
        speed = progression.get("speed", {})
        grinds = progression.get("grinds", {})
        weakest = progression.get("weakest_set", {})
        farming = progression.get("farming", [])
        farm_next = farming[0].get("dungeon", "--") if farming else "--"

        values = [
            ("%.0f" % progression.get("account_score", 0)) + "/100",
            ("%.0f" % progression.get("rune_score", 0)) + "/100",
            str(speed.get("p90", 0)),
            ("%.0f" % grinds.get("coverage_pct", 0)) + "%",
            weakest.get("set_name", "--"),
            farm_next,
        ]
        labels = [
            "Account Strength - " + progression.get("account_tier", "Developing"),
            "Rune Readiness",
            "90th Percentile SPD",
            "Grind Coverage",
            "Weakest Core Set",
            "Farm Next",
        ]
        for card, value, label in zip(self._cards, values, labels):
            card.set_value(value)
            card.set_label(label)

        self._summary_lbl.setText(
            str(data.get("total_runes", 0)) + " runes, "
            + str(data.get("total_monsters", 0)) + " monsters, and "
            + str(data.get("total_artifacts", 0)) + " artifacts analyzed. "
            + "Scores are inventory-readiness estimates, not player rankings."
        )
        self._recommendations.set_data(progression.get("recommendations", []))

        farming_data = [
            (row.get("dungeon", ""), int(round(row.get("priority", 0))))
            for row in farming
        ]
        chart_data = [
            farming_data,
            progression.get("core_set_quality", []),
            data.get("grades", []),
            data.get("efficiency", []),
            data.get("sets", []),
            data.get("stars", []),
            data.get("elements", []),
            data.get("artifact_quality", []),
        ]
        for chart, chart_rows in zip(self._charts, chart_data):
            chart.set_data(chart_rows)
