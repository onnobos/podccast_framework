"""
VolleyBrains Masterclass Ingester
"""
from pathlib import Path
from src.framework.base_ingester import BaseIngester
from src.framework.models import IngestionResult
from src.scraper import scrape_article, get_url_slug


class VolleyBrainsIngester(BaseIngester):
    """Ingester for VolleyBrains authenticated masterclass articles & YouTube embeds."""

    def get_slug(self, source: str) -> str:
        return get_url_slug(source)

    def ingest(self, source: str, force_scrape: bool = False, **kwargs) -> IngestionResult:
        slug = self.get_slug(source)
        scraped_path = scrape_article(source, force_scrape=force_scrape)

        article_md = scraped_path.read_text(encoding="utf-8")
        title = slug.replace("-", " ").replace("_", " ").title()
        for line in article_md.splitlines():
            if line.startswith("# "):
                title = line.replace("# ", "").strip()
                break

        return IngestionResult(
            slug=slug,
            title=title,
            article_markdown=article_md,
            video_urls=[],
            metadata={"source_url": source, "scraped_path": str(scraped_path)}
        )
