"""Composes each agent's system prompt (skill injected) from disk."""

from fitcoach.domain.agents import ExerciseCuratorAgent, InterviewerAgent, TrainerAgent
from fitcoach.infrastructure.prompts.prompt_loader import PromptLoader


def build_interviewer_agent(
    loader: PromptLoader | None = None, skill_name: str = "interviewer"
) -> InterviewerAgent:
    loader = loader or PromptLoader()
    system_prompt = loader.load_assembled_system_prompt("interviewer", skill_name)
    return InterviewerAgent(system_prompt)


def build_trainer_agent(
    loader: PromptLoader | None = None, skill_name: str = "trainer"
) -> TrainerAgent:
    loader = loader or PromptLoader()
    system_prompt = loader.load_assembled_system_prompt("trainer", skill_name)
    return TrainerAgent(system_prompt)


def build_exercise_curator_agent(
    loader: PromptLoader | None = None,
) -> ExerciseCuratorAgent:
    loader = loader or PromptLoader()
    return ExerciseCuratorAgent(loader.load_system_prompt("exercise_curator"))
