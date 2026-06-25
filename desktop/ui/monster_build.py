"""Monster build detail panel -- shows a monster's 6 equipped rune slots
and equipped rune details for each slot.
"""
from __future__ import annotations

import json
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QCheckBox,
    QFrame, QScrollArea, QSizePolicy,
)

from desktop.db import queries
from desktop.ui.theme import BORDER, TEXT_DIM, ACCENT, ELEMENT_COLORS


# ---- Visual constants -------------------------------------------------------

_GRADE_COLOR: dict[str, str] = {
    "S": "#ffd700",
    "A": "#c792ea",
    "B": "#5c9cf5",
    "C": "#4caf72",
    "D": "#888888",
}

# SW set bonus piece requirements (2-piece or 4-piece)
_SET_SIZE: dict[str, int] = {
    # 4-piece sets
    "Violent": 4, "Swift": 4, "Rage": 4,
    "Despair": 4, "Vampire": 4, "Fatal": 4,
    # 2-piece sets (everything else)
    "Will": 2, "Energy": 2, "Guard": 2, "Endure": 2, "Blade": 2,
    "Focus": 2, "Shield": 2, "Revenge": 2, "Nemesis": 2,
    "Destroy": 2, "Fight": 2, "Determination": 2,
    "Enhance": 2, "Accuracy": 2, "Tolerance": 2,
}

# Fixed main stat labels for odd slots (no choice on these)
_ODD_SLOT_MAIN: dict[int, str] = {
    1: "ATK+",
    3: "DEF+",
    5: "HP+",
}


# ---- Slot card widget -------------------------------------------------------

class _SlotCard(QFrame):
    """One rune slot card: equipped rune info (set, main, substats, grade)."""

    def __init__(
        self,
        slot_no: int,
        rune: dict | None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._slot_no = slot_no
        self._populate(rune)

    def _populate(self, rune: dict | None) -> None:
        grade = rune["grade"] if rune else None
        border = _GRADE_COLOR.get(grade or "", "#2d333b")

        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "QFrame {"
            "  background: #161b22;"
            "  border: 1px solid " + border + ";"
            "  border-radius: 6px;"
            "}"
            "QLabel { border: none; }"
        )
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(90)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(3)

        # ---- Header row (slot number + grade badge) -------------------------
        hdr = QHBoxLayout()
        slot_lbl = QLabel("Slot " + str(self._slot_no))
        slot_lbl.setFont(QFont("Segoe UI", 8, QFont.Bold))
        slot_lbl.setStyleSheet("color: #8b949e;")
        hdr.addWidget(slot_lbl)
        hdr.addStretch()

        if rune:
            g_lbl = QLabel(grade or "?")
            g_lbl.setFont(QFont("Segoe UI", 8, QFont.Bold))
            g_lbl.setStyleSheet(
                "background: " + border + ";"
                " color: #0d1117;"
                " border-radius: 3px; padding: 1px 6px;"
            )
            hdr.addWidget(g_lbl)
        layout.addLayout(hdr)

        if not rune:
            # Empty slot placeholder
            main_hint = _ODD_SLOT_MAIN.get(self._slot_no, "")
            empty_lbl = QLabel(main_hint + "\nEmpty" if main_hint else "Empty")
            empty_lbl.setFont(QFont("Segoe UI", 9))
            empty_lbl.setStyleSheet("color: " + TEXT_DIM + ";")
            empty_lbl.setAlignment(Qt.AlignCenter)
            layout.addWidget(empty_lbl)
            return

        # ---- Set + main stat ------------------------------------------------
        set_name = rune.get("set_name") or "?"
        main_n   = rune.get("main_stat_name") or ""
        main_v   = rune.get("main_stat_value") or ""
        set_main = QLabel(set_name + "  |  " + main_n + " " + str(main_v))
        set_main.setFont(QFont("Segoe UI", 10, QFont.Bold))
        set_main.setStyleSheet("color: #c9d1d9;")
        layout.addWidget(set_main)

        # ---- Meta: level / stars / efficiency -------------------------------
        upgrade_lvl = rune.get("upgrade_curr") or 0
        stars_n     = rune.get("stars") or 6
        eff         = rune.get("efficiency") or 0
        desr        = rune.get("desirability") or 0
        meta_lbl = QLabel(
            "+" + str(upgrade_lvl)
            + "  " + str(stars_n) + "★"
            + "  Eff " + str(eff) + "%"
            + "  Desr " + str(desr) + "%"
        )
        meta_lbl.setFont(QFont("Segoe UI", 8))
        meta_lbl.setStyleSheet("color: " + TEXT_DIM + ";")
        layout.addWidget(meta_lbl)

        # ---- Substats -------------------------------------------------------
        subs_raw = rune.get("substat_labels")
        if subs_raw:
            try:
                subs = json.loads(subs_raw) if isinstance(subs_raw, str) else subs_raw
                subs_txt = "  ·  ".join(str(s) for s in (subs or []))
            except Exception:
                subs_txt = str(subs_raw)
            subs_lbl = QLabel(subs_txt)
            subs_lbl.setFont(QFont("Segoe UI", 8))
            subs_lbl.setStyleSheet("color: #8b949e;")
            subs_lbl.setWordWrap(True)
            layout.addWidget(subs_lbl)




