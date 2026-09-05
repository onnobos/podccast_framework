# Podcast Framework Plugin Guide

This framework allows you to build multiple distinct podcasts on top of a single unified engine.

## Directory Structure

Each plugin lives in its own folder inside `plugins/<show_slug>/`:

```
plugins/
  └── <your_podcast_slug>/
      ├── __init__.py
      ├── plugin.py              # Subclass of PodcastPlugin (Required)
      ├── ingester.py            # Subclass of BaseIngester (Required)
      ├── prompts/               # Custom Markdown prompt templates (Optional)
      │   ├── curator_system.md
      │   ├── hosts.md
      │   ├── script_generator_system.md
      │   ├── script_verifier_system.md
      │   └── article_summary.md
      └── assets/                # Audio stingers, cover art, music (Optional)
          ├── cover_art.jpg
          └── music/
              ├── intro.mp3
              └── outro.mp3
```

## Creating a New Podcast Plugin

### 1. Create `plugin.py`

```python
from pathlib import Path
from typing import Dict
from src.framework.base_plugin import PodcastPlugin
from src.framework.base_ingester import BaseIngester
from src.framework.models import (
    ShowMetadata,
    HostConfig,
    AudioThemeConfig,
    CloudDistributionConfig,
    ScriptConfig,
    IngestionResult
)

class MyCustomPodcast(PodcastPlugin):
    @property
    def name(self) -> str:
        return "My Custom Tech Podcast"

    @property
    def slug(self) -> str:
        return "tech_podcast"

    @property
    def show_metadata(self) -> ShowMetadata:
        return ShowMetadata(
            title="Silicon Tactical",
            author="Studio Media",
            email="podcast@example.com",
            description="Deep tactical breakdowns of tech companies and engineering.",
            category="Technology",
            subcategory="Tech News"
        )

    @property
    def hosts(self) -> Dict[str, HostConfig]:
        return {
            "HOST_A": HostConfig(name="Alex", role="Host", voice="alloy"),
            "HOST_B": HostConfig(name="Jordan", role="Analyst", voice="echo")
        }

    @property
    def audio_theme(self) -> AudioThemeConfig:
        return AudioThemeConfig(
            target_lufs=-16.0,
            duck_gain_db=-16.0
        )

    @property
    def distribution(self) -> CloudDistributionConfig:
        return CloudDistributionConfig(
            feed_key="tech_feed.xml"
        )

    def validate_script(self, script_text: str) -> list[str]:
        issues = super().validate_script(script_text)
        # Add custom validation rules
        if "forbidden_word" in script_text.lower():
            issues.append("Found forbidden word in dialogue.")
        return issues

    def get_ingester(self) -> BaseIngester:
        return MyIngester()
```

### 2. Ingester (`ingester.py`)

```python
from src.framework.base_ingester import BaseIngester
from src.framework.models import IngestionResult

class MyIngester(BaseIngester):
    def get_slug(self, source: str) -> str:
        return source.strip("/").split("/")[-1]

    def ingest(self, source: str, **kwargs) -> IngestionResult:
        # Fetch markdown or raw article
        return IngestionResult(
            slug=self.get_slug(source),
            title="Episode Title",
            article_markdown="# Content...",
            video_urls=[]
        )
```

### 3. Custom Prompts (Optional)

Place any customized Markdown prompt files in `plugins/<your_podcast_slug>/prompts/`:
- `curator_system.md`: Domain-specific analysis and chapter extraction.
- `hosts.md`: Host dynamic profiles and vocal lenses.
- `script_generator_system.md`: Writing style, tone, and pacing instructions.
- `script_verifier_system.md`: Audit rubric and terminology checks.
- `article_summary.md`: RSS episode summary instructions.

If a prompt file is omitted, the engine automatically falls back to the default prompt in root `prompts/`.

### 4. Verify & Test Your Plugin

Run the framework test suite to ensure your plugin adheres to all contracts:
```bash
python -m unittest tests/test_framework.py
```

### 5. Usage via CLI

List installed plugins:
```bash
python main.py plugins
```

Generate an episode using your plugin:
```bash
python main.py generate "https://example.com/article" --plugin tech_podcast
```

