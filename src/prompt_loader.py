from pathlib import Path
from typing import Optional

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

def load_prompt(filename: str, default: str = "", plugin=None) -> str:
    """Load prompt markdown file from plugin prompts/ or root prompts/ directory with fallback to default string."""
    # Check plugin-specific prompts if available
    if plugin is not None and hasattr(plugin, "prompts_dir"):
        candidate = plugin.prompts_dir / filename
        if candidate.exists():
            content = candidate.read_text(encoding="utf-8").strip()
            if content:
                lines = content.splitlines()
                if lines and lines[0].startswith("# "):
                    content = "\n".join(lines[1:]).strip()
                return content

    prompt_file = PROMPTS_DIR / filename
    if prompt_file.exists():
        content = prompt_file.read_text(encoding="utf-8").strip()
        if content:
            # Strip leading markdown H1 if followed by empty line (e.g. # Title\n\n)
            lines = content.splitlines()
            if lines and lines[0].startswith("# "):
                content = "\n".join(lines[1:]).strip()
            return content
    return default