# ---- Monster build panel ---------------------------------------------------

class MonsterBuildPanel(QWidget):
    """
    Right-hand panel in the monster roster showing:
      - Monster name / element / archetype / level
      - Base stats at max level
      - Active set bonuses
      - 6 rune slot cards in a 2-column grid
      - Upgrade hints from storage for each slot
    """

    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self._conn = conn
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Placeholder shown when no monster is selected
        self._placeholder = QLabel("Select a monster to view its build")
        self._placeholder.setObjectName("subtitle")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setFont(QFont("Segoe UI", 13))
        self._placeholder.setStyleSheet("color: " + TEXT_DIM + ";")
        self._placeholder.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding,
        )
        root.addWidget(self._placeholder)

        # Scrollable content area (hidden initially)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setVisible(False)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(12, 10, 12, 10)
        self._content_layout.setSpacing(8)
        self._scroll.setWidget(self._content)
        root.addWidget(self._scroll, 1)

        # Monster header labels (populated in show_monster)
        self._name_lbl  = QLabel("")
        self._name_lbl.setFont(QFont("Segoe UI", 15, QFont.Bold))
        self._name_lbl.setStyleSheet("color: #c9d1d9;")
        self._content_layout.addWidget(self._name_lbl)

        self._meta_lbl  = QLabel("")
        self._meta_lbl.setFont(QFont("Segoe UI", 9))
        self._meta_lbl.setStyleSheet("color: " + TEXT_DIM + ";")
        self._content_layout.addWidget(self._meta_lbl)

        # Stats row: label + base/total toggle
        stats_row = QHBoxLayout()
        self._stats_lbl = QLabel("")
        self._stats_lbl.setFont(QFont("Segoe UI", 9))
        self._stats_lbl.setStyleSheet("color: #8b949e;")
        stats_row.addWidget(self._stats_lbl, 1)
        self._total_stats_chk = QCheckBox("+ Runes & Artifacts")
        self._total_stats_chk.setChecked(False)
        self._total_stats_chk.setFont(QFont("Segoe UI", 8))
        self._total_stats_chk.setStyleSheet("color: " + TEXT_DIM + ";")
        self._total_stats_chk.toggled.connect(self._on_stats_toggle)
        stats_row.addWidget(self._total_stats_chk)
        self._content_layout.addLayout(stats_row)

        self._current_monster: dict | None = None

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #2d333b;")
        self._content_layout.addWidget(sep)

        # Set bonus badges row
        self._sets_widget  = QWidget()
        self._sets_layout  = QHBoxLayout(self._sets_widget)
        self._sets_layout.setContentsMargins(0, 0, 0, 0)
        self._sets_layout.setSpacing(6)
        self._sets_layout.addStretch()
        self._content_layout.addWidget(self._sets_widget)

        # Build score row
        self._score_lbl = QLabel("")
        self._score_lbl.setFont(QFont("Segoe UI", 9))
        self._score_lbl.setStyleSheet("color: " + TEXT_DIM + ";")
        self._content_layout.addWidget(self._score_lbl)

        # Building bonus summary row (shown once buildings are imported)
        self._building_lbl = QLabel("")
        self._building_lbl.setFont(QFont("Segoe UI", 8))
        self._building_lbl.setStyleSheet("color: #58a6ff; background: transparent;")
        self._building_lbl.setVisible(False)
        self._content_layout.addWidget(self._building_lbl)

        # 6 slot cards in a 2-column grid
        self._grid = QGridLayout()
        self._grid.setSpacing(8)
        self._content_layout.addLayout(self._grid)
        self._content_layout.addStretch()

    # ---- Public API ---------------------------------------------------------

    def _on_stats_toggle(self) -> None:
        self._refresh_stats()

    def _refresh_stats(self) -> None:
        monster = self._current_monster
        if not monster:
            return
        if self._total_stats_chk.isChecked():
            uid = monster.get("unit_id")
            ts  = queries.compute_monster_stats(self._conn, uid) if uid else {}
            if ts:
                self._stats_lbl.setStyleSheet("color: #c9d1d9;")
                self._stats_lbl.setText(
                    "HP " + str(ts.get("hp", "?"))
                    + "  ATK " + str(ts.get("atk", "?"))
                    + "  DEF " + str(ts.get("def_", "?"))
                    + "  SPD " + str(ts.get("spd", "?"))
                    + "  CR " + str(ts.get("cr", "?")) + "%"
                    + "  CD " + str(ts.get("cd", "?")) + "%"
                    + "  RES " + str(ts.get("res", "?")) + "%"
                    + "  ACC " + str(ts.get("acc", "?")) + "%"
                )
                return
        # Base stats
        self._stats_lbl.setStyleSheet("color: #8b949e;")
        self._stats_lbl.setText(
            "HP " + str(monster.get("max_lvl_hp") or "?")
            + "  ATK " + str(monster.get("max_lvl_attack") or "?")
            + "  DEF " + str(monster.get("max_lvl_defense") or "?")
            + "  SPD " + str(monster.get("base_speed") or "?")
            + "  CR " + str(monster.get("crit_rate") or "?") + "%"
            + "  CD " + str(monster.get("crit_damage") or "?") + "%"
            + "  RES " + str(monster.get("resistance") or "?") + "%"
            + "  ACC " + str(monster.get("accuracy") or "?") + "%"
        )

    def _refresh_building_label(self) -> None:
        from desktop.db.queries import get_building_bonuses
        try:
            bb = get_building_bonuses(self._conn)
        except Exception:
            self._building_lbl.setVisible(False)
            return
        parts = []
        if bb.get("hp_pct"):  parts.append("HP +"  + str(int(bb["hp_pct"]))  + "%")
        if bb.get("atk_pct"): parts.append("ATK +" + str(int(bb["atk_pct"])) + "%")
        if bb.get("def_pct"): parts.append("DEF +" + str(int(bb["def_pct"])) + "%")
        if bb.get("spd_pct"): parts.append("SPD +" + str(int(bb["spd_pct"])) + "%")
        if bb.get("cd_add"):  parts.append("CD +"  + str(int(bb["cd_add"]))  + "%")
        if bb.get("cr_add"):  parts.append("CR +"  + str(int(bb["cr_add"]))  + "%")
        if parts:
            self._building_lbl.setText("Buildings: " + "  |  ".join(parts))
            self._building_lbl.setVisible(True)
        else:
            self._building_lbl.setVisible(False)

    def show_monster(self, monster: dict) -> None:
        unit_id = monster.get("unit_id")
        if unit_id is None:
            self.clear()
            return

        # ---- Monster header -------------------------------------------------
        elem    = monster.get("element") or ""
        arch    = monster.get("archetype") or ""
        stars   = str(monster.get("stars") or "") + "★"
        nat     = "(" + str(monster.get("natural_stars") or "") + "★ natural)"
        lvl     = "Lv" + str(monster.get("level") or "?")
        name    = monster.get("display_name") or "Unknown"

        self._name_lbl.setText(name)
        elem_color = ELEMENT_COLORS.get(elem, "#c9d1d9")
        self._meta_lbl.setStyleSheet("color: " + elem_color + ";")
        self._meta_lbl.setText(elem + "  " + arch + "  " + stars + "  " + nat + "  " + lvl)

        self._current_monster = monster
        self._refresh_stats()

        # ---- Building bonus label ------------------------------------------
        self._refresh_building_label()

        # ---- Fetch runes + compute upgrades ---------------------------------
        rune_build = queries.get_monster_rune_build(self._conn, unit_id)

        # ---- Set bonus badges -----------------------------------------------
        # clear old badges
        while self._sets_layout.count() > 1:
            item = self._sets_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        set_counts: dict[str, int] = {}
        for r in rune_build.values():
            s = r.get("set_name") or ""
            if s:
                set_counts[s] = set_counts.get(s, 0) + 1

        badges_added = 0
        for s, cnt in sorted(set_counts.items(), key=lambda x: -x[1]):
            required = _SET_SIZE.get(s, 2)
            active   = cnt >= required
            badge = QLabel(s + " " + str(cnt) + "/" + str(required))
            badge.setFont(QFont("Segoe UI", 8, QFont.Bold))
            if active:
                badge.setStyleSheet(
                    "background: rgba(63,185,80,0.15);"
                    " color: #3fb950;"
                    " border: 1px solid rgba(63,185,80,0.35);"
                    " border-radius: 4px; padding: 2px 7px;"
                )
            else:
                badge.setStyleSheet(
                    "background: rgba(139,148,158,0.10);"
                    " color: #8b949e;"
                    " border: 1px solid rgba(139,148,158,0.25);"
                    " border-radius: 4px; padding: 2px 7px;"
                )
            self._sets_layout.insertWidget(badges_added, badge)
            badges_added += 1

        if not badges_added:
            empty_badge = QLabel("No runes equipped")
            empty_badge.setStyleSheet("color: " + TEXT_DIM + ";")
            empty_badge.setFont(QFont("Segoe UI", 8))
            self._sets_layout.insertWidget(0, empty_badge)

        # ---- Build score ----------------------------------------------------
        desrs = [
            rune_build[s].get("desirability") or 0
            for s in rune_build
            if rune_build[s].get("desirability") is not None
        ]
        if desrs:
            avg_desr   = round(sum(desrs) / len(desrs), 1)
            slots_used = len(desrs)
            self._score_lbl.setText(
                "Build avg desr: " + str(avg_desr) + "%"
                + "  (" + str(slots_used) + "/6 slots filled)"
            )
        else:
            self._score_lbl.setText("No runes equipped")

        # ---- Slot cards (2-col grid) ----------------------------------------
        # Clear old cards
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, slot_no in enumerate([1, 2, 3, 4, 5, 6]):
            rune = rune_build.get(slot_no)
            card = _SlotCard(slot_no, rune)
            self._grid.addWidget(card, i // 2, i % 2)

        # Show content, hide placeholder
        self._placeholder.setVisible(False)
        self._scroll.setVisible(True)

    def clear(self) -> None:
        self._current_monster = None
        self._scroll.setVisible(False)
        self._placeholder.setVisible(True)
