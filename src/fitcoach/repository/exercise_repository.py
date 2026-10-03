from collections.abc import Sequence
from typing import Protocol

from fitcoach.domain.exercise import Exercise


class ExerciseRepository(Protocol):
    async def search(
        self,
        query_vector: Sequence[float],
        top_k: int,
        equipment: Sequence[str] | None = None,
        muscle_group: str | None = None,
        target: str | None = None,
        excluded_ids: Sequence[int] = (),
    ) -> list[Exercise]:
        """Exercises closest to ``query_vector``, optionally restricted by equipment."""
        ...

    async def get_by_ids(self, ids: Sequence[int]) -> list[Exercise]: ...
