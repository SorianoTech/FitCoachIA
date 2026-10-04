import pytest

from fitcoach.domain.exercise import Exercise
from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.service.agent.rag_context import (
    MAX_INSTRUCTION_CHARS,
    allowed_exercise_ids,
    build_query_text,
    build_rag_context,
    equipment_filter,
)


class TestBuildQueryText:
    def test_uses_the_loaders_pipe_separated_shape(self, profile: InterviewerProfile) -> None:
        query = build_query_text(profile, "chest")

        assert query.startswith("muscle_group: chest | ")
        assert " | " in query
        assert "target: pectorals" in query
        assert "gain muscle" not in query
        assert "category: gym" not in query
        assert "equipment: barbell" in query


class TestEquipmentFilter:
    def test_restricts_a_gym_member_to_confirmed_equipment(
        self, profile: InterviewerProfile
    ) -> None:
        assert equipment_filter(profile) == ["barbell", "body weight"]

    @pytest.mark.parametrize(
        ("environment", "expected_member"),
        [("home", "body weight"), ("outdoors", "body weight")],
    )
    def test_restricts_equipment_outside_the_gym(
        self, profile: InterviewerProfile, environment: str, expected_member: str
    ) -> None:
        home_profile = profile.model_copy(
            update={"training": profile.training.model_copy(update={"environment": environment})}
        )

        result = equipment_filter(home_profile)

        assert result is not None
        assert expected_member in result

    def test_restricts_a_mixed_environment(self, profile: InterviewerProfile) -> None:
        mixed = profile.model_copy(
            update={"training": profile.training.model_copy(update={"environment": "mixed"})}
        )

        assert equipment_filter(mixed) == ["barbell", "body weight"]

    @pytest.mark.parametrize("environment", ["gym", "home", "outdoors", "mixed"])
    def test_only_bands_never_implies_dumbbells(
        self, profile: InterviewerProfile, environment: str
    ) -> None:
        profile.training.environment = environment
        profile.training.equipment = ["bandas"]
        assert equipment_filter(profile) == ["body weight", "resistance band"]


class TestBuildRagContext:
    def test_renders_one_line_per_exercise_with_its_id(self, exercises: list[Exercise]) -> None:
        context = build_rag_context(exercises)

        assert "id: 101" in context
        assert "id: 102" in context
        assert "barbell bench press" in context
        assert context.count("\n- ") == 2

    def test_returns_an_empty_string_when_nothing_was_retrieved(self) -> None:
        assert build_rag_context([]) == ""

    def test_truncates_long_instructions(self) -> None:
        exercise = Exercise(id=1, name="x", instructions_en="a" * (MAX_INSTRUCTION_CHARS + 50))

        context = build_rag_context([exercise])

        assert f"{'a' * MAX_INSTRUCTION_CHARS}..." in context
        assert "a" * (MAX_INSTRUCTION_CHARS + 1) not in context

    def test_strips_control_characters_from_corpus_text(self) -> None:
        # Corpus rows are data; a row must not be able to break out of its line.
        exercise = Exercise(id=1, name="push\x00up\x1b[31m", instructions_en="do\x07it")

        context = build_rag_context([exercise])

        assert "\x00" not in context
        assert "\x1b" not in context
        assert "\x07" not in context
        assert "pushup" in context

    def test_omits_empty_optional_fields(self) -> None:
        context = build_rag_context([Exercise(id=1, name="push up")])

        assert "secondary_muscles" not in context
        assert "instructions" not in context

    def test_includes_secondary_muscles_when_present(self, exercises: list[Exercise]) -> None:
        context = build_rag_context(exercises)

        assert "secondary_muscles: triceps" in context

    def test_uses_target_not_misleading_raw_group(self) -> None:
        exercise = Exercise(1, "press", target="pectorals", muscle_group="triceps")
        assert "muscle_group: chest" in build_rag_context([exercise])


class TestAllowedExerciseIds:
    def test_collects_every_retrieved_id(self, exercises: list[Exercise]) -> None:
        assert allowed_exercise_ids(exercises) == {101, 102}

    def test_is_empty_when_nothing_was_retrieved(self) -> None:
        assert allowed_exercise_ids([]) == set()
