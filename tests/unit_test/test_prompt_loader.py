from pathlib import Path

import pytest

from fitcoach.domain.constants import Constants
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


_PROMPTS_ROOT = PromptLoader()._prompts_root
# renewal_prompt.txt is appended to trainer/system_prompt.txt, which already carries the rule.
_STANDALONE_PROMPTS = sorted(
    path for path in _PROMPTS_ROOT.rglob("*.txt") if path.name != "renewal_prompt.txt"
)


class TestLanguagePolicy:
    @pytest.mark.parametrize(
        "path", _STANDALONE_PROMPTS, ids=lambda path: path.parent.name + "/" + path.name
    )
    def test_every_prompt_forces_spanish(self, path: Path) -> None:
        prompt = path.read_text(encoding="utf-8")

        assert "LANGUAGE (MANDATORY)" in prompt
        assert "ALWAYS in Spanish" in prompt
        assert 'never "intervista"' in prompt

    @pytest.mark.parametrize(
        "path", _STANDALONE_PROMPTS, ids=lambda path: path.parent.name + "/" + path.name
    )
    def test_no_prompt_follows_the_user_language(self, path: Path) -> None:
        prompt = path.read_text(encoding="utf-8")

        assert "user's language" not in prompt
        assert "default to Spanish" not in prompt.replace("\n", " ")

    def test_interview_seed_message_is_spanish(self) -> None:
        assert "entrevista" in Constants.INTERVIEW_SEED_MESSAGE
        assert "interview" not in Constants.INTERVIEW_SEED_MESSAGE.lower()

    def test_renewal_inherits_the_rule_from_the_trainer_prompt(self) -> None:
        assert "ALWAYS in Spanish" in PromptLoader().load_assembled_system_prompt("trainer")

    @pytest.mark.parametrize("skill_name", ["interviewer", "interviewer-dev"])
    def test_interviewer_skills_do_not_reintroduce_user_language(self, skill_name: str) -> None:
        assert "user's language" not in PromptLoader().load_skill(skill_name)


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
        assert "name: interviewer\n" in result
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

    def test_trainer_prompt_uses_placeholders_and_states_evaluated_limits(self) -> None:
        loader = PromptLoader()
        prompt = loader.load_assembled_system_prompt("trainer")
        skill = (loader._skills_root / "trainer" / "SKILL.md").read_text(encoding="utf-8")

        assert "1234" not in prompt
        assert '"focus": "Empuje"' in prompt
        assert "`reply` at most 600 characters" in prompt
        assert "`report` at most 3500 characters" in prompt
        assert "SELF-CHECK" in prompt
        assert "Σ(sets × (40 + rest_seconds))" in skill

    def test_answer_prompt_routes_intents_and_documents_swap_selection(self) -> None:
        prompt = PromptLoader().load_system_prompt("trainer", "answer_prompt.txt")

        assert "# INTENT ROUTING" in prompt
        assert (
            '"week": 1-4 or null, "exercise_id": integer or null, "reason": string or null'
            in prompt
        )
        assert "hypothetical" in prompt
        assert "at most 1200 characters" in prompt
        assert '"intent":"<answer|exercise_swap|renewal>"' in prompt
        assert '"swap_selection":<object or null>' in prompt
        assert '"intent":"answer","swap_selection":null' not in prompt

    def test_skills_carry_no_dead_or_noise_sections(self) -> None:
        skills_root = PromptLoader()._skills_root
        trainer = (skills_root / "trainer" / "SKILL.md").read_text(encoding="utf-8")
        interviewer = (skills_root / "interviewer" / "SKILL.md").read_text(encoding="utf-8")

        assert "Answering follow-up questions" not in trainer
        for noise in ("Keywords and Triggers", "Continuous Improvement", "When to use this skill"):
            assert noise not in interviewer
            assert noise not in trainer

    def test_interviewer_prompt_and_skill_close_the_open_contract_gaps(self) -> None:
        loader = PromptLoader()
        prompt = loader.load_system_prompt("interviewer")
        skill = (loader._skills_root / "interviewer" / "SKILL.md").read_text(encoding="utf-8")

        assert "translated into Spanish" in prompt
        assert "CURRENT DATETIME" in prompt
        assert "in the same turn as the answer to the last step" in prompt
        assert "always ask them in Spanish" in skill
        assert "`timeframe_weeks`" in skill
        assert "`realistic_expectation`" in skill
        assert "dizzy or faint" in skill
        assert "Signs of distress" in skill
        assert "testosterone" not in skill

    def test_trainer_skill_examples_are_spanish_and_session_size_is_defined(self) -> None:
        skill = (PromptLoader()._skills_root / "trainer" / "SKILL.md").read_text(encoding="utf-8")

        assert "knee: excluded" not in skill
        assert "rodilla: excluidos" in skill
        assert "usually 4-7" in skill
        assert "lighter day" in skill

    def test_dev_skills_keep_core_data_user_provided_and_align_with_the_evaluator(self) -> None:
        skills_root = PromptLoader()._skills_root
        trainer = (skills_root / "trainer-dev" / "SKILL.md").read_text(encoding="utf-8")
        interviewer = (skills_root / "interviewer-dev" / "SKILL.md").read_text(encoding="utf-8")

        assert "Follow-up questions" not in trainer
        assert "`goal.primary` | Reps" in trainer
        assert "chest, back and legs" in trainer
        assert "round(0.55 × its week 1 sets)" in trainer
        assert "never from defaults" in interviewer
        assert "not assessed (development test)" in interviewer
        assert "Mifflin-St" in interviewer
        assert "BMI below 13.5" in interviewer

    def test_interviewer_calculations_are_fixed_and_no_elimination_diets(self) -> None:
        loader = PromptLoader()
        prompt = loader.load_assembled_system_prompt("interviewer")
        skill = (loader._skills_root / "interviewer" / "SKILL.md").read_text(encoding="utf-8")

        assert "Mifflin-St Jeor" in skill
        assert "NEAT base" in skill
        assert "gluten elimination" not in skill
        assert "never\n  suggest elimination diets" in skill
        assert "ONE skill step per message" in prompt
        assert "those two sections win" in prompt

    def test_trainer_contract_lives_in_the_prompt_not_the_skill(self) -> None:
        loader = PromptLoader()
        prompt = loader.load_assembled_system_prompt("trainer")
        skill = (loader._skills_root / "trainer" / "SKILL.md").read_text(encoding="utf-8")

        assert "PLAN STRUCTURE:" in prompt
        assert '"exercise_id": "<id copiado de rag_context>"' in prompt
        assert "Plan Structure" not in skill
        assert "<id copiado de rag_context>" not in skill

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
