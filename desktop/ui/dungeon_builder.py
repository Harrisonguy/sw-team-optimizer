"""Dungeon Builder panel.

Shows wave-by-wave enemy stats for any imported dungeon, with
per-wave stat breakdowns, boss highlight, and ACC/SPD threshold indicators.
"""
from __future__ import annotations

import sqlite3

from PySide6.QtCore    import Qt, QSortFilterProxyModel
from PySide6.QtGui     import QFont, QColor, QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QComboBox, QFrame, QScrollArea, QSplitter, QGridLayout,
    QSizePolicy, QSpacerItem, QTableView, QHeaderView,
    QAbstractItemView, QLineEdit, QGroupBox, QDoubleSpinBox,
    QSpinBox, QCheckBox,
)

from desktop.db import queries
from optimizer.artifact_optimizer import ArtifactProfile
from optimizer.damage_calculator import (
    DamageContext,
    SkillScaling,
    UnitStats,
    WaveDamageResult,
    analyze_waves,
)
from optimizer.dungeon_profiles import DUNGEON_PROFILES

TEXT_DIM  = "#8b949e"
TEXT_MAIN = "#c9d1d9"
BG_CARD   = "#161b22"
BG_PANEL  = "#0d1117"

# Stat display columns
_COLS = ["Monster", "Lv", "HP", "ATK", "DEF", "SPD", "RES%", "ACC%", "CR%", "CDmg Red%"]
_COL_IDX = {c: i for i, c in enumerate(_COLS)}


def _pct_label(val: int, warn: int, danger: int) -> tuple[str, str]:
    """(text, color) based on threshold."""
    if val >= danger:
        return str(val) + "%", "#e05c5c"
    if val >= warn:
        return str(val) + "%", "#e8c84a"
    return str(val) + "%", "#4caf72"


