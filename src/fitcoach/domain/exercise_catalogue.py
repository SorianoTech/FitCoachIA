"""Canonical classification and equipment vocabulary for the read-only catalogue."""

from collections.abc import Sequence

MUSCLE_TARGETS: dict[str, frozenset[str]] = {
    "chest": frozenset({"pectorals"}),
    "back": frozenset({"lats", "upper back", "traps", "spine"}),
    "legs": frozenset({"quads", "hamstrings", "glutes", "calves", "adductors", "abductors"}),
    "shoulders": frozenset({"delts"}),
    "arms": frozenset({"biceps", "triceps", "forearms"}),
    "core": frozenset({"abs", "serratus anterior"}),
    "cardio": frozenset({"cardiovascular system"}),
}

_EQUIPMENT_ALIASES = {
    "barra": "barbell",
    "mancuernas": "dumbbell",
    "mancuerna": "dumbbell",
    "bandas": "resistance band",
    "banda elastica": "resistance band",
    "banda elástica": "resistance band",
    "band": "resistance band",
    "peso corporal": "body weight",
    "polea": "cable",
    "poleas": "cable",
    "maquina smith": "smith machine",
}
_KNOWN_EQUIPMENT = frozenset({
    "barbell",
    "dumbbell",
    "body weight",
    "cable",
    "resistance band",
    "kettlebell",
    "stability ball",
    "smith machine",
    "leverage machine",
    "assisted",
    "weighted",
    "medicine ball",
    "bosu ball",
    "roller",
    "rope",
    "elliptical machine",
    "stationary bike",
    "skierg machine",
    "upper body ergometer",
    "trap bar",
    "ez barbell",
    "sled machine",
    "olympic barbell",
    "hammer",
    "wheel roller",
    "tire",
    "stepmill machine",
})


class EquipmentClarificationError(ValueError):
    """Declared equipment cannot be matched to the catalogue."""


def canonical_group(target: str | None) -> str | None:
    return next((group for group, targets in MUSCLE_TARGETS.items() if target in targets), None)


def normalize_equipment(value: str) -> str:
    normalized = value.lower().strip()
    return _EQUIPMENT_ALIASES.get(normalized, normalized)


def known_equipment() -> list[str]:
    return sorted(_KNOWN_EQUIPMENT)


def available_equipment(declared: Sequence[str]) -> list[str]:
    equipment = {"body weight"}
    for value in declared:
        normalized = normalize_equipment(value)
        if normalized not in _KNOWN_EQUIPMENT:
            raise EquipmentClarificationError(f"Equipment needs clarification: {value}")
        equipment.add(normalized)
    return sorted(equipment)


def catalogue_equipment(values: Sequence[str]) -> list[str]:
    """Expand only corpus synonyms; distinct apparatus remain distinct."""
    equipment = {normalize_equipment(value) for value in values}
    if "resistance band" in equipment:
        equipment.add("band")
    return sorted(equipment)
