"""QAbstractTableModel + sort proxy for the rune inventory table."""
from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel
from PySide6.QtGui  import QColor


COLUMNS = [
    ("slot_no",        "Slot"),
    ("set_name",       "Set"),
    ("stars",          "★"),
    ("upgrade_curr",   "+Lvl"),
    ("main_stat_name", "Main"),
    ("main_stat_value","Val"),
    ("prefix_str",     "Prefix"),
    ("subs_str",       "Substats"),
    ("efficiency",     "Eff%"),
    ("desirability",   "Desr%"),
    ("grade",          "Grade"),
    ("quality",        "Quality"),
    ("user_locked",    "Lock"),      # new — 1 if user-locked
    ("location_label", "Location"),
]

# Columns that hold numeric data — sort numerically, not lexicographically
_NUMERIC_COLS: set[int] = {0, 2, 3, 5, 8, 9}   # slot, stars, +lvl, val, eff%, desr%

_LOCK_COL = 12   # index of user_locked column in COLUMNS

GRADE_COLORS = {
    "S": "#ffd700",
    "A": "#7fff00",
    "B": "#00bfff",
    "C": "#aaaaaa",
    "D": "#ff5555",
}

# Rune quality colours (game quality, not our computed grade)
QUALITY_COLORS = {
    "Legend":         "#ffa500",
    "Ancient Legend": "#ff6600",
    "Hero":           "#9370db",
    "Ancient Hero":   "#7b00db",
    "Rare":           "#4169e1",
    "Ancient Rare":   "#3050c0",
    "Magic":          "#2e8b57",
    "Ancient Magic":  "#1a6640",
    "Normal":         "#888888",
    "Ancient Normal": "#666666",
}

# Dim tint applied to locked rows (semi-transparent red overlay)
_LOCKED_BG   = QColor(180, 40, 40, 55)
_LOCKED_TEXT = QColor(160, 100, 100)


class RuneTableModel(QAbstractTableModel):
    """
    Holds a list of rune row dicts.
    Call ``set_runes(rows)`` to replace data (triggers full reset).
    Call ``toggle_lock(row)`` to flip the user_locked flag in-place and notify views.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[dict] = []

    # ── Public API ────────────────────────────────────────────────────────────

    def set_runes(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = [_enrich(r) for r in rows]
        self.endResetModel()

    def row_data(self, row: int) -> dict | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def toggle_lock_at(self, row: int) -> bool:
        """Flip user_locked for the given row in-place; return new lock state."""
        if not (0 <= row < len(self._rows)):
            return False
        r = self._rows[row]
        new_val = 0 if r.get("user_locked") else 1
        r["user_locked"] = new_val
        # Notify the whole row — background, lock column, and substats all change
        top_left     = self.index(row, 0)
        bottom_right = self.index(row, len(COLUMNS) - 1)
        self.dataChanged.emit(top_left, bottom_right, [Qt.BackgroundRole, Qt.ForegroundRole, Qt.DisplayRole])
        return bool(new_val)

    # ── QAbstractTableModel ───────────────────────────────────────────────────

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section: int, orientation, role: int = Qt.DisplayRole) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section][1]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None

        row = self._rows[index.row()]
        key = COLUMNS[index.column()][0]
        col = index.column()
        locked = bool(row.get("user_locked"))

        if role == Qt.DisplayRole:
            if key == "user_locked":
                return "Lock" if locked else ""
            val = row.get(key)
            if key in ("efficiency", "desirability") and val is not None:
                return "%.1f" % val
            return "" if val is None else str(val)

        if role == Qt.UserRole:
            # Return numeric value for sortable numeric columns
            if col in _NUMERIC_COLS:
                try:
                    return float(row.get(key) or 0)
                except (ValueError, TypeError):
                    return 0.0
            return row

        if role == Qt.BackgroundRole:
            if locked:
                return _LOCKED_BG

        if role == Qt.ForegroundRole:
            if locked:
                # Dim all text for locked rows, except the Lock column itself
                if key != "user_locked":
                    return _LOCKED_TEXT
                return QColor("#e05c5c")   # red lock label
            if key == "grade":
                color = GRADE_COLORS.get(row.get("grade", ""))
                if color:
                    return QColor(color)
            if key == "quality":
                q = row.get("quality") or ""
                color = QUALITY_COLORS.get(q)
                if color:
                    return QColor(color)

        if role == Qt.TextAlignmentRole:
            if key in ("slot_no", "stars", "upgrade_curr", "main_stat_value",
                       "efficiency", "desirability", "grade", "quality", "user_locked"):
                return Qt.AlignCenter

        return None


class RuneSortProxy(QSortFilterProxyModel):
    """
    Proxy that sorts numeric columns by value rather than string.
    Attach to a RuneTableModel for correct header-click sorting.

    Optional hide_locked flag: when True, filters out user_locked rows.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._hide_locked = False

    def set_hide_locked(self, hide: bool) -> None:
        if self._hide_locked != hide:
            self._hide_locked = hide
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if self._hide_locked:
            src = self.sourceModel()
            r = src.row_data(source_row)
            if r and r.get("user_locked"):
                return False
        return super().filterAcceptsRow(source_row, source_parent)

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        col = left.column()
        if col in _NUMERIC_COLS:
            lv = self.sourceModel().data(left,  Qt.UserRole)
            rv = self.sourceModel().data(right, Qt.UserRole)
            try:
                return float(lv or 0) < float(rv or 0)
            except (ValueError, TypeError):
                pass
        return super().lessThan(left, right)


# ── Helper ────────────────────────────────────────────────────────────────────

def _enrich(row: dict) -> dict:
    """Add derived display-only fields to a raw DB row dict."""
    r = dict(row)

    pfx_name = r.get("prefix_stat_name") or ""
    pfx_val  = r.get("prefix_stat_value")
    if pfx_name and pfx_val:
        r["prefix_str"] = pfx_name + " +" + str(pfx_val)
    else:
        r["prefix_str"] = ""

    raw_subs = r.get("substat_labels", "[]")
    try:
        subs: list[str] = json.loads(raw_subs) if isinstance(raw_subs, str) else (raw_subs or [])
    except (ValueError, TypeError):
        subs = []
    r["subs_str"] = "  \xb7  ".join(subs)

    # Ensure user_locked is always present as int
    r.setdefault("user_locked", 0)

    return r
