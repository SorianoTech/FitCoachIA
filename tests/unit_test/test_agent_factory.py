from unittest.mock import MagicMock

import pytest

from fitcoach.domain.agents import InterviewerAgent, TrainerAgent
from fitcoach.infrastructure.prompts.prompt_loader import PromptAssetNotFoundError, PromptLoader
from fitcoach.service.agent.agent_factory import build_interviewer_agent, build_trainer_agent


@pytest.fixture
def loader() -> MagicMock:
    return MagicMock(spec=PromptLoader)


class TestBuildInterviewerAgent:
    def test_builds_interviewer_agent_from_the_loaded_prompt(self, loader: MagicMock) -> None:
        loader.load_assembled_system_prompt.return_value = "assembled prompt {{rag_context}}"

        agent = build_interviewer_agent(loader=loader)

        assert isinstance(agent, InterviewerAgent)
        assert agent.system_prompt == "assembled prompt {{rag_context}}"
        loader.load_assembled_system_prompt.assert_called_once_with("interviewer", "interviewer")

    def test_propagates_the_loader_error_when_assets_are_missing(self, loader: MagicMock) -> None:
        loader.load_assembled_system_prompt.side_effect = PromptAssetNotFoundError("missing asset")

        with pytest.raises(PromptAssetNotFoundError):
            build_interviewer_agent(loader=loader)


class TestBuildTrainerAgent:
    def test_builds_trainer_agent_from_the_loaded_prompt(self, loader: MagicMock) -> None:
        loader.load_assembled_system_prompt.return_value = "trainer prompt {{rag_context}}"

        agent = build_trainer_agent(loader=loader)

        assert isinstance(agent, TrainerAgent)
        assert agent.system_prompt == "trainer prompt {{rag_context}}"
        loader.load_assembled_system_prompt.assert_called_once_with("trainer", "trainer")

    def test_uses_the_configured_skill_variant(self, loader: MagicMock) -> None:
        loader.load_assembled_system_prompt.return_value = "trainer prompt"

        build_trainer_agent(loader=loader, skill_name="trainer-dev")

        loader.load_assembled_system_prompt.assert_called_once_with("trainer", "trainer-dev")

    def test_propagates_the_loader_error_when_assets_are_missing(self, loader: MagicMock) -> None:
        loader.load_assembled_system_prompt.side_effect = PromptAssetNotFoundError("missing asset")

        with pytest.raises(PromptAssetNotFoundError):
            build_trainer_agent(loader=loader)


class TestRealPromptAssets:
    """El prompt y la skill del entrenador existen en disco y encajan."""

    def test_assembles_the_real_trainer_prompt_with_its_skill(self) -> None:
        agent = build_trainer_agent()

        assert "{{skill_content}}" not in agent.system_prompt
        assert "fitness-trainer" in agent.system_prompt
        # El hueco de RAG sigue sin resolver: se rellena en cada peticion.
        assert "{{rag_context}}" in agent.system_prompt

    def test_assembles_the_dev_trainer_skill_variant(self) -> None:
        agent = build_trainer_agent(skill_name="trainer-dev")

        assert "fitness-trainer-dev" in agent.system_prompt
        assert "{{skill_content}}" not in agent.system_prompt
