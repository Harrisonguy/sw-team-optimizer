"""Hardcoded dungeon profiles for the team optimizer.

Stat targets are derived from real dungeon data (swgt.io):
  - ACC target = max enemy RES in any wave (so debuffers can reliably land)
  - SPD target = max enemy SPD + ~5 buffer (to move before fastest mob)

Dungeon naming follows in-game convention:
  B10     = top standard floor
  Normal  = Abyss Normal mode
  Hard    = Abyss Hard mode
"""
from __future__ import annotations

from typing import TypedDict


class RoleTargets(TypedDict, total=False):
    SPD:  int
    CR:   int
    CD:   int
    ATK:  int
    HP:   int
    DEF:  int
    RES:  int
    ACC:  int


class DungeonProfile(TypedDict, total=False):
    display_name:  str
    category:      str
    dungeon_key:   str   # maps to dungeon_waves table key
    notes:         str
    max_enemy_spd: int
    max_enemy_res: int
    boss_element:  str   # element of the boss (Water/Fire/Wind/Light/Dark/"" if N/A)
    attacker:      RoleTargets
    tank:          RoleTargets
    support:       RoleTargets
    healer:        RoleTargets


DUNGEON_PROFILES: dict[str, DungeonProfile] = {
    # -----------------------------------------------------------------------
    # Giant's Keep
    # -----------------------------------------------------------------------
    "gb_b10": {
        "display_name": "Giant's Keep B10",
        "category": "Cairos",
        "dungeon_key": "Giant's Keep - B10",
        "notes": "Max enemy SPD 169, RES 70%. DoT team standard. High ACC needed (70%+).",
        "max_enemy_spd": 169,
        "max_enemy_res": 70,
        "boss_element": "Water",
        "attacker": {"SPD": 175, "CR%": 85, "CD%": 180, "ATK%": 0},
        "tank":     {"SPD": 172, "HP%": 0,   "DEF%": 0},
        "support":  {"SPD": 175, "ACC%": 70,  "HP%": 0},
        "healer":   {"SPD": 172, "HP%": 0,   "RES%": 45},
    },
    "gb_abyss_normal": {
        "display_name": "Giant's Keep Abyss Normal",
        "category": "Cairos Abyss",
        "dungeon_key": "Giant's Keep - Abyss Normal",
        "notes": "Max enemy SPD 169, RES 40%. Easier than B10 on ACC.",
        "max_enemy_spd": 169,
        "max_enemy_res": 40,
        "boss_element": "Water",
        "attacker": {"SPD": 175, "CR%": 85, "CD%": 180, "ATK%": 0},
        "tank":     {"SPD": 172, "HP%": 0,   "DEF%": 0},
        "support":  {"SPD": 175, "ACC%": 45,  "HP%": 0},
        "healer":   {"SPD": 172, "HP%": 0,   "RES%": 40},
    },
    "gb_abyss_hard": {
        "display_name": "Giant's Keep Abyss Hard",
        "category": "Cairos Abyss",
        "dungeon_key": "Giant's Keep - Abyss Hard",
        "notes": "Max enemy SPD 169, RES 50%. Harder than Normal.",
        "max_enemy_spd": 169,
        "max_enemy_res": 50,
        "boss_element": "Water",
        "attacker": {"SPD": 175, "CR%": 85, "CD%": 180, "ATK%": 0},
        "tank":     {"SPD": 172, "HP%": 0,   "DEF%": 0, "RES%": 40},
        "support":  {"SPD": 175, "ACC%": 55,  "HP%": 0},
        "healer":   {"SPD": 172, "HP%": 0,   "RES%": 45},
    },
    # -----------------------------------------------------------------------
    # Dragon's Lair
    # -----------------------------------------------------------------------
    "db_b10": {
        "display_name": "Dragon's Lair B10",
        "category": "Cairos",
        "dungeon_key": "Dragon's Lair - B10",
        "notes": "Max enemy SPD 169, RES 80%! Very high ACC needed on CC/debuff slot.",
        "max_enemy_spd": 169,
        "max_enemy_res": 80,
        "boss_element": "Fire",
        "attacker": {"SPD": 175, "CR%": 85, "CD%": 200, "ATK%": 0},
        "tank":     {"SPD": 172, "HP%": 0,   "DEF%": 0, "RES%": 45},
        "support":  {"SPD": 178, "ACC%": 85,  "HP%": 0},
        "healer":   {"SPD": 172, "HP%": 0,   "RES%": 55},
    },
    "db_abyss_normal": {
        "display_name": "Dragon's Lair Abyss Normal",
        "category": "Cairos Abyss",
        "dungeon_key": "Dragon's Lair - Abyss Normal",
        "notes": "Max enemy SPD 169, wave RES 70% but boss only 30%.",
        "max_enemy_spd": 169,
        "max_enemy_res": 70,
        "boss_element": "Fire",
        "attacker": {"SPD": 175, "CR%": 85, "CD%": 200, "ATK%": 0},
        "tank":     {"SPD": 172, "HP%": 0,   "DEF%": 0, "RES%": 45},
        "support":  {"SPD": 178, "ACC%": 75,  "HP%": 0},
        "healer":   {"SPD": 172, "HP%": 0,   "RES%": 55},
    },
    "db_abyss_hard": {
        "display_name": "Dragon's Lair Abyss Hard",
        "category": "Cairos Abyss",
        "dungeon_key": "Dragon's Lair - Abyss Hard",
        "notes": "Max enemy SPD 169, max RES 80%. Hardest ACC requirements in Cairos.",
        "max_enemy_spd": 169,
        "max_enemy_res": 80,
        "boss_element": "Fire",
        "attacker": {"SPD": 175, "CR%": 85, "CD%": 200, "ATK%": 0},
        "tank":     {"SPD": 172, "HP%": 0,   "DEF%": 0, "RES%": 55},
        "support":  {"SPD": 178, "ACC%": 85,  "HP%": 0},
        "healer":   {"SPD": 172, "HP%": 0,   "RES%": 60},
    },
    # -----------------------------------------------------------------------
    # Necropolis
    # -----------------------------------------------------------------------
    "nb_b10": {
        "display_name": "Necropolis B10",
        "category": "Cairos",
        "dungeon_key": "Necropolis - B10",
        "notes": "Max enemy SPD 169, RES 70%. Multi-hit + DoT. High ACC for debuffers.",
        "max_enemy_spd": 169,
        "max_enemy_res": 70,
        "boss_element": "Dark",
        "attacker": {"SPD": 172, "ACC%": 70,  "ATK%": 0},
        "tank":     {"SPD": 170, "HP%": 0,   "DEF%": 0, "RES%": 45},
        "support":  {"SPD": 175, "ACC%": 70,  "HP%": 0},
        "healer":   {"SPD": 170, "HP%": 0,   "RES%": 55},
    },
    "nb_abyss_normal": {
        "display_name": "Necropolis Abyss Normal",
        "category": "Cairos Abyss",
        "dungeon_key": "Necropolis - Abyss Normal",
        "notes": "Max enemy SPD 169, RES 30%. ACC requirement reduced significantly.",
        "max_enemy_spd": 169,
        "max_enemy_res": 30,
        "boss_element": "Dark",
        "attacker": {"SPD": 172, "ACC%": 35,  "ATK%": 0},
        "tank":     {"SPD": 170, "HP%": 0,   "DEF%": 0, "RES%": 40},
        "support":  {"SPD": 175, "ACC%": 35,  "HP%": 0},
        "healer":   {"SPD": 170, "HP%": 0,   "RES%": 45},
    },
    "nb_abyss_hard": {
        "display_name": "Necropolis Abyss Hard",
        "category": "Cairos Abyss",
        "dungeon_key": "Necropolis - Abyss Hard",
        "notes": "Max enemy SPD 169, RES 50%. Mid-range ACC.",
        "max_enemy_spd": 169,
        "max_enemy_res": 50,
        "boss_element": "Dark",
        "attacker": {"SPD": 172, "ACC%": 55,  "ATK%": 0},
        "tank":     {"SPD": 170, "HP%": 0,   "DEF%": 0, "RES%": 45},
        "support":  {"SPD": 175, "ACC%": 55,  "HP%": 0},
        "healer":   {"SPD": 170, "HP%": 0,   "RES%": 50},
    },
    # -----------------------------------------------------------------------
    # Steel Fortress
    # -----------------------------------------------------------------------
    "sf_b10": {
        "display_name": "Steel Fortress B10",
        "category": "Cairos",
        "dungeon_key": "Steel Fortress - B10",
        "notes": "Max enemy SPD 150, RES 40% throughout. DEF-break essential.",
        "max_enemy_spd": 150,
        "max_enemy_res": 40,
        "boss_element": "Wind",
        "attacker": {"SPD": 155, "CR%": 85, "CD%": 185, "ATK%": 0},
        "tank":     {"SPD": 152, "HP%": 0,   "DEF%": 0},
        "support":  {"SPD": 155, "ACC%": 45,  "HP%": 0},
        "healer":   {"SPD": 152, "HP%": 0,   "RES%": 35},
    },
    "sf_abyss_normal": {
        "display_name": "Steel Fortress Abyss Normal",
        "category": "Cairos Abyss",
        "dungeon_key": "Steel Fortress - Abyss Normal",
        "notes": "Max enemy SPD 150, RES 40%. Identical resistances to B10 but harder.",
        "max_enemy_spd": 150,
        "max_enemy_res": 40,
        "boss_element": "Wind",
        "attacker": {"SPD": 158, "CR%": 85, "CD%": 185, "ATK%": 0},
        "tank":     {"SPD": 155, "HP%": 0,   "DEF%": 0, "RES%": 35},
        "support":  {"SPD": 158, "ACC%": 45,  "HP%": 0},
        "healer":   {"SPD": 155, "HP%": 0,   "RES%": 35},
    },
    "sf_abyss_hard": {
        "display_name": "Steel Fortress Abyss Hard",
        "category": "Cairos Abyss",
        "dungeon_key": "Steel Fortress - Abyss Hard",
        "notes": "Max enemy SPD 150, RES 40%. Harder HP/damage. Tankiness matters.",
        "max_enemy_spd": 150,
        "max_enemy_res": 40,
        "boss_element": "Wind",
        "attacker": {"SPD": 158, "CR%": 85, "CD%": 185, "ATK%": 0},
        "tank":     {"SPD": 155, "HP%": 0,   "DEF%": 0, "RES%": 35},
        "support":  {"SPD": 158, "ACC%": 45,  "HP%": 0},
        "healer":   {"SPD": 155, "HP%": 0,   "RES%": 40},
    },
    # -----------------------------------------------------------------------
    # Punisher's Crypt
    # -----------------------------------------------------------------------
    "pc_b10": {
        "display_name": "Punisher's Crypt B10",
        "category": "Cairos",
        "dungeon_key": "Punisher's Crypt - B10",
        "notes": "Max wave enemy SPD 175 (boss 164), wave RES 54%. Fastest dungeon. "
                 "Speed tuning is everything.",
        "max_enemy_spd": 175,
        "max_enemy_res": 54,
        "boss_element": "Light",
        "attacker": {"SPD": 182, "CR%": 85, "CD%": 180, "ATK%": 0},
        "tank":     {"SPD": 178, "HP%": 0,   "DEF%": 0},
        "support":  {"SPD": 185, "ACC%": 59,  "HP%": 0},
        "healer":   {"SPD": 180, "HP%": 0,   "RES%": 45},
    },
    "pc_abyss_normal": {
        "display_name": "Punisher's Crypt Abyss Normal",
        "category": "Cairos Abyss",
        "dungeon_key": "Punisher's Crypt - Abyss Normal",
        "notes": "Same enemy SPD 175, RES 54%. Harder damage. Speed tuning still key.",
        "max_enemy_spd": 175,
        "max_enemy_res": 54,
        "boss_element": "Light",
        "attacker": {"SPD": 182, "CR%": 85, "CD%": 180, "ATK%": 0},
        "tank":     {"SPD": 180, "HP%": 0,   "DEF%": 0, "RES%": 45},
        "support":  {"SPD": 185, "ACC%": 59,  "HP%": 0},
        "healer":   {"SPD": 180, "HP%": 0,   "RES%": 50},
    },
    "pc_abyss_hard": {
        "display_name": "Punisher's Crypt Abyss Hard",
        "category": "Cairos Abyss",
        "dungeon_key": "Punisher's Crypt - Abyss Hard",
        "notes": "Enemy SPD 175, RES 54%. Hardest PC content. More tankiness needed.",
        "max_enemy_spd": 175,
        "max_enemy_res": 54,
        "boss_element": "Light",
        "attacker": {"SPD": 185, "CR%": 85, "CD%": 180, "ATK%": 0},
        "tank":     {"SPD": 182, "HP%": 0,   "DEF%": 0, "RES%": 50},
        "support":  {"SPD": 188, "ACC%": 59,  "HP%": 0},
        "healer":   {"SPD": 182, "HP%": 0,   "RES%": 55},
    },
    # -----------------------------------------------------------------------
    # Spiritual Realm  (Abyss dungeon — "ABYSS 12")
    # -----------------------------------------------------------------------
    "abyss_b10": {
        "display_name": "Spiritual Realm B10",
        "category": "Spiritual Realm",
        "dungeon_key": "Spiritual Realm - B10",
        "notes": "Max wave SPD 177, RES 50%. Boss SPD only 98 but waves are fast.",
        "max_enemy_spd": 177,
        "max_enemy_res": 50,
        "boss_element": "Wind",
        "attacker": {"SPD": 183, "CR%": 85, "CD%": 185, "ATK%": 0},
        "tank":     {"SPD": 180, "HP%": 0,   "DEF%": 0, "RES%": 45},
        "support":  {"SPD": 185, "ACC%": 55,  "HP%": 0},
        "healer":   {"SPD": 181, "HP%": 0,   "RES%": 50},
    },
    "abyss_normal": {
        "display_name": "Spiritual Realm Abyss Normal",
        "category": "Spiritual Realm",
        "dungeon_key": "Spiritual Realm - Abyss Normal",
        "notes": "Max wave SPD 177, RES 50%. Mid Abyss difficulty.",
        "max_enemy_spd": 177,
        "max_enemy_res": 50,
        "boss_element": "Wind",
        "attacker": {"SPD": 183, "CR%": 85, "CD%": 185, "ATK%": 0},
        "tank":     {"SPD": 180, "HP%": 0,   "DEF%": 0, "RES%": 50},
        "support":  {"SPD": 185, "ACC%": 55,  "HP%": 0},
        "healer":   {"SPD": 181, "HP%": 0,   "RES%": 55},
    },
    "abyss_hard": {
        "display_name": "Spiritual Realm Abyss Hard",
        "category": "Spiritual Realm",
        "dungeon_key": "Spiritual Realm - Abyss Hard",
        "notes": "Hardest Abyss content. Max wave SPD 177, RES 50%. "
                 "Highest HP boss. Speed + tankiness.",
        "max_enemy_spd": 177,
        "max_enemy_res": 50,
        "boss_element": "Wind",
        "attacker": {"SPD": 185, "CR%": 85, "CD%": 185, "ATK%": 0},
        "tank":     {"SPD": 182, "HP%": 0,   "DEF%": 0, "RES%": 55},
        "support":  {"SPD": 188, "ACC%": 55,  "HP%": 0},
        "healer":   {"SPD": 183, "HP%": 0,   "RES%": 60},
    },
    # -----------------------------------------------------------------------
    # Rift Beasts
    # -----------------------------------------------------------------------
    "rift": {
        "display_name": "Rift Beasts",
        "category": "Rift",
        "dungeon_key": "",
        "notes": "ATK/HP teams. Speed less critical. Violent recommended. Max damage.",
        "max_enemy_spd": 0,
        "max_enemy_res": 0,
        "attacker": {"CR%": 85, "CD%": 200, "ATK%": 0, "SPD": 140},
        "tank":     {"HP%": 0,  "DEF%": 0,  "SPD": 130},
        "support":  {"HP%": 0,  "ACC%": 45, "SPD": 130},
        "healer":   {"HP%": 0,  "RES%": 35, "SPD": 130},
    },
    # -----------------------------------------------------------------------
    # PvP
    # -----------------------------------------------------------------------
    "pvp": {
        "display_name": "PvP / Arena / RTA",
        "category": "PvP",
        "dungeon_key": "",
        "notes": "Speed is everything. Violent/Will dominant. Tune to your bracket.",
        "max_enemy_spd": 0,
        "max_enemy_res": 0,
        "attacker": {"SPD": 200, "CR%": 85, "CD%": 200, "ATK%": 0},
        "tank":     {"SPD": 190, "HP%": 0,   "DEF%": 0, "RES%": 55},
        "support":  {"SPD": 205, "ACC%": 65,  "HP%": 0, "RES%": 55},
        "healer":   {"SPD": 195, "HP%": 0,   "RES%": 65},
    },
    # -----------------------------------------------------------------------
    # Custom
    # -----------------------------------------------------------------------
    "custom": {
        "display_name": "Custom",
        "category": "Custom",
        "dungeon_key": "",
        "notes": "Set your own targets per monster.",
        "max_enemy_spd": 0,
        "max_enemy_res": 0,
        "attacker": {},
        "tank":     {},
        "support":  {},
        "healer":   {},
    },
}

ROLES = ["Attacker", "Tank", "Support", "Healer"]

ROLE_KEY: dict[str, str] = {
    "Attacker": "attacker",
    "Tank":     "tank",
    "Support":  "support",
    "Healer":   "healer",
}

TARGET_STAT_KEYS = ["HP", "ATK", "DEF", "SPD", "CR%", "CD%", "RES%", "ACC%"]
