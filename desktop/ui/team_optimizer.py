"""Team Optimizer panel.

Left:  dungeon picker + turn order plan + 5 monster slots + rune pool config.
Right: turn order visualization + per-monster build cards with final stats.
"""
from __future__ import annotations

import heapq
import json as _json
import sqlite3
import sys
from collections import Counter
from typing import NamedTuple

from PySide6.QtCore    import Qt, QThread, Signal
from PySide6.QtGui     import QFont
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QComboBox, QCheckBox, QFrame, QScrollArea, QGridLayout,
    QSizePolicy, QSpacerItem, QSplitter, QLineEdit, QSpinBox,
    QGroupBox, QDoubleSpinBox,
)

from desktop.db import queries
from desktop.task_lifecycle import cancel_task, is_task_running
from optimizer.dungeon_profiles import (
    DUNGEON_PROFILES, ROLES, ROLE_KEY, TARGET_STAT_KEYS,
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

_SET_SIZE: dict[str, int] = {
    "Violent": 4, "Swift": 4, "Rage": 4,
    "Despair": 4, "Vampire": 4, "Fatal": 4,
    "Will": 2, "Energy": 2, "Guard": 2, "Endure": 2, "Blade": 2,
    "Focus": 2, "Shield": 2, "Revenge": 2, "Nemesis": 2,
    "Destroy": 2, "Fight": 2, "Determination": 2,
    "Enhance": 2, "Accuracy": 2, "Tolerance": 2,
}

# Set stat bonuses live in ONE place: optimizer.stat_utils.SET_STAT_BONUS.
# (The old local copy here had wrong values — e.g. Violent does NOT give +SPD.)

_SLOT2_MAINS = ["Any", "SPD", "HP%", "ATK%", "DEF%"]
_SLOT4_MAINS = ["Any", "CR%", "CD%", "HP%", "ATK%", "DEF%"]
_SLOT6_MAINS = ["Any", "HP%", "ATK%", "DEF%", "RES%", "ACC%"]

_GRADE_COLOR = {
    "S": "#ffd700", "A": "#c792ea", "B": "#5c9cf5",
    "C": "#4caf72", "D": "#888888",
}

_TEAM_COLORS = ["#3fb950", "#5c9cf5", "#c792ea", "#e8c84a", "#ff9800"]
_ENEMY_COLOR = "#e05c5c"
_ENEMY_DARK  = "rgba(224,92,92,0.15)"

TEXT_DIM  = "#8b949e"
TEXT_MAIN = "#c9d1d9"
BG_CARD   = "#161b22"
BG_PANEL  = "#0d1117"
COL_OK    = "#3fb950"
COL_WARN  = "#e8c84a"
COL_FAIL  = "#e05c5c"

MAX_SLOTS      = 5
TURN_SIM_COUNT = 25

_TO_EMPTY   = "--"
_TO_ENEMY   = "Enemy"
_TO_SLOTS   = ["S1", "S2", "S3", "S4", "S5"]
_TO_OPTIONS = [_TO_EMPTY, _TO_ENEMY] + _TO_SLOTS
_TO_DEFAULTS = _TO_SLOTS + [_TO_ENEMY]


# ---------------------------------------------------------------------------
# Stat helpers
# ---------------------------------------------------------------------------

_MID_FLAT = {1: "hp", 3: "atk", 5: "def"}
_MID_PCT  = {2: "hp", 4: "atk", 6: "def"}
_MID_ADD  = {8: "spd", 9: "cr", 10: "cd", 11: "res", 12: "acc"}

_PNAME_TO_ID: dict[str, int] = {
    "HP+": 1, "HP%": 2, "ATK+": 3, "ATK%": 4, "DEF+": 5, "DEF%": 6,
    "SPD": 8, "CR%": 9, "CD%": 10, "RES%": 11, "ACC%": 12,
}


def _compute_final_stats(
    monster_info: dict,
    build,
    artifact_flat: dict | None = None,
    building_bonuses: dict | None = None,
) -> dict:
    """Delegate to shared stat_utils.compute_final_stats (includes building bonuses)."""
    from optimizer.stat_utils import compute_final_stats as _cfs
    return _cfs(monster_info, build, artifact_flat, building_bonuses)


def _fmt_k(n: int) -> str:
    """Format a large integer as '23.5k' or plain number."""
    if n >= 10_000:
        return str(round(n / 1000, 1)) + "k"
    return str(n)


# ---------------------------------------------------------------------------
# Label helper
# ---------------------------------------------------------------------------

def _build_labels(monsters: list[dict]) -> list[str]:
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
# Turn order simulation
# ---------------------------------------------------------------------------

class TurnEntry(NamedTuple):
    name:    str
    spd:     int
    is_team: bool
    color:   str


def simulate_turns(units: list[TurnEntry], n: int = TURN_SIM_COUNT) -> list[TurnEntry]:
    if not units:
        return []
    heap: list[tuple] = []
    for i, u in enumerate(units):
        if u.spd > 0:
            heapq.heappush(heap, (10000.0 / u.spd, i, u))
    result: list[TurnEntry] = []
    while heap and len(result) < n:
        t, idx, u = heapq.heappop(heap)
        result.append(u)
        heapq.heappush(heap, (t + 10000.0 / u.spd, idx, u))
    return result


def _estimate_spd(mr, base_spd: int) -> int:
    """Fallback SPD estimate. build.stat_totals['SPD'] already includes main
    stats, so nothing may be added on top (the old code double-counted the
    slot-2 main stat)."""
    build = mr.build
    if not build:
        return base_spd
    if build.final_stats:
        return int(build.final_stats.get("spd", base_spd))
    sub_spd = build.stat_totals.get("SPD", 0) if build.stat_totals else 0
    return base_spd + sub_spd


# ---------------------------------------------------------------------------
# Turn order visual widget
# ---------------------------------------------------------------------------

def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"{r},{g},{b},{alpha}"


class _TurnChip(QLabel):
    def __init__(self, entry: TurnEntry, turn_num: int, parent=None):
        abbr = (entry.name[:9] + "...") if len(entry.name) > 9 else entry.name
        super().__init__(abbr, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(90, 40)
        c = entry.color
        self.setFont(QFont("Segoe UI", 7, QFont.Bold))
        self.setToolTip("#" + str(turn_num) + "  " + entry.name + "  (SPD " + str(entry.spd) + ")")
        if entry.is_team:
            self.setStyleSheet(
                "background: rgba(" + _hex_to_rgba(c, 0.18) + ");"
                " color: " + c + ";"
                " border: 1px solid rgba(" + _hex_to_rgba(c, 0.45) + ");"
                " border-radius: 5px; padding: 2px 3px;"
            )
        else:
            self.setStyleSheet(
                "background: " + _ENEMY_DARK + "; color: " + _ENEMY_COLOR + ";"
                " border: 1px solid rgba(224,92,92,0.35);"
                " border-radius: 5px; padding: 2px 3px;"
            )


class _TurnOrderWidget(QFrame):
    def __init__(self, units: list[TurnEntry], dungeon_name: str = "", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "QFrame { background: " + BG_CARD + "; border: 1px solid #2d333b; border-radius: 6px; }"
            "QLabel { border: none; }"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(6)

        hdr = QHBoxLayout()
        title = QLabel("Turn Order")
        title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        title.setStyleSheet("color: " + TEXT_MAIN + ";")
        hdr.addWidget(title)
        hdr.addStretch()

        turns = simulate_turns(units, TURN_SIM_COUNT)
        first_enemy = next((i for i, t in enumerate(turns) if not t.is_team), None)
        first_team  = next((i for i, t in enumerate(turns) if t.is_team),  None)
        enemy_first = first_enemy is not None and (first_team is None or first_enemy < first_team)

        badge_text  = "  Enemy moves first!" if enemy_first else "  Team has first move"
        badge_color = _ENEMY_COLOR if enemy_first else COL_OK
        badge_bg    = "rgba(224,92,92," if enemy_first else "rgba(63,185,80,"
        badge = QLabel(badge_text)
        badge.setFont(QFont("Segoe UI", 8, QFont.Bold if enemy_first else QFont.Normal))
        badge.setStyleSheet(
            "color: " + badge_color + "; background: " + badge_bg + "0.08);"
            " border: 1px solid " + badge_bg + "0.3); border-radius: 3px; padding: 1px 7px;"
        )
        hdr.addWidget(badge)
        root.addLayout(hdr)

        legend = QHBoxLayout()
        legend.setSpacing(8)
        shown: set[str] = set()
        for u in units:
            if u.name in shown:
                continue
            shown.add(u.name)
            lbl = QLabel(u.name + " " + str(u.spd))
            lbl.setFont(QFont("Segoe UI", 7))
            lbl.setStyleSheet(
                "color: " + u.color + "; background: rgba(" + _hex_to_rgba(u.color, 0.12) + ");"
                " border-radius: 3px; padding: 1px 5px;"
            )
            legend.addWidget(lbl)
        legend.addStretch()
        root.addWidget(self._wrap(legend))

        chips_scroll = QScrollArea()
        chips_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        chips_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        chips_scroll.setFixedHeight(56)
        chips_scroll.setFrameShape(QFrame.NoFrame)
        chips_scroll.setWidgetResizable(False)
        chips_w = QWidget()
        chips_row = QHBoxLayout(chips_w)
        chips_row.setContentsMargins(0, 4, 0, 4)
        chips_row.setSpacing(4)
        for turn_num, entry in enumerate(turns, 1):
            chips_row.addWidget(_TurnChip(entry, turn_num))
        chips_row.addStretch()
        chips_w.setFixedWidth(max(60, len(turns) * 94))
        chips_scroll.setWidget(chips_w)
        root.addWidget(chips_scroll)

        summary: dict[str, int] = {}
        for t in turns:
            summary[t.name] = summary.get(t.name, 0) + 1
        counts_row = QHBoxLayout()
        counts_row.setSpacing(10)
        for u in [x for x in units if x.is_team] + [x for x in units if not x.is_team]:
            cnt = summary.get(u.name, 0)
            lbl = QLabel(u.name[:8] + ": " + str(cnt) + "t")
            lbl.setFont(QFont("Segoe UI", 7))
            lbl.setStyleSheet("color: " + u.color + ";")
            lbl.setToolTip(u.name + " takes " + str(cnt) + " turns in first " + str(TURN_SIM_COUNT))
            counts_row.addWidget(lbl)
        counts_row.addStretch()
        root.addWidget(self._wrap(counts_row))

    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------

class _TeamWorker(QThread):
    # Emits (TeamResult, base_spd_map, monster_data_map, artifact_flat_map,
    # bonuses_map) or an error string
    finished = Signal(object)
    progress = Signal(str)

    def __init__(self, conn_path, slot_configs, min_stars, include_equipped,
                 include_locked=False, leader=None, turn_positions=None,
                 enemy_rank=None, enemy_spd=0, assume_max=True,
                 dungeon_key="custom", optimize_artifacts=True):
        super().__init__()
        self._conn_path        = conn_path
        self._slot_configs     = slot_configs
        self._min_stars        = min_stars
        self._include_equipped = include_equipped
        self._include_locked   = include_locked
        self._assume_max       = assume_max
        self._leader           = leader          # leader monster dict or None
        self._turn_positions   = turn_positions or {}   # slot_index -> rank
        self._enemy_rank       = enemy_rank      # rank of "Enemy" in the plan
        self._enemy_spd        = enemy_spd
        self._dungeon_key       = dungeon_key
        self._optimize_artifacts = optimize_artifacts

    def run(self):
        conn = None
        try:
            from desktop.db.schema import get_connection
            from optimizer.team_optimizer import optimize_team, MonsterRequest

            conn = get_connection(self._conn_path)
            all_unit_ids = [s["unit_id"] for s in self._slot_configs if s.get("unit_id")]

            # Always fetch equipped runes too: the team's OWN runes must be
            # available to the team (otherwise the optimizer can't even
            # reproduce the current builds). The checkbox only controls
            # whether runes on NON-team monsters may be taken.
            pool = queries.get_rune_pool(
                conn,
                min_stars        = self._min_stars,
                include_equipped = True,
                exclude_unit_id  = None,
                exclude_user_locked = not self._include_locked,
            )
            team_id_set = set(all_unit_ids)
            if not self._include_equipped:
                pool = [r for r in pool
                        if not r.get("occupied_id")
                        or r["occupied_id"] in team_id_set]

            all_monsters = queries.get_monsters(conn)
            base_spd_map: dict[int, int] = {m["unit_id"]: (m.get("base_speed") or 0) for m in all_monsters}

            # Full monster data for final stat computation
            monster_data_map: dict[int, dict] = {m["unit_id"]: dict(m) for m in all_monsters}

            # Equipped artifact bonuses, including structured secondary effects.
            from optimizer.artifact_optimizer import ArtifactProfile
            _dungeon_profile = DUNGEON_PROFILES.get(self._dungeon_key, {})
            from optimizer.dungeon_data import load_dungeon_profile_waves
            dungeon_waves = load_dungeon_profile_waves(self._dungeon_key)
            _artifact_profile = ArtifactProfile(
                goal="damage",
                target_element=_dungeon_profile.get("boss_element") or None,
                single_target=True,
                enemy_hp_ratio=1.0,
            )
            artifact_flat_map: dict[int, dict] = {}
            for uid in all_unit_ids:
                bonus = queries.get_monster_artifact_bonuses(
                    conn,
                    uid,
                    _artifact_profile,
                )
                if any(bonus.values()):
                    artifact_flat_map[uid] = bonus

            from desktop.db.queries import get_building_bonuses, compute_leader_bonus
            from optimizer.stat_utils import merge_bonuses

            requests = []
            bonuses_map: dict[int, dict] = {}
            for cfg in self._slot_configs:
                uid = cfg.get("unit_id")
                if not uid:
                    continue
                current_build = queries.get_monster_rune_build(conn, uid)
                _minfo = monster_data_map.get(uid, {})
                _elem  = _minfo.get("element")
                # element-aware building bonuses + leader skill bonus
                try:
                    _bld = get_building_bonuses(conn, _elem)
                except Exception:
                    _bld = None
                _ldr = compute_leader_bonus(self._leader, _elem)
                _bb  = merge_bonuses(_bld, _ldr)
                bonuses_map[uid] = _bb

                # Estimate ref stats for EO scoring from the monster's base stats
                _ref_atk = float(_minfo.get("max_lvl_attack", 0) or 3000) * 1.8
                _ref_cr  = float(_minfo.get("crit_rate", 15) or 15) + 70.0
                _ref_cd  = float(_minfo.get("crit_damage", 50) or 50) + 150.0

                # Planned turn position + enemy-relative SPD constraints
                _slot_idx = cfg.get("slot_index")
                _tpos = self._turn_positions.get(_slot_idx)
                _tstats = dict(cfg.get("target_stats", {}))
                _target_mode = str(cfg.get("target_mode") or "total")
                _mstats = {}
                if _tpos is not None and self._enemy_rank is not None and self._enemy_spd:
                    if _tpos < self._enemy_rank:
                        _tstats["SPD"] = max(int(_tstats.get("SPD", 0) or 0),
                                             self._enemy_spd + 1)
                    elif _tpos > self._enemy_rank:
                        _mstats["SPD"] = self._enemy_spd - 1

                requests.append(MonsterRequest(
                    unit_id               = uid,
                    display_name          = cfg.get("display_name", "?"),
                    priority              = cfg.get("priority", 99),
                    set_reqs              = cfg.get("set_reqs", []),
                    main_stat_constraints = cfg.get("main_stat_constraints", {}),
                    target_stats          = _tstats,
                    current_build         = current_build,
                    target_mode           = _target_mode,
                    scoring_mode          = cfg.get("scoring_mode", "desirability"),
                    ref_atk               = _ref_atk,
                    ref_cr                = min(100.0, _ref_cr),
                    ref_cd                = _ref_cd,
                    monster_info          = _minfo or None,
                    artifact_flat         = artifact_flat_map.get(uid),
                    bonuses               = _bb,
                    turn_pos              = _tpos,
                    max_stats             = _mstats or None,
                    assume_max            = self._assume_max,
                    combat_role          = str(
                        cfg.get("role") or "attacker"
                    ).lower(),
                    skill_atk_multiplier = float(
                        cfg.get("skill_atk_multiplier", 3.0) or 0
                    ),
                    skill_hp_multiplier  = float(cfg.get("skill_hp_multiplier", 0) or 0),
                    skill_def_multiplier = float(cfg.get("skill_def_multiplier", 0) or 0),
                    skill_spd_multiplier = float(cfg.get("skill_spd_multiplier", 0) or 0),
                    skill_target_hp_multiplier = float(
                        cfg.get("skill_target_hp_multiplier", 0) or 0
                    ),
                    skill_flat_damage    = float(cfg.get("skill_flat_damage", 0) or 0),
                    skillup_bonus_pct    = float(cfg.get("skillup_bonus_pct", 0) or 0),
                    skill_ignore_defense = bool(cfg.get("skill_ignore_defense", False)),
                    skill_hits           = int(cfg.get("skill_hits", 1) or 1),
                    skill_aoe            = bool(cfg.get("skill_aoe", False)),
                    provides_defense_break = bool(
                        cfg.get("provides_defense_break", False)
                    ),
                    provides_atk_buff      = bool(
                        cfg.get("provides_atk_buff", False)
                    ),
                    provides_brand         = bool(cfg.get("provides_brand", False)),
                    provides_healing       = bool(
                        cfg.get("provides_healing", "healer" in str(cfg.get("role", "")).lower())
                    ),
                    provides_control       = bool(cfg.get("provides_control", False)),
                    skill_cooldown         = int(cfg.get("skill_cooldown", 1) or 1),
                    skill_effect_chance    = float(
                        cfg.get("skill_effect_chance", 100.0) or 0
                    ),
                ))

            # Compute current (pre-optimization) stats for each monster
            current_stats_map: dict[int, dict] = {}
            from optimizer.stat_utils import compute_stats_from_equipped
            for cfg in self._slot_configs:
                uid = cfg.get("unit_id")
                if not uid:
                    continue
                curr_build = queries.get_monster_rune_build(conn, uid)
                minfo = monster_data_map.get(uid, {})
                art   = artifact_flat_map.get(uid)
                bb    = bonuses_map.get(uid)
                try:
                    current_stats_map[uid] = compute_stats_from_equipped(
                        minfo, curr_build, art, bb
                    )
                except Exception:
                    pass

            self.progress.emit("Searching joint rune allocations...")
            result = optimize_team(
                pool,
                requests,
                dungeon_waves=dungeon_waves,
                cancel_check=self.isInterruptionRequested,
                progress_callback=lambda done, total, message: self.progress.emit(
                    "%s (%d/%d)" % (message, done, total)
                ),
            )
            if self.isInterruptionRequested():
                from optimizer.rune_optimizer import OptimizationCancelled
                raise OptimizationCancelled("Optimization cancelled")
            artifact_pair_map = {}
            if self._optimize_artifacts:
                from optimizer.artifact_optimizer import (
                    ArtifactRequest,
                    optimize_team_artifacts,
                )
                from optimizer.stat_utils import compute_final_stats

                config_by_uid = {
                    cfg.get("unit_id"): cfg
                    for cfg in self._slot_configs
                    if cfg.get("unit_id")
                }
                artifact_pool = queries.get_artifacts(conn)
                if not self._include_equipped:
                    artifact_pool = [
                        artifact
                        for artifact in artifact_pool
                        if not artifact.get("occupied_id")
                        or artifact.get("occupied_id") in team_id_set
                    ]

                artifact_requests = []
                for monster_result in result.monsters:
                    if not monster_result.build:
                        continue
                    uid = monster_result.unit_id
                    config = config_by_uid.get(uid, {})
                    role = str(config.get("role") or "").lower()
                    if "tank" in role:
                        artifact_goal = "survivability"
                    elif "support" in role or "healer" in role:
                        artifact_goal = "support"
                    elif config.get("scoring_mode") == "effective_offense":
                        artifact_goal = "damage"
                    else:
                        artifact_goal = "balanced"
                    baseline_stats = compute_final_stats(
                        monster_data_map.get(uid, {}),
                        monster_result.build,
                        None,
                        bonuses_map.get(uid),
                    )
                    artifact_requests.append(
                        ArtifactRequest(
                            unit_id=uid,
                            display_name=monster_result.display_name,
                            monster_info=monster_data_map.get(uid, {}),
                            stats=baseline_stats,
                            profile=ArtifactProfile(
                                goal=artifact_goal,
                                target_element=_dungeon_profile.get("boss_element") or None,
                                skill_number=3 if artifact_goal == "damage" else None,
                                single_target=True,
                                first_attack=artifact_goal == "damage",
                                enemy_hp_ratio=1.0,
                            ),
                        )
                    )

                if artifact_requests:
                    self.progress.emit("Allocating artifact pairs...")
                    artifact_team = optimize_team_artifacts(
                        artifact_pool,
                        artifact_requests,
                        top_n_per_monster=8,
                        cancel_check=self.isInterruptionRequested,
                        progress_callback=lambda done, total, message: self.progress.emit(
                            "%s (%d/%d)" % (message, done, total)
                        ),
                    )
                    artifact_pair_map = {
                        member.unit_id: member.pair
                        for member in artifact_team.members
                        if member.pair is not None
                    }
                    updated_monsters = []
                    for monster_result in result.monsters:
                        pair = artifact_pair_map.get(monster_result.unit_id)
                        if pair is None or monster_result.build is None:
                            updated_monsters.append(monster_result)
                            continue
                        uid = monster_result.unit_id
                        artifact_flat_map[uid] = pair.bonuses
                        updated_stats = compute_final_stats(
                            monster_data_map.get(uid, {}),
                            monster_result.build,
                            pair.bonuses,
                            bonuses_map.get(uid),
                        )
                        updated_build = monster_result.build._replace(
                            final_stats=updated_stats
                        )
                        updated_monsters.append(
                            monster_result._replace(build=updated_build)
                        )
                    result = result._replace(monsters=updated_monsters)

            from optimizer.team_optimizer import score_team_for_dungeon
            final_requests = [
                request._replace(
                    artifact_flat=artifact_flat_map.get(request.unit_id)
                )
                for request in requests
            ]
            final_dungeon_evaluation = score_team_for_dungeon(
                result.monsters,
                final_requests,
                dungeon_waves,
            )
            if final_dungeon_evaluation is not None:
                from optimizer.dungeon_simulator import simulate_dungeon_runs
                from optimizer.team_optimizer import build_dungeon_combatants
                simulation_members = build_dungeon_combatants(
                    result.monsters,
                    final_requests,
                )
                simulation_seed = sum(
                    request.unit_id for request in final_requests
                ) % (2 ** 32)
                self.progress.emit("Simulating dungeon clears...")
                simulated_success = simulate_dungeon_runs(
                    final_dungeon_evaluation,
                    trials=2000,
                    seed=simulation_seed,
                    cancel_check=self.isInterruptionRequested,
                    members=simulation_members,
                    waves=dungeon_waves,
                )
                result = result._replace(
                    dungeon_score=final_dungeon_evaluation.readiness_score,
                    estimated_success=simulated_success,
                    dungeon_evaluation=final_dungeon_evaluation,
                )

            if conn is not None:
                conn.close()
                conn = None
            self.finished.emit((result, base_spd_map, monster_data_map,
                                artifact_flat_map, bonuses_map, current_stats_map,
                                artifact_pair_map))

        except Exception as exc:
            from optimizer.rune_optimizer import OptimizationCancelled
            if isinstance(exc, OptimizationCancelled):
                self.finished.emit(exc)
            else:
                import traceback
                self.finished.emit(str(exc) + "\n" + traceback.format_exc())
        finally:
            if conn is not None:
                conn.close()


# ---------------------------------------------------------------------------
# Focus-aware spinbox (scroll wheel only works after the user clicks it)
# ---------------------------------------------------------------------------

class _FocusSpinBox(QSpinBox):
    """Scroll wheel only changes value after the user clicks the spinbox.

    Root cause: QSpinBox default focus policy includes Qt.WheelFocus, which
    grants the widget focus *before* wheelEvent() fires — so hasFocus() returns
    True even on a first hover-scroll. Setting Qt.StrongFocus removes WheelFocus
    from the policy, so the spinbox only gets focus from explicit clicks/Tab.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


# ---------------------------------------------------------------------------
# Monster slot config widget
# ---------------------------------------------------------------------------

class _MonsterSlotWidget(QGroupBox):
    monster_changed = Signal()  # emitted whenever the selected monster changes

    def __init__(self, slot_index: int, monsters: list[dict], parent=None):
        super().__init__("Slot " + str(slot_index + 1), parent)
        self._monsters   = list(monsters)
        self._slot_index = slot_index
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(8, 6, 8, 8)

        top_row = QHBoxLayout()
        self._combo = QComboBox()
        self._combo.setEditable(True)
        self._combo.setInsertPolicy(QComboBox.NoInsert)
        self._combo.setMinimumHeight(26)
        self._combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._combo.lineEdit().setPlaceholderText("Search monster...")
        _c = self._combo.completer()
        if _c:
            _c.setFilterMode(Qt.MatchContains)
            _c.setCaseSensitivity(Qt.CaseInsensitive)
        top_row.addWidget(self._combo, 1)
        self._combo.currentIndexChanged.connect(self._on_monster_changed)

        self._role_combo = QComboBox()
        self._role_combo.addItems(["-- none --"] + ROLES)
        self._role_combo.setFixedWidth(88)
        self._role_combo.setMinimumHeight(26)
        self._role_combo.currentTextChanged.connect(self._on_role_changed)
        top_row.addWidget(self._role_combo)
        layout.addLayout(top_row)

        pri_row = QHBoxLayout()
        pri_lbl = QLabel("Pool priority:")
        pri_lbl.setFont(QFont("Segoe UI", 8))
        pri_lbl.setStyleSheet("color: " + TEXT_DIM + ";")
        pri_row.addWidget(pri_lbl)
        self._priority_spin = _FocusSpinBox()
        self._priority_spin.setRange(1, MAX_SLOTS)
        self._priority_spin.setValue(self._slot_index + 1)
        self._priority_spin.setFixedWidth(46)
        self._priority_spin.setMinimumHeight(24)
        pri_row.addWidget(self._priority_spin)
        pri_row.addStretch()
        layout.addLayout(pri_row)

        # 3 set dropdowns for full 6-slot coverage (3 x 2-set or 4+2)
        sets_row = QHBoxLayout()
        sets_row.setSpacing(4)
        self._set_combos: list[QComboBox] = []
        for _ in range(3):
            cb = QComboBox()
            cb.addItems(_ALL_SETS)
            cb.setMinimumHeight(24)
            self._set_combos.append(cb)
            sets_row.addWidget(cb, 1)
        layout.addLayout(sets_row)

        mains_row = QHBoxLayout()
        self._main_combos: dict[int, QComboBox] = {}
        for slot_no, opts in [(2, _SLOT2_MAINS), (4, _SLOT4_MAINS), (6, _SLOT6_MAINS)]:
            lbl = QLabel(str(slot_no) + ":")
            lbl.setFont(QFont("Segoe UI", 7))
            lbl.setStyleSheet("color: " + TEXT_DIM + ";")
            lbl.setFixedWidth(14)
            cb = QComboBox()
            cb.addItems(opts)
            cb.setMinimumHeight(22)
            cb.setFixedWidth(78)
            self._main_combos[slot_no] = cb
            mains_row.addWidget(lbl)
            mains_row.addWidget(cb)
        layout.addLayout(mains_row)

        mode_row = QHBoxLayout()
        mode_lbl = QLabel("Targets:")
        mode_lbl.setFont(QFont("Segoe UI", 7))
        mode_lbl.setStyleSheet("color: " + TEXT_DIM + ";")
        self._target_mode_combo = QComboBox()
        self._target_mode_combo.addItem("Total stats", userData="total")
        self._target_mode_combo.addItem("Bonus stats (+green)", userData="bonus")
        self._target_mode_combo.setMinimumHeight(22)
        self._target_mode_combo.setToolTip(
            "Total stats: targets the final in-game number.\n"
            "Bonus stats: targets the green +bonus amount for HP/ATK/DEF/SPD."
        )
        mode_row.addWidget(mode_lbl)
        mode_row.addWidget(self._target_mode_combo, 1)
        layout.addLayout(mode_row)

        self._target_spins: dict[str, QSpinBox] = {}
        stats_grid = QGridLayout()
        stats_grid.setSpacing(3)
        for i, stat in enumerate(TARGET_STAT_KEYS):
            lbl = QLabel(stat + ">=")
            lbl.setFont(QFont("Segoe UI", 7))
            lbl.setStyleSheet("color: " + TEXT_DIM + ";")
            sb = _FocusSpinBox()
            sb.setRange(0, 9999)
            sb.setValue(0)
            sb.setSpecialValueText("--")
            sb.setMinimumHeight(22)
            self._target_spins[stat] = sb
            row, col = divmod(i, 2)
            stats_grid.addWidget(lbl, row, col * 2)
            stats_grid.addWidget(sb,  row, col * 2 + 1)
        layout.addLayout(stats_grid)

        # Scoring mode
        score_row = QHBoxLayout()
        score_lbl = QLabel("Score by:")
        score_lbl.setFont(QFont("Segoe UI", 7))
        score_lbl.setStyleSheet("color: " + TEXT_DIM + ";")
        score_row.addWidget(score_lbl)
        self._scoring_combo = QComboBox()
        self._scoring_combo.addItem("Best Runes (desirability)",  userData="desirability")
        self._scoring_combo.addItem("Max Damage (Eff. Offense)",  userData="effective_offense")
        self._scoring_combo.setMinimumHeight(22)
        self._scoring_combo.setToolTip(
            "Best Runes: ranks by rune desirability score (balanced quality).\n"
            "Max Damage: ranks by Effective Offense contribution — maximises\n"
            "ATK × [1 + (CR/100) × (CD/100 - 1)]. Use for pure damage dealers."
        )
        score_row.addWidget(self._scoring_combo, 1)
        layout.addLayout(score_row)

        skill_row = QHBoxLayout()
        skill_row.setSpacing(4)
        skill_label = QLabel("Dungeon skill:")
        skill_label.setFont(QFont("Segoe UI", 7))
        skill_label.setStyleSheet("color: " + TEXT_DIM + ";")
        skill_row.addWidget(skill_label)

        self._skill_combo = QComboBox()
        self._skill_combo.addItem("Manual", None)
        self._skill_combo.setMinimumWidth(130)
        self._skill_combo.currentIndexChanged.connect(self._apply_skill_profile)
        skill_row.addWidget(self._skill_combo)

        self._skill_atk_spin = QDoubleSpinBox()
        self._skill_atk_spin.setRange(0.0, 20.0)
        self._skill_atk_spin.setDecimals(2)
        self._skill_atk_spin.setSingleStep(0.1)
        self._skill_atk_spin.setValue(3.0)
        self._skill_atk_spin.setPrefix("ATK ")
        self._skill_atk_spin.setSuffix("x")
        self._skill_atk_spin.setFixedWidth(84)
        skill_row.addWidget(self._skill_atk_spin)

        self._skill_hits_spin = _FocusSpinBox()
        self._skill_hits_spin.setRange(1, 20)
        self._skill_hits_spin.setValue(1)
        self._skill_hits_spin.setPrefix("Hits ")
        self._skill_hits_spin.setFixedWidth(72)
        skill_row.addWidget(self._skill_hits_spin)

        skill_row.addStretch()
        layout.addLayout(skill_row)

        skill_flags = QHBoxLayout()
        skill_flags.setSpacing(10)
        skill_flags.addSpacing(skill_label.sizeHint().width())
        self._skill_aoe_check = QCheckBox("AOE")
        self._def_break_check = QCheckBox("DEF break")
        self._atk_buff_check = QCheckBox("ATK buff")
        skill_flags.addWidget(self._skill_aoe_check)
        skill_flags.addWidget(self._def_break_check)
        skill_flags.addWidget(self._atk_buff_check)
        skill_flags.addStretch()
        layout.addLayout(skill_flags)

        self._populate_combo(self._monsters)

    def _on_monster_changed(self) -> None:
        self._populate_skill_combo()
        self.monster_changed.emit()

    def _populate_skill_combo(self) -> None:
        from dataclasses import asdict
        from src.core.skills.skill_library import monster_skill_profiles

        monster = self._combo.currentData()
        selected = self._skill_combo.currentData()
        selected_id = selected.get("skill_id") if isinstance(selected, dict) else None
        profiles = []
        if isinstance(monster, dict):
            profiles = [
                asdict(profile)
                for profile in monster_skill_profiles(
                    monster.get("skills") or [],
                    monster.get("skill_levels") or {},
                )
                if profile.supported
            ]
        self._skill_combo.blockSignals(True)
        try:
            self._skill_combo.clear()
            self._skill_combo.addItem("Manual", None)
            for profile in profiles:
                self._skill_combo.addItem(
                    "S%s %s" % (profile.get("slot", "?"), profile.get("name", "Skill")),
                    profile,
                )
            index = 1 if profiles else 0
            if selected_id is not None:
                for candidate in range(1, self._skill_combo.count()):
                    data = self._skill_combo.itemData(candidate)
                    if isinstance(data, dict) and data.get("skill_id") == selected_id:
                        index = candidate
                        break
            self._skill_combo.setCurrentIndex(index)
        finally:
            self._skill_combo.blockSignals(False)
        self._apply_skill_profile()

    def _apply_skill_profile(self) -> None:
        profile = self._skill_combo.currentData()
        if not isinstance(profile, dict):
            self._skill_combo.setToolTip("Manual dungeon combat assumptions.")
            return
        self._skill_atk_spin.setValue(float(profile.get("atk") or 0.0))
        self._skill_hits_spin.setValue(max(1, int(profile.get("hits") or 1)))
        self._skill_aoe_check.setChecked(bool(profile.get("aoe", False)))
        self._def_break_check.setChecked(bool(profile.get("provides_defense_break", False)))
        self._atk_buff_check.setChecked(bool(profile.get("provides_atk_buff", False)))
        self._skill_combo.setToolTip(
            "%s | Level %s/%s | Skill-up damage +%s%%"
            % (
                profile.get("formula") or "No formula",
                profile.get("level", 1),
                profile.get("max_level", 1),
                profile.get("skillup_bonus_pct", 0),
            )
            + " | Cooldown %s turn%s"
            % (
                profile.get("cooldown", 1),
                "" if profile.get("cooldown", 1) == 1 else "s",
            )
        )

    def _populate_combo(self, monsters: list[dict]):
        prev_id = None
        cur = self._combo.currentData()
        if isinstance(cur, dict):
            prev_id = cur.get("unit_id")
        labels = _build_labels(monsters)
        self._combo.blockSignals(True)
        self._combo.clear()
        for label, m in zip(labels, monsters):
            self._combo.addItem(label, userData=m)
        self._combo.blockSignals(False)
        if prev_id is not None:
            for i in range(self._combo.count()):
                d = self._combo.itemData(i)
                if isinstance(d, dict) and d.get("unit_id") == prev_id:
                    self._combo.setCurrentIndex(i)
                    self._populate_skill_combo()
                    return
        self._combo.setCurrentIndex(-1)
        self._combo.lineEdit().clear()
        self._populate_skill_combo()

    def set_monsters(self, monsters: list[dict]):
        self._monsters = list(monsters)
        self._populate_combo(self._monsters)

    def _on_role_changed(self, role_display: str) -> None:
        role = role_display.lower()
        if isinstance(self._skill_combo.currentData(), dict):
            if "attacker" in role:
                self._scoring_combo.setCurrentIndex(1)
            return
        if "attacker" in role:
            self._skill_atk_spin.setValue(4.0)
            self._skill_aoe_check.setChecked(True)
            self._def_break_check.setChecked(False)
            self._atk_buff_check.setChecked(False)
            self._scoring_combo.setCurrentIndex(1)
        elif "support" in role:
            self._skill_atk_spin.setValue(2.5)
            self._skill_aoe_check.setChecked(False)
            self._def_break_check.setChecked(True)
            self._atk_buff_check.setChecked(False)
        elif "healer" in role:
            self._skill_atk_spin.setValue(1.5)
            self._skill_aoe_check.setChecked(False)
            self._def_break_check.setChecked(False)
            self._atk_buff_check.setChecked(False)
        elif "tank" in role:
            self._skill_atk_spin.setValue(2.0)
            self._skill_aoe_check.setChecked(False)
            self._def_break_check.setChecked(False)
            self._atk_buff_check.setChecked(False)

    def apply_dungeon_role(self, dungeon_key: str):
        role_display = self._role_combo.currentText()
        if role_display == "-- none --" or dungeon_key == "custom":
            return
        role_key = ROLE_KEY.get(role_display)
        if not role_key:
            return
        profile = DUNGEON_PROFILES.get(dungeon_key, {})
        targets: dict = profile.get(role_key, {})  # type: ignore
        for stat, sb in self._target_spins.items():
            sb.setValue(int(targets.get(stat, 0) or 0))

    def get_config(self) -> dict | None:
        monster = self._combo.currentData()
        if not isinstance(monster, dict):
            return None
        set_reqs = [cb.currentText() for cb in self._set_combos if cb.currentText()]
        main_stat_constraints = {
            slot_no: cb.currentText()
            for slot_no, cb in self._main_combos.items()
            if cb.currentText() and cb.currentText() != "Any"
        }
        target_stats = {
            s: sb.value() for s, sb in self._target_spins.items() if sb.value() > 0
        }
        target_mode = self._target_mode_combo.currentData() or "total"
        return {
            "unit_id":               monster.get("unit_id"),
            "display_name":          monster.get("display_name", "?"),
            "slot_index":            self._slot_index,
            "priority":              self._priority_spin.value(),
            "role":                  self._role_combo.currentText(),
            "set_reqs":              set_reqs,
            "main_stat_constraints": main_stat_constraints,
            "target_stats":          target_stats,
            "target_mode":           target_mode,
            "scoring_mode":          self._scoring_combo.currentData() or "desirability",
            "skill_id":               (
                self._skill_combo.currentData().get("skill_id")
                if isinstance(self._skill_combo.currentData(), dict) else None
            ),
            "skill_atk_multiplier":   float(self._skill_atk_spin.value()),
            "skill_hp_multiplier":    float(
                self._skill_combo.currentData().get("hp", 0.0)
                if isinstance(self._skill_combo.currentData(), dict) else 0.0
            ),
            "skill_def_multiplier":   float(
                self._skill_combo.currentData().get("defense", 0.0)
                if isinstance(self._skill_combo.currentData(), dict) else 0.0
            ),
            "skill_spd_multiplier":   float(
                self._skill_combo.currentData().get("speed", 0.0)
                if isinstance(self._skill_combo.currentData(), dict) else 0.0
            ),
            "skill_target_hp_multiplier": float(
                self._skill_combo.currentData().get("target_hp", 0.0)
                if isinstance(self._skill_combo.currentData(), dict) else 0.0
            ),
            "skill_flat_damage":      float(
                self._skill_combo.currentData().get("flat", 0.0)
                if isinstance(self._skill_combo.currentData(), dict) else 0.0
            ),
            "skillup_bonus_pct":      float(
                self._skill_combo.currentData().get("skillup_bonus_pct", 0.0)
                if isinstance(self._skill_combo.currentData(), dict) else 0.0
            ),
            "skill_ignore_defense":   bool(
                self._skill_combo.currentData().get("ignores_defense", False)
                if isinstance(self._skill_combo.currentData(), dict) else False
            ),
            "skill_hits":             int(self._skill_hits_spin.value()),
            "skill_aoe":              self._skill_aoe_check.isChecked(),
            "provides_defense_break": self._def_break_check.isChecked(),
            "provides_atk_buff":      self._atk_buff_check.isChecked(),
            "provides_brand":         bool(
                self._skill_combo.currentData().get("provides_brand", False)
                if isinstance(self._skill_combo.currentData(), dict) else False
            ),
            "provides_healing":       bool(
                self._skill_combo.currentData().get("provides_healing", False)
                if isinstance(self._skill_combo.currentData(), dict)
                else "healer" in self._role_combo.currentText().lower()
            ),
            "provides_control":       bool(
                self._skill_combo.currentData().get("provides_control", False)
                if isinstance(self._skill_combo.currentData(), dict) else False
            ),
            "skill_cooldown":         int(
                self._skill_combo.currentData().get("cooldown", 1)
                if isinstance(self._skill_combo.currentData(), dict) else 1
            ),
            "skill_effect_chance":    float(
                self._skill_combo.currentData().get("effect_chance", 100.0)
                if isinstance(self._skill_combo.currentData(), dict) else 100.0
            ),
        }


# ---------------------------------------------------------------------------
# Monster result card  (now shows full final stats)
# ---------------------------------------------------------------------------

class _MonsterResultCard(QFrame):
    def __init__(
        self,
        monster_result,
        monster_info: dict,
        artifact_flat: dict | None,
        dungeon_key: str,
        building_bonuses: dict | None = None,
        selected_leader: dict | None = None,
        current_stats: dict | None = None,
        parent=None,
    ):
        super().__init__(parent)
        from optimizer.team_optimizer import MonsterResult
        mr: MonsterResult = monster_result
        build = mr.build
        avg   = build.avg_desr if build else 0.0
        grade = "S" if avg >= 65 else "A" if avg >= 50 else "B" if avg >= 38 else "C"
        border = _GRADE_COLOR.get(grade, "#2d333b")

        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "QFrame { background: " + BG_CARD + "; border: 1px solid " + border + ";"
            " border-radius: 6px; }"
            "QLabel { border: none; }"
        )
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        profile       = DUNGEON_PROFILES.get(dungeon_key, {})
        enemy_spd     = int(profile.get("max_enemy_spd", 0) or 0)
        enemy_res     = int(profile.get("max_enemy_res", 0) or 0)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(4)

        # ---- Header ----
        hdr = QHBoxLayout()
        name_lbl = QLabel("P" + str(mr.priority) + "  " + mr.display_name)
        name_lbl.setFont(QFont("Segoe UI", 10, QFont.Bold))
        name_lbl.setStyleSheet("color: " + TEXT_MAIN + ";")
        hdr.addWidget(name_lbl)
        hdr.addStretch()
        if build:
            avg_lbl = QLabel("Avg " + str(avg) + "%")
            avg_lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
            avg_lbl.setStyleSheet("color: " + border + ";")
            hdr.addWidget(avg_lbl)
        root.addLayout(hdr)

        if not build:
            root.addWidget(QLabel("No runes found"))
            return

        # ---- Set badges ----
        badges_row = QHBoxLayout()
        for sname, cnt in sorted(build.set_summary.items(), key=lambda x: -x[1]):
            req    = _SET_SIZE.get(sname, 2)
            active = cnt >= req
            badge  = QLabel(sname + " " + str(cnt) + "/" + str(req))
            badge.setFont(QFont("Segoe UI", 7, QFont.Bold))
            badge.setStyleSheet(
                ("background: rgba(63,185,80,0.15); color: #3fb950;"
                 " border: 1px solid rgba(63,185,80,0.35);"
                 if active else
                 "background: rgba(139,148,158,0.10); color: " + TEXT_DIM + ";"
                 " border: 1px solid rgba(139,148,158,0.25);")
                + " border-radius: 3px; padding: 1px 5px;"
            )
            badges_row.addWidget(badge)
        badges_row.addStretch()
        root.addLayout(badges_row)

        # ---- Rune slot grade chips ----
        slots_row = QHBoxLayout()
        slots_row.setSpacing(4)
        for sr in build.slots:
            r = sr.rune
            if r:
                g      = r.get("grade") or "?"
                occ    = r.get("occupied_id")
                bg     = _GRADE_COLOR.get(g, "#888")
                marker = "!" if occ and occ != 0 else ""
                s_lbl  = QLabel(str(sr.slot_no) + ":" + g + marker)
                s_lbl.setFont(QFont("Segoe UI", 7, QFont.Bold))
                s_lbl.setStyleSheet(
                    "background: " + bg + "; color: #0d1117;"
                    " border-radius: 3px; padding: 1px 4px;"
                )
            else:
                s_lbl = QLabel(str(sr.slot_no) + ":--")
                s_lbl.setFont(QFont("Segoe UI", 7))
                s_lbl.setStyleSheet("color: " + TEXT_DIM + ";")
            slots_row.addWidget(s_lbl)
        slots_row.addStretch()
        root.addLayout(slots_row)

        # ---- Final stats grid ----
        # Prefer the stats computed by the optimizer itself (identical math,
        # same bonuses) so the display always matches what was optimized.
        if build.final_stats:
            stats = build.final_stats
        else:
            from desktop.db.queries import compute_leader_bonus
            from optimizer.stat_utils import merge_bonuses
            _elem = monster_info.get("element")
            _leader_bb = compute_leader_bonus(selected_leader, _elem)
            _combined_bb = merge_bonuses(building_bonuses, _leader_bb)
            stats = _compute_final_stats(monster_info, build, artifact_flat, _combined_bb)

        def _stat_lbl(key: str, label: str, val, color: str | None = None):
            """One stat: dim label + bright value (optionally colored)."""
            row = QHBoxLayout()
            row.setSpacing(2)
            k = QLabel(label)
            k.setFont(QFont("Segoe UI", 7))
            k.setStyleSheet("color: " + TEXT_DIM + ";")
            k.setFixedWidth(38)
            v = QLabel(str(val))
            v.setFont(QFont("Segoe UI", 8, QFont.Bold))
            c = color if color else TEXT_MAIN
            v.setStyleSheet("color: " + c + ";")
            row.addWidget(k)
            row.addWidget(v)
            row.addStretch()
            return row

        def _req_color(val: float, threshold: float, higher_is_better: bool = True) -> str:
            if threshold <= 0:
                return TEXT_MAIN
            if higher_is_better:
                return COL_OK if val >= threshold else COL_FAIL
            return COL_OK if val <= threshold else COL_FAIL

        sg = QGridLayout()
        sg.setSpacing(2)
        sg.setContentsMargins(0, 2, 0, 0)

        def _scell(label: str, val_str: str, color: str):
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 4, 0)
            h.setSpacing(2)
            lbl = QLabel(label)
            lbl.setFont(QFont("Segoe UI", 7))
            lbl.setStyleSheet("color: " + TEXT_DIM + ";")
            v = QLabel(val_str)
            v.setFont(QFont("Segoe UI", 8, QFont.Bold))
            v.setStyleSheet("color: " + color + ";")
            h.addWidget(lbl)
            h.addWidget(v)
            h.addStretch()
            return w

        spd_color = _req_color(stats["spd"], enemy_spd)
        acc_color = _req_color(stats["acc"], enemy_res)
        cr_color  = COL_OK if stats["cr"] >= 85 else COL_WARN if stats["cr"] >= 70 else TEXT_MAIN
        cd_color  = COL_OK if stats["cd"] >= 150 else TEXT_MAIN

        cells = [
            ("HP",   _fmt_k(stats["hp"]),   TEXT_MAIN),
            ("ATK",  _fmt_k(stats["atk"]),  TEXT_MAIN),
            ("DEF",  _fmt_k(stats["def_"]), TEXT_MAIN),
            ("SPD",  str(stats["spd"]),      spd_color),
            ("CR%",  str(stats["cr"]) + "%", cr_color),
            ("CD%",  str(stats["cd"]) + "%", cd_color),
            ("RES%", str(stats["res"]) + "%", TEXT_MAIN),
            ("ACC%", str(stats["acc"]) + "%", acc_color),
        ]

        for idx, (lbl_text, val_text, color) in enumerate(cells):
            r, c = divmod(idx, 4)
            sg.addWidget(_scell(lbl_text, val_text, color), r, c)

        root.addLayout(sg)

        # ---- Before/After delta row ----
        if current_stats:
            delta_items = []
            for key, label, is_big in [
                ("hp",   "HP",   True),
                ("atk",  "ATK",  True),
                ("def_", "DEF",  True),
                ("spd",  "SPD",  False),
                ("cr",   "CR%",  False),
                ("cd",   "CD%",  False),
                ("res",  "RES%", False),
                ("acc",  "ACC%", False),
            ]:
                new_v = float(stats.get(key, 0) or 0)
                old_v = float(current_stats.get(key, 0) or 0)
                diff  = new_v - old_v
                if abs(diff) < 0.5:
                    continue
                if is_big:
                    diff_str = ("+" if diff > 0 else "") + _fmt_k(int(diff))
                else:
                    diff_str = ("%+.0f" % diff) + ("%" if "%" in label else "")
                delta_items.append((label, diff_str, diff > 0))
            if delta_items:
                delta_row = QHBoxLayout()
                delta_row.setSpacing(6)
                d_hdr = QLabel("vs current:")
                d_hdr.setFont(QFont("Segoe UI", 7))
                d_hdr.setStyleSheet("color: " + TEXT_DIM + ";")
                delta_row.addWidget(d_hdr)
                for lbl_text, diff_text, positive in delta_items:
                    color = COL_OK if positive else COL_FAIL
                    chip = QLabel(lbl_text + " " + diff_text)
                    chip.setFont(QFont("Segoe UI", 7, QFont.Bold))
                    chip.setStyleSheet(
                        "color: " + color + "; background: rgba("
                        + _hex_to_rgba(color, 0.1) + ");"
                        " border: 1px solid rgba(" + _hex_to_rgba(color, 0.3) + ");"
                        " border-radius: 3px; padding: 0px 4px;"
                    )
                    delta_row.addWidget(chip)
                delta_row.addStretch()
                root.addLayout(delta_row)

        # ---- Effective Offense / EHP metrics ----
        # NOTE: do NOT import DUNGEON_PROFILES locally here — a local import
        # shadows the module-level name and makes the earlier
        # DUNGEON_PROFILES.get() at the top of __init__ raise
        # UnboundLocalError, killing every result card.
        from optimizer.stat_utils import effective_offense, effective_hp, fmt_k
        _ab          = artifact_flat or {}
        _cd_bonus    = float(_ab.get("cd_bonus",     0) or 0)
        _addl_atk    = float(_ab.get("addl_atk_pct", 0) or 0)
        _addl_hp     = float(_ab.get("addl_hp_pct",  0) or 0)
        _addl_def    = float(_ab.get("addl_def_pct", 0) or 0)
        _addl_spd    = float(_ab.get("addl_spd_pct", 0) or 0)
        # Element damage bonus: look up dungeon boss element -> effect_id -> bonus %
        _ELEMENT_EFF = {"Water": 301, "Fire": 300, "Wind": 302, "Light": 303, "Dark": 304}
        _boss_elem   = (DUNGEON_PROFILES.get(dungeon_key) or {}).get("boss_element", "")
        _elem_eff_id = _ELEMENT_EFF.get(_boss_elem, 0)
        _elem_bonus  = float(_ab.get("element_dmg", {}).get(_elem_eff_id, 0) or 0)
        eo  = effective_offense(
            stats,
            cd_bonus=_cd_bonus,
            element_bonus=_elem_bonus,
            addl_atk_pct=_addl_atk,
            addl_hp_pct=_addl_hp,
            addl_def_pct=_addl_def,
            addl_spd_pct=_addl_spd,
        )
        ehp = effective_hp(stats)
        eo_row = QHBoxLayout()
        eo_row.setSpacing(8)

        def _metric_widget(label: str, value: str, tooltip: str, color: str) -> QWidget:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(4, 1, 4, 1)
            h.setSpacing(3)
            lbl_w = QLabel(label)
            lbl_w.setFont(QFont("Segoe UI", 7))
            lbl_w.setStyleSheet("color: " + TEXT_DIM + ";")
            val_w = QLabel(value)
            val_w.setFont(QFont("Segoe UI", 8, QFont.Bold))
            val_w.setStyleSheet("color: " + color + ";")
            h.addWidget(lbl_w)
            h.addWidget(val_w)
            w.setStyleSheet(
                "QWidget { background: rgba(" + _hex_to_rgba(color, 0.08) + ");"
                " border: 1px solid rgba(" + _hex_to_rgba(color, 0.25) + ");"
                " border-radius: 3px; }"
            )
            w.setToolTip(tooltip)
            return w

        _art_parts = []
        if _cd_bonus  > 0: _art_parts.append("+{:.0f}% CD".format(_cd_bonus))
        if _elem_bonus > 0: _art_parts.append("+{:.0f}% {} DMG".format(_elem_bonus, _boss_elem))
        if _addl_atk  > 0: _art_parts.append("+{:.0f}% addl ATK hit".format(_addl_atk))
        if _addl_hp   > 0: _art_parts.append("+{:.0f}% addl HP hit".format(_addl_hp))
        if _addl_def  > 0: _art_parts.append("+{:.0f}% addl DEF hit".format(_addl_def))
        if _addl_spd  > 0: _art_parts.append("+{:.0f}% addl SPD hit".format(_addl_spd))
        _art_tip = (" (incl. " + ", ".join(_art_parts) + " from artifacts)" if _art_parts else "")
        eo_tip  = (
            "Effective Offense = ATK x [1 + CR x ((CD+art_CD)/100-1)] x (1+addl/100) x (1+elem/100)\n"
            "Expected average damage per hit, proportional to actual skill damage." +
            _art_tip + "\n"
            "Artifact CD bonuses: Own-turn 1-target CD, [S1-S4] CRIT DMG, First Attack CRIT DMG.\n"
            "Element bonus applies only when dungeon boss matches artifact element type.\n"
            "Add'l hits (HP/ATK/DEF/SPD): separate crit-capable hits at minimum (full-HP) value."
        )
        ehp_tip = (
            "Effective HP = HP x (1140 + 3.75 x DEF) / 1000\n"
            "Survivability using the actual SW damage-reduction formula\n"
            "(damage taken = damage x 1000 / (1140 + 3.75 x DEF)).\n"
            "Useful for comparing tank/support builds."
        )
        eo_row.addWidget(_metric_widget("EO", fmt_k(eo),  eo_tip,  "#f0a830"))
        eo_row.addWidget(_metric_widget("EHP", fmt_k(ehp), ehp_tip, "#58a6ff"))
        eo_row.addStretch()
        root.addLayout(eo_row)

        # ---- Dungeon req check summary ----
        req_items: list[tuple[str, bool]] = []
        if enemy_spd:
            req_items.append(("SPD>" + str(enemy_spd), stats["spd"] > enemy_spd))
        if enemy_res:
            req_items.append(("ACC>=" + str(enemy_res) + "%", stats["acc"] >= enemy_res))

        if req_items:
            req_row = QHBoxLayout()
            for label, ok in req_items:
                badge = QLabel(("+ " if ok else "x ") + label)
                badge.setFont(QFont("Segoe UI", 7))
                c = COL_OK if ok else COL_FAIL
                badge.setStyleSheet(
                    "color: " + c + "; background: rgba(" + _hex_to_rgba(c, 0.1) + ");"
                    " border: 1px solid rgba(" + _hex_to_rgba(c, 0.3) + ");"
                    " border-radius: 3px; padding: 1px 5px;"
                )
                req_row.addWidget(badge)
            req_row.addStretch()
            root.addLayout(req_row)

        # ---- Per-target report (actual vs target, on FINAL stats) ----
        report = build.target_report or {}
        if report:
            tr_row = QHBoxLayout()
            tr_row.setSpacing(4)
            for key, v in report.items():
                ok = v["met"]
                if v.get("kind") == "max":
                    txt = "%s %s<=%s" % (key, v["actual"], int(v["target"]))
                else:
                    txt = "%s %s/%s" % (key, v["actual"], int(v["target"]))
                if not ok:
                    txt += " (-%s)" % v["miss"] if v.get("kind") != "max" \
                           else " (+%s)" % v["miss"]
                badge = QLabel(("+ " if ok else "x ") + txt)
                badge.setFont(QFont("Segoe UI", 7))
                c = COL_OK if ok else COL_FAIL
                badge.setStyleSheet(
                    "color: " + c + "; background: rgba(" + _hex_to_rgba(c, 0.1) + ");"
                    " border: 1px solid rgba(" + _hex_to_rgba(c, 0.3) + ");"
                    " border-radius: 3px; padding: 1px 5px;"
                )
                tr_row.addWidget(badge)
            tr_row.addStretch()
            root.addLayout(tr_row)

        # ---- Broken set warning ----
        if not build.sets_complete:
            bs_lbl = QLabel(
                "  Required set could not be completed with available runes —"
                " farm the suggested rune below, relax the main-stat filter,"
                " or enable 'Include runes from other monsters'"
            )
            bs_lbl.setWordWrap(True)
            bs_lbl.setFont(QFont("Segoe UI", 7))
            bs_lbl.setStyleSheet(
                "color: " + COL_FAIL + "; background: rgba(224,92,92,0.07);"
                " border: 1px solid rgba(224,92,92,0.2);"
                " border-radius: 3px; padding: 1px 5px;"
            )
            root.addWidget(bs_lbl)

        # ---- +15 projection note ----
        if build.assumed_max:
            _n_under = sum(
                1 for sr in build.slots
                if sr.rune and int(sr.rune.get("upgrade_curr") or 0) < 15
            )
            if _n_under:
                pj_lbl = QLabel(
                    "  %d rune%s valued at +15 — upgrade %s to reach the shown stats"
                    % (_n_under, "s" if _n_under != 1 else "",
                       "them" if _n_under != 1 else "it")
                )
                pj_lbl.setFont(QFont("Segoe UI", 7))
                pj_lbl.setStyleSheet(
                    "color: " + COL_WARN + "; background: rgba(232,200,74,0.07);"
                    " border: 1px solid rgba(232,200,74,0.2);"
                    " border-radius: 3px; padding: 1px 5px;"
                )
                root.addWidget(pj_lbl)

        # ---- Weak-slot upgrade suggestion ----
        ws = build.weak_slot
        if ws:
            subs = "/".join(ws.get("suggested_subs") or [])
            ws_lbl = QLabel(
                "Weakest: Slot " + str(ws["slot_no"]) + " — " + ws["current"]
                + "\nFarm: " + str(ws["suggested_set"]) + " slot-"
                + str(ws["slot_no"]) + " " + str(ws["suggested_main"])
                + " rune with " + subs + " subs  (" + ws["reason"] + ")"
            )
            ws_lbl.setWordWrap(True)
            ws_lbl.setFont(QFont("Segoe UI", 7))
            ws_lbl.setStyleSheet(
                "color: #58a6ff; background: rgba(88,166,255,0.07);"
                " border: 1px solid rgba(88,166,255,0.2);"
                " border-radius: 3px; padding: 2px 5px;"
            )
            root.addWidget(ws_lbl)

        # ---- Rune Details expander ----
        toggle_btn = QPushButton("\u25b6  Rune Details")
        toggle_btn.setFont(QFont("Segoe UI", 7))
        toggle_btn.setStyleSheet(
            "QPushButton { color: " + TEXT_DIM + "; background: transparent;"
            " border: none; text-align: left; padding: 2px 0px; }"
            "QPushButton:hover { color: " + TEXT_MAIN + "; }"
        )
        toggle_btn.setCursor(Qt.PointingHandCursor)
        root.addWidget(toggle_btn)

        rune_panel = QFrame()
        rune_panel.setStyleSheet(
            "QFrame { background: rgba(0,0,0,0.15); border: 1px solid #2d333b;"
            " border-radius: 4px; } QLabel { border: none; }"
        )
        rune_panel.setVisible(False)
        rp_layout = QVBoxLayout(rune_panel)
        rp_layout.setContentsMargins(8, 6, 8, 6)
        rp_layout.setSpacing(3)

        # Header row
        hdr_row = QHBoxLayout()
        for hdr_text, hdr_w in [("Slot", 28), ("Set", 72), ("Main Stat", 130),
                                 ("Gr", 22), ("Substats", 0), ("Location", 110)]:
            h = QLabel(hdr_text)
            h.setFont(QFont("Segoe UI", 7, QFont.Bold))
            h.setStyleSheet("color: " + TEXT_DIM + ";")
            if hdr_w:
                h.setFixedWidth(hdr_w)
            else:
                h.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            hdr_row.addWidget(h)
        rp_layout.addLayout(hdr_row)

        # One row per slot
        for sr in build.slots:
            r = sr.rune
            row_w = QHBoxLayout()
            row_w.setSpacing(4)

            def _cell(text, width=0, color=None, bold=False):
                lb = QLabel(text)
                lb.setFont(QFont("Segoe UI", 7, QFont.Bold if bold else QFont.Normal))
                c = color if color else TEXT_MAIN
                lb.setStyleSheet("color: " + c + ";")
                lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
                if width:
                    lb.setFixedWidth(width)
                else:
                    lb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                return lb

            slot_no = sr.slot_no
            if r:
                grade      = r.get("grade") or "?"
                set_nm     = r.get("set_name") or "?"
                main_nm    = r.get("main_stat_name") or "?"
                main_val   = r.get("main_stat_value")
                main_str   = main_nm + (" +" + str(main_val) if main_val else "")
                # Show +15 projection for under-leveled runes
                if build.assumed_max:
                    from optimizer.stat_utils import projected_main_value
                    _proj = projected_main_value(r)
                    _lvl  = int(r.get("upgrade_curr") or 0)
                    if _lvl < 15 and main_val and _proj > float(main_val):
                        main_str += " ->%s @15" % int(_proj)
                # Substats: stored as a JSON list of label strings — parse
                # and join cleanly instead of dumping raw JSON brackets.
                raw_subs = r.get("substat_labels") or ""
                try:
                    _sl = _json.loads(raw_subs) if isinstance(raw_subs, str) else raw_subs
                    substats = "  |  ".join(str(x) for x in (_sl or []))
                except Exception:
                    substats = str(raw_subs)
                # Location: where this rune currently lives
                occ_id     = r.get("occupied_id")
                occ_nm     = r.get("occupied_name") or ""
                locked     = bool(r.get("user_locked"))
                if occ_id and occ_id != 0 and occ_nm and occ_nm != mr.display_name:
                    loc_str   = "On: " + occ_nm   # taken from another monster
                    loc_color = COL_WARN
                elif occ_id and occ_id != 0:
                    loc_str   = "Equipped (own)"  # already on this monster
                    loc_color = COL_OK
                else:
                    loc_str   = "Storage"
                    loc_color = "#58a6ff"
                if locked:
                    loc_str += " [locked]"
                gr_color = _GRADE_COLOR.get(grade, TEXT_MAIN)
                row_w.addWidget(_cell(str(slot_no), 28, TEXT_DIM))
                row_w.addWidget(_cell(set_nm, 72))
                row_w.addWidget(_cell(main_str, 130))
                row_w.addWidget(_cell(grade, 22, gr_color, bold=True))
                _sub_lbl = _cell(substats, 0, TEXT_DIM)
                _sub_lbl.setWordWrap(True)   # never push Location off-screen
                row_w.addWidget(_sub_lbl)
                row_w.addWidget(_cell(loc_str, 110, loc_color))
            else:
                row_w.addWidget(_cell(str(slot_no), 28, TEXT_DIM))
                row_w.addWidget(_cell("-- no rune --", 0, TEXT_DIM))
            rp_layout.addLayout(row_w)

        root.addWidget(rune_panel)

        def _toggle_rune_panel():
            vis = not rune_panel.isVisible()
            rune_panel.setVisible(vis)
            toggle_btn.setText(("\u25bc  Rune Details" if vis else "\u25b6  Rune Details"))

        toggle_btn.clicked.connect(_toggle_rune_panel)


# ---------------------------------------------------------------------------
# Results panel
# ---------------------------------------------------------------------------

class _ResultsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_result = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._placeholder = QLabel("Configure your team on the left and press Optimize Team.")
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

    def _copy_to_clipboard(self):
        if not self._last_result:
            return
        (
            team_result,
            dungeon_key,
            monster_data_map,
            artifact_flat_map,
            current_stats_map,
            selected_leader,
            artifact_pair_map,
        ) = self._last_result
        profile = DUNGEON_PROFILES.get(dungeon_key, {})
        lines = []
        lines.append("=== SW Team Optimizer Results ===")
        lines.append("Dungeon: " + profile.get("display_name", dungeon_key))
        if selected_leader and selected_leader.get("leader_skill_label"):
            lines.append("Leader: " + selected_leader.get("display_name", "?")
                         + "  —  " + selected_leader.get("leader_skill_label", ""))
        lines.append("Team avg desirability: " + str(team_result.team_avg_desr) + "%")
        if team_result.dungeon_evaluation is not None:
            lines.append(
                "Dungeon readiness: %.1f%%  Simulated clear rate: %.1f%%"
                % (
                    team_result.dungeon_score or 0,
                    team_result.estimated_success or 0,
                )
            )
            for wave in team_result.dungeon_evaluation.waves:
                lines.append(
                    "  Wave %d: %.2f rounds / %d budget, damage %.0f%%,"
                    " survival %.0f%%, chance %.1f%%"
                    % (
                        wave.wave_number,
                        wave.rounds_to_clear,
                        wave.turn_budget,
                        wave.damage_score,
                        wave.survivability_score,
                        wave.success_probability,
                    )
                )
            lines.append(
                "  Bottlenecks: "
                + "; ".join(team_result.dungeon_evaluation.bottlenecks)
            )
        lines.append("")
        for mr in team_result.monsters:
            lines.append("── " + mr.display_name + " (P" + str(mr.priority) + ") ──")
            artifact_pair = (artifact_pair_map or {}).get(mr.unit_id)
            if artifact_pair is not None:
                attribute_id = (
                    artifact_pair.attribute_artifact or {}
                ).get("artifact_id", "-")
                type_id = (
                    artifact_pair.type_artifact or {}
                ).get("artifact_id", "-")
                lines.append(
                    "  Artifacts: Attribute #%s  Type #%s  Score %,.0f"
                    % (attribute_id, type_id, artifact_pair.score)
                )
            if not mr.build:
                lines.append("  No runes found")
            else:
                b = mr.build
                s = b.final_stats or {}
                lines.append(
                    "  HP %s  ATK %s  DEF %s  SPD %s  CR %s%%  CD %s%%  RES %s%%  ACC %s%%" % (
                        _fmt_k(int(s.get("hp", 0))),
                        _fmt_k(int(s.get("atk", 0))),
                        _fmt_k(int(s.get("def_", 0))),
                        s.get("spd", 0),
                        s.get("cr", 0), s.get("cd", 0),
                        s.get("res", 0), s.get("acc", 0),
                    )
                )
                if current_stats_map and mr.unit_id in current_stats_map:
                    cs = current_stats_map[mr.unit_id]
                    deltas = []
                    for key, label in [("spd","SPD"),("cr","CR"),("cd","CD"),
                                       ("res","RES"),("acc","ACC")]:
                        d = round(float(s.get(key, 0)) - float(cs.get(key, 0)), 1)
                        if d != 0:
                            deltas.append("%s%+.0f" % (label, d))
                    for key, label in [("hp","HP"),("atk","ATK"),("def_","DEF")]:
                        d = int(s.get(key, 0)) - int(cs.get(key, 0))
                        if d != 0:
                            deltas.append("%s%+s" % (label, _fmt_k(abs(d)) if d > 0 else "-" + _fmt_k(abs(d))))
                    if deltas:
                        lines.append("  Δ vs current: " + "  ".join(deltas))
                sets = "  ".join(
                    k + "×" + str(v) for k, v in sorted(b.set_summary.items(), key=lambda x: -x[1])
                )
                lines.append("  Sets: " + sets)
                for sr in b.slots:
                    r = sr.rune
                    if r:
                        occ = r.get("occupied_name") or ("own" if r.get("occupied_id") else "storage")
                        lines.append("  [%d] %s %s +%s  (%s)" % (
                            sr.slot_no, r.get("set_name", "?"),
                            r.get("main_stat_name", "?"),
                            r.get("upgrade_curr", 0), occ,
                        ))
            lines.append("")
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText("\n".join(lines))

    def show_results(
        self,
        team_result,
        base_spd_map: dict[int, int],
        dungeon_key: str,
        monster_data_map: dict[int, dict] | None = None,
        artifact_flat_map: dict[int, dict] | None = None,
        building_bonuses: dict | None = None,
        selected_leader: dict | None = None,
        current_stats_map: dict[int, dict] | None = None,
        artifact_pair_map: dict[int, object] | None = None,
    ):
        self._clear()
        self._placeholder.setVisible(False)
        self._scroll.setVisible(True)

        # Store for clipboard export
        self._last_result = (
            team_result,
            dungeon_key,
            monster_data_map,
            artifact_flat_map,
            current_stats_map,
            selected_leader,
            artifact_pair_map,
        )

        hdr_row = QHBoxLayout()
        hdr = QLabel("Team Build Results")
        hdr.setFont(QFont("Segoe UI", 13, QFont.Bold))
        hdr.setStyleSheet("color: " + TEXT_MAIN + ";")
        hdr_row.addWidget(hdr)
        hdr_row.addStretch()
        copy_btn = QPushButton("Copy Summary")
        copy_btn.setFont(QFont("Segoe UI", 8))
        copy_btn.setFixedHeight(28)
        copy_btn.setStyleSheet(
            "QPushButton { padding: 2px 10px; color: " + TEXT_DIM + ";"
            " border: 1px solid #2d333b; border-radius: 4px; background: " + BG_CARD + "; }"
            "QPushButton:hover { color: " + TEXT_MAIN + "; border-color: #58a6ff; }"
        )
        copy_btn.clicked.connect(self._copy_to_clipboard)
        hdr_row.addWidget(copy_btn)
        self._layout.addLayout(hdr_row)

        avg_lbl = QLabel("Team avg desr: " + str(team_result.team_avg_desr) + "%")
        avg_lbl.setFont(QFont("Segoe UI", 10))
        avg_lbl.setStyleSheet("color: " + TEXT_DIM + ";")
        self._layout.addWidget(avg_lbl)

        dungeon_evaluation = team_result.dungeon_evaluation
        if dungeon_evaluation is not None:
            displayed_success = float(
                team_result.estimated_success
                if team_result.estimated_success is not None
                else dungeon_evaluation.success_probability
            )
            score_color = (
                COL_OK
                if displayed_success >= 80
                else COL_WARN
                if displayed_success >= 45
                else COL_FAIL
            )
            readiness_label = QLabel(
                "Dungeon readiness %.1f%%  |  Simulated clear rate %.1f%%"
                % (
                    dungeon_evaluation.readiness_score,
                    displayed_success,
                )
            )
            readiness_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
            readiness_label.setStyleSheet("color: " + score_color + ";")
            self._layout.addWidget(readiness_label)

            wave_grid = QGridLayout()
            wave_grid.setHorizontalSpacing(12)
            wave_grid.setVerticalSpacing(2)
            headers = ("Wave", "Rounds", "Damage", "Survival", "Speed", "Chance")
            for column, header in enumerate(headers):
                header_label = QLabel(header)
                header_label.setFont(QFont("Segoe UI", 7, QFont.Bold))
                header_label.setStyleSheet("color: " + TEXT_DIM + ";")
                wave_grid.addWidget(header_label, 0, column)
            for row, wave in enumerate(dungeon_evaluation.waves, 1):
                values = (
                    str(wave.wave_number),
                    "%.2f / %d" % (wave.rounds_to_clear, wave.turn_budget),
                    "%.0f%%" % wave.damage_score,
                    "%.0f%%" % wave.survivability_score,
                    "%.0f%%" % wave.speed_score,
                    "%.1f%%" % wave.success_probability,
                )
                for column, value in enumerate(values):
                    value_label = QLabel(value)
                    value_label.setFont(QFont("Segoe UI", 8))
                    value_label.setStyleSheet("color: " + TEXT_MAIN + ";")
                    wave_grid.addWidget(value_label, row, column)
            self._layout.addLayout(wave_grid)

            bottleneck_label = QLabel(
                "Bottleneck: " + "; ".join(dungeon_evaluation.bottlenecks)
            )
            bottleneck_label.setFont(QFont("Segoe UI", 8))
            bottleneck_label.setStyleSheet("color: " + TEXT_DIM + ";")
            bottleneck_label.setWordWrap(True)
            self._layout.addWidget(bottleneck_label)

        # Planned turn order check (only meaningful when a plan was enforced)
        if any(mr.turn_pos is not None for mr in team_result.monsters):
            ok = getattr(team_result, "turn_order_ok", True)
            to_lbl = QLabel(
                "Turn order plan: ACHIEVED — speeds match the planned order"
                if ok else
                "Turn order plan: NOT achieved — rune pool can't satisfy the "
                "planned speed gaps (see SPD caps/targets on each card)"
            )
            to_lbl.setFont(QFont("Segoe UI", 8, QFont.Bold))
            to_lbl.setWordWrap(True)
            to_lbl.setStyleSheet("color: " + (COL_OK if ok else COL_WARN) + ";")
            self._layout.addWidget(to_lbl)

        if selected_leader and selected_leader.get("leader_skill_attribute"):
            _ls_lbl = QLabel(
                "Leader: " + selected_leader.get("display_name", "?") + "  —  "
                + selected_leader.get("leader_skill_label", "")
            )
            _ls_lbl.setFont(QFont("Segoe UI", 9))
            _ls_lbl.setStyleSheet("color: #f0a830;")
            self._layout.addWidget(_ls_lbl)

        profile       = DUNGEON_PROFILES.get(dungeon_key, {})
        max_enemy_spd = profile.get("max_enemy_spd", 0) or 0
        dungeon_name  = profile.get("display_name", dungeon_key)

        turn_units: list[TurnEntry] = []
        for i, mr in enumerate(team_result.monsters):
            base_spd = base_spd_map.get(mr.unit_id, 0)
            # The optimizer's own final stats are authoritative
            if mr.build and mr.build.final_stats:
                est_spd = int(mr.build.final_stats.get("spd", base_spd))
            elif monster_data_map and mr.unit_id in monster_data_map and mr.build:
                info = monster_data_map[mr.unit_id]
                art  = (artifact_flat_map or {}).get(mr.unit_id)
                from desktop.db.queries import compute_leader_bonus
                from optimizer.stat_utils import merge_bonuses
                _to_elem = info.get("element")
                _to_lbb  = compute_leader_bonus(selected_leader, _to_elem)
                _to_bb   = merge_bonuses(building_bonuses, _to_lbb)
                est_spd = _compute_final_stats(info, mr.build, art, _to_bb)["spd"]
            else:
                est_spd = _estimate_spd(mr, base_spd)
            color = _TEAM_COLORS[i % len(_TEAM_COLORS)]
            turn_units.append(TurnEntry(mr.display_name[:12], est_spd, True, color))
        if max_enemy_spd > 0:
            turn_units.append(TurnEntry("Enemy (fast)", max_enemy_spd, False, _ENEMY_COLOR))
        if turn_units:
            self._layout.addWidget(_TurnOrderWidget(turn_units, dungeon_name))

        for i, mr in enumerate(team_result.monsters):
            info         = (monster_data_map or {}).get(mr.unit_id, {})
            art          = (artifact_flat_map or {}).get(mr.unit_id)
            curr_stats   = (current_stats_map or {}).get(mr.unit_id)
            artifact_pair = (artifact_pair_map or {}).get(mr.unit_id)
            if artifact_pair is not None:
                attribute = artifact_pair.attribute_artifact or {}
                type_artifact = artifact_pair.type_artifact or {}
                artifact_label = QLabel(
                    "Recommended artifacts: Attribute #%s (%s)  |  Type #%s (%s)"
                    % (
                        attribute.get("artifact_id", "-"),
                        attribute.get("pri_effect") or "none",
                        type_artifact.get("artifact_id", "-"),
                        type_artifact.get("pri_effect") or "none",
                    )
                )
                artifact_label.setFont(QFont("Segoe UI", 8, QFont.Bold))
                artifact_label.setStyleSheet("color: #d2a8ff;")
                artifact_label.setWordWrap(True)
                artifact_label.setToolTip("\n".join(artifact_pair.reasons))
                self._layout.addWidget(artifact_label)
            try:
                card = _MonsterResultCard(mr, info, art, dungeon_key,
                                          building_bonuses, selected_leader,
                                          current_stats=curr_stats)
                self._layout.addWidget(card)
            except Exception:
                # Never let one bad card blank the whole results panel —
                # show the error inline instead.
                import traceback
                err = QLabel("Card error (" + mr.display_name + "):\n"
                             + traceback.format_exc())
                err.setWordWrap(True)
                err.setStyleSheet("color: " + COL_FAIL + "; font-size: 7pt;")
                self._layout.addWidget(err)

        self._layout.addStretch()


# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------

class TeamOptimizerWidget(QWidget):
    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self._conn    = conn
        self._db_path = conn.execute("PRAGMA database_list").fetchone()[2]
        self._monsters: list[dict] = []
        self._worker: _TeamWorker | None = None
        self._monsters_loaded = False
        self._build_ui()
        self._load_monsters()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._monsters_loaded:
            self._load_monsters()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        title_bar = QFrame()
        title_bar.setObjectName("topbar")
        title_bar.setFixedHeight(42)
        tb = QHBoxLayout(title_bar)
        tb.setContentsMargins(16, 0, 16, 0)
        tl = QLabel("Team Optimizer")
        tl.setFont(QFont("Segoe UI", 12, QFont.Bold))
        tb.addWidget(tl)
        tb.addStretch()
        root.addWidget(title_bar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(6)
        splitter.setChildrenCollapsible(False)

        left = QWidget()
        left.setMinimumWidth(380)
        left.setMaximumWidth(480)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setWidget(left)

        ll = QVBoxLayout(left)
        ll.setContentsMargins(10, 10, 10, 10)
        ll.setSpacing(8)
        ll.setAlignment(Qt.AlignTop)

        # -- Saved Teams --
        ll.addWidget(self._sec("Saved Teams"))
        saved_row = QHBoxLayout()
        saved_row.setSpacing(4)
        self._saved_combo = QComboBox()
        self._saved_combo.setMinimumHeight(26)
        self._saved_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._saved_combo.setToolTip("Select a saved team config to load.")
        saved_row.addWidget(self._saved_combo, 1)
        # NOTE: no setFixedWidth here — the global QPushButton style adds
        # 14px horizontal padding, so fixed widths clip the text ("oa(").
        # Compact padding + natural sizing instead.
        _cfg_btn_style = (
            "QPushButton { padding: 4px 8px; }"
        )
        self._load_cfg_btn = QPushButton("Load")
        self._load_cfg_btn.setMinimumHeight(26)
        self._load_cfg_btn.setStyleSheet(_cfg_btn_style)
        self._load_cfg_btn.clicked.connect(self._load_config)
        saved_row.addWidget(self._load_cfg_btn)
        self._save_cfg_btn = QPushButton("Save")
        self._save_cfg_btn.setMinimumHeight(26)
        self._save_cfg_btn.setStyleSheet(_cfg_btn_style)
        self._save_cfg_btn.clicked.connect(self._save_config)
        saved_row.addWidget(self._save_cfg_btn)
        self._del_cfg_btn = QPushButton("Del")
        self._del_cfg_btn.setMinimumHeight(26)
        self._del_cfg_btn.setStyleSheet(
            "QPushButton { padding: 4px 8px; color: #e05252; }"
        )
        self._del_cfg_btn.clicked.connect(self._delete_config)
        saved_row.addWidget(self._del_cfg_btn)
        ll.addLayout(saved_row)

        # -- Dungeon --
        ll.addWidget(self._sec("Dungeon"))
        dungeon_row = QHBoxLayout()
        self._dungeon_combo = QComboBox()
        for key, profile in DUNGEON_PROFILES.items():
            self._dungeon_combo.addItem(profile["display_name"], userData=key)
        self._dungeon_combo.setMinimumHeight(28)
        self._dungeon_combo.currentIndexChanged.connect(self._on_dungeon_changed)
        dungeon_row.addWidget(self._dungeon_combo, 1)
        self._auto_fill_btn = QPushButton("Auto-fill targets")
        self._auto_fill_btn.setMinimumHeight(28)
        self._auto_fill_btn.clicked.connect(self._auto_fill_all)
        dungeon_row.addWidget(self._auto_fill_btn)
        ll.addLayout(dungeon_row)

        self._dungeon_notes = QLabel("")
        self._dungeon_notes.setFont(QFont("Segoe UI", 8))
        self._dungeon_notes.setStyleSheet("color: " + TEXT_DIM + ";")
        self._dungeon_notes.setWordWrap(True)
        ll.addWidget(self._dungeon_notes)

        # -- Turn Order Plan --
        ll.addWidget(self._sec("Turn Order Plan"))
        to_hint = QLabel("Desired move order (left = first).  S1-S5 = team slots.")
        to_hint.setFont(QFont("Segoe UI", 8))
        to_hint.setStyleSheet("color: " + TEXT_DIM + ";")
        ll.addWidget(to_hint)

        to_row = QHBoxLayout()
        to_row.setSpacing(4)
        self._turn_order_combos: list[QComboBox] = []
        for i in range(MAX_SLOTS + 1):
            cb = QComboBox()
            cb.addItems(_TO_OPTIONS)
            # Auto-size to the selected item ("Enemy" was clipped to "En"
            # at a fixed 57px) with compact padding.
            cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
            cb.setMinimumWidth(46)
            cb.setStyleSheet("QComboBox { padding: 2px 6px; }")
            cb.setMinimumHeight(24)
            default = _TO_DEFAULTS[i] if i < len(_TO_DEFAULTS) else _TO_EMPTY
            idx = _TO_OPTIONS.index(default) if default in _TO_OPTIONS else 0
            cb.setCurrentIndex(idx)
            self._turn_order_combos.append(cb)
            to_row.addWidget(cb)
        to_row.addStretch()
        ll.addLayout(to_row)

        to_btn_row = QHBoxLayout()
        self._enforce_to_check = QCheckBox("Enforce turn order")
        self._enforce_to_check.setToolTip(
            "When ON: SPD targets are automatically derived from the plan\n"
            "and kept in sync as you change the order. Each monster must\n"
            "meet its assigned SPD target or the build is rejected."
        )
        self._enforce_to_check.toggled.connect(self._on_enforce_to_toggled)
        to_btn_row.addWidget(self._enforce_to_check)
        to_btn_row.addStretch()
        self._derive_btn = QPushButton("Derive SPD Targets")
        self._derive_btn.setMinimumHeight(28)
        self._derive_btn.setToolTip(
            "Auto-fill each slot's SPD target based on the planned order vs enemy SPD.\n"
            "Slots before Enemy: SPD = enemy_spd + buffer (earlier = larger buffer).\n"
            "Fine-tune the spinboxes if you need exact relative ordering."
        )
        self._derive_btn.clicked.connect(self._derive_spd_targets)
        to_btn_row.addWidget(self._derive_btn)
        ll.addLayout(to_btn_row)
        # connect turn-order combos so auto-derive fires while enforce is on
        for _cb in self._turn_order_combos:
            _cb.currentIndexChanged.connect(self._on_to_combo_changed)

        # -- Team Slots --
        ll.addWidget(self._sec("Team Slots"))
        self._slot_widgets: list[_MonsterSlotWidget] = []
        for i in range(MAX_SLOTS):
            sw = _MonsterSlotWidget(i, [])
            sw.monster_changed.connect(self._refresh_leader_from_slots)
            self._slot_widgets.append(sw)
            ll.addWidget(sw)

        # -- Leader Skill --
        ll.addWidget(self._sec("Leader Skill"))
        self._leader_combo = QComboBox()
        self._leader_combo.setMinimumHeight(26)
        self._leader_combo.setToolTip(
            "Select which monster acts as leader.\n"
            "Their skill bonus is applied to all qualifying allies.\n"
            "General + Dungeon skills always apply; Element skills only\n"
            "apply to monsters of the matching element."
        )
        self._leader_combo.currentIndexChanged.connect(self._on_leader_changed)
        ll.addWidget(self._leader_combo)
        self._leader_desc = QLabel("")
        self._leader_desc.setFont(QFont("Segoe UI", 8))
        self._leader_desc.setStyleSheet("color: #58a6ff;")
        self._leader_desc.setWordWrap(True)
        self._leader_desc.setVisible(False)
        ll.addWidget(self._leader_desc)

        # -- Rune Pool --
        ll.addWidget(self._sec("Rune Pool"))
        stars_row = QHBoxLayout()
        stars_row.addWidget(QLabel("Min stars:"))
        self._stars_combo = QComboBox()
        self._stars_combo.addItems(["4", "5", "6"])
        self._stars_combo.setCurrentIndex(1)
        self._stars_combo.setMinimumHeight(26)
        stars_row.addWidget(self._stars_combo)
        stars_row.addStretch()
        ll.addLayout(stars_row)

        self._include_chk = QCheckBox("Include gear from other monsters")
        self._include_chk.setChecked(False)
        ll.addWidget(self._include_chk)
        self._include_locked_chk = QCheckBox("Include locked runes")
        self._include_locked_chk.setChecked(False)
        self._include_locked_chk.setToolTip(
            "By default locked runes are excluded from the optimizer pool.\n"
            "Check this to allow the optimizer to consider them."
        )
        ll.addWidget(self._include_locked_chk)
        self._assume_max_chk = QCheckBox("Value under-leveled runes at +15")
        self._assume_max_chk.setChecked(True)
        self._assume_max_chk.setToolTip(
            "ON: each rune's MAIN stat is valued at its +15 maximum, so the\n"
            "optimizer sees the rune's true potential. Displayed stats then\n"
            "assume you upgrade those runes (marked with -> in Rune Details).\n"
            "Substats are never projected (future rolls are random).\n"
            "OFF: runes are valued exactly as they are right now."
        )
        ll.addWidget(self._assume_max_chk)
        self._optimize_artifacts_chk = QCheckBox("Optimize artifact pairs with team")
        self._optimize_artifacts_chk.setChecked(True)
        self._optimize_artifacts_chk.setToolTip(
            "Allocates one Attribute and one Type artifact per monster without conflicts."
        )
        ll.addWidget(self._optimize_artifacts_chk)

        ll.addSpacerItem(QSpacerItem(0, 8, QSizePolicy.Minimum, QSizePolicy.Fixed))

        self._optimize_btn = QPushButton("Optimize Team")
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

        splitter.addWidget(left_scroll)

        self._results = _ResultsPanel()
        splitter.addWidget(self._results)
        splitter.setSizes([420, 780])

        root.addWidget(splitter, 1)
        self._on_dungeon_changed()
        self._refresh_saved_combo()

    # -----------------------------------------------------------------------
    # Config save / load helpers
    # -----------------------------------------------------------------------

    def _refresh_saved_combo(self):
        """Reload the saved-configs combo from the DB."""
        try:
            cfgs = queries.list_team_configs(self._conn)
        except Exception:
            cfgs = []
        self._saved_combo.blockSignals(True)
        self._saved_combo.clear()
        self._saved_combo.addItem("-- select saved team --", userData=None)
        for c in cfgs:
            label = c["name"]
            self._saved_combo.addItem(label, userData=c["id"])
        self._saved_combo.blockSignals(False)

    def _gather_config(self) -> dict:
        """Serialise current UI state into a plain dict (no unit_id loss)."""
        slot_configs = []
        for sw in self._slot_widgets:
            cfg = sw.get_config()
            if cfg:
                slot_configs.append(cfg)
            else:
                slot_configs.append(None)
        _li = self._leader_combo.currentIndex()
        leader_data = self._leader_combo.itemData(_li)
        leader_uid = leader_data.get("unit_id") if isinstance(leader_data, dict) else None
        return {
            "dungeon_key":      self._dungeon_combo.currentData() or "custom",
            "enforce_to":       self._enforce_to_check.isChecked(),
            "turn_order":       [cb.currentText() for cb in self._turn_order_combos],
            "include_occupied": self._include_chk.isChecked(),
            "include_locked":   self._include_locked_chk.isChecked(),
            "assume_max":       self._assume_max_chk.isChecked(),
            "optimize_artifacts": self._optimize_artifacts_chk.isChecked(),
            "min_stars":        int(self._stars_combo.currentText()),
            "leader_unit_id":   leader_uid,
            "slots":            slot_configs,
        }

    def _apply_config(self, cfg: dict):
        """Restore UI state from a config dict."""
        import json as _json

        # Dungeon
        dkey = cfg.get("dungeon_key", "custom")
        for i in range(self._dungeon_combo.count()):
            if self._dungeon_combo.itemData(i) == dkey:
                self._dungeon_combo.setCurrentIndex(i)
                break

        # Turn order
        to_vals = cfg.get("turn_order", [])
        for i, cb in enumerate(self._turn_order_combos):
            val = to_vals[i] if i < len(to_vals) else _TO_EMPTY
            idx = cb.findText(val)
            if idx >= 0:
                cb.setCurrentIndex(idx)

        # Enforce toggle (set after turn order so derive fires correctly)
        self._enforce_to_check.setChecked(bool(cfg.get("enforce_to", False)))

        # Pool options
        self._include_chk.setChecked(bool(cfg.get("include_occupied", False)))
        self._include_locked_chk.setChecked(bool(cfg.get("include_locked", False)))
        self._assume_max_chk.setChecked(bool(cfg.get("assume_max", True)))
        self._optimize_artifacts_chk.setChecked(
            bool(cfg.get("optimize_artifacts", True))
        )
        stars_str = str(cfg.get("min_stars", 5))
        si = self._stars_combo.findText(stars_str)
        if si >= 0:
            self._stars_combo.setCurrentIndex(si)

        # Slots
        slot_cfgs = cfg.get("slots", [])
        for idx, sw in enumerate(self._slot_widgets):
            sc = slot_cfgs[idx] if idx < len(slot_cfgs) else None
            if not sc:
                sw._combo.setCurrentIndex(-1)
                sw._combo.lineEdit().clear()
                continue
            # Monster
            uid = sc.get("unit_id")
            found = False
            for ci in range(sw._combo.count()):
                d = sw._combo.itemData(ci)
                if isinstance(d, dict) and d.get("unit_id") == uid:
                    sw._combo.setCurrentIndex(ci)
                    found = True
                    break
            if not found:
                sw._combo.setCurrentIndex(-1)
                sw._combo.lineEdit().clear()
            # Role
            role = sc.get("role", "-- none --")
            ri = sw._role_combo.findText(role)
            if ri >= 0:
                sw._role_combo.setCurrentIndex(ri)
            # Priority
            sw._priority_spin.setValue(int(sc.get("priority", idx + 1)))
            # Set reqs
            set_reqs = sc.get("set_reqs", [])
            for si2, scb in enumerate(sw._set_combos):
                val = set_reqs[si2] if si2 < len(set_reqs) else ""
                vi = scb.findText(val)
                if vi >= 0:
                    scb.setCurrentIndex(vi)
            # Main stat constraints
            msc = sc.get("main_stat_constraints", {})
            for slot_no, mcb in sw._main_combos.items():
                val = msc.get(str(slot_no), msc.get(slot_no, "Any"))
                vi = mcb.findText(str(val))
                if vi >= 0:
                    mcb.setCurrentIndex(vi)
            # Target stats
            mode = str(sc.get("target_mode") or "total")
            for i in range(sw._target_mode_combo.count()):
                if sw._target_mode_combo.itemData(i) == mode:
                    sw._target_mode_combo.setCurrentIndex(i)
                    break
            ts = sc.get("target_stats", {})
            for stat, sb in sw._target_spins.items():
                sb.setValue(int(ts.get(stat, 0) or 0))
            # Dungeon combat assumptions
            saved_skill_id = sc.get("skill_id")
            if saved_skill_id is not None:
                for skill_index in range(1, sw._skill_combo.count()):
                    skill_data = sw._skill_combo.itemData(skill_index)
                    if isinstance(skill_data, dict) and skill_data.get("skill_id") == saved_skill_id:
                        sw._skill_combo.setCurrentIndex(skill_index)
                        break
            else:
                sw._skill_combo.setCurrentIndex(0)
            sw._skill_atk_spin.setValue(
                float(sc.get("skill_atk_multiplier", 3.0) or 0)
            )
            sw._skill_hits_spin.setValue(int(sc.get("skill_hits", 1) or 1))
            sw._skill_aoe_check.setChecked(bool(sc.get("skill_aoe", False)))
            sw._def_break_check.setChecked(
                bool(sc.get("provides_defense_break", False))
            )
            sw._atk_buff_check.setChecked(
                bool(sc.get("provides_atk_buff", False))
            )
            # Scoring mode
            sm = sc.get("scoring_mode", "desirability")
            for ci in range(sw._scoring_combo.count()):
                if sw._scoring_combo.itemData(ci) == sm:
                    sw._scoring_combo.setCurrentIndex(ci)
                    break

        # Leader — re-scan slots first, then match unit_id
        self._refresh_leader_from_slots()
        leader_uid = cfg.get("leader_unit_id")
        if leader_uid is not None:
            for ci in range(self._leader_combo.count()):
                d = self._leader_combo.itemData(ci)
                if isinstance(d, dict) and d.get("unit_id") == leader_uid:
                    self._leader_combo.setCurrentIndex(ci)
                    break

    def _save_config(self):
        """Open a name dialog and save the current config."""
        from PySide6.QtWidgets import QInputDialog
        import json as _json

        # Pre-fill with current combo selection name if any
        cur_id = self._saved_combo.currentData()
        cur_name = ""
        if cur_id is not None:
            cur_name = self._saved_combo.currentText()

        name, ok = QInputDialog.getText(
            self, "Save Team Config", "Config name:", text=cur_name
        )
        if not ok or not name.strip():
            return
        name = name.strip()

        cfg = self._gather_config()
        cfg_json = _json.dumps(cfg)
        dkey = cfg.get("dungeon_key", "custom")

        # Overwrite if same name already exists as selected item
        overwrite_id = cur_id if cur_id is not None and cur_name == name else None
        new_id = queries.save_team_config(
            self._conn, name, dkey, cfg_json, config_id=overwrite_id
        )
        self._refresh_saved_combo()
        # Re-select the just-saved config in the combo
        for i in range(self._saved_combo.count()):
            if self._saved_combo.itemData(i) == new_id:
                self._saved_combo.setCurrentIndex(i)
                break
        self._status_lbl.setText("Saved: \"" + name + "\"")

    def _load_config(self):
        """Load the selected config from the combo into the UI."""
        cfg_id = self._saved_combo.currentData()
        if cfg_id is None:
            self._status_lbl.setText("Select a saved config first.")
            return
        row = queries.load_team_config(self._conn, cfg_id)
        if not row:
            self._status_lbl.setText("Config not found.")
            return
        self._apply_config(row["config"])
        self._status_lbl.setText("Loaded: \"" + row["name"] + "\"")

    def _delete_config(self):
        """Delete the selected config after confirmation."""
        from PySide6.QtWidgets import QMessageBox
        cfg_id = self._saved_combo.currentData()
        if cfg_id is None:
            self._status_lbl.setText("Select a saved config first.")
            return
        name = self._saved_combo.currentText()
        ans = QMessageBox.question(
            self, "Delete Config",
            "Delete \"" + name + "\"?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        queries.delete_team_config(self._conn, cfg_id)
        self._refresh_saved_combo()
        self._status_lbl.setText("Deleted: \"" + name + "\"")

    def _sec(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl.setStyleSheet("color: " + TEXT_DIM + "; margin-top: 4px;")
        return lbl

    def _on_enforce_to_toggled(self, checked: bool):
        """Called when the Enforce Turn Order checkbox is toggled."""
        if checked:
            self._derive_btn.setEnabled(False)
            self._derive_spd_targets()
        else:
            self._derive_btn.setEnabled(True)
            # Clear only the SPD targets that came from the plan
            planned_slots: set[int] = set()
            for cb in self._turn_order_combos:
                lbl = cb.currentText()
                if lbl and lbl.startswith("S"):
                    try:
                        planned_slots.add(int(lbl[1:]) - 1)
                    except ValueError:
                        pass
            for idx in planned_slots:
                if idx < len(self._slot_widgets):
                    spd_spin = self._slot_widgets[idx]._target_spins.get("SPD")
                    if spd_spin is not None:
                        spd_spin.setValue(0)
            self._status_lbl.setText("Turn order enforcement off — SPD targets cleared.")

    def _on_to_combo_changed(self):
        """Re-derive SPD targets whenever a turn-order combo changes (if enforced)."""
        if self._enforce_to_check.isChecked():
            self._derive_spd_targets()

    def _derive_spd_targets(self):
        key       = self._dungeon_combo.currentData() or "custom"
        profile   = DUNGEON_PROFILES.get(key, {})
        enemy_spd = int(profile.get("max_enemy_spd", 0) or 0)
        if enemy_spd == 0:
            self._status_lbl.setText("Select a dungeon with known enemy SPD first.")
            return

        planned: list[tuple[int, str]] = [
            (i, cb.currentText())
            for i, cb in enumerate(self._turn_order_combos)
            if cb.currentText() and cb.currentText() != _TO_EMPTY
        ]
        if not planned:
            self._status_lbl.setText("Fill in at least one position in the plan.")
            return

        enemy_rank = next((r for r, (_, lbl) in enumerate(planned) if lbl == _TO_ENEMY), None)
        derived: list[str] = []

        for rank, (_, lbl) in enumerate(planned):
            if lbl == _TO_ENEMY or not lbl.startswith("S"):
                continue
            try:
                slot_idx = int(lbl[1:]) - 1
            except ValueError:
                continue
            if slot_idx < 0 or slot_idx >= len(self._slot_widgets):
                continue
            spd_spin = self._slot_widgets[slot_idx]._target_spins.get("SPD")
            if spd_spin is None:
                continue

            if enemy_rank is None:
                spd_target = max(1, 200 - rank * 10)
            elif rank < enemy_rank:
                buffer = (enemy_rank - rank) * 5
                spd_target = enemy_spd + buffer
            else:
                spd_spin.setValue(0)
                derived.append(lbl + " cleared")
                continue

            spd_spin.setValue(spd_target)
            derived.append(lbl + "=" + str(spd_target))

        if derived:
            self._status_lbl.setText("SPD targets: " + ", ".join(derived))
        else:
            self._status_lbl.setText("Nothing to derive -- check plan.")

    def _load_monsters(self):
        try:
            monsters = queries.get_monsters(self._conn)
            self._monsters = monsters
            for sw in self._slot_widgets:
                sw.set_monsters(monsters)
            # Populate leader skill dropdown from current slot selections
            self._refresh_leader_from_slots()
            if monsters:
                self._monsters_loaded = True
                self._status_lbl.setText(str(len(monsters)) + " monsters loaded")
            else:
                self._status_lbl.setText("No monsters -- import your account first")
        except Exception as exc:
            import traceback
            print("[TeamOptimizer] _load_monsters failed:", exc, file=sys.stderr)
            traceback.print_exc()
            self._status_lbl.setText("Failed to load monsters: " + str(exc))

    def _refresh_leader_from_slots(self):
        """Rebuild leader combo from monsters currently selected in team slots."""
        leaders = []
        seen_ids: set = set()
        for sw in self._slot_widgets:
            m = sw._combo.currentData()
            if not m or not isinstance(m, dict):
                continue
            uid = m.get("unit_id")
            if uid in seen_ids:
                continue
            seen_ids.add(uid)
            if m.get("leader_skill_attribute"):
                attr = m.get("leader_skill_attribute", "?")
                amt  = m.get("leader_skill_amount", 0)
                area = m.get("leader_skill_area", "General")
                elem = m.get("leader_skill_element")
                if elem:
                    label = "%s +%d%% (%s, %s only)" % (attr, amt, area, elem)
                else:
                    label = "%s +%d%% (%s)" % (attr, amt, area)
                d = dict(m)
                d["leader_skill_label"] = label
                leaders.append(d)
        self._populate_leader_combo(leaders)

    def _on_leader_changed(self):
        idx = self._leader_combo.currentIndex()
        data = self._leader_combo.itemData(idx)
        if data and isinstance(data, dict):
            lbl = data.get("leader_skill_label", "")
            self._leader_desc.setText(lbl)
            self._leader_desc.setVisible(bool(lbl))
        else:
            self._leader_desc.setVisible(False)

    def _populate_leader_combo(self, leaders: list):
        self._leader_combo.blockSignals(True)
        self._leader_combo.clear()
        self._leader_combo.addItem("-- None (no leader) --", userData=None)
        for m in leaders:
            label = m.get("display_name", "?") + "  —  " + m.get("leader_skill_label", "")
            self._leader_combo.addItem(label, userData=m)
        self._leader_combo.blockSignals(False)
        self._on_leader_changed()

    def refresh(self):
        self._load_monsters()
        self._results.show_placeholder()

    def _on_dungeon_changed(self):
        key = self._dungeon_combo.currentData() or "custom"
        profile = DUNGEON_PROFILES.get(key, {})
        self._dungeon_notes.setText(profile.get("notes", ""))

    def _auto_fill_all(self):
        key = self._dungeon_combo.currentData() or "custom"
        for sw in self._slot_widgets:
            sw.apply_dungeon_role(key)

    def is_task_running(self) -> bool:
        """Return whether this page currently owns a running search."""
        return is_task_running(self._worker)

    def cancel_active_task(self, timeout_ms: int = 5000) -> bool:
        """Cooperatively stop the active search before application shutdown."""
        return cancel_task(self._worker, timeout_ms)

    def _run_optimize(self):
        slot_configs = [sw.get_config() for sw in self._slot_widgets]
        slot_configs = [c for c in slot_configs if c is not None]
        if not slot_configs:
            self._status_lbl.setText("Add at least one monster.")
            return
        if self._worker and self._worker.isRunning():
            self._worker.requestInterruption()
            self._optimize_btn.setEnabled(False)
            self._status_lbl.setText("Cancelling...")
            return

        self._optimize_btn.setEnabled(True)
        self._optimize_btn.setText("Cancel Search")
        self._status_lbl.setText("Optimizing " + str(len(slot_configs)) + " monsters...")
        self._current_dungeon_key = self._dungeon_combo.currentData() or "custom"

        # Leader (applied to targets inside the optimizer, not just display)
        _li = self._leader_combo.currentIndex()
        leader = self._leader_combo.itemData(_li)
        leader = leader if isinstance(leader, dict) else None

        # Turn-order plan -> {slot_index: rank}, enemy rank, enemy spd
        turn_positions: dict[int, int] = {}
        enemy_rank = None
        rank = 0
        for cb in self._turn_order_combos:
            lbl = cb.currentText()
            if not lbl or lbl == _TO_EMPTY:
                continue
            rank += 1
            if lbl == _TO_ENEMY:
                enemy_rank = rank
            elif lbl.startswith("S"):
                try:
                    turn_positions[int(lbl[1:]) - 1] = rank
                except ValueError:
                    pass
        profile   = DUNGEON_PROFILES.get(self._current_dungeon_key, {})
        enemy_spd = int(profile.get("max_enemy_spd", 0) or 0)
        enforce   = self._enforce_to_check.isChecked()

        from pathlib import Path
        self._worker = _TeamWorker(
            conn_path        = Path(self._db_path),
            slot_configs     = slot_configs,
            min_stars        = int(self._stars_combo.currentText()),
            include_equipped = self._include_chk.isChecked(),
            include_locked   = self._include_locked_chk.isChecked(),
            leader           = leader,
            turn_positions   = turn_positions if enforce else {},
            enemy_rank       = enemy_rank if enforce else None,
            enemy_spd        = enemy_spd,
            assume_max       = self._assume_max_chk.isChecked(),
            dungeon_key      = self._current_dungeon_key,
            optimize_artifacts = self._optimize_artifacts_chk.isChecked(),
        )
        self._worker.finished.connect(self._on_finished)
        self._worker.progress.connect(self._status_lbl.setText)
        self._worker.start()

    def _on_finished(self, result):
        self._optimize_btn.setEnabled(True)
        self._optimize_btn.setText("Optimize Team")
        from optimizer.rune_optimizer import OptimizationCancelled
        if isinstance(result, OptimizationCancelled):
            self._status_lbl.setText("Search cancelled")
            return
        if isinstance(result, str):
            self._status_lbl.setText("")
            self._results.show_error(result)
            return
        (
            team_result,
            base_spd_map,
            monster_data_map,
            artifact_flat_map,
            bonuses_map,
            current_stats_map,
            artifact_pair_map,
        ) = result
        n = len(team_result.monsters)
        self._status_lbl.setText(str(n) + " monster" + ("s" if n != 1 else "") + " optimized")
        # Load building bonuses
        from desktop.db.queries import get_building_bonuses
        try:
            building_bonuses = get_building_bonuses(self._conn)
        except Exception:
            building_bonuses = None

        # Capture selected leader
        _li = self._leader_combo.currentIndex()
        selected_leader = self._leader_combo.itemData(_li)  # dict or None

        self._results.show_results(
            team_result,
            base_spd_map,
            self._current_dungeon_key,
            monster_data_map,
            artifact_flat_map,
            building_bonuses,
            selected_leader,
            current_stats_map,
            artifact_pair_map,
        )
