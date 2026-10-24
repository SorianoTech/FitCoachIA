"""Reads system_prompt.txt + SKILL.md pairs and assembles them per agent."""

from pathlib import Path


class PromptAssetNotFoundError(FileNotFoundError):
    """Raised when a system_prompt.txt or SKILL.md file is missing for an agent asset."""


class PromptLoader:
    def __init__(
        self,
        prompts_root: Path | None = None,
        skills_root: Path | None = None,
    ) -> None:
        package_root = Path(__file__).resolve().parent
        self._prompts_root = prompts_root or package_root
        self._skills_root = skills_root or package_root.parent / "ia" / "skills"

    def load_assembled_system_prompt(
        self, asset_name: str = "", skill_name: str | None = None
    ) -> str:
        """Return the agent's system prompt with its skill injected.

        ``{{rag_context}}`` is left untouched: it is filled per request, not at load time.
        """

        template = self.load_system_prompt(asset_name)
        skill_asset = skill_name or asset_name
        skill = self.load_skill(skill_asset)

        return template.replace("{{skill_content}}", skill)

    def load_system_prompt(self, asset_name: str, file_name: str = "system_prompt.txt") -> str:
        """Load a prompt without injecting a generation skill."""
        return self._read(self._prompts_root / asset_name / file_name, asset_name)

    def load_skill(self, skill_name: str) -> str:
        """Return one skill asset exactly as stored, for assembly and trace hashing."""
        return self._read(self._skills_root / skill_name / "SKILL.md", skill_name)

    def _read(self, path: Path, asset_name: str) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise PromptAssetNotFoundError(
                f"Missing asset file for agent '{asset_name}': {path}"
            ) from exc
