from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.core.resources import DATA_DIR


ARTIFACT_EFFECTS_FILE = DATA_DIR / "artifact_effects.json"


ARTIFACT_QUALITY_NAMES: dict[int, str] = {
    1: "Normal",
    2: "Magic",
    3: "Rare",
    4: "Hero",
    5: "Legend",
}


ARTIFACT_ATTRIBUTE_NAMES: dict[int, str] = {
    0: "None",
    1: "Water",
    2: "Fire",
    3: "Wind",
    4: "Light",
    5: "Dark",
}


ARTIFACT_UNIT_STYLE_NAMES: dict[int, str] = {
    0: "None",
    1: "Attack",
    2: "Defense",
    3: "HP",
    4: "Support",
}


@lru_cache(maxsize=1)
def load_artifact_effect_definitions() -> dict[str, dict[str, Any]]:
    if not ARTIFACT_EFFECTS_FILE.exists():
        #print(f"WARNING: Missing artifact effects file: {ARTIFACT_EFFECTS_FILE.resolve()}")
        return {}

    with ARTIFACT_EFFECTS_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)

    print(f"Loaded {len(data)} artifact effect definitions from {ARTIFACT_EFFECTS_FILE.resolve()}")
    return data


def artifact_quality_name(rank: int | None) -> str:
    if rank is None:
        return "Unknown"

    return ARTIFACT_QUALITY_NAMES.get(rank, f"Unknown Quality {rank}")


def artifact_attribute_name(attribute: int | None) -> str:
    if attribute is None:
        return "Unknown"

    return ARTIFACT_ATTRIBUTE_NAMES.get(attribute, f"Unknown Attribute {attribute}")


def artifact_unit_style_name(unit_style: int | None) -> str:
    if unit_style is None:
        return "Unknown"

    return ARTIFACT_UNIT_STYLE_NAMES.get(unit_style, f"Unknown Style {unit_style}")


def artifact_effect_name(effect_id: int | None) -> str:
    if effect_id is None:
        return "Unknown Effect"

    definitions = load_artifact_effect_definitions()
    definition = definitions.get(str(effect_id))

    if not definition:
        return f"Artifact Effect {effect_id}"

    return definition.get("name") or f"Artifact Effect {effect_id}"


def artifact_effect_definition(effect_id: int | None) -> dict[str, Any] | None:
    if effect_id is None:
        return None

    return load_artifact_effect_definitions().get(str(effect_id))