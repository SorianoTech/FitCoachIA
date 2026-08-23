"""Composes the Interviewer agent's system prompt (skill injected) from disk."""

from fitcoach.domain.agents import InterviewerAgent
from fitcoach.infrastructure.prompts.prompt_loader import PromptLoader


def build_interviewer_agent(loader: PromptLoader | None = None) -> InterviewerAgent:
    loader = loader or PromptLoader()
    system_prompt = loader.load_assembled_system_prompt("interviewer")
    return InterviewerAgent(system_prompt)
