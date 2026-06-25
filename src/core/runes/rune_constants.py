RUNE_SET_NAMES: dict[int, str] = {
    1: "Energy",
    2: "Guard",
    3: "Swift",
    4: "Blade",
    5: "Rage",
    6: "Focus",
    7: "Endure",
    8: "Fatal",
    10: "Despair",
    11: "Vampire",
    13: "Violent",
    14: "Nemesis",
    15: "Will",
    16: "Shield",
    17: "Revenge",
    18: "Destroy",
    19: "Fight",
    20: "Determination",
    21: "Enhance",
    22: "Accuracy",
    23: "Tolerance",
    24: "Seal",
    25: "Intangible",
}


RUNE_STAT_NAMES: dict[int, str] = {
    1: "Flat HP",
    2: "HP%",
    3: "Flat ATK",
    4: "ATK%",
    5: "Flat DEF",
    6: "DEF%",
    8: "SPD",
    9: "CR",
    10: "CD",
    11: "RES",
    12: "ACC",
}


def rune_set_name(set_id: int | None) -> str:
    if set_id is None:
        return "Unknown"
    return RUNE_SET_NAMES.get(set_id, f"Unknown Set {set_id}")


def rune_stat_name(stat_id: int | None) -> str:
    if stat_id is None:
        return "Unknown"
    return RUNE_STAT_NAMES.get(stat_id, f"Unknown Stat {stat_id}")