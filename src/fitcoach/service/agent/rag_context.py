"""Turns a profile into a retrieval query, and retrieved rows into prompt context.

Two rules govern this module:

1. The query text must be built exactly like ``build_metadata_text()`` in
   ``infra/vector-db/loader/loader.py``, or the query lands in a different
   region of the embedding space than the corpus it is compared against.
2. Retrieved rows are DATA. The prompt says so, but this module also strips
   control characters and caps length, so a malicious row cannot smuggle a
   prompt-sized payload or terminate the context block early.
"""

import logging
import re
from collections.abc import Sequence

from fitcoach.domain.exercise import Exercise
from fitcoach.domain.interviewer_profile import InterviewerProfile

logger = logging.getLogger(__name__)

# Everything except tab/newline: keeps the block readable and un-spoofable.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
MAX_INSTRUCTION_CHARS = 400

# Equipment values in the corpus for someone training without a gym. Used as a
# cheap SQL prefilter before the semantic ordering.
_HOME_EQUIPMENT = ("body weight", "dumbbell", "resistance band", "kettlebell", "stability ball")
_OUTDOOR_EQUIPMENT = ("body weight", "resistance band")


def build_query_text(profile: InterviewerProfile, muscle_group: str) -> str:
    """Compose the retrieval query in the loader's ``key: value | ...`` shape."""
    parts = [
        f"muscle_group: {muscle_group}",
        f"target: {profile.goal.primary.replace('_', ' ')}",
        f"equipment: {', '.join(profile.training.equipment)}",
        f"category: {profile.training.environment}",
    ]
    return " | ".join(parts)


def equipment_filter(profile: InterviewerProfile) -> list[str] | None:
    """Equipment values worth restricting to, or None to search the whole corpus.

    A gym member can use anything, so filtering would only cost recall.
    """
    if profile.training.environment == "gym":
        return None
    if profile.training.environment == "home":
        return list(_HOME_EQUIPMENT)
    if profile.training.environment == "outdoors":
        return list(_OUTDOOR_EQUIPMENT)
    return None


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
            f"muscle_group: {_clean(exercise.muscle_group)}",
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