class _WaveCard(QGroupBox):
    """One collapsible wave showing a table of enemy stats."""

    def __init__(
        self,
        wave_number: int,
        monsters: list[dict],
        is_boss_wave: bool,
        damage_result: WaveDamageResult | None = None,
        parent=None,
    ):
        label = ("Wave " + str(wave_number)
                 + ("  ⚔  Boss Wave" if is_boss_wave else ""))
        super().__init__(label, parent)
        self._is_boss = is_boss_wave
        self._build_ui(monsters, damage_result)
        if is_boss_wave:
            self.setStyleSheet(
                "QGroupBox { border: 1px solid rgba(232,200,74,0.35);"
                " border-radius:6px; margin-top:10px; font-weight:bold;"
                " color: #e8c84a; }"
                "QGroupBox::title { padding: 0 4px; }"
                "QLabel { border:none; }"
            )

    def _build_ui(
        self,
        monsters: list[dict],
        damage_result: WaveDamageResult | None,
    ):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 14, 6, 6)
        layout.setSpacing(4)

        grid = QGridLayout()
        grid.setSpacing(2)

        headers = list(_COLS)
        if damage_result is not None:
            headers.extend(["Skill Dmg", "KO"])
        for col, h in enumerate(headers):
            lbl = QLabel(h)
            lbl.setFont(QFont("Segoe UI", 7, QFont.Bold))
            lbl.setStyleSheet("color: " + TEXT_DIM + ";")
            lbl.setAlignment(Qt.AlignCenter if col > 0 else Qt.AlignLeft)
            grid.addWidget(lbl, 0, col)

        for row_i, m in enumerate(monsters, 1):
            is_boss_row = self._is_boss and row_i == len(monsters)
            row_color = "#e8c84a" if is_boss_row else TEXT_MAIN

            def cell(text, align=Qt.AlignCenter, color=row_color, bold=False):
                l = QLabel(str(text))
                l.setFont(QFont("Segoe UI", 7, QFont.Bold if (bold or is_boss_row) else QFont.Normal))
                l.setStyleSheet("color: " + color + ";")
                l.setAlignment(align)
                return l

            spd = m.get('spd') or 0
            res = m.get('res') or 0
            acc = m.get('acc') or 0
            cr  = m.get('cr')  or 0
            cdmg = m.get('cdmg_reduction') or 0
            hp  = m.get('hp')  or 0
            atk = m.get('atk') or 0
            defv = m.get('def') or 0
            lv  = m.get('level') or 0
            name = m.get('monster_name') or '?'

            _, spd_color = _pct_label(spd, 150, 170)
            _, res_color = _pct_label(res, 40, 70)

            grid.addWidget(cell(name,  Qt.AlignLeft), row_i, 0)
            grid.addWidget(cell(lv),                  row_i, 1)
            grid.addWidget(cell(f"{hp:,}"),           row_i, 2)
            grid.addWidget(cell(f"{atk:,}"),          row_i, 3)
            grid.addWidget(cell(f"{defv:,}"),         row_i, 4)
            grid.addWidget(cell(spd, color=spd_color if spd >= 150 else row_color), row_i, 5)
            grid.addWidget(cell(str(res) + "%", color=res_color if res >= 40 else row_color), row_i, 6)
            grid.addWidget(cell(str(acc) + "%"), row_i, 7)
            grid.addWidget(cell(str(cr)  + "%"), row_i, 8)
            grid.addWidget(cell(str(cdmg) + "%"), row_i, 9)

            if damage_result is not None and row_i <= len(damage_result.enemies):
                enemy_result = damage_result.enemies[row_i - 1]
                ko_color = "#3fb950" if enemy_result.one_shot else "#e05c5c"
                grid.addWidget(cell(f"{enemy_result.damage:,}"), row_i, 10)
                grid.addWidget(
                    cell("YES" if enemy_result.one_shot else "NO", color=ko_color, bold=True),
                    row_i,
                    11,
                )

        if damage_result is not None:
            total = len(damage_result.enemies)
            summary = QLabel(
                "One-shot: %d/%d enemies%s"
                % (
                    damage_result.defeated_count,
                    total,
                    " - wave clears" if damage_result.clears_wave else "",
                )
            )
            summary.setFont(QFont("Segoe UI", 8, QFont.Bold))
            summary.setStyleSheet(
                "color: %s;" % (
                    "#3fb950" if damage_result.clears_wave else "#e8c84a"
                )
            )
            layout.addWidget(summary)

        layout.addLayout(grid)


