"""
Volleyball Masterclass Podcast Plugin
"""
from pathlib import Path
from typing import Dict, List, Optional

from src.framework.base_plugin import PodcastPlugin
from src.framework.base_ingester import BaseIngester
from src.framework.models import (
    ShowMetadata,
    HostConfig,
    AudioThemeConfig,
    CloudDistributionConfig,
    ScriptConfig,
)
from src.config import settings
from plugins.volleyball.ingester import VolleyBrainsIngester


class VolleyballPodcastPlugin(PodcastPlugin):
    """Flagship plugin: Volleyball Coaching Uncovered 2-Host Audio Masterclass."""

    @property
    def name(self) -> str:
        return "Volleyball Coaching Uncovered"

    @property
    def slug(self) -> str:
        return "volleyball"

    @property
    def show_metadata(self) -> ShowMetadata:
        cover_art = None
        for candidate in [
            Path("assets/images/cover_art.jpg"),
            Path("assets/images/cover_art.png"),
            Path("assets/cover_art.jpg"),
            Path("assets/cover_art.png"),
        ]:
            if candidate.exists():
                cover_art = candidate
                break

        return ShowMetadata(
            title="Volleyball Coaching Uncovered",
            author="Volleyball Coaching Uncovered",
            email="ebook53-podcast@yahoo.com",
            description="Transforming rich volleyball masterclasses into high-retention 2-host audio podcast episodes for volleyball coaches.",
            language="en",
            category="Sports",
            subcategory="Volleyball",
            cover_art_path=cover_art,
            explicit=False,
            public_domain=settings.clean_r2_public_domain if hasattr(settings, "clean_r2_public_domain") else None,
        )

    @property
    def hosts(self) -> Dict[str, HostConfig]:
        return {
            "HOST_A": HostConfig(
                name="Chloe Miller",
                role="European Pro / NCAA D1 Bench Realist",
                voice=settings.HOST_A_VOICE or "shimmer",
                description="Conversational lead. Asks clarifying questions, focuses on locker room realities, accountability, and drill mechanics.",
                mic_position="left",
            ),
            "HOST_B": HostConfig(
                name="Davis Hayes",
                role="Broadcast Analyst",
                voice=settings.HOST_B_VOICE or "ash",
                description="Tactical specialist. Focuses on macro-psychology, sideline body language, opponent classification, and timeout pacing.",
                mic_position="right",
            ),
        }

    @property
    def audio_theme(self) -> AudioThemeConfig:
        intro_music = None
        outro_music = None

        intro_candidates = list(Path("music").glob("*intro*.mp3")) or list(Path("assets/music").glob("*intro*.mp3"))
        if intro_candidates:
            intro_music = intro_candidates[0]

        outro_candidates = list(Path("music").glob("*outro*.mp3")) or list(Path("assets/music").glob("*outro*.mp3"))
        if outro_candidates:
            outro_music = outro_candidates[0]

        return AudioThemeConfig(
            intro_music_path=intro_music,
            outro_music_path=outro_music,
            intro_solo_ms=7500,
            intro_duck_ms=30000,
            outro_duck_ms=5000,
            outro_solo_ms=2000,
            duck_gain_db=-16.0,
            target_lufs=-16.0,
            room_tone_dbfs=-56.0,
            enable_room_tone=True,
            enable_mic_bleed=True,
        )

    @property
    def distribution(self) -> CloudDistributionConfig:
        return CloudDistributionConfig(
            account_id=getattr(settings, "clean_r2_account_id", ""),
            access_key_id=getattr(settings, "R2_ACCESS_KEY_ID", ""),
            secret_access_key=getattr(settings, "R2_SECRET_ACCESS_KEY", ""),
            bucket_name=getattr(settings, "R2_BUCKET_NAME", ""),
            public_domain=getattr(settings, "clean_r2_public_domain", ""),
            feed_key="feed.xml",
            audio_prefix="",
        )

    @property
    def script_config(self) -> ScriptConfig:
        return ScriptConfig(
            curator_model=getattr(settings, "CURATOR_MODEL", "google/gemini-2.5-pro"),
            script_model=getattr(settings, "SCRIPT_MODEL", "anthropic/claude-sonnet-4"),
            audit_model=getattr(settings, "AUDIT_MODEL", "google/gemini-2.5-flash"),
            tts_model=getattr(settings, "TTS_MODEL", "openai/gpt-audio"),
            target_duration_min=25,
            target_clip_ratio=0.40,
            banned_phrases=[
                "incredible", "this is huge", "that is huge", "the fact that",
                "fascinating", "game-changer", "insane", "unbelievable",
                "mind-blowing", "super interesting", "at the end of the day",
                "volleybrains", "volleybrains.com"
            ],
        )

    @property
    def prompts_dir(self) -> Path:
        # Check plugin-local prompts first, then root prompts
        local_prompts = self.plugin_dir / "prompts"
        if local_prompts.exists():
            return local_prompts
        return Path("prompts")

    def get_ingester(self) -> BaseIngester:
        return VolleyBrainsIngester()

    def validate_script(self, script_text: str) -> List[str]:
        issues = super().validate_script(script_text)
        # Volleyball specific validation: brand neutrality
        if "volleybrains" in script_text.lower():
            issues.append("Violation of brand neutrality: 'VolleyBrains' found in script dialogue.")
        return issues
