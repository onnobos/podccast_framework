"""
Podcast Framework Core Data Models
"""
from pathlib import Path
from typing import Optional, List, Dict
from pydantic import BaseModel, Field


class HostConfig(BaseModel):
    """Configuration for a podcast host."""
    name: str
    role: str
    voice: str
    description: str = ""
    mic_position: str = "left"  # 'left' for Host A, 'right' for Host B


class AudioThemeConfig(BaseModel):
    """Audio theme, sound design, and loudness configuration."""
    intro_music_path: Optional[Path] = None
    outro_music_path: Optional[Path] = None
    intro_solo_ms: int = 7500
    intro_duck_ms: int = 30000
    outro_duck_ms: int = 5000
    outro_solo_ms: int = 2000
    duck_gain_db: float = -16.0
    target_lufs: float = -16.0
    room_tone_dbfs: float = -56.0
    enable_room_tone: bool = True
    enable_mic_bleed: bool = True


class ShowMetadata(BaseModel):
    """Metadata for podcast show RSS distribution."""
    title: str
    author: str
    email: str
    description: str
    language: str = "en"
    category: str = "Sports"
    subcategory: str = "Volleyball"
    cover_art_path: Optional[Path] = None
    explicit: bool = False
    public_domain: Optional[str] = None


class CloudDistributionConfig(BaseModel):
    """S3/Cloudflare R2 storage credentials and endpoints."""
    account_id: str = ""
    access_key_id: str = ""
    secret_access_key: str = ""
    bucket_name: str = ""
    public_domain: str = ""
    feed_key: str = "feed.xml"
    audio_prefix: str = ""


class ScriptConfig(BaseModel):
    """LLM model orchestration and script length targets."""
    curator_model: str = "google/gemini-2.5-pro"
    script_model: str = "anthropic/claude-sonnet-4"
    audit_model: str = "google/gemini-2.5-flash"
    tts_model: str = "openai/gpt-audio"
    target_duration_min: int = 25
    target_clip_ratio: float = 0.40  # 40% coach/expert voice target
    banned_phrases: List[str] = Field(default_factory=lambda: [
        "incredible", "this is huge", "that is huge", "the fact that",
        "fascinating", "game-changer", "insane", "unbelievable",
        "mind-blowing", "super interesting", "at the end of the day"
    ])


class IngestionResult(BaseModel):
    """Standardized output from an ingestion source."""
    slug: str
    title: str
    article_markdown: str
    video_urls: List[str] = Field(default_factory=list)
    metadata: Dict[str, str] = Field(default_factory=dict)
