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
    def test_loads_consultation_without_a_skill(self, tmp_path: Path) -> None:
        prompts = tmp_path / "prompts" / "trainer"
        prompts.mkdir(parents=True)
        (prompts / "answer_prompt.txt").write_text("read-only", encoding="utf-8")
        loader = PromptLoader(prompts_root=prompts.parent, skills_root=tmp_path / "missing")

        assert loader.load_system_prompt("trainer", "answer_prompt.txt") == "read-only"

    def test_default_roots_load_the_interviewer_prompt_and_skill(self) -> None:
        result = PromptLoader().load_assembled_system_prompt("interviewer")

        assert "{{skill_content}}" not in result
        assert "fitness-interviewer" in result
        assert "rag_context" not in result

    @pytest.mark.parametrize("skill_name", ["interviewer", "interviewer-dev"])
    def test_interviewer_variants_share_contract_without_rag(self, skill_name: str) -> None:
        loader = PromptLoader()
        result = loader.load_assembled_system_prompt("interviewer", skill_name)
        skill = loader.load_skill(skill_name)

        assert "selected interviewer skill" in result
        assert "COLLECTED DATA STRUCTURE:" in result
        assert "PER MUSCLE GROUP" in result
        assert "rag_context" not in result
        assert "RAG" not in result
        assert '"status":' not in skill
        assert "Collected Data Structure:" not in skill
        if skill_name == "interviewer-dev":
            assert "use `10`" in skill
            assert "development interview" in skill
            assert "name: interviewer-dev\n" in skill
            assert "perder grasa, ganar masa muscular o mejorar tu rendimiento físico" in skill
            assert "never internal enum values or field names" in skill
            assert "`lose_fat`" not in skill
            assert "`gain_muscle`" not in skill
            assert "`performance`" not in skill

    @pytest.mark.parametrize("skill_name", ["trainer", "trainer-dev"])
    def test_trainer_volume_is_per_target_not_full_body(self, skill_name: str) -> None:
        result = PromptLoader().load_assembled_system_prompt("trainer", skill_name)

        assert "PER MUSCLE GROUP" in result
        assert "full-body" in result
        assert "separately for each" in result
        assert "{{rag_context}}" in result

    def test_trainer_contract_lives_in_the_prompt_not_the_skill(self) -> None:
        loader = PromptLoader()
        prompt = loader.load_assembled_system_prompt("trainer")
        skill = (loader._skills_root / "trainer" / "SKILL.md").read_text(encoding="utf-8")

        assert "PLAN STRUCTURE:" in prompt
        assert '"exercise_id": 1234' in prompt
        assert "Plan Structure" not in skill
        assert '"exercise_id": 1234' not in skill

    def test_load_assembled_system_prompt_injects_skill_and_keeps_rag_placeholder(
        self, loader: PromptLoader
    ) -> None:
        result = loader.load_assembled_system_prompt("interviewer")

        assert "{{skill_content}}" not in result
        assert "# fitness-interviewer skill body" in result
        assert "{{rag_context}}" in result

    def test_load_assembled_system_prompt_can_select_a_skill_variant(
        self, loader: PromptLoader, tmp_path: Path
    ) -> None:
        dev_skills = tmp_path / "skills" / "interviewer-dev"
        dev_skills.mkdir(parents=True)
        (dev_skills / "SKILL.md").write_text("# short development skill", encoding="utf-8")
        loader = PromptLoader(prompts_root=loader._prompts_root, skills_root=tmp_path / "skills")

        result = loader.load_assembled_system_prompt("interviewer", "interviewer-dev")

        assert "# short development skill" in result
        assert "# fitness-interviewer skill body" not in result

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
