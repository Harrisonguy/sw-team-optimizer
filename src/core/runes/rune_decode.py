from __future__ import annotations


QUALITY_NAMES: dict[int, str] = {
    1: "Normal",
    2: "Magic",
    3: "Rare",
    4: "Hero",
    5: "Legend",
}


def is_ancient_class(raw_class: int | None) -> bool:
    """
    SWEX class appears to encode both stars and ancient status.

    1-6   = normal rune stars
    11-16 = ancient rune stars
    """
    if raw_class is None:
        return False

    return raw_class >= 11


def rune_stars_from_class(raw_class: int | None) -> int | None:
    """
    Examples:
    class 6  -> 6★ normal
    class 16 -> 6★ ancient
    """
    if raw_class is None:
        return None

    if raw_class >= 11:
        return raw_class - 10

    return raw_class


def quality_code(raw_quality: int | None) -> int | None:
    """
    Quality appears to be:
    1-5   for normal quality
    11-15 for ancient quality

    This returns the base quality code:
    15 -> 5
    14 -> 4
    5  -> 5
    4  -> 4
    """
    if raw_quality is None:
        return None

    if raw_quality >= 11:
        return raw_quality - 10

    return raw_quality


def is_ancient_quality(raw_quality: int | None) -> bool:
    if raw_quality is None:
        return False

    return raw_quality >= 11


def quality_name(raw_quality: int | None) -> str:
    code = quality_code(raw_quality)

    if code is None:
        return "Unknown"

    return QUALITY_NAMES.get(code, f"Unknown Quality {raw_quality}")


def rune_type_label(raw_class: int | None) -> str:
    if is_ancient_class(raw_class):
        return "Ancient"

    return "Normal"


def rune_stars_label(raw_class: int | None) -> str:
    stars = rune_stars_from_class(raw_class)

    if stars is None:
        return "Unknown ★"

    return f"{stars}★"