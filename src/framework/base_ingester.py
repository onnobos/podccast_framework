"""
Abstract Base Ingester for Podcast Content Sources
"""
from abc import ABC, abstractmethod
from typing import Optional
from src.framework.models import IngestionResult


class BaseIngester(ABC):
    """Abstract base class for extracting source content (URL, text, PDF, video channel)."""

    @abstractmethod
    def ingest(self, source: str, **kwargs) -> IngestionResult:
        """
        Extract content from source and return structured IngestionResult.
        
        Args:
            source: URL, file path, or raw identifier.
        """
        pass

    @abstractmethod
    def get_slug(self, source: str) -> str:
        """Extract or generate a filesystem-safe slug from the source input."""
        pass
