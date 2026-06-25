"""Rune Optimizer panel.

Left:  monster picker, set constraints, main-stat constraints (slots 2/4/6),
       target substat minimums, rune pool options, Optimize button.
Right: 6 slot cards showing current vs. suggested rune + before/after stat comparison.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter

from PySide6.QtCore    import Qt, QThread, Signal
from PySide6.QtGui     import QFont
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QComboBox, QCheckBox, QFrame, QScrollArea, QGridLayout,
    QSizePolicy, QSpacerItem, QSplitter, QLineEdit, QSpinBox,
)

from desktop.db import queries
from desktop.task_lifecycle import cancel_task, is_task_running
from optimizer.stat_utils import (
    SET_SIZE              as _SET_SIZE,
    compute_final_stats,
    compute_stats_from_equipped,
    fmt_k,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ALL_SETS = [
    "",
    "Violent", "Swift", "Rage", "Despair", "Vampire", "Fatal",
    "Will", "Energy", "Guard", "Endure", "Blade", "Focus",
    "Shield", "Revenge", "Nemesis", "Destroy", "Fight",
    "Determination", "Enhance", "Accuracy", "Tolerance",
]

_SLOT2_MAINS  = ["Any", "SPD", "HP%", "ATK%", "DEF%"]
_SLOT4_MAINS  = ["Any", "CR%", "CD%", "HP%", "ATK%", "DEF%"]
_SLOT6_MAINS  = ["Any", "HP%", "ATK%", "DEF%", "RES%", "ACC%"]

_TARGET_STATS = ["HP", "ATK", "DEF", "SPD", "CR%", "CD%", "RES%", "ACC%"]

_GRADE_COLOR = {
    "S": "#ffd700", "A": "#c792ea", "B": "#5c9cf5",
    "C": "#4caf72", "D": "#888888",
}

_ELEMENT_COLOR = {
    "Fire": "#e05c5c", "Water": "#5c9cf5", "Wind": "#4caf72",
    "Light": "#e8c84a", "Dark": "#c792ea",
}

TEXT_DIM  = "#8b949e"
TEXT_MAIN = "#c9d1d9"
BG_CARD   = "#161b22"
COL_OK    = "#3fb950"
COL_WARN  = "#e8c84a"
COL_FAIL  = "#e05c5c"


# ---------------------------------------------------------------------------
# Label helper (same smart-prefix logic as team optimizer)
# ---------------------------------------------------------------------------

def _build_labels(monsters: list[dict]) -> list[str]:
    """Omit element prefix when a base_name is unique in the roster."""
    base_counts = Counter(m.get("base_name") or m.get("display_name", "") for m in monsters)
    labels: list[str] = []
    for m in monsters:
        base  = m.get("base_name") or m.get("display_name") or "?"
        disp  = m.get("display_name") or base
        stars = m.get("stars") or 0
        name  = base if base_counts[base] == 1 else disp
        labels.append(name + "  " + str(stars) + "*")
    return labels


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------

class _OptimizeWorker(QThread):
    finished = Signal(object)
    progress = Signal(str)

    def __init__(self, conn_path, unit_id, set_reqs, main_stat_constraints,
                 target_stats, min_stars, include_equipped, include_locked=False,
                 target_mode="total"):
        super().__init__()
        self._conn_path             = conn_path
        self._unit_id               = unit_id
        self._set_reqs              = set_reqs
        self._main_stat_constraints = main_stat_constraints
        self._target_stats          = target_stats
        self._min_stars             = min_stars
        self._include_equipped      = include_equipped
        self._include_locked        = include_locked
        self._target_mode           = target_mode

    def run(self):
        try:
            from desktop.db.schema import get_connection
            conn = get_connection(self._conn_path)
            # Always fetch equipped runes too: the monster's OWN runes must
            # stay available to itself (otherwise suggestions can be worse
            # than the current build). The checkbox only controls whether
            # runes on OTHER monsters may be taken.
            pool = queries.get_rune_pool(
                conn,
                min_stars        = self._min_stars,
                include_equipped = True,
                exclude_unit_id  = None,
                exclude_user_locked = not self._include_locked,
            )
            if not self._include_equipped:
                pool = [r for r in pool
                        if not r.get("occupied_id")
                        or r["occupied_id"] == self._unit_id]
            current_build = queries.get_monster_rune_build(conn, self._unit_id)

            # Monster base stats + building bonuses + artifact flats so the
            # optimizer evaluates targets on FINAL stats (same semantics as
            # the Team Optimizer).
            _minfo = next((m for m in queries.get_monsters(conn)
                           if m.get("unit_id") == self._unit_id), None)
            try:
                _bld = queries.get_building_bonuses(
                    conn, (_minfo or {}).get("element"))
            except Exception:
                _bld = None
            _af = {"hp": 0, "atk": 0, "def": 0}
            for eff_id, eff_val, label in conn.execute(
                "SELECT pri_effect_id, pri_effect_value, pri_effect"
                " FROM artifacts WHERE occupied_id = ?", (self._unit_id,)
            ).fetchall():
                if eff_id == 100 and eff_val:   _af["hp"]  += int(eff_val)
                elif eff_id == 101 and eff_val: _af["atk"] += int(eff_val)
                elif eff_id == 102 and eff_val: _af["def"] += int(eff_val)
                elif eff_id is None:
                    try:
                        sp, vp = (label or "").split(":", 1)
                        v = int(float(vp.strip().replace(",", "")))
                        sp = sp.strip().upper()
                        if sp in ("HP", "ATK", "DEF"):
                            _af[sp.lower()] += v
                    except Exception:
                        pass
            conn.close()

            from optimizer.rune_optimizer import optimize
            results = optimize(
                rune_pool              = pool,
                set_reqs               = self._set_reqs,
                current_build          = current_build,
                main_stat_constraints  = self._main_stat_constraints,
                target_stats           = self._target_stats,
                top_n                  = 5,
                target_mode            = self._target_mode,
                monster_info           = _minfo,
                artifact_flat          = _af if any(_af.values()) else None,
                extra_bonuses          = _bld,
                cancel_check           = self.isInterruptionRequested,
                progress_callback      = lambda done, total, message: self.progress.emit(
                    "%s (%d/%d)" % (message, done, total)
                ),
            )
            self.finished.emit(results)
        except Exception as exc:
            from optimizer.rune_optimizer import OptimizationCancelled
            if isinstance(exc, OptimizationCancelled):
                self.finished.emit(exc)
            else:
                import traceback
                self.finished.emit(str(exc) + "\n" + traceback.format_exc())


# ---------------------------------------------------------------------------
# Slot comparison card
# ---------------------------------------------------------------------------

class _SlotCompareCard(QFrame):
    def __init__(self, slot_no: int, current: dict | None, suggested: dict | None,
                 required_set: str | None, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        grade  = (suggested or current or {}).get("grade") or ""
        border = _GRADE_COLOR.get(grade, "#2d333b")
        self.setStyleSheet(
            "QFrame { background: " + BG_CARD + ";"
            " border: 1px solid " + (border if suggested else "#2d333b") + ";"
            " border-radius: 6px; }"
            "QLabel { border: none; }"
        )
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(3)

        # Header: slot label + set tag + grade badge
        hdr = QHBoxLayout()
        slot_lbl = QLabel("Slot " + str(slot_no))
        slot_lbl.setFont(QFont("Segoe UI", 8, QFont.Bold))
        slot_lbl.setStyleSheet("color: " + TEXT_DIM + ";")
        hdr.addWidget(slot_lbl)
        if required_set:
            req_lbl = QLabel(required_set)
            req_lbl.setFont(QFont("Segoe UI", 7))
            req_lbl.setStyleSheet(
                "color: #8b949e; background: rgba(139,148,158,0.12);"
                " border: 1px solid rgba(139,148,158,0.2);"
                " border-radius: 3px; padding: 1px 5px;"
            )
            hdr.addWidget(req_lbl)
        hdr.addStretch()
        if suggested:
            g = suggested.get("grade") or "?"
            g_lbl = QLabel(g)
            g_lbl.setFont(QFont("Segoe UI", 8, QFont.Bold))
            g_lbl.setStyleSheet(
                "background: " + _GRADE_COLOR.get(g, "#888") + ";"
                " color: #0d1117; border-radius: 3px; padding: 1px 6px;"
            )
            hdr.addWidget(g_lbl)
        root.addLayout(hdr)

        # Current rune (compact, dimmed)
        if current:
            cur_desr  = current.get("desirability") or 0
            cur_set   = current.get("set_name") or "?"
            cur_main  = current.get("main_stat_name") or ""
            cur_val   = current.get("main_stat_value") or ""
            cur_grade = current.get("grade") or "?"
            cur_lbl = QLabel(
                "Current: " + cur_grade + "  " + cur_set + "  "
                + cur_main + " " + str(cur_val)
                + "  (" + str(cur_desr) + "% desr)"
            )
            cur_lbl.setFont(QFont("Segoe UI", 7))
            cur_lbl.setStyleSheet("color: " + TEXT_DIM + ";")
            root.addWidget(cur_lbl)
        else:
            cur_lbl = QLabel("Current: empty")
            cur_lbl.setFont(QFont("Segoe UI", 7))
            cur_lbl.setStyleSheet("color: " + TEXT_DIM + ";")
            root.addWidget(cur_lbl)

        if not suggested:
            no_lbl = QLabel("No candidate found")
            no_lbl.setFont(QFont("Segoe UI", 8))
            no_lbl.setStyleSheet("color: " + TEXT_DIM + ";")
            root.addWidget(no_lbl)
            return

        # Suggested rune — main line
        sug_desr = suggested.get("desirability") or 0
        sug_set  = suggested.get("set_name") or "?"
        sug_main = suggested.get("main_stat_name") or ""
        sug_val  = suggested.get("main_stat_value") or ""
        sug_lvl  = suggested.get("upgrade_curr") or 0
        sug_eff  = suggested.get("efficiency") or 0

        main_line = QLabel(
            sug_set + "  |  " + sug_main + " " + str(sug_val)
            + "   +" + str(sug_lvl) + "  Eff " + str(sug_eff) + "%"
        )
        main_line.setFont(QFont("Segoe UI", 9, QFont.Bold))
        main_line.setStyleSheet("color: " + TEXT_MAIN + ";")
        root.addWidget(main_line)

        # Delta
        cur_d = (current.get("desirability") or 0) if current else 0
        diff  = round(sug_desr - cur_d, 1)
        diff_str   = ("+" if diff >= 0 else "") + str(diff) + "% desr"
        diff_color = COL_OK if diff > 0 else (COL_FAIL if diff < 0 else TEXT_DIM)
        delta_lbl = QLabel(diff_str)
        delta_lbl.setFont(QFont("Segoe UI", 8, QFont.Bold))
        delta_lbl.setStyleSheet("color: " + diff_color + ";")
        root.addWidget(delta_lbl)

        # Substats
        try:
            subs_raw = suggested.get("substat_labels")
            subs = json.loads(subs_raw) if isinstance(subs_raw, str) else subs_raw
            subs_txt = "  .  ".join(str(s) for s in (subs or []))
        except Exception:
            subs_txt = ""
        if subs_txt:
            subs_lbl = QLabel(subs_txt)
            subs_lbl.setFont(QFont("Segoe UI", 7))
            subs_lbl.setStyleSheet("color: " + TEXT_DIM + ";")
            subs_lbl.setWordWrap(True)
            root.addWidget(subs_lbl)

        # Source warning
        occupied_id   = suggested.get("occupied_id")
        occupied_name = suggested.get("occupied_name")
        if occupied_id and occupied_id != 0:
            src_lbl = QLabel("  Currently on: " + str(occupied_name or "unknown"))
            src_lbl.setFont(QFont("Segoe UI", 7))
            src_lbl.setStyleSheet(
                "color: " + COL_WARN + "; background: rgba(232,200,74,0.07);"
                " border: 1px solid rgba(232,200,74,0.2);"
                " border-radius: 3px; padding: 1px 5px;"
            )
            root.addWidget(src_lbl)


# ---------------------------------------------------------------------------
# Before/After stat comparison bar
# ---------------------------------------------------------------------------

def _stat_color(key: str, val: float) -> str:
    """Color code a stat based on typical breakpoints."""
    if key == "cr":
        return COL_OK if val >= 85 else (COL_WARN if val >= 70 else TEXT_MAIN)
    if key == "cd":
        return COL_OK if val >= 150 else TEXT_MAIN
    return TEXT_MAIN


class _StatsCompareBar(QFrame):
    """Two-row stat comparison: current build vs. suggested build."""

    def __init__(
        self,
        monster_info: dict,
        current_build: dict,         # {slot_no: rune_dict}
        suggested_build,             # BuildResult
        artifact_flat: dict | None,
        building_bonuses: dict | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "QFrame { background: rgba(22,27,34,0.7);"
            " border: 1px solid #2d333b; border-radius: 6px; }"
            "QLabel { border: none; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(4)

        cur_s = compute_stats_from_equipped(monster_info, current_build, artifact_flat, building_bonuses)
        sug_s = compute_final_stats(monster_info, suggested_build, artifact_flat, building_bonuses)

        keys  = [("hp", "HP"), ("atk", "ATK"), ("def_", "DEF"),
                 ("spd", "SPD"), ("cr", "CR%"), ("cd", "CD%"),
                 ("res", "RES%"), ("acc", "ACC%")]

        # Header row: stat labels
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr.setSpacing(0)
        spacer = QLabel("")
        spacer.setFixedWidth(62)
        hdr.addWidget(spacer)
        for key, label in keys:
            lbl = QLabel(label)
            lbl.setFont(QFont("Segoe UI", 7))
            lbl.setStyleSheet("color: " + TEXT_DIM + ";")
            lbl.setAlignment(Qt.AlignCenter)
            hdr.addWidget(lbl, 1)
        root.addLayout(hdr)

        def _fmt(key: str, val) -> str:
            if key in ("hp", "atk", "def_"):
                return fmt_k(int(val))
            if key in ("cr", "cd", "res", "acc"):
                return str(round(val, 1)) + "%"
            return str(val)

        def _make_row(label: str, stats: dict, label_color: str) -> QHBoxLayout:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(0)
            lbl = QLabel(label)
            lbl.setFont(QFont("Segoe UI", 7, QFont.Bold))
            lbl.setStyleSheet("color: " + label_color + ";")
            lbl.setFixedWidth(62)
            row.addWidget(lbl)
            for key, _ in keys:
                v = stats.get(key, 0)
                txt = _fmt(key, v)
                c   = _stat_color(key, v)
                vl  = QLabel(txt)
                vl.setFont(QFont("Segoe UI", 8, QFont.Bold))
                vl.setStyleSheet("color: " + c + ";")
                vl.setAlignment(Qt.AlignCenter)
                row.addWidget(vl, 1)
            return row

        root.addLayout(_make_row("Current:", cur_s, TEXT_DIM))

        # Delta row
        delta_row = QHBoxLayout()
        delta_row.setContentsMargins(0, 0, 0, 0)
        delta_row.setSpacing(0)
        arrow = QLabel("Suggested:")
        arrow.setFont(QFont("Segoe UI", 7, QFont.Bold))
        arrow.setStyleSheet("color: " + COL_OK + ";")
        arrow.setFixedWidth(62)
        delta_row.addWidget(arrow)

        for key, _ in keys:
            cur_v = cur_s.get(key, 0)
            sug_v = sug_s.get(key, 0)
            txt   = _fmt(key, sug_v)
            c     = _stat_color(key, sug_v)

            # Add delta badge if changed
            delta = sug_v - cur_v
            if abs(delta) >= (1 if key in ("spd",) else
                              0.5 if key in ("cr", "cd", "res", "acc") else
                              10):
                sign = "+" if delta >= 0 else ""
                if key in ("hp", "atk", "def_"):
                    dsign = ("+" if delta >= 0 else "") + str(round(delta / max(cur_v, 1) * 100, 0))[:-2] + "%"
                    if dsign == "+0%": dsign = ""
                else:
                    dsign = sign + str(round(delta, 1))
                delta_color = COL_OK if delta > 0 else COL_FAIL
                if dsign:
                    txt = txt + " " + dsign
                    c   = delta_color

            vl = QLabel(txt)
            vl.setFont(QFont("Segoe UI", 8, QFont.Bold))
            vl.setStyleSheet("color: " + c + ";")
            vl.setAlignment(Qt.AlignCenter)
            delta_row.addWidget(vl, 1)

        root.addLayout(delta_row)

        # Artifact footnote
        if artifact_flat and any(artifact_flat.get(k, 0) for k in ("hp", "atk", "def")):
            art_lbl = QLabel(
                "Artifact bonuses included: "
                + ("HP +" + fmt_k(artifact_flat.get("hp", 0)) + " " if artifact_flat.get("hp") else "")
                + ("ATK +" + str(artifact_flat.get("atk", 0)) + " " if artifact_flat.get("atk") else "")
                + ("DEF +" + str(artifact_flat.get("def", 0)) if artifact_flat.get("def") else "")
            )
            art_lbl.setFont(QFont("Segoe UI", 7))
            art_lbl.setStyleSheet("color: " + TEXT_DIM + ";")
            root.addWidget(art_lbl)


# ---------------------------------------------------------------------------
# Results panel
# ---------------------------------------------------------------------------

class _ResultsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._placeholder = QLabel(
            "Configure constraints on the left and press Optimize."
        )
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet("color: " + TEXT_DIM + ";")
        self._placeholder.setFont(QFont("Segoe UI", 12))
        self._placeholder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self._placeholder)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setVisible(False)
        root.addWidget(self._scroll, 1)

        self._content = QWidget()
        self._scroll.setWidget(self._content)
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(0, 0, 8, 0)
        self._layout.setSpacing(10)

    def _clear(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def show_placeholder(self):
        self._clear()
        self._scroll.setVisible(False)
        self._placeholder.setVisible(True)

    def show_error(self, msg: str):
        self._clear()
        self._placeholder.setVisible(False)
        self._scroll.setVisible(True)
        lbl = QLabel("Error: " + msg)
        lbl.setStyleSheet("color: " + COL_FAIL + ";")
        lbl.setWordWrap(True)
        self._layout.addWidget(lbl)
        self._layout.addStretch()

    def show_results(
        self,
        results,
        monster: dict,
        current_build: dict[int, dict],
        target_stats: dict[str, int],
        artifact_flat: dict | None = None,
        building_bonuses: dict | None = None,
    ):
        self._clear()
        self._placeholder.setVisible(False)
        self._scroll.setVisible(True)

        if not results:
            self._layout.addWidget(QLabel("No valid build found for these constraints."))
            self._layout.addStretch()
            return

        best = results[0]
        name = monster.get("display_name") or "?"

        # Title
        title = QLabel("Suggested build for " + name)
        title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        title.setStyleSheet("color: " + TEXT_MAIN + ";")
        self._layout.addWidget(title)

        # Set badges row
        badges_row = QHBoxLayout()
        for sname, cnt in sorted(best.set_summary.items(), key=lambda x: -x[1]):
            req    = _SET_SIZE.get(sname, 2)
            active = cnt >= req
            badge  = QLabel(sname + " " + str(cnt) + "/" + str(req))
            badge.setFont(QFont("Segoe UI", 8, QFont.Bold))
            if active:
                badge.setStyleSheet(
                    "background: rgba(63,185,80,0.15); color: " + COL_OK + ";"
                    " border: 1px solid rgba(63,185,80,0.35);"
                    " border-radius: 4px; padding: 2px 7px;"
                )
            else:
                badge.setStyleSheet(
                    "background: rgba(139,148,158,0.10); color: " + TEXT_DIM + ";"
                    " border: 1px solid rgba(139,148,158,0.25);"
                    " border-radius: 4px; padding: 2px 7px;"
                )
            badges_row.addWidget(badge)
        badges_row.addStretch()
        badges_widget = QWidget()
        badges_widget.setLayout(badges_row)
        self._layout.addWidget(badges_widget)

        # Score + target-stat row
        cur_avg = round(
            sum((r.get("desirability") or 0) for r in current_build.values())
            / max(len(current_build), 1), 1
        ) if current_build else 0.0
        delta     = round(best.avg_desr - cur_avg, 1)
        delta_str = ("+" if delta >= 0 else "") + str(delta) + "%"
        d_color   = COL_OK if delta > 0 else (COL_FAIL if delta < 0 else TEXT_DIM)

        score_parts = [
            "Avg desr: " + str(cur_avg) + "% -> " + str(best.avg_desr) + "%"
            + "  (" + delta_str + ")"
        ]

        _report = getattr(best, "target_report", None)
        if target_stats and (_report or best.stat_totals):
            parts = []
            if _report:
                # Final-stat semantics: actual vs target as seen in-game
                for stat, v in _report.items():
                    met  = v["met"]
                    mark = "+" if met else "x"
                    color_tag = COL_OK if met else COL_FAIL
                    parts.append((stat + " " + mark + " " + str(v["actual"])
                                  + "/" + str(int(v["target"])), color_tag))
            else:
                for stat, minval in target_stats.items():
                    got  = best.stat_totals.get(stat, 0)
                    met  = got >= minval
                    mark = "+" if met else "x"
                    color_tag = COL_OK if met else COL_FAIL
                    parts.append((stat + " " + mark + " " + str(got) + "/" + str(minval), color_tag))

            stat_row = QHBoxLayout()
            score_lbl = QLabel(score_parts[0])
            score_lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
            score_lbl.setStyleSheet("color: " + d_color + ";")
            stat_row.addWidget(score_lbl)
            stat_row.addSpacing(12)
            for txt, clr in parts:
                tl = QLabel(txt)
                tl.setFont(QFont("Segoe UI", 9, QFont.Bold))
                tl.setStyleSheet("color: " + clr + ";")
                stat_row.addWidget(tl)
            stat_row.addStretch()
            stat_widget = QWidget()
            stat_widget.setLayout(stat_row)
            self._layout.addWidget(stat_widget)
        else:
            score_lbl = QLabel(score_parts[0])
            score_lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
            score_lbl.setStyleSheet("color: " + d_color + ";")
            self._layout.addWidget(score_lbl)

        # --- Before/After stat comparison bar ---
        self._layout.addWidget(
            _StatsCompareBar(monster, current_build, best, artifact_flat, building_bonuses)
        )

        # Slot cards — 2-column grid
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, sr in enumerate(best.slots):
            card = _SlotCompareCard(
                sr.slot_no, current_build.get(sr.slot_no), sr.rune, sr.required_set
            )
            grid.addWidget(card, i // 2, i % 2)
        self._layout.addLayout(grid)

        # Alternative builds
        if len(results) > 1:
            alt_hdr = QLabel("Alternative builds")
            alt_hdr.setFont(QFont("Segoe UI", 10, QFont.Bold))
            alt_hdr.setStyleSheet("color: " + TEXT_DIM + "; margin-top: 6px;")
            self._layout.addWidget(alt_hdr)
            for alt in results[1:]:
                sets_txt = "  ".join(
                    s + " " + str(c) + "/" + str(_SET_SIZE.get(s, 2))
                    for s, c in sorted(alt.set_summary.items(), key=lambda x: -x[1])
                )
                tgt_txt = ""
                if target_stats and alt.stat_totals:
                    tgt_txt = "   " + "  ".join(
                        s + " " + str(alt.stat_totals.get(s, 0))
                        for s in target_stats
                    )
                alt_stats = compute_final_stats(monster, alt, artifact_flat, building_bonuses)
                stats_txt = (
                    "  SPD " + str(alt_stats["spd"])
                    + "  CR " + str(alt_stats["cr"]) + "%"
                    + "  CD " + str(alt_stats["cd"]) + "%"
                )
                lbl = QLabel(
                    "Avg " + str(alt.avg_desr) + "%   " + sets_txt + tgt_txt + stats_txt
                )
                lbl.setFont(QFont("Segoe UI", 8))
                lbl.setStyleSheet("color: " + TEXT_DIM + ";")
                self._layout.addWidget(lbl)

        self._layout.addStretch()


# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------

class RuneOptimizerWidget(QWidget):
    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self._conn     = conn
        self._db_path  = conn.execute("PRAGMA database_list").fetchone()[2]
        self._monsters: list[dict] = []
        self._worker: _OptimizeWorker | None = None
        self._build_ui()
        self._load_monsters()

    # ------------------------------------------------------------------
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
        tl = QLabel("Rune Optimizer")
        tl.setFont(QFont("Segoe UI", 12, QFont.Bold))
        tb.addWidget(tl)
        tb.addStretch()
        root.addWidget(title_bar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(6)
        splitter.setChildrenCollapsible(False)

        # ---- Left config panel ----------------------------------------
        left = QWidget()
        left.setMinimumWidth(270)
        left.setMaximumWidth(330)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 12, 12, 12)
        ll.setSpacing(8)
        ll.setAlignment(Qt.AlignTop)

        # Monster picker — editable search combo
        ll.addWidget(self._sec("Monster"))
        self._monster_combo = QComboBox()
        self._monster_combo.setEditable(True)
        self._monster_combo.setInsertPolicy(QComboBox.NoInsert)
        self._monster_combo.setMinimumHeight(30)
        self._monster_combo.lineEdit().setPlaceholderText("Search monster...")
        _c = self._monster_combo.completer()
        if _c:
            _c.setFilterMode(Qt.MatchContains)
            _c.setCaseSensitivity(Qt.CaseInsensitive)
        ll.addWidget(self._monster_combo)

        # Set requirements
        ll.addWidget(self._sec("Set Requirements"))
        self._ignore_sets_chk = QCheckBox("Best stats only (ignore sets)")
        self._ignore_sets_chk.toggled.connect(self._on_ignore_sets_toggled)
        ll.addWidget(self._ignore_sets_chk)

        self._set_combos:    list[QComboBox] = []
        self._set_size_lbls: list[QLabel]    = []
        self._set_rows:      list[QWidget]   = []

        for _ in range(3):
            row_w = QWidget()
            row_h = QHBoxLayout(row_w)
            row_h.setContentsMargins(0, 0, 0, 0)
            row_h.setSpacing(6)
            cb = QComboBox()
            cb.addItems(_ALL_SETS)
            cb.setMinimumHeight(26)
            cb.currentTextChanged.connect(self._on_set_changed)
            size_lbl = QLabel("")
            size_lbl.setFont(QFont("Segoe UI", 7))
            size_lbl.setStyleSheet("color: " + TEXT_DIM + ";")
            size_lbl.setFixedWidth(30)
            row_h.addWidget(cb, 1)
            row_h.addWidget(size_lbl)
            self._set_combos.append(cb)
            self._set_size_lbls.append(size_lbl)
            self._set_rows.append(row_w)
            ll.addWidget(row_w)

        self._constraint_warn = QLabel("")
        self._constraint_warn.setFont(QFont("Segoe UI", 7))
        self._constraint_warn.setStyleSheet("color: " + COL_WARN + ";")
        self._constraint_warn.setWordWrap(True)
        ll.addWidget(self._constraint_warn)

        # Main stat constraints (slots 2, 4, 6)
        ll.addWidget(self._sec("Main Stats"))
        self._main_combos: dict[int, QComboBox] = {}
        for slot_no, opts in [(2, _SLOT2_MAINS), (4, _SLOT4_MAINS), (6, _SLOT6_MAINS)]:
            row_w = QWidget()
            row_h = QHBoxLayout(row_w)
            row_h.setContentsMargins(0, 0, 0, 0)
            row_h.setSpacing(6)
            row_h.addWidget(QLabel("Slot " + str(slot_no) + ":"))
            cb = QComboBox()
            cb.addItems(opts)
            cb.setMinimumHeight(26)
            self._main_combos[slot_no] = cb
            row_h.addWidget(cb, 1)
            ll.addWidget(row_w)

        # Target stats
        ll.addWidget(self._sec("Target Stats (minimum)"))
        self._target_mode_combo = QComboBox()
        self._target_mode_combo.addItem("Total stats", userData="total")
        self._target_mode_combo.addItem("Bonus stats (+green)", userData="bonus")
        self._target_mode_combo.setMinimumHeight(26)
        self._target_mode_combo.setToolTip(
            "Total stats: targets the final in-game number.\n"
            "Bonus stats: targets the green +bonus amount for HP/ATK/DEF/SPD."
        )
        ll.addWidget(self._target_mode_combo)
        self._target_spins: dict[str, QSpinBox] = {}
        for stat in _TARGET_STATS:
            row_w = QWidget()
            row_h = QHBoxLayout(row_w)
            row_h.setContentsMargins(0, 0, 0, 0)
            row_h.setSpacing(6)
            lbl = QLabel(stat + " >=")
            lbl.setFixedWidth(52)
            sb = QSpinBox()
            sb.setRange(0, 9999)
            sb.setValue(0)
            sb.setSpecialValueText("--")
            sb.setMinimumHeight(24)
            self._target_spins[stat] = sb
            row_h.addWidget(lbl)
            row_h.addWidget(sb, 1)
            ll.addWidget(row_w)

        # Rune pool options
        ll.addWidget(self._sec("Rune Pool"))
        stars_row = QWidget()
        stars_h   = QHBoxLayout(stars_row)
        stars_h.setContentsMargins(0, 0, 0, 0)
        stars_h.addWidget(QLabel("Min stars:"))
        self._stars_combo = QComboBox()
        self._stars_combo.addItems(["4", "5", "6"])
        self._stars_combo.setCurrentIndex(1)
        self._stars_combo.setMinimumHeight(26)
        stars_h.addWidget(self._stars_combo)
        stars_h.addStretch()
        ll.addWidget(stars_row)

        self._include_chk = QCheckBox("Include runes from other monsters")
        self._include_chk.setChecked(False)
        ll.addWidget(self._include_chk)
        self._include_locked_chk = QCheckBox("Include locked runes")
        self._include_locked_chk.setChecked(False)
        self._include_locked_chk.setToolTip(
            "By default locked runes are excluded from the optimizer pool.\n"
            "Check this to allow the optimizer to consider them."
        )
        ll.addWidget(self._include_locked_chk)

        ll.addSpacerItem(QSpacerItem(0, 8, QSizePolicy.Minimum, QSizePolicy.Fixed))

        # Optimize button
        self._optimize_btn = QPushButton("Optimize")
        self._optimize_btn.setObjectName("import_btn")
        self._optimize_btn.setMinimumHeight(40)
        self._optimize_btn.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self._optimize_btn.clicked.connect(self._run_optimize)
        ll.addWidget(self._optimize_btn)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color: " + TEXT_DIM + "; font-size: 8pt;")
        self._status_lbl.setAlignment(Qt.AlignCenter)
        ll.addWidget(self._status_lbl)
        ll.addStretch()

        splitter.addWidget(left)

        self._results = _ResultsPanel()
        splitter.addWidget(self._results)
        splitter.setSizes([300, 900])

        root.addWidget(splitter, 1)

    # ------------------------------------------------------------------
    def _sec(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl.setStyleSheet("color: " + TEXT_DIM + "; margin-top: 4px;")
        return lbl

    def _load_monsters(self):
        self._monsters = queries.get_monsters(self._conn)
        self._populate_combo(self._monsters)

    def _populate_combo(self, monsters: list[dict]) -> None:
        prev_id = None
        cur = self._monster_combo.currentData()
        if isinstance(cur, dict):
            prev_id = cur.get("unit_id")
        labels = _build_labels(monsters)
        self._monster_combo.blockSignals(True)
        self._monster_combo.clear()
        for label, m in zip(labels, monsters):
            self._monster_combo.addItem(label, userData=m)
        self._monster_combo.blockSignals(False)
        if prev_id is not None:
            for i in range(self._monster_combo.count()):
                d = self._monster_combo.itemData(i)
                if isinstance(d, dict) and d.get("unit_id") == prev_id:
                    self._monster_combo.setCurrentIndex(i)
                    return
        if self._monster_combo.count():
            self._monster_combo.setCurrentIndex(0)

    def refresh(self):
        self._load_monsters()
        self._results.show_placeholder()

    # ------------------------------------------------------------------
    # Set constraint validation
    # ------------------------------------------------------------------

    def _on_ignore_sets_toggled(self, checked: bool):
        for rw in self._set_rows:
            rw.setEnabled(not checked)
            rw.setVisible(not checked)
        self._constraint_warn.setVisible(not checked)

    def _on_set_changed(self):
        selected = [cb.currentText() for cb in self._set_combos if cb.currentText()]
        total    = sum(_SET_SIZE.get(s, 2) for s in selected)
        for i, cb in enumerate(self._set_combos):
            s = cb.currentText()
            self._set_size_lbls[i].setText(str(_SET_SIZE.get(s, 2)) + "pc" if s else "")
        self._constraint_warn.setText(
            "Warning: constraints require " + str(total) + " pieces (max 6)."
            if total > 6 else ""
        )

    # ------------------------------------------------------------------
    # Run optimization
    # ------------------------------------------------------------------

    def is_task_running(self) -> bool:
        """Return whether this page currently owns a running search."""
        return is_task_running(self._worker)

    def cancel_active_task(self, timeout_ms: int = 5000) -> bool:
        """Cooperatively stop the active search before application shutdown."""
        return cancel_task(self._worker, timeout_ms)

    def _run_optimize(self):
        monster = self._monster_combo.currentData()
        if not isinstance(monster, dict):
            self._status_lbl.setText("Select a monster first.")
            return

        if self._ignore_sets_chk.isChecked():
            set_reqs = []
        else:
            set_reqs = [cb.currentText() for cb in self._set_combos if cb.currentText()]

        total_pieces = sum(_SET_SIZE.get(s, 2) for s in set_reqs)
        if total_pieces > 6:
            self._status_lbl.setText("Set constraints exceed 6 pieces.")
            return

        # Main stat constraints for even slots (ignore "Any")
        main_stat_constraints: dict[int, str] = {}
        for slot_no, cb in self._main_combos.items():
            val = cb.currentText()
            if val and val != "Any":
                main_stat_constraints[slot_no] = val

        # Target stats (ignore zeros)
        target_stats: dict[str, int] = {
            s: sb.value()
            for s, sb in self._target_spins.items()
            if sb.value() > 0
        }

        target_mode = self._target_mode_combo.currentData() or "total"

        if self._worker and self._worker.isRunning():
            self._worker.requestInterruption()
            self._optimize_btn.setEnabled(False)
            self._status_lbl.setText("Cancelling...")
            return

        self._optimize_btn.setEnabled(True)
        self._optimize_btn.setText("Cancel Search")
        self._status_lbl.setText("Optimizing...")

        from pathlib import Path
        self._worker = _OptimizeWorker(
            conn_path             = Path(self._db_path),
            unit_id               = monster.get("unit_id"),
            set_reqs              = set_reqs,
            main_stat_constraints = main_stat_constraints,
            target_stats          = target_stats,
            min_stars             = int(self._stars_combo.currentText()),
            include_equipped      = self._include_chk.isChecked(),
            include_locked        = self._include_locked_chk.isChecked(),
            target_mode           = target_mode,
        )
        self._worker.finished.connect(
            lambda res: self._on_finished(res, monster, target_stats)
        )
        self._worker.progress.connect(self._status_lbl.setText)
        self._worker.start()

    def _on_finished(self, result, monster: dict, target_stats: dict[str, int]):
        self._optimize_btn.setEnabled(True)
        self._optimize_btn.setText("Optimize")
        from optimizer.rune_optimizer import OptimizationCancelled
        if isinstance(result, OptimizationCancelled):
            self._status_lbl.setText("Search cancelled")
            return
        if isinstance(result, str):
            self._status_lbl.setText("")
            self._results.show_error(result)
            return
        n = len(result)
        self._status_lbl.setText(str(n) + " build" + ("s" if n != 1 else "") + " found")

        current_build = queries.get_monster_rune_build(
            self._conn, monster.get("unit_id")
        )

        # Fetch equipped artifact flat bonuses for this monster
        artifact_flat: dict | None = None
        uid = monster.get("unit_id")
        if uid:
            flat = {"hp": 0, "atk": 0, "def": 0}
            arts = self._conn.execute(
                "SELECT pri_effect FROM artifacts WHERE occupied_id = ?", (uid,)
            ).fetchall()
            for art in arts:
                label = (art[0] or "").strip()
                try:
                    stat_part, val_part = label.split(":", 1)
                    sp = stat_part.strip().upper()
                    v  = int(float(val_part.strip().replace(",", "")))
                    if sp == "HP":    flat["hp"]  += v
                    elif sp == "ATK": flat["atk"] += v
                    elif sp == "DEF": flat["def"] += v
                except Exception:
                    pass
            if any(v for v in flat.values()):
                artifact_flat = flat

        # Load building bonuses for this monster's element
        from desktop.db.queries import get_building_bonuses
        element = monster.get("element") or None
        try:
            building_bonuses = get_building_bonuses(self._conn, element)
        except Exception:
            building_bonuses = None

        self._results.show_results(result, monster, current_build, target_stats, artifact_flat, building_bonuses)