class _DungeonSummaryBar(QFrame):
    """Compact summary strip: max SPD, max RES, ACC needed."""

    def __init__(self, summary: dict, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "QFrame { background: " + BG_CARD + ";"
            " border: 1px solid #2d333b; border-radius:6px; }"
            "QLabel { border:none; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(24)

        max_spd = summary.get('max_spd') or 0
        max_res = summary.get('max_res') or 0
        max_acc = summary.get('max_acc') or 0
        total   = summary.get('total_monsters') or 0

        def stat_block(label: str, val: str, color: str):
            vbox = QVBoxLayout()
            vbox.setSpacing(1)
            lbl = QLabel(label)
            lbl.setFont(QFont("Segoe UI", 7))
            lbl.setStyleSheet("color: " + TEXT_DIM + ";")
            val_lbl = QLabel(val)
            val_lbl.setFont(QFont("Segoe UI", 11, QFont.Bold))
            val_lbl.setStyleSheet("color: " + color + ";")
            vbox.addWidget(lbl)
            vbox.addWidget(val_lbl)
            return vbox

        _, spd_color = _pct_label(max_spd, 150, 170)
        _, res_color = _pct_label(max_res, 40, 70)
        acc_needed = max_res  # team debuffers should hit >= this
        _, acc_color = _pct_label(acc_needed, 40, 70)

        layout.addLayout(stat_block("Max Enemy SPD", str(max_spd), spd_color))
        layout.addLayout(stat_block("Max Enemy RES", str(max_res) + "%", res_color))
        layout.addLayout(stat_block("ACC Target", str(acc_needed) + "%", acc_color))
        layout.addLayout(stat_block("Max Enemy ACC", str(max_acc) + "%", TEXT_DIM))
        layout.addLayout(stat_block("Total Enemies", str(total), TEXT_DIM))

        # Team SPD hint
        team_spd = max_spd + 5 if max_spd else 0
        if team_spd:
            layout.addSpacerItem(QSpacerItem(20, 0, QSizePolicy.Fixed))
            hint = QLabel("→ Team SPD goal: " + str(team_spd) + "+  |  ACC goal: " + str(acc_needed) + "%+")
            hint.setFont(QFont("Segoe UI", 8))
            hint.setStyleSheet("color: #3fb950;")
            layout.addWidget(hint)

        layout.addStretch()


class DungeonBuilderWidget(QWidget):
    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._damage_results: dict[int, WaveDamageResult] = {}
        self._build_ui()
        self._populate_attackers()
        self._populate_dungeons()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Title bar
        title_bar = QFrame()
        title_bar.setObjectName("topbar")
        title_bar.setFixedHeight(42)
        tb = QHBoxLayout(title_bar)
        tb.setContentsMargins(16, 0, 16, 0)
        tl = QLabel("Dungeon Builder")
        tl.setFont(QFont("Segoe UI", 12, QFont.Bold))
        tb.addWidget(tl)
        tb.addStretch()
        root.addWidget(title_bar)

        # Controls row
        ctrl = QFrame()
        ctrl.setStyleSheet("QFrame { background: " + BG_CARD + "; border-bottom: 1px solid #2d333b; }")
        ctrl.setFixedHeight(46)
        cl = QHBoxLayout(ctrl)
        cl.setContentsMargins(12, 6, 12, 6)
        cl.setSpacing(10)

        cl.addWidget(QLabel("Dungeon:"))

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter dungeons...")
        self._search.setFixedWidth(160)
        self._search.textChanged.connect(self._filter_dungeons)
        cl.addWidget(self._search)

        self._dungeon_combo = QComboBox()
        self._dungeon_combo.setMinimumWidth(280)
        self._dungeon_combo.setMinimumHeight(30)
        self._dungeon_combo.currentIndexChanged.connect(self._on_dungeon_changed)
        cl.addWidget(self._dungeon_combo)

        self._no_data_lbl = QLabel("")
        self._no_data_lbl.setStyleSheet("color: #e8c84a;")
        cl.addWidget(self._no_data_lbl)

        cl.addStretch()
        root.addWidget(ctrl)

        damage_ctrl = QFrame()
        damage_ctrl.setStyleSheet(
            "QFrame { background: " + BG_PANEL + "; border-bottom: 1px solid #2d333b; }"
        )
        dl = QHBoxLayout(damage_ctrl)
        dl.setContentsMargins(12, 6, 12, 6)
        dl.setSpacing(8)

        dl.addWidget(QLabel("Attacker"))
        self._attacker_combo = QComboBox()
        self._attacker_combo.setMinimumWidth(210)
        self._attacker_combo.currentIndexChanged.connect(self._populate_skills)
        dl.addWidget(self._attacker_combo)

        dl.addWidget(QLabel("Skill"))
        self._skill_number = QComboBox()
        self._skill_number.addItem("Manual", None)
        self._skill_number.setMinimumWidth(180)
        self._skill_number.currentIndexChanged.connect(self._apply_skill_profile)
        dl.addWidget(self._skill_number)

        dl.addWidget(QLabel("Skill ATK"))
        self._skill_atk = QDoubleSpinBox()
        self._skill_atk.setRange(0.0, 20.0)
        self._skill_atk.setDecimals(2)
        self._skill_atk.setSingleStep(0.1)
        self._skill_atk.setValue(4.0)
        self._skill_atk.setSuffix(" x")
        self._skill_atk.setFixedWidth(82)
        dl.addWidget(self._skill_atk)

        dl.addWidget(QLabel("Hits"))
        self._skill_hits = QSpinBox()
        self._skill_hits.setRange(1, 20)
        self._skill_hits.setValue(1)
        self._skill_hits.setFixedWidth(54)
        dl.addWidget(self._skill_hits)

        dl.addWidget(QLabel("Skill-up"))
        self._skillup_bonus = QDoubleSpinBox()
        self._skillup_bonus.setRange(0.0, 100.0)
        self._skillup_bonus.setValue(0.0)
        self._skillup_bonus.setSuffix("%")
        self._skillup_bonus.setFixedWidth(72)
        dl.addWidget(self._skillup_bonus)

        dl.addWidget(QLabel("Artifact"))
        self._artifact_bonus = QDoubleSpinBox()
        self._artifact_bonus.setRange(0.0, 100.0)
        self._artifact_bonus.setValue(0.0)
        self._artifact_bonus.setSuffix("%")
        self._artifact_bonus.setFixedWidth(72)
        dl.addWidget(self._artifact_bonus)

        self._atk_buff = QCheckBox("ATK buff")
        self._def_break = QCheckBox("DEF break")
        self._brand = QCheckBox("Brand")
        self._force_crit = QCheckBox("Force crit")
        self._force_crit.setChecked(True)
        for checkbox in (
            self._atk_buff,
            self._def_break,
            self._brand,
            self._force_crit,
        ):
            dl.addWidget(checkbox)

        self._analyze_btn = QPushButton("Analyze Damage")
        self._analyze_btn.clicked.connect(self._refresh_damage_results)
        dl.addWidget(self._analyze_btn)
        dl.addStretch()
        root.addWidget(damage_ctrl)

        # Summary bar placeholder
        self._summary_container = QWidget()
        scl = QVBoxLayout(self._summary_container)
        scl.setContentsMargins(10, 8, 10, 0)
        scl.setSpacing(0)
        self._summary_bar: _DungeonSummaryBar | None = None
        root.addWidget(self._summary_container)

        # Waves scroll area
        self._waves_scroll = QScrollArea()
        self._waves_scroll.setWidgetResizable(True)
        self._waves_scroll.setFrameShape(QFrame.NoFrame)

        self._waves_widget = QWidget()
        self._waves_layout = QVBoxLayout(self._waves_widget)
        self._waves_layout.setContentsMargins(10, 6, 10, 10)
        self._waves_layout.setSpacing(10)
        self._waves_layout.setAlignment(Qt.AlignTop)
        self._waves_scroll.setWidget(self._waves_widget)
        root.addWidget(self._waves_scroll, 1)

        # Placeholder message
        self._placeholder = QLabel(
            "Import account data to load dungeon wave information.\n\n"
            "Use File → Import JSON to get started."
        )
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet("color: " + TEXT_DIM + "; font-size: 12pt;")
        self._waves_layout.addWidget(self._placeholder)

    def _populate_attackers(self) -> None:
        selected_id = self._attacker_combo.currentData()
        monsters = queries.get_monsters(self._conn)
        self._attacker_combo.blockSignals(True)
        try:
            self._attacker_combo.clear()
            for monster in monsters:
                self._attacker_combo.addItem(
                    monster["display_name"],
                    monster["unit_id"],
                )
            if selected_id is not None:
                index = self._attacker_combo.findData(selected_id)
                if index >= 0:
                    self._attacker_combo.setCurrentIndex(index)
            self._attacker_combo.setEnabled(bool(monsters))
            self._analyze_btn.setEnabled(bool(monsters))
        finally:
            self._attacker_combo.blockSignals(False)
        self._populate_skills()

    def _populate_skills(self) -> None:
        unit_id = self._attacker_combo.currentData()
        current = self._skill_number.currentData()
        selected_skill_id = current.get("skill_id") if isinstance(current, dict) else None
        profiles = (
            queries.get_monster_skill_profiles(self._conn, int(unit_id))
            if unit_id is not None else []
        )
        supported = [profile for profile in profiles if profile.get("supported")]
        self._skill_number.blockSignals(True)
        try:
            self._skill_number.clear()
            self._skill_number.addItem("Manual", None)
            for profile in supported:
                self._skill_number.addItem(
                    "S%s  %s" % (profile.get("slot", "?"), profile.get("name", "Skill")),
                    profile,
                )
            index = 1 if supported else 0
            if selected_skill_id is not None:
                for candidate in range(1, self._skill_number.count()):
                    data = self._skill_number.itemData(candidate)
                    if isinstance(data, dict) and data.get("skill_id") == selected_skill_id:
                        index = candidate
                        break
            self._skill_number.setCurrentIndex(index)
        finally:
            self._skill_number.blockSignals(False)
        self._apply_skill_profile()

    def _apply_skill_profile(self) -> None:
        profile = self._skill_number.currentData()
        if not isinstance(profile, dict):
            self._skill_number.setToolTip("Enter a manual multiplier and hit count.")
            return
        self._skill_atk.setValue(float(profile.get("atk") or 0.0))
        self._skill_hits.setValue(max(1, int(profile.get("hits") or 1)))
        self._skillup_bonus.setValue(float(profile.get("skillup_bonus_pct") or 0.0))
        self._skill_number.setToolTip(
            "%s | Level %s/%s"
            % (
                profile.get("formula") or "No formula",
                profile.get("level", 1),
                profile.get("max_level", 1),
            )
        )

    def _calculate_damage_results(
        self,
        waves: dict[int, list[dict]],
    ) -> dict[int, WaveDamageResult]:
        unit_id = self._attacker_combo.currentData()
        if unit_id is None:
            return {}
        stats = queries.compute_monster_stats(
            self._conn,
            int(unit_id),
            include_artifacts=False,
        )
        if not stats:
            return {}
        dungeon_name = self._dungeon_combo.currentText()
        dungeon_profile = next(
            (
                profile
                for profile in DUNGEON_PROFILES.values()
                if profile.get("dungeon_key") == dungeon_name
            ),
            {},
        )
        selected_skill = self._skill_number.currentData()
        selected_profile = selected_skill if isinstance(selected_skill, dict) else {}
        artifact_profile = ArtifactProfile(
            goal="damage",
            target_element=dungeon_profile.get("boss_element") or None,
            skill_number=int(selected_profile.get("slot") or 1),
            single_target=not bool(selected_profile.get("aoe", False)),
            enemy_hp_ratio=1.0,
        )
        artifact_bonuses = queries.get_monster_artifact_bonuses(
            self._conn,
            int(unit_id),
            artifact_profile,
        )
        attacker = UnitStats(
            hp=float(stats.get("hp") or 0) + float(artifact_bonuses.get("hp") or 0),
            atk=float(stats.get("atk") or 0) + float(artifact_bonuses.get("atk") or 0),
            defense=float(stats.get("def_") or 0) + float(artifact_bonuses.get("def") or 0),
            speed=float(stats.get("spd") or 0),
            crit_rate=float(stats.get("cr") or 0),
            crit_damage=(
                float(stats.get("cd") or 0)
                + float(artifact_bonuses.get("cd_bonus") or 0)
            ),
        )
        scaling = SkillScaling(
            atk=float(self._skill_atk.value()),
            hp=float(selected_profile.get("hp") or 0.0),
            defense=float(selected_profile.get("defense") or 0.0),
            speed=float(selected_profile.get("speed") or 0.0),
            target_hp=float(selected_profile.get("target_hp") or 0.0),
            flat=float(selected_profile.get("flat") or 0.0),
            hits=int(self._skill_hits.value()),
        )
        context = DamageContext(
            atk_buff=self._atk_buff.isChecked(),
            defense_break=self._def_break.isChecked(),
            brand=self._brand.isChecked(),
            skillup_bonus_pct=float(self._skillup_bonus.value()),
            artifact_bonus_pct=(
                float(self._artifact_bonus.value())
                + float(artifact_bonuses.get("damage_bonus_pct") or 0)
            ),
            element_bonus_pct=float(
                artifact_bonuses.get("element_bonus_pct") or 0
            ),
            additional_damage_by_hp_pct=float(
                artifact_bonuses.get("addl_hp_pct") or 0
            ),
            additional_damage_by_atk_pct=float(
                artifact_bonuses.get("addl_atk_pct") or 0
            ),
            additional_damage_by_def_pct=float(
                artifact_bonuses.get("addl_def_pct") or 0
            ),
            additional_damage_by_spd_pct=float(
                artifact_bonuses.get("addl_spd_pct") or 0
            ),
            force_crit=(
                self._force_crit.isChecked()
                and not bool(selected_profile.get("fixed_damage", False))
            ),
            ignore_defense=bool(selected_profile.get("ignores_defense", False)),
        )
        return analyze_waves(attacker, waves, scaling, context)

    def _refresh_damage_results(self) -> None:
        dungeon_name = self._dungeon_combo.currentText()
        if dungeon_name:
            self._show_dungeon(dungeon_name)

    def _populate_dungeons(self, filter_text: str = ""):
        if not queries.has_dungeon_data(self._conn):
            self._no_data_lbl.setText(
                "No dungeon data — use Settings → Import Dungeon Data to load wave info."
            )
            return

        self._no_data_lbl.setText("")
        names = queries.get_dungeon_names(self._conn)
        if filter_text:
            fl = filter_text.lower()
            names = [n for n in names if fl in n.lower()]

        prev = self._dungeon_combo.currentText()
        self._dungeon_combo.blockSignals(True)
        self._dungeon_combo.clear()
        for name in names:
            self._dungeon_combo.addItem(name)
        # Restore selection
        idx = self._dungeon_combo.findText(prev)
        if idx >= 0:
            self._dungeon_combo.setCurrentIndex(idx)
        self._dungeon_combo.blockSignals(False)

        if self._dungeon_combo.count() > 0:
            self._on_dungeon_changed()

    def _filter_dungeons(self, text: str):
        self._populate_dungeons(text.strip())

    def _on_dungeon_changed(self):
        dungeon_name = self._dungeon_combo.currentText()
        if not dungeon_name:
            return
        self._show_dungeon(dungeon_name)

    def _show_dungeon(self, dungeon_name: str):
        # Clear old content
        while self._waves_layout.count():
            item = self._waves_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Summary bar
        summary = queries.get_dungeon_summary(self._conn, dungeon_name)
        if self._summary_bar:
            self._summary_bar.deleteLater()
        self._summary_bar = _DungeonSummaryBar(summary)
        # Replace summary container content
        old_layout = self._summary_container.layout()
        while old_layout.count():
            item = old_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        old_layout.addWidget(self._summary_bar)

        # Waves
        waves = queries.get_dungeon_waves(self._conn, dungeon_name)
        if not waves:
            lbl = QLabel("No wave data for this dungeon.")
            lbl.setStyleSheet("color: " + TEXT_DIM + ";")
            self._waves_layout.addWidget(lbl)
            return

        self._damage_results = self._calculate_damage_results(waves)
        num_waves = max(waves.keys())
        for wave_num in sorted(waves.keys()):
            monsters = waves[wave_num]
            is_boss = wave_num == num_waves
            card = _WaveCard(
                wave_num,
                monsters,
                is_boss,
                self._damage_results.get(wave_num),
            )
            self._waves_layout.addWidget(card)

        self._waves_layout.addStretch()

    def refresh(self):
        self._populate_attackers()
        self._populate_dungeons(self._search.text().strip())

    def load_dungeon_data(self, json_path):
        """Called from main window after user imports dungeon JSON."""
        from pathlib import Path
        from desktop.db.dungeon_importer import import_dungeon_data
        n = import_dungeon_data(self._conn, Path(json_path))
        self._populate_dungeons()
        return n
