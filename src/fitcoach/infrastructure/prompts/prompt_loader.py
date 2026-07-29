"""Reads system_prompt.txt + SKILL.md pairs and assembles them per agent."""

from pathlib import Path

_SKILL_CONTENT_PLACEHOLDER = "{{skill_content}}"

_PROMPTS_ROOT = Path(__file__).parent
_SKILLS_ROOT = Path(__file__).parent.parent / "ia" / "skills"


class PromptAssetNotFoundError(FileNotFoundError):
    """Raised when a system_prompt.txt or SKILL.md file is missing for an agent asset."""


class PromptLoader:
    def __init__(
        self,
        prompts_root: Path = _PROMPTS_ROOT,
        skills_root: Path = _SKILLS_ROOT,
    ) -> None:
        self._prompts_root = prompts_root
        self._skills_root = skills_root

    def load_assembled_system_prompt(self, asset_name: str) -> str:
        """Return the agent's system prompt with its skill injected.

        ``{{rag_context}}`` is left untouched: it is filled per request, not at load time.
        """
        template = self._read(self._prompts_root / asset_name / "system_prompt.txt", asset_name)
        skill = self._read(self._skills_root / asset_name / "SKILL.md", asset_name)
        return template.replace(_SKILL_CONTENT_PLACEHOLDER, skill)

    def _read(self, path: Path, asset_name: str) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise PromptAssetNotFoundError(
                f"Missing asset file for agent '{asset_name}': {path}"
            ) from exc
