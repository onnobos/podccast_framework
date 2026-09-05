"""
Podcast Framework Core Package
"""
from src.framework.models import (
    HostConfig,
    AudioThemeConfig,
    ShowMetadata,
    CloudDistributionConfig,
    ScriptConfig,
    IngestionResult,
)
from src.framework.base_ingester import BaseIngester
from src.framework.base_plugin import PodcastPlugin
from src.framework.registry import registry, get_active_plugin

__all__ = [
    "HostConfig",
    "AudioThemeConfig",
    "ShowMetadata",
    "CloudDistributionConfig",
    "ScriptConfig",
    "IngestionResult",
    "BaseIngester",
    "PodcastPlugin",
    "registry",
    "get_active_plugin",
]
