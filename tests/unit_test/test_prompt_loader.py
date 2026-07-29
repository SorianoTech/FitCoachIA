from pathlib import Path

import pytest

from fitcoach.infrastructure.prompts.prompt_loader import (
    PromptAssetNotFoundError,
    PromptLoader,
)


@pytest.fixture
def loader(tmp_path: Path) -> PromptLoader:
    prompts_root = tmp_path / "prompts"
    skills_root = tmp_path / "skills"
    (prompts_root / "interviewer").mkdir(parents=True)
    (skills_root / "interviewer").mkdir(parents=True)
    (prompts_root / "interviewer" / "system_prompt.txt").write_text(
        "ROLE\n<skill>\n{{skill_content}}\n</skill>\n<rag_context>{{rag_context}}</rag_context>\n",
        encoding="utf-8",
    )
    (skills_root / "interviewer" / "SKILL.md").write_text(
        "# fitness-interviewer skill body", encoding="utf-8"
    )
    return PromptLoader(prompts_root=prompts_root, skills_root=skills_root)


class TestPromptLoader:
    def test_load_assembled_system_prompt_injects_skill_and_keeps_rag_placeholder(
        self, loader: PromptLoader
    ) -> None:
        result = loader.load_assembled_system_prompt("interviewer")

        assert "{{skill_content}}" not in result
        assert "# fitness-interviewer skill body" in result
        assert "{{rag_context}}" in result

    def test_load_assembled_system_prompt_raises_when_system_prompt_missing(
        self, tmp_path: Path
    ) -> None:
        skills_root = tmp_path / "skills"
        (skills_root / "ghost").mkdir(parents=True)
        (skills_root / "ghost" / "SKILL.md").write_text("skill", encoding="utf-8")
        loader = PromptLoader(prompts_root=tmp_path / "prompts", skills_root=skills_root)

        with pytest.raises(PromptAssetNotFoundError):
            loader.load_assembled_system_prompt("ghost")

    def test_load_assembled_system_prompt_raises_when_skill_missing(self, tmp_path: Path) -> None:
        prompts_root = tmp_path / "prompts"
        (prompts_root / "ghost").mkdir(parents=True)
        (prompts_root / "ghost" / "system_prompt.txt").write_text("x", encoding="utf-8")
        loader = PromptLoader(prompts_root=prompts_root, skills_root=tmp_path / "skills")

        with pytest.raises(PromptAssetNotFoundError):
            loader.load_assembled_system_prompt("ghost")
