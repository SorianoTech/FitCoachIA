from unittest.mock import MagicMock

import pytest

from fitcoach.domain.agents import InterviewerAgent
from fitcoach.infrastructure.prompts.prompt_loader import PromptAssetNotFoundError, PromptLoader
from fitcoach.service.agent.agent_factory import build_interviewer_agent


@pytest.fixture
def loader() -> MagicMock:
    return MagicMock(spec=PromptLoader)


class TestBuildInterviewerAgent:
    def test_builds_interviewer_agent_from_the_loaded_prompt(self, loader: MagicMock) -> None:
        loader.load_assembled_system_prompt.return_value = "assembled prompt {{rag_context}}"

        agent = build_interviewer_agent(loader=loader)

        assert isinstance(agent, InterviewerAgent)
        assert agent.system_prompt == "assembled prompt {{rag_context}}"
        loader.load_assembled_system_prompt.assert_called_once_with("interviewer")

    def test_propagates_the_loader_error_when_assets_are_missing(self, loader: MagicMock) -> None:
        loader.load_assembled_system_prompt.side_effect = PromptAssetNotFoundError("missing asset")

        with pytest.raises(PromptAssetNotFoundError):
            build_interviewer_agent(loader=loader)
