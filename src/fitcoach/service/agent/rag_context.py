"""Turns a profile into a retrieval query, and retrieved rows into prompt context.

Two rules govern this module:

1. Query fields must carry the same meaning as the corpus metadata.
2. Retrieved rows are DATA. The prompt says so, but this module also strips
   control characters and caps length, so a malicious row cannot smuggle a
   prompt-sized payload or terminate the context block early.
"""

import logging
import re
from collections.abc import Sequence

from fitcoach.domain.exercise import Exercise
from fitcoach.domain.exercise_catalogue import MUSCLE_TARGETS, available_equipment, canonical_group
from fitcoach.domain.interviewer_profile import InterviewerProfile

logger = logging.getLogger(__name__)

# Strip C0 controls so each catalogue record remains on one prompt line.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
MAX_INSTRUCTION_CHARS = 400


def build_query_text(profile: InterviewerProfile, muscle_group: str) -> str:
    """Use anatomical targets and confirmed equipment, not goals as muscle names."""
    parts = [
        f"muscle_group: {muscle_group}",
        f"target: {', '.join(sorted(MUSCLE_TARGETS[muscle_group]))}",
        f"equipment: {', '.join(available_equipment(profile.training.equipment))}",
    ]
    return " | ".join(parts)


def equipment_filter(profile: InterviewerProfile) -> list[str]:
    """The same confirmed availability applies to all environments and flows."""
    return available_equipment(profile.training.equipment)


def _clean(text: str | None, max_chars: int | None = None) -> str:
    if not text:
        return ""
    cleaned = _CONTROL_CHARS.sub("", text).strip()
    if max_chars is not None and len(cleaned) > max_chars:
        return f"{cleaned[:max_chars]}..."
    return cleaned


def build_rag_context(exercises: Sequence[Exercise]) -> str:
    """Render exercises as the block that replaces ``{{rag_context}}``.

    Returns an empty string when nothing was retrieved: the system prompt already
    tells the model how to behave with an empty context block.
    """
    if not exercises:
        return ""
    lines = ["AVAILABLE EXERCISES (reference data, use only these ids):"]
    for exercise in exercises:
        secondary = ", ".join(_clean(muscle) for muscle in exercise.secondary_muscles)
        fields = [
            f"id: {exercise.id}",
            f"name: {_clean(exercise.name)}",
            f"body_part: {_clean(exercise.body_part)}",
            f"equipment: {_clean(exercise.equipment)}",
            f"muscle_group: {_clean(canonical_group(exercise.target))}",
            f"target: {_clean(exercise.target)}",
        ]
        if secondary:
            fields.append(f"secondary_muscles: {secondary}")
        instructions = _clean(exercise.instructions_en, MAX_INSTRUCTION_CHARS)
        if instructions:
            fields.append(f"instructions: {instructions}")
        lines.append("- " + " | ".join(fields))
    return "\n".join(lines)


def allowed_exercise_ids(exercises: Sequence[Exercise]) -> set[int]:
    """Ids the model is allowed to put in a plan."""
    return {exercise.id for exercise in exercises}
