"""
Abstract Base Plugin for Podcast Shows
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional

from src.framework.models import (
    ShowMetadata,
    HostConfig,
    AudioThemeConfig,
    CloudDistributionConfig,
    ScriptConfig,
)
from src.framework.base_ingester import BaseIngester


class PodcastPlugin(ABC):
    """
    Abstract Base Class for podcast show plugins.
    Every show (Volleyball, Tech, Business, History, etc.) implements this class.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable show plugin name (e.g. 'Volleyball Coaching Uncovered')."""
        pass

    @property
    @abstractmethod
    def slug(self) -> str:
        """Filesystem and CLI identifier (e.g. 'volleyball')."""
        pass

    @property
    @abstractmethod
    def show_metadata(self) -> ShowMetadata:
        """Show RSS metadata (title, author, categories, cover art)."""
        pass

    @property
    @abstractmethod
    def hosts(self) -> Dict[str, HostConfig]:
        """Hosts definition keyed by identifier (e.g. 'HOST_A', 'HOST_B')."""
        pass

    @property
    @abstractmethod
    def audio_theme(self) -> AudioThemeConfig:
        """Audio theme configuration (music files, ducking, LUFS)."""
        pass

    @property
    @abstractmethod
    def distribution(self) -> CloudDistributionConfig:
        """R2/S3 distribution credentials and endpoints."""
        pass

    @property
    def script_config(self) -> ScriptConfig:
        """Scriptwriting models, targets, and banned phrases."""
        return ScriptConfig()

    @abstractmethod
    def get_ingester(self) -> BaseIngester:
        """Return the ingester used by this plugin."""
        pass

    @property
    def plugin_dir(self) -> Path:
        """Root directory for this plugin's assets and code."""
        import inspect
        return Path(inspect.getfile(self.__class__)).resolve().parent

    @property
    def prompts_dir(self) -> Path:
        """Directory containing plugin prompt markdown files."""
        custom_prompts = self.plugin_dir / "prompts"
        if custom_prompts.exists():
            return custom_prompts
        return Path("prompts")

    def get_prompt(self, filename: str, default: str = "") -> str:
        """Load a prompt template from this plugin's prompts directory."""
        prompt_file = self.prompts_dir / filename
        if prompt_file.exists():
            content = prompt_file.read_text(encoding="utf-8").strip()
            if content:
                lines = content.splitlines()
                if lines and lines[0].startswith("# "):
                    content = "\n".join(lines[1:]).strip()
                return content
        return default

    @property
    def memory_path(self) -> Path:
        """Path to this show plugin's accumulated knowledge memory markdown file."""
        return self.plugin_dir / "MEMORY.md"

    def get_memory(self) -> str:
        """Load the show's cumulative MEMORY.md content if it exists."""
        if self.memory_path.exists():
            return self.memory_path.read_text(encoding="utf-8").strip()
        return ""

    def save_memory(self, content: str) -> Path:
        """Write content to this show plugin's MEMORY.md."""
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        self.memory_path.write_text(content.strip() + "\n", encoding="utf-8")
        return self.memory_path

    def validate_script(self, script_text: str) -> List[str]:
        """
        Run plugin-specific script validation rules.
        Returns a list of warning or error messages (empty if valid).
        """
        issues = []
        # Check banned phrases
        for phrase in self.script_config.banned_phrases:
            if phrase.lower() in script_text.lower():
                issues.append(f"Contains banned phrase: '{phrase}'")
        return issues
